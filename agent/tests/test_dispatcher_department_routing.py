"""Sprint 03.04 — integration tests for department_target plumbing.

Background (R3 A3): WorkOrder.department_target had zero production
callers. Skills classified as "department" by EnvironmentSelector were
routed to DepartmentExecutor.execute, which immediately raised
``ValueError("unknown department: ")`` because the registry has no entry
for an empty string.  Every department dispatch silently burned a retry.

Sprint 03.04 plumbs the field through 3 production WorkOrder creation
sites (app.py dispatcher, api_server.py external ingestion, commands.py
``/dispatch``).  These integration tests verify the end-to-end contract:
a board-classified skill arrives at DepartmentExecutor with
``department_target == "board"`` instead of None.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from bridge.dispatcher import Dispatcher
from bridge.environment_selector import EnvironmentSelector, _derive_department
from bridge.work_order import Environment, WorkOrder, WorkOrderStatus


def _build_wo_like_dispatcher_branch(skill: str) -> WorkOrder:
    """Replicate the construction sequence used in app.py:1826-1871.

    The harness must mirror production: classify skill → choose env via
    selector → derive department → with_environment → with_department →
    transition(ASSIGNED).  A regression in any helper is caught here.
    """
    wo = WorkOrder.create(intent="convene the board", skill=skill, project="bumba")
    selector = EnvironmentSelector()
    env, rationale = selector.select(wo)
    wo = wo.with_environment(env, rationale)
    dept = _derive_department(skill)
    if dept is not None and env is Environment.DEPARTMENT:
        wo = wo.with_department(dept)
    return wo.transition(WorkOrderStatus.ASSIGNED)


@pytest.mark.asyncio
async def test_board_skill_reaches_department_executor_with_target_set() -> None:
    """A board-classified skill → DepartmentExecutor sees department_target='board'.

    This is the headline integration test for Sprint 03.04.  Pre-fix this
    would arrive with department_target=None and DepartmentExecutor would
    raise ValueError("unknown department: ").
    """
    from teams._types import TeamResult

    captured_wo: list[WorkOrder] = []

    async def _capture_route(dept: str, intent: str, deps: object) -> TeamResult:
        # We capture the dept argument the registry sees; the WO itself
        # is captured via the executor wrapper below.
        return TeamResult(
            department=dept,
            manager_output="ok",
            success=True,
            total_cost_usd=0.0,
            duration_seconds=0.1,
        )

    mock_registry = MagicMock()
    mock_registry.department_names.return_value = ["board"]
    mock_registry.route = AsyncMock(side_effect=_capture_route)
    mock_registry.get_cost_limit = MagicMock(return_value=2.0)

    dispatcher = Dispatcher(
        tmux_manager=MagicMock(),
        event_bus=MagicMock(),
        department_registry=mock_registry,
    )

    # Wrap the actual DepartmentExecutor's execute to capture the WO that
    # arrives.  This is exactly the spot the bug bit: dept = wo.department_target
    # used to be None.
    real_executor = dispatcher._executors[Environment.DEPARTMENT]
    real_execute = real_executor.execute

    async def _wrap_execute(wo: WorkOrder):  # type: ignore[no-untyped-def]
        captured_wo.append(wo)
        return await real_execute(wo)

    real_executor.execute = _wrap_execute  # type: ignore[method-assign]

    wo = _build_wo_like_dispatcher_branch(skill="board")
    assert wo.environment is Environment.DEPARTMENT
    assert wo.department_target == "board"

    result = await dispatcher.dispatch(wo)

    assert result.valid is True
    assert result.handled is True
    assert len(captured_wo) == 1
    # The WorkOrder that reached the executor carries the department_target.
    assert captured_wo[0].department_target == "board"
    # Registry was queried with the same name.
    mock_registry.route.assert_awaited_once()
    args, _ = mock_registry.route.await_args
    assert args[0] == "board"


@pytest.mark.asyncio
async def test_board_skill_without_with_department_raises_unknown() -> None:
    """Regression guard: prior to Sprint 03.04 the department_target was
    never set, so DepartmentExecutor.execute raised "unknown department: ".

    This test reproduces the pre-fix path explicitly: build the WO, route
    it to DEPARTMENT, BUT skip the with_department call — exactly what
    every production caller did before this sprint. The dispatcher catches
    the ValueError and falls through with handled=False.
    """
    mock_registry = MagicMock()
    mock_registry.department_names.return_value = ["board"]
    mock_registry.route = AsyncMock()

    dispatcher = Dispatcher(
        tmux_manager=MagicMock(),
        event_bus=MagicMock(),
        department_registry=mock_registry,
    )

    wo = WorkOrder.create(intent="convene", skill="board", project="bumba")
    wo = wo.with_environment(Environment.DEPARTMENT, "department-default: department")
    # Intentionally do NOT call with_department — pre-Sprint-03.04 behavior.
    wo = wo.transition(WorkOrderStatus.ASSIGNED)
    assert wo.department_target is None

    result = await dispatcher.dispatch(wo)

    # Dispatcher catches the ValueError and falls through. The point is:
    # without with_department(), the registry is never invoked.
    assert result.valid is True
    assert result.handled is False
    mock_registry.route.assert_not_awaited()


def test_non_department_skill_keeps_department_target_none() -> None:
    """Regression guard: skills not in _SKILL_CLASS_RULES must yield
    department_target=None after going through the dispatcher branch
    construction sequence. If a stray skill picked up a department, every
    DEPARTMENT-routed WO would be poisoned.
    """
    # Filesystem-class skill — classified as filesystem, env=WORKTREE.
    wo = _build_wo_like_dispatcher_branch(skill="fix-test-flake")
    assert wo.environment is Environment.WORKTREE
    assert wo.department_target is None

    # Readonly-class skill — classified as readonly, env=SUBAGENT.
    wo2 = _build_wo_like_dispatcher_branch(skill="explain-this")
    assert wo2.environment is Environment.SUBAGENT
    assert wo2.department_target is None

    # Truly unknown skill — falls back to readonly default.
    wo3 = _build_wo_like_dispatcher_branch(skill="never-seen-before-skill")
    assert wo3.environment is Environment.SUBAGENT
    assert wo3.department_target is None


def test_environment_not_department_skips_with_department() -> None:
    """If selector picked a non-DEPARTMENT env, with_department is skipped
    even when _derive_department returns a value. This is a defensive
    invariant — the skill matched a department rule but the env was
    overridden, so the department_target must not leak through.
    """
    # Manually construct: skill="board" (department-class) but force
    # env=SUBAGENT to simulate an override path.
    wo = WorkOrder.create(intent="x", skill="board", project="bumba")
    wo = wo.with_environment(Environment.SUBAGENT, "manual-override")
    dept = _derive_department("board")
    assert dept == "board"
    # Production guard: only call with_department when env is DEPARTMENT.
    if dept is not None and wo.environment is Environment.DEPARTMENT:
        wo = wo.with_department(dept)
    assert wo.department_target is None
