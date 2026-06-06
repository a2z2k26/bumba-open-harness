"""Tests for the SQLite-backed ``ChiefSessionStore`` — Z4-S10 (#1381).

Ports the in-memory test suite from ``test_chief_session_store.py`` to run
against the SQLite implementation by swapping the fixture. The Protocol
contract guarantees the same test surface works against either store.

Two extra suites live here that don't apply to the in-memory impl:
- ``TestSqliteRoundTrip`` — verifies datetime + metadata + nullable
  fields survive an INSERT/SELECT round trip with values intact.
- ``TestSqliteSchema`` — confirms migration #13 actually created the
  ``chief_sessions`` and ``chief_session_history`` tables.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio

from bridge.chief_session import (
    ChiefSession,
    ChiefSessionState,
)
from bridge.chief_session_store import (
    ChiefSessionAlreadyExistsError,
    ChiefSessionNotFoundError,
    ChiefSessionStore,
    SQLiteChiefSessionStore,
)
from bridge.database import Database


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


@pytest_asyncio.fixture
async def store(tmp_path) -> SQLiteChiefSessionStore:
    """Return a SQLiteChiefSessionStore backed by a fresh tmp database.

    Each test gets its own DB so concurrent collection (xdist, etc.) never
    sees cross-test row leaks. The Database is closed at fixture teardown.
    """
    db = Database(tmp_path / "memory.db")
    await db.connect()
    await db.migrate()
    store = SQLiteChiefSessionStore(db)
    yield store
    await db.close()


# ---------------------------------------------------------------------------
# Protocol structural conformance
# ---------------------------------------------------------------------------


class TestProtocolConformance:
    """The SQLite impl must satisfy the runtime-checkable Protocol."""

    def test_sqlite_satisfies_protocol(self, store):
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
        """Spawn many concurrent `update()` calls on the same session id.
        aiosqlite serialises through the underlying connection, so the
        final state must match one of the writes (no torn rows).
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

        # Update all 20 in parallel
        warmed = [s.transition(ChiefSessionState.WARM) for s in sessions]
        await asyncio.gather(*(store.update(s) for s in warmed))

        # Read back and confirm all are WARM
        for s in sessions:
            got = await store.get(s.session_id)
            assert got.state == ChiefSessionState.WARM


# ---------------------------------------------------------------------------
# SQLite-only suites — round-trip fidelity + schema sanity
# ---------------------------------------------------------------------------


class TestSqliteRoundTrip:
    """SQLite-only: confirm every dataclass field survives the SQL boundary."""

    @pytest.mark.asyncio
    async def test_all_fields_round_trip(self, store):
        """Every field on ChiefSession must survive INSERT + SELECT intact.

        This is what catches "I forgot to serialise field X" regressions
        — the equality check at the end is the canary.
        """
        now = datetime.now(timezone.utc)
        s = ChiefSession(
            session_id="cs-roundtripABC",
            work_order_id="wo-roundtrip",
            department="qa",
            chief_name="qa-chief",
            state=ChiefSessionState.AWAITING_EVALUATION,
            created_at_utc=now - timedelta(minutes=5),
            warmed_at_utc=now - timedelta(minutes=4),
            execution_started_at_utc=now - timedelta(minutes=3),
            completed_at_utc=None,  # still in flight
            idle_since_utc=now - timedelta(minutes=1),
            run_count=3,
            cost_usd=0.42,
            error=None,
            metadata={"trace_id": "abc-123", "nested": {"k": [1, 2, 3]}},
        )
        await store.create(s)
        got = await store.get(s.session_id)
        assert got == s

    @pytest.mark.asyncio
    async def test_error_field_round_trips(self, store):
        """Failed sessions populate ``error``; the field must persist."""
        s = _make_session()
        await store.create(s)
        # Drive through the state machine to a FAILED transition with error
        warmed = s.transition(ChiefSessionState.WARM)
        await store.update(warmed)
        running = warmed.transition(ChiefSessionState.EXECUTING)
        await store.update(running)
        failed = running.transition(
            ChiefSessionState.FAILED, error="db connection refused"
        )
        await store.update(failed)

        got = await store.get(s.session_id)
        assert got.state == ChiefSessionState.FAILED
        assert got.error == "db connection refused"
        assert got.completed_at_utc is not None

    @pytest.mark.asyncio
    async def test_metadata_empty_dict_round_trips(self, store):
        """Default metadata is `{}` — the empty mapping must survive too."""
        s = _make_session()
        assert s.metadata == {}
        await store.create(s)
        got = await store.get(s.session_id)
        assert got.metadata == {}

    @pytest.mark.asyncio
    async def test_run_count_and_cost_persist_across_update(self, store):
        """run_count and cost_usd are mutated outside transition() (via
        add_cost and the EXECUTING-transition increment); they must be
        written by update() too.
        """
        s = _make_session()
        await store.create(s)
        # Apply a cost charge + state change, persist, read back.
        charged = s.add_cost(1.25)
        warmed = charged.transition(ChiefSessionState.WARM)
        running = warmed.transition(ChiefSessionState.EXECUTING)
        # run_count should now be 1, cost_usd 1.25
        assert running.run_count == 1
        assert running.cost_usd == 1.25
        await store.update(running)
        got = await store.get(s.session_id)
        assert got.run_count == 1
        assert got.cost_usd == 1.25


