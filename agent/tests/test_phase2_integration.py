"""Phase 2 integration tests (S69-S70)."""

from __future__ import annotations


import pytest

from bridge.memory import Memory
from bridge.message_queue import MessageQueue
from bridge.session_manager import SessionManager


class TestHappyPath:
    """S69: Message flow happy path."""

    @pytest.mark.asyncio
    async def test_message_flow(self, migrated_db, sample_config, mock_claude_result):
        """Full pipeline: enqueue → dequeue → (mock) invoke → store → complete."""
        queue = MessageQueue(migrated_db)
        memory = Memory(migrated_db, sample_config)
        session_mgr = SessionManager(migrated_db, sample_config)

        # 1. New message arrives
        await queue.enqueue(100, "chat-1", "Hello Bumba")

        # 2. Resolve session (none exists → create new)
        session_id = await session_mgr.resolve_session("chat-1")
        assert session_id is None
        session_id = await session_mgr.create_session("chat-1")

        # 3. Dequeue
        msg = await queue.dequeue()
        assert msg.text == "Hello Bumba"

        # 4. Store user message
        await memory.store_message(session_id, "chat-1", "user", msg.text)

        # 5. Invoke Claude (mocked)
        result = mock_claude_result(response_text="Hello! I'm Bumba.", session_id=session_id)

        # 6. Store assistant response
        await memory.store_message(
            session_id, "chat-1", "assistant", result.response_text,
            cost_usd=result.cost_usd, duration_ms=result.duration_ms,
        )

        # 7. Update session stats
        await session_mgr.update_session(session_id, cost_usd=result.cost_usd)

        # 8. Complete queue item
        await queue.complete(msg.id)

        # Verify
        messages = await memory.get_recent_messages("chat-1")
        assert len(messages) == 2
        assert messages[0]["role"] == "user"
        assert messages[1]["role"] == "assistant"

        stats = await session_mgr.get_session_stats()
        assert stats["active_session"]["message_count"] == 1

    @pytest.mark.asyncio
    async def test_message_flow_with_resume(self, migrated_db, sample_config, mock_claude_result):
        """Second message should resolve existing session."""
        MessageQueue(migrated_db)
        memory = Memory(migrated_db, sample_config)
        session_mgr = SessionManager(migrated_db, sample_config)

        # First message
        session_id = await session_mgr.create_session("chat-1")
        await memory.store_message(session_id, "chat-1", "user", "Message 1")
        await session_mgr.update_session(session_id)

        # Second message
        resolved = await session_mgr.resolve_session("chat-1")
        assert resolved == session_id  # Should resume


class TestErrorFlows:
    """S70: Error flow tests."""

    @pytest.mark.asyncio
    async def test_session_expiry_creates_summary(self, migrated_db, sample_config):
        """Expired session should store summary."""
        session_mgr = SessionManager(migrated_db, sample_config)
        memory = Memory(migrated_db, sample_config)

        session_id = await session_mgr.create_session("chat-1")
        await memory.store_message(session_id, "chat-1", "user", "Discussed auth")
        await memory.store_message(session_id, "chat-1", "assistant", "Implemented JWT")

        await session_mgr.expire_with_summary(
            "chat-1", session_id, "idle_timeout",
            "- Discussed auth refactor\n- Implemented JWT",
        )

        # Summary should be in knowledge
        value = await memory.get_knowledge(f"session:summary:{session_id}")
        assert "JWT" in value

    @pytest.mark.asyncio
    async def test_queue_mixed_states(self, migrated_db, sample_config):
        """Queue should handle multiple statuses correctly."""
        queue = MessageQueue(migrated_db)

        # Add messages with different outcomes
        await queue.enqueue(1, "chat-1", "Success")
        await queue.enqueue(2, "chat-1", "Will fail")
        await queue.enqueue(3, "chat-1", "Rate limited")

        msg1 = await queue.dequeue()
        await queue.complete(msg1.id)

        msg2 = await queue.dequeue()
        await queue.fail(msg2.id, "timeout")

        await queue.rate_limit_all()  # msg3 → rate_limited

        status = await queue.get_queue_status()
        assert status["counts"].get("completed", 0) == 1
        assert status["counts"].get("failed", 0) == 1
        assert status["counts"].get("rate_limited", 0) == 1

    @pytest.mark.asyncio
    async def test_context_assembly_with_data(self, migrated_db, sample_config):
        """Context assembly should include messages and knowledge."""
        memory = Memory(migrated_db, sample_config)
        session_mgr = SessionManager(migrated_db, sample_config)

        session_id = await session_mgr.create_session("chat-1")
        await memory.store_message(session_id, "chat-1", "user", "Build auth module")
        await memory.store_message(session_id, "chat-1", "assistant", "Created auth.py with JWT")
        await memory.store_knowledge("fact.auth.strategy", "JWT with refresh", source="agent")

        context = await memory.assemble_context("chat-1", session_id)
        assert "auth" in context.lower()
        assert "JWT" in context


class TestNoCircularImports:
    """S72: Verify no circular imports."""

    def test_import_all_phase2(self):
        from bridge import (
            claude_runner,
            commands,
            config,
            database,
            formatting,
            memory,
            message_queue,
            session_manager,
            discord_bot,
        )
        assert config.BridgeConfig is not None
        assert database.Database is not None
        assert formatting.format_response is not None
        assert claude_runner.ClaudeRunner is not None
        assert message_queue.MessageQueue is not None
        assert memory.Memory is not None
        assert session_manager.SessionManager is not None
        assert discord_bot.DiscordBot is not None
        assert commands.CommandHandler is not None
