"""Tests for WorkOrder data model."""

from __future__ import annotations

import pytest

from bridge.work_order import (
    Environment,
    WorkOrder,
    WorkOrderInput,
    WorkOrderContext,
    WorkOrderStatus,
    InvalidTransitionError,
)


def test_status_enum_values() -> None:
    assert WorkOrderStatus.PENDING.value == "pending"
    assert WorkOrderStatus.ASSIGNED.value == "assigned"
    assert WorkOrderStatus.EXECUTING.value == "executing"
    assert WorkOrderStatus.VERIFYING.value == "verifying"
    assert WorkOrderStatus.COMPLETE.value == "complete"
    assert WorkOrderStatus.FAILED.value == "failed"


def test_environment_enum_values() -> None:
    assert Environment.SUBAGENT.value == "subagent"
    assert Environment.TMUX.value == "tmux"
    assert Environment.WORKTREE.value == "worktree"
    assert Environment.E2B.value == "e2b"
    assert Environment.DEPARTMENT.value == "department"


def test_environment_department_roundtrip() -> None:
    """DEPARTMENT environment survives to_dict/from_dict roundtrip."""
    wo = WorkOrder.create(
        intent="Analyze competitive landscape",
        skill="strategy-chief",
        project="bumba",
    )
    wo = wo.with_environment(Environment.DEPARTMENT, "Routed to strategy department")
    data = wo.to_dict()
    assert data["environment"] == "department"
    restored = WorkOrder.from_dict(data)
    assert restored.environment == Environment.DEPARTMENT


def test_create_work_order() -> None:
    wo = WorkOrder.create(
        intent="Implement user authentication API",
        skill="backend-architect",
        project="my-project",
    )
    assert wo.id != ""
    assert wo.status == WorkOrderStatus.PENDING
    assert wo.intent == "Implement user authentication API"
    assert wo.skill == "backend-architect"
    assert wo.project == "my-project"
    assert wo.parent_id is None


def test_create_child_work_order() -> None:
    parent = WorkOrder.create(intent="Build auth system", skill="chief", project="proj")
    child = WorkOrder.create(
        intent="Build JWT middleware",
        skill="backend-architect",
        project="proj",
        parent_id=parent.id,
    )
    assert child.parent_id == parent.id


def test_valid_transitions() -> None:
    wo = WorkOrder.create(intent="test", skill="test", project="test")
    assert wo.status == WorkOrderStatus.PENDING

    wo = wo.transition(WorkOrderStatus.ASSIGNED)
    assert wo.status == WorkOrderStatus.ASSIGNED

    wo = wo.transition(WorkOrderStatus.EXECUTING)
    assert wo.status == WorkOrderStatus.EXECUTING

    wo = wo.transition(WorkOrderStatus.VERIFYING)
    assert wo.status == WorkOrderStatus.VERIFYING

    wo = wo.transition(WorkOrderStatus.COMPLETE)
    assert wo.status == WorkOrderStatus.COMPLETE


def test_invalid_transition_raises() -> None:
    wo = WorkOrder.create(intent="test", skill="test", project="test")
    with pytest.raises(InvalidTransitionError):
        wo.transition(WorkOrderStatus.COMPLETE)


def test_transition_to_failed_from_any_active() -> None:
    """FAILED should be reachable from any non-terminal status."""
    for status in [
        WorkOrderStatus.PENDING,
        WorkOrderStatus.ASSIGNED,
        WorkOrderStatus.EXECUTING,
        WorkOrderStatus.VERIFYING,
    ]:
        wo = WorkOrder.create(intent="test", skill="test", project="test")
        wo = WorkOrder(
            id=wo.id, intent=wo.intent, skill=wo.skill, project=wo.project,
            status=status,
            input=wo.input, constraints=wo.constraints, output=wo.output,
            environment=wo.environment, environment_rationale=wo.environment_rationale,
            parent_id=wo.parent_id, context_id=wo.context_id,
            assignment=wo.assignment, execution=wo.execution,
            dependencies=wo.dependencies, output_schema=wo.output_schema,
        )
        result = wo.transition(WorkOrderStatus.FAILED)
        assert result.status == WorkOrderStatus.FAILED


