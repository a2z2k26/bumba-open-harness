"""Tests for issue #16: Proactive summarize-and-reset at pressure >= 0.9."""

from __future__ import annotations

import pytest
import pytest_asyncio

from bridge.config import BridgeConfig
from bridge.session_manager import SessionManager


@pytest_asyncio.fixture
async def session_mgr(migrated_db):
    """Session manager with tight limits for easy pressure testing."""
    config = BridgeConfig(
        session_max_messages=10,   # small max so we can test at scale
        session_max_duration=7200,
    )
    return SessionManager(db=migrated_db, config=config)


class TestProactiveReset:
    @pytest.mark.asyncio
    async def test_pressure_at_90_percent(self, session_mgr, migrated_db):
        """At 90% of max_messages, pressure should be >= 0.9."""
        sid = await session_mgr.create_session("chat-pr1")
        # 9 out of 10 messages
        await migrated_db.execute(
            "UPDATE sessions SET message_count = 9 WHERE claude_session_id = ?",
            (sid,),
        )
        await migrated_db.commit()
        pressure = await session_mgr.context_pressure(sid)
        assert pressure >= 0.9

    @pytest.mark.asyncio
    async def test_pressure_below_90_at_80_percent(self, session_mgr, migrated_db):
        """At 80% of max_messages, pressure should be < 0.9."""
        sid = await session_mgr.create_session("chat-pr2")
        # 8 out of 10 messages
        await migrated_db.execute(
            "UPDATE sessions SET message_count = 8 WHERE claude_session_id = ?",
            (sid,),
        )
        await migrated_db.commit()
        pressure = await session_mgr.context_pressure(sid)
        assert pressure < 0.9

    @pytest.mark.asyncio
    async def test_expire_with_proactive_reason(self, session_mgr, migrated_db):
        """expire_with_summary stores summary and expires session."""
        sid = await session_mgr.create_session("chat-pr3")
        await session_mgr.expire_with_summary(
            "chat-pr3", sid, "proactive_context_reset", "Summary of session."
        )
        # Session should be expired
        row = await migrated_db.fetchone(
            "SELECT status FROM sessions WHERE claude_session_id = ?", (sid,)
        )
        assert row[0] == "expired"

    @pytest.mark.asyncio
    async def test_summary_stored_in_knowledge(self, session_mgr, migrated_db):
        """Session summary is stored in knowledge table on expiry."""
        sid = await session_mgr.create_session("chat-pr4")
        await session_mgr.expire_with_summary(
            "chat-pr4", sid, "proactive_context_reset", "Proactive summary text."
        )
        row = await migrated_db.fetchone(
            "SELECT value FROM knowledge WHERE key = ?",
            (f"session:summary:{sid}",),
        )
        assert row is not None
        assert "Proactive summary text." in row[0]

    @pytest.mark.asyncio
    async def test_fresh_session_after_expiry(self, session_mgr, migrated_db):
        """After proactive reset, next resolve_session returns None → creates fresh session."""
        chat_id = "chat-pr5"
        sid = await session_mgr.create_session(chat_id)
        await session_mgr.expire_with_summary(
            chat_id, sid, "proactive_context_reset", None
        )
        # After expiry, resolve should find no active session
        resolved = await session_mgr.resolve_session(chat_id)
        assert resolved is None
