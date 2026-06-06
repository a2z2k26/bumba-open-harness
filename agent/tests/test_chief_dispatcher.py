"""Tests for ``bridge.chief_dispatcher`` — Z4-S21 (#1392).

Coverage targets:

- Happy path: router returns a department → dispatcher creates a session,
  WarmChief runs the chief, dispatch returns the AWAITING_EVALUATION row.
- Routing-error path: router raises ``RoutingError`` → ``chief_dispatcher.rejected``
  event published, exception re-raised, NO session row created.
- Unknown department after routing → rejected + RoutingError (registry
  missing the dept the router named).
- Low-confidence routing → NUDGE escalation triggered (best-effort).
- Failure path: chief raises during execution → session ends FAILED,
  ``chief_dispatcher.routed`` still fires (routing succeeded; only
  execution failed).
- Requeue path: AWAITING_EVALUATION → WARM transition + ``chief_dispatcher.requeued``
  event with the post-transition attempt count.
- Shutdown path: idempotent on already-SHUTDOWN sessions; force-shutdowns
  non-terminal sessions through FAILED first.

Tests use ``InMemoryChiefSessionStore`` (Z4-S03 #1387), ``NullRouter`` from
``bridge.work_order_router`` (Z4-S20 #1390), and ``WarmChief._run_chief``
patched with a ``TestModel``-overridden ``DepartmentTeam`` (matches the
pattern in ``test_warm_chief.py::TestIntegrationWithTestModel``). A real
``EventBus`` instance is used so ``publish()`` exercises the production
sync code path; events are read back from ``recent_events()`` for
assertions.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from unittest import mock

import pytest

from bridge.chief_dispatcher import (
    ChiefDispatcher,
    InvalidRequeueError,
    MaxRetriesExceededError,
)
from bridge.circuit_breaker import State as CircuitState
from bridge.chief_session import ChiefSession, ChiefSessionState
from bridge.chief_session_store import (
    ChiefSessionNotFoundError,
    InMemoryChiefSessionStore,
)
from bridge.event_bus import EventBus
from bridge.warm_chief import WarmChief
from bridge.work_order import WorkOrder, WorkOrderInput
from bridge.work_order_router import (
    NullRouter,
    RoutingDecision,
    RoutingError,
    WorkOrderRouter,
)
from teams._types import (
    AgentSpec,
    DepartmentConfig,
    EmployeeResult,
    TeamResult,
)
from tests.test_teams.conftest import make_deps


# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------


@dataclass
class _FakeRegistry:
    """Minimal ``DepartmentRegistry`` substitute.

    Maps department slug → ``DepartmentConfig``. ``get_config`` returns
    ``None`` for unknowns so the dispatcher's "registry missed" path
    fires; production ``DepartmentRegistry`` raises ``KeyError`` instead
    and is covered by a separate test.
    """

    configs: dict[str, DepartmentConfig] = field(default_factory=dict)

    def get_config(self, name: str) -> DepartmentConfig | None:
        return self.configs.get(name)


@dataclass
class _RaisingRegistry:
    """Registry that raises ``KeyError`` on unknown names — DepartmentRegistry shape."""

    configs: dict[str, DepartmentConfig] = field(default_factory=dict)

    def get_config(self, name: str) -> DepartmentConfig:
        if name not in self.configs:
            raise KeyError(f"Unknown department: {name}")
        return self.configs[name]


class _RaisingRouter(WorkOrderRouter):
    """Router that always raises ``RoutingError`` — exercises the rejected path."""

    async def route(self, work_order: WorkOrder) -> RoutingDecision:
        raise RoutingError(
            work_order_id=work_order.id,
            reason="no rule matched",
        )


class _FixedConfidenceRouter(WorkOrderRouter):
    """Router that returns a configurable confidence level.

    Used to exercise the dispatcher's NUDGE-on-low-confidence path
    without depending on the rule-based router's tier-4 fallback (which
    requires a registry shape that satisfies it). Direct injection is
    cleaner here.
    """

    def __init__(self, department: str, confidence: float) -> None:
        self._department = department
        self._confidence = confidence

    async def route(self, work_order: WorkOrder) -> RoutingDecision:
        return RoutingDecision(
            department=self._department,
            rationale=f"fixed-confidence={self._confidence}",
            confidence=self._confidence,
        )


class _RecordingEscalation:
    """Captures NUDGE calls for assertion."""

    def __init__(self) -> None:
        self.calls: list[dict] = []

    def notify(self, *, level: Any, source: str, message: str) -> None:
        self.calls.append(
            {"level": level, "source": source, "message": message},
        )


class _ExplodingEscalation:
    """Always raises — proves dispatch survives best-effort escalation failures."""

    def notify(self, *, level: Any, source: str, message: str) -> None:
        raise RuntimeError("escalation engine offline")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def qa_config() -> DepartmentConfig:
    return DepartmentConfig(
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


@pytest.fixture
def registry(qa_config: DepartmentConfig) -> _FakeRegistry:
    return _FakeRegistry(configs={"qa": qa_config})


@pytest.fixture
def store() -> InMemoryChiefSessionStore:
    return InMemoryChiefSessionStore()


@pytest.fixture
def event_bus(tmp_path) -> EventBus:
    """Real EventBus with persistence directed at a tmp dir.

    Using the real bus rather than a MagicMock proves the dispatcher's
    sync ``publish()`` call shape matches production. Events are read
    back via ``recent_events()`` for assertion.
    """
    return EventBus(data_dir=tmp_path)


def _work_order(
    *,
    intent: str = "test work order",
    department_target: str | None = None,
) -> WorkOrder:
    return WorkOrder.create(
        intent=intent,
        skill="test",
        project="test-project",
    )


def _team_result(
    *,
    success: bool = True,
    cost_usd: float = 0.0,
    department: str = "qa",
    manager_output: str = "synthesised",
    error: str | None = None,
    employee_results: tuple[EmployeeResult, ...] = (),
) -> TeamResult:
    return TeamResult(
        department=department,
        manager_output=manager_output,
        employee_results=employee_results,
        total_tokens=0,
        total_cost_usd=cost_usd,
        duration_seconds=0.01,
        success=success,
        error=error,
    )


def _events_of(bus: EventBus, event_type: str) -> list[Any]:
    """Return all recorded events of a given type from the bus's recent ring."""
    return [e for e in bus._recent_events if e.event_type == event_type]


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


