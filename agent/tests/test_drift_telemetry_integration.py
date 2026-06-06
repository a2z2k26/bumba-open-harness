"""Integration tests for drift_telemetry session-end producer (Sprint 07.12).

Wires SessionManager._expire_session to drift_telemetry.record_metrics
behind the drift_telemetry_enabled config flag. These tests cover:

- Flag on: end_session writes one MetricsRecord JSONL line.
- All seven MetricsRecord fields are populated (numeric, not None).
- Flag off: no JSONL file is written.
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path

import pytest

from bridge.config import BridgeConfig
from bridge.database import Database
from bridge.drift_telemetry import METRIC_FIELDS
from bridge.session_manager import SessionManager


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_config(
    *,
    data_dir: Path,
    drift_enabled: bool,
    metrics_filename: str = "bridge-metrics.jsonl",
) -> BridgeConfig:
    """Build a minimal BridgeConfig override with telemetry knobs set.

    We can't pass the real loader path because validation requires a
    Discord token. ``dataclasses.replace`` on a default-constructed
    config is the smallest viable override surface for unit tests that
    only exercise SessionManager.
    """
    return dataclasses.replace(
        BridgeConfig(),
        data_dir=str(data_dir),
        drift_telemetry_enabled=drift_enabled,
        bridge_metrics_path=metrics_filename,
    )


async def _make_session_manager(
    tmp_path: Path,
    *,
    drift_enabled: bool,
) -> tuple[SessionManager, Database, BridgeConfig]:
    """Spin up a SessionManager backed by a real migrated SQLite DB."""
    db_path = tmp_path / "test.db"
    db = Database(db_path)
    await db.connect()
    await db.migrate()
    cfg = _make_config(data_dir=tmp_path, drift_enabled=drift_enabled)
    return SessionManager(db, cfg), db, cfg


async def _seed_session_with_messages(
    sm: SessionManager,
    db: Database,
    chat_id: str,
) -> str:
    """Create a session and insert 4 conversations rows: user → assistant
    pair, then a second user → assistant pair with a tool call.

    Returns the claude_session_id.
    """
    session_id = await sm.create_session(chat_id)
    # Backfill four conversations for richer metric coverage.
    rows = [
        ("user", "hello", None),
        ("assistant", "hi back", "Read"),
        ("user", "run the tests", None),
        ("assistant", "all green", "Bash(pytest),Read"),
    ]
    for role, content, tools_used in rows:
        await db.execute(
            """INSERT INTO conversations
               (session_id, chat_id, role, content, tools_used)
               VALUES (?, ?, ?, ?, ?)""",
            (session_id, chat_id, role, content, tools_used),
        )
    # Bump message_count to match.
    await db.execute(
        """UPDATE sessions
           SET message_count = ?,
               last_active_at = datetime('now', '+5 minutes')
           WHERE claude_session_id = ?""",
        (len(rows), session_id),
    )
    await db.commit()
    return session_id


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_session_end_writes_metrics_record(tmp_path: Path) -> None:
    """Flag on: ending a session must append exactly one JSONL record."""
    sm, db, cfg = await _make_session_manager(tmp_path, drift_enabled=True)
    try:
        session_id = await _seed_session_with_messages(sm, db, "chat-1")

        await sm.force_expire("chat-1")
        # force_expire bypasses _expire_session — call the hot path directly
        # via expire_with_summary which does invoke _expire_session.
        # Re-create a session and use expire_with_summary to take that path:
        session_id_2 = await sm.create_session("chat-2")
        # Seed at least one conversation row so duration computes deterministically.
        await db.execute(
            """INSERT INTO conversations
               (session_id, chat_id, role, content, tools_used)
               VALUES (?, ?, ?, ?, ?)""",
            (session_id_2, "chat-2", "user", "ping", None),
        )
        await db.execute(
            """UPDATE sessions
               SET message_count = 1,
                   last_active_at = datetime('now', '+1 minutes')
               WHERE claude_session_id = ?""",
            (session_id_2,),
        )
        await db.commit()

        await sm.expire_with_summary(
            "chat-2", session_id_2, "idle_timeout", None
        )

        metrics_path = tmp_path / cfg.bridge_metrics_path
        assert metrics_path.exists(), (
            "drift_telemetry should have created the JSONL file"
        )
        lines = [
            line for line in metrics_path.read_text().splitlines() if line
        ]
        assert len(lines) == 1, f"expected 1 record, got {len(lines)}"
        obj = json.loads(lines[0])
        assert obj["session_id"] == session_id_2
        # The first session was force-expired; only the second hit the
        # _expire_session telemetry hook.
        assert session_id != session_id_2
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_all_seven_fields_populated(tmp_path: Path) -> None:
    """Every MetricsRecord field must be present and numeric."""
    sm, db, cfg = await _make_session_manager(tmp_path, drift_enabled=True)
    try:
        session_id = await _seed_session_with_messages(sm, db, "chat-1")
        await sm.expire_with_summary(
            "chat-1", session_id, "idle_timeout", None
        )

        metrics_path = tmp_path / cfg.bridge_metrics_path
        obj = json.loads(metrics_path.read_text().splitlines()[0])

        for field_name in METRIC_FIELDS:
            assert field_name in obj, f"missing field: {field_name}"
            value = obj[field_name]
            assert value is not None, f"{field_name} is None"
            assert isinstance(value, (int, float)), (
                f"{field_name} is not numeric: {type(value).__name__}"
            )

        # Spot-check that derivations actually fired (vs all zeros).
        # The seeded session has 4 messages and ~5 minutes of duration,
        # so velocity should be > 0.
        assert obj["velocity"] > 0.0
        # Two user messages, two assistant — engagement ratio = 1.0
        # (clamped). bundling_indicator = (1+2)/4 = 0.75.
        assert obj["engagement_indicator"] == pytest.approx(1.0)
        assert obj["bundling_indicator"] == pytest.approx(0.75)
        # One Bash(pytest) call — counts as a test-runner tool.
        assert obj["test_frequency"] >= 1.0
        # honesty_indicator falls back to the documented default 0.5.
        assert obj["honesty_indicator"] == pytest.approx(0.5)
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_flag_off_no_writes(tmp_path: Path) -> None:
    """Flag off: end_session must not create the metrics file."""
    sm, db, cfg = await _make_session_manager(tmp_path, drift_enabled=False)
    try:
        session_id = await _seed_session_with_messages(sm, db, "chat-1")
        await sm.expire_with_summary(
            "chat-1", session_id, "idle_timeout", None
        )

        metrics_path = tmp_path / cfg.bridge_metrics_path
        assert not metrics_path.exists(), (
            "drift_telemetry must NOT write when flag is off"
        )
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_telemetry_failure_does_not_break_teardown(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A drift_telemetry exception must be swallowed and logged, not raised."""
    sm, db, cfg = await _make_session_manager(tmp_path, drift_enabled=True)
    try:
        session_id = await _seed_session_with_messages(sm, db, "chat-1")

        def explode(*_args: object, **_kwargs: object) -> None:
            raise RuntimeError("simulated disk failure")

        monkeypatch.setattr(
            "bridge.session_manager.record_metrics", explode
        )

        # expire_with_summary must complete cleanly.
        await sm.expire_with_summary(
            "chat-1", session_id, "idle_timeout", None
        )

        # Session is still expired in the DB.
        row = await db.fetchone(
            "SELECT status FROM sessions WHERE claude_session_id = ?",
            (session_id,),
        )
        assert row is not None
        assert row[0] == "expired"
    finally:
        await db.close()
