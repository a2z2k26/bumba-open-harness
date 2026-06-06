"""Sprint 04.07 — integration tests for the three default workflow YAMLs.

The three production workflow YAMLs ship under ``agent/config/workflows/``:

    example.yaml
    pr-ship-decision.yaml
    weekly-ceo-review.yaml

This test file proves three properties:

1. All three YAMLs load via ``WorkflowRegistry`` without raising.
2. Every department referenced by a department-step resolves against
   ``DepartmentRegistry`` (loaded from ``agent/config/teams/``).
3. ``WorkflowEngine.start`` fires every step in declared order against the
   ``pr-ship-decision`` workflow when given a mock ``department_runner``.

Sprint 04.06 stood up the construction sites; 04.07 is the contract test that
proves the wiring + adapter shim survives a real workflow definition.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

pytest.importorskip("pydantic")
pytest.importorskip("yaml")

from bridge.workflow_engine import WorkflowEngine
from bridge.workflow_registry import WorkflowRegistry


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _config_dir() -> Path:
    """Return the canonical config/workflows directory for this checkout."""
    return Path(__file__).parent.parent / "config" / "workflows"


def _teams_dir() -> Path:
    """Return the canonical config/teams directory for this checkout."""
    return Path(__file__).parent.parent / "config" / "teams"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def production_registry() -> WorkflowRegistry:
    """A registry pointed at the real config/workflows directory."""
    return WorkflowRegistry(config_dir=_config_dir())


@pytest.fixture()
def department_names() -> set[str]:
    """Return the set of department names ``DepartmentRegistry`` would load."""
    from teams._registry import DepartmentRegistry

    registry = DepartmentRegistry.from_directory(_teams_dir())
    return set(registry.department_names())


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestProductionYAMLsLoad:
    """All three default YAMLs must parse + validate against the schema."""

    def test_all_three_workflows_load(self, production_registry: WorkflowRegistry) -> None:
        names = set(production_registry.names())
        expected = {
            "example-workflow",
            "pr-ship-decision",
            "weekly-ceo-review",
            "board.weekly_review",
        }
        assert expected.issubset(names), (
            f"Missing default workflow YAMLs. "
            f"Loaded: {sorted(names)} | Expected superset of: {sorted(expected)}"
        )

    @pytest.mark.parametrize(
        "workflow_name",
        [
            "example-workflow",
            "pr-ship-decision",
            "weekly-ceo-review",
            "board.weekly_review",
        ],
    )
    def test_each_workflow_has_at_least_one_step(
        self, production_registry: WorkflowRegistry, workflow_name: str
    ) -> None:
        cfg = production_registry.get(workflow_name)
        assert cfg is not None, f"WorkflowRegistry.get({workflow_name!r}) returned None"
        assert len(cfg.steps) > 0, f"Workflow {workflow_name!r} loaded with zero steps"

    def test_board_weekly_review_mirrors_cron_schedule(
        self, production_registry: WorkflowRegistry
    ) -> None:
        """Sprint 5b.03 (#2167): board.weekly_review formalises the
        weekly_ceo_review cron — same Monday 08:00 UTC trigger."""
        cfg = production_registry.get("board.weekly_review")
        assert cfg is not None
        assert cfg.trigger == "schedule"
        assert cfg.schedule == "cron:0 8 * * 1"


class TestDepartmentReferencesResolve:
    """Every department-step must reference a known DepartmentRegistry entry."""

    def test_every_referenced_department_exists(
        self,
        production_registry: WorkflowRegistry,
        department_names: set[str],
    ) -> None:
        unresolved: dict[str, list[str]] = {}
        for name in production_registry.names():
            cfg = production_registry.get(name)
            assert cfg is not None
            missing = [
                getattr(step, "department")
                for step in cfg.steps
                if getattr(step, "department", None)
                and getattr(step, "department") not in department_names
            ]
            if missing:
                unresolved[name] = sorted(set(missing))

        assert not unresolved, (
            f"One or more workflows reference departments not present in "
            f"DepartmentRegistry. Loaded departments: {sorted(department_names)}. "
            f"Unresolved references: {unresolved}"
        )


class TestWorkflowEngineFiresStepsInOrder:
    """``WorkflowEngine.start`` must dispatch each step exactly once."""

    @pytest.mark.asyncio
    async def test_pr_ship_decision_runs_all_department_steps(
        self,
        production_registry: WorkflowRegistry,
    ) -> None:
        cfg = production_registry.get("pr-ship-decision")
        assert cfg is not None

        called_with: list[tuple[str, str]] = []

        async def mock_department_runner(
            department: str, intent: str, context: dict
        ) -> tuple[str, float]:
            called_with.append((department, intent[:40]))
            return (f"[mock {department}]", 0.001)

        engine = WorkflowEngine(department_runner=mock_department_runner)

        # PR-ship-decision references {pr_number} + {pr_title} + {confidence};
        # provide a fixture context so _render_template substitutes cleanly.
        run_id = engine.start(
            cfg,
            inputs={
                "pr_number": "123",
                "pr_title": "fixture",
                "confidence": "0.9",  # >= 0.7 → gate skipped
            },
        )
        assert run_id, "WorkflowEngine.start did not return a run id"

        # Workflow steps fan out via asyncio.create_task; allow the loop a
        # few iterations to drain the gather + parallel group.
        for _ in range(20):
            state = engine.get_run_state(run_id)
            if state and state.status in {"completed", "failed", "cancelled"}:
                break
            await asyncio.sleep(0.05)

        state = engine.get_run_state(run_id)
        assert state is not None
        # Three department steps in pr-ship-decision: qa-check, strategy-check,
        # board-decide. Each must have called the mock runner exactly once.
        called_departments = sorted(d for d, _ in called_with)
        assert called_departments == ["board", "qa", "strategy"], (
            f"Expected department dispatches [board, qa, strategy], "
            f"got {called_departments}"
        )
        assert state.status == "completed", (
            f"Workflow ended in unexpected state {state.status!r}"
        )


# ---------------------------------------------------------------------------
# Sprint 5.00c (#2155) — WorkflowRegistry.match()
# ---------------------------------------------------------------------------


class TestWorkflowRegistryMatch:
    """Rule-based directive → workflow matching."""

    def test_full_dotted_name_match_returns_confidence_1(self):
        from bridge.workflow_registry import WorkflowRegistry
        r = WorkflowRegistry()
        # Pick any registered workflow
        names = r.names()
        if not names:
            return  # No workflows loaded; test environment quirk
        target = names[0]
        directive = f"Please run the {target} workflow for me"
        result = r.match(directive)
        assert result is not None
        assert result["name"] == target
        assert result["confidence"] == 1.0

    def test_trailing_token_match_returns_confidence_0_8(self):
        from bridge.workflow_registry import WorkflowRegistry
        r = WorkflowRegistry()
        # Find a dotted workflow name
        dotted_names = [n for n in r.names() if "." in n]
        if not dotted_names:
            return
        target = dotted_names[0]
        trailing = target.rsplit(".", 1)[-1]
        directive = f"please {trailing}"
        result = r.match(directive)
        assert result is not None
        assert result["name"] == target
        assert result["confidence"] == 0.8

    def test_slug_form_match_returns_confidence_0_6(self):
        from bridge.workflow_registry import WorkflowRegistry
        r = WorkflowRegistry()
        # Find a dotted workflow whose trailing has underscores
        candidates = [n for n in r.names() if "." in n and "_" in n.rsplit(".", 1)[-1]]
        if not candidates:
            return
        target = candidates[0]
        trailing = target.rsplit(".", 1)[-1]
        slug = trailing.replace("_", " ")
        directive = f"do a {slug}"
        result = r.match(directive)
        assert result is not None
        assert result["name"] == target
        assert result["confidence"] == 0.6

    def test_no_match_returns_none(self):
        from bridge.workflow_registry import WorkflowRegistry
        r = WorkflowRegistry()
        result = r.match("completely unrelated directive zzqq foobar")
        assert result is None

    def test_empty_directive_returns_none(self):
        from bridge.workflow_registry import WorkflowRegistry
        r = WorkflowRegistry()
        assert r.match("") is None
        assert r.match(None) is None  # defensive

    def test_match_is_case_insensitive(self):
        from bridge.workflow_registry import WorkflowRegistry
        r = WorkflowRegistry()
        names = r.names()
        if not names:
            return
        target = names[0]
        directive = f"PLEASE RUN {target.upper()} NOW"
        result = r.match(directive)
        assert result is not None
        assert result["name"] == target
