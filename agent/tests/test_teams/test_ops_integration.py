"""Integration tests for the Ops department — full pipeline."""

from __future__ import annotations

import unittest.mock as mock
from pathlib import Path

import pytest
from pydantic_ai.models.test import TestModel

from tests.test_teams.conftest import make_deps
from teams import BridgeDeps, DepartmentRegistry


@pytest.fixture
def registry() -> DepartmentRegistry:
    teams_dir = Path(__file__).parent.parent.parent / "config" / "teams"
    return DepartmentRegistry.from_directory(teams_dir)


@pytest.fixture
def deps() -> BridgeDeps:
    return make_deps(session_id="ops-integration-test", department="ops")


class TestOpsDepartmentIntegration:
    def test_ops_registered(self, registry: DepartmentRegistry):
        assert "ops" in registry.department_names()

    def test_ops_config_loaded(self, registry: DepartmentRegistry):
        cfg = registry.get_config("ops")
        assert cfg.zone == 4
        assert cfg.manager.name == "ops-chief"
        assert len(cfg.employees) >= 7
        names = {e.name for e in cfg.employees}
        assert {
            "ops-devops-specialist",
            "ops-kubernetes-engineer",
            "ops-sre-engineer",
            "ops-monitoring-specialist",
        }.issubset(names)

    def test_ops_specialists_have_no_execution_mode_field(
        self, registry: DepartmentRegistry
    ):
        # Sprint 04.04 (2026-04-30 delete-it path): the dual-mode
        # executor was removed. Three ops specialists (devops, k8s, sre)
        # previously declared execution_mode: claude_code in YAML; that
        # field is now gone. Every ops specialist runs through
        # OpenRouter on openai/gpt-4o-mini per the no-Anthropic-in-Z4
        # contract (docs/zone4/model-assignments.md).
        cfg = registry.get_config("ops")
        for emp in cfg.employees:
            assert not hasattr(emp, "execution_mode"), (
                f"{emp.name} unexpectedly has execution_mode "
                "(should have been removed in Sprint 04.04)"
            )

    def test_ops_constraints(self, registry: DepartmentRegistry):
        cfg = registry.get_config("ops")
        assert cfg.constraints.cost_limit_usd == 1.50
        assert cfg.constraints.timeout_seconds == 600
        assert cfg.constraints.concurrency_limit == 3

    def test_ops_budget(self, registry: DepartmentRegistry):
        cfg = registry.get_config("ops")
        assert cfg.budget.daily_limit_usd == 4.00
        assert 0.50 in cfg.budget.alert_thresholds

    def test_ops_team_builds(self, registry: DepartmentRegistry):
        team = registry.get_team("ops")
        assert team.manager is not None
        assert len(team.employees) >= 7

    @pytest.mark.skip(
        reason=(
            "strict-floor activated 2026-05-12 per #1645 + classification doc "
            "(docs/architecture/2026-05-12-1645-delegation-floor-classification.md, "
            "Class A). Ops is a delegate-mode team (7 workers); the "
            "direct-answer test shortcut is incompatible with the activated "
            "strict-floor."
        )
    )
    @pytest.mark.asyncio
    async def test_ops_route_with_test_model(
        self,
        registry: DepartmentRegistry,
        deps: BridgeDeps,
    ):
        team = registry.get_team("ops")
        test_model = TestModel(
            custom_output_args={"answer": "Ops assessment: com.bumba.agent-bridge is running normally. No action needed."},
            call_tools=[],
        )

        with team.manager.override(model=test_model):
            result = await registry.route(
                "ops",
                "Check bridge service health",
                deps,
            )

        assert result.department == "ops"
        assert result.success is True
        assert "Ops assessment" in result.manager_output

    @pytest.mark.asyncio
    async def test_ops_error_handling(
        self,
        registry: DepartmentRegistry,
        deps: BridgeDeps,
    ):
        team = registry.get_team("ops")

        async def failing_run(*args, **kwargs):
            raise RuntimeError("simulated failure")

        with mock.patch.object(team.manager, "run", side_effect=failing_run):
            result = await registry.route("ops", "task", deps)

        assert result.success is False
        assert result.error is not None