class TestSqliteSchema:
    """Confirm migration #13 created the expected schema."""

    @pytest.mark.asyncio
    async def test_chief_sessions_table_exists(self, store):
        rows = await store._db.fetchall(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name='chief_sessions'"
        )
        assert len(rows) == 1

    @pytest.mark.asyncio
    async def test_chief_session_history_table_exists(self, store):
        rows = await store._db.fetchall(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name='chief_session_history'"
        )
        assert len(rows) == 1

    @pytest.mark.asyncio
    async def test_chief_sessions_indexes_exist(self, store):
        rows = await store._db.fetchall(
            "SELECT name FROM sqlite_master WHERE type='index' "
            "AND tbl_name='chief_sessions'"
        )
        names = {r[0] for r in rows}
        assert "idx_chief_sessions_work_order" in names
        assert "idx_chief_sessions_state" in names
        assert "idx_chief_sessions_idle" in names

    @pytest.mark.asyncio
    async def test_state_check_constraint_rejects_unknown_states(self, store):
        """The CHECK constraint is a defence-in-depth backstop. Bypass the
        store and write a raw row to confirm SQLite rejects bad states.
        """
        with pytest.raises(Exception):
            await store._db.execute(
                """INSERT INTO chief_sessions (
                    session_id, work_order_id, department, chief_name, state,
                    created_at_utc, run_count, cost_usd, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    "cs-bad",
                    "wo-bad",
                    "qa",
                    "qa-chief",
                    "not_a_real_state",
                    "2026-05-09T00:00:00+00:00",
                    0,
                    0.0,
                    "{}",
                ),
            )
            await store._db.commit()


# ---------------------------------------------------------------------------
# update_message_history — zone4-warmth.B.02 (#2294) SQLite path
# ---------------------------------------------------------------------------


class TestUpdateMessageHistorySqlite:
    @pytest.mark.asyncio
    async def test_round_trip_writes_and_reads_blob(self, store):
        """Write a blob, read it back via direct SELECT to confirm BLOB
        round-trip through aiosqlite.
        """
        s = _make_session(session_id="cs-sql-blob01")
        await store.create(s)
        blob = b'{"messages": ["sqlite ok"]}'

        await store.update_message_history("cs-sql-blob01", blob)
        row = await store._db.fetchone(
            "SELECT message_history_blob FROM chief_sessions "
            "WHERE session_id = ?",
            ("cs-sql-blob01",),
        )
        assert row is not None
        assert bytes(row["message_history_blob"]) == blob

    @pytest.mark.asyncio
    async def test_overwrite_replaces_existing_blob(self, store):
        """Idempotent at the row level: last write wins."""
        s = _make_session(session_id="cs-sql-blob02")
        await store.create(s)
        await store.update_message_history("cs-sql-blob02", b"first")
        await store.update_message_history("cs-sql-blob02", b"second")
        row = await store._db.fetchone(
            "SELECT message_history_blob FROM chief_sessions "
            "WHERE session_id = ?",
            ("cs-sql-blob02",),
        )
        assert bytes(row["message_history_blob"]) == b"second"

    @pytest.mark.asyncio
    async def test_missing_session_raises_not_found(self, store):
        """Missing row surfaces ChiefSessionNotFoundError — matches Protocol."""
        with pytest.raises(ChiefSessionNotFoundError):
            await store.update_message_history("cs-sql-never", b"x")

    @pytest.mark.asyncio
    async def test_blob_column_starts_null(self, store):
        """A fresh row has message_history_blob = NULL until written."""
        s = _make_session(session_id="cs-sql-blob03")
        await store.create(s)
        row = await store._db.fetchone(
            "SELECT message_history_blob FROM chief_sessions "
            "WHERE session_id = ?",
            ("cs-sql-blob03",),
        )
        assert row["message_history_blob"] is None


# ---------------------------------------------------------------------------
# Migration idempotency — Z4-S10 acceptance criterion
# ---------------------------------------------------------------------------


class TestMigrationIdempotency:
    """The new migration must be a no-op when re-applied to an existing DB."""

    @pytest.mark.asyncio
    async def test_migrate_twice_is_a_noop(self, tmp_path):
        db = Database(tmp_path / "memory.db")
        await db.connect()
        await db.migrate()
        v1 = await db.get_schema_version()
        assert v1 >= 13
        # Run a second time — must not error or bump the version
        await db.migrate()
        v2 = await db.get_schema_version()
        assert v1 == v2
        await db.close()