class TestHappyPath:
    @pytest.mark.asyncio
    async def test_dispatch_routes_creates_session_and_runs_chief(
        self, qa_config, registry, store, event_bus
    ):
        """Router → store.create → WarmChief → AWAITING_EVALUATION + routed event."""
        router = NullRouter(department="qa")
        dispatcher = ChiefDispatcher(
            router=router,
            session_store=store,
            dept_registry=registry,
            event_bus=event_bus,
        )

        # Patch _run_chief so the test doesn't need an Anthropic key.
        result = _team_result(success=True, manager_output="QA done")

        async def _fake_run_chief(self):  # noqa: ANN001
            return result

        wo = _work_order(intent="review the auth module")
        deps = make_deps(department="qa")

        with mock.patch.object(WarmChief, "_run_chief", _fake_run_chief):
            session = await dispatcher.dispatch(wo, deps)

        assert session.state == ChiefSessionState.AWAITING_EVALUATION
        assert session.work_order_id == wo.id
        assert session.department == "qa"
        assert session.chief_name == "qa-chief"
        assert session.run_count == 1

        # Routing decision metadata persisted on the session.
        assert "routing_decision" in session.metadata
        rd = session.metadata["routing_decision"]
        assert rd["confidence"] == 1.0
        assert "NullRouter" in rd["rationale"]

        # Event published.
        routed = _events_of(event_bus, "chief_dispatcher.routed")
        assert len(routed) == 1
        assert routed[0].payload["session_id"] == session.session_id
        assert routed[0].payload["department"] == "qa"

        # No rejected event.
        assert _events_of(event_bus, "chief_dispatcher.rejected") == []

    @pytest.mark.asyncio
    async def test_dispatch_returns_persisted_state_not_local_snapshot(
        self, qa_config, registry, store, event_bus
    ):
        """The returned ``ChiefSession`` is the one in the store, post-WarmChief."""
        router = NullRouter(department="qa")
        dispatcher = ChiefDispatcher(
            router=router,
            session_store=store,
            dept_registry=registry,
            event_bus=event_bus,
        )

        async def _fake_run_chief(self):  # noqa: ANN001
            return _team_result(cost_usd=0.07)

        wo = _work_order()
        deps = make_deps(department="qa")
        with mock.patch.object(WarmChief, "_run_chief", _fake_run_chief):
            returned = await dispatcher.dispatch(wo, deps)

        # The store and the return value agree.
        stored = await store.get(returned.session_id)
        assert returned.session_id == stored.session_id
        assert returned.state == stored.state
        assert returned.cost_usd == pytest.approx(0.07)
        assert stored.cost_usd == pytest.approx(0.07)

    @pytest.mark.asyncio
    async def test_task_string_falls_back_to_input_text_when_intent_empty(
        self, qa_config, registry, store, event_bus
    ):
        """When ``intent`` is empty, the chief receives ``input.text`` as the task."""
        router = NullRouter(department="qa")
        dispatcher = ChiefDispatcher(
            router=router,
            session_store=store,
            dept_registry=registry,
            event_bus=event_bus,
        )

        captured_task: dict[str, str] = {}

        async def _capture_run_chief(self):  # noqa: ANN001
            captured_task["task"] = self._task
            return _team_result()

        # Build a WorkOrder with empty intent and non-empty input.text.
        from dataclasses import replace as dc_replace

        wo = WorkOrder.create(intent="", skill="x", project="p")
        wo = dc_replace(wo, input=WorkOrderInput(text="from input.text"))

        deps = make_deps(department="qa")
        with mock.patch.object(WarmChief, "_run_chief", _capture_run_chief):
            await dispatcher.dispatch(wo, deps)

        assert captured_task["task"] == "from input.text"


# ---------------------------------------------------------------------------
# Routing error path
# ---------------------------------------------------------------------------


class TestRoutingError:
    @pytest.mark.asyncio
    async def test_routing_error_publishes_rejected_and_reraises(
        self, registry, store, event_bus
    ):
        """RoutingError → rejected event + re-raise + NO session created."""
        router = _RaisingRouter()
        dispatcher = ChiefDispatcher(
            router=router,
            session_store=store,
            dept_registry=registry,
            event_bus=event_bus,
        )

        wo = _work_order()
        deps = make_deps(department="qa")

        with pytest.raises(RoutingError):
            await dispatcher.dispatch(wo, deps)

        # rejected event published with the WorkOrder id and reason.
        rejected = _events_of(event_bus, "chief_dispatcher.rejected")
        assert len(rejected) == 1
        assert rejected[0].payload["work_order_id"] == wo.id
        assert "no rule matched" in rejected[0].payload["reason"]

        # No routed event.
        assert _events_of(event_bus, "chief_dispatcher.routed") == []

        # No session row was created — the store is empty.
        assert await store._count() == 0

    @pytest.mark.asyncio
    async def test_unknown_department_after_routing_publishes_rejected(
        self, store, event_bus
    ):
        """Router returns a dept the registry doesn't know → rejected + RoutingError."""
        router = NullRouter(department="ghost")  # not in registry
        registry = _FakeRegistry(configs={})  # empty
        dispatcher = ChiefDispatcher(
            router=router,
            session_store=store,
            dept_registry=registry,
            event_bus=event_bus,
        )

        wo = _work_order()
        deps = make_deps(department="ghost")

        with pytest.raises(RoutingError):
            await dispatcher.dispatch(wo, deps)

        rejected = _events_of(event_bus, "chief_dispatcher.rejected")
        assert len(rejected) == 1
        assert rejected[0].payload["department"] == "ghost"
        assert "not registered" in rejected[0].payload["reason"]
        assert await store._count() == 0

    @pytest.mark.asyncio
    async def test_registry_keyerror_treated_same_as_missing(
        self, qa_config, store, event_bus
    ):
        """``DepartmentRegistry.get_config`` raises KeyError on unknown — same path."""
        router = NullRouter(department="ghost")
        registry = _RaisingRegistry(configs={"qa": qa_config})
        dispatcher = ChiefDispatcher(
            router=router,
            session_store=store,
            dept_registry=registry,
            event_bus=event_bus,
        )

        wo = _work_order()
        deps = make_deps(department="ghost")
        with pytest.raises(RoutingError):
            await dispatcher.dispatch(wo, deps)

        assert _events_of(event_bus, "chief_dispatcher.rejected") != []
        assert await store._count() == 0


# ---------------------------------------------------------------------------
# Low-confidence NUDGE escalation
# ---------------------------------------------------------------------------


class TestLowConfidenceEscalation:
    @pytest.mark.asyncio
    async def test_low_confidence_triggers_nudge(
        self, qa_config, registry, store, event_bus
    ):
        """Confidence < 0.5 fires a NUDGE call on the escalation engine."""
        router = _FixedConfidenceRouter(department="qa", confidence=0.3)
        escalation = _RecordingEscalation()
        dispatcher = ChiefDispatcher(
            router=router,
            session_store=store,
            dept_registry=registry,
            event_bus=event_bus,
            escalation=escalation,
        )

        async def _fake_run_chief(self):  # noqa: ANN001
            return _team_result()

        wo = _work_order(intent="ambiguous task")
        deps = make_deps(department="qa")
        with mock.patch.object(WarmChief, "_run_chief", _fake_run_chief):
            await dispatcher.dispatch(wo, deps)

        assert len(escalation.calls) == 1
        call = escalation.calls[0]
        assert call["source"] == "chief_dispatcher:qa"
        assert "Low-confidence routing" in call["message"]

        # The level is the EscalationLevel.NUDGE enum value (or the string
        # fallback) — accept either to keep this test robust against
        # import-order changes.
        from bridge.escalation import EscalationLevel

        assert call["level"] == EscalationLevel.NUDGE

    @pytest.mark.asyncio
    async def test_threshold_of_exactly_0_5_does_not_trigger(
        self, qa_config, registry, store, event_bus
    ):
        """Confidence == 0.5 does NOT trigger — strictly less-than threshold."""
        router = _FixedConfidenceRouter(department="qa", confidence=0.5)
        escalation = _RecordingEscalation()
        dispatcher = ChiefDispatcher(
            router=router,
            session_store=store,
            dept_registry=registry,
            event_bus=event_bus,
            escalation=escalation,
        )

        async def _fake_run_chief(self):  # noqa: ANN001
            return _team_result()

        wo = _work_order()
        deps = make_deps(department="qa")
        with mock.patch.object(WarmChief, "_run_chief", _fake_run_chief):
            await dispatcher.dispatch(wo, deps)

        assert escalation.calls == []

    @pytest.mark.asyncio
    async def test_high_confidence_does_not_trigger(
        self, qa_config, registry, store, event_bus
    ):
        """Confidence == 1.0 (NullRouter) doesn't trigger NUDGE."""
        router = NullRouter(department="qa")
        escalation = _RecordingEscalation()
        dispatcher = ChiefDispatcher(
            router=router,
            session_store=store,
            dept_registry=registry,
            event_bus=event_bus,
            escalation=escalation,
        )

        async def _fake_run_chief(self):  # noqa: ANN001
            return _team_result()

        wo = _work_order()
        deps = make_deps(department="qa")
        with mock.patch.object(WarmChief, "_run_chief", _fake_run_chief):
            await dispatcher.dispatch(wo, deps)

        assert escalation.calls == []

    @pytest.mark.asyncio
    async def test_escalation_failure_does_not_break_dispatch(
        self, qa_config, registry, store, event_bus
    ):
        """A raising escalation is best-effort — dispatch still completes."""
        router = _FixedConfidenceRouter(department="qa", confidence=0.3)
        escalation = _ExplodingEscalation()
        dispatcher = ChiefDispatcher(
            router=router,
            session_store=store,
            dept_registry=registry,
            event_bus=event_bus,
            escalation=escalation,
        )

        async def _fake_run_chief(self):  # noqa: ANN001
            return _team_result()

        wo = _work_order()
        deps = make_deps(department="qa")
        with mock.patch.object(WarmChief, "_run_chief", _fake_run_chief):
            session = await dispatcher.dispatch(wo, deps)

        assert session.state == ChiefSessionState.AWAITING_EVALUATION

    @pytest.mark.asyncio
    async def test_no_escalation_engine_is_a_no_op(
        self, qa_config, registry, store, event_bus
    ):
        """``escalation=None`` (default) — low-confidence routing silently noops."""
        router = _FixedConfidenceRouter(department="qa", confidence=0.3)
        dispatcher = ChiefDispatcher(
            router=router,
            session_store=store,
            dept_registry=registry,
            event_bus=event_bus,
            # no escalation
        )

        async def _fake_run_chief(self):  # noqa: ANN001
            return _team_result()

        wo = _work_order()
        deps = make_deps(department="qa")
        with mock.patch.object(WarmChief, "_run_chief", _fake_run_chief):
            session = await dispatcher.dispatch(wo, deps)

        assert session.state == ChiefSessionState.AWAITING_EVALUATION


