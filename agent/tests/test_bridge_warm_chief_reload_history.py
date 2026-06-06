"""Tests for WarmChief + ChiefDispatcher message_history reload — C.03 (#2297).

Phase 3 of the zone4-warmth program. The flow under test:

1. **WarmChief side** — when constructed with ``message_history=...``,
   ``_run_chief`` threads the kwarg into ``DepartmentTeam.run`` which
   forwards it to ``manager.run(message_history=...)``. When None (the
   default), the chief boots fresh — pre-C.03 behavior.

2. **Dispatcher side** — on the warm-reuse branch, ``dispatch`` calls
   ``store.get_message_history(session_id)`` and feeds the bytes to
   ``_deserialize_history_safe``. Result is threaded into the
   ``WarmChief`` constructor. Corruption / missing blob / cold-start
   all degrade to ``message_history=None`` cleanly.

3. **End-to-end** — a real PydanticAI message list serialized by
   B.02's write path is deserializable by C.03's read path. Proves
   the contract round-trips through SQLite.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any
from unittest import mock
from unittest.mock import MagicMock, patch

import pytest

from bridge.chief_dispatcher import ChiefDispatcher
from bridge.chief_session import ChiefSession, ChiefSessionState
from bridge.chief_session_store import InMemoryChiefSessionStore
from bridge.event_bus import EventBus
from bridge.warm_chief import WarmChief
from bridge.work_order_router import NullRouter
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
    """WorkOrder double with a ``metadata`` dict.

    Mirrors the test double from C.02's lookup tests — the dispatcher
    reads ``metadata.operator`` via duck-typing.
    """

    def __init__(
        self,
        *,
        wo_id: str = "wo-test",
        intent: str = "proceed",
        metadata: dict[str, Any] | None = None,
    ) -> None:
        self.id = wo_id
        self.intent = intent
        self.metadata = metadata if metadata is not None else {}
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
    blob: bytes | None = None,
) -> ChiefSession:
    """Create and persist an AWAITING_EVALUATION session with an
    optional pre-loaded message_history blob.
    """
    import dataclasses as _dc

    session = ChiefSession(
        session_id=session_id,
        work_order_id="wo-prev",
        department=department,
        chief_name=f"{department}-ceo",
        metadata={"operator": operator},
    )
    session = session.transition(ChiefSessionState.WARM)
    session = session.transition(ChiefSessionState.EXECUTING)
    session = session.transition(ChiefSessionState.AWAITING_EVALUATION)

    backdated_idle = (
        datetime.now(timezone.utc) - timedelta(minutes=idle_minutes_ago)
        if session.idle_since_utc is not None
        else None
    )
    session = _dc.replace(
        session,
        idle_since_utc=backdated_idle,
        run_count=run_count,
    )
    await store.create(session)
    if blob is not None:
        await store.update_message_history(session_id, blob)
    return session


# ---------------------------------------------------------------------------
# WarmChief-level tests — kwarg threading
# ---------------------------------------------------------------------------


class TestWarmChiefThreadsMessageHistory:
    """When constructed with ``message_history``, ``_run_chief`` threads
    it through to ``DepartmentTeam.run`` which forwards to
    ``manager.run(message_history=...)``.
    """

    @pytest.mark.asyncio
    async def test_run_chief_with_message_history_passes_to_manager(
        self, board_config
    ):
        """Spec test 1: WarmChief(message_history=[...]) → manager.run
        receives the kwarg.

        We patch ``DepartmentTeam`` at the WarmChief module boundary so
        the chief-build path doesn't try to spin a real PydanticAI
        ``Agent``. The patched team records the kwargs its ``run`` was
        called with so the test can assert the wiring.
        """
        history = [MagicMock(name="msg-1"), MagicMock(name="msg-2")]

        captured_kwargs: dict[str, Any] = {}

        class _FakeTeam:
            def __init__(self, *args, **kwargs) -> None:
                self._last_run_result = MagicMock()

            async def run(self, task, **kwargs):
                captured_kwargs.update(kwargs)
                return _team_result()

        store = InMemoryChiefSessionStore()
        session = ChiefSession(
            session_id="cs-hist01",
            work_order_id="wo-hist",
            department="board",
            chief_name="board-ceo",
            state=ChiefSessionState.WARM,
        )
        await store.create(session)
        deps = make_deps(session_id="cs-hist01", department="board")

        wc = WarmChief(
            session,
            store,
            board_config,
            deps,
            "proceed",
            message_history=history,
        )
        with patch("bridge.warm_chief.DepartmentTeam", _FakeTeam):
            async with wc:
                pass

        assert captured_kwargs.get("message_history") is history

    @pytest.mark.asyncio
    async def test_run_chief_without_message_history_omits_kwarg(
        self, board_config
    ):
        """Spec test 2: WarmChief(message_history=None) → manager.run
        is called WITHOUT the message_history kwarg. Pre-C.03 callers
        see the same call signature they always did.
        """
        captured_kwargs: dict[str, Any] = {}

        class _FakeTeam:
            def __init__(self, *args, **kwargs) -> None:
                self._last_run_result = MagicMock()

            async def run(self, task, **kwargs):
                captured_kwargs.update(kwargs)
                return _team_result()

        store = InMemoryChiefSessionStore()
        session = ChiefSession(
            session_id="cs-nohist01",
            work_order_id="wo-nohist",
            department="board",
            chief_name="board-ceo",
            state=ChiefSessionState.WARM,
        )
        await store.create(session)
        deps = make_deps(session_id="cs-nohist01", department="board")

        wc = WarmChief(
            session,
            store,
            board_config,
            deps,
            "proceed",
            # message_history defaults to None — exercise the default
            # path explicitly via omission.
        )
        with patch("bridge.warm_chief.DepartmentTeam", _FakeTeam):
            async with wc:
                pass

        # ``DepartmentTeam.run`` forwards kwargs to ``manager.run``;
        # both omit ``message_history`` when None.
        assert "message_history" not in captured_kwargs


# ---------------------------------------------------------------------------
# Dispatcher-level tests — load + deserialize + thread into WarmChief
# ---------------------------------------------------------------------------


class TestDispatcherLoadsHistoryOnWarmReuse:
    """``dispatch`` on a warm-reuse branch loads the blob via
    ``get_message_history``, deserializes it, and threads it into
    WarmChief's constructor.
    """

    @pytest.mark.asyncio
    async def test_dispatcher_loads_history_on_warm_reuse(
        self, board_config, registry, store, event_bus
    ):
        """Spec test 3: warm-reuse path loads + deserializes the blob
        and passes the deserialized list into WarmChief.
        """
        blob = b'{"messages": ["fake"]}'
        await _seed_warm_session(
            store,
            session_id="warm-load1",
            department="board",
            operator="default-operator",
            idle_minutes_ago=5.0,
            run_count=1,
            blob=blob,
        )

        router = NullRouter(department="board")
        dispatcher = ChiefDispatcher(
            router=router,
            session_store=store,
            dept_registry=registry,
            event_bus=event_bus,
            warmth_reuse_enabled=True,
        )

        wo = _MetadataWorkOrder(
            wo_id="wo-reload",
            metadata={"operator": "default-operator"},
        )

        # Patch the adapter where the dispatcher imports it — the
        # ``_deserialize_history_safe`` helper lazy-imports the adapter
        # inside the try block so the patch needs to target the
        # ``pydantic_ai.messages`` module that the helper imports from.
        with patch(
            "pydantic_ai.messages.ModelMessagesTypeAdapter"
        ) as mock_adapter:
            mock_adapter.validate_json.return_value = [
                MagicMock(name="deserialized-1"),
                MagicMock(name="deserialized-2"),
            ]

            # Capture the message_history kwarg WarmChief was
            # constructed with via a sentinel patch on ``_run_chief``
            # that reads ``self._message_history`` from the live
            # instance — proves the dispatcher threaded the list into
            # the constructor.
            captured_history: dict[str, Any] = {}

            async def _spy_run_chief(self):  # noqa: ANN001
                captured_history["value"] = self._message_history
                return _team_result()

            with mock.patch.object(
                WarmChief, "_run_chief", _spy_run_chief
            ):
                await dispatcher.dispatch(
                    wo, deps=make_deps(department="board"),
                )

        mock_adapter.validate_json.assert_called_once_with(blob)
        assert captured_history["value"] == (
            mock_adapter.validate_json.return_value
        )

        # warmth_reused event carries the history-present signal.
        events = _events_of(event_bus, "chief_dispatcher.warmth_reused")
        assert len(events) == 1
        payload = events[0].payload
        assert payload["message_history_present"] is True
        assert payload["message_history_count"] == 2

    @pytest.mark.asyncio
    async def test_dispatcher_corrupted_blob_falls_back_to_none(
        self, board_config, registry, store, event_bus
    ):
        """Spec test 4: deserialization failure → message_history=None.

        Chief still runs; the run just starts from a fresh prompt.
        Non-fatal degradation matches the pre-B.02 / pre-C.03 behavior.
        """
        corrupted = b'{"corrupted": malformed'
        await _seed_warm_session(
            store,
            session_id="warm-corrupt1",
            department="board",
            operator="default-operator",
            idle_minutes_ago=5.0,
            blob=corrupted,
        )

        router = NullRouter(department="board")
        dispatcher = ChiefDispatcher(
            router=router,
            session_store=store,
            dept_registry=registry,
            event_bus=event_bus,
            warmth_reuse_enabled=True,
        )

        wo = _MetadataWorkOrder(
            metadata={"operator": "default-operator"},
        )

        with patch(
            "pydantic_ai.messages.ModelMessagesTypeAdapter"
        ) as mock_adapter:
            mock_adapter.validate_json.side_effect = ValueError("bad json")

            captured_history: dict[str, Any] = {}

            async def _spy_run_chief(self):  # noqa: ANN001
                captured_history["value"] = self._message_history
                return _team_result()

            with mock.patch.object(
                WarmChief, "_run_chief", _spy_run_chief
            ):
                result = await dispatcher.dispatch(
                    wo, deps=make_deps(department="board"),
                )

        # WarmChief was constructed with None — corruption swallowed.
        assert captured_history["value"] is None
        # Chief still ran (no exception); session is AWAITING_EVALUATION.
        assert result.state == ChiefSessionState.AWAITING_EVALUATION

        # Event payload reflects the fall-through to fresh-start.
        events = _events_of(event_bus, "chief_dispatcher.warmth_reused")
        payload = events[0].payload
        assert payload["message_history_present"] is False
        assert payload["message_history_count"] == 0

    @pytest.mark.asyncio
    async def test_dispatcher_missing_blob_falls_back_to_none(
        self, board_config, registry, store, event_bus
    ):
        """Spec test 5: row exists but no blob persisted → history=None.

        Models the pre-B.02 row case (column is NULL) and the early
        write-failure case (B.02 logged WARNING and left the column
        NULL). Chief boots fresh; same fall-through as corruption.
        """
        await _seed_warm_session(
            store,
            session_id="warm-noblobseed",
            department="board",
            operator="default-operator",
            idle_minutes_ago=5.0,
            blob=None,  # no blob written
        )

        router = NullRouter(department="board")
        dispatcher = ChiefDispatcher(
            router=router,
            session_store=store,
            dept_registry=registry,
            event_bus=event_bus,
            warmth_reuse_enabled=True,
        )

        wo = _MetadataWorkOrder(
            metadata={"operator": "default-operator"},
        )

        captured_history: dict[str, Any] = {}

        async def _spy_run_chief(self):  # noqa: ANN001
            captured_history["value"] = self._message_history
            return _team_result()

        with mock.patch.object(WarmChief, "_run_chief", _spy_run_chief):
            result = await dispatcher.dispatch(
                wo, deps=make_deps(department="board"),
            )

        assert captured_history["value"] is None
        assert result.state == ChiefSessionState.AWAITING_EVALUATION
        events = _events_of(event_bus, "chief_dispatcher.warmth_reused")
        assert events[0].payload["message_history_present"] is False
        assert events[0].payload["message_history_count"] == 0

    @pytest.mark.asyncio
    async def test_dispatcher_cold_start_does_not_call_get_message_history(
        self, board_config, registry, store, event_bus
    ):
        """Spec test 6: no warm session → ``get_message_history`` never
        called. The reader is only invoked on the reuse branch.
        """
        router = NullRouter(department="board")
        dispatcher = ChiefDispatcher(
            router=router,
            session_store=store,
            dept_registry=registry,
            event_bus=event_bus,
            warmth_reuse_enabled=True,
        )

        wo = _MetadataWorkOrder(
            metadata={"operator": "default-operator"},
        )

        async def _fake_run_chief(self):  # noqa: ANN001
            return _team_result()

        with mock.patch.object(
            store, "get_message_history", autospec=True
        ) as get_spy:
            with mock.patch.object(WarmChief, "_run_chief", _fake_run_chief):
                result = await dispatcher.dispatch(
                    wo, deps=make_deps(department="board"),
                )
            get_spy.assert_not_called()

        # Cold-start path: AWAITING_EVALUATION after run, no
        # warmth_reused event, history is None on the chief.
        assert result.state == ChiefSessionState.AWAITING_EVALUATION
        assert _events_of(event_bus, "chief_dispatcher.warmth_reused") == []


# ---------------------------------------------------------------------------
# End-to-end round-trip — B.02 write side meets C.03 read side
# ---------------------------------------------------------------------------


class TestEndToEndRoundTrip:
    """B.02's serialize-on-success path produces bytes that C.03's
    deserialize-on-reuse path accepts back without semantic loss.
    """

    @pytest.mark.asyncio
    async def test_real_message_list_roundtrips_through_inmemory_store(
        self,
    ):
        """Spec test 7: a real PydanticAI message list serialized by
        ``ModelMessagesTypeAdapter.dump_json`` round-trips through the
        store and back via ``validate_json``.

        Uses InMemoryChiefSessionStore so the test runs without the
        SQLite Database stack (covered separately by
        ``test_migration_16_chief_sessions_blob`` and
        ``test_chief_session_store_sqlite``). The contract is identical:
        ``update_message_history`` round-trips with ``get_message_history``.
        """
        from pydantic_ai.messages import (
            ModelMessagesTypeAdapter,
            ModelRequest,
            UserPromptPart,
        )

        original = [
            ModelRequest(parts=[UserPromptPart(content="initial prompt")]),
        ]
        # B.02 write side
        blob = ModelMessagesTypeAdapter.dump_json(original)

        store = InMemoryChiefSessionStore()
        session = ChiefSession(
            session_id="cs-rt1",
            work_order_id="wo-rt1",
            department="board",
            chief_name="board-ceo",
            state=ChiefSessionState.WARM,
        )
        await store.create(session)
        await store.update_message_history("cs-rt1", blob)

        # C.03 read side
        retrieved_blob = await store.get_message_history("cs-rt1")
        assert retrieved_blob == blob

        deserialized = ModelMessagesTypeAdapter.validate_json(
            retrieved_blob
        )
        assert len(deserialized) == 1
        # PydanticAI preserves the UserPromptPart shape across the
        # round-trip — the chief on reuse sees the same prompt the
        # operator originally sent.
        first_part = deserialized[0].parts[0]
        assert first_part.content == "initial prompt"

    @pytest.mark.asyncio
    async def test_real_message_list_roundtrips_through_sqlite_store(
        self, tmp_path,
    ):
        """Bonus end-to-end: same round-trip through the SQLite store
        instead of the in-memory store. Proves the production-grade
        persistence path (BLOB column ↔ ``ModelMessagesTypeAdapter``)
        survives writes and reads at the SQLite boundary.
        """
        from pydantic_ai.messages import (
            ModelMessagesTypeAdapter,
            ModelRequest,
            UserPromptPart,
        )
        from bridge.chief_session_store import SQLiteChiefSessionStore
        from bridge.database import Database

        original = [
            ModelRequest(parts=[UserPromptPart(content="hello chief")]),
        ]
        blob = ModelMessagesTypeAdapter.dump_json(original)

        db = Database(tmp_path / "rt.db")
        await db.connect()
        await db.migrate()
        store = SQLiteChiefSessionStore(db)

        session = ChiefSession(
            session_id="cs-rt-sqlite",
            work_order_id="wo-rt-sqlite",
            department="board",
            chief_name="board-ceo",
            state=ChiefSessionState.WARM,
        )
        await store.create(session)
        await store.update_message_history("cs-rt-sqlite", blob)

        retrieved_blob = await store.get_message_history("cs-rt-sqlite")
        assert retrieved_blob == blob

        deserialized = ModelMessagesTypeAdapter.validate_json(
            retrieved_blob
        )
        assert len(deserialized) == 1
        assert deserialized[0].parts[0].content == "hello chief"

        await db.close()
