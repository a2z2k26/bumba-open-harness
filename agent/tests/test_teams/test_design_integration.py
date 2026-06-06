"""Integration tests for the Design department — full pipeline."""

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
    return make_deps(session_id="design-integration-test", department="design")


class TestDesignDepartmentIntegration:
    def test_design_registered(self, registry: DepartmentRegistry):
        assert "design" in registry.department_names()

    def test_design_config_loaded(self, registry: DepartmentRegistry):
        cfg = registry.get_config("design")
        assert cfg.zone == 4
        assert cfg.manager.name == "design-chief"
        assert len(cfg.employees) >= 7
        names = {e.name for e in cfg.employees}
        assert {
            "design-ui-designer",
            "design-accessibility-specialist",
            "design-prototyper",
        }.issubset(names)

    def test_design_specialists_have_no_execution_mode_field(
        self, registry: DepartmentRegistry
    ):
        # Sprint 04.04 (2026-04-30): execution_mode field removed from
        # AgentSpec along with the dual-mode executor implementations.
        # Every specialist runs as pydantic-ai now via OpenRouter
        # (see docs/zone4/model-assignments.md).
        cfg = registry.get_config("design")
        for emp in cfg.employees:
            assert not hasattr(emp, "execution_mode"), (
                f"{emp.name} unexpectedly has execution_mode "
                "(should have been removed in Sprint 04.04)"
            )

    def test_design_constraints_loaded(self, registry: DepartmentRegistry):
        cfg = registry.get_config("design")
        assert cfg.constraints.cost_limit_usd == 2.00
        assert cfg.constraints.timeout_seconds == 900
        assert cfg.constraints.concurrency_limit == 4
        assert cfg.constraints.request_limit == 30
        assert cfg.constraints.request_token_limit == 250_000
        assert cfg.constraints.response_token_limit == 250_000

    def test_design_budget_loaded(self, registry: DepartmentRegistry):
        cfg = registry.get_config("design")
        assert cfg.budget.daily_limit_usd == 6.00
        assert cfg.budget.alert_thresholds == (0.50, 0.75, 0.90)

    def test_design_tools_loaded(self, registry: DepartmentRegistry):
        cfg = registry.get_config("design")
        assert "search_design_system" in cfg.department_tools
        assert "lookup_component" in cfg.department_tools
        assert "recall_brand_guidelines" in cfg.department_tools
        assert "read_file" in cfg.common_tools
        # accessibility-specialist gets check_wcag_contrast
        assert "check_wcag_contrast" in cfg.per_employee_tools.get(
            "design-accessibility-specialist", ()
        )

    def test_design_vapi_config(self, registry: DepartmentRegistry):
        cfg = registry.get_config("design")
        assert cfg.vapi.enabled is True
        assert cfg.vapi.model == "gpt-4o-mini"
        assert cfg.vapi.voice == "nova"

    def test_design_team_builds(self, registry: DepartmentRegistry):
        team = registry.get_team("design")
        assert team.manager is not None
        assert len(team.employees) >= 7

    def test_manager_model_routes_via_anthropic_oauth(
        self, registry: DepartmentRegistry
    ):
        # 2026-06-04 #2566 hybrid fleet: department chiefs run on
        # anthropic-oauth (subscription Claude via the bridge's minted OAuth
        # token) with adapter "claude" because codex `exec` cannot drive
        # pydantic-ai tool-calling (delegate/final_result). OpenRouter is dead
        # (key died); chiefs REQUIRE tool-calling so they route via the native
        # AnthropicModel through the anthropic-oauth: prefix.
        cfg = registry.get_config("design")
        assert cfg.manager.model == "anthropic-oauth:claude-sonnet-4-5"
        assert cfg.manager.adapter == "claude"

    def test_workers_route_via_codex(
        self, registry: DepartmentRegistry
    ):
        # 2026-06 #2566 + fleet migration #2595: every design specialist —
        # including design-visual-designer, which used to be the singular
        # OpenRouter/Claude exception — now runs on codex-exec (prose only,
        # no tool-calling). OpenRouter is dead; workers route via the
        # codex-exec: prefix with adapter "codex-exec".
        cfg = registry.get_config("design")
        for emp in cfg.employees:
            assert emp.model.startswith("codex-exec:"), (
                f"{emp.name}: model {emp.model} must route via codex-exec"
            )
            assert emp.adapter == "codex-exec", (
                f"{emp.name}: adapter {emp.adapter} must be codex-exec"
            )

    @pytest.mark.skip(
        reason=(
            "strict-floor activated 2026-05-12 per #1645 + classification doc "
            "(docs/architecture/2026-05-12-1645-delegation-floor-classification.md, "
            "Class A). Design is a delegate-mode team (7 workers); the "
            "direct-answer test shortcut is incompatible with the activated "
            "strict-floor."
        )
    )
    @pytest.mark.asyncio
    async def test_design_route_with_test_model(
        self,
        registry: DepartmentRegistry,
        deps: BridgeDeps,
    ):
        team = registry.get_team("design")
        test_model = TestModel(
            custom_output_args={"answer": "Design recommendation: use the editorial grid with serif display type."},
            call_tools=[],
        )

        # agent.override() is sync in pydantic-ai 1.80.0 — use `with`, not `async with`
        with team.manager.override(model=test_model):
            result = await registry.route(
                "design",
                "Redesign the marketing hero section",
                deps,
            )

        assert result.success is True
        assert "Design recommendation" in result.manager_output
        assert result.department == "design"
        assert result.error is None

    @pytest.mark.asyncio
    async def test_design_error_handling(
        self,
        registry: DepartmentRegistry,
        deps: BridgeDeps,
    ):
        team = registry.get_team("design")

        async def failing_run(*args, **kwargs):
            raise RuntimeError("simulated failure")

        with mock.patch.object(team.manager, "run", side_effect=failing_run):
            result = await registry.route("design", "task", deps)

        assert result.success is False
        assert result.error is not None
        assert "simulated failure" in result.error or "RuntimeError" in result.error
