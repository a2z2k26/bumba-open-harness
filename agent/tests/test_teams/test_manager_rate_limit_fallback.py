"""Manager fallback behavior for rate-limited OAuth canaries."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from pydantic_ai.exceptions import ModelHTTPError

from teams._config import load_department_config_from_string
from teams._team import DepartmentTeam
from teams._types import AgentSpec, Constraints, DepartmentConfig, TeamOutput
from tests.test_teams.conftest import make_deps


class _RunResult:
    output = TeamOutput(answer="fallback synthesis")

    def usage(self) -> None:
        return None


def test_agent_spec_loads_manager_fallback_model_from_yaml() -> None:
    cfg = load_department_config_from_string(
        """\
team:
  name: strategy
  zone: 4
  chief:
    name: strategy-product-chief
    model: anthropic-oauth:claude-sonnet-4-5
    fallback_model: openrouter:z-ai/glm-5.1
""",
        source="fallback-model-test.yaml",
    )

    assert cfg.manager.model == "anthropic-oauth:claude-sonnet-4-5"
    assert cfg.manager.fallback_model == "openrouter:z-ai/glm-5.1"


@pytest.mark.asyncio
async def test_manager_rate_limit_uses_configured_fallback_model() -> None:
    config = DepartmentConfig(
        name="strategy",
        zone=4,
        description="Strategy",
        manager=AgentSpec(
            name="strategy-product-chief",
            model="anthropic-oauth:claude-sonnet-4-5",
            fallback_model="openrouter:z-ai/glm-5.1",
        ),
        employees=(),
        constraints=Constraints(timeout_seconds=10, cost_limit_usd=10.0),
    )
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
            new=AsyncMock(return_value=_RunResult()),
        ) as fallback_run:
            result = await team.run("ready to work?", deps=deps)

    assert result.success is True
    assert result.manager_output == "fallback synthesis"
    fallback_run.assert_awaited_once()


@pytest.mark.asyncio
async def test_manager_non_rate_limit_error_does_not_use_fallback() -> None:
    config = DepartmentConfig(
        name="strategy",
        zone=4,
        description="Strategy",
        manager=AgentSpec(
            name="strategy-product-chief",
            model="anthropic-oauth:claude-sonnet-4-5",
            fallback_model="openrouter:z-ai/glm-5.1",
        ),
        employees=(),
        constraints=Constraints(timeout_seconds=10, cost_limit_usd=10.0),
    )
    team = DepartmentTeam(config=config, lazy_build=False)
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
            new=AsyncMock(return_value=_RunResult()),
        ) as fallback_run:
            result = await team.run("ready to work?", deps=deps)

    assert result.success is False
    assert "ModelHTTPError" in (result.error or "")
    fallback_run.assert_not_awaited()
