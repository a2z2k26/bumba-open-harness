"""Provider-aware Zone 4 usage policy contracts."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from unittest.mock import AsyncMock, patch

import pytest
from pydantic_ai.exceptions import ModelHTTPError, UsageLimitExceeded
from pydantic_ai.usage import UsageLimits

from teams._circuit import get_registry
from teams._team import DepartmentTeam, _resolve_usage_limits
from teams._types import AgentSpec, Constraints, DepartmentConfig, TeamOutput
from tests.test_teams.conftest import make_deps


@dataclass(frozen=True)
class _RunResult:
    output: TeamOutput

    def usage(self) -> None:
        return None


@pytest.fixture(autouse=True)
def _reset_circuit_breakers() -> None:
    get_registry().reset_all()
    yield
    get_registry().reset_all()


def _config(
    *,
    model: str = "anthropic-oauth:claude-sonnet-4-5",
    request_limit: int = 42,
    request_token_limit: int = 350_000,
    response_token_limit: int = 250_000,
) -> DepartmentConfig:
    return DepartmentConfig(
        name="strategy",
        zone=4,
        description="Strategy",
        manager=AgentSpec(name="strategy-product-chief", model=model),
        employees=(),
        constraints=Constraints(
            timeout_seconds=10,
            cost_limit_usd=10.0,
            request_limit=request_limit,
            request_token_limit=request_token_limit,
            response_token_limit=response_token_limit,
        ),
    )


def test_classifies_known_provider_prefixes() -> None:
    from teams._usage_policy import classify_model_provider

    assert classify_model_provider("openrouter:z-ai/glm-5.1") == "openrouter"
    assert classify_model_provider("anthropic-oauth:claude-sonnet-4-5") == (
        "anthropic-oauth"
    )
    assert classify_model_provider("openai:gpt-4o-mini") == "openai"
    assert classify_model_provider("codex-exec:gpt-5.4") == "codex-cli"


def test_usage_policy_preserves_configured_caps_for_first_rollout() -> None:
    from teams._usage_policy import resolve_usage_policy

    policy = resolve_usage_policy(
        provider="openai",
        configured_request_limit=42,
        configured_input_limit=350_000,
        configured_output_limit=250_000,
    )

    assert policy.provider == "openai"
    assert policy.request_limit == 42
    assert policy.input_tokens_limit == 350_000
    assert policy.output_tokens_limit == 250_000
    assert policy.provider_context_window_tokens >= 350_000
    assert policy.preflight_context_chars > 0
    assert policy.clear_warm_context_after_tokens > 0


def test_resolve_usage_limits_threads_provider_policy_without_lowering_caps() -> None:
    usage_limits = _resolve_usage_limits(
        Constraints(
            request_limit=42,
            request_token_limit=350_000,
            response_token_limit=250_000,
        ),
        model="openai:gpt-4o-mini",
    )

    assert isinstance(usage_limits, UsageLimits)
    assert usage_limits.request_limit == 42
    assert usage_limits.input_tokens_limit == 350_000
    assert usage_limits.output_tokens_limit == 250_000


@pytest.mark.asyncio
async def test_preflight_context_estimate_is_logged_before_manager_run(
    caplog: pytest.LogCaptureFixture,
) -> None:
    team = DepartmentTeam(config=_config(model="openai:gpt-4o-mini"), lazy_build=False)
    deps = make_deps(session_id="usage-policy", department="strategy")

    async def fake_run(*args: object, **kwargs: object) -> _RunResult:
        assert "usage_limits" in kwargs
        assert any(
            "department_team.preflight_context_estimate" in record.getMessage()
            for record in caplog.records
        )
        return _RunResult(output=TeamOutput(answer="ok"))

    with caplog.at_level(logging.INFO, logger="teams._team"):
        with patch.object(team.manager, "run", new=AsyncMock(side_effect=fake_run)):
            result = await team.run("summarize current usage policy", deps=deps)

    assert result.success is True
    messages = [record.getMessage() for record in caplog.records]
    assert any("provider=openai" in message for message in messages)
    assert any("preflight_context_chars=" in message for message in messages)


@pytest.mark.asyncio
async def test_request_limit_failure_records_request_count_cap() -> None:
    team = DepartmentTeam(config=_config(), lazy_build=False)
    deps = make_deps(session_id="usage-policy", department="strategy")

    with patch.object(
        team.manager,
        "run",
        new=AsyncMock(side_effect=UsageLimitExceeded("request limit reached")),
    ):
        result = await team.run("trip request count cap", deps=deps)

    assert result.telemetry is not None
    assert result.telemetry.failure_class == "usage_request_count_cap"


@pytest.mark.asyncio
async def test_input_token_failure_records_internal_input_cap() -> None:
    team = DepartmentTeam(config=_config(), lazy_build=False)
    deps = make_deps(session_id="usage-policy", department="strategy")

    with patch.object(
        team.manager,
        "run",
        new=AsyncMock(side_effect=UsageLimitExceeded("input_tokens_limit reached")),
    ):
        result = await team.run("trip input cap", deps=deps)

    assert result.telemetry is not None
    assert result.telemetry.failure_class == "usage_internal_input_cap"


@pytest.mark.asyncio
async def test_provider_context_failure_records_provider_hard_cap() -> None:
    team = DepartmentTeam(config=_config(), lazy_build=False)
    deps = make_deps(session_id="usage-policy", department="strategy")
    error = ModelHTTPError(
        status_code=400,
        model_name="z-ai/glm-5.1",
        body={
            "type": "error",
            "error": {
                "type": "invalid_request_error",
                "message": "maximum context length exceeded",
            },
        },
    )

    with patch.object(team.manager, "run", new=AsyncMock(side_effect=error)):
        result = await team.run("trip provider context cap", deps=deps)

    assert result.telemetry is not None
    assert result.telemetry.failure_class == "usage_provider_hard_cap"