def test_verifying_to_executing_rework_loop() -> None:
    wo = WorkOrder.create(intent="test", skill="test", project="test")
    wo = wo.transition(WorkOrderStatus.ASSIGNED)
    wo = wo.transition(WorkOrderStatus.EXECUTING)
    wo = wo.transition(WorkOrderStatus.VERIFYING)
    wo = wo.transition(WorkOrderStatus.EXECUTING)
    assert wo.status == WorkOrderStatus.EXECUTING


def test_immutability_on_transition() -> None:
    wo = WorkOrder.create(intent="test", skill="test", project="test")
    wo2 = wo.transition(WorkOrderStatus.ASSIGNED)
    assert wo.status == WorkOrderStatus.PENDING
    assert wo2.status == WorkOrderStatus.ASSIGNED
    assert wo.id == wo2.id


def test_set_environment() -> None:
    wo = WorkOrder.create(intent="test", skill="test", project="test")
    wo2 = wo.with_environment(Environment.TMUX, "Parallel work needed — two independent modules")
    assert wo2.environment == Environment.TMUX
    assert wo2.environment_rationale == "Parallel work needed — two independent modules"
    assert wo.environment is None


def test_set_input_context() -> None:
    ctx = WorkOrderContext(
        spec_section="Section 3.2",
        prerequisite_outputs=["wo-001-result.json"],
        constraints=["Must use existing JWT middleware"],
    )
    inp = WorkOrderInput(
        text="Implement auth API",
        files=["src/auth/"],
        context=ctx,
    )
    wo = WorkOrder.create(intent="test", skill="test", project="test")
    wo2 = wo.with_input(inp)
    assert wo2.input.text == "Implement auth API"
    assert wo2.input.context.spec_section == "Section 3.2"


def test_to_dict_roundtrip() -> None:
    wo = WorkOrder.create(
        intent="Build API",
        skill="api-engineer",
        project="my-proj",
    )
    wo = wo.with_environment(Environment.SUBAGENT, "Quick focused task")
    data = wo.to_dict()
    assert data["intent"] == "Build API"
    assert data["environment"] == "subagent"
    assert data["environment_rationale"] == "Quick focused task"
    assert data["status"] == "pending"

    restored = WorkOrder.from_dict(data)
    assert restored.id == wo.id
    assert restored.intent == wo.intent
    assert restored.environment == wo.environment


def test_department_target_field() -> None:
    """department_target is None by default and round-trips through dict."""
    wo = WorkOrder.create(intent="test", skill="test", project="test")
    assert wo.department_target is None

    from dataclasses import replace
    wo2 = replace(wo, department_target="engineering")
    assert wo2.department_target == "engineering"

    data = wo2.to_dict()
    assert data["department_target"] == "engineering"

    restored = WorkOrder.from_dict(data)
    assert restored.department_target == "engineering"


def test_department_target_none_roundtrip() -> None:
    """department_target=None round-trips correctly."""
    wo = WorkOrder.create(intent="test", skill="test", project="test")
    data = wo.to_dict()
    assert data["department_target"] is None

    restored = WorkOrder.from_dict(data)
    assert restored.department_target is None


# ---------------------------------------------------------------------------
# Sprint 03.04 — with_department() helper for plumbing department_target
# through the 3 production WorkOrder creation sites (app.py dispatcher,
# api_server.py external ingestion, commands.py /dispatch).
# ---------------------------------------------------------------------------


def test_with_department_sets_field() -> None:
    """with_department() returns a WorkOrder with the supplied dept on department_target."""
    wo = WorkOrder.create(intent="Convene the board", skill="board", project="bumba")
    assert wo.department_target is None
    wo2 = wo.with_department("board")
    assert wo2.department_target == "board"


def test_with_department_returns_new_instance() -> None:
    """with_department() must not mutate the receiver — frozen dataclass invariant."""
    wo = WorkOrder.create(intent="QA review", skill="qa-tests", project="bumba")
    wo2 = wo.with_department("qa")
    # Different instance, same id — original untouched.
    assert wo is not wo2
    assert wo.department_target is None
    assert wo2.department_target == "qa"
    assert wo.id == wo2.id
