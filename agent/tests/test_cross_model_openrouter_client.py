"""Tests for bridge.cross_model.openrouter_client (Sprint 04.03a)."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from bridge.cross_model.openrouter_client import (
    OPENROUTER_URL,
    CompletionResult,
    OpenRouterClient,
)


class TestOpenRouterClientConfig:
    """Configuration surface."""

    def test_not_configured_without_key(self):
        client = OpenRouterClient(api_key="")
        assert client.is_configured is False

    def test_configured_with_key(self):
        client = OpenRouterClient(api_key="sk-test-123")
        assert client.is_configured is True

    def test_default_model(self):
        client = OpenRouterClient(api_key="sk-test")
        # Mirrors the default fallback model — extracted, not changed.
        assert client.default_model == "anthropic/claude-3.5-sonnet"

    def test_custom_model(self):
        client = OpenRouterClient(api_key="sk-test", model="openai/gpt-4")
        assert client.default_model == "openai/gpt-4"


class TestOpenRouterClientComplete:
    """The actual HTTP call."""

    @patch("bridge.cross_model.openrouter_client.urllib.request.urlopen")
    def test_complete_returns_parsed_result_on_200(self, mock_urlopen):
        response_data = {
            "choices": [{"message": {"content": "Hello back"}}],
            "model": "anthropic/claude-3.5-sonnet",
            "usage": {"prompt_tokens": 5, "completion_tokens": 3, "total_tokens": 8},
        }
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(response_data).encode()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        client = OpenRouterClient(api_key="sk-test")
        result = client.complete([{"role": "user", "content": "Hello"}])

        assert isinstance(result, CompletionResult)
        assert result.content == "Hello back"
        assert result.model == "anthropic/claude-3.5-sonnet"
        # `raw` carries the full payload so callers can read usage/cost data.
        assert result.raw["usage"]["total_tokens"] == 8

    @patch("bridge.cross_model.openrouter_client.urllib.request.urlopen")
    def test_complete_uses_per_call_model_override(self, mock_urlopen):
        response_data = {
            "choices": [{"message": {"content": "ok"}}],
            "model": "openai/gpt-4o",
        }
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(response_data).encode()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        client = OpenRouterClient(api_key="sk-test")  # default sonnet
        result = client.complete(
            [{"role": "user", "content": "Hi"}],
            model="openai/gpt-4o",
        )

        # Verify the request payload sent the override, not the default.
        sent_request = mock_urlopen.call_args.args[0]
        sent_payload = json.loads(sent_request.data.decode())
        assert sent_payload["model"] == "openai/gpt-4o"
        assert result.model == "openai/gpt-4o"

    @patch("bridge.cross_model.openrouter_client.urllib.request.urlopen")
    def test_complete_falls_back_to_requested_model_when_response_omits_it(
        self, mock_urlopen
    ):
        # Some OpenRouter responses don't echo back `model`; mirror the
        # original `result.get("model", self._model)` defaulting.
        response_data = {"choices": [{"message": {"content": "ok"}}]}
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(response_data).encode()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        client = OpenRouterClient(api_key="sk-test", model="anthropic/claude-3.5-sonnet")
        result = client.complete([{"role": "user", "content": "Hi"}])
        assert result.model == "anthropic/claude-3.5-sonnet"

    @patch("bridge.cross_model.openrouter_client.urllib.request.urlopen")
    def test_complete_propagates_url_error(self, mock_urlopen):
        import urllib.error

        mock_urlopen.side_effect = urllib.error.URLError("boom")

        client = OpenRouterClient(api_key="sk-test")
        # The client doesn't translate; callers (e.g. FallbackChain) decide.
        with pytest.raises(urllib.error.URLError):
            client.complete([{"role": "user", "content": "Hi"}])

    @patch("bridge.cross_model.openrouter_client.urllib.request.urlopen")
    def test_complete_propagates_parse_errors(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.read.return_value = b"not json"
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        client = OpenRouterClient(api_key="sk-test")
        with pytest.raises(json.JSONDecodeError):
            client.complete([{"role": "user", "content": "Hi"}])

    @patch("bridge.cross_model.openrouter_client.urllib.request.urlopen")
    def test_complete_propagates_keyerror_on_missing_choices(self, mock_urlopen):
        # Same shape error path FallbackChain swallows as "Parse error".
        response_data = {"unexpected": "shape"}
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(response_data).encode()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        client = OpenRouterClient(api_key="sk-test")
        with pytest.raises(KeyError):
            client.complete([{"role": "user", "content": "Hi"}])

    @patch("bridge.cross_model.openrouter_client.urllib.request.urlopen")
    def test_complete_sends_correct_url_and_headers(self, mock_urlopen):
        response_data = {
            "choices": [{"message": {"content": "ok"}}],
            "model": "anthropic/claude-3.5-sonnet",
        }
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(response_data).encode()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        client = OpenRouterClient(api_key="sk-test-key")
        client.complete([{"role": "user", "content": "Hi"}])

        sent_request = mock_urlopen.call_args.args[0]
        assert sent_request.full_url == OPENROUTER_URL
        assert sent_request.method == "POST"
        # Header lookup is case-insensitive on urllib Request — use header_items.
        headers = {k.lower(): v for k, v in sent_request.header_items()}
        assert headers["authorization"] == "Bearer sk-test-key"
        assert headers["content-type"] == "application/json"
        assert headers["http-referer"] == "https://bumba-agent.local"
        assert headers["x-title"] == "Bumba Agent Fallback"

    @patch("bridge.cross_model.openrouter_client.urllib.request.urlopen")
    def test_complete_respects_timeout(self, mock_urlopen):
        response_data = {
            "choices": [{"message": {"content": "ok"}}],
            "model": "anthropic/claude-3.5-sonnet",
        }
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(response_data).encode()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        client = OpenRouterClient(api_key="sk-test", timeout=7)
        client.complete([{"role": "user", "content": "Hi"}])

        # urlopen called as urlopen(req, timeout=N); pull from kwargs.
        assert mock_urlopen.call_args.kwargs["timeout"] == 7


class TestCompletionResult:
    """Frozen dataclass invariants."""

    def test_completion_result_is_frozen(self):
        r = CompletionResult(content="hi", model="m", raw={})
        with pytest.raises(Exception):
            r.content = "changed"  # type: ignore[misc]
