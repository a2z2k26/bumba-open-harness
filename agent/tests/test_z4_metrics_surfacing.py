"""Tests for Z4.15 — MetricsAggregator daily surfacing.

Covers:
1. Retro source function (_zone4_activity)
2. Command handler (_cmd_z4_metrics)
3. RetroService.set_metrics_aggregator wiring
"""

from __future__ import annotations

import asyncio
import sqlite3
import tempfile
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from bridge.services.retro import (
    RetroService,
    _SOURCES,
    _zone4_activity,
)
from bridge.observability.metrics_aggregator import (
    DailyCostEntry,
    AgentUtilization,
    MetricsAggregator,
)


# ── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture()
def tmp_dirs():
    with tempfile.TemporaryDirectory() as d:
        data_dir = Path(d) / "data"
        data_dir.mkdir()
        yield data_dir


@pytest.fixture()
def db_conn():
    """In-memory SQLite with retro-compatible schema."""
    conn = sqlite3.connect(":memory:")
    conn.executescript("""
        CREATE TABLE conversations (
            id INTEGER PRIMARY KEY,
            session_id TEXT,
            role TEXT,
            content TEXT,
            created_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE knowledge (
            id INTEGER PRIMARY KEY,
            key TEXT UNIQUE,
            value TEXT,
            archived INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE message_queue (
            id INTEGER PRIMARY KEY,
            status TEXT DEFAULT 'pending'
        );
        CREATE TABLE audit_log (
            id INTEGER PRIMARY KEY,
            event_type TEXT,
            timestamp TEXT DEFAULT (datetime('now'))
        );
    """)
    yield conn
    conn.close()


@pytest.fixture()
def mock_aggregator():
    """Mock MetricsAggregator with configurable return values."""
    agg = MagicMock(spec=MetricsAggregator)
    agg.daily_cost.return_value = []
    agg.agent_utilization.return_value = []
    return agg


@pytest.fixture(autouse=True)
def _reset_retro_metrics():
    """Reset module-level _metrics_aggregator before each test."""
    import bridge.services.retro as retro_mod
    original = retro_mod._metrics_aggregator
    yield
    retro_mod._metrics_aggregator = original


# ── Retro source registration ──────────────────────────────────────────────


class TestRetroSourceRegistration:
    """Verify the Zone 4 Activity source is registered in the right order."""

    def test_zone4_activity_is_registered(self):
        names = [name for name, _ in _SOURCES]
        assert "Zone 4 Activity" in names

    def test_zone4_activity_between_open_loops_and_tomorrow(self):
        names = [name for name, _ in _SOURCES]
        open_loops_idx = names.index("Open Loops")
        zone4_idx = names.index("Zone 4 Activity")
        tomorrow_idx = names.index("Tomorrow Preview")
        assert open_loops_idx < zone4_idx < tomorrow_idx


# ── Retro source function ──────────────────────────────────────────────────


class TestZone4ActivitySource:
    """Test the _zone4_activity retro source function."""

    def test_returns_none_when_no_aggregator(self, db_conn):
        """With no MetricsAggregator wired, returns None."""
        import bridge.services.retro as retro_mod
        retro_mod._metrics_aggregator = None
        result = _zone4_activity(db_conn)
        assert result is None

    def test_returns_no_activity_when_empty(self, db_conn, mock_aggregator):
        """When aggregator returns empty daily_cost, reports no activity."""
        import bridge.services.retro as retro_mod
        retro_mod._metrics_aggregator = mock_aggregator
        mock_aggregator.daily_cost.return_value = []

        result = _zone4_activity(db_conn)
        assert result is not None
        assert "No department activity today" in result

    def test_returns_summary_with_data(self, db_conn, mock_aggregator):
        """When daily_cost returns entries, shows session and cost summary."""
        import bridge.services.retro as retro_mod
        retro_mod._metrics_aggregator = mock_aggregator

        mock_aggregator.daily_cost.return_value = [
            DailyCostEntry(
                date=date.today().isoformat(),
                total_usd=0.0542,
                session_count=3,
                total_calls=47,
            )
        ]
        mock_aggregator.agent_utilization.return_value = [
            AgentUtilization(
                agent_name="qa-engineer",
                session_count=2,
                total_calls=30,
                total_usd=0.03,
            ),
            AgentUtilization(
                agent_name="backend-architect",
                session_count=1,
                total_calls=17,
                total_usd=0.0242,
            ),
        ]

        result = _zone4_activity(db_conn)
        assert result is not None
        assert "3 session(s)" in result
        assert "47 tool calls" in result
        assert "$0.0542" in result
        assert "qa-engineer" in result
        assert "backend-architect" in result

    def test_handles_aggregator_exception(self, db_conn, mock_aggregator):
        """If the aggregator raises, returns None without crashing."""
        import bridge.services.retro as retro_mod
        retro_mod._metrics_aggregator = mock_aggregator
        mock_aggregator.daily_cost.side_effect = RuntimeError("disk full")

        result = _zone4_activity(db_conn)
        assert result is None


