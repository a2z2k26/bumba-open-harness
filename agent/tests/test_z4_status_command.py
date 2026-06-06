"""Tests for /z4 status Discord command (sprint E-O.2).

Verifies that _cmd_z4_status returns a formatted summary of all registered
Zone 4 departments including circuit state and cost.
"""
from __future__ import annotations

import unittest.mock as mock

import pytest

from bridge.commands import CommandHandler


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_registry():
    """Mock DepartmentRegistry with board, qa, ops departments."""
    registry = mock.MagicMock()
    registry.department_names.return_value = ["board", "ops", "qa"]

    def get_config(name):
        cfg = mock.MagicMock()
        cfg.zone = 4
        cfg.employees = [mock.MagicMock() for _ in range(3)]
        cfg.vapi = mock.MagicMock()
        cfg.vapi.enabled = False
        return cfg

    registry.get_config.side_effect = get_config
    return registry


@pytest.fixture
def mock_circuit_registry():
    """Mock CircuitBreakerRegistry — all circuits closed."""
    reg = mock.MagicMock()

    def get(name):
        breaker = mock.MagicMock()
        breaker.state.value = "closed"
        return breaker

    reg.get.side_effect = get
    return reg


@pytest.fixture
def handler(mock_registry, mock_circuit_registry):
    """CommandHandler with departments and circuit registry wired."""
    h = CommandHandler.__new__(CommandHandler)
    h._departments = mock_registry
    h._circuit_registry = mock_circuit_registry
    h._metrics_aggregator = None
    h._cost_tracker = None
    return h


@pytest.fixture
def handler_no_registry():
    """CommandHandler with no departments wired."""
    h = CommandHandler.__new__(CommandHandler)
    h._departments = None
    return h


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestZ4StatusCommand:
    @pytest.mark.asyncio
    async def test_returns_error_when_no_registry(self, handler_no_registry):
        """Test 1: Returns informative message when departments not wired."""
        result = await handler_no_registry._cmd_z4_status("chat1", "")
        assert "not wired" in result.lower() or "Zone 4" in result

    @pytest.mark.asyncio
    async def test_lists_all_departments(self, handler, mock_registry):
        """Test 2: Output contains all registered department names."""
        result = await handler._cmd_z4_status("chat1", "")
        assert "board" in result
        assert "ops" in result
        assert "qa" in result

    @pytest.mark.asyncio
    async def test_shows_zone4_status_header(self, handler):
        """Test 3: Output includes Zone 4 Status header."""
        result = await handler._cmd_z4_status("chat1", "")
        assert "Zone 4" in result

    @pytest.mark.asyncio
    async def test_shows_circuit_state(self, handler):
        """Test 4: Output includes circuit state for each department."""
        result = await handler._cmd_z4_status("chat1", "")
        assert "closed" in result

    @pytest.mark.asyncio
    async def test_shows_cost_info(self, handler):
        """Test 5: Output includes cost ($) for each department."""
        result = await handler._cmd_z4_status("chat1", "")
        assert "$" in result

    @pytest.mark.asyncio
    async def test_shows_runs_count(self, handler):
        """Test 6: Output includes runs= field for each department."""
        result = await handler._cmd_z4_status("chat1", "")
        assert "runs=" in result

    @pytest.mark.asyncio
    async def test_shows_daily_total_when_cost_tracker_available(self, mock_registry, mock_circuit_registry):
        """Test 7: Daily total line appears when cost_tracker is available."""
        h = CommandHandler.__new__(CommandHandler)
        h._departments = mock_registry
        h._circuit_registry = mock_circuit_registry
        h._metrics_aggregator = None
        mock_tracker = mock.MagicMock()
        mock_tracker.daily_summary.return_value = {
            "total_usd": 1.50,
            "daily_limit_usd": 25.0,
        }
        h._cost_tracker = mock_tracker

        result = await h._cmd_z4_status("chat1", "")
        assert "Daily total" in result
        assert "1.50" in result

    @pytest.mark.asyncio
    async def test_shows_open_circuit(self, mock_registry):
        """Test 8: OPEN circuit state is surfaced in the output."""
        h = CommandHandler.__new__(CommandHandler)
        h._departments = mock_registry
        h._metrics_aggregator = None
        h._cost_tracker = None

        reg = mock.MagicMock()

        def get(name):
            breaker = mock.MagicMock()
            breaker.state.value = "open" if name == "ops" else "closed"
            return breaker

        reg.get.side_effect = get
        h._circuit_registry = reg

        result = await h._cmd_z4_status("chat1", "")
        assert "open" in result

    @pytest.mark.asyncio
    async def test_no_registry_returns_sentinel_message(self, handler_no_registry):
        """Test 9: Returns sentinel message when departments not wired."""
        result = await handler_no_registry._cmd_z4_status("chat1", "")
        assert "Zone 4" in result or "department" in result.lower()

    @pytest.mark.asyncio
    async def test_z4_status_in_bridge_commands(self):
        """Test 10: z4_status is registered in BRIDGE_COMMANDS."""
        from bridge.commands import BRIDGE_COMMANDS
        assert "z4_status" in BRIDGE_COMMANDS

    @pytest.mark.asyncio
    async def test_metrics_aggregator_enriches_cost(self, mock_registry, mock_circuit_registry):
        """Test 11: MetricsAggregator data is reflected in per-dept cost."""
        h = CommandHandler.__new__(CommandHandler)
        h._departments = mock_registry
        h._circuit_registry = mock_circuit_registry
        h._cost_tracker = None

        aggregator = mock.MagicMock()
        util = mock.MagicMock()
        util.agent_name = "qa-chief"
        util.total_usd = 0.42
        util.session_count = 3
        aggregator.agent_utilization.return_value = [util]
        h._metrics_aggregator = aggregator

        result = await h._cmd_z4_status("chat1", "")
        # qa dept cost should include 0.42
        assert "0.42" in result
