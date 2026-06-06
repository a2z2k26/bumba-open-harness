"""Tests for bridge.fallback (Fallback LLM Chain)."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from bridge.fallback import FALLBACK_INDICATOR, FallbackChain, FallbackResult


class TestFallbackChain:
    """Fallback LLM via OpenRouter."""

    def test_not_configured_without_key(self):
        chain = FallbackChain(api_key="")
        assert chain.is_configured is False

    def test_configured_with_key(self):
        chain = FallbackChain(api_key="sk-test-123")
        assert chain.is_configured is True

    def test_invoke_without_key(self):
        chain = FallbackChain(api_key="")
        result = chain.invoke("Hello")
        assert result.is_fallback is True
        assert result.error is not None
        assert "configured" in result.error.lower()

    @patch("bridge.fallback.urllib.request.urlopen")
    def test_invoke_success(self, mock_urlopen):
        response_data = {
            "choices": [{"message": {"content": "I can help with that."}}],
            "model": "anthropic/claude-3.5-sonnet",
        }
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(response_data).encode()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        chain = FallbackChain(api_key="sk-test")
        result = chain.invoke("Hello")

        assert result.is_fallback is True
        assert result.error is None
        assert result.response_text.startswith(FALLBACK_INDICATOR)
        assert "I can help with that." in result.response_text

    @patch("bridge.fallback.urllib.request.urlopen")
    def test_invoke_network_error(self, mock_urlopen):
        import urllib.error
        mock_urlopen.side_effect = urllib.error.URLError("Connection refused")

        chain = FallbackChain(api_key="sk-test")
        result = chain.invoke("Hello")

        assert result.is_fallback is True
        assert result.error is not None
        assert "Network" in result.error

    @patch("bridge.fallback.urllib.request.urlopen")
    def test_invoke_bad_json(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.read.return_value = b"not json"
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        chain = FallbackChain(api_key="sk-test")
        result = chain.invoke("Hello")

        assert result.error is not None
        assert "Parse" in result.error

    @patch("bridge.fallback.urllib.request.urlopen")
    def test_invoke_with_context(self, mock_urlopen):
        response_data = {
            "choices": [{"message": {"content": "Response with context"}}],
        }
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(response_data).encode()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        chain = FallbackChain(api_key="sk-test")
        result = chain.invoke("Hello", context="You are a helpful assistant")
        assert "Response with context" in result.response_text

    def test_custom_model(self):
        chain = FallbackChain(api_key="sk-test", model="openai/gpt-4")
        assert chain._model == "openai/gpt-4"

    def test_result_dataclass(self):
        r = FallbackResult(response_text="test", model_used="gpt-4", is_fallback=True)
        assert r.response_text == "test"
        assert r.model_used == "gpt-4"
        assert r.error is None
