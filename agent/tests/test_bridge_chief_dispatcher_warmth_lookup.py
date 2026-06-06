"""Tests for ChiefDispatcher warmth-reuse lookup — zone4-warmth.C.02 (#2296).

Covers the pre-dispatch warm-session lookup added at the top of
``ChiefDispatcher.dispatch``. When the ``warmth_reuse_enabled`` flag is
True AND ``store.find_warm_session`` returns an AWAITING_EVALUATION
session for ``(department, operator)`` within the configured idle window,
dispatch short-circuits: AWAITING_EVALUATION → WARM, manual ``run_count``
bump (since no EXECUTING transition runs in this sprint), publish
``chief_dispatcher.warmth_reused``, return the reused row. No COLD
session is created, no chief runs.

**Spec drift note:** the sprint doc described a ``chief_sessions.updated_at``
column. ``ChiefSession`` has no such field; the state machine sets
``idle_since_utc`` on the ``→ AWAITING_EVALUATION`` arc, which is exactly
the "moment this conversation went idle" the warm-window lookup wants to
measure against. The tests below use ``idle_since_utc`` accordingly.

**Operator identity:** Option 2 from the sprint spec. Dispatcher reads
``metadata.operator`` off the WorkOrder when present; falls back to the
string constant ``"default-operator"``.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any
from unittest import mock

import pytest

from bridge.chief_dispatcher import ChiefDispatcher
from bridge.chief_session import ChiefSession, ChiefSessionState
from bridge.chief_session_store import InMemoryChiefSessionStore
from bridge.event_bus import EventBus
from bridge.warm_chief import WarmChief
from bridge.work_order import WorkOrder
from bridge.work_order_router import (
    NullRouter,
)
from teams._types import AgentSpec, DepartmentConfig, TeamResult
from tests.test_teams.conftest import make_deps


# ---------------------------------------------------------------------------
# Test doubles + fixtures
# ---------------------------------------------------------------------------


@dataclass
class _FakeRegistry:
    """Minimal DepartmentRegistry substitute — returns None on miss."""

    configs: dict[str, DepartmentConfig] = field(default_factory=dict)

    def get_config(self, name: str) -> DepartmentConfig | None:
        return self.configs.get(name)


class _MetadataWorkOrder:
    """WorkOrder double that carries a ``metadata`` dict.

    Real ``WorkOrder`` has no ``metadata`` field today (see
    ``bridge.work_order.WorkOrder``); the sprint spec extends the
    contract via duck-typing — the dispatcher reads
    ``getattr(work_order, "metadata", None)``. This double keeps the
    fixture explicit without coupling tests to the WorkOrder dataclass.
    """

    def __init__(
        self,
        *,
        wo_id: str = "wo-test",
        intent: str = "do the thing",
        metadata: dict[str, Any] | None = None,
    ) -> None:
        self.id = wo_id
        self.intent = intent
        self.metadata = metadata if metadata is not None else {}
        # Mirror enough of the real shape for the dispatcher's
        # ``_task_from_work_order`` helper:
        self.input = None


@pytest.fixture
def board_config() -> DepartmentConfig:
    return DepartmentConfig(
        name="board",
        zone=4,
        description="Board department",
        manager=AgentSpec(name="board-ceo", model="anthropic:claude-opus-4-6"),
        employees=(),
    )


@pytest.fixture
def registry(board_config: DepartmentConfig) -> _FakeRegistry:
    return _FakeRegistry(configs={"board": board_config})


@pytest.fixture
def store() -> InMemoryChiefSessionStore:
    return InMemoryChiefSessionStore()


@pytest.fixture
def event_bus(tmp_path) -> EventBus:
    return EventBus(data_dir=tmp_path)


def _events_of(bus: EventBus, event_type: str) -> list[Any]:
    return [e for e in bus._recent_events if e.event_type == event_type]


def _team_result() -> TeamResult:
    return TeamResult(
        department="board",
        manager_output="ok",
        employee_results=(),
        total_tokens=0,
        total_cost_usd=0.0,
        duration_seconds=0.01,
        success=True,
        error=None,
    )


async def _seed_warm_session(
    store: InMemoryChiefSessionStore,
    *,
    session_id: str = "warm-1",
    department: str = "board",
    operator: str = "default-operator",
    idle_minutes_ago: float = 5.0,
    run_count: int = 1,
    state: ChiefSessionState = ChiefSessionState.AWAITING_EVALUATION,
) -> ChiefSession:
    """Create and persist a session in the requested state.

    Goes through the legal state-machine arcs:
    COLD → WARM → EXECUTING → AWAITING_EVALUATION
    so ``idle_since_utc`` is naturally set by the transition logic. We
    then back-date it to ``idle_minutes_ago`` minutes ago for the warm-
    window assertion. ``run_count`` is overridden after the EXECUTING
    bump so each test can request its own value.
    """
    session = ChiefSession(
        session_id=session_id,
        work_order_id="wo-prev",
        department=department,
        chief_name=f"{department}-ceo",
        metadata={"operator": operator},
    )
    session = session.transition(ChiefSessionState.WARM)
    if state in (
        ChiefSessionState.EXECUTING,
        ChiefSessionState.AWAITING_EVALUATION,
        ChiefSessionState.FAILED,
        ChiefSessionState.DONE,
        ChiefSessionState.TIMED_OUT,
        ChiefSessionState.SHUTDOWN,
    ):
        session = session.transition(ChiefSessionState.EXECUTING)
    if state == ChiefSessionState.AWAITING_EVALUATION:
        session = session.transition(ChiefSessionState.AWAITING_EVALUATION)
    elif state == ChiefSessionState.FAILED:
        session = session.transition(ChiefSessionState.FAILED, error="x")
    elif state == ChiefSessionState.TIMED_OUT:
        session = session.transition(ChiefSessionState.TIMED_OUT)
    elif state == ChiefSessionState.DONE:
        session = session.transition(ChiefSessionState.AWAITING_EVALUATION)
        session = session.transition(ChiefSessionState.DONE)
    elif state == ChiefSessionState.SHUTDOWN:
        # WARM → SHUTDOWN is legal.
        session = ChiefSession(
            session_id=session_id,
            work_order_id="wo-prev",
            department=department,
            chief_name=f"{department}-ceo",
            metadata={"operator": operator},
        )
        session = session.transition(ChiefSessionState.WARM)
        session = session.transition(ChiefSessionState.SHUTDOWN)

    # Back-date idle_since_utc + override run_count.
    backdated_idle = (
        datetime.now(timezone.utc) - timedelta(minutes=idle_minutes_ago)
        if session.idle_since_utc is not None
        else None
    )
    import dataclasses as _dc
    session = _dc.replace(
        session,
        idle_since_utc=backdated_idle,
        run_count=run_count,
    )
    await store.create(session)
    return session


# ---------------------------------------------------------------------------
# Dispatcher-level tests
# ---------------------------------------------------------------------------


class TestDispatcherWarmthReuse:
    """The dispatcher's pre-dispatch warm lookup behavior."""

    @pytest.mark.asyncio
    async def test_flag_on_reuses_warm_session_when_found(
        self, board_config, registry, store, event_bus
    ):
        """Flag on + in-window AWAITING_EVALUATION match → reuse path.

        Updated for zone4-warmth.C.03 (#2297): the reuse path no longer
        short-circuits before WarmChief — it runs the chief against the
        same row with the prior message_history threaded in. Final state
        after the chief run is AWAITING_EVALUATION (WarmChief's __aexit__
        success transition); run_count climbs by one EXECUTING bump.
        """
        await _seed_warm_session(
            store,
            session_id="warm-1",
            department="board",
            operator="default-operator",
            idle_minutes_ago=5.0,
            run_count=1,
        )

        router = NullRouter(department="board")
        dispatcher = ChiefDispatcher(
            router=router,
            session_store=store,
            dept_registry=registry,
            event_bus=event_bus,
            warmth_reuse_enabled=True,
            warmth_idle_window_seconds=1800.0,
        )

        wo = _MetadataWorkOrder(
            wo_id="wo-new",
            metadata={"operator": "default-operator"},
        )

        async def _fake_run_chief(self):  # noqa: ANN001
            return _team_result()

        with mock.patch.object(WarmChief, "_run_chief", _fake_run_chief):
            result = await dispatcher.dispatch(
                wo, deps=make_deps(department="board"),
            )

        assert result.session_id == "warm-1"
        # C.03: chief ran via WarmChief, ending in AWAITING_EVALUATION.
        assert result.state == ChiefSessionState.AWAITING_EVALUATION
        # run_count was 1, WARM→EXECUTING bump in __aenter__ → 2.
        assert result.run_count == 2

        # warmth_reused event published.
        events = _events_of(event_bus, "chief_dispatcher.warmth_reused")
        assert len(events) == 1
        payload = events[0].payload
        assert payload["session_id"] == "warm-1"
        assert payload["work_order_id"] == "wo-new"
        assert payload["department"] == "board"
        assert payload["operator"] == "default-operator"
        # C.03: run_count in event reflects the row-after-reuse-prep
        # (post AWAITING_EVALUATION→WARM, pre WarmChief execution).
        assert payload["run_count"] == 1
        assert payload["age_seconds"] == pytest.approx(300.0, rel=0.2)
        # C.03 fields: no blob was persisted on the seeded row, so
        # the message_history reload comes back as None.
        assert payload["message_history_present"] is False
        assert payload["message_history_count"] == 0

        # No new COLD session was created — store still has exactly one row.
        assert await store._count() == 1

    @pytest.mark.asyncio
    async def test_flag_off_does_not_consult_find_warm_session(
        self, board_config, registry, store, event_bus
    ):
        """Flag off → find_warm_session is never called; cold-start runs."""
        router = NullRouter(department="board")
        dispatcher = ChiefDispatcher(
            router=router,
            session_store=store,
            dept_registry=registry,
            event_bus=event_bus,
            warmth_reuse_enabled=False,
        )

        wo = _MetadataWorkOrder(
            wo_id="wo-new",
            metadata={"operator": "default-operator"},
        )

        async def _fake_run_chief(self):  # noqa: ANN001
            return _team_result()

        with mock.patch.object(
            store, "find_warm_session", autospec=True
        ) as spy:
            with mock.patch.object(WarmChief, "_run_chief", _fake_run_chief):
                result = await dispatcher.dispatch(wo, deps=make_deps(department="board"))
            spy.assert_not_called()

        # New session created via the cold-start path.
        assert result.state == ChiefSessionState.AWAITING_EVALUATION
        assert result.run_count == 1  # EXECUTING bump from the chief run
        assert _events_of(event_bus, "chief_dispatcher.warmth_reused") == []
        assert _events_of(event_bus, "chief_dispatcher.routed")

    @pytest.mark.asyncio
    async def test_flag_on_no_warm_session_creates_cold(
        self, board_config, registry, store, event_bus
    ):
        """Flag on + store returns None → cold-start path runs."""
        router = NullRouter(department="board")
        dispatcher = ChiefDispatcher(
            router=router,
            session_store=store,
            dept_registry=registry,
            event_bus=event_bus,
            warmth_reuse_enabled=True,
        )

        wo = _MetadataWorkOrder(metadata={"operator": "default-operator"})

        async def _fake_run_chief(self):  # noqa: ANN001
            return _team_result()

        with mock.patch.object(WarmChief, "_run_chief", _fake_run_chief):
            result = await dispatcher.dispatch(wo, deps=make_deps(department="board"))

        # Cold start: new session, AWAITING_EVALUATION after chief run.
        assert result.state == ChiefSessionState.AWAITING_EVALUATION
        assert result.run_count == 1
        # No warmth_reused event.
        assert _events_of(event_bus, "chief_dispatcher.warmth_reused") == []
        # The routed event fired (cold-start observability).
        assert _events_of(event_bus, "chief_dispatcher.routed")

    @pytest.mark.asyncio
    async def test_flag_on_out_of_window_session_creates_cold(
        self, board_config, registry, store, event_bus
    ):
        """Flag on + only a stale (out-of-window) match → cold-start path."""
        # Seed a session 2 hours old; window is 30 minutes (default).
        await _seed_warm_session(
            store,
            session_id="stale-1",
            department="board",
            operator="default-operator",
            idle_minutes_ago=120.0,
            run_count=1,
        )

        router = NullRouter(department="board")
        dispatcher = ChiefDispatcher(
            router=router,
            session_store=store,
            dept_registry=registry,
            event_bus=event_bus,
            warmth_reuse_enabled=True,
            warmth_idle_window_seconds=1800.0,  # 30 min
        )

        wo = _MetadataWorkOrder(metadata={"operator": "default-operator"})

        async def _fake_run_chief(self):  # noqa: ANN001
            return _team_result()

        with mock.patch.object(WarmChief, "_run_chief", _fake_run_chief):
            result = await dispatcher.dispatch(wo, deps=make_deps(department="board"))

        # The stale session was NOT reused; a fresh AWAITING_EVALUATION row exists.
        assert result.session_id != "stale-1"
        assert result.run_count == 1  # fresh chief run, single EXECUTING bump
        assert _events_of(event_bus, "chief_dispatcher.warmth_reused") == []

    @pytest.mark.asyncio
    async def test_operator_extracted_from_work_order_metadata(
        self, board_config, registry, store, event_bus
    ):
        """Operator from metadata.operator scopes the lookup (Option 2)."""
        # Seed a warm row for operator "alice".
        await _seed_warm_session(
            store,
            session_id="warm-alice",
            department="board",
            operator="alice",
            idle_minutes_ago=5.0,
            run_count=1,
        )

        router = NullRouter(department="board")
        dispatcher = ChiefDispatcher(
            router=router,
            session_store=store,
            dept_registry=registry,
            event_bus=event_bus,
            warmth_reuse_enabled=True,
        )

        # WO from alice → reuse alice's row.
        wo_alice = _MetadataWorkOrder(metadata={"operator": "alice"})

        async def _fake_run_chief(self):  # noqa: ANN001
            return _team_result()

        with mock.patch.object(WarmChief, "_run_chief", _fake_run_chief):
            result = await dispatcher.dispatch(
                wo_alice, deps=make_deps(department="board"),
            )
        assert result.session_id == "warm-alice"
        events = _events_of(event_bus, "chief_dispatcher.warmth_reused")
        assert events[-1].payload["operator"] == "alice"

    @pytest.mark.asyncio
    async def test_operator_falls_back_to_default_operator_constant(
        self, board_config, registry, store, event_bus
    ):
        """No metadata.operator → fallback "default-operator" used as key."""
        await _seed_warm_session(
            store,
            session_id="warm-default",
            department="board",
            operator="default-operator",
            idle_minutes_ago=5.0,
            run_count=1,
        )

        router = NullRouter(department="board")
        dispatcher = ChiefDispatcher(
            router=router,
            session_store=store,
            dept_registry=registry,
            event_bus=event_bus,
            warmth_reuse_enabled=True,
        )

        # Real WorkOrder has no metadata attr at all — the dispatcher
        # must still resolve operator via the fallback.
        wo = WorkOrder.create(intent="x", skill="x", project="p")

        async def _fake_run_chief(self):  # noqa: ANN001
            return _team_result()

        with mock.patch.object(WarmChief, "_run_chief", _fake_run_chief):
            result = await dispatcher.dispatch(
                wo, deps=make_deps(department="board"),
            )
        assert result.session_id == "warm-default"
        events = _events_of(event_bus, "chief_dispatcher.warmth_reused")
        assert events[-1].payload["operator"] == "default-operator"