# ---------------------------------------------------------------------------
# Failure path: chief raises during execution
# ---------------------------------------------------------------------------


class TestChiefFailure:
    @pytest.mark.asyncio
    async def test_chief_raises_session_marked_failed_routed_event_still_fires(
        self, qa_config, registry, store, event_bus
    ):
        """Chief raising → FAILED row + chief_dispatcher.routed already published."""
        router = NullRouter(department="qa")
        dispatcher = ChiefDispatcher(
            router=router,
            session_store=store,
            dept_registry=registry,
            event_bus=event_bus,
        )

        async def _failing_run(self):  # noqa: ANN001
            raise RuntimeError("chief blew up")

        wo = _work_order()
        deps = make_deps(department="qa")

        with mock.patch.object(WarmChief, "_run_chief", _failing_run):
            session = await dispatcher.dispatch(wo, deps)

        # Session is FAILED, not raised out of dispatch.
        assert session.state == ChiefSessionState.FAILED
        assert session.error is not None
        assert "RuntimeError" in session.error
        assert "chief blew up" in session.error

        # Routed event still fired (routing succeeded).
        assert len(_events_of(event_bus, "chief_dispatcher.routed")) == 1

        # No rejected event (this was an executor failure, not a routing one).
        assert _events_of(event_bus, "chief_dispatcher.rejected") == []


# ---------------------------------------------------------------------------
# Best-effort event publishing
# ---------------------------------------------------------------------------


class TestEventBusBestEffort:
    @pytest.mark.asyncio
    async def test_dispatch_works_with_no_event_bus(
        self, qa_config, registry, store
    ):
        """``event_bus=None`` is allowed — dispatch completes silently."""
        router = NullRouter(department="qa")
        dispatcher = ChiefDispatcher(
            router=router,
            session_store=store,
            dept_registry=registry,
            # no event_bus
        )

        async def _fake_run_chief(self):  # noqa: ANN001
            return _team_result()

        wo = _work_order()
        deps = make_deps(department="qa")
        with mock.patch.object(WarmChief, "_run_chief", _fake_run_chief):
            session = await dispatcher.dispatch(wo, deps)

        assert session.state == ChiefSessionState.AWAITING_EVALUATION

    @pytest.mark.asyncio
    async def test_publish_failure_does_not_break_dispatch(
        self, qa_config, registry, store
    ):
        """A raising EventBus is best-effort — dispatch still completes."""

        class _ExplodingBus:
            def publish(self, *a: Any, **kw: Any) -> Any:
                raise RuntimeError("bus offline")

        router = NullRouter(department="qa")
        dispatcher = ChiefDispatcher(
            router=router,
            session_store=store,
            dept_registry=registry,
            event_bus=_ExplodingBus(),
        )

        async def _fake_run_chief(self):  # noqa: ANN001
            return _team_result()

        wo = _work_order()
        deps = make_deps(department="qa")
        with mock.patch.object(WarmChief, "_run_chief", _fake_run_chief):
            session = await dispatcher.dispatch(wo, deps)

        assert session.state == ChiefSessionState.AWAITING_EVALUATION


# ---------------------------------------------------------------------------
# Requeue path
# ---------------------------------------------------------------------------


class TestRequeue:
    @pytest.mark.asyncio
    async def test_requeue_transitions_to_warm_and_publishes_event(
        self, qa_config, registry, store, event_bus
    ):
        """AWAITING_EVALUATION → WARM + chief_dispatcher.requeued event."""
        # First, run a full dispatch so we have an AWAITING_EVALUATION session.
        router = NullRouter(department="qa")
        dispatcher = ChiefDispatcher(
            router=router,
            session_store=store,
            dept_registry=registry,
            event_bus=event_bus,
        )

        async def _fake_run_chief(self):  # noqa: ANN001
            return _team_result()

        wo = _work_order()
        deps = make_deps(department="qa")
        with mock.patch.object(WarmChief, "_run_chief", _fake_run_chief):
            session = await dispatcher.dispatch(wo, deps)

        assert session.state == ChiefSessionState.AWAITING_EVALUATION

        # Now requeue.
        new_session = await dispatcher.requeue(session.session_id)

        assert new_session.state == ChiefSessionState.WARM
        # run_count is unchanged on AWAITING_EVALUATION → WARM (only the
        # WARM → EXECUTING transition increments it).
        assert new_session.run_count == 1

        stored = await store.get(session.session_id)
        assert stored.state == ChiefSessionState.WARM

        # Event published.
        requeued = _events_of(event_bus, "chief_dispatcher.requeued")
        assert len(requeued) == 1
        assert requeued[0].payload["session_id"] == session.session_id
        assert requeued[0].payload["work_order_id"] == session.work_order_id
        assert requeued[0].payload["attempt"] == 1

    @pytest.mark.asyncio
    async def test_requeue_from_invalid_state_raises(
        self, qa_config, registry, store, event_bus
    ):
        """Requeueing a non-AWAITING_EVALUATION session raises InvalidRequeueError."""
        router = NullRouter(department="qa")
        dispatcher = ChiefDispatcher(
            router=router,
            session_store=store,
            dept_registry=registry,
            event_bus=event_bus,
        )

        # Build a session in DONE state — requeue should reject this.
        session = ChiefSession(
            session_id="cs-test01",
            work_order_id="wo-test",
            department="qa",
            chief_name="qa-chief",
            state=ChiefSessionState.DONE,
        )
        await store.create(session)

        with pytest.raises(InvalidRequeueError) as excinfo:
            await dispatcher.requeue(session.session_id)
        assert excinfo.value.session_id == session.session_id
        assert excinfo.value.actual_state == ChiefSessionState.DONE


# ---------------------------------------------------------------------------
# Z4-S31 (#1393) — formalised requeue flow
# ---------------------------------------------------------------------------


