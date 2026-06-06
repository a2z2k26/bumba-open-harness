"""Tests for bridge.cross_model.openrouter_adapter (Sprint 04.03).

The adapter is a thin wrapper around `OpenRouterClient` (Sprint 04.03a). These
tests verify:

  1. The class satisfies the runtime-checkable `AgentAdapter` Protocol.
  2. `invoke()` delegates to `OpenRouterClient.complete()` — no parallel HTTP
     code is allowed to creep in.
  3. The `CompletionResult` -> `AdapterResult` translation preserves model and
     usage data.
  4. Client exceptions are caught and turned into a graceful
     `AdapterResult(success=False, ...)` envelope; the Board never sees a raise.
  5. The `board_cross_vendor_enabled` feature flag exists on `BridgeConfig` and
     defaults to OFF (the adapter itself stays available regardless — the flag
     gates *use* of the adapter from `agent_router.py`, see Sprint 04.05).
"""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch

from bridge.config import BridgeConfig
from bridge.cross_model import OpenRouterAdapter
from bridge.cross_model.agent_adapter import AdapterResult, AgentAdapter
from bridge.cross_model.openrouter_client import CompletionResult


# ---------------------------------------------------------------------------
# Protocol conformance
# ---------------------------------------------------------------------------


class TestProtocolConformance:
    """OpenRouterAdapter satisfies the AgentAdapter Protocol."""

    def test_isinstance_against_runtime_checkable_protocol(self):
        adapter = OpenRouterAdapter(api_key="sk-test")
        # `AgentAdapter` is decorated `@runtime_checkable`; this verifies the
        # adapter exposes the required `invoke` attribute.
        assert isinstance(adapter, AgentAdapter)

    def test_invoke_is_async(self):
        adapter = OpenRouterAdapter(api_key="sk-test")
        assert asyncio.iscoroutinefunction(adapter.invoke)


# ---------------------------------------------------------------------------
# Construction / configuration surface
# ---------------------------------------------------------------------------


class TestConstruction:
    """Adapter accepts the same config as OpenRouterClient."""

    def test_default_model_matches_client_default(self):
        adapter = OpenRouterAdapter(api_key="sk-test")
        # Mirrors `OpenRouterClient` default — the adapter does not invent
        # a different default.
        assert adapter.model == "anthropic/claude-3.5-sonnet"

    def test_custom_model(self):
        adapter = OpenRouterAdapter(api_key="sk-test", model="openai/gpt-4o")
        assert adapter.model == "openai/gpt-4o"

    def test_is_configured_reflects_api_key(self):
        assert OpenRouterAdapter(api_key="").is_configured is False
        assert OpenRouterAdapter(api_key="sk-test").is_configured is True


# ---------------------------------------------------------------------------
# Delegation to OpenRouterClient (no new HTTP code)
# ---------------------------------------------------------------------------


class TestDelegation:
    """invoke() must call OpenRouterClient.complete; never craft its own POST."""

    def test_invoke_delegates_to_client_complete(self):
        adapter = OpenRouterAdapter(api_key="sk-test")
        mock_client = MagicMock()
        mock_client.complete.return_value = CompletionResult(
            content="hi back",
            model="anthropic/claude-3.5-sonnet",
            raw={"choices": [{"message": {"content": "hi back"}}]},
        )
        adapter._client = mock_client  # type: ignore[assignment]

        asyncio.run(adapter.invoke("hello"))

        mock_client.complete.assert_called_once()
        sent_messages = mock_client.complete.call_args.args[0]
        # The user prompt must be the last message regardless of context.
        assert sent_messages[-1] == {"role": "user", "content": "hello"}

    def test_invoke_passes_context_system_field_as_system_message(self):
        adapter = OpenRouterAdapter(api_key="sk-test")
        mock_client = MagicMock()
        mock_client.complete.return_value = CompletionResult(
            content="ok", model="m", raw={}
        )
        adapter._client = mock_client  # type: ignore[assignment]

        asyncio.run(adapter.invoke("user q", context={"system": "you are X"}))

        sent_messages = mock_client.complete.call_args.args[0]
        assert sent_messages[0] == {"role": "system", "content": "you are X"}
        assert sent_messages[1] == {"role": "user", "content": "user q"}

    def test_invoke_ignores_non_string_system_context(self):
        adapter = OpenRouterAdapter(api_key="sk-test")
        mock_client = MagicMock()
        mock_client.complete.return_value = CompletionResult(
            content="ok", model="m", raw={}
        )
        adapter._client = mock_client  # type: ignore[assignment]

        asyncio.run(adapter.invoke("q", context={"system": 42, "feature": "council"}))

        sent_messages = mock_client.complete.call_args.args[0]
        # Non-string `system` must not produce a system message.
        assert all(m["role"] != "system" for m in sent_messages)


