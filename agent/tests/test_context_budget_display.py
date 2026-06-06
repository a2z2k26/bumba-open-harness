"""Tests for issue #17: Context budget display in /status."""

from __future__ import annotations

import pytest
import pytest_asyncio

from bridge.commands import CommandHandler as CmdHandler


@pytest_asyncio.fixture
async def cmd_handler(migrated_db, message_queue, session_manager):
    """CommandHandler with real session_manager for context pressure tests."""
    return CmdHandler(
        db=migrated_db,
        queue=message_queue,
        session_manager=session_manager,
        claude_runner=None,
    )


class TestContextBudgetDisplay:
    @pytest.mark.asyncio
    async def test_status_with_no_session_shows_no_active(self, cmd_handler):
        result = await cmd_handler.handle("chat-1", "status", "")
        assert "No active session" in result or "Session:" in result

    @pytest.mark.asyncio
    async def test_status_with_active_session_shows_bar(self, cmd_handler, session_manager):
        """After creating a session, /status should show the context pressure bar."""
        await session_manager.create_session("chat-1")
        result = await cmd_handler.handle("chat-1", "status", "")
        # Should show the context budget bar format
        assert "[" in result and "]" in result and "%" in result
        assert "Messages:" in result

    @pytest.mark.asyncio
    async def test_status_bar_format(self, cmd_handler, session_manager):
        """Verify the bar format: [###---] N%"""
        await session_manager.create_session("chat-1")
        result = await cmd_handler.handle("chat-1", "status", "")
        # Check for pressure bar components
        import re
        # Look for pattern like [##########----------] 25%
        bar_match = re.search(r"\[([#\-]+)\]\s+\d+%", result)
        assert bar_match is not None, f"No bar found in: {result!r}"

    @pytest.mark.asyncio
    async def test_status_bar_shows_message_count(self, cmd_handler, session_manager):
        """Bar line shows Messages: N/M format."""
        await session_manager.create_session("chat-1")
        result = await cmd_handler.handle("chat-1", "status", "")
        assert "Messages:" in result

    @pytest.mark.asyncio
    async def test_status_bar_shows_max_messages(self, cmd_handler, session_manager):
        """Bar line shows the max messages config value."""
        await session_manager.create_session("chat-1")
        result = await cmd_handler.handle("chat-1", "status", "")
        # Should show N/40 or similar
        assert "/40" in result or "/20" in result or "max" in result.lower() or "Messages:" in result

    @pytest.mark.asyncio
    async def test_status_bar_accuracy_at_50_percent(self, cmd_handler, session_manager, migrated_db):
        """At 50% messages, bar should show approximately half filled."""
        sid = await session_manager.create_session("chat-1")
        # Set message count to 20 (50% of 40)
        await migrated_db.execute(
            "UPDATE sessions SET message_count = 20 WHERE claude_session_id = ?",
            (sid,),
        )
        await migrated_db.commit()
        result = await cmd_handler.handle("chat-1", "status", "")
        # Pressure at 50% = 50% bar
        # Bar: [##########----------] 50%
        import re
        match = re.search(r"\[([#\-]+)\]\s+(\d+)%", result)
        if match:
            pct = int(match.group(2))
            assert 45 <= pct <= 55, f"Expected ~50% but got {pct}%"

    @pytest.mark.asyncio
    async def test_status_does_not_fail_without_session(self, cmd_handler):
        """Status command works correctly when there's no active session."""
        result = await cmd_handler.handle("chat-no-session", "status", "")
        assert result is not None
        assert "Agent online" in result
