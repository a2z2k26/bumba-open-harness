"""VAL-13 — Zone 4 OpenRouter text-only team route smoke.

The campaign treats OpenRouter as a text-only backend until proven otherwise.
This smoke validates one narrow Zone 4 route whose model path can answer
without team tools and classifies delegated/team-tool work as blocked before
any live provider is reachable.
"""

from __future__ import annotations

from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.models.test import TestModel

from teams._agent_cache import AgentCache
from teams._factory import build_employee_agents, build_manager_agent
from teams._openrouter_route_policy import (
    classify_openrouter_zone4_route,
)
from teams._team import DepartmentTeam
from teams._types import AgentSpec, Constraints, DepartmentConfig, TeamOutput
from tests.test_teams.conftest import make_deps


def _text_only_strategy_config() -> DepartmentConfig:
    return DepartmentConfig(
        name="strategy-openrouter-text-only",
        zone=4,
        description="Strategy summarization route with no tool or delegation needs",
        manager=AgentSpec(
            name="strategy-summary-chief",
            model="openrouter:z-ai/glm-4.6",
            adapter="openrouter",
            role="Summarize strategy notes in prose only",
        ),
        employees=(),
        common_tools=(),
        department_tools=(),
        allowed_tools=(),
        mcp_mode="deny_by_default",
        mcp_allowed_servers=(),
    )


def _delegating_strategy_config() -> DepartmentConfig:
    return DepartmentConfig(
        name="strategy-openrouter-delegating",
        zone=4,
        description="Strategy route that requires team delegation",
        manager=AgentSpec(
            name="strategy-delegating-chief",
            model="openrouter:z-ai/glm-4.6",
            adapter="openrouter",
            role="Coordinate a strategy specialist before synthesizing",
        ),
        employees=(
            AgentSpec(
                name="market-analyst",
                model="openrouter:z-ai/glm-4.6",
                adapter="openrouter",
                role="Analyze market risk",
            ),
        ),
        constraints=Constraints(expected_min_specialists=1),
        common_tools=(),
        department_tools=(),
        allowed_tools=(),
        mcp_mode="deny_by_default",
        mcp_allowed_servers=(),
    )


def _claude_strategy_config() -> DepartmentConfig:
    return DepartmentConfig(
        name="strategy-claude-text-only",
        zone=4,
        description="Strategy route that stays on the tool-capable Claude path",
        manager=AgentSpec(
            name="strategy-claude-chief",
            model="claude-3-5-sonnet-latest",
            adapter="claude",
            role="Summarize strategy notes in prose only",
        ),
        employees=(),
        common_tools=(),
        department_tools=(),
        allowed_tools=(),
        mcp_mode="deny_by_default",
        mcp_allowed_servers=(),
    )


async def test_zone4_text_generation_path_runs_on_openrouter_with_mocked_model() -> None:
    config = _text_only_strategy_config()
    verdict = classify_openrouter_zone4_route(config)

    assert verdict.classification == "hybrid"
    assert verdict.backend == "openrouter"
    assert verdict.required_capabilities == ("tool_calling",)
    assert verdict.missing_capabilities == ("tool_calling",)
    assert "text generation portion" in verdict.reason
    assert "tool-free enforcement seam" in verdict.reason

    employees = build_employee_agents(config)
    manager = build_manager_agent(config, employees, agent_cache=AgentCache())

    assert employees == {}
    assert isinstance(manager.model, OpenAIChatModel)
    assert manager.model.model_name == "z-ai/glm-4.6"

    test_model = TestModel(
        custom_output_args={
            "answer": "OpenRouter Zone 4 text-only strategy summary is safe."
        },
        call_tools=[],
    )

    with manager.override(model=test_model):
        result = await manager.run(
            "Summarize this strategy note. Do not use tools or delegate.",
            deps=make_deps(
                session_id="val-13-zone4-safe",
                department=config.name,
            ),
        )

    assert isinstance(result.output, TeamOutput)
    assert "text-only strategy summary is safe" in result.output.answer


def test_zone4_delegating_route_blocks_openrouter_with_capability_reason() -> None:
    verdict = classify_openrouter_zone4_route(_delegating_strategy_config())

    assert verdict.classification == "blocked"
    assert verdict.backend == "openrouter"
    assert verdict.required_capabilities == ("tool_calling",)
    assert verdict.missing_capabilities == ("tool_calling",)
    assert "delegate" in verdict.reason
    assert "OpenRouter" in verdict.reason


async def test_zone4_hybrid_openrouter_team_run_refuses_before_manager_build() -> None:
    team = DepartmentTeam(config=_text_only_strategy_config(), lazy_build=True)
    team._last_run_result = object()

    result = await team.run(
        "Summarize this strategy note.",
        deps=make_deps(
            session_id="val-2687-zone4-hybrid-refusal",
            department=team.config.name,
        ),
    )

    assert not result.success
    assert result.total_tokens == 0
    assert result.manager_output == ""
    assert team._manager is None
    assert team._last_run_result is None
    assert "OpenRouter Zone 4 route refused" in (result.error or "")
    assert "hybrid" in (result.error or "")
    assert result.telemetry is not None
    assert result.telemetry.failure_class == "openrouter_zone4_route_policy"
    assert ("openrouter_route_classification", "hybrid") in result.telemetry.extra
    assert ("openrouter_route", "zone4:strategy-openrouter-text-only") in (
        result.telemetry.extra
    )


async def test_zone4_blocked_openrouter_team_run_refuses_before_manager_build() -> None:
    team = DepartmentTeam(config=_delegating_strategy_config(), lazy_build=True)

    result = await team.run(
        "Coordinate this strategy review.",
        deps=make_deps(
            session_id="val-2687-zone4-blocked-refusal",
            department=team.config.name,
        ),
    )

    assert not result.success
    assert result.total_tokens == 0
    assert team._manager is None
    assert "OpenRouter Zone 4 route refused" in (result.error or "")
    assert "blocked" in (result.error or "")
    assert "tool_calling" in (result.error or "")
    assert result.telemetry is not None
    assert result.telemetry.failure_class == "openrouter_zone4_route_policy"
    assert ("openrouter_route_classification", "blocked") in result.telemetry.extra


async def test_zone4_non_openrouter_team_run_is_not_policy_blocked() -> None:
    team = DepartmentTeam(config=_claude_strategy_config(), lazy_build=False)
    test_model = TestModel(
        custom_output_args={
            "answer": "Claude path remains available for Zone 4."
        },
        call_tools=[],
    )

    with team.manager.override(model=test_model):
        result = await team.run(
            "Summarize this strategy note.",
            deps=make_deps(
                session_id="val-2687-zone4-claude-preserved",
                department=team.config.name,
            ),
        )

    assert result.success
    assert "Claude path remains available" in result.manager_output
    assert (
        result.telemetry is None
        or result.telemetry.failure_class != "openrouter_zone4_route_policy"
    )