# ---------------------------------------------------------------------------
# CompletionResult -> AdapterResult translation
# ---------------------------------------------------------------------------


class TestResponseTranslation:
    """The adapter wraps CompletionResult into the Protocol's AdapterResult."""

    def test_success_envelope_carries_model_and_response(self):
        adapter = OpenRouterAdapter(api_key="sk-test", model="openai/gpt-4o")
        mock_client = MagicMock()
        mock_client.complete.return_value = CompletionResult(
            content="The answer is 42.",
            model="openai/gpt-4o",
            raw={
                "choices": [{"message": {"content": "The answer is 42."}}],
                "model": "openai/gpt-4o",
                "usage": {"total_tokens": 17},
            },
        )
        adapter._client = mock_client  # type: ignore[assignment]

        result = asyncio.run(adapter.invoke("what?"))

        assert isinstance(result, AdapterResult)
        assert result.success is True
        assert result.model_used == "openai/gpt-4o"
        assert result.tokens_used == 17
        assert result.data["response"] == "The answer is 42."
        assert result.error == ""

    def test_tokens_default_to_zero_when_usage_absent(self):
        adapter = OpenRouterAdapter(api_key="sk-test")
        mock_client = MagicMock()
        mock_client.complete.return_value = CompletionResult(
            content="ok",
            model="m",
            raw={"choices": [{"message": {"content": "ok"}}]},  # no usage key
        )
        adapter._client = mock_client  # type: ignore[assignment]

        result = asyncio.run(adapter.invoke("q"))
        assert result.success is True
        assert result.tokens_used == 0

    def test_raw_payload_preserved_in_data(self):
        adapter = OpenRouterAdapter(api_key="sk-test")
        raw_payload = {
            "id": "gen-abc",
            "choices": [{"message": {"content": "ok"}}],
            "model": "m",
            "usage": {"total_tokens": 5},
        }
        mock_client = MagicMock()
        mock_client.complete.return_value = CompletionResult(
            content="ok", model="m", raw=raw_payload
        )
        adapter._client = mock_client  # type: ignore[assignment]

        result = asyncio.run(adapter.invoke("q"))
        # Raw is preserved so cost_tracker (Plan 04.04) can pull cost data.
        assert result.data["raw"] == raw_payload


# ---------------------------------------------------------------------------
# Error path — graceful AdapterResult, never raise
# ---------------------------------------------------------------------------


class TestErrorPath:
    """Client exceptions become AdapterResult(success=False, error=...)."""

    def test_network_error_returns_graceful_failure(self):
        import urllib.error

        adapter = OpenRouterAdapter(api_key="sk-test", model="openai/gpt-4o")
        mock_client = MagicMock()
        mock_client.complete.side_effect = urllib.error.URLError("dns boom")
        adapter._client = mock_client  # type: ignore[assignment]

        result = asyncio.run(adapter.invoke("q"))

        assert isinstance(result, AdapterResult)
        assert result.success is False
        assert result.tokens_used == 0
        # Per spec test 4: failure populates `error` so the Board can log it.
        assert "URLError" in result.error
        assert "dns boom" in result.error
        # `model_used` falls back to the configured model since we have no
        # server response to read.
        assert result.model_used == "openai/gpt-4o"

    def test_parse_error_returns_graceful_failure(self):
        adapter = OpenRouterAdapter(api_key="sk-test")
        mock_client = MagicMock()
        mock_client.complete.side_effect = KeyError("choices")
        adapter._client = mock_client  # type: ignore[assignment]

        result = asyncio.run(adapter.invoke("q"))

        assert result.success is False
        assert "KeyError" in result.error

    def test_unknown_error_does_not_raise(self):
        adapter = OpenRouterAdapter(api_key="sk-test")
        mock_client = MagicMock()
        mock_client.complete.side_effect = RuntimeError("unexpected")
        adapter._client = mock_client  # type: ignore[assignment]

        # Must NOT raise — the Board contract is that one bad member
        # degrades gracefully while the rest of the council continues.
        result = asyncio.run(adapter.invoke("q"))
        assert result.success is False
        assert "RuntimeError" in result.error


