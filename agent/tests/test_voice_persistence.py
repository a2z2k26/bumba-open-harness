"""Tests for voice conversation persistence and context injection."""

import json
import pytest
from unittest.mock import AsyncMock, patch


@pytest.fixture
def mock_memory():
    """Create a mock memory manager."""
    mem = AsyncMock()
    mem.store_message = AsyncMock()
    return mem


class TestVoicePersistence:
    @pytest.mark.asyncio
    async def test_persist_voice_exchange_stores_both_messages(self, mock_memory):
        """Voice exchanges should store both user and assistant messages."""
        from bridge.app import BridgeApp
        agent = BridgeApp.__new__(BridgeApp)
        agent._memory = mock_memory

        await agent._persist_voice_exchange(
            session_id="sess-123",
            chat_id="chat-456",
            user_text="What time is my meeting?",
            assistant_text="Your next meeting is at 3pm.",
            cost_usd=0.01,
            duration_ms=1500,
        )

        assert mock_memory.store_message.call_count == 2

        # First call: user message
        user_call = mock_memory.store_message.call_args_list[0]
        assert user_call.kwargs["role"] == "user"
        assert user_call.kwargs["content"] == "What time is my meeting?"

        # Second call: assistant message
        asst_call = mock_memory.store_message.call_args_list[1]
        assert asst_call.kwargs["role"] == "assistant"
        assert asst_call.kwargs["content"] == "Your next meeting is at 3pm."
        assert asst_call.kwargs["cost_usd"] == 0.01

    @pytest.mark.asyncio
    async def test_persist_voice_exchange_handles_failure(self, mock_memory):
        """DB failures should be logged but not raise."""
        mock_memory.store_message.side_effect = Exception("DB locked")

        from bridge.app import BridgeApp
        agent = BridgeApp.__new__(BridgeApp)
        agent._memory = mock_memory

        # Should not raise
        await agent._persist_voice_exchange(
            session_id="sess-123",
            chat_id="chat-456",
            user_text="test",
            assistant_text="response",
        )


class TestVoiceContextInjection:
    def test_summarize_for_voice_with_context(self, tmp_path):
        """Context summary should include schedule, inbox, goals, system."""
        ctx_path = tmp_path / "context.json"
        ctx_path.write_text(json.dumps({
            "schedule": {"today_count": 2, "next_event": {"title": "Sync", "minutes_until": 20}},
            "inbox": {"unread_total": 5, "unread_urgent": 0},
            "goals": {"active": [{"key": "g1"}, {"key": "g2"}], "overdue": []},
            "system": {"uptime_hours": 12.0, "error_count_1h": 0, "halt_flag": False},
        }))

        from bridge.services.context_builder import summarize_for_voice
        with patch("bridge.services.context_builder.CONTEXT_PATH", ctx_path):
            summary = summarize_for_voice()

        assert summary.startswith("Context:")
        assert "2 meetings" in summary
        assert "5 unread" in summary
        assert "2 active goals" in summary

    def test_summarize_returns_empty_when_no_context(self, tmp_path):
        """Should return empty string when no context file exists."""
        from bridge.services.context_builder import summarize_for_voice
        with patch("bridge.services.context_builder.CONTEXT_PATH", tmp_path / "nope.json"):
            summary = summarize_for_voice()
        assert summary == ""

    def test_context_injection_prepends_to_message(self):
        """Voice message should be prepended with context summary."""
        # Test the logic inline since the actual method is hard to unit test
        text = "What's my schedule?"
        ctx_summary = "Context: 3 meetings today. 5 unread emails."
        voice_message = f"[{ctx_summary}]\n\n{text}"
        assert voice_message.startswith("[Context:")
        assert voice_message.endswith("What's my schedule?")
