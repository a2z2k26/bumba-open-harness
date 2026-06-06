"""Integration tests for the Board department — multi-perspective decision flow."""

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
    return make_deps(session_id="board-integration-test", department="board")


class TestBoardDepartmentIntegration:
    def test_board_registered(self, registry: DepartmentRegistry):
        assert "board" in registry.department_names()

    def test_board_config_loaded(self, registry: DepartmentRegistry):
        cfg = registry.get_config("board")
        assert cfg.zone == 4
        assert cfg.manager.name == "board-ceo"
        assert len(cfg.employees) >= 6

    def test_board_members_have_no_execution_mode_field(
        self, registry: DepartmentRegistry
    ):
        # Sprint 04.04 (2026-04-30): execution_mode field removed from
        # AgentSpec. Every board seat runs as pydantic-ai; post-#2566 the
        # chief is anthropic-oauth and workers are codex-exec (hybrid fleet).
        cfg = registry.get_config("board")
        for emp in cfg.employees:
            assert not hasattr(emp, "execution_mode"), (
                f"{emp.name} unexpectedly has execution_mode "
                "(should have been removed in Sprint 04.04)"
            )

    def test_board_vapi_disabled(self, registry: DepartmentRegistry):
        cfg = registry.get_config("board")
        assert cfg.vapi is not None
        assert cfg.vapi.enabled is False

    def test_board_team_builds(self, registry: DepartmentRegistry):
        team = registry.get_team("board")
        assert team.manager is not None
        assert len(team.employees) >= 6

    def test_board_constraints_are_elevated(self, registry: DepartmentRegistry):
        cfg = registry.get_config("board")
        # Board gets higher limits than standard departments
        assert cfg.constraints.cost_limit_usd >= 3.0
        assert cfg.constraints.timeout_seconds >= 900

    def test_board_budget_elevated(self, registry: DepartmentRegistry):
        cfg = registry.get_config("board")
        assert cfg.budget.daily_limit_usd >= 8.0

    def test_board_department_tool_registered(self, registry: DepartmentRegistry):
        cfg = registry.get_config("board")
        assert "recall_past_decisions" in cfg.department_tools

    def test_board_hybrid_fleet_chief_anthropic_workers_codex(
        self, registry: DepartmentRegistry
    ):
        # 2026-06-04 #2566 hybrid-fleet: OpenRouter is dead and codex `exec`
        # cannot tool-call. The board now splits by tier:
        #   - chief (board-ceo): anthropic-oauth:claude-sonnet-4-5 + adapter
        #     "claude" — chiefs REQUIRE tool-calling (delegate/final_result)
        #     which only the native AnthropicModel provides.
        #   - workers/board-members: model "codex-exec:" + adapter
        #     "codex-exec" — prose-only autonomous agents.
        # The historical openrouter:-prefix invariant is retired; we now
        # assert the two-tier hybrid contract.
        cfg = registry.get_config("board")
        assert cfg.manager.model == "anthropic-oauth:claude-sonnet-4-5", (
            f"board chief should be on anthropic-oauth, got {cfg.manager.model}"
        )
        assert cfg.manager.adapter == "claude"
        for emp in cfg.employees:
            assert emp.model == "codex-exec:", (
                f"{emp.name} should be a codex-exec worker, got {emp.model}"
            )
            assert emp.adapter == "codex-exec", (
                f"{emp.name} should have adapter=codex-exec, got {emp.adapter}"
            )

    def test_board_agents_have_retry_headroom(self, registry: DepartmentRegistry):
        cfg = registry.get_config("board")
        assert cfg.manager.retries == 3
        offenders = [emp.name for emp in cfg.employees if emp.retries != 3]
        assert not offenders, f"board agents missing retries=3: {offenders}"

    @pytest.mark.skip(
        reason=(
            "strict-floor activated 2026-05-12 per #1645 + classification doc "
            "(docs/architecture/2026-05-12-1645-delegation-floor-classification.md, "
            "Class A). Board is explicitly designed for peer-ranked "
            "deliberation; direct-answer here is a test shortcut, not a "
            "production behaviour."
        )
    )
    @pytest.mark.asyncio
    async def test_board_multi_perspective_route(
        self, registry: DepartmentRegistry, deps: BridgeDeps,
    ):
        team = registry.get_team("board")
        test_model = TestModel(
            custom_output_args={"answer": "Decision framing: Whether to adopt framework X.\n\nBoard views: product-strategist says yes, contrarian warns of lock-in.\n\nRecommendation: Adopt with exit criteria defined."},
            call_tools=[],
        )

        with team.manager.override(model=test_model):
            result = await registry.route(
                "board",
                "Should we adopt framework X?",
                deps,
            )

        assert result.success is True
        assert (
            "Decision framing" in result.manager_output
            or "Recommendation" in result.manager_output
        )

    @pytest.mark.asyncio
    async def test_board_error_handling(
        self, registry: DepartmentRegistry, deps: BridgeDeps,
    ):
        team = registry.get_team("board")

        async def failing_run(*args, **kwargs):
            raise RuntimeError("simulated failure")

        with mock.patch.object(team.manager, "run", side_effect=failing_run):
            result = await registry.route("board", "task", deps)

        assert result.success is False
        assert result.error is not None
