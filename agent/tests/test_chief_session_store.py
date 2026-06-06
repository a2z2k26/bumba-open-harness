"""Tests for `bridge.chief_session_store` — Z4-S03 (#1387).

Coverage target: 90%+ on `InMemoryChiefSessionStore`. Tests are written
against the `ChiefSessionStore` Protocol so the same suite ports to the
SQLite impl in Z4-S10 (#1381) by swapping the fixture.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from bridge.chief_session import (
    ChiefSession,
    ChiefSessionState,
)
from bridge.chief_session_store import (
    ChiefSessionAlreadyExistsError,
    ChiefSessionNotFoundError,
    ChiefSessionStore,
    InMemoryChiefSessionStore,
)


def _make_session(
    session_id: str = "cs-test01abcdef",
    work_order_id: str = "wo-test",
    department: str = "strategy",
    state: ChiefSessionState = ChiefSessionState.COLD,
    *,
    idle_since_utc: datetime | None = None,
    created_at_utc: datetime | None = None,
) -> ChiefSession:
    """Build a stub ChiefSession with optional override of timestamp fields."""
    overrides: dict = {}
    if idle_since_utc is not None:
        overrides["idle_since_utc"] = idle_since_utc
    if created_at_utc is not None:
        overrides["created_at_utc"] = created_at_utc
    return ChiefSession(
        session_id=session_id,
        work_order_id=work_order_id,
        department=department,
        chief_name=f"{department}-chief",
        state=state,
        **overrides,
    )


@pytest.fixture
def store() -> InMemoryChiefSessionStore:
    return InMemoryChiefSessionStore()


# ---------------------------------------------------------------------------
# Protocol structural conformance
# ---------------------------------------------------------------------------


class TestProtocolConformance:
    """The in-memory impl must satisfy the runtime-checkable Protocol."""

    def test_in_memory_satisfies_protocol(self, store):
        # `runtime_checkable` Protocols use isinstance() at runtime.
        assert isinstance(store, ChiefSessionStore)


# ---------------------------------------------------------------------------
# create / get round-trip
# ---------------------------------------------------------------------------


class TestCreateAndGet:
    @pytest.mark.asyncio
    async def test_create_then_get_returns_same_session(self, store):
        s = _make_session()
        await store.create(s)
        got = await store.get(s.session_id)
        assert got == s

    @pytest.mark.asyncio
    async def test_get_unknown_id_raises(self, store):
        with pytest.raises(ChiefSessionNotFoundError) as exc:
            await store.get("cs-does-not-exist")
        assert exc.value.session_id == "cs-does-not-exist"

    @pytest.mark.asyncio
    async def test_create_duplicate_raises(self, store):
        s = _make_session()
        await store.create(s)
        with pytest.raises(ChiefSessionAlreadyExistsError) as exc:
            await store.create(s)
        assert exc.value.session_id == s.session_id

    @pytest.mark.asyncio
    async def test_create_duplicate_is_caught_by_value_error(self, store):
        """ChiefSessionAlreadyExistsError subclasses ValueError so callers
        catching the looser type per the issue spec still work.
        """
        s = _make_session()
        await store.create(s)
        with pytest.raises(ValueError):
            await store.create(s)


# ---------------------------------------------------------------------------
# update
# ---------------------------------------------------------------------------


class TestUpdate:
    @pytest.mark.asyncio
    async def test_update_overwrites_stored_row(self, store):
        s = _make_session()
        await store.create(s)
        s_warm = s.transition(ChiefSessionState.WARM)
        await store.update(s_warm)
        got = await store.get(s.session_id)
        assert got.state == ChiefSessionState.WARM
        assert got.warmed_at_utc is not None

    @pytest.mark.asyncio
    async def test_update_unknown_id_raises(self, store):
        s = _make_session(session_id="cs-never-created")
        with pytest.raises(ChiefSessionNotFoundError):
            await store.update(s)

    @pytest.mark.asyncio
    async def test_update_is_not_an_upsert(self, store):
        """The contract says update() requires an existing row — it's not
        a silent insert. This makes 'dispatcher forgot to create()' a
        loud failure.
        """
        s = _make_session()
        # Don't call create first
        with pytest.raises(ChiefSessionNotFoundError):
            await store.update(s)
        # And confirm nothing was inserted
        with pytest.raises(ChiefSessionNotFoundError):
            await store.get(s.session_id)


# ---------------------------------------------------------------------------
# list_by_work_order
# ---------------------------------------------------------------------------


class TestListByWorkOrder:
    @pytest.mark.asyncio
    async def test_returns_only_sessions_for_that_work_order(self, store):
        s1 = _make_session(session_id="cs-aaaaaaaaaaaa", work_order_id="wo-A")
        s2 = _make_session(session_id="cs-bbbbbbbbbbbb", work_order_id="wo-A")
        s3 = _make_session(session_id="cs-cccccccccccc", work_order_id="wo-B")
        for s in (s1, s2, s3):
            await store.create(s)

        result = await store.list_by_work_order("wo-A")
        ids = [s.session_id for s in result]
        assert ids == ["cs-aaaaaaaaaaaa", "cs-bbbbbbbbbbbb"]

    @pytest.mark.asyncio
    async def test_returns_in_creation_order(self, store):
        # Create deliberately out of order to prove the sort key works
        early = datetime(2026, 5, 1, tzinfo=timezone.utc)
        later = datetime(2026, 5, 8, tzinfo=timezone.utc)
        s_late = _make_session(
            session_id="cs-late",
            work_order_id="wo-X",
            created_at_utc=later,
        )
        s_early = _make_session(
            session_id="cs-early",
            work_order_id="wo-X",
            created_at_utc=early,
        )
        await store.create(s_late)
        await store.create(s_early)

        result = await store.list_by_work_order("wo-X")
        assert [s.session_id for s in result] == ["cs-early", "cs-late"]

    @pytest.mark.asyncio
    async def test_returns_empty_when_no_match(self, store):
        await store.create(_make_session(work_order_id="wo-A"))
        assert await store.list_by_work_order("wo-NOPE") == []


# ---------------------------------------------------------------------------
# list_by_state
# ---------------------------------------------------------------------------


class TestListByState:
    @pytest.mark.asyncio
    async def test_returns_only_sessions_in_that_state(self, store):
        s_cold = _make_session(
            session_id="cs-cold0000000", state=ChiefSessionState.COLD
        )
        s_warm = _make_session(
            session_id="cs-warm0000000", state=ChiefSessionState.WARM
        )
        s_exec = _make_session(
            session_id="cs-exec0000000", state=ChiefSessionState.EXECUTING
        )
        for s in (s_cold, s_warm, s_exec):
            await store.create(s)

        warm_only = await store.list_by_state(ChiefSessionState.WARM)
        assert [s.session_id for s in warm_only] == ["cs-warm0000000"]

    @pytest.mark.asyncio
    async def test_returns_empty_when_no_match(self, store):
        await store.create(_make_session(state=ChiefSessionState.COLD))
        assert await store.list_by_state(ChiefSessionState.SHUTDOWN) == []


# ---------------------------------------------------------------------------
# list_idle — the reaper-facing query
# ---------------------------------------------------------------------------


class TestListIdle:
    @pytest.mark.asyncio
    async def test_returns_sessions_idle_longer_than_threshold(self, store):
        now = datetime.now(timezone.utc)
        # Idle for 100s — older than threshold of 60s
        old = _make_session(
            session_id="cs-old000000000",
            state=ChiefSessionState.AWAITING_EVALUATION,
            idle_since_utc=now - timedelta(seconds=100),
        )
        # Idle for 30s — younger than threshold
        young = _make_session(
            session_id="cs-young00000000",
            state=ChiefSessionState.AWAITING_EVALUATION,
            idle_since_utc=now - timedelta(seconds=30),
        )
        for s in (old, young):
            await store.create(s)

        result = await store.list_idle(older_than_seconds=60.0)
        assert [s.session_id for s in result] == ["cs-old000000000"]

    @pytest.mark.asyncio
    async def test_excludes_non_awaiting_evaluation_states(self, store):
        """Even if idle_since_utc is set, a session must be in
        AWAITING_EVALUATION to be reaped — other states are caller-owned.
        """
        now = datetime.now(timezone.utc)
        for state in (
            ChiefSessionState.COLD,
            ChiefSessionState.WARM,
            ChiefSessionState.EXECUTING,
            ChiefSessionState.DONE,
            ChiefSessionState.FAILED,
        ):
            s = _make_session(
                session_id=f"cs-{state.value:14s}"[:15],
                state=state,
                idle_since_utc=now - timedelta(seconds=300),
            )
            await store.create(s)

        result = await store.list_idle(older_than_seconds=60.0)
        assert result == []

    @pytest.mark.asyncio
    async def test_excludes_sessions_without_idle_since(self, store):
        s = _make_session(
            state=ChiefSessionState.AWAITING_EVALUATION,
            # idle_since_utc deliberately not set
        )
        await store.create(s)
        result = await store.list_idle(older_than_seconds=0.0)
        assert result == []

    @pytest.mark.asyncio
    async def test_threshold_zero_returns_all_idle_sessions(self, store):
        """Threshold of 0s catches every AWAITING_EVALUATION session with
        idle_since_utc set (regardless of how recent).
        """
        s = _make_session(
            state=ChiefSessionState.AWAITING_EVALUATION,
            idle_since_utc=datetime.now(timezone.utc) - timedelta(seconds=0.001),
        )
        await store.create(s)
        result = await store.list_idle(older_than_seconds=0.0)
        assert len(result) == 1


# ---------------------------------------------------------------------------
# Concurrency — concurrent updates do not corrupt state
# ---------------------------------------------------------------------------


class TestConcurrency:
    @pytest.mark.asyncio
    async def test_concurrent_updates_do_not_corrupt_state(self, store):
        """Spawn many concurrent `update()` calls on the same session id —
        the asyncio.Lock serialises them, so the final state must match
        one of the writes (no torn rows).
        """
        s = _make_session()
        await store.create(s)

        async def write_state(state: ChiefSessionState) -> None:
            current = await store.get(s.session_id)
            # Force-construct a session with the target state without
            # going through transition() (we want to test the store's
            # concurrency, not the state machine).
            await store.update(
                ChiefSession(
                    session_id=current.session_id,
                    work_order_id=current.work_order_id,
                    department=current.department,
                    chief_name=current.chief_name,
                    state=state,
                )
            )

        # 50 concurrent writes alternating between two states — winner
        # is one of them, never a corruption.
        tasks = [
            write_state(
                ChiefSessionState.WARM if i % 2 == 0 else ChiefSessionState.EXECUTING
            )
            for i in range(50)
        ]
        await asyncio.gather(*tasks)

        final = await store.get(s.session_id)
        assert final.state in (
            ChiefSessionState.WARM,
            ChiefSessionState.EXECUTING,
        )

    @pytest.mark.asyncio
    async def test_concurrent_create_then_update_resolves_cleanly(self, store):
        """Concurrent `create` + `update` for different sessions do not
        deadlock or interleave incorrectly.
        """
        sessions = [
            _make_session(session_id=f"cs-{i:012d}")
            for i in range(20)
        ]
        # Create all 20 in parallel
        await asyncio.gather(*(store.create(s) for s in sessions))
        assert await store._count() == 20

        # Update all 20 in parallel
        warmed = [s.transition(ChiefSessionState.WARM) for s in sessions]
        await asyncio.gather(*(store.update(s) for s in warmed))

        all_sessions = await store._all()
        assert len(all_sessions) == 20
        assert all(s.state == ChiefSessionState.WARM for s in all_sessions)


# ---------------------------------------------------------------------------
# Independent instances — sessions don't bleed between stores
# ---------------------------------------------------------------------------


class TestStoreIsolation:
    @pytest.mark.asyncio
    async def test_separate_stores_have_separate_state(self):
        a = InMemoryChiefSessionStore()
        b = InMemoryChiefSessionStore()
        await a.create(_make_session(session_id="cs-in-a000000000"))
        # Store b doesn't have it
        with pytest.raises(ChiefSessionNotFoundError):
            await b.get("cs-in-a000000000")


# ---------------------------------------------------------------------------
# update_message_history — zone4-warmth.B.02 (#2294)
# ---------------------------------------------------------------------------


class TestUpdateMessageHistory:
    @pytest.mark.asyncio
    async def test_round_trip_writes_and_reads_blob(self, store):
        """Write a blob to an existing session, read it back unchanged."""
        s = _make_session(session_id="cs-blob01")
        await store.create(s)
        blob = b'{"messages": ["hello"]}'

        await store.update_message_history("cs-blob01", blob)
        got = await store.get_message_history_blob("cs-blob01")
        assert got == blob

    @pytest.mark.asyncio
    async def test_missing_blob_returns_none(self, store):
        """Sessions without a written blob report None — pre-B.02 default."""
        s = _make_session(session_id="cs-blob02")
        await store.create(s)
        assert await store.get_message_history_blob("cs-blob02") is None

    @pytest.mark.asyncio
    async def test_overwrite_replaces_existing_blob(self, store):
        """Repeated calls overwrite — last writer wins."""
        s = _make_session(session_id="cs-blob03")
        await store.create(s)
        await store.update_message_history("cs-blob03", b"first")
        await store.update_message_history("cs-blob03", b"second")
        assert await store.get_message_history_blob("cs-blob03") == b"second"

    @pytest.mark.asyncio
    async def test_missing_session_raises_not_found(self, store):
        """Writing to a session_id that doesn't exist surfaces a loud error.

        The B.02 caller (``WarmChief.__aexit__``) creates the row long
        before this method is reached, so a missing row here signals a
        lifecycle bug rather than a silent-insert opportunity.
        """
        with pytest.raises(ChiefSessionNotFoundError):
            await store.update_message_history("cs-never-existed", b"x")
