"""Integration tests for the QA department — full pipeline."""

from __future__ import annotations

import asyncio
import unittest.mock as mock
from pathlib import Path

import pytest
from pydantic_ai.models.test import TestModel

from tests.test_teams.conftest import (
    make_chief_delegating_model,
    make_deps,
    make_specialist_text_model,
)
from teams import (
    BridgeDeps,
    DepartmentRegistry,
)


@pytest.fixture
def registry() -> DepartmentRegistry:
    """Load the real config/teams/ directory."""
    teams_dir = Path(__file__).parent.parent.parent / "config" / "teams"
    return DepartmentRegistry.from_directory(teams_dir)


@pytest.fixture
def deps() -> BridgeDeps:
    return make_deps(session_id="integration-test", department="qa")


class TestQADepartmentIntegration:
    def test_qa_registered(self, registry: DepartmentRegistry):
        assert "qa" in registry.department_names()

    def test_qa_config_loaded_with_employees(self, registry: DepartmentRegistry):
        cfg = registry.get_config("qa")
        assert cfg.zone == 4
        # cfg.manager is AgentSpec — check .name
        assert cfg.manager.name == "qa-chief"
        # qa.yaml has 4 workers
        assert len(cfg.employees) >= 4
        names = {e.name for e in cfg.employees}
        assert {"qa-engineer", "security-auditor"}.issubset(names)

    def test_qa_team_builds(self, registry: DepartmentRegistry):
        team = registry.get_team("qa")
        assert team.manager is not None
        assert len(team.employees) >= 4

    @pytest.mark.skip(
        reason=(
            "strict-floor activated 2026-05-12 per #1645 + classification doc "
            "(docs/architecture/2026-05-12-1645-delegation-floor-classification.md, "
            "Class A). QA is a delegate-mode team (4 workers); the "
            "direct-answer test shortcut is incompatible with the activated "
            "strict-floor."
        )
    )
    @pytest.mark.asyncio
    async def test_qa_route_with_test_model(
        self, registry: DepartmentRegistry, deps: BridgeDeps,
    ):
        team = registry.get_team("qa")
        manager_model = TestModel(
            custom_output_args={"answer": "QA analysis complete. No critical issues found."},
            call_tools=[],
        )

        # agent.override() is sync in pydantic-ai 1.80.0 — use `with`, not `async with`
        with team.manager.override(model=manager_model):
            result = await registry.route("qa", "Review the auth module for issues", deps)

        assert result.department == "qa"
        assert result.success is True
        assert "QA analysis complete" in result.manager_output
        assert result.error is None

    @pytest.mark.asyncio
    async def test_qa_error_handling(
        self, registry: DepartmentRegistry, deps: BridgeDeps,
    ):
        team = registry.get_team("qa")

        async def failing_run(*args, **kwargs):
            raise RuntimeError("simulated failure")

        with mock.patch.object(team.manager, "run", side_effect=failing_run):
            result = await registry.route("qa", "task", deps)

        assert result.success is False
        assert result.error is not None
        # team.run formats as "{type(e).__name__}: {e}"
        assert "simulated failure" in result.error or "RuntimeError" in result.error

    @pytest.mark.asyncio
    async def test_qa_concurrent_invocations_respect_semaphore(
        self, registry: DepartmentRegistry, deps: BridgeDeps,
    ):
        # P3.6 strict-floor migration (#1692): QA is a delegate-mode team
        # (4 workers, expected_min_specialists=1), so runtime Gate 8 requires
        # ≥1 delegation per run. Drive a deterministic offline delegation to
        # qa-engineer instead of TestModel direct-answer.
        #
        # Each coroutine builds its OWN mgr_model — the FunctionModel helper
        # carries a closure-local call_count, so reusing one across 5 concurrent
        # invocations would land 9 of 10 calls in the synthesis branch and miss
        # the delegate emission for invocations 2-5.
        team = registry.get_team("qa")
        emp_model = make_specialist_text_model("qa-engineer output")

        async def invoke():
            mgr_model = make_chief_delegating_model(
                [("qa-engineer", "task")], final_answer="done"
            )
            # Each coroutine gets its own override context — override is sync
            # but the agent instance is shared; pydantic-ai stacks overrides safely.
            with team.employees["qa-engineer"].override(model=emp_model):
                with team.manager.override(model=mgr_model):
                    return await registry.route("qa", "task", deps)

        results = await asyncio.gather(*[invoke() for _ in range(5)])
        assert all(r.success for r in results)
        assert all(r.department == "qa" for r in results)
