"""Pre-flag-flip dispatcher smoke-test subset (Sprint 03.09).

This file is the curated subset the operator runs as the smoke test
in the Sprint 03.08 flag-flip runbook. Invocation:

    cd agent && uv run pytest tests/test_dispatcher_smoke.py -v

What this covers (load-bearing dispatcher functionality):
  1. Dispatch validation (environment / status / unknown route)
  2. Route mapping (subagent / tmux / worktree / e2b / department)
  3. WorkOrder lifecycle — Sprint 03.01 ASSIGNED → EXECUTING transition
  4. Regression guards — circuit-breaker-open and dojo-gate early returns
     (no spurious transition / no double-invoke)
  5. Subagent + Department executor success / fall-through paths
  6. Executor timeout enforcement (issue #627)
  7. Environment selector skew detection (Sprint 03.07 anti-default-gravity)

Fall-through invariants enforced everywhere: if the dispatcher cannot fully
handle a WorkOrder, it returns ``handled=False`` so the caller falls through
to the direct ``claude_runner.invoke`` path. This file is a *guard* against
silent regressions in that contract.

Tests for sprints not yet merged are wrapped with ``pytest.importorskip``
guards or AttributeError-tolerant assertions so the suite stays green
during partial roll-out.
"""

from __future__ import annotations

import asyncio
from dataclasses import replace
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from bridge.dispatcher import Dispatcher, DispatchResult
from bridge.work_order import (
    Environment,
    WorkOrder,
    WorkOrderAssignment,
    WorkOrderConstraints,
    WorkOrderStatus,
)


# ---------------------------------------------------------------------------
# Local fixtures — self-contained, do not rely on test_dispatcher.py
# ---------------------------------------------------------------------------


@pytest.fixture
def dispatcher() -> Dispatcher:
    """A Dispatcher with mock tmux + event bus, no real claude_runner."""
    return Dispatcher(tmux_manager=MagicMock(), event_bus=MagicMock())


@pytest.fixture
def subagent_wo() -> WorkOrder:
    wo = WorkOrder.create(intent="Quick fix", skill="code-reviewer", project="p")
    return wo.with_environment(Environment.SUBAGENT, "Quick focused task")


def _make_department_wo(department: str = "engineering") -> WorkOrder:
    wo = WorkOrder.create(
        intent="Implement auth", skill="backend-architect", project="p"
    )
    wo = replace(wo, department_target=department)
    wo = wo.with_environment(Environment.DEPARTMENT, f"Route to {department}")
    return wo.transition(WorkOrderStatus.ASSIGNED)


def _build_executor_spy(
    captured_wos: list[WorkOrder] | None = None,
    *,
    is_error: bool = False,
) -> tuple[Dispatcher, MagicMock, AsyncMock]:
    """Build a Dispatcher whose SUBAGENT executor is a spy AsyncMock."""
    from bridge.claude_runner import ClaudeResult

    captured_wos = captured_wos if captured_wos is not None else []

    async def _spy_execute(wo: WorkOrder) -> ClaudeResult:
        captured_wos.append(wo)
        return ClaudeResult(
            response_text="ok",
            session_id="s1",
            is_error=is_error,
            error_type="boom" if is_error else "",
        )

    spy = AsyncMock(side_effect=_spy_execute)
    event_bus = MagicMock()
    disp = Dispatcher(tmux_manager=MagicMock(), event_bus=event_bus)
    fake_executor = MagicMock()
    fake_executor.execute = spy
    disp._executors[Environment.SUBAGENT] = fake_executor
    return disp, event_bus, spy


# ---------------------------------------------------------------------------
# 1. Validation paths — fast-fail before any executor is invoked
# ---------------------------------------------------------------------------


def test_smoke_validate_requires_environment(dispatcher: Dispatcher) -> None:
    """A WorkOrder with no environment must be rejected at validate stage."""
    wo = WorkOrder.create(intent="test", skill="test", project="test")
    result = dispatcher.validate_for_dispatch(wo)
    assert result.valid is False
    assert "environment" in result.reason.lower()


def test_smoke_validate_requires_assigned_status(
    dispatcher: Dispatcher, subagent_wo: WorkOrder
) -> None:
    """A non-ASSIGNED WorkOrder must be rejected at validate stage."""
    result = dispatcher.validate_for_dispatch(subagent_wo)  # CREATED, not ASSIGNED
    assert result.valid is False
    assert "assigned" in result.reason.lower()