# ---------------------------------------------------------------------------
# Async offload — adapter must not block the event loop on the sync client
# ---------------------------------------------------------------------------


class TestAsyncOffload:
    """invoke() offloads the sync client.complete call via asyncio.to_thread."""

    def test_invoke_uses_to_thread(self):
        adapter = OpenRouterAdapter(api_key="sk-test")
        mock_client = MagicMock()
        mock_client.complete.return_value = CompletionResult(
            content="ok", model="m", raw={}
        )
        adapter._client = mock_client  # type: ignore[assignment]

        with patch(
            "bridge.cross_model.openrouter_adapter.asyncio.to_thread",
            wraps=asyncio.to_thread,
        ) as spy:
            asyncio.run(adapter.invoke("q"))

        spy.assert_called_once()
        # First positional arg is the client.complete bound method.
        called_target = spy.call_args.args[0]
        assert called_target == mock_client.complete


# ---------------------------------------------------------------------------
# End-to-end with mocked urlopen — exercises the real OpenRouterClient
# ---------------------------------------------------------------------------


class TestEndToEndWithMockedUrlopen:
    """One real-client integration test, mocking urlopen at the bottom."""

    @patch("bridge.cross_model.openrouter_client.urllib.request.urlopen")
    def test_adapter_with_real_client_returns_success(self, mock_urlopen):
        import json as _json

        response_data = {
            "choices": [{"message": {"content": "hello back"}}],
            "model": "anthropic/claude-3.5-sonnet",
            "usage": {"total_tokens": 12},
        }
        mock_resp = MagicMock()
        mock_resp.read.return_value = _json.dumps(response_data).encode()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        adapter = OpenRouterAdapter(api_key="sk-test")
        result = asyncio.run(adapter.invoke("hello"))

        assert result.success is True
        assert result.data["response"] == "hello back"
        assert result.model_used == "anthropic/claude-3.5-sonnet"
        assert result.tokens_used == 12


# ---------------------------------------------------------------------------
# Feature flag — adapter exists regardless, flag gates use from agent_router
# ---------------------------------------------------------------------------


class TestFeatureFlagDefault:
    """`board_cross_vendor_enabled` exists on BridgeConfig and defaults OFF.

    The flag gates *use* of the adapter from `agent_router.py` (Sprint 04.05),
    NOT the existence of the adapter class. The class is unconditionally
    importable so unit tests, smoke tests, and offline tooling can run
    without a runtime config flip.
    """

    def test_flag_exists_on_bridge_config(self):
        cfg = BridgeConfig()
        assert hasattr(cfg, "board_cross_vendor_enabled")

    def test_flag_defaults_on(self):
        """2026-05-18 zone4-model-allocation: flag default flipped to True.

        After the cost-optimization migration every board member routes via
        OpenRouter on the cheap-frontier cohort; the original shadow-period
        gate (False default) would strip all 10 board members from the team
        build. Flag flipped to True; flag itself retained so operators who
        want to revert can do so via bridge.toml.
        """
        cfg = BridgeConfig()
        assert cfg.board_cross_vendor_enabled is True

    def test_adapter_class_importable_regardless_of_flag(self):
        # Importing the adapter never reads the flag.
        from bridge.cross_model.openrouter_adapter import OpenRouterAdapter as _A

        cfg = BridgeConfig()  # flag ON by default post-2026-05-18
        adapter = _A(api_key="sk-test")
        assert adapter is not None
        assert cfg.board_cross_vendor_enabled is True
