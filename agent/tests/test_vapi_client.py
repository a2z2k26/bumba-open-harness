"""Unit tests for VAPIClient — D1.7b HTTP implementation.

Covers:
- is_configured gating
- create_assistant HTTP call (mocked aiohttp session)
- trigger_outbound_call raises ValueError when unconfigured
- handle_webhook routing for status-update
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bridge.vapi_client import VAPIClient


# ---------------------------------------------------------------------------
# is_configured
# ---------------------------------------------------------------------------


class TestIsConfigured:
    def test_is_configured_false_when_no_key(self) -> None:
        client = VAPIClient("")
        assert client.is_configured is False

    def test_is_configured_false_when_empty_string(self) -> None:
        client = VAPIClient(api_key="")
        assert client.is_configured is False

    def test_is_configured_true_when_key_set(self) -> None:
        client = VAPIClient("key123")
        assert client.is_configured is True


# ---------------------------------------------------------------------------
# create_assistant
# ---------------------------------------------------------------------------


class TestCreateAssistant:
    @pytest.mark.asyncio
    async def test_create_assistant_raises_when_not_configured(self) -> None:
        client = VAPIClient("")
        with pytest.raises(ValueError, match="vapi_api_key"):
            await client.create_assistant({"name": "Test"})

    @pytest.mark.asyncio
    async def test_create_assistant_posts_to_vapi_api(self) -> None:
        """Mock aiohttp session; POST /assistant returns {"id": "asst_123"}."""
        client = VAPIClient("test-api-key")

        # Build a minimal mock chain: session → context-manager → response
        mock_response = AsyncMock()
        mock_response.status = 201
        mock_response.json = AsyncMock(return_value={"id": "asst_123", "name": "Bumba Receptionist"})
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=False)

        mock_session = MagicMock()
        mock_session.post = MagicMock(return_value=mock_response)
        mock_session.closed = False

        with patch.object(client, "_get_session", new=AsyncMock(return_value=mock_session)):
            result = await client.create_assistant({"name": "Bumba Receptionist"})

        assert result == "asst_123"
        mock_session.post.assert_called_once()
        call_kwargs = mock_session.post.call_args
        # Verify Authorization header is set
        headers = call_kwargs.kwargs.get("headers") or call_kwargs[1].get("headers", {})
        assert headers.get("Authorization") == "Bearer test-api-key"


# ---------------------------------------------------------------------------
# trigger_outbound_call
# ---------------------------------------------------------------------------


class TestTriggerOutboundCall:
    @pytest.mark.asyncio
    async def test_trigger_outbound_call_raises_when_not_configured(self) -> None:
        client = VAPIClient("")
        with pytest.raises(ValueError, match="vapi_api_key"):
            await client.trigger_outbound_call("+15551234567", "test context")

    @pytest.mark.asyncio
    async def test_trigger_outbound_call_raises_when_no_receptionist_id(self) -> None:
        client = VAPIClient(api_key="test-key", vapi_assistant_id_receptionist="")
        with pytest.raises(ValueError, match="vapi_assistant_id_receptionist"):
            await client.trigger_outbound_call("+15551234567", "test context")


# ---------------------------------------------------------------------------
# handle_webhook
# ---------------------------------------------------------------------------


class TestHandleWebhook:
    @pytest.mark.asyncio
    async def test_handle_webhook_status_update_returns_empty(self) -> None:
        client = VAPIClient("key123")
        result = await client.handle_webhook("status-update", {"status": "ringing"})
        assert result == {}

    @pytest.mark.asyncio
    async def test_handle_webhook_hang_returns_empty(self) -> None:
        client = VAPIClient("key123")
        result = await client.handle_webhook("hang", {"call": {"id": "call_abc"}})
        assert result == {}

    @pytest.mark.asyncio
    async def test_handle_webhook_transcript_returns_empty(self) -> None:
        client = VAPIClient("key123")
        result = await client.handle_webhook("transcript", {"role": "user", "transcript": "Hello"})
        assert result == {}

    @pytest.mark.asyncio
    async def test_handle_webhook_end_of_call_report_returns_empty(self) -> None:
        client = VAPIClient("key123")
        result = await client.handle_webhook("end-of-call-report", {"summary": "Call ended"})
        assert result == {}

    @pytest.mark.asyncio
    async def test_handle_webhook_unknown_type_returns_empty(self) -> None:
        client = VAPIClient("key123")
        result = await client.handle_webhook("unknown-event", {})
        assert result == {}

    @pytest.mark.asyncio
    async def test_handle_webhook_assistant_request_returns_config(self) -> None:
        client = VAPIClient("key123", webhook_url="https://example.com/webhook")
        result = await client.handle_webhook("assistant-request", {})
        assert "assistant" in result
        assert result["assistant"]["name"] == "Bumba Receptionist"
        assert result["assistant"]["serverUrl"] == "https://example.com/webhook"