def test_smoke_validate_passes_for_assigned_with_environment(
    dispatcher: Dispatcher, subagent_wo: WorkOrder
) -> None:
    """ASSIGNED WorkOrder with environment passes validation."""
    assigned = subagent_wo.transition(WorkOrderStatus.ASSIGNED)
    result = dispatcher.validate_for_dispatch(assigned)
    assert result.valid is True


# ---------------------------------------------------------------------------
# 2. Route mapping — every Environment must produce a stable route key
# ---------------------------------------------------------------------------


def test_smoke_route_keys_for_all_environments(dispatcher: Dispatcher) -> None:
    """Every Environment maps to its lowercased value as the route key."""
    assert dispatcher.get_route(Environment.SUBAGENT) == "subagent"
    assert dispatcher.get_route(Environment.TMUX) == "tmux"
    assert dispatcher.get_route(Environment.WORKTREE) == "worktree"
    assert dispatcher.get_route(Environment.E2B) == "e2b"
    assert dispatcher.get_route(Environment.DEPARTMENT) == "department"


# ---------------------------------------------------------------------------
# 3. WorkOrder lifecycle — Sprint 03.01 ASSIGNED → EXECUTING transition
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_smoke_executing_transition(subagent_wo: WorkOrder) -> None:
    """The WorkOrder reaching the executor must have status=EXECUTING (Sprint 03.01)."""
    captured: list[WorkOrder] = []
    disp, _bus, _spy = _build_executor_spy(captured_wos=captured)
    assigned = subagent_wo.transition(WorkOrderStatus.ASSIGNED)

    await disp.dispatch(assigned)

    assert len(captured) == 1, "executor.execute must be called exactly once"
    assert captured[0].status == WorkOrderStatus.EXECUTING, (
        "Sprint 03.01 wiring missing: executor saw "
        f"status={captured[0].status.value}, expected EXECUTING."
    )
    # Immutability: the original ASSIGNED instance is untouched.
    assert assigned.status == WorkOrderStatus.ASSIGNED


@pytest.mark.asyncio
async def test_smoke_executing_event_published(subagent_wo: WorkOrder) -> None:
    """A workorder.executing event must be published with route + skill + intent."""
    disp, event_bus, _spy = _build_executor_spy()
    assigned = subagent_wo.transition(WorkOrderStatus.ASSIGNED)

    await disp.dispatch(assigned)

    executing_calls = [
        call for call in event_bus.publish.call_args_list
        if call.args and call.args[0] == "workorder.executing"
    ]
    assert len(executing_calls) == 1, (
        "expected exactly one workorder.executing publish, got "
        f"{[c.args[0] for c in event_bus.publish.call_args_list]}"
    )
    payload = executing_calls[0].args[1]
    assert payload["workorder_id"] == assigned.id
    assert payload["environment"] == "subagent"
    assert payload["skill"] == assigned.skill
    assert payload["intent"] == assigned.intent


@pytest.mark.asyncio
async def test_smoke_dispatch_result_includes_workorder(
    subagent_wo: WorkOrder,
) -> None:
    """DispatchResult.workorder must be populated post-transition (chain hook for 03.03+).

    Each sprint of the state-machine roll-out (03.01 → 03.02 → 03.03)
    advances the final status one step further.  Accept any of the
    three so the smoke test survives the ordered roll-out:
      - EXECUTING : 03.01 only (entry transition wired, exit not yet)
      - VERIFYING : post-03.02  (exit transition wired, close not yet)
      - COMPLETE  : post-03.03  (close wired under verification-disabled
                                 default path)
    """
    disp, _bus, _spy = _build_executor_spy()
    assigned = subagent_wo.transition(WorkOrderStatus.ASSIGNED)

    result = await disp.dispatch(assigned)

    # Sprint 03.02 / 03.03 chain off this attribute. Skip if 03.01 hasn't shipped.
    if not hasattr(result, "workorder"):
        pytest.skip("DispatchResult.workorder field not present — Sprint 03.01 not deployed yet")
    assert result.workorder is not None
    assert result.workorder.status in (
        WorkOrderStatus.EXECUTING,  # pre-03.02
        WorkOrderStatus.VERIFYING,  # post-03.02
        WorkOrderStatus.COMPLETE,   # post-03.03
    ), (
        f"unexpected post-dispatch status: {result.workorder.status.value}"
    )
    assert result.workorder.id == assigned.id


