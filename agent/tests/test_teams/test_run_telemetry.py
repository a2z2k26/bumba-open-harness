"""Run telemetry for Zone 4 department execution."""

from __future__ import annotations

from dataclasses import dataclass
from unittest.mock import AsyncMock, patch

import pytest
from pydantic_ai.exceptions import ModelHTTPError, UsageLimitExceeded
from pydantic_ai.usage import RunUsage

from teams._run_telemetry import RunTelemetry, render_telemetry_footer
from teams._team import DepartmentTeam
from teams._types import AgentSpec, Constraints, DepartmentConfig, TeamOutput
from tests.test_teams.conftest import make_deps


@dataclass(frozen=True)
class _RunResult:
    output: TeamOutput
    run_usage: RunUsage | None = None

    def usage(self) -> RunUsage | None:
        return self.run_usage


def _config(
    *,
    fallback_model: str | None = None,
    expected_min_specialists: int = 0,
) -> DepartmentConfig:
    return DepartmentConfig(
        name="strategy",
        zone=4,
        description="Strategy",
        manager=AgentSpec(
            name="strategy-product-chief",
            model="anthropic-oauth:claude-sonnet-4-5",
            fallback_model=fallback_model,
        ),
        employees=(),
        constraints=Constraints(
            timeout_seconds=10,
            cost_limit_usd=10.0,
            expected_min_specialists=expected_min_specialists,
        ),
    )


def test_render_telemetry_footer_exposes_provider_path_and_counts() -> None:
    telemetry = RunTelemetry(
        department="strategy",
        chief_name="strategy-product-chief",
        primary_model="anthropic-oauth:claude-sonnet-4-5",
        fallback_model="openrouter:z-ai/glm-5.1",
        fallback_reason="http_429",
        input_tokens=321,
        output_tokens=45,
        request_count=3,
        specialists_expected_min=1,
        specialists_returned=1,
        specialists_successful=1,
        surfaces_written=2,
        artifacts_written=1,
    )

    footer = render_telemetry_footer(telemetry)

    assert "strategy-product-chief" in footer
    assert "primary=anthropic-oauth:claude-sonnet-4-5" in footer
    assert "fallback=openrouter:z-ai/glm-5.1" in footer
    assert "reason=http_429" in footer
    assert "tokens=in:321 out:45" in footer
    assert "requests=3" in footer
    assert "specialists=1/1" in footer
    assert "surfaces=2" in footer
    assert "artifacts=1" in footer


@pytest.mark.asyncio
async def test_fallback_run_records_provider_path_and_usage_counts() -> None:
    config = _config(fallback_model="openrouter:z-ai/glm-5.1")
    team = DepartmentTeam(config=config, lazy_build=False)
    deps = make_deps(session_id="s1", department="strategy")
    error = ModelHTTPError(
        status_code=429,
        model_name="claude-sonnet-4-5",
        body={
            "type": "error",
            "error": {"type": "rate_limit_error", "message": "Error"},
        },
    )

    with patch.object(team.manager, "run", new=AsyncMock(side_effect=error)):
        assert team._manager_fallback is not None
        with patch.object(
            team._manager_fallback,
            "run",
            new=AsyncMock(
                return_value=_RunResult(
                    output=TeamOutput(answer="fallback synthesis"),
                    run_usage=RunUsage(
                        input_tokens=321,
                        output_tokens=45,
                        requests=3,
                    ),
                )
            ),
        ) as fallback_run:
            result = await team.run("size the acquisition options", deps=deps)

    assert result.success is True
    assert result.manager_output == "fallback synthesis"
    assert result.total_tokens == 366
    fallback_run.assert_awaited_once()
    assert result.telemetry is not None
    assert result.telemetry.department == "strategy"
    assert result.telemetry.chief_name == "strategy-product-chief"
    assert result.telemetry.primary_model == "anthropic-oauth:claude-sonnet-4-5"
    assert result.telemetry.fallback_model == "openrouter:z-ai/glm-5.1"
    assert result.telemetry.fallback_reason == "http_429"
    assert result.telemetry.input_tokens == 321
    assert result.telemetry.output_tokens == 45
    assert result.telemetry.request_count == 3
    assert result.telemetry.specialists_expected_min == 0
    assert result.telemetry.specialists_returned == 0
    assert result.telemetry.specialists_successful == 0
    assert result.telemetry.failure_class is None


@pytest.mark.asyncio
async def test_usage_limit_failure_records_request_count_cap() -> None:
    team = DepartmentTeam(config=_config(), lazy_build=False)
    deps = make_deps(session_id="s1", department="strategy")

    with patch.object(
        team.manager,
        "run",
        new=AsyncMock(side_effect=UsageLimitExceeded("request limit reached")),
    ):
        result = await team.run("size the acquisition options", deps=deps)

    assert result.success is False
    assert "UsageLimitExceeded" in (result.error or "")
    assert result.telemetry is not None
    assert result.telemetry.failure_class == "usage_request_count_cap"
    assert result.telemetry.primary_model == "anthropic-oauth:claude-sonnet-4-5"


@pytest.mark.asyncio
async def test_model_http_error_failure_records_normalized_failure_class() -> None:
    team = DepartmentTeam(config=_config(fallback_model="openrouter:z-ai/glm-5.1"), lazy_build=False)
    deps = make_deps(session_id="s1", department="strategy")
    error = ModelHTTPError(
        status_code=500,
        model_name="claude-sonnet-4-5",
        body={"type": "error", "error": {"type": "server_error"}},
    )

    with patch.object(team.manager, "run", new=AsyncMock(side_effect=error)):
        assert team._manager_fallback is not None
        with patch.object(
            team._manager_fallback,
            "run",
            new=AsyncMock(
                return_value=_RunResult(
                    output=TeamOutput(answer="should not run fallback"),
                )
            ),
        ) as fallback_run:
            result = await team.run("size the acquisition options", deps=deps)

    assert result.success is False
    assert "ModelHTTPError" in (result.error or "")
    fallback_run.assert_not_awaited()
    assert result.telemetry is not None
    assert result.telemetry.failure_class == "model_http_error"
    assert result.telemetry.fallback_model is None
    assert result.telemetry.fallback_reason is None


@pytest.mark.asyncio
async def test_output_gate_failure_preserves_run_telemetry() -> None:
    team = DepartmentTeam(
        config=_config(expected_min_specialists=1),
        lazy_build=False,
    )
    deps = make_deps(session_id="s1", department="strategy")

    with patch.object(
        team.manager,
        "run",
        new=AsyncMock(
            return_value=_RunResult(
                output=TeamOutput(answer="direct answer"),
                run_usage=RunUsage(input_tokens=100, output_tokens=25, requests=1),
            )
        ),
    ):
        result = await team.run("size the acquisition options", deps=deps)

    assert result.success is False
    assert "Gate 8 FAIL" in (result.error or "")
    assert result.telemetry is not None
    assert result.telemetry.failure_class == "output_gate_violation"
    assert result.telemetry.input_tokens == 100
    assert result.telemetry.output_tokens == 25
    assert result.telemetry.request_count == 1
    assert result.telemetry.specialists_expected_min == 1
    assert result.telemetry.specialists_returned == 0
    assert result.telemetry.specialists_successful == 0