# ---------------------------------------------------------------------------
# Store-level tests — find_warm_session contract
# ---------------------------------------------------------------------------


class TestFindWarmSessionContract:
    """Direct tests of ``InMemoryChiefSessionStore.find_warm_session``."""

    @pytest.mark.asyncio
    async def test_returns_in_window_match(self, store):
        await _seed_warm_session(
            store,
            session_id="s1",
            department="board",
            operator="op-a",
            idle_minutes_ago=5.0,
        )
        result = await store.find_warm_session(
            "board", "op-a", max_age_seconds=600.0,
        )
        assert result is not None
        assert result.session_id == "s1"

    @pytest.mark.asyncio
    async def test_returns_none_when_out_of_window(self, store):
        await _seed_warm_session(
            store,
            session_id="s2",
            department="board",
            operator="op-a",
            idle_minutes_ago=120.0,
        )
        # Window 1 hour; session 2 hours old.
        result = await store.find_warm_session(
            "board", "op-a", max_age_seconds=3600.0,
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_ignores_non_awaiting_evaluation_states(self, store):
        # Seed rows in every non-AWAITING_EVALUATION state we can reach
        # from the COLD → WARM → EXECUTING → ... arcs. find_warm_session
        # must reject all of them.
        for idx, state in enumerate([
            ChiefSessionState.FAILED,
            ChiefSessionState.TIMED_OUT,
            ChiefSessionState.SHUTDOWN,
        ]):
            await _seed_warm_session(
                store,
                session_id=f"s-{state.value}",
                department="board",
                operator="op-a",
                idle_minutes_ago=5.0,
                state=state,
            )
        result = await store.find_warm_session(
            "board", "op-a", max_age_seconds=600.0,
        )
        assert result is None
