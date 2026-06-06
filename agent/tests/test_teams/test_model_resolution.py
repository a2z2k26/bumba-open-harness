"""Tests for ``teams._factory._resolve_model`` (Sprint 04.07 / #1961).

The factory's ``_resolve_model`` helper is the one place where the
``openrouter:`` prefix on ``AgentSpec.model`` is consulted and routed
through pydantic-ai's OpenAI-compatible provider pointed at OpenRouter.
Without this, every department YAML declaring ``model: openrouter:*``
constructs an Agent that fails silently at run time when the chief
delegates — surfacing only as Gate 8 floor violations on the operator side.

These unit tests pin four branches:

1. Bare ``openrouter:`` prefix → returns an ``OpenAIChatModel`` whose provider's
   ``base_url`` is OpenRouter's chat-completions endpoint and whose
   ``model_name`` has the prefix stripped.
2. ``openai:`` prefix → returns an ``OpenAIChatModel`` backed by the direct
   OpenAI API billing surface certified by Z4-15.
3. Anthropic-style ``anthropic:`` / ``opus-4.6`` / etc. → returns the raw
   string so pydantic-ai's existing resolution path keeps working
   byte-for-byte.
4. The OpenRouter credential lookup falls back through BridgeConfig → env var → empty
   string without raising.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml
from pydantic_ai.models.anthropic import AnthropicModel
from pydantic_ai.models.openai import OpenAIChatModel

from teams._factory import (
    MissingProviderCredentialError,
    _OPENAI_BILLED_SURFACE,
    _OPENROUTER_BASE_URL,
    _resolve_model,
    _resolve_openai_api_key,
    _resolve_openrouter_api_key,
)
from teams._types import AgentSpec


def _spec(model: str, *, adapter: str = "claude", name: str = "test-agent") -> AgentSpec:
    """Build a minimal AgentSpec for resolution tests."""
    return AgentSpec(name=name, model=model, adapter=adapter)


class TestResolveModelOpenRouterPrefix:
    def test_openrouter_prefix_returns_openai_model_instance(self) -> None:
        spec = _spec("openrouter:openai/gpt-5")
        resolved = _resolve_model(spec)
        assert isinstance(resolved, OpenAIChatModel)

    def test_openrouter_prefix_strips_prefix_from_model_name(self) -> None:
        spec = _spec("openrouter:openai/gpt-5")
        resolved = _resolve_model(spec)
        assert isinstance(resolved, OpenAIChatModel)
        # The model_name on the underlying client should be the stripped value
        assert resolved.model_name == "openai/gpt-5"

    def test_openrouter_prefix_uses_openrouter_base_url(self) -> None:
        spec = _spec("openrouter:openai/gpt-5")
        resolved = _resolve_model(spec)
        assert isinstance(resolved, OpenAIChatModel)
        # The provider's underlying OpenAI client should point at OpenRouter
        # base_url ends with /v1/ — accept either with or without trailing slash
        provider_base = str(resolved.client.base_url).rstrip("/")
        assert provider_base == _OPENROUTER_BASE_URL.rstrip("/")

    def test_openrouter_prefix_for_non_openai_provider_model(self) -> None:
        # OpenRouter passes any backing-provider model through; pydantic-ai
        # should not care what comes after the prefix.
        spec = _spec("openrouter:meta-llama/llama-3.1-405b-instruct")
        resolved = _resolve_model(spec)
        assert isinstance(resolved, OpenAIChatModel)
        assert resolved.model_name == "meta-llama/llama-3.1-405b-instruct"

    def test_openrouter_prefix_ignores_adapter_field(self) -> None:
        # The 6 paradoxical pairs (adapter=claude + model=openrouter:*) MUST
        # route through OpenRouter — the model prefix is the source of truth.
        spec = _spec("openrouter:openai/gpt-5", adapter="claude")
        resolved = _resolve_model(spec)
        assert isinstance(resolved, OpenAIChatModel)


class TestResolveModelAnthropicOAuthPrefix:
    """Canary path for routing a PydanticAI agent through Claude OAuth.

    This does not flip any production YAML. It only proves that a deliberately
    prefixed model string can build an AnthropicModel with bearer-token auth
    and without leaking ANTHROPIC_API_KEY into the request headers.
    """

    def test_anthropic_oauth_prefix_returns_anthropic_model(
        self, monkeypatch
    ) -> None:
        monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "oauth-token")

        resolved = _resolve_model(_spec("anthropic-oauth:claude-sonnet-4-5"))

        assert isinstance(resolved, AnthropicModel)
        assert resolved.model_name == "claude-sonnet-4-5"
        assert resolved.client.max_retries == 5

    def test_anthropic_oauth_prefix_uses_bearer_without_api_key_header(
        self, monkeypatch
    ) -> None:
        monkeypatch.setenv("ANTHROPIC_API_KEY", "api-key-must-not-leak")
        monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "oauth-token")

        resolved = _resolve_model(_spec("anthropic-oauth:claude-sonnet-4-5"))

        assert isinstance(resolved, AnthropicModel)
        assert resolved.client.auth_headers == {
            "Authorization": "Bearer oauth-token"
        }

    def test_anthropic_oauth_client_reads_fresh_token(
        self, monkeypatch
    ) -> None:
        token = {"value": "first-token"}
        monkeypatch.setattr(
            "teams._factory._resolve_claude_oauth_token",
            lambda: token["value"],
        )

        resolved = _resolve_model(_spec("anthropic-oauth:claude-sonnet-4-5"))

        assert isinstance(resolved, AnthropicModel)
        assert resolved.client.auth_headers == {
            "Authorization": "Bearer first-token"
        }
        token["value"] = "second-token"
        assert resolved.client.auth_headers == {
            "Authorization": "Bearer second-token"
        }


class TestResolveModelPassThrough:
    def test_bare_shortcut_string_passes_through(self) -> None:
        spec = _spec("sonnet-4.6")
        resolved = _resolve_model(spec)
        assert resolved == "sonnet-4.6"

    def test_anthropic_prefix_passes_through(self) -> None:
        spec = _spec("anthropic:claude-opus-4-6")
        resolved = _resolve_model(spec)
        assert resolved == "anthropic:claude-opus-4-6"

    def test_pass_through_returns_str_not_model_instance(self) -> None:
        spec = _spec("opus-4.6")
        resolved = _resolve_model(spec)
        assert isinstance(resolved, str)
        assert not isinstance(resolved, OpenAIChatModel)


class TestResolveModelOpenAIPrefix:
    """Z4-16: OpenAI API canary path certified by the Z4-15 spike."""

    def test_openai_prefix_returns_openai_chat_model(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("OPENAI_API_KEY", "sk-openai-canary")

        resolved = _resolve_model(
            _spec("openai:gpt-4o-mini", name="strategy-product-metrics-analyst")
        )

        assert isinstance(resolved, OpenAIChatModel)
        assert resolved.model_name == "gpt-4o-mini"
        assert resolved.client.api_key == "sk-openai-canary"

    def test_missing_openai_key_fails_with_named_provider(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)

        with pytest.raises(MissingProviderCredentialError, match="OPENAI_API_KEY"):
            _resolve_model(_spec("openai:gpt-4o-mini"))

    def test_openai_key_reads_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("OPENAI_API_KEY", "sk-openai-env")

        assert _resolve_openai_api_key() == "sk-openai-env"

    def test_openai_prefix_logs_provider_and_billing_surface(
        self,
        caplog: pytest.LogCaptureFixture,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("OPENAI_API_KEY", "sk-openai-canary")

        with caplog.at_level(logging.INFO, logger="teams._factory"):
            _resolve_model(
                _spec(
                    "openai:gpt-4o-mini",
                    name="strategy-product-metrics-analyst",
                )
            )

        messages = [record.getMessage() for record in caplog.records]
        assert any("provider=openai" in message for message in messages)
        assert any(
            f"billed_surface={_OPENAI_BILLED_SURFACE}" in message
            for message in messages
        )


class TestResolveOpenRouterApiKey:
    def test_env_var_used_when_bridge_config_unavailable(self) -> None:
        # When BridgeConfig() raises (e.g. teams-only fixtures with no bridge
        # package on the path), the env var is the fallback path.
        with patch.dict(os.environ, {"OPENROUTER_API_KEY": "env-fallback-key"}):
            with patch(
                "bridge.config.BridgeConfig",
                side_effect=ImportError("simulated"),
            ):
                key = _resolve_openrouter_api_key()
                assert key == "env-fallback-key"

    def test_empty_string_when_neither_source_present(self) -> None:
        # Mock BridgeConfig().openrouter_api_key returning empty string and
        # ensure env var is also absent. The function should return "" without
        # raising.
        with patch.dict(os.environ, {}, clear=False):
            # Pop the env var if present
            os.environ.pop("OPENROUTER_API_KEY", None)
            # Mock BridgeConfig to return an instance with empty key
            class _MockBridgeConfig:
                openrouter_api_key = ""
            with patch("bridge.config.BridgeConfig", _MockBridgeConfig):
                key = _resolve_openrouter_api_key()
                assert key == ""

    def test_bridge_config_value_preferred_over_env(self) -> None:
        with patch.dict(os.environ, {"OPENROUTER_API_KEY": "env-key"}):
            class _MockBridgeConfig:
                openrouter_api_key = "bridge-config-key"
            with patch("bridge.config.BridgeConfig", _MockBridgeConfig):
                key = _resolve_openrouter_api_key()
                assert key == "bridge-config-key"


class TestResolveModelDoesNotRaise:
    """The factory must never raise during agent construction — a bad
    credential surfaces as a 401 at invocation time, not as an import-time
    crash. defer_model_check=True on Agent() backs this; _resolve_model
    must hold up its end."""

    def test_openrouter_prefix_with_empty_api_key_returns_model_anyway(
        self,
    ) -> None:
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("OPENROUTER_API_KEY", None)

            class _MockBridgeConfig:
                openrouter_api_key = ""

            with patch("bridge.config.BridgeConfig", _MockBridgeConfig):
                spec = _spec("openrouter:openai/gpt-5")
                resolved = _resolve_model(spec)
                # No raise; the provider just carries an empty credential.
                assert isinstance(resolved, OpenAIChatModel)


# ---------------------------------------------------------------------------
# Sprint S4.1 (#2285) — Backend-Operability adapter+model contract
#
# The 2026-05-18 model-allocation PR (#2275) flipped every Zone 4 agent to
# ``adapter: openrouter`` + ``model: openrouter:*``. Several follow-up PRs
# (C.02 #2310, C.03 #2312) caught remaining stragglers. This regression test
# pins the contract against the *real* team YAMLs so a future YAML edit that
# re-introduces an ``adapter: claude`` + ``model: openrouter:*`` pair fails
# the suite, not just the load-time warning in
# test_adapter_model_mismatch_warning.py (which uses synthetic fixtures).
# ---------------------------------------------------------------------------


_TEAMS_DIR = Path(__file__).parent.parent.parent / "config" / "teams"


def _real_team_yaml_paths() -> list[Path]:
    """Return every department-team YAML, excluding ``_template.yaml``."""
    return [p for p in sorted(_TEAMS_DIR.glob("*.yaml")) if p.name != "_template.yaml"]


def _team_members(path: Path) -> list[dict[str, object]]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    team = data["team"]
    members = [team["chief"]]
    members.extend(team.get("workers", []) or [])
    return members


class TestRealTeamYamlAdapterModelContract:
    """The runtime routes by ``model:`` prefix. If a YAML declares
    ``model: openrouter:*`` it MUST also declare ``adapter: openrouter`` so
    the operator's declared intent matches what the runtime actually does.
    """

    def test_openrouter_prefixed_models_declare_openrouter_adapter(self) -> None:
        offenders: list[str] = []
        for path in _real_team_yaml_paths():
            for member in _team_members(path):
                model = str(member.get("model", ""))
                if model.startswith("openrouter:"):
                    adapter = member.get("adapter")
                    if adapter != "openrouter":
                        offenders.append(
                            f"{path.name}: {member.get('name')!r} "
                            f"routes via OpenRouter (model={model!r}) "
                            f"but declares adapter={adapter!r}"
                        )
        assert not offenders, (
            "Team YAML adapter/model mismatch (see #2285, #2275):\n  "
            + "\n  ".join(offenders)
        )

    def test_openrouter_adapter_implies_openrouter_prefixed_model(self) -> None:
        """The inverse contract: an ``adapter: openrouter`` declaration must
        be paired with a ``model: openrouter:*`` prefix so the runtime
        actually routes there. Bare model strings under adapter=openrouter
        would silently fall through pydantic-ai's default resolution path."""
        offenders: list[str] = []
        for path in _real_team_yaml_paths():
            for member in _team_members(path):
                if member.get("adapter") == "openrouter":
                    model = str(member.get("model", ""))
                    if not model.startswith("openrouter:"):
                        offenders.append(
                            f"{path.name}: {member.get('name')!r} "
                            f"declares adapter=openrouter but model={model!r} "
                            f"lacks the 'openrouter:' prefix"
                        )
        assert not offenders, (
            "Team YAML adapter=openrouter with non-openrouter model "
            "(see #2285):\n  " + "\n  ".join(offenders)
        )

    def test_strategy_declares_exactly_one_openai_canary_role(self) -> None:
        strategy_path = _TEAMS_DIR / "strategy.yaml"

        canaries = [
            str(member.get("name"))
            for member in _team_members(strategy_path)
            if str(member.get("model", "")).startswith("openai:")
        ]

        assert canaries == ["strategy-product-metrics-analyst"]