# ---------------------------------------------------------------------------
# 4. Regression guards — circuit-breaker + dojo-gate early returns
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_smoke_circuit_breaker_open_does_not_transition(
    subagent_wo: WorkOrder,
) -> None:
    """Open breaker returns BEFORE _run_executor — no transition, no executor call."""
    disp, event_bus, spy = _build_executor_spy()
    breaker = disp._breakers["subagent"]
    for _ in range(3):  # failure_threshold=3
        breaker.record_failure()
    assert breaker.is_available is False

    assigned = subagent_wo.transition(WorkOrderStatus.ASSIGNED)
    result = await disp.dispatch(assigned)

    assert result.valid is True
    assert result.handled is False
    assert "circuit open" in result.reason
    spy.assert_not_called()
    executing_calls = [
        c for c in event_bus.publish.call_args_list
        if c.args and c.args[0] == "workorder.executing"
    ]
    assert executing_calls == [], "no transition event must fire when breaker is open"


@pytest.mark.asyncio
async def test_smoke_dojo_gate_blocked_does_not_transition() -> None:
    """Dojo trust-floor block returns BEFORE _run_executor (issue #628 regression)."""
    from bridge.claude_runner import ClaudeResult

    captured: list[WorkOrder] = []

    async def _spy_execute(wo: WorkOrder) -> ClaudeResult:
        captured.append(wo)
        return ClaudeResult(response_text="ok", session_id="s1")

    spy = AsyncMock(side_effect=_spy_execute)
    event_bus = MagicMock()
    trust_manager = MagicMock()
    trust_manager.get_skill_proficiency = MagicMock(return_value=0.10)

    disp = Dispatcher(
        tmux_manager=MagicMock(),
        event_bus=event_bus,
        trust_manager=trust_manager,
    )
    fake_executor = MagicMock()
    fake_executor.execute = spy
    disp._executors[Environment.SUBAGENT] = fake_executor
    disp._skill_floors["code-reviewer"] = 0.80  # force the gate

    wo = WorkOrder.create(intent="Quick fix", skill="code-reviewer", project="p")
    wo = wo.with_environment(Environment.SUBAGENT, "Quick task")
    wo = wo.with_assignment(WorkOrderAssignment(agent_type="t", agent_id="a-1"))
    assigned = wo.transition(WorkOrderStatus.ASSIGNED)

    result = await disp.dispatch(assigned)

    assert result.valid is True
    assert result.handled is False, (
        "Dojo gate must return handled=False — handled=True with no result "
        "would cause double-invocation (issue #628)."
    )
    assert "dojo floor" in result.reason
    spy.assert_not_called()


def test_smoke_dojo_gate_publishes_event_for_observability() -> None:
    """Static-analysis guard: dojo gate still emits 'dojo.gated' event."""
    src = Path(__file__).parent.parent / "bridge" / "dispatcher.py"
    text = src.read_text()
    assert "dojo.gated" in text, (
        "Dojo gate no longer publishes 'dojo.gated' to the event bus — "
        "observability was lost. See issue #628 regression test."
    )


# ---------------------------------------------------------------------------
# 5. Subagent + Department dispatch — success and fall-through
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_smoke_subagent_success(subagent_wo: WorkOrder) -> None:
    """Subagent dispatch with a healthy runner returns handled=True with a ClaudeResult."""
    from bridge.claude_runner import ClaudeResult

    mock_runner = AsyncMock()
    mock_runner.invoke = AsyncMock(
        return_value=ClaudeResult(response_text="Done", session_id="s1")
    )
    disp = Dispatcher(
        tmux_manager=MagicMock(), event_bus=MagicMock(), claude_runner=mock_runner
    )
    assigned = subagent_wo.transition(WorkOrderStatus.ASSIGNED)
    result = await disp.dispatch(assigned)

    assert result.valid is True
    assert result.handled is True
    assert result.result is not None
    assert result.result.response_text == "Done"