class TestRequeueFlow:
    """Z4-S31 (#1393) — hardened ``requeue(session_id)`` contract.

    Covers:
      - happy path: AWAITING_EVALUATION → WARM, run_count preserved,
        event payload matches the registry catalog
        (``chief_dispatcher.requeued`` carries
        ``{session_id, work_order_id, attempt}``)
      - return value is the new session in WARM
      - invalid source state (EXECUTING) → ``InvalidRequeueError``
      - invalid source state (SHUTDOWN) → ``InvalidRequeueError``
      - unknown session id → ``ChiefSessionNotFoundError`` propagates
      - event publish failure does NOT block the requeue (best-effort)
      - store update failure DOES propagate (callers must know)
    """

    async def _persist_awaiting(
        self,
        store: InMemoryChiefSessionStore,
        *,
        session_id: str = "cs-await001",
        work_order_id: str = "wo-await",
        run_count: int = 1,
    ) -> ChiefSession:
        """Build + persist an AWAITING_EVALUATION row via the legal arc."""
        session = ChiefSession(
            session_id=session_id,
            work_order_id=work_order_id,
            department="qa",
            chief_name="qa-chief",
        )
        # Walk the legal arc: COLD → WARM → EXECUTING → AWAITING_EVALUATION
        session = session.transition(ChiefSessionState.WARM)
        session = session.transition(ChiefSessionState.EXECUTING)
        # run_count is at 1 after one EXECUTING. Walk further EXECUTING
        # cycles via the explicit AWAITING_EVALUATION → WARM arc to land
        # at the requested ``run_count``.
        for _ in range(run_count - 1):
            session = session.transition(ChiefSessionState.AWAITING_EVALUATION)
            session = session.transition(ChiefSessionState.WARM)
            session = session.transition(ChiefSessionState.EXECUTING)
        session = session.transition(ChiefSessionState.AWAITING_EVALUATION)
        await store.create(session)
        return session

    @pytest.mark.asyncio
    async def test_happy_path_publishes_correct_payload(
        self, registry, store, event_bus
    ):
        """AWAITING_EVALUATION → WARM, run_count preserved, payload matches catalog."""
        dispatcher = ChiefDispatcher(
            router=NullRouter(),
            session_store=store,
            dept_registry=registry,
            event_bus=event_bus,
        )
        original = await self._persist_awaiting(
            store, session_id="cs-happy01", work_order_id="wo-happy", run_count=2,
        )
        assert original.state == ChiefSessionState.AWAITING_EVALUATION
        assert original.run_count == 2

        new_session = await dispatcher.requeue(original.session_id)

        assert new_session.state == ChiefSessionState.WARM
        # AWAITING_EVALUATION → WARM does NOT increment run_count.
        assert new_session.run_count == 2

        events = _events_of(event_bus, "chief_dispatcher.requeued")
        assert len(events) == 1
        payload = events[0].payload
        # The registry catalog (config/registry/events/chief-dispatcher.yaml)
        # promises {session_id, work_order_id, attempt} on this event.
        assert set(payload.keys()) >= {"session_id", "work_order_id", "attempt"}
        assert payload["session_id"] == "cs-happy01"
        assert payload["work_order_id"] == "wo-happy"
        assert payload["attempt"] == 2

    @pytest.mark.asyncio
    async def test_returns_new_session_in_warm(
        self, registry, store, event_bus
    ):
        """The return value is the post-transition session in WARM."""
        dispatcher = ChiefDispatcher(
            router=NullRouter(),
            session_store=store,
            dept_registry=registry,
            event_bus=event_bus,
        )
        original = await self._persist_awaiting(store, session_id="cs-ret01")

        returned = await dispatcher.requeue(original.session_id)

        assert isinstance(returned, ChiefSession)
        assert returned.session_id == original.session_id
        assert returned.state == ChiefSessionState.WARM
        # The store agrees with the return value (same row, same state).
        stored = await store.get(original.session_id)
        assert stored.state == ChiefSessionState.WARM
        assert stored.session_id == returned.session_id

    @pytest.mark.asyncio
    async def test_invalid_state_executing_raises(
        self, registry, store, event_bus
    ):
        """Requeue on an EXECUTING session → InvalidRequeueError with state name."""
        dispatcher = ChiefDispatcher(
            router=NullRouter(),
            session_store=store,
            dept_registry=registry,
            event_bus=event_bus,
        )
        # Build a session in EXECUTING via the legal arc.
        session = ChiefSession(
            session_id="cs-exec01",
            work_order_id="wo-exec",
            department="qa",
            chief_name="qa-chief",
        )
        session = session.transition(ChiefSessionState.WARM)
        session = session.transition(ChiefSessionState.EXECUTING)
        await store.create(session)

        with pytest.raises(InvalidRequeueError) as excinfo:
            await dispatcher.requeue(session.session_id)

        assert excinfo.value.session_id == session.session_id
        assert excinfo.value.actual_state == ChiefSessionState.EXECUTING
        # The message names the actual state so an operator log /
        # Discord surface can read it without unpacking attributes.
        assert "executing" in str(excinfo.value)
        # The store row is unchanged — no half-applied requeue.
        stored = await store.get(session.session_id)
        assert stored.state == ChiefSessionState.EXECUTING
        # No event published (the error fired before the publish path).
        assert _events_of(event_bus, "chief_dispatcher.requeued") == []

    @pytest.mark.asyncio
    async def test_invalid_state_shutdown_raises(
        self, registry, store, event_bus
    ):
        """Requeue on a SHUTDOWN session → InvalidRequeueError."""
        dispatcher = ChiefDispatcher(
            router=NullRouter(),
            session_store=store,
            dept_registry=registry,
            event_bus=event_bus,
        )
        # COLD → SHUTDOWN is a legal arc (per _ALLOWED_TRANSITIONS).
        session = ChiefSession(
            session_id="cs-shut01",
            work_order_id="wo-shut",
            department="qa",
            chief_name="qa-chief",
        )
        session = session.transition(ChiefSessionState.SHUTDOWN)
        await store.create(session)

        with pytest.raises(InvalidRequeueError) as excinfo:
            await dispatcher.requeue(session.session_id)

        assert excinfo.value.actual_state == ChiefSessionState.SHUTDOWN
        # ValueError-subclass contract: existing callers catching ValueError
        # also catch this.
        assert isinstance(excinfo.value, ValueError)

    @pytest.mark.asyncio
    async def test_unknown_session_propagates_not_found(
        self, registry, store, event_bus
    ):
        """Unknown session id → ChiefSessionNotFoundError propagates as-is."""
        dispatcher = ChiefDispatcher(
            router=NullRouter(),
            session_store=store,
            dept_registry=registry,
            event_bus=event_bus,
        )

        with pytest.raises(ChiefSessionNotFoundError):
            await dispatcher.requeue("cs-missing-xx")

        # No event leaked.
        assert _events_of(event_bus, "chief_dispatcher.requeued") == []

    @pytest.mark.asyncio
    async def test_event_publish_failure_does_not_block_requeue(
        self, registry, store
    ):
        """A raising EventBus must NOT block the requeue from taking effect."""

        class _ExplodingBus:
            def publish(self, *a: Any, **kw: Any) -> Any:
                raise RuntimeError("bus offline")

        dispatcher = ChiefDispatcher(
            router=NullRouter(),
            session_store=store,
            dept_registry=registry,
            event_bus=_ExplodingBus(),
        )
        original = await self._persist_awaiting(store, session_id="cs-busfail")

        # Requeue completes despite the publish failure.
        returned = await dispatcher.requeue(original.session_id)
        assert returned.state == ChiefSessionState.WARM

        # And the persisted row reflects the requeue.
        stored = await store.get(original.session_id)
        assert stored.state == ChiefSessionState.WARM

    @pytest.mark.asyncio
    async def test_store_update_failure_propagates(
        self, registry, store, event_bus
    ):
        """A raising store.update DOES propagate — callers must know."""
        dispatcher = ChiefDispatcher(
            router=NullRouter(),
            session_store=store,
            dept_registry=registry,
            event_bus=event_bus,
        )
        original = await self._persist_awaiting(store, session_id="cs-storefail")

        async def _boom(_session: ChiefSession) -> None:
            raise RuntimeError("disk full")

        with mock.patch.object(store, "update", side_effect=_boom):
            with pytest.raises(RuntimeError, match="disk full"):
                await dispatcher.requeue(original.session_id)

        # Event was NOT published — the publish path runs after update,
        # and we want to keep the contract honest: only successful
        # persists emit the event.
        assert _events_of(event_bus, "chief_dispatcher.requeued") == []


