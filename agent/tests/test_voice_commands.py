"""Tests for /voice and /tts operator commands (D1.7c, issue #1179)."""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock

from bridge.commands import CommandHandler


def _make_handler(app: object | None = None) -> CommandHandler:
    """Create a CommandHandler with the given app mock wired in."""
    handler = CommandHandler.__new__(CommandHandler)
    handler._app = app
    return handler


# ---------------------------------------------------------------------------
# /voice tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cmd_voice_no_app_returns_status_disabled() -> None:
    """With app=None, /voice should report voice as disabled."""
    handler = _make_handler(app=None)
    result = await handler._cmd_voice("chat1", "")
    assert "disabled" in result.lower()


@pytest.mark.asyncio
async def test_cmd_voice_status_not_configured() -> None:
    """voice_enabled=True but _vapi.is_configured=False → vapi_api_key missing message."""
    app = MagicMock()
    app._config.voice_enabled = True
    app._vapi.is_configured = False
    handler = _make_handler(app=app)
    result = await handler._cmd_voice("chat1", "")
    assert "vapi_api_key missing" in result


@pytest.mark.asyncio
async def test_cmd_voice_status_configured() -> None:
    """voice_enabled=True, is_configured=True, squad set → response contains 'active'."""
    app = MagicMock()
    app._config.voice_enabled = True
    app._vapi.is_configured = True
    app._vapi_squad = {
        "squad_id": "sq_abc123",
        "receptionist_id": "asst_xyz",
        "assistant_count": 4,
    }
    handler = _make_handler(app=app)
    result = await handler._cmd_voice("chat1", "")
    assert "active" in result.lower()
    assert "sq_abc123" in result


@pytest.mark.asyncio
async def test_cmd_voice_call_triggers_outbound() -> None:
    """/voice call <phone> triggers trigger_outbound_call and returns call ID."""
    app = MagicMock()
    app._config.voice_enabled = True
    app._vapi.is_configured = True
    app._vapi.trigger_outbound_call = AsyncMock(return_value="call_999")
    handler = _make_handler(app=app)
    result = await handler._cmd_voice("chat1", "call +15551234567")
    app._vapi.trigger_outbound_call.assert_awaited_once_with(
        "+15551234567", "Operator-initiated call"
    )
    assert "call_999" in result


# ---------------------------------------------------------------------------
# /tts tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cmd_tts_text() -> None:
    """/tts <text> should acknowledge the text in the response."""
    handler = _make_handler(app=None)
    result = await handler._cmd_tts("chat1", "hello world")
    assert "hello world" in result


@pytest.mark.asyncio
async def test_cmd_tts_status() -> None:
    """/tts status should return a string containing 'TTS'."""
    app = MagicMock()
    app._config.voice_enabled = True
    app._config.voice_tts_url = "http://127.0.0.1:7888"
    app._config.voice_tts_voice = "af_sky"
    app._tts.enabled = True
    handler = _make_handler(app=app)
    result = await handler._cmd_tts("chat1", "status")
    assert "TTS" in result
