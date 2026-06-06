"""Tests for E1.5: universal tool-call gate + ForcePauseAlerter + DialogueDelayMonitor
lifecycle wiring.

Test 1 (gate_blocks_invoke): An operator message in the inbox causes invoke() to return
the block_message without spawning a subprocess.

Test 2 (force_pause_blocks_invoke): A force-paused alerter causes invoke() to short-circuit
without spawning a subprocess.

Test 3 (gate_allows_when_empty): An empty inbox lets invoke() reach subprocess spawn
(subprocess mock is invoked).

Test 4 (alerter_sets_pause_flag): DiscordForcePauseAlerter.alert() sets paused=True and
calls notify_fn.

Test 5 (alerter_clear_pause): DiscordForcePauseAlerter.clear_pause() resets paused to False.

Test 6 (monitor_started_on_create_session): set_dialogue_delay_monitor wires monitor;
create_session calls monitor.start().

Test 7 (monitor_stopped_on_expire_session): _expire_session calls monitor.stop().

Test 8 (config_defaults): BridgeConfig defaults for interrupt flags are correct.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio

from bridge.claude_runner import ClaudeRunner, DiscordForcePauseAlerter
from bridge.config import BridgeConfig
from bridge.database import Database
from bridge.operator_inbox import MessageSeverity, OperatorInbox
from bridge.session_manager import SessionManager


# ---------------------------------------------------------------------------
# Minimal config helper
# ---------------------------------------------------------------------------


def make_config(tmp_path: Path, **overrides) -> BridgeConfig:
    """Build a minimal BridgeConfig pointing at tmp_path dirs."""
    data_dir = tmp_path / "data"
    log_dir = tmp_path / "logs"
    data_dir.mkdir(exist_ok=True)
    log_dir.mkdir(exist_ok=True)
    defaults = dict(
        discord_bot_token="fake-token",
        operator_discord_id="12345",
        data_dir=str(data_dir),
        log_dir=str(log_dir),
        claude_working_dir=str(tmp_path),
        claude_timeout=120,
        claude_hard_timeout=600,
        claude_absolute_timeout=1800,
        claude_max_turns=25,
        claude_output_format="stream-json",
        session_idle_timeout=1800,
        session_max_file_size=31457280,
        session_max_errors=3,
        session_max_messages=1000,
        session_max_duration=86400,
        heartbeat_interval=60,
        rate_limit_multiplier=2.0,
        rate_limit_jitter=0.5,
    )
    defaults.update(overrides)
    return BridgeConfig(**defaults)


# ---------------------------------------------------------------------------
# Test 1: gate blocks invoke when inbox has pending message
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_gate_blocks_invoke(tmp_path):
    """If a pending QUESTION message is in the inbox, invoke() returns block_message
    without touching the subprocess.
    """
    config = make_config(tmp_path, universal_tool_gate_enabled=True)
    runner = ClaudeRunner(config)

    inbox = OperatorInbox(session_id="test-session")
    await inbox.receive("Are you sure you want to proceed?", MessageSeverity.QUESTION)
    runner.set_operator_inbox(inbox)

    # subprocess should NOT be spawned; patch it to verify it's never called
    with patch("asyncio.create_subprocess_exec") as mock_spawn:
        result = await runner.invoke("do some work", session_id="test-session")

    # Gate should have blocked
    mock_spawn.assert_not_called()
    assert result.is_error is False
    assert "BLOCKED" in result.response_text or "QUESTION" in result.response_text


# ---------------------------------------------------------------------------
# Test 2: force_pause blocks invoke
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_force_pause_blocks_invoke(tmp_path):
    """If force_pause_alerter.paused is True, invoke() short-circuits before spawning."""
    config = make_config(tmp_path)
    runner = ClaudeRunner(config)

    alerter = DiscordForcePauseAlerter()
    # Manually trigger the pause flag (as DialogueDelayMonitor would)
    alerter._paused = True
    runner.set_force_pause_alerter(alerter)

    with patch("asyncio.create_subprocess_exec") as mock_spawn:
        result = await runner.invoke("do some work", session_id="test-session")

    mock_spawn.assert_not_called()
    assert result.is_error is False
    assert "BLOCKED" in result.response_text or "force-pause" in result.response_text.lower()


# ---------------------------------------------------------------------------
# Test 3: gate allows when inbox is empty
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_gate_allows_when_empty(tmp_path):
    """An empty inbox passes the gate, so invoke() reaches subprocess spawn."""
    config = make_config(tmp_path, universal_tool_gate_enabled=True)
    runner = ClaudeRunner(config)

    inbox = OperatorInbox(session_id="test-session")
    # No messages — inbox is empty
    runner.set_operator_inbox(inbox)

    # Use fake binary to avoid real subprocess; it will fail at spawn level
    # but the important assertion is that create_subprocess_exec WAS called.
    with patch("asyncio.create_subprocess_exec") as mock_spawn:
        # Make the mock raise so we don't need a real claude binary
        mock_spawn.side_effect = FileNotFoundError("no claude binary in test")
        result = await runner.invoke("do some work", session_id="test-session")

    # Spawn was attempted (gate allowed it)
    mock_spawn.assert_called_once()
    assert result.is_error is True


# ---------------------------------------------------------------------------
# Test 4: DiscordForcePauseAlerter.alert() sets paused + calls notify_fn
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_alerter_sets_pause_flag():
    """DiscordForcePauseAlerter.alert() sets paused=True and invokes notify_fn."""
    notify_calls = []

    async def fake_notify(msg: str) -> None:
        notify_calls.append(msg)

    alerter = DiscordForcePauseAlerter(notify_fn=fake_notify)
    assert alerter.paused is False

    from bridge.operator_inbox import OperatorMessage, MessageSeverity
    from datetime import datetime, timezone

    pending = [
        OperatorMessage(
            id="msg_1000_1",
            content="Are you sure?",
            severity=MessageSeverity.QUESTION,
            received_at=datetime.now(timezone.utc),
        )
    ]
    await alerter.alert(pending)

    assert alerter.paused is True
    assert len(notify_calls) == 1
    assert "force-pause" in notify_calls[0].lower() or "FORCE-PAUSE" in notify_calls[0]


# ---------------------------------------------------------------------------
# Test 5: DiscordForcePauseAlerter.clear_pause() resets paused
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_alerter_clear_pause():
    """DiscordForcePauseAlerter.clear_pause() resets the paused flag."""
    alerter = DiscordForcePauseAlerter()
    alerter._paused = True
    assert alerter.paused is True

    alerter.clear_pause()
    assert alerter.paused is False


# ---------------------------------------------------------------------------
# Test 6: monitor started on create_session
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def migrated_db_for_session(tmp_path):
    db_path = tmp_path / "test.db"
    db = Database(db_path)
    await db.connect()
    await db.migrate()
    yield db
    await db.close()


@pytest.mark.asyncio
async def test_monitor_started_on_create_session(tmp_path, migrated_db_for_session):
    """set_dialogue_delay_monitor wires monitor; create_session calls monitor.start()."""
    config = make_config(tmp_path)
    sm = SessionManager(migrated_db_for_session, config)

    mock_monitor = MagicMock()
    mock_monitor.start = AsyncMock()
    mock_monitor.stop = AsyncMock()

    sm.set_dialogue_delay_monitor(mock_monitor)

    session_id = await sm.create_session(chat_id="chat-001")

    assert session_id is not None
    mock_monitor.start.assert_awaited_once()


# ---------------------------------------------------------------------------
# Test 7: monitor stopped on _expire_session
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_monitor_stopped_on_expire_session(tmp_path, migrated_db_for_session):
    """_expire_session calls monitor.stop()."""
    config = make_config(tmp_path)
    sm = SessionManager(migrated_db_for_session, config)

    mock_monitor = MagicMock()
    mock_monitor.start = AsyncMock()
    mock_monitor.stop = AsyncMock()

    sm.set_dialogue_delay_monitor(mock_monitor)

    # Create a session so we have a real session DB row
    session_id = await sm.create_session(chat_id="chat-002")

    # Find the session_db_id
    row = await migrated_db_for_session.fetchone(
        "SELECT id FROM sessions WHERE claude_session_id = ?", (session_id,)
    )
    session_db_id = row[0]

    # Expire it
    await sm._expire_session(session_db_id, reason="test")

    mock_monitor.stop.assert_awaited_once()


# ---------------------------------------------------------------------------
# Test 8: BridgeConfig defaults for interrupt flags
# ---------------------------------------------------------------------------


def test_config_interrupt_defaults(tmp_path):
    """BridgeConfig defaults: universal_tool_gate_enabled=True, thresholds correct."""
    config = make_config(tmp_path)
    assert config.universal_tool_gate_enabled is True
    assert config.dialogue_delay_threshold_seconds == 60
    assert config.force_pause_threshold_seconds == 300
    assert config.interrupts_poll_interval_seconds == 10


# ---------------------------------------------------------------------------
# Test 9: gate disabled by flag — bypass even with pending messages
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_gate_disabled_bypasses_gate(tmp_path):
    """When universal_tool_gate_enabled=False, pending messages don't block invoke()."""
    config = make_config(tmp_path, universal_tool_gate_enabled=False)
    runner = ClaudeRunner(config)

    inbox = OperatorInbox(session_id="test-session")
    await inbox.receive("HALT the pipeline", MessageSeverity.HALT)
    runner.set_operator_inbox(inbox)

    with patch("asyncio.create_subprocess_exec") as mock_spawn:
        mock_spawn.side_effect = FileNotFoundError("no claude binary in test")
        result = await runner.invoke("do some work", session_id="test-session")

    # Gate was disabled so spawn was attempted
    mock_spawn.assert_called_once()
    assert result.is_error is True  # FileNotFoundError → spawn_error