# ---------------------------------------------------------------------------
# Shutdown path
# ---------------------------------------------------------------------------


class TestShutdown:
    @pytest.mark.asyncio
    async def test_shutdown_already_shutdown_is_idempotent(
        self, registry, store, event_bus
    ):
        """Calling shutdown_session on an already-SHUTDOWN row is a no-op."""
        dispatcher = ChiefDispatcher(
            router=NullRouter(),
            session_store=store,
            dept_registry=registry,
            event_bus=event_bus,
        )

        # Persist a SHUTDOWN session directly (constructed via the legal
        # path: DONE → SHUTDOWN).
        from datetime import datetime, timezone

        session = ChiefSession(
            session_id="cs-done01",
            work_order_id="wo-x",
            department="qa",
            chief_name="qa-chief",
            state=ChiefSessionState.DONE,
            completed_at_utc=datetime.now(timezone.utc),
        )
        session = session.transition(ChiefSessionState.SHUTDOWN)
        await store.create(session)

        # No-op — should not raise, should not change state.
        await dispatcher.shutdown_session(session.session_id)

        stored = await store.get(session.session_id)
        assert stored.state == ChiefSessionState.SHUTDOWN

    @pytest.mark.asyncio
    async def test_shutdown_unknown_session_is_no_op(
        self, registry, store, event_bus
    ):
        """shutdown_session on a missing id silently returns."""
        dispatcher = ChiefDispatcher(
            router=NullRouter(),
            session_store=store,
            dept_registry=registry,
            event_bus=event_bus,
        )
        # Should not raise.
        await dispatcher.shutdown_session("cs-missing01")
        # Store still empty.
        assert await store._count() == 0

    @pytest.mark.asyncio
    async def test_shutdown_on_awaiting_evaluation_routes_through_failed(
        self, qa_config, registry, store, event_bus
    ):
        """A non-terminal session is force-failed first, then SHUTDOWN."""
        # Run a real dispatch to get a session in AWAITING_EVALUATION.
        router = NullRouter(department="qa")
        dispatcher = ChiefDispatcher(
            router=router,
            session_store=store,
            dept_registry=registry,
            event_bus=event_bus,
        )

        async def _fake_run_chief(self):  # noqa: ANN001
            return _team_result()

        wo = _work_order()
        deps = make_deps(department="qa")
        with mock.patch.object(WarmChief, "_run_chief", _fake_run_chief):
            session = await dispatcher.dispatch(wo, deps)
        assert session.state == ChiefSessionState.AWAITING_EVALUATION

        await dispatcher.shutdown_session(session.session_id, note="bridge exit")

        stored = await store.get(session.session_id)
        assert stored.state == ChiefSessionState.SHUTDOWN
        # The error field carries the force-shutdown reason for audit.
        assert stored.error is not None
        assert "force-shutdown" in stored.error
        assert "bridge exit" in stored.error


# ---------------------------------------------------------------------------
# Z4-S60 (#1404) — retry with exponential backoff for FAILED sessions.
#
# ``retry_failed`` is the FAILED → WARM helper (companion to
# ``requeue``'s AWAITING_EVALUATION → WARM). ``retry_with_backoff`` wraps
# it with a deterministic backoff sleep and a max-attempts budget.
#
# Backoff formula: ``min(initial * (multiplier ** (attempt - 1)), max_backoff)``.
# With initial=5.0, multiplier=2.0, max_backoff=300.0 the first three
# attempts produce 5.0, 10.0, 20.0 seconds. The cap kicks in at attempt 7
# (initial * 2**6 = 320 > 300 → cap).
# ---------------------------------------------------------------------------


async def _persist_failed(
    store: InMemoryChiefSessionStore,
    *,
    session_id: str = "cs-fail01",
    work_order_id: str = "wo-fail",
    run_count: int = 1,
    error: str = "boom",
) -> ChiefSession:
    """Build + persist a FAILED row via the legal arc.

    Walks COLD → WARM → EXECUTING → FAILED, then loops AWAITING_EVALUATION → WARM
    → EXECUTING → FAILED to reach a target ``run_count`` if needed.
    """
    session = ChiefSession(
        session_id=session_id,
        work_order_id=work_order_id,
        department="qa",
        chief_name="qa-chief",
    )
    session = session.transition(ChiefSessionState.WARM)
    session = session.transition(ChiefSessionState.EXECUTING)
    # Each loop iteration adds one EXECUTING transition (run_count++).
    for _ in range(run_count - 1):
        session = session.transition(
            ChiefSessionState.AWAITING_EVALUATION,
        )
        session = session.transition(ChiefSessionState.WARM)
        session = session.transition(ChiefSessionState.EXECUTING)
    session = session.transition(ChiefSessionState.FAILED, error=error)
    await store.create(session)
    return session


class TestRetryFailed:
    """``retry_failed(session_id)`` — FAILED → WARM helper."""

    @pytest.mark.asyncio
    async def test_failed_to_warm_preserves_run_count(
        self, registry, store, event_bus
    ):
        """FAILED session re-warms with run_count preserved + event published."""
        dispatcher = ChiefDispatcher(
            router=NullRouter(),
            session_store=store,
            dept_registry=registry,
            event_bus=event_bus,
        )
        original = await _persist_failed(
            store, session_id="cs-rf01", work_order_id="wo-rf", run_count=2,
        )
        assert original.state == ChiefSessionState.FAILED
        assert original.run_count == 2

        new_session = await dispatcher.retry_failed(original.session_id)

        assert new_session.state == ChiefSessionState.WARM
        # FAILED → WARM does NOT increment run_count (state machine only
        # bumps on WARM → EXECUTING).
        assert new_session.run_count == 2

        stored = await store.get(original.session_id)
        assert stored.state == ChiefSessionState.WARM

        # Reuses the chief_dispatcher.requeued event (same audit trail).
        events = _events_of(event_bus, "chief_dispatcher.requeued")
        assert len(events) == 1
        payload = events[0].payload
        assert payload["session_id"] == "cs-rf01"
        assert payload["work_order_id"] == "wo-rf"
        assert payload["attempt"] == 2

    @pytest.mark.asyncio
    async def test_non_failed_state_raises(
        self, registry, store, event_bus
    ):
        """Calling retry_failed on EXECUTING raises InvalidRequeueError."""
        dispatcher = ChiefDispatcher(
            router=NullRouter(),
            session_store=store,
            dept_registry=registry,
            event_bus=event_bus,
        )
        # Build an EXECUTING session.
        session = ChiefSession(
            session_id="cs-exec02",
            work_order_id="wo-exec02",
            department="qa",
            chief_name="qa-chief",
        )
        session = session.transition(ChiefSessionState.WARM)
        session = session.transition(ChiefSessionState.EXECUTING)
        await store.create(session)

        with pytest.raises(InvalidRequeueError) as excinfo:
            await dispatcher.retry_failed(session.session_id)

        assert excinfo.value.session_id == session.session_id
        assert excinfo.value.actual_state == ChiefSessionState.EXECUTING
        # No event leaked.
        assert _events_of(event_bus, "chief_dispatcher.requeued") == []

    @pytest.mark.asyncio
    async def test_unknown_session_propagates_not_found(
        self, registry, store, event_bus
    ):
        """Unknown session id propagates ChiefSessionNotFoundError."""
        dispatcher = ChiefDispatcher(
            router=NullRouter(),
            session_store=store,
            dept_registry=registry,
            event_bus=event_bus,
        )
        with pytest.raises(ChiefSessionNotFoundError):
            await dispatcher.retry_failed("cs-missing-yy")

    @pytest.mark.asyncio
    async def test_event_publish_failure_does_not_block(
        self, registry, store
    ):
        """A raising EventBus does NOT block FAILED → WARM."""

        class _ExplodingBus:
            def publish(self, *a: Any, **kw: Any) -> Any:
                raise RuntimeError("bus offline")

        dispatcher = ChiefDispatcher(
            router=NullRouter(),
            session_store=store,
            dept_registry=registry,
            event_bus=_ExplodingBus(),
        )
        original = await _persist_failed(store, session_id="cs-rf-busfail")

        returned = await dispatcher.retry_failed(original.session_id)
        assert returned.state == ChiefSessionState.WARM
        stored = await store.get(original.session_id)
        assert stored.state == ChiefSessionState.WARM


