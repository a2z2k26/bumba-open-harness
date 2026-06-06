"""P3.02 — HttpBackend: request/parse against an OpenAI-compatible endpoint.

httpx is fully mocked — NO live model calls. Placed flat
(tests/test_http_backend.py); no tests/test_backends/ package exists.
"""
from __future__ import annotations

import json
from unittest import mock

import pytest

from bridge.backends._protocol import BackendProtocol, StreamEvent
from bridge.backends.http_base import HttpBackend


def _make_backend() -> HttpBackend:
    return HttpBackend(
        base_url="https://openrouter.ai/api/v1",
        api_key="sk-test-key",
        model="deepseek/deepseek-chat",
        timeout=30,
    )


def test_http_backend_reports_http_transport() -> None:
    assert _make_backend().transport == "http"


def test_http_backend_satisfies_protocol() -> None:
    # Full BackendProtocol surface incl. P1.01 capability methods + P3.01
    # transport — runtime_checkable matches by member name, so a missing
    # method silently drops it out of the structural check.
    assert isinstance(_make_backend(), BackendProtocol)


def test_http_backend_capability_honesty() -> None:
    """Base OpenAI-compatible chat backend does not wire tools / system-prompt
    files / MCP / tool pre-auth — report all four False rather than no-op."""
    backend = _make_backend()
    assert backend.supports_tool_calling() is False
    assert backend.supports_system_prompt() is False
    assert backend.supports_mcp_config() is False
    assert backend.supports_tool_preauth() is False


def test_subprocess_surface_raises_not_implemented() -> None:
    backend = _make_backend()
    with pytest.raises(NotImplementedError):
        backend.resolve_binary()
    with pytest.raises(NotImplementedError):
        backend.build_command(message="hi")


def test_request_requires_live_allow_env(monkeypatch) -> None:
    backend = _make_backend()
    monkeypatch.delenv("BUMBA_ALLOW_LIVE", raising=False)

    with pytest.raises(RuntimeError, match="BUMBA_ALLOW_LIVE=1"):
        backend.request(message="say hi")


def test_request_posts_openai_chat_shape(monkeypatch) -> None:
    monkeypatch.setenv("BUMBA_ALLOW_LIVE", "1")
    backend = _make_backend()
    fake_response = mock.Mock()
    fake_response.json.return_value = {
        "id": "gen-123",
        "model": "deepseek/deepseek-chat",
        "choices": [{"message": {"role": "assistant", "content": "hello world"}}],
        "usage": {"prompt_tokens": 5, "completion_tokens": 2},
    }
    fake_response.raise_for_status.return_value = None
    fake_client = mock.MagicMock()
    fake_client.post.return_value = fake_response
    fake_client.__enter__.return_value = fake_client

    with mock.patch("bridge.backends.http_base.httpx.Client", return_value=fake_client):
        raw = backend.request(message="say hi", system_prompt="be terse")

    args, kwargs = fake_client.post.call_args
    assert args[0] == "https://openrouter.ai/api/v1/chat/completions"
    assert kwargs["headers"]["Authorization"] == "Bearer sk-test-key"
    payload = kwargs["json"]
    assert payload["model"] == "deepseek/deepseek-chat"
    assert payload["messages"][0] == {"role": "system", "content": "be terse"}
    assert payload["messages"][1] == {"role": "user", "content": "say hi"}
    assert raw["choices"][0]["message"]["content"] == "hello world"


def test_parse_event_maps_chat_response_to_result_streamevent() -> None:
    backend = _make_backend()
    raw = {
        "id": "gen-123",
        "model": "deepseek/deepseek-chat",
        "choices": [{"message": {"role": "assistant", "content": "the answer"}}],
        "usage": {"prompt_tokens": 5, "completion_tokens": 2},
    }
    event = backend.parse_event(json.dumps(raw))
    assert isinstance(event, StreamEvent)
    assert event.type == "result"
    assert event.text == "the answer"
    assert event.is_error is False


def test_parse_event_returns_none_for_blank_line() -> None:
    assert _make_backend().parse_event("   ") is None


def test_parse_event_flags_error_on_malformed_choices() -> None:
    backend = _make_backend()
    event = backend.parse_event(json.dumps({"id": "x", "choices": []}))
    assert event is not None
    assert event.is_error is True
