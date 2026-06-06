"""Tests for teams._factory module using TestModel (zero API calls)."""

from __future__ import annotations

import pytest
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.models.test import TestModel

from teams._factory import build_employee_agents, build_manager_agent
from tests.test_teams.conftest import make_deps
from teams._types import (
    AgentSpec,
    BridgeDeps,
    DepartmentConfig,
    TeamOutput,
)


@pytest.fixture
def minimal_config() -> DepartmentConfig:
    return DepartmentConfig(
        name="qa",
        zone=4,
        description="QA department for testing",
        manager=AgentSpec(
            name="qa-chief",
            model="anthropic:claude-opus-4-6",
            role="Orchestrates QA work",
        ),
        employees=(
            AgentSpec(
                name="qa-engineer",
                model="anthropic:claude-sonnet-4-6",
                role="Test design and coverage",
            ),
            AgentSpec(
                name="security-auditor",
                model="anthropic:claude-sonnet-4-6",
                role="Security scanning",
            ),
        ),
    )


@pytest.fixture
def bridge_deps() -> BridgeDeps:
    return make_deps(session_id="test-s1", department="qa")


class TestBuildEmployeeAgents:
    def test_returns_one_agent_per_employee(self, minimal_config):
        agents = build_employee_agents(minimal_config)
        assert len(agents) == 2
        assert "qa-engineer" in agents
        assert "security-auditor" in agents

    def test_agent_has_expected_name(self, minimal_config):
        agents = build_employee_agents(minimal_config)
        assert agents["qa-engineer"] is not None


class TestBuildManagerAgent:
    def test_returns_single_agent(self, minimal_config):
        employees = build_employee_agents(minimal_config)
        manager = build_manager_agent(minimal_config, employees)
        assert manager is not None

    @pytest.mark.asyncio
    async def test_manager_delegates_with_test_model(self, minimal_config, bridge_deps):
        employees = build_employee_agents(minimal_config)
        manager = build_manager_agent(minimal_config, employees)

        # call_tools=[] — manager produces output directly without invoking delegation
        # tools; this keeps the test to zero API calls while verifying the agent
        # runs and returns structured output.
        test_model = TestModel(
            custom_output_args={"answer": "QA review complete. No critical issues."},
            call_tools=[],
        )

        with manager.override(model=test_model):
            result = await manager.run("Review the auth module", deps=bridge_deps)

        assert result.output
        assert isinstance(result.output, TeamOutput)
        assert "QA review complete" in result.output.answer


class TestModelRoutingIntegration:
    """Sprint 04.07 (#1961) — integration: confirm that an AgentSpec with
    an ``openrouter:*`` model string ends up backed by an OpenAIChatModel
    instance after going through build_employee_agents / build_manager_agent.

    These tests close the loop on _resolve_model's unit tests by verifying
    the wiring inside the factory functions, not just the helper in
    isolation. They use private attribute access on the constructed Agent
    to inspect the model — fragile against pydantic-ai upgrades, but the
    fragility is exactly what we want pinned: if pydantic-ai changes how
    Agent stores its model and this breaks, the OpenRouter wiring needs
    to be re-validated.
    """

    @pytest.fixture
    def openrouter_config(self) -> DepartmentConfig:
        return DepartmentConfig(
            name="strategy",
            zone=4,
            description="Strategy department for OpenRouter routing tests",
            manager=AgentSpec(
                name="strategy-chief",
                model="openrouter:openai/gpt-5",
                adapter="claude",  # paradoxical-pair on purpose — see #1961
                role="Orchestrates strategy work",
            ),
            employees=(
                AgentSpec(
                    name="strategy-claude-worker",
                    model="anthropic:claude-sonnet-4-6",
                    role="Native pydantic-ai routing path",
                ),
                AgentSpec(
                    name="strategy-openrouter-worker",
                    model="openrouter:openai/gpt-4o-mini",
                    adapter="openrouter",
                    role="OpenRouter routing path",
                ),
            ),
        )

    def test_openrouter_employee_agent_uses_openai_model(
        self, openrouter_config: DepartmentConfig
    ) -> None:
        agents = build_employee_agents(openrouter_config)
        or_agent = agents["strategy-openrouter-worker"]
        # pydantic-ai stashes the resolved model on the agent's _model attr
        assert isinstance(or_agent.model, OpenAIChatModel), (
            f"openrouter-worker expected OpenAIChatModel; got {type(or_agent.model)}"
        )
        assert or_agent.model.model_name == "openai/gpt-4o-mini"

    def test_non_openrouter_employee_agent_uses_string_model(
        self, openrouter_config: DepartmentConfig
    ) -> None:
        agents = build_employee_agents(openrouter_config)
        claude_agent = agents["strategy-claude-worker"]
        # Native pydantic-ai path: model resolves from the string
        # (Anthropic-Anthropic). It will NOT be an OpenAIChatModel instance.
        assert not isinstance(claude_agent.model, OpenAIChatModel)

    def test_openrouter_manager_agent_uses_openai_model(
        self, openrouter_config: DepartmentConfig
    ) -> None:
        employees = build_employee_agents(openrouter_config)
        manager = build_manager_agent(openrouter_config, employees)
        assert isinstance(manager.model, OpenAIChatModel), (
            "manager with adapter=claude + model=openrouter:* must route "
            "through OpenRouter post-#1961 (prefix-based routing)"
        )
        assert manager.model.model_name == "openai/gpt-5"