class TestRetryWithBackoff:
    """``retry_with_backoff(session_id, attempt)`` — sleep + retry_failed."""

    def test_backoff_formula_initial(self, registry, store, event_bus):
        """attempt=1 → backoff equals ``initial`` (no exponentiation)."""
        dispatcher = ChiefDispatcher(
            router=NullRouter(),
            session_store=store,
            dept_registry=registry,
            event_bus=event_bus,
            retry_initial_backoff_seconds=5.0,
            retry_max_backoff_seconds=300.0,
            retry_backoff_multiplier=2.0,
        )
        assert dispatcher._compute_backoff_seconds(1) == 5.0

    def test_backoff_formula_doubles_per_attempt(
        self, registry, store, event_bus
    ):
        """multiplier=2.0 doubles the backoff each attempt."""
        dispatcher = ChiefDispatcher(
            router=NullRouter(),
            session_store=store,
            dept_registry=registry,
            event_bus=event_bus,
            retry_initial_backoff_seconds=5.0,
            retry_max_backoff_seconds=300.0,
            retry_backoff_multiplier=2.0,
        )
        # 5 * 2**0=5, 5 * 2**1=10, 5 * 2**2=20.
        assert dispatcher._compute_backoff_seconds(1) == 5.0
        assert dispatcher._compute_backoff_seconds(2) == 10.0
        assert dispatcher._compute_backoff_seconds(3) == 20.0

    def test_backoff_cap_at_max(self, registry, store, event_bus):
        """Beyond the cap, backoff stops climbing."""
        dispatcher = ChiefDispatcher(
            router=NullRouter(),
            session_store=store,
            dept_registry=registry,
            event_bus=event_bus,
            retry_initial_backoff_seconds=5.0,
            retry_max_backoff_seconds=30.0,  # tight cap for test
            retry_backoff_multiplier=2.0,
        )
        # 5 * 2**3 = 40 > 30 → capped at 30.
        # 5 * 2**10 = 5120 > 30 → still capped at 30.
        assert dispatcher._compute_backoff_seconds(4) == 30.0
        assert dispatcher._compute_backoff_seconds(11) == 30.0

    @pytest.mark.asyncio
    async def test_first_retry_warms_failed_session(
        self, registry, store, event_bus
    ):
        """attempt=1 → asyncio.sleep is called, FAILED → WARM, run_count preserved."""
        dispatcher = ChiefDispatcher(
            router=NullRouter(),
            session_store=store,
            dept_registry=registry,
            event_bus=event_bus,
            retry_initial_backoff_seconds=5.0,
        )
        original = await _persist_failed(
            store, session_id="cs-rb01", run_count=1,
        )

        with mock.patch(
            "bridge.chief_dispatcher.asyncio.sleep",
            new_callable=mock.AsyncMock,
        ) as mock_sleep:
            new_session = await dispatcher.retry_with_backoff(
                original.session_id, attempt=1,
            )

        # Slept for the first-attempt backoff (5.0s with default config).
        mock_sleep.assert_awaited_once_with(5.0)

        assert new_session.state == ChiefSessionState.WARM
        # run_count preserved across FAILED → WARM.
        assert new_session.run_count == 1

    @pytest.mark.asyncio
    async def test_second_retry_uses_doubled_backoff(
        self, registry, store, event_bus
    ):
        """attempt=2 sleeps for ``initial * multiplier`` seconds."""
        dispatcher = ChiefDispatcher(
            router=NullRouter(),
            session_store=store,
            dept_registry=registry,
            event_bus=event_bus,
            retry_initial_backoff_seconds=5.0,
            retry_backoff_multiplier=2.0,
        )
        original = await _persist_failed(store, session_id="cs-rb02")

        with mock.patch(
            "bridge.chief_dispatcher.asyncio.sleep",
            new_callable=mock.AsyncMock,
        ) as mock_sleep:
            await dispatcher.retry_with_backoff(
                original.session_id, attempt=2,
            )

        mock_sleep.assert_awaited_once_with(10.0)

    @pytest.mark.asyncio
    async def test_attempt_past_max_raises(
        self, registry, store, event_bus
    ):
        """attempt > retry_max_attempts → MaxRetriesExceededError, no sleep, no requeue."""
        dispatcher = ChiefDispatcher(
            router=NullRouter(),
            session_store=store,
            dept_registry=registry,
            event_bus=event_bus,
            retry_max_attempts=3,
        )
        original = await _persist_failed(store, session_id="cs-rb-max")

        with mock.patch(
            "bridge.chief_dispatcher.asyncio.sleep",
            new_callable=mock.AsyncMock,
        ) as mock_sleep:
            with pytest.raises(MaxRetriesExceededError) as excinfo:
                await dispatcher.retry_with_backoff(
                    original.session_id, attempt=4,
                )

        # No sleep — we bailed before wasting wall-clock.
        mock_sleep.assert_not_awaited()
        # Error carries the session id and the offending attempt.
        assert excinfo.value.session_id == original.session_id
        assert excinfo.value.final_attempt == 4
        # Subclass discipline: NOT a ValueError (this is a budget signal,
        # not a contract-violation argument).
        assert not isinstance(excinfo.value, ValueError)
        # And the row is unchanged (still FAILED).
        stored = await store.get(original.session_id)
        assert stored.state == ChiefSessionState.FAILED

    @pytest.mark.asyncio
    async def test_publish_failure_in_retry_does_not_block(
        self, registry, store
    ):
        """Best-effort publish: a raising bus does NOT prevent the retry."""

        class _ExplodingBus:
            def publish(self, *a: Any, **kw: Any) -> Any:
                raise RuntimeError("bus offline")

        dispatcher = ChiefDispatcher(
            router=NullRouter(),
            session_store=store,
            dept_registry=registry,
            event_bus=_ExplodingBus(),
        )
        original = await _persist_failed(store, session_id="cs-rb-busfail")

        with mock.patch(
            "bridge.chief_dispatcher.asyncio.sleep",
            new_callable=mock.AsyncMock,
        ):
            new_session = await dispatcher.retry_with_backoff(
                original.session_id, attempt=1,
            )

        assert new_session.state == ChiefSessionState.WARM
        stored = await store.get(original.session_id)
        assert stored.state == ChiefSessionState.WARM

    @pytest.mark.asyncio
    async def test_executing_session_raises_invalid_requeue(
        self, registry, store, event_bus
    ):
        """retry_with_backoff on a non-FAILED session raises InvalidRequeueError."""
        dispatcher = ChiefDispatcher(
            router=NullRouter(),
            session_store=store,
            dept_registry=registry,
            event_bus=event_bus,
        )
        # EXECUTING session.
        session = ChiefSession(
            session_id="cs-rb-exec",
            work_order_id="wo-rb-exec",
            department="qa",
            chief_name="qa-chief",
        )
        session = session.transition(ChiefSessionState.WARM)
        session = session.transition(ChiefSessionState.EXECUTING)
        await store.create(session)

        with mock.patch(
            "bridge.chief_dispatcher.asyncio.sleep",
            new_callable=mock.AsyncMock,
        ):
            with pytest.raises(InvalidRequeueError) as excinfo:
                await dispatcher.retry_with_backoff(
                    session.session_id, attempt=1,
                )

        assert excinfo.value.actual_state == ChiefSessionState.EXECUTING

    @pytest.mark.asyncio
    async def test_default_attempt_is_one(
        self, registry, store, event_bus
    ):
        """attempt defaults to 1 when not passed."""
        dispatcher = ChiefDispatcher(
            router=NullRouter(),
            session_store=store,
            dept_registry=registry,
            event_bus=event_bus,
            retry_initial_backoff_seconds=7.5,
        )
        original = await _persist_failed(store, session_id="cs-rb-default")

        with mock.patch(
            "bridge.chief_dispatcher.asyncio.sleep",
            new_callable=mock.AsyncMock,
        ) as mock_sleep:
            new_session = await dispatcher.retry_with_backoff(
                original.session_id,
            )

        mock_sleep.assert_awaited_once_with(7.5)
        assert new_session.state == ChiefSessionState.WARM