@pytest.mark.asyncio
async def test_smoke_department_success() -> None:
    """Department dispatch with a healthy registry wraps TeamResult as ClaudeResult."""
    from teams._types import TeamResult

    team_result = TeamResult(
        department="engineering",
        manager_output="Auth module implemented",
        success=True,
        total_cost_usd=0.05,
        duration_seconds=2.5,
    )
    mock_registry = MagicMock()
    mock_registry.department_names.return_value = ["engineering"]
    mock_registry.route = AsyncMock(return_value=team_result)

    disp = Dispatcher(
        tmux_manager=MagicMock(),
        event_bus=MagicMock(),
        department_registry=mock_registry,
    )
    wo = _make_department_wo(department="engineering")
    result = await disp.dispatch(wo)

    assert result.valid is True
    assert result.handled is True
    assert result.result is not None
    assert result.result.response_text == "Auth module implemented"


@pytest.mark.asyncio
async def test_smoke_department_unknown_falls_through() -> None:
    """Unknown department_target falls through with a clear reason."""
    mock_registry = MagicMock()
    mock_registry.department_names.return_value = ["engineering", "qa"]

    disp = Dispatcher(
        tmux_manager=MagicMock(),
        event_bus=MagicMock(),
        department_registry=mock_registry,
    )
    wo = _make_department_wo(department="nonexistent")
    result = await disp.dispatch(wo)

    assert result.valid is True
    assert result.handled is False
    assert "unknown department" in result.reason
    assert "nonexistent" in result.reason


# ---------------------------------------------------------------------------
# 6. Executor timeout enforcement (issue #627)
# ---------------------------------------------------------------------------


def test_smoke_dispatcher_uses_wait_for() -> None:
    """Static-analysis guard: dispatcher.py must wrap executor calls in asyncio.wait_for."""
    src = Path(__file__).parent.parent / "bridge" / "dispatcher.py"
    text = src.read_text()
    assert "import asyncio" in text
    assert "asyncio.wait_for" in text
    assert "asyncio.TimeoutError" in text
    assert "executor timeout" in text
    assert 'record_dispatch_fallthrough("timeout")' in text


@pytest.mark.asyncio
async def test_smoke_executor_timeout_falls_through() -> None:
    """A slow executor must trigger handled=False with reason='executor timeout'."""
    wo = WorkOrder(
        skill="test-skill",
        intent="test intent",
        environment=Environment.SUBAGENT,
        status=WorkOrderStatus.ASSIGNED,
        constraints=WorkOrderConstraints(timeout_ms=10),
        assignment=WorkOrderAssignment(agent_id="agent-1"),
    )

    async def _slow_execute(_wo: Any) -> Any:
        await asyncio.sleep(10)

    mock_executor = MagicMock()
    mock_executor.execute = _slow_execute

    disp = Dispatcher.__new__(Dispatcher)
    result = await disp._run_executor(mock_executor, wo, "subagent")

    assert isinstance(result, DispatchResult)
    assert result.valid is True
    assert result.handled is False
    assert result.reason == "executor timeout"


# ---------------------------------------------------------------------------
# 7. Environment selector skew (Sprint 03.07 anti-default-gravity)
# ---------------------------------------------------------------------------


def test_smoke_environment_selector_skew_detection() -> None:
    """EnvironmentSelector reports skew when one env dominates the recent window.

    Sprint 03.07 ships dispatch-side hooks that read this selector. Until
    then the module/class exists but isn't wired into dispatch. This test
    asserts the underlying detector still works so 03.07 has solid ground
    to wire against.
    """
    es_mod = pytest.importorskip(
        "bridge.environment_selector",
        reason="bridge.environment_selector not present — Sprint 03.07 not deployed",
    )
    EnvironmentSelector = getattr(es_mod, "EnvironmentSelector", None)
    if EnvironmentSelector is None:
        pytest.skip("EnvironmentSelector class not present — Sprint 03.07 not deployed")

    selector = EnvironmentSelector(skew_threshold=0.6)
    # Drive a strong skew: 7 SUBAGENT vs 3 TMUX → 70% > 60% threshold.
    for _ in range(7):
        selector.record_usage(Environment.SUBAGENT)
    for _ in range(3):
        selector.record_usage(Environment.TMUX)

    assert selector.is_skewed() is True, (
        "Anti-default-gravity guard missing: 7/10 SUBAGENT records "
        "must register as skewed at threshold=0.6."
    )
