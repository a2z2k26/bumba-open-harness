"""Integration tests for the full pipeline (S85-S88)."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio

from bridge.app import BridgeApp
from bridge.claude_runner import ClaudeResult


@pytest_asyncio.fixture
async def integrated_app(sample_config_toml, mock_keyring):
    """A fully wired BridgeApp with mocked Discord and Claude."""
    app = BridgeApp(config_path=str(sample_config_toml))
    await app._initialize()

    # Mock Discord
    app._discord._start_typing = MagicMock()
    app._discord._stop_typing = MagicMock()
    app._discord.send_message = AsyncMock()
    app._discord.send_alert = AsyncMock()

    # Mock security log_event (keep check_anomalies real)
    original_log = app._security.log_event
    app._security.log_event = AsyncMock(side_effect=original_log)

    yield app

    if app._db:
        await app._db.close()


def _make_result(**kwargs) -> ClaudeResult:
    """Factory for ClaudeResult."""
    defaults = {
        "response_text": "Test response from Claude",
        "session_id": "sess-integration-123",
        "cost_usd": 0.02,
        "num_turns": 2,
        "tools_used": ["Read"],
        "is_error": False,
        "error_type": "",
        "duration_ms": 2000,
        "exit_code": 0,
        "stderr_output": "",
    }
    defaults.update(kwargs)
    return ClaudeResult(**defaults)


class TestEndToEndMocked:
    """S85: Full pipeline with mocked Claude and Discord."""

    @pytest.mark.asyncio
    async def test_message_arrives_claude_invoked_response_sent(self, integrated_app):
        app = integrated_app
        result = _make_result()
        app._claude.invoke = AsyncMock(return_value=result)

        # Simulate message arrival
        await app._handle_new_message("chat-1", "What is Python?", 100)

        # Process the queued message
        msg = await app._queue.dequeue()
        assert msg is not None
        assert msg.text == "What is Python?"

        await app._process_single_message(msg)

        # Claude was invoked
        app._claude.invoke.assert_called_once()

        # Response was sent via Discord
        send_calls = app._discord.send_message.call_args_list
        response_sent = any("Test response from Claude" in str(c) for c in send_calls)
        assert response_sent

        # DB updated: conversations should have user + assistant messages
        rows = await app._db.fetchall(
            "SELECT role, content FROM conversations ORDER BY id"
        )
        assert len(rows) >= 2
        assert rows[-2][0] == "user"
        assert rows[-1][0] == "assistant"

        # Audit logged
        app._security.log_event.assert_called()

    @pytest.mark.asyncio
    async def test_queue_fifo_processing(self, integrated_app):
        app = integrated_app
        result = _make_result()
        app._claude.invoke = AsyncMock(return_value=result)

        # Enqueue 3 messages
        for i in range(3):
            await app._handle_new_message("chat-1", f"Message {i}", 100 + i)

        # Verify queue has 3 pending
        status = await app._queue.get_queue_status()
        assert status["counts"].get("pending", 0) == 3

        # Process in order
        for i in range(3):
            msg = await app._queue.dequeue()
            assert msg is not None
            assert msg.text == f"Message {i}"
            await app._process_single_message(msg)

        # All completed
        status = await app._queue.get_queue_status()
        assert status["counts"].get("completed", 0) == 3
        assert status["counts"].get("pending", 0) == 0

    @pytest.mark.asyncio
    async def test_queue_position_acknowledgment(self, integrated_app):
        app = integrated_app

        # First message from chat-1: no position ack (position 1)
        await app._handle_new_message("chat-1", "First", 100)

        # Second message from chat-2: should get position 2 ack
        await app._handle_new_message("chat-2", "Second", 101)

        # Check that position message was sent for chat-2
        send_calls = app._discord.send_message.call_args_list
        position_msgs = [c for c in send_calls if "position" in str(c).lower()]
        assert len(position_msgs) >= 1


class TestErrorScenarios:
    """S86: Error handling through full pipeline."""

    @pytest.mark.asyncio
    async def test_timeout_retry_flow(self, integrated_app):
        app = integrated_app
        error_result = _make_result(
            is_error=True, error_type="unknown",
            response_text="", exit_code=1,
        )
        app._claude.invoke = AsyncMock(return_value=error_result)

        await app._queue.enqueue(100, "chat-1", "test timeout")
        msg = await app._queue.dequeue()
        assert msg is not None

        await app._process_single_message(msg)

        # Message should be retried (back to pending) since attempt_count < max_retries
        status = await app._queue.get_queue_status()
        assert status["counts"].get("pending", 0) >= 1

    @pytest.mark.asyncio
    async def test_auth_expiry_halts_agent(self, integrated_app):
        app = integrated_app
        error_result = _make_result(
            is_error=True, error_type="auth",
            stderr_output="auth token expired",
        )
        app._claude.invoke = AsyncMock(return_value=error_result)

        await app._queue.enqueue(100, "chat-1", "test auth")
        msg = await app._queue.dequeue()
        assert msg is not None

        await app._process_single_message(msg)

        assert app._halted is True
        assert app._security.is_halted()

    @pytest.mark.asyncio
    async def test_content_filter_fails_message(self, integrated_app):
        app = integrated_app
        error_result = _make_result(
            is_error=True, error_type="content_filter",
        )
        app._claude.invoke = AsyncMock(return_value=error_result)

        await app._queue.enqueue(100, "chat-1", "test content filter")
        msg = await app._queue.dequeue()
        assert msg is not None

        await app._process_single_message(msg)

        status = await app._queue.get_queue_status()
        assert status["counts"].get("failed", 0) >= 1

    @pytest.mark.asyncio
    async def test_max_turns_sends_partial(self, integrated_app):
        app = integrated_app
        error_result = _make_result(
            is_error=True, error_type="error_max_turns",
            response_text="Partial response so far...",
        )
        app._claude.invoke = AsyncMock(return_value=error_result)

        await app._queue.enqueue(100, "chat-1", "test max turns")
        msg = await app._queue.dequeue()
        assert msg is not None

        await app._process_single_message(msg)

        # Partial response should be sent
        send_calls = app._discord.send_message.call_args_list
        partial_sent = any("Partial response" in str(c) for c in send_calls)
        assert partial_sent


class TestSessionLifecycle:
    """S87: Session lifecycle through the pipeline."""

    @pytest.mark.asyncio
    async def test_session_creation_first_message(self, integrated_app):
        app = integrated_app
        result = _make_result()
        app._claude.invoke = AsyncMock(return_value=result)

        await app._queue.enqueue(100, "chat-1", "Hello!")
        msg = await app._queue.dequeue()
        await app._process_single_message(msg)

        # Session should exist
        stats = await app._session_mgr.get_session_stats()
        assert stats["total_sessions"] >= 1

    @pytest.mark.asyncio
    async def test_session_resume(self, integrated_app):
        app = integrated_app
        result = _make_result(session_id="sess-resume-1")
        app._claude.invoke = AsyncMock(return_value=result)

        # First message creates session
        await app._queue.enqueue(100, "chat-1", "Hello!")
        msg = await app._queue.dequeue()
        await app._process_single_message(msg)

        # Second message should resolve existing session
        result2 = _make_result(session_id="sess-resume-2")
        app._claude.invoke = AsyncMock(return_value=result2)

        await app._queue.enqueue(101, "chat-1", "Follow up")
        msg2 = await app._queue.dequeue()
        await app._process_single_message(msg2)

        # Should have conversations from both messages
        rows = await app._db.fetchall(
            "SELECT role FROM conversations WHERE chat_id = 'chat-1'"
        )
        assert len(rows) >= 4  # 2 user + 2 assistant

    @pytest.mark.asyncio
    async def test_context_injection(self, integrated_app):
        app = integrated_app
        result = _make_result()
        app._claude.invoke = AsyncMock(return_value=result)

        # Store some knowledge
        await app._memory.store_knowledge("project:name", "Bumba")

        # Process a message
        await app._queue.enqueue(100, "chat-1", "Tell me about the project")
        msg = await app._queue.dequeue()
        await app._process_single_message(msg)

        # Claude was invoked with a system_prompt_file argument
        call_kwargs = app._claude.invoke.call_args
        assert call_kwargs is not None
        # The context file path should have been passed
        assert "system_prompt_file" in str(call_kwargs)


class TestSecurityAudit:
    """S88: Security and audit integration."""

    @pytest.mark.asyncio
    async def test_audit_logs_message_exchange(self, integrated_app):
        app = integrated_app
        result = _make_result()
        app._claude.invoke = AsyncMock(return_value=result)

        await app._queue.enqueue(100, "chat-1", "Test audit")
        msg = await app._queue.dequeue()
        await app._process_single_message(msg)

        # Check audit log
        events = await app._security.get_recent_events(event_type="message_processed")
        assert len(events) >= 1

    @pytest.mark.asyncio
    async def test_audit_append_only(self, integrated_app, tmp_dirs):
        app = integrated_app

        # Log multiple events
        await app._security.log_event("event_1")
        await app._security.log_event("event_2")

        jsonl_path = tmp_dirs["log_dir"] / "audit.jsonl"
        lines = jsonl_path.read_text().strip().split("\n")
        assert len(lines) == 2

        # Verify both events exist (append-only)
        events = [json.loads(line) for line in lines]
        types = {e["event_type"] for e in events}
        assert "event_1" in types
        assert "event_2" in types

    @pytest.mark.asyncio
    async def test_halt_prevents_processing(self, integrated_app):
        app = integrated_app
        app._halted = True

        await app._handle_new_message("chat-1", "Should be rejected", 100)

        # Message should NOT be in queue
        status = await app._queue.get_queue_status()
        assert status["counts"].get("pending", 0) == 0

        # Should have sent "halted" notification
        app._discord.send_message.assert_called()

    @pytest.mark.asyncio
    async def test_command_logged_to_audit(self, integrated_app):
        app = integrated_app

        await app._handle_command("chat-1", "ping", "")

        # Verify the command was logged
        app._security.log_event.assert_called()
        call_args = app._security.log_event.call_args_list
        command_logged = any(
            c[1].get("event_type", c[0][0] if c[0] else "") == "command"
            for c in call_args
        )
        # The first positional arg should be "command"
        command_logged = any(
            len(c[0]) > 0 and c[0][0] == "command"
            for c in call_args
        )
        assert command_logged


class TestPhase3Imports:
    """Verify all Phase 3 modules import correctly."""

    def test_import_security(self):
        from bridge.security import SecurityManager
        assert SecurityManager is not None

    def test_import_app(self):
        from bridge.app import BridgeApp
        assert BridgeApp is not None

    def test_import_main(self):
        from bridge.__main__ import parse_args, setup_logging, main
        assert parse_args is not None
        assert setup_logging is not None
        assert main is not None

    def test_all_modules_importable(self):
        """Verify no circular imports across all bridge modules."""
        import bridge.config  # noqa: F811
        import bridge.database  # noqa: F811
        import bridge.formatting  # noqa: F811
        import bridge.claude_runner  # noqa: F811
        import bridge.message_queue  # noqa: F811
        import bridge.memory  # noqa: F811
        import bridge.session_manager  # noqa: F811
        import bridge.discord_bot  # noqa: F811
        import bridge.commands  # noqa: F811
        import bridge.security  # noqa: F811
        import bridge.app  # noqa: F811
        assert bridge.app is not None