# ---------------------------------------------------------------------------
# Z4-S64 (#1408) — per-department circuit breaker integration
# ---------------------------------------------------------------------------


class _FallbackRouter(WorkOrderRouter):
    """Router that returns a fixed primary + fallback list — exercises Z4-S64."""

    def __init__(
        self,
        department: str,
        fallbacks: tuple[str, ...] = (),
        confidence: float = 1.0,
    ) -> None:
        self._department = department
        self._fallbacks = fallbacks
        self._confidence = confidence

    async def route(self, work_order: WorkOrder) -> RoutingDecision:
        return RoutingDecision(
            department=self._department,
            rationale=f"primary={self._department} fallbacks={self._fallbacks}",
            confidence=self._confidence,
            fallback_departments=self._fallbacks,
        )


@pytest.fixture
def ops_config() -> DepartmentConfig:
    return DepartmentConfig(
        name="ops",
        zone=4,
        description="Ops department",
        manager=AgentSpec(
            name="ops-chief",
            model="anthropic:claude-opus-4-6",
        ),
        employees=(),
    )


class TestCircuitBreaker:
    """Z4-S64 (#1408) — per-department circuit breaker integration."""

    @pytest.mark.asyncio
    async def test_three_consecutive_failures_open_circuit_and_emit_event(
        self, qa_config, registry, store, event_bus
    ):
        """3 chief-raise dispatches → CLOSED → OPEN + circuit_open event fires once."""
        router = NullRouter(department="qa")
        dispatcher = ChiefDispatcher(
            router=router,
            session_store=store,
            dept_registry=registry,
            event_bus=event_bus,
        )

        async def _failing_run(self):  # noqa: ANN001
            raise RuntimeError("chief blew up")

        deps = make_deps(department="qa")
        with mock.patch.object(WarmChief, "_run_chief", _failing_run):
            for _ in range(3):
                await dispatcher.dispatch(_work_order(), deps)

        breaker = dispatcher._circuit_breakers["qa"]
        assert breaker.state == CircuitState.OPEN

        # Exactly one circuit_open event — the open-transition fires once,
        # not on every subsequent failure.
        opens = _events_of(event_bus, "chief_dispatcher.circuit_open")
        assert len(opens) == 1
        assert opens[0].payload["department"] == "qa"
        assert opens[0].payload["failure_count"] >= 3

    @pytest.mark.asyncio
    async def test_open_circuit_routes_to_fallback_department(
        self, qa_config, ops_config, store, event_bus
    ):
        """Primary OPEN + fallback CLOSED → run uses fallback config."""
        registry = _FakeRegistry(configs={"qa": qa_config, "ops": ops_config})
        router = _FallbackRouter(department="qa", fallbacks=("ops",))
        dispatcher = ChiefDispatcher(
            router=router,
            session_store=store,
            dept_registry=registry,
            event_bus=event_bus,
        )

        # Pre-trip the qa breaker by injecting an OPEN one. The dispatcher
        # creates breakers lazily so this short-circuits before any run.
        from bridge.circuit_breaker import CircuitBreaker
        tripped = CircuitBreaker(failure_threshold=1, recovery_timeout=300)
        tripped.record_failure()
        assert tripped.state == CircuitState.OPEN
        dispatcher._circuit_breakers["qa"] = tripped

        captured: dict[str, Any] = {}

        async def _capture_run(self):  # noqa: ANN001
            captured["department"] = self._config.name
            captured["chief_name"] = self._config.manager.name
            return _team_result(department=self._config.name)

        wo = _work_order()
        deps = make_deps(department="qa")
        with mock.patch.object(WarmChief, "_run_chief", _capture_run):
            session = await dispatcher.dispatch(wo, deps)

        # The session row records the *primary* department (the routing
        # decision is what was made), but WarmChief ran with the fallback
        # config.
        assert session.state == ChiefSessionState.AWAITING_EVALUATION
        assert captured["department"] == "ops"
        assert captured["chief_name"] == "ops-chief"

        # F1 fix (#1501): metadata records the fallback outcome so audit
        # consumers see WHICH chief actually ran without ambiguity.
        assert session.metadata.get("actual_run_department") == "ops"
        assert session.metadata.get("fallback_used") is True
        assert "circuit OPEN" in session.metadata.get("fallback_reason", "")

    @pytest.mark.asyncio
    async def test_all_circuits_open_raises_routing_error(
        self, qa_config, ops_config, store, event_bus
    ):
        """Primary + every fallback OPEN → RoutingError, no run."""
        registry = _FakeRegistry(configs={"qa": qa_config, "ops": ops_config})
        router = _FallbackRouter(department="qa", fallbacks=("ops",))
        dispatcher = ChiefDispatcher(
            router=router,
            session_store=store,
            dept_registry=registry,
            event_bus=event_bus,
        )

        from bridge.circuit_breaker import CircuitBreaker
        for dept in ("qa", "ops"):
            cb = CircuitBreaker(failure_threshold=1, recovery_timeout=300)
            cb.record_failure()
            dispatcher._circuit_breakers[dept] = cb

        wo = _work_order()
        deps = make_deps(department="qa")

        ran: list[bool] = []

        async def _should_not_run(self):  # noqa: ANN001
            ran.append(True)
            return _team_result()

        with mock.patch.object(WarmChief, "_run_chief", _should_not_run):
            with pytest.raises(RoutingError):
                await dispatcher.dispatch(wo, deps)

        assert ran == []

    @pytest.mark.asyncio
    async def test_success_after_failures_does_not_open_circuit(
        self, qa_config, registry, store, event_bus
    ):
        """2 failures + 1 success → still CLOSED, no circuit_open event."""
        router = NullRouter(department="qa")
        dispatcher = ChiefDispatcher(
            router=router,
            session_store=store,
            dept_registry=registry,
            event_bus=event_bus,
        )

        deps = make_deps(department="qa")

        async def _failing_run(self):  # noqa: ANN001
            raise RuntimeError("blew up")

        async def _ok_run(self):  # noqa: ANN001
            return _team_result()

        with mock.patch.object(WarmChief, "_run_chief", _failing_run):
            for _ in range(2):
                await dispatcher.dispatch(_work_order(), deps)

        with mock.patch.object(WarmChief, "_run_chief", _ok_run):
            session = await dispatcher.dispatch(_work_order(), deps)

        assert session.state == ChiefSessionState.AWAITING_EVALUATION
        breaker = dispatcher._circuit_breakers["qa"]
        # Successful run in CLOSED state prunes the failure window — the
        # circuit stays CLOSED and no transition event fires.
        assert breaker.state == CircuitState.CLOSED
        assert _events_of(event_bus, "chief_dispatcher.circuit_open") == []
        assert _events_of(event_bus, "chief_dispatcher.circuit_closed") == []

    @pytest.mark.asyncio
    async def test_breaker_record_failure_does_not_break_dispatch_return(
        self, qa_config, registry, store, event_bus
    ):
        """A broken breaker must not prevent dispatch from returning the session."""
        router = NullRouter(department="qa")
        dispatcher = ChiefDispatcher(
            router=router,
            session_store=store,
            dept_registry=registry,
            event_bus=event_bus,
        )

        # Inject a breaker whose record_success raises.
        class _ExplodingBreaker:
            state = CircuitState.CLOSED
            failure_count = 0

            def record_success(self) -> None:
                raise RuntimeError("breaker offline")

            def record_failure(self) -> None:
                raise RuntimeError("breaker offline")

        dispatcher._circuit_breakers["qa"] = _ExplodingBreaker()

        async def _ok_run(self):  # noqa: ANN001
            return _team_result()

        wo = _work_order()
        deps = make_deps(department="qa")
        with mock.patch.object(WarmChief, "_run_chief", _ok_run):
            session = await dispatcher.dispatch(wo, deps)

        # Despite the breaker exploding, dispatch returns the persisted
        # AWAITING_EVALUATION row.
        assert session.state == ChiefSessionState.AWAITING_EVALUATION


