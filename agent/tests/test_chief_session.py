"""Tests for `bridge.chief_session` — Z4-S01 (#1385).

Coverage:
- ID generator format
- Default-state construction + auto-set timestamps
- All 11 valid transitions in `_ALLOWED_TRANSITIONS`
- 7 representative invalid transitions (>5 per acceptance criteria)
- Run-count semantics on requeue path
- Timestamp side effects on each transition class
- `add_cost`, `is_terminal`, `is_idle` helpers
- audit-2026-05-16.D.04 (#2065): chief-session cost-cap dependency
  wiring through the dispatcher — strict-mode fail-closed behaviour
  and the WarmChief ``cost_tracker`` hand-off.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from decimal import Decimal
from unittest import mock

import pytest

from bridge.chief_session import (
    ChiefSession,
    ChiefSessionState,
    InvalidTransitionError,
    new_chief_session_id,
)


def _make(state: ChiefSessionState = ChiefSessionState.COLD) -> ChiefSession:
    """Build a stub ChiefSession in the given state."""
    return ChiefSession(
        session_id="cs-test01abcdef",
        work_order_id="wo-test",
        department="strategy",
        chief_name="strategy-product-chief",
        state=state,
    )


# ---------------------------------------------------------------------------
# ID generator
# ---------------------------------------------------------------------------


class TestNewChiefSessionId:
    def test_format_is_cs_prefix_plus_12_hex(self):
        ident = new_chief_session_id()
        assert re.fullmatch(r"cs-[0-9a-f]{12}", ident), ident

    def test_ids_are_unique(self):
        # 1000 ids should not collide (96-bit entropy makes collision
        # vanishingly improbable; this is the cheap regression guard for
        # an accidentally-deterministic generator).
        ids = {new_chief_session_id() for _ in range(1000)}
        assert len(ids) == 1000


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


class TestConstruction:
    def test_default_state_is_cold(self):
        s = _make()
        assert s.state == ChiefSessionState.COLD

    def test_created_at_is_tz_aware_utc(self):
        s = _make()
        assert s.created_at_utc.tzinfo is not None
        assert s.created_at_utc.utcoffset() == timezone.utc.utcoffset(None)

    def test_run_count_defaults_to_zero(self):
        assert _make().run_count == 0

    def test_cost_usd_defaults_to_zero(self):
        assert _make().cost_usd == 0.0

    def test_metadata_defaults_to_empty_dict(self):
        s = _make()
        assert s.metadata == {}
        # Confirm the default_factory isolates instances (no shared mutable default)
        s.metadata["key"] = "value"
        assert _make().metadata == {}


# ---------------------------------------------------------------------------
# Valid transitions — covers every edge in _ALLOWED_TRANSITIONS
# ---------------------------------------------------------------------------


_VALID_TRANSITIONS = [
    # COLD ─►
    (ChiefSessionState.COLD, ChiefSessionState.WARM),
    (ChiefSessionState.COLD, ChiefSessionState.SHUTDOWN),
    # WARM ─►
    (ChiefSessionState.WARM, ChiefSessionState.EXECUTING),
    (ChiefSessionState.WARM, ChiefSessionState.SHUTDOWN),
    # EXECUTING ─►
    (ChiefSessionState.EXECUTING, ChiefSessionState.AWAITING_EVALUATION),
    (ChiefSessionState.EXECUTING, ChiefSessionState.FAILED),
    (ChiefSessionState.EXECUTING, ChiefSessionState.TIMED_OUT),
    # AWAITING_EVALUATION ─►
    (ChiefSessionState.AWAITING_EVALUATION, ChiefSessionState.DONE),
    (ChiefSessionState.AWAITING_EVALUATION, ChiefSessionState.FAILED),
    (ChiefSessionState.AWAITING_EVALUATION, ChiefSessionState.TIMED_OUT),
    (ChiefSessionState.AWAITING_EVALUATION, ChiefSessionState.WARM),  # requeue
    # DONE ─►
    (ChiefSessionState.DONE, ChiefSessionState.SHUTDOWN),
    # FAILED ─►
    (ChiefSessionState.FAILED, ChiefSessionState.SHUTDOWN),
    (ChiefSessionState.FAILED, ChiefSessionState.WARM),  # retry path
    # TIMED_OUT ─►
    (ChiefSessionState.TIMED_OUT, ChiefSessionState.SHUTDOWN),
]


@pytest.mark.parametrize(("from_s", "to_s"), _VALID_TRANSITIONS)
def test_valid_transitions(from_s: ChiefSessionState, to_s: ChiefSessionState):
    session = _make(from_s)
    result = session.transition(to_s)
    assert result.state == to_s
    # Original session is not mutated (immutable-update convention)
    assert session.state == from_s


# ---------------------------------------------------------------------------
# Invalid transitions — at least 5 per acceptance criteria
# ---------------------------------------------------------------------------


_INVALID_TRANSITIONS = [
    # Skipping intermediate states
    (ChiefSessionState.COLD, ChiefSessionState.EXECUTING),
    (ChiefSessionState.WARM, ChiefSessionState.AWAITING_EVALUATION),
    # Going backwards from a "completed" state to mid-pipeline
    (ChiefSessionState.EXECUTING, ChiefSessionState.WARM),
    (ChiefSessionState.EXECUTING, ChiefSessionState.DONE),
    (ChiefSessionState.DONE, ChiefSessionState.EXECUTING),
    # SHUTDOWN is terminal — nothing leaves it
    (ChiefSessionState.SHUTDOWN, ChiefSessionState.WARM),
    (ChiefSessionState.SHUTDOWN, ChiefSessionState.COLD),
    # TIMED_OUT can only go to SHUTDOWN
    (ChiefSessionState.TIMED_OUT, ChiefSessionState.WARM),
    (ChiefSessionState.TIMED_OUT, ChiefSessionState.EXECUTING),
]


@pytest.mark.parametrize(("from_s", "to_s"), _INVALID_TRANSITIONS)
def test_invalid_transitions(from_s: ChiefSessionState, to_s: ChiefSessionState):
    session = _make(from_s)
    with pytest.raises(InvalidTransitionError) as exc_info:
        session.transition(to_s)
    # Exception carries both ends of the bad edge for log triage
    assert exc_info.value.from_state == from_s
    assert exc_info.value.to_state == to_s


# ---------------------------------------------------------------------------
# Transition side effects — timestamps + run_count
# ---------------------------------------------------------------------------


class TestTransitionSideEffects:
    def test_warm_sets_warmed_at_on_first_warm_only(self):
        s0 = _make(ChiefSessionState.COLD)
        s1 = s0.transition(ChiefSessionState.WARM)
        assert s1.warmed_at_utc is not None
        first_warm = s1.warmed_at_utc

        # Drive through to AWAITING_EVALUATION then re-warm via requeue
        s2 = s1.transition(ChiefSessionState.EXECUTING)
        s3 = s2.transition(ChiefSessionState.AWAITING_EVALUATION)
        s4 = s3.transition(ChiefSessionState.WARM)  # requeue

        # warmed_at_utc must NOT be overwritten on re-warm
        assert s4.warmed_at_utc == first_warm

    def test_executing_increments_run_count(self):
        s0 = _make(ChiefSessionState.COLD)
        s1 = s0.transition(ChiefSessionState.WARM)
        assert s1.run_count == 0  # not incremented yet
        s2 = s1.transition(ChiefSessionState.EXECUTING)
        assert s2.run_count == 1
        s3 = s2.transition(ChiefSessionState.AWAITING_EVALUATION)
        s4 = s3.transition(ChiefSessionState.WARM)
        s5 = s4.transition(ChiefSessionState.EXECUTING)
        assert s5.run_count == 2

    def test_executing_sets_execution_started_and_clears_idle(self):
        s = _make(ChiefSessionState.AWAITING_EVALUATION)
        s = ChiefSession(**{**s.__dict__, "idle_since_utc": datetime.now(timezone.utc)})
        s_warm = s.transition(ChiefSessionState.WARM)
        s_exec = s_warm.transition(ChiefSessionState.EXECUTING)
        assert s_exec.execution_started_at_utc is not None
        assert s_exec.idle_since_utc is None

    def test_awaiting_evaluation_sets_idle_since(self):
        s = _make(ChiefSessionState.EXECUTING)
        s2 = s.transition(ChiefSessionState.AWAITING_EVALUATION)
        assert s2.idle_since_utc is not None
        assert s2.idle_since_utc.tzinfo is not None  # tz-aware

    def test_terminal_states_set_completed_at(self):
        for terminal in (
            ChiefSessionState.DONE,
            ChiefSessionState.FAILED,
            ChiefSessionState.TIMED_OUT,
        ):
            # Set up the session in AWAITING_EVALUATION which can reach all 3
            s = _make(ChiefSessionState.AWAITING_EVALUATION)
            s2 = s.transition(terminal)
            assert s2.completed_at_utc is not None, (
                f"transition to {terminal} should set completed_at_utc"
            )

    def test_shutdown_sets_completed_at(self):
        s = _make(ChiefSessionState.DONE)
        s2 = s.transition(ChiefSessionState.SHUTDOWN)
        assert s2.completed_at_utc is not None

    def test_failed_with_error_populates_error_field(self):
        s = _make(ChiefSessionState.EXECUTING)
        s2 = s.transition(
            ChiefSessionState.FAILED, error="OpenRouter 503 — backend unavailable"
        )
        assert s2.error == "OpenRouter 503 — backend unavailable"

    def test_failed_without_error_keeps_existing_error(self):
        s = _make(ChiefSessionState.EXECUTING)
        s2 = s.transition(ChiefSessionState.FAILED)
        assert s2.error is None  # default; no override applied


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class TestHelpers:
    def test_is_terminal_only_true_for_shutdown(self):
        for state in ChiefSessionState:
            s = _make(state)
            assert s.is_terminal() == (state == ChiefSessionState.SHUTDOWN)

    def test_is_idle_requires_awaiting_evaluation_and_idle_since(self):
        # AWAITING_EVALUATION but idle_since not set yet
        s = _make(ChiefSessionState.AWAITING_EVALUATION)
        assert not s.is_idle()
        # AWAITING_EVALUATION with idle_since set
        s2 = ChiefSession(
            **{**s.__dict__, "idle_since_utc": datetime.now(timezone.utc)}
        )
        assert s2.is_idle()
        # Other states with idle_since set are still not idle
        for state in ChiefSessionState:
            if state == ChiefSessionState.AWAITING_EVALUATION:
                continue
            s3 = ChiefSession(
                **{
                    **_make(state).__dict__,
                    "idle_since_utc": datetime.now(timezone.utc),
                }
            )
            assert not s3.is_idle(), f"state={state} should not be idle"

    def test_add_cost_returns_new_session_with_summed_cost(self):
        s = _make().add_cost(0.42)
        assert s.cost_usd == pytest.approx(0.42)
        s2 = s.add_cost(0.18)
        assert s2.cost_usd == pytest.approx(0.60)
        # Original is not mutated
        assert s.cost_usd == pytest.approx(0.42)

    def test_add_cost_accepts_negative_delta(self):
        # Refund / reconciliation paths
        s = _make().add_cost(1.00).add_cost(-0.25)
        assert s.cost_usd == pytest.approx(0.75)


# ---------------------------------------------------------------------------
# audit-2026-05-16.D.04 (#2065): chief-session cost-cap dependency wiring.
#
# Audit M-1 in ``docs/audits/2026-05-16-whole-codebase-audit.md`` flags that
# WarmChief accepts an optional ``cost_tracker`` but ChiefDispatcher does
# not supply it, silently disabling cap enforcement on every dispatcher-
# driven path. These tests prove:
#
# 1. The dispatcher now passes its configured ``cost_tracker`` into
#    WarmChief at construction time.
# 2. When the dispatcher is constructed with ``strict_budget_enforcement
#    =True`` and the tracker reports the prior session's most recent
#    CostMeasurement as ``source='unknown'``, dispatch fails closed
#    (RoutingError + ``chief_dispatcher.rejected`` with
#    ``block_reason='strict_budget_unknown_cost'``) before WarmChief runs.
# 3. The same setup with a ``measured`` measurement allows dispatch to
#    proceed normally — strict mode does not over-fire.
# 4. With ``strict_budget_enforcement=False`` (the back-compat default),
#    the strict-mode branch is a no-op even when the tracker reports
#    ``source='unknown'`` — the prior behaviour is preserved.
# ---------------------------------------------------------------------------


class _StrictModeStubTracker:
    """Duck-typed CostTracker substitute for the strict-mode pre-flight.

    Only the surface the dispatcher actually consults is implemented:
    ``last_session_measurement(session_id)`` returns the configured
    measurement (or ``None``), ``get_session_cost(session_id)`` returns
    0.0 so WarmChief's pre/post-flight cap checks are also exercised
    end-to-end without dragging in the real JSONL ledger. ``calls``
    records every lookup for assertion.
    """

    def __init__(self, measurement=None) -> None:
        # Lazy import keeps the contract test self-contained.
        from bridge.cost_tracker import CostMeasurement  # noqa: F401

        self._measurement = measurement
        self.calls: list[tuple[str, str]] = []

    def last_session_measurement(self, session_id: str):
        self.calls.append(("last_session_measurement", session_id))
        return self._measurement

    def get_session_cost(self, session_id: str) -> float:
        # WarmChief calls this in its pre/post-flight enforcement. Always
        # 0.0 here — the strict-mode tests gate on the measurement source,
        # not on a numeric cap breach.
        self.calls.append(("get_session_cost", session_id))
        return 0.0


def _strict_mode_fixtures():
    """Return ``(qa_config, registry, store, event_bus, router, deps)``.

    Reuses the same shapes as the live ``tests/test_chief_dispatcher.py``
    suite without copying its module so the test isolation stays clean.
    Constructed lazily so the import-time cost stays on the
    chief-dispatcher path only when the test class actually runs.
    """
    from bridge.chief_session_store import InMemoryChiefSessionStore
    from bridge.event_bus import EventBus
    from bridge.work_order_router import NullRouter
    from teams._types import AgentSpec, DepartmentConfig
    from tests.test_chief_dispatcher import _FakeRegistry
    from tests.test_teams.conftest import make_deps

    qa_config = DepartmentConfig(
        name="qa",
        zone=4,
        description="QA department",
        manager=AgentSpec(
            name="qa-chief",
            model="anthropic:claude-opus-4-6",
        ),
        employees=(
            AgentSpec(
                name="qa-engineer",
                model="anthropic:claude-sonnet-4-6",
            ),
        ),
    )
    registry = _FakeRegistry(configs={"qa": qa_config})
    store = InMemoryChiefSessionStore()
    event_bus = EventBus(data_dir=None)
    router = NullRouter(department="qa")
    deps = make_deps(department="qa")
    return qa_config, registry, store, event_bus, router, deps


def _work_order():
    from bridge.work_order import WorkOrder

    return WorkOrder.create(
        intent="strict-mode contract test",
        skill="test",
        project="test-project",
    )


def _team_result_ok(cost_usd: float = 0.0):
    from teams._types import TeamResult

    return TeamResult(
        department="qa",
        manager_output="OK",
        employee_results=(),
        total_tokens=0,
        total_cost_usd=cost_usd,
        duration_seconds=0.01,
        success=True,
        error=None,
    )


class TestChiefSessionCostCapDependencies:
    """audit-2026-05-16.D.04 — cost-cap dependency wiring contract."""

    @pytest.mark.asyncio
    async def test_chief_session_strict_mode_blocks_unknown_cost(self):
        """Strict mode + last measurement source='unknown' must fail closed."""
        from bridge.chief_dispatcher import ChiefDispatcher
        from bridge.cost_tracker import CostMeasurement
        from bridge.warm_chief import WarmChief
        from bridge.work_order_router import RoutingError

        (
            _qa_config,
            registry,
            store,
            event_bus,
            router,
            deps,
        ) = _strict_mode_fixtures()

        unknown_measurement = CostMeasurement(
            amount_usd=None,
            source="unknown",
            backend="claude",
            raw_usage_id=None,
        )
        tracker = _StrictModeStubTracker(measurement=unknown_measurement)

        dispatcher = ChiefDispatcher(
            router=router,
            session_store=store,
            dept_registry=registry,
            event_bus=event_bus,
            cost_tracker=tracker,
            strict_budget_enforcement=True,
        )

        # WarmChief._run_chief must NOT execute on the strict-mode reject
        # path. Patch it to a sentinel that records a call so a regression
        # would surface as a non-empty list.
        run_invocations: list[int] = []

        async def _should_not_run(self):  # noqa: ANN001
            run_invocations.append(1)
            return _team_result_ok()

        wo = _work_order()
        with mock.patch.object(WarmChief, "_run_chief", _should_not_run):
            with pytest.raises(RoutingError) as exc_info:
                await dispatcher.dispatch(wo, deps)

        # The strict-mode branch wins: no chief ran, the RoutingError
        # carries the structured reason, and the tracker was consulted
        # with the WO's id.
        assert run_invocations == []
        assert "strict_budget_unknown_cost" in exc_info.value.reason
        assert any(
            call[0] == "last_session_measurement" and call[1] == wo.id
            for call in tracker.calls
        )

        # The rejected event carries the block-reason classifier so an
        # operator subscribing to ``/ws/events`` can pivot on it.
        rejected_events = [
            e
            for e in event_bus._recent_events
            if e.event_type == "chief_dispatcher.rejected"
        ]
        assert rejected_events, "rejected event must be published"
        payload = rejected_events[-1].payload
        assert payload["block_reason"] == "strict_budget_unknown_cost"
        assert payload["measurement_source"] == "unknown"
        assert payload["measurement_backend"] == "claude"

    @pytest.mark.asyncio
    async def test_chief_session_strict_mode_allows_measured_cost_under_cap(
        self,
    ):
        """Strict mode + last measurement source='measured' permits dispatch."""
        from bridge.chief_dispatcher import ChiefDispatcher
        from bridge.chief_session import ChiefSessionState
        from bridge.cost_tracker import CostMeasurement
        from bridge.warm_chief import WarmChief

        (
            _qa_config,
            registry,
            store,
            event_bus,
            router,
            deps,
        ) = _strict_mode_fixtures()

        measured = CostMeasurement(
            amount_usd=Decimal("0.05"),
            source="measured",
            backend="claude",
            raw_usage_id="usage-abc",
        )
        tracker = _StrictModeStubTracker(measurement=measured)

        dispatcher = ChiefDispatcher(
            router=router,
            session_store=store,
            dept_registry=registry,
            event_bus=event_bus,
            cost_tracker=tracker,
            strict_budget_enforcement=True,
        )

        async def _fake_run_chief(self):  # noqa: ANN001
            return _team_result_ok(cost_usd=0.0)

        wo = _work_order()
        with mock.patch.object(WarmChief, "_run_chief", _fake_run_chief):
            session = await dispatcher.dispatch(wo, deps)

        # Strict gate did not trip; the dispatch completed and the
        # session lands in the normal post-run state.
        assert session.state == ChiefSessionState.AWAITING_EVALUATION
        # The tracker was still consulted for the strict-mode pre-flight
        # AND by WarmChief for its own pre/post-flight checks (because
        # the dispatcher now threads ``cost_tracker`` into WarmChief —
        # the M-1 wiring fix this sprint targets).
        kinds = [call[0] for call in tracker.calls]
        assert "last_session_measurement" in kinds
        assert "get_session_cost" in kinds

    @pytest.mark.asyncio
    async def test_chief_session_lenient_mode_unchanged(self):
        """``strict_budget_enforcement=False`` preserves pre-PR behavior.

        Even when the tracker reports an unknown-source measurement, a
        dispatcher built in lenient mode must not reject. This is the
        regression guard for the back-compat default.
        """
        from bridge.chief_dispatcher import ChiefDispatcher
        from bridge.chief_session import ChiefSessionState
        from bridge.cost_tracker import CostMeasurement
        from bridge.warm_chief import WarmChief

        (
            _qa_config,
            registry,
            store,
            event_bus,
            router,
            deps,
        ) = _strict_mode_fixtures()

        unknown_measurement = CostMeasurement(
            amount_usd=None,
            source="unknown",
            backend="claude",
        )
        tracker = _StrictModeStubTracker(measurement=unknown_measurement)

        dispatcher = ChiefDispatcher(
            router=router,
            session_store=store,
            dept_registry=registry,
            event_bus=event_bus,
            cost_tracker=tracker,
            # Lenient — back-compat default explicit for the test's intent.
            strict_budget_enforcement=False,
        )

        async def _fake_run_chief(self):  # noqa: ANN001
            return _team_result_ok(cost_usd=0.0)

        wo = _work_order()
        with mock.patch.object(WarmChief, "_run_chief", _fake_run_chief):
            session = await dispatcher.dispatch(wo, deps)

        # Lenient mode never invokes the strict pre-flight, so the
        # ``last_session_measurement`` call must NOT happen. Only
        # WarmChief's own ``get_session_cost`` is exercised.
        assert session.state == ChiefSessionState.AWAITING_EVALUATION
        kinds = [call[0] for call in tracker.calls]
        assert "last_session_measurement" not in kinds
        # No ``chief_dispatcher.rejected`` event for an unknown cost in
        # lenient mode.
        rejected_events = [
            e
            for e in event_bus._recent_events
            if e.event_type == "chief_dispatcher.rejected"
        ]
        assert rejected_events == []

    @pytest.mark.asyncio
    async def test_chief_dispatcher_passes_cost_deps(self):
        """The dispatcher must thread its ``cost_tracker`` into WarmChief.

        Audit M-1 keystone: prior to this sprint the dispatcher silently
        constructed WarmChief without ``cost_tracker``, disabling cap
        enforcement on every dispatcher-driven path. The fix is observable
        here — assert that WarmChief is instantiated with the same
        tracker instance the dispatcher was given.
        """
        from bridge.chief_dispatcher import ChiefDispatcher
        from bridge.warm_chief import WarmChief

        (
            _qa_config,
            registry,
            store,
            event_bus,
            router,
            deps,
        ) = _strict_mode_fixtures()

        # No measurement configured — strict mode is off; we only want
        # to observe the WarmChief constructor call.
        tracker = _StrictModeStubTracker(measurement=None)

        dispatcher = ChiefDispatcher(
            router=router,
            session_store=store,
            dept_registry=registry,
            event_bus=event_bus,
            cost_tracker=tracker,
        )

        async def _fake_run_chief(self):  # noqa: ANN001
            return _team_result_ok(cost_usd=0.0)

        # Spy on the real WarmChief.__init__ to capture the kwargs the
        # dispatcher passes in. We delegate to the original ``__init__``
        # so the rest of the lifecycle runs unchanged.
        captured: dict = {}
        original_init = WarmChief.__init__

        def _spy_init(self, *args, **kwargs):
            captured["args"] = args
            captured["kwargs"] = dict(kwargs)
            return original_init(self, *args, **kwargs)

        wo = _work_order()
        with mock.patch.object(WarmChief, "__init__", _spy_init), mock.patch.object(
            WarmChief, "_run_chief", _fake_run_chief
        ):
            await dispatcher.dispatch(wo, deps)

        # The dispatcher MUST pass its tracker through. Before the M-1
        # fix this assertion failed: ``cost_tracker`` was absent or None.
        assert captured["kwargs"].get("cost_tracker") is tracker
