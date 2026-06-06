"""Tests for workflow-level budget aggregate cost cap (sprint F-W.7)."""

from __future__ import annotations

import asyncio
import textwrap

import pytest

pytest.importorskip("pydantic")
pytest.importorskip("yaml")

from bridge.workflow_engine import WorkflowEngine
from config.workflows._schema import WorkflowBudget, WorkflowConfig, load_workflow_config


BUDGET_WORKFLOW = textwrap.dedent(
    """\
    name: budget-test
    trigger: explicit
    budget:
      max_cost_usd: 0.5
      max_duration_seconds: 30
    steps:
      - name: step-cheap
        department: strategy
        intent: "Cheap step"
        outputs: [cheap_result]
        cost_limit_usd: 0.1

      - name: step-expensive
        department: board
        intent: "Expensive step"
        outputs: [expensive_result]
        cost_limit_usd: 0.6
    """
)

NO_PER_STEP_CAP_WORKFLOW = textwrap.dedent(
    """\
    name: aggregate-budget-test
    trigger: explicit
    budget:
      max_cost_usd: 0.3
    steps:
      - name: step-1
        department: ops
        intent: "Step 1"
        outputs: [r1]

      - name: step-2
        department: qa
        intent: "Step 2"
        outputs: [r2]

      - name: step-3
        department: strategy
        intent: "Step 3"
        outputs: [r3]
    """
)


class TestWorkflowBudgetSchema:
    def test_budget_fields_validated(self) -> None:
        cfg = load_workflow_config(
            textwrap.dedent(
                """\
                name: budget-schema
                trigger: explicit
                budget:
                  max_cost_usd: 3.0
                  max_duration_seconds: 120
                steps: []
                """
            )
        )
        assert cfg.budget.max_cost_usd == 3.0
        assert cfg.budget.max_duration_seconds == 120

    def test_budget_defaults(self) -> None:

        cfg = WorkflowConfig(name="wf", trigger="explicit", steps=[])
        assert cfg.budget.max_cost_usd == 5.0
        assert cfg.budget.max_duration_seconds == 600

    def test_zero_cost_invalid(self) -> None:
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            WorkflowBudget(max_cost_usd=0)


class TestBudgetEnforcement:
    @pytest.mark.asyncio
    async def test_pre_step_budget_check_blocks_expensive_step(self) -> None:
        """When step's cost_limit_usd would exceed cap, engine halts before dispatching."""
        cfg = load_workflow_config(BUDGET_WORKFLOW)

        dispatched: list[str] = []

        async def dept_runner(dept, intent, ctx):
            dispatched.append(dept)
            # cheap step costs 0.1
            return "result", 0.1

        engine = WorkflowEngine(department_runner=dept_runner)
        run_id = engine.start(cfg)
        await asyncio.sleep(0.1)

        state = engine.get_run_state(run_id)
        assert state is not None
        assert state.status == "failed"
        # Only the cheap step should have dispatched
        assert dispatched == ["strategy"]

    @pytest.mark.asyncio
    async def test_aggregate_cost_check_after_steps(self) -> None:
        """Aggregate check: workflow fails when cumulative cost crosses cap mid-run."""
        cfg = load_workflow_config(NO_PER_STEP_CAP_WORKFLOW)

        step_cost = 0.15  # 3 steps × $0.15 = $0.45 > $0.30 cap

        async def dept_runner(dept, intent, ctx):
            return "ok", step_cost

        engine = WorkflowEngine(department_runner=dept_runner)
        run_id = engine.start(cfg)
        await asyncio.sleep(0.1)

        state = engine.get_run_state(run_id)
        assert state is not None
        assert state.status == "failed"
        # Should have stopped at or after step 2 ($0.30 → $0.30 exactly hits cap)
        assert state.cost_usd >= 0.30

    @pytest.mark.asyncio
    async def test_workflow_succeeds_within_budget(self) -> None:
        """Workflow completes when total cost stays within cap."""
        cfg = load_workflow_config(
            textwrap.dedent(
                """\
                name: within-budget
                trigger: explicit
                budget:
                  max_cost_usd: 1.0
                steps:
                  - name: s1
                    department: ops
                    intent: "Step 1"
                    outputs: [r1]
                  - name: s2
                    department: qa
                    intent: "Step 2"
                    outputs: [r2]
                """
            )
        )

        async def dept_runner(dept, intent, ctx):
            return "ok", 0.1

        engine = WorkflowEngine(department_runner=dept_runner)
        run_id = engine.start(cfg)
        await asyncio.sleep(0.1)

        state = engine.get_run_state(run_id)
        assert state is not None
        assert state.status == "completed"
        assert state.cost_usd == pytest.approx(0.2)

    @pytest.mark.asyncio
    async def test_budget_exceeded_event_published(self) -> None:
        """z4.workflow.budget_exceeded is published when budget is exceeded."""
        cfg = load_workflow_config(BUDGET_WORKFLOW)

        published_events: list[str] = []

        class FakeEventBus:
            def publish(self, event_type, payload, source):
                published_events.append(event_type)

        async def dept_runner(dept, intent, ctx):
            return "ok", 0.1

        engine = WorkflowEngine(
            department_runner=dept_runner,
            event_bus=FakeEventBus(),
        )
        run_id = engine.start(cfg)
        await asyncio.sleep(0.1)

        assert "z4.workflow.budget_exceeded" in published_events