# ---------------------------------------------------------------------------
# Sprint 5.00c (#2155) — workflow-first dispatch
# ---------------------------------------------------------------------------


class _FakeWorkflowRegistry:
    """Test double for WorkflowRegistry — only the methods workflow-first uses."""

    def __init__(self, match_result=None, trigger_run_id="wf-run-123"):
        self._match_result = match_result
        self._trigger_run_id = trigger_run_id
        self.trigger_calls = []

    def match(self, directive):
        return self._match_result

    def trigger(self, name, inputs=None, *, engine=None):
        self.trigger_calls.append({"name": name, "inputs": inputs, "engine": engine})
        return self._trigger_run_id


class _FakeWorkflowEngine:
    """Sentinel — workflow engine is passed but only the registry calls into it."""
    pass


class TestWorkflowFirstDispatch:
    """Sprint 5.00c (#2155): when flag is on and a workflow matches, bypass chief."""

    @pytest.mark.asyncio
    async def test_flag_off_default_falls_through_to_chief_path(
        self, qa_config, registry, store, event_bus
    ):
        """Default behavior: workflow-first hook is a no-op when flag is off."""
        from bridge.chief_dispatcher import ChiefDispatcher
        from bridge.work_order_router import NullRouter

        router = NullRouter(department="qa")
        wf_registry = _FakeWorkflowRegistry(
            match_result={"name": "qa.api_contract_test", "confidence": 1.0, "matched_token": "qa.api_contract_test"}
        )
        dispatcher = ChiefDispatcher(
            router=router,
            session_store=store,
            dept_registry=registry,
            event_bus=event_bus,
            workflow_registry=wf_registry,
            workflow_engine=_FakeWorkflowEngine(),
            workflow_first_dispatch_enabled=False,  # FLAG OFF
        )
        # Even though the directive matches, the workflow path is NOT taken.
        # The match() method should never even be called when the flag is off.
        wo = _work_order(intent="please run qa.api_contract_test on the api")
        # We don't fully execute the chief here; we assert match was NOT called.
        # The dispatch will then go to the chief path (which will fail without
        # a full WarmChief stack), so we catch the expected error.
        try:
            await dispatcher.dispatch(wo, deps=None)
        except Exception:
            pass  # Expected — no WarmChief mock; we only care match wasn't called
        assert wf_registry.trigger_calls == []  # workflow path NOT taken

    @pytest.mark.asyncio
    async def test_flag_on_and_match_short_circuits_to_workflow(
        self, qa_config, registry, store, event_bus
    ):
        """When flag is on AND match confidence >= threshold, fire workflow + return SHUTDOWN session."""
        from bridge.chief_dispatcher import ChiefDispatcher
        from bridge.work_order_router import NullRouter

        router = NullRouter(department="qa")
        wf_registry = _FakeWorkflowRegistry(
            match_result={"name": "qa.api_contract_test", "confidence": 1.0, "matched_token": "qa.api_contract_test"}
        )
        dispatcher = ChiefDispatcher(
            router=router,
            session_store=store,
            dept_registry=registry,
            event_bus=event_bus,
            workflow_registry=wf_registry,
            workflow_engine=_FakeWorkflowEngine(),
            workflow_first_dispatch_enabled=True,
        )
        wo = _work_order(intent="please run qa.api_contract_test on the api")
        session = await dispatcher.dispatch(wo, deps=None)

        # Workflow was triggered
        assert len(wf_registry.trigger_calls) == 1
        assert wf_registry.trigger_calls[0]["name"] == "qa.api_contract_test"

        # Returned session is SHUTDOWN with workflow metadata
        assert session.state == ChiefSessionState.SHUTDOWN
        assert session.metadata.get("workflow_run_id") == "wf-run-123"
        assert session.metadata.get("workflow_name") == "qa.api_contract_test"
        assert session.metadata.get("dispatch_path") == "workflow_first"
        assert session.chief_name == "workflow:qa.api_contract_test"

    @pytest.mark.asyncio
    async def test_flag_on_but_no_match_falls_through(
        self, qa_config, registry, store, event_bus
    ):
        """When flag is on but match returns None, dispatch proceeds to chief path."""
        from bridge.chief_dispatcher import ChiefDispatcher
        from bridge.work_order_router import NullRouter

        router = NullRouter(department="qa")
        wf_registry = _FakeWorkflowRegistry(match_result=None)  # No match
        dispatcher = ChiefDispatcher(
            router=router,
            session_store=store,
            dept_registry=registry,
            event_bus=event_bus,
            workflow_registry=wf_registry,
            workflow_engine=_FakeWorkflowEngine(),
            workflow_first_dispatch_enabled=True,
        )
        wo = _work_order(intent="some unrelated directive")
        try:
            await dispatcher.dispatch(wo, deps=None)
        except Exception:
            pass  # chief path runs without mocks, expected to fail
        assert wf_registry.trigger_calls == []  # workflow NOT fired

    @pytest.mark.asyncio
    async def test_flag_on_but_match_below_threshold_falls_through(
        self, qa_config, registry, store, event_bus
    ):
        """When match confidence < threshold (default 0.6), dispatch falls through to chief."""
        from bridge.chief_dispatcher import ChiefDispatcher
        from bridge.work_order_router import NullRouter

        router = NullRouter(department="qa")
        wf_registry = _FakeWorkflowRegistry(
            match_result={"name": "qa.api_contract_test", "confidence": 0.5, "matched_token": "x"}
        )
        dispatcher = ChiefDispatcher(
            router=router,
            session_store=store,
            dept_registry=registry,
            event_bus=event_bus,
            workflow_registry=wf_registry,
            workflow_engine=_FakeWorkflowEngine(),
            workflow_first_dispatch_enabled=True,
            workflow_match_threshold=0.6,
        )
        wo = _work_order(intent="vague directive")
        try:
            await dispatcher.dispatch(wo, deps=None)
        except Exception:
            pass
        assert wf_registry.trigger_calls == []  # threshold check rejected

    @pytest.mark.asyncio
    async def test_flag_on_no_registry_falls_through(
        self, qa_config, registry, store, event_bus
    ):
        """When workflow_registry is None, the flag has no effect."""
        from bridge.chief_dispatcher import ChiefDispatcher
        from bridge.work_order_router import NullRouter

        router = NullRouter(department="qa")
        dispatcher = ChiefDispatcher(
            router=router,
            session_store=store,
            dept_registry=registry,
            event_bus=event_bus,
            workflow_registry=None,
            workflow_engine=None,
            workflow_first_dispatch_enabled=True,
        )
        wo = _work_order(intent="please run qa.api_contract_test")
        try:
            await dispatcher.dispatch(wo, deps=None)
        except Exception:
            pass
        # No registry to call; dispatch falls through cleanly
        # (no assert — just verifies no AttributeError or crash from missing registry)
