"""Tests for D7.8 — operator-visible signal on auto-compaction (#1420).

Two surfaces under test:

1. ``compaction_checkpoint.capture_checkpoint`` writes
   ``checkpoints/last_compaction.json`` with the operator-readable summary.

2. ``CommandHandler._cmd_compact_status`` reads the file and renders a
   friendly response (or "no compactions yet" when missing).
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from bridge.compaction_checkpoint import capture_checkpoint
from bridge.commands import CommandHandler


# ---------------------------------------------------------------------------
# capture_checkpoint — last_compaction.json side-effect
# ---------------------------------------------------------------------------

def test_capture_checkpoint_writes_last_compaction_summary(tmp_path: Path) -> None:
    """capture_checkpoint with checkpoint_dir → last_compaction.json appears."""
    capture_checkpoint(
        session_id="abc-def-1234",
        message_count=42,
        estimated_tokens=18_000,
        active_task_titles=["Sprint D7.8"],
        workflow_state={"hard_stop_pressure": 0.85},
        checkpoint_dir=str(tmp_path),
        active_sprint="D7.8",
        last_handoff_reason="auto-compact at 85%",
    )

    last_path = tmp_path / "last_compaction.json"
    assert last_path.exists()

    data = json.loads(last_path.read_text())
    assert data["session_id"] == "abc-def-1234"
    assert data["message_count_before"] == 42
    assert data["estimated_tokens_before"] == 18_000
    assert data["active_sprint"] == "D7.8"
    assert "Sprint D7.8" in data["active_tasks"]
    assert data["last_handoff_reason"] == "auto-compact at 85%"
    # ISO timestamp parses cleanly
    fired_at = datetime.fromisoformat(data["fired_at_utc"].replace("Z", "+00:00"))
    age = (datetime.now(timezone.utc) - fired_at).total_seconds()
    assert age < 60  # very recent


def test_capture_checkpoint_does_not_write_summary_without_checkpoint_dir(
    tmp_path: Path,
) -> None:
    """checkpoint_dir omitted → no last_compaction.json side-effect."""
    capture_checkpoint(
        session_id="no-dir",
        message_count=1,
        estimated_tokens=100,
        # checkpoint_dir intentionally empty
    )
    assert not (tmp_path / "last_compaction.json").exists()


# ---------------------------------------------------------------------------
# /compact-status — handler renders the file
# ---------------------------------------------------------------------------

def _make_handler_with_data_dir(data_dir: Path) -> CommandHandler:
    """Build a minimally-wired CommandHandler with a known data_dir."""
    db = MagicMock()
    queue = MagicMock()
    queue.get_queue_status = AsyncMock(return_value={"counts": {"pending": 0}})
    session_mgr = MagicMock()
    runner = MagicMock()
    runner.config = SimpleNamespace(data_dir=str(data_dir))
    return CommandHandler(db=db, queue=queue, session_manager=session_mgr, claude_runner=runner)


@pytest.mark.asyncio
async def test_compact_status_no_compactions_yet(tmp_path: Path) -> None:
    """Missing file → friendly 'no compactions yet' response."""
    handler = _make_handler_with_data_dir(tmp_path)
    out = await handler._cmd_compact_status("ch", "")
    assert "no compaction" in out.lower()


@pytest.mark.asyncio
async def test_compact_status_renders_recent_event(tmp_path: Path) -> None:
    """File present → rendered body contains the key fields."""
    cp_dir = tmp_path / "checkpoints"
    cp_dir.mkdir(parents=True)
    payload = {
        "session_id": "session-abcdef0123",
        "fired_at_utc": datetime.now(timezone.utc).isoformat(),
        "message_count_before": 87,
        "estimated_tokens_before": 25_000,
        "active_sprint": "D7.8",
        "active_tasks": ["compaction visibility"],
        "last_handoff_reason": "auto-compact pressure 0.78",
        "capsule_path": "/tmp/cap.json",
    }
    (cp_dir / "last_compaction.json").write_text(json.dumps(payload))

    handler = _make_handler_with_data_dir(tmp_path)
    out = await handler._cmd_compact_status("ch", "")

    assert "Last compaction" in out
    assert "session-abcd" in out  # session id truncated
    assert "87" in out
    assert "25,000" in out
    assert "D7.8" in out
    assert "auto-compact pressure 0.78" in out


@pytest.mark.asyncio
async def test_compact_status_handles_corrupt_json(tmp_path: Path) -> None:
    """Corrupt file → graceful error, no exception."""
    cp_dir = tmp_path / "checkpoints"
    cp_dir.mkdir(parents=True)
    (cp_dir / "last_compaction.json").write_text("not-json")

    handler = _make_handler_with_data_dir(tmp_path)
    out = await handler._cmd_compact_status("ch", "")

    assert "Could not read" in out


@pytest.mark.asyncio
async def test_compact_status_age_formats_for_seconds_minutes_hours(
    tmp_path: Path,
) -> None:
    """Age string format adapts to time-since-fire."""
    cp_dir = tmp_path / "checkpoints"
    cp_dir.mkdir(parents=True)

    # Fire 3 hours ago
    three_h_ago = datetime.now(timezone.utc).replace(microsecond=0)
    three_h_ago_iso = three_h_ago.isoformat()
    payload = {
        "session_id": "x",
        "fired_at_utc": three_h_ago_iso,
        "message_count_before": 0,
        "estimated_tokens_before": 0,
        "active_sprint": "",
        "active_tasks": [],
        "last_handoff_reason": "",
        "capsule_path": "",
    }
    # Move timestamp explicitly 3h into the past
    from datetime import timedelta
    payload["fired_at_utc"] = (
        datetime.now(timezone.utc) - timedelta(hours=3)
    ).isoformat()
    (cp_dir / "last_compaction.json").write_text(json.dumps(payload))

    handler = _make_handler_with_data_dir(tmp_path)
    out = await handler._cmd_compact_status("ch", "")

    # Should render an "h ago" suffix for the 3h delta
    assert "h ago" in out
