"""Integration tests for the Strategy department — full pipeline."""

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
    return make_deps(session_id="strategy-integration-test", department="strategy")


class TestStrategyDepartmentIntegration:
    def test_strategy_registered(self, registry: DepartmentRegistry):
        assert "strategy" in registry.department_names()

    def test_strategy_config_loaded(self, registry: DepartmentRegistry):
        cfg = registry.get_config("strategy")
        assert cfg.zone == 4
        assert cfg.manager.name == "strategy-product-chief"
        assert len(cfg.employees) >= 7
        names = {e.name for e in cfg.employees}
        assert {
            "strategy-business-analyst",
            "strategy-market-researcher",
            "strategy-requirement-engineer",
            "strategy-roadmap-strategist",
            "strategy-competitive-intelligence-analyst",
        }.issubset(names)

    def test_strategy_team_builds(self, registry: DepartmentRegistry):
        team = registry.get_team("strategy")
        assert team.manager is not None
        assert len(team.employees) >= 7

    def test_strategy_constraints_loaded(self, registry: DepartmentRegistry):
        cfg = registry.get_config("strategy")
        assert cfg.constraints.cost_limit_usd == 1.50
        assert cfg.constraints.timeout_seconds == 600
        assert cfg.constraints.concurrency_limit == 4

    def test_strategy_budget_loaded(self, registry: DepartmentRegistry):
        cfg = registry.get_config("strategy")
        assert cfg.budget.daily_limit_usd == 5.00
        assert 0.50 in cfg.budget.alert_thresholds

    def test_strategy_tools_loaded(self, registry: DepartmentRegistry):
        cfg = registry.get_config("strategy")
        assert "read_file" in cfg.common_tools
        assert "search_market_data" in cfg.department_tools
        assert "analyze_competitor" in cfg.department_tools

    def test_strategy_vapi_config(self, registry: DepartmentRegistry):
        cfg = registry.get_config("strategy")
        assert cfg.vapi.enabled is True
        assert cfg.vapi.voice == "alloy"
        assert "search_market_data" in cfg.vapi.tools

    def test_strategy_model_strings_normalized(self, registry: DepartmentRegistry):
        # #2566 hybrid fleet:
        # - strategy-product-chief runs anthropic-oauth (tool-calling tier).
        # - strategy-product-metrics-analyst keeps the OpenAI API canary.
        # - Every other Strategy specialist runs codex-exec (prose only).
        # OpenRouter is dead — no specialist routes through it anymore.
        cfg = registry.get_config("strategy")
        assert cfg.manager.model == "anthropic-oauth:claude-sonnet-4-5"
        assert cfg.manager.adapter == "claude"
        openai_canaries = [
            emp.name for emp in cfg.employees if emp.model.startswith("openai:")
        ]
        assert openai_canaries == ["strategy-product-metrics-analyst"]
        for emp in cfg.employees:
            if emp.name == "strategy-product-metrics-analyst":
                assert emp.model == "openai:gpt-4o-mini"
                assert emp.adapter == "claude"
                continue
            assert emp.model == "codex-exec:", (
                f"{emp.name}: specialists run codex-exec, got {emp.model}"
            )
            assert emp.adapter == "codex-exec"
            assert "anthropic" not in emp.model.lower(), (
                f"{emp.name}: strategy specialists must not use Anthropic models"
            )
            assert "openrouter" not in emp.model.lower(), (
                f"{emp.name}: OpenRouter is dead (#2566) — no specialist routes it"
            )

    @pytest.mark.skip(
        reason=(
            "strict-floor activated 2026-05-12 per #1645 + classification doc "
            "(docs/architecture/2026-05-12-1645-delegation-floor-classification.md, "
            "Class A). Strategy is a delegate-mode team (7 workers); the "
            "direct-answer test shortcut is incompatible with the activated "
            "strict-floor."
        )
    )
    @pytest.mark.asyncio
    async def test_strategy_route_with_test_model(
        self, registry: DepartmentRegistry, deps: BridgeDeps,
    ):
        team = registry.get_team("strategy")
        test_model = TestModel(
            custom_output_args={"answer": "Strategy analysis: recommended approach is A. Trade-off: slower but lower risk."},
            call_tools=[],
        )

        with team.manager.override(model=test_model):
            result = await registry.route(
                "strategy",
                "Should we pursue approach A or B for the new feature?",
                deps,
            )

        assert result.department == "strategy"
        assert result.success is True
        assert "Strategy analysis" in result.manager_output

    @pytest.mark.asyncio
    async def test_strategy_error_handling(
        self, registry: DepartmentRegistry, deps: BridgeDeps,
    ):
        team = registry.get_team("strategy")

        async def failing_run(*args, **kwargs):
            raise RuntimeError("simulated failure")

        with mock.patch.object(team.manager, "run", side_effect=failing_run):
            result = await registry.route("strategy", "task", deps)

        assert result.success is False
        assert result.error is not None