# ── RetroService.set_metrics_aggregator ──────────────────────────────────


class TestRetroServiceSetMetricsAggregator:
    """Test the static setter for wiring the aggregator."""

    def test_sets_module_level_aggregator(self, mock_aggregator):
        import bridge.services.retro as retro_mod

        RetroService.set_metrics_aggregator(mock_aggregator)
        assert retro_mod._metrics_aggregator is mock_aggregator

    def test_set_none_clears_aggregator(self, mock_aggregator):
        import bridge.services.retro as retro_mod

        RetroService.set_metrics_aggregator(mock_aggregator)
        RetroService.set_metrics_aggregator(None)
        assert retro_mod._metrics_aggregator is None


# ── Command handler: z4_metrics ──────────────────────────────────────────


class TestZ4MetricsCommand:
    """Test the /z4-metrics command handler."""

    def _make_handler(self):
        """Create a minimal CommandHandler for testing."""
        from bridge.commands import CommandHandler

        db = MagicMock()
        queue = MagicMock()
        session_mgr = MagicMock()
        handler = CommandHandler(db, queue, session_mgr)
        return handler

    def test_returns_not_initialized_without_aggregator(self):
        handler = self._make_handler()
        result = asyncio.run(handler._cmd_z4_metrics("test-chat", ""))
        assert "not initialized" in result

    def test_returns_no_sessions_when_empty(self, mock_aggregator):
        handler = self._make_handler()
        handler.set_metrics_aggregator(mock_aggregator)
        mock_aggregator.daily_cost.return_value = []
        mock_aggregator.agent_utilization.return_value = []

        result = asyncio.run(handler._cmd_z4_metrics("test-chat", ""))
        assert "No department sessions" in result
        assert "7-Day Trend" in result

    def test_returns_trend_and_breakdown(self, mock_aggregator):
        handler = self._make_handler()
        handler.set_metrics_aggregator(mock_aggregator)

        today = date.today()
        yesterday = today - timedelta(days=1)

        mock_aggregator.daily_cost.return_value = [
            DailyCostEntry(
                date=yesterday.isoformat(),
                total_usd=0.12,
                session_count=5,
                total_calls=80,
            ),
            DailyCostEntry(
                date=today.isoformat(),
                total_usd=0.08,
                session_count=3,
                total_calls=45,
            ),
        ]
        mock_aggregator.agent_utilization.return_value = [
            AgentUtilization(
                agent_name="eng-chief",
                session_count=4,
                total_calls=60,
                total_usd=0.10,
            ),
            AgentUtilization(
                agent_name="qa-chief",
                session_count=3,
                total_calls=40,
                total_usd=0.06,
                blocked_calls=2,
            ),
        ]

        result = asyncio.run(handler._cmd_z4_metrics("test-chat", ""))

        # 7-day total
        assert "$0.2000" in result
        assert "8 sessions" in result
        assert "125 tool calls" in result

        # Daily entries
        assert yesterday.isoformat() in result
        assert today.isoformat() in result

        # Agent breakdown
        assert "eng-chief" in result
        assert "qa-chief" in result
        assert "2 blocked" in result

    def test_handles_exception_gracefully(self, mock_aggregator):
        handler = self._make_handler()
        handler.set_metrics_aggregator(mock_aggregator)
        mock_aggregator.daily_cost.side_effect = RuntimeError("oops")

        result = asyncio.run(handler._cmd_z4_metrics("test-chat", ""))
        assert "Zone 4 metrics error" in result


# ── BRIDGE_COMMANDS includes z4_metrics ──────────────────────────────────


class TestBridgeCommandsIncludesZ4Metrics:
    def test_z4_metrics_in_bridge_commands(self):
        from bridge.commands import BRIDGE_COMMANDS
        assert "z4_metrics" in BRIDGE_COMMANDS


# ── Runner wiring ──────────────────────────────────────────────────────────


class TestRunnerWiring:
    """Test that runner.py wires MetricsAggregator into retro service."""

    def test_wire_retro_metrics_skips_when_no_dir(self, tmp_dirs):
        """When z4-sessions dir doesn't exist, wiring is skipped."""
        from bridge.services.runner import _wire_retro_metrics

        svc = MagicMock()
        with patch("bridge.services.runner.DATA_DIR", tmp_dirs):
            _wire_retro_metrics(svc)

        # The module-level aggregator should remain unchanged
        import bridge.services.retro as retro_mod
        assert retro_mod._metrics_aggregator is None

    def test_wire_retro_metrics_activates_when_dir_exists(self, tmp_dirs):
        """When z4-sessions dir exists, wiring succeeds."""
        from bridge.services.runner import _wire_retro_metrics

        z4_dir = tmp_dirs / "z4-sessions"
        z4_dir.mkdir()

        svc = MagicMock()
        with patch("bridge.services.runner.DATA_DIR", tmp_dirs):
            _wire_retro_metrics(svc)

        import bridge.services.retro as retro_mod
        assert retro_mod._metrics_aggregator is not None
        assert isinstance(retro_mod._metrics_aggregator, MetricsAggregator)
