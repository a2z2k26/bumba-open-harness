"""ChiefSessionStore — Z4-S03 (#1387) persistence protocol + in-memory impl.

Storage layer for the ``ChiefSession`` rows defined in ``bridge.chief_session``
(Z4-S01 #1385). Today's chief lifecycle is WARM single-run (per the team-
playbook from Z4-S00 #1384) — but the *envelope* tracking each chief's work
across requeues, retries, and idle-timeout reaping needs to survive bridge
restarts. This module is the persistence contract.

Two implementations land in this sprint:

- ``ChiefSessionStore`` — runtime-checkable Protocol. Structural typing
  (no inheritance) so the SQLite-backed impl from Z4-S10 (#1381) can
  satisfy the contract without subclassing.
- ``InMemoryChiefSessionStore`` — thread-safe (asyncio-Lock) dict-backed
  implementation for tests + dev. Real production uses the SQLite impl
  (Z4-S10 #1381).

Why a separate sprint for the in-memory impl: the SQLite migration in
Z4-S10 needs to write a real schema, run a forward migration, and pass
the same protocol tests. By landing the protocol + in-memory impl first,
Z4-S10 has a fixed shape to build against.

Companion docs:
  - `agent/bridge/chief_session.py` — the row type
  - `docs/zone4/team-playbook.md` — the WARM single-run invariant the
    *chief agent* preserves while the *session envelope* lives across runs
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from bridge.chief_session import ChiefSession, ChiefSessionState

if TYPE_CHECKING:
    from bridge.database import Database


class ChiefSessionNotFoundError(Exception):
    """Raised when a ChiefSession lookup misses.

    Carries the session_id so log triage can match to the create() event.
    """

    def __init__(self, session_id: str) -> None:
        super().__init__(f"ChiefSession not found: {session_id}")
        self.session_id = session_id


class ChiefSessionAlreadyExistsError(ValueError):
    """Raised when ``create()`` is called for an id that already exists.

    Subclasses ``ValueError`` so callers that want to catch it as the
    issue spec described still can (the spec says "raises ValueError on
    duplicate"); a more-specific subclass keeps the door open for
    targeted handling without breaking the looser contract.
    """

    def __init__(self, session_id: str) -> None:
        super().__init__(f"ChiefSession already exists: {session_id}")
        self.session_id = session_id


@runtime_checkable
class ChiefSessionStore(Protocol):
    """Storage protocol for ChiefSession rows.

    Async-native. The SQLite-backed implementation (Z4-S10 #1381) will
    use the bridge's existing async sqlite3 wrapper and serialise via
    the shared ``memory.db``; this in-memory impl uses a single
    ``asyncio.Lock`` to keep semantics identical so tests written against
    the protocol port to the real impl unchanged.
    """

    async def create(self, session: ChiefSession) -> None:
        """Persist a new ChiefSession.

        Raises ``ChiefSessionAlreadyExistsError`` if a session with the
        same ``session_id`` already exists.
        """
        ...

    async def get(self, session_id: str) -> ChiefSession:
        """Return the ChiefSession with the given id.

        Raises ``ChiefSessionNotFoundError`` if no row with that id exists.
        """
        ...

    async def update(self, session: ChiefSession) -> None:
        """Overwrite the stored row for ``session.session_id``.

        Raises ``ChiefSessionNotFoundError`` if the row doesn't exist —
        callers are expected to ``create()`` first; ``update()`` is not
        an upsert. This separation makes "did the dispatcher forget to
        register the session?" a loud failure rather than a silent insert.
        """
        ...

    async def list_by_work_order(self, work_order_id: str) -> list[ChiefSession]:
        """Return all sessions for a given work order, ordered by ``created_at_utc``.

        The requeue path can produce multiple rows for one work order
        (one per re-warm); this lookup is how the dispatcher reconstructs
        the full lineage.
        """
        ...

    async def list_by_state(self, state: ChiefSessionState) -> list[ChiefSession]:
        """Return all sessions currently in the given state.

        Used by `/status` surfaces and the cost roll-up that reports
        per-state aggregates.
        """
        ...

    async def list_idle(self, older_than_seconds: float) -> list[ChiefSession]:
        """Return AWAITING_EVALUATION sessions idle for longer than the threshold.

        A session is "idle" when (state == AWAITING_EVALUATION) AND
        (idle_since_utc is set) AND (idle_since_utc < now - older_than_seconds).
        Used by the idle-timeout reaper (Z4-S30 #1391).
        """
        ...

    async def find_warm_session(
        self,
        department: str,
        operator: str,
        max_age_seconds: float,
    ) -> ChiefSession | None:
        """Find the most recent AWAITING_EVALUATION session within the warm window.

        zone4-warmth.C.02 (#2296). Returns the freshest
        ``AWAITING_EVALUATION`` session for ``(department, operator)``
        whose ``idle_since_utc`` is within ``max_age_seconds`` of now,
        or ``None`` if no such session exists.

        **Spec drift note:** the sprint spec referred to ``updated_at``
        as the freshness column. ``ChiefSession`` has no such field —
        the state machine sets ``idle_since_utc`` when a session enters
        ``AWAITING_EVALUATION`` (see ``ChiefSession.transition``), which
        is exactly the "moment this conversation went idle" the warm-
        window lookup wants to measure against. Filter mirrors
        ``list_idle`` but inverts the comparator (older_than_seconds vs
        max_age_seconds) so this method returns rows still INSIDE the
        window rather than outside it.

        ``operator`` is matched against ``metadata["operator"]``. The
        dispatcher reads ``metadata.operator`` off the WorkOrder when
        building this argument, falling back to the constant
        ``"default-operator"`` per the sprint spec's Option 2.
        """
        ...

    async def update_message_history(
        self, session_id: str, blob: bytes | None
    ) -> None:
        """Persist a serialized PydanticAI message_history blob to the row.

        zone4-warmth.B.02 (#2294). Writes the bytes produced by
        ``ModelMessagesTypeAdapter.dump_json(messages)`` to the
        ``message_history_blob`` column of the existing
        ``chief_sessions`` row. Idempotent — repeated calls overwrite the
        same column with the same (or updated) bytes.

        zone4-warmth.D.01 (#2299) extended the contract so ``blob=None``
        clears the column to NULL — used by the idle-timeout reaper to
        evict stale history at reap so it doesn't accumulate in SQLite.

        Not an upsert: a missing row raises ``ChiefSessionNotFoundError``.
        The caller (``WarmChief.__aexit__``) creates the row long before
        this method is reached, so a missing-row error here signals a
        lifecycle bug worth surfacing rather than silently dropping the
        blob.
        """
        ...

    async def get_message_history(self, session_id: str) -> bytes | None:
        """Return the persisted message_history_blob, or None when absent.

        zone4-warmth.C.03 (#2297). Reader counterpart to
        ``update_message_history``. Returns raw bytes — deserialization
        via ``ModelMessagesTypeAdapter.validate_json`` happens at the
        call site (``ChiefDispatcher._deserialize_history_safe``) so any
        adapter-side error is caught at the boundary that knows how to
        fall back to fresh-start, rather than the store swallowing it
        and returning misleading state.

        Returns:
            The raw blob bytes when the row exists AND a blob has been
            written via ``update_message_history``. ``None`` when the
            row exists but no blob has landed yet (the pre-B.02 column
            default), OR when the row does not exist. The reader never
            raises on missing rows — the dispatcher's reuse branch only
            calls this method AFTER ``find_warm_session`` returned a
            session, so a missing row would be a transient race the
            cold-start fallback handles cleanly.
        """
        ...


def _utc_now() -> datetime:
    """tz-aware UTC now — matches `bridge.chief_session._utc_now` so
    timestamp comparisons in `list_idle` don't trip on naive-vs-aware
    mismatches.
    """
    return datetime.now(timezone.utc)


class InMemoryChiefSessionStore:
    """Thread-safe in-memory ChiefSessionStore for tests + dev.

    Backed by a single ``dict[str, ChiefSession]`` guarded by an
    ``asyncio.Lock``. Concurrent ``update()`` calls serialise via the
    lock — this is the canonical asyncio pattern for "many tasks, one
    in-memory store, no race." The Protocol contract is async, so the
    real SQLite impl (Z4-S10) can use the same shape and add real
    isolation (begin/commit/rollback) at that layer.

    Production explicitly does NOT use this class — it's bounded by
    process memory and lacks the persistence the bridge requires across
    restarts. Z4-S10 swaps in the SQLite-backed impl.
    """

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._sessions: dict[str, ChiefSession] = {}
        # zone4-warmth.B.02 (#2294) — out-of-band blob storage so the
        # ``message_history_blob`` column can round-trip without
        # extending the ``ChiefSession`` dataclass (which intentionally
        # carries lifecycle metadata only). Keyed by ``session_id``;
        # entries land only when ``update_message_history`` is called
        # and remain until the session is removed from the dict.
        self._message_history_blobs: dict[str, bytes] = {}

    async def create(self, session: ChiefSession) -> None:
        async with self._lock:
            if session.session_id in self._sessions:
                raise ChiefSessionAlreadyExistsError(session.session_id)
            self._sessions[session.session_id] = session

    async def get(self, session_id: str) -> ChiefSession:
        async with self._lock:
            try:
                return self._sessions[session_id]
            except KeyError:
                raise ChiefSessionNotFoundError(session_id) from None

    async def update(self, session: ChiefSession) -> None:
        async with self._lock:
            if session.session_id not in self._sessions:
                raise ChiefSessionNotFoundError(session.session_id)
            self._sessions[session.session_id] = session

    async def list_by_work_order(self, work_order_id: str) -> list[ChiefSession]:
        async with self._lock:
            matches = [
                s for s in self._sessions.values()
                if s.work_order_id == work_order_id
            ]
        # Sort outside the lock — pure CPU work, no need to hold the lock
        return sorted(matches, key=lambda s: s.created_at_utc)

    async def list_by_state(self, state: ChiefSessionState) -> list[ChiefSession]:
        async with self._lock:
            return [s for s in self._sessions.values() if s.state == state]

    async def list_idle(self, older_than_seconds: float) -> list[ChiefSession]:
        cutoff = _utc_now() - timedelta(seconds=older_than_seconds)
        async with self._lock:
            return [
                s for s in self._sessions.values()
                if s.state == ChiefSessionState.AWAITING_EVALUATION
                and s.idle_since_utc is not None
                and s.idle_since_utc < cutoff
            ]

    async def find_warm_session(
        self,
        department: str,
        operator: str,
        max_age_seconds: float,
    ) -> ChiefSession | None:
        """Return the freshest in-window AWAITING_EVALUATION session for (dept, operator).

        zone4-warmth.C.02 (#2296). Mirrors ``list_idle`` (state +
        idle_since_utc filter) but inverts the comparator so callers
        receive rows whose ``idle_since_utc`` is INSIDE the window. When
        multiple matches exist we return the one with the most recent
        ``idle_since_utc`` (newest first) — that's the most likely
        continuation of the active conversation.
        """
        cutoff = _utc_now() - timedelta(seconds=max_age_seconds)
        async with self._lock:
            candidates = [
                s for s in self._sessions.values()
                if s.state == ChiefSessionState.AWAITING_EVALUATION
                and s.department == department
                and s.metadata.get("operator") == operator
                and s.idle_since_utc is not None
                and s.idle_since_utc >= cutoff
            ]
        if not candidates:
            return None
        # idle_since_utc is guaranteed non-None by the filter above.
        return max(candidates, key=lambda s: s.idle_since_utc)

    async def update_message_history(
        self, session_id: str, blob: bytes | None
    ) -> None:
        """Persist a serialized PydanticAI message_history blob.

        zone4-warmth.B.02 (#2294). Stores ``blob`` in the out-of-band
        ``_message_history_blobs`` dict so the SQLite impl's column
        layout doesn't need to be mirrored in the ``ChiefSession``
        dataclass. Raises ``ChiefSessionNotFoundError`` when the
        session row doesn't exist — matches the SQLite contract.

        zone4-warmth.D.01 (#2299): ``blob=None`` clears the entry,
        mirroring SQLite's NULL semantics so the idle-timeout reaper
        can evict stale history at reap.
        """
        async with self._lock:
            if session_id not in self._sessions:
                raise ChiefSessionNotFoundError(session_id)
            if blob is None:
                # Mirror SQLite's NULL: remove the dict entry so
                # ``get_message_history_blob`` returns None.
                self._message_history_blobs.pop(session_id, None)
            else:
                self._message_history_blobs[session_id] = blob

    async def get_message_history(self, session_id: str) -> bytes | None:
        """Return the persisted message_history_blob, or None when absent.

        zone4-warmth.C.03 (#2297). Reader for the warm-reuse path.
        Returns the bytes previously written via
        ``update_message_history`` keyed by ``session_id``. Returns
        ``None`` both when the row exists but no blob has been written
        AND when the row does not exist — the dispatcher's reuse branch
        only calls this method after ``find_warm_session`` returned a
        match, so the missing-row case is a benign race the cold-start
        fallback handles cleanly.
        """
        async with self._lock:
            return self._message_history_blobs.get(session_id)

    # Test/diagnostic helpers — not part of the protocol; not for
    # production use beyond test fixtures.

    async def get_message_history_blob(
        self, session_id: str
    ) -> bytes | None:
        """Return the persisted message_history blob for ``session_id``.

        zone4-warmth.B.02 (#2294) test helper retained for back-compat
        with the B.02 test suite. Production reads should go through
        the Protocol-level ``get_message_history`` (C.03 #2297), which
        this method aliases.
        """
        return await self.get_message_history(session_id)

    async def _all(self) -> list[ChiefSession]:
        """Return every session. Test-only helper."""
        async with self._lock:
            return list(self._sessions.values())

    async def _count(self) -> int:
        """Return the total session count. Test-only helper."""
        async with self._lock:
            return len(self._sessions)


# ---------------------------------------------------------------------------
# SQLite-backed implementation — Z4-S10 (#1381)
# ---------------------------------------------------------------------------


def _dt_to_iso(value: datetime | None) -> str | None:
    """Serialise a tz-aware UTC datetime to ISO-8601 for SQLite TEXT storage.

    Returns ``None`` for ``None`` inputs. The ChiefSession contract guarantees
    tz-aware UTC datetimes (`bridge.chief_session._utc_now`); naive datetimes
    would be a programmer error and are passed through unchanged so the bug
    surfaces on read rather than being silently coerced.
    """
    if value is None:
        return None
    return value.isoformat()


def _iso_to_dt(value: str | None) -> datetime | None:
    """Hydrate an ISO-8601 string back to a tz-aware UTC datetime.

    SQLite returns ``None`` for nullable columns; we propagate that. Strings
    written by ``_dt_to_iso`` always include the offset (``+00:00``) so
    ``fromisoformat`` returns a tz-aware value without further coercion.
    """
    if value is None:
        return None
    return datetime.fromisoformat(value)


def _row_to_session(row: Any) -> ChiefSession:
    """Hydrate a SQLite row from ``chief_sessions`` into a ChiefSession.

    Accepts an ``aiosqlite.Row`` (mapping access by column name) — the
    Database wrapper sets ``row_factory = aiosqlite.Row`` in ``connect()``,
    so every read goes through this code path.

    The ``metadata_json`` column is JSON-encoded text; bad JSON is treated
    as empty rather than raised, keeping `get()` resilient against legacy
    rows. A real corruption surface would log + alert at the call site,
    but the store should not panic at the read boundary.
    """
    try:
        metadata = json.loads(row["metadata_json"]) if row["metadata_json"] else {}
    except (json.JSONDecodeError, TypeError):
        metadata = {}

    return ChiefSession(
        session_id=row["session_id"],
        work_order_id=row["work_order_id"],
        department=row["department"],
        chief_name=row["chief_name"],
        state=ChiefSessionState(row["state"]),
        created_at_utc=_iso_to_dt(row["created_at_utc"]),
        warmed_at_utc=_iso_to_dt(row["warmed_at_utc"]),
        execution_started_at_utc=_iso_to_dt(row["execution_started_at_utc"]),
        completed_at_utc=_iso_to_dt(row["completed_at_utc"]),
        idle_since_utc=_iso_to_dt(row["idle_since_utc"]),
        run_count=row["run_count"],
        cost_usd=row["cost_usd"],
        error=row["error"],
        metadata=metadata,
    )


class SQLiteChiefSessionStore:
    """SQLite-backed ChiefSessionStore — production persistence for Z4 chief sessions.

    Satisfies the ``ChiefSessionStore`` Protocol (structural conformance,
    no inheritance) so callers written against the in-memory impl port
    unchanged. All writes flow through the shared ``Database`` wrapper
    from ``bridge.database`` — that wrapper holds a single ``aiosqlite``
    connection in WAL mode with a 5-second busy timeout, so concurrent
    callers serialise through the connection's own GIL-bound queue rather
    than this class's own lock. No additional asyncio.Lock is added here:
    layering one over aiosqlite would only block tasks that already could
    not be racing.

    Tables (created by migration #13 in ``bridge.database``):
      - ``chief_sessions`` — one row per ChiefSession envelope
      - ``chief_session_history`` — append-only state-transition log
        (reserved for Z4-S30 #1391; not written by this store yet)

    All timestamps round-trip as ISO-8601 strings with the ``+00:00`` offset
    so a ``datetime.fromisoformat`` on read returns a tz-aware value.
    """

    def __init__(self, db: "Database") -> None:
        self._db = db

    async def create(self, session: ChiefSession) -> None:
        """Insert a new session row.

        Raises ``ChiefSessionAlreadyExistsError`` on primary-key collision.
        We check first rather than rely on ``IntegrityError`` so the error
        type matches the Protocol contract used by the in-memory impl
        (callers catching the named error continue to work).
        """
        existing = await self._db.fetchone(
            "SELECT session_id FROM chief_sessions WHERE session_id = ?",
            (session.session_id,),
        )
        if existing is not None:
            raise ChiefSessionAlreadyExistsError(session.session_id)

        await self._db.execute(
            """INSERT INTO chief_sessions (
                session_id, work_order_id, department, chief_name, state,
                created_at_utc, warmed_at_utc, execution_started_at_utc,
                completed_at_utc, idle_since_utc, run_count, cost_usd,
                error, metadata_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                session.session_id,
                session.work_order_id,
                session.department,
                session.chief_name,
                session.state.value,
                _dt_to_iso(session.created_at_utc),
                _dt_to_iso(session.warmed_at_utc),
                _dt_to_iso(session.execution_started_at_utc),
                _dt_to_iso(session.completed_at_utc),
                _dt_to_iso(session.idle_since_utc),
                session.run_count,
                session.cost_usd,
                session.error,
                json.dumps(session.metadata),
            ),
        )
        await self._db.commit()

    async def get(self, session_id: str) -> ChiefSession:
        row = await self._db.fetchone(
            """SELECT session_id, work_order_id, department, chief_name, state,
                      created_at_utc, warmed_at_utc, execution_started_at_utc,
                      completed_at_utc, idle_since_utc, run_count, cost_usd,
                      error, metadata_json
               FROM chief_sessions WHERE session_id = ?""",
            (session_id,),
        )
        if row is None:
            raise ChiefSessionNotFoundError(session_id)
        return _row_to_session(row)

    async def update(self, session: ChiefSession) -> None:
        """Overwrite the stored row for ``session.session_id``.

        Raises ``ChiefSessionNotFoundError`` if the row doesn't exist —
        the Protocol contract is "not an upsert", and we honour that here
        by checking first. SQLite's ``UPDATE`` would silently no-op on a
        missing row, which is exactly the kind of "did the dispatcher
        forget to register the session?" silent failure the protocol is
        trying to make loud.
        """
        existing = await self._db.fetchone(
            "SELECT session_id FROM chief_sessions WHERE session_id = ?",
            (session.session_id,),
        )
        if existing is None:
            raise ChiefSessionNotFoundError(session.session_id)

        await self._db.execute(
            """UPDATE chief_sessions SET
                work_order_id = ?,
                department = ?,
                chief_name = ?,
                state = ?,
                created_at_utc = ?,
                warmed_at_utc = ?,
                execution_started_at_utc = ?,
                completed_at_utc = ?,
                idle_since_utc = ?,
                run_count = ?,
                cost_usd = ?,
                error = ?,
                metadata_json = ?
               WHERE session_id = ?""",
            (
                session.work_order_id,
                session.department,
                session.chief_name,
                session.state.value,
                _dt_to_iso(session.created_at_utc),
                _dt_to_iso(session.warmed_at_utc),
                _dt_to_iso(session.execution_started_at_utc),
                _dt_to_iso(session.completed_at_utc),
                _dt_to_iso(session.idle_since_utc),
                session.run_count,
                session.cost_usd,
                session.error,
                json.dumps(session.metadata),
                session.session_id,
            ),
        )
        await self._db.commit()

    async def list_by_work_order(self, work_order_id: str) -> list[ChiefSession]:
        rows = await self._db.fetchall(
            """SELECT session_id, work_order_id, department, chief_name, state,
                      created_at_utc, warmed_at_utc, execution_started_at_utc,
                      completed_at_utc, idle_since_utc, run_count, cost_usd,
                      error, metadata_json
               FROM chief_sessions
               WHERE work_order_id = ?
               ORDER BY created_at_utc ASC""",
            (work_order_id,),
        )
        return [_row_to_session(r) for r in rows]

    async def list_by_state(self, state: ChiefSessionState) -> list[ChiefSession]:
        rows = await self._db.fetchall(
            """SELECT session_id, work_order_id, department, chief_name, state,
                      created_at_utc, warmed_at_utc, execution_started_at_utc,
                      completed_at_utc, idle_since_utc, run_count, cost_usd,
                      error, metadata_json
               FROM chief_sessions
               WHERE state = ?""",
            (state.value,),
        )
        return [_row_to_session(r) for r in rows]

    async def list_idle(self, older_than_seconds: float) -> list[ChiefSession]:
        """Return AWAITING_EVALUATION sessions whose idle interval exceeds the threshold.

        Filtering happens in SQL (against the cutoff timestamp) rather than
        in Python so the partial index ``idx_chief_sessions_idle`` from
        migration #13 actually gets used. The index covers state +
        idle_since_utc ordered, which is the exact shape of this query.
        """
        cutoff_iso = _dt_to_iso(_utc_now() - timedelta(seconds=older_than_seconds))
        rows = await self._db.fetchall(
            """SELECT session_id, work_order_id, department, chief_name, state,
                      created_at_utc, warmed_at_utc, execution_started_at_utc,
                      completed_at_utc, idle_since_utc, run_count, cost_usd,
                      error, metadata_json
               FROM chief_sessions
               WHERE state = ?
                 AND idle_since_utc IS NOT NULL
                 AND idle_since_utc < ?""",
            (ChiefSessionState.AWAITING_EVALUATION.value, cutoff_iso),
        )
        return [_row_to_session(r) for r in rows]

    async def find_warm_session(
        self,
        department: str,
        operator: str,
        max_age_seconds: float,
    ) -> ChiefSession | None:
        """Return the freshest in-window AWAITING_EVALUATION session for (dept, operator).

        zone4-warmth.C.02 (#2296). Mirrors ``list_idle``'s SQL shape but
        inverts the cutoff comparator so we receive sessions still INSIDE
        the warm window (``idle_since_utc >= cutoff``). Adds a department
        equality filter and a ``json_extract`` lookup against
        ``metadata_json -> '$.operator'`` so the warm pool is scoped per
        conversation, not per box.

        Ordering: ``idle_since_utc DESC LIMIT 1`` — the most-recently-idle
        match is the most likely continuation of the active conversation.

        Returns ``None`` when no match exists. Operator equality is exact
        string match; ``operator='default-operator'`` is the back-compat
        value the dispatcher supplies when a WorkOrder has no
        ``metadata.operator`` field.
        """
        cutoff_iso = _dt_to_iso(_utc_now() - timedelta(seconds=max_age_seconds))
        row = await self._db.fetchone(
            """SELECT session_id, work_order_id, department, chief_name, state,
                      created_at_utc, warmed_at_utc, execution_started_at_utc,
                      completed_at_utc, idle_since_utc, run_count, cost_usd,
                      error, metadata_json
               FROM chief_sessions
               WHERE state = ?
                 AND department = ?
                 AND idle_since_utc IS NOT NULL
                 AND idle_since_utc >= ?
                 AND json_extract(metadata_json, '$.operator') = ?
               ORDER BY idle_since_utc DESC
               LIMIT 1""",
            (
                ChiefSessionState.AWAITING_EVALUATION.value,
                department,
                cutoff_iso,
                operator,
            ),
        )
        if row is None:
            return None
        return _row_to_session(row)

    async def update_message_history(
        self, session_id: str, blob: bytes | None
    ) -> None:
        """Persist a serialized PydanticAI message_history blob to SQLite.

        zone4-warmth.B.02 (#2294). Writes ``blob`` to the
        ``message_history_blob`` BLOB column on the existing
        ``chief_sessions`` row. Raises ``ChiefSessionNotFoundError``
        when the row doesn't exist — explicit check rather than relying
        on UPDATE's silent no-op, matching the Protocol contract for
        ``update()``.

        zone4-warmth.D.01 (#2299): ``blob=None`` writes a SQL NULL —
        used by the idle-timeout reaper to evict stale message_history
        at reap so the column doesn't accumulate dead bytes.

        Migration #16 (B.01) added the column nullable, so callers that
        never reach this method (failure paths, pre-Phase-3 sessions)
        leave it NULL. Idempotent at the row level: repeated calls
        overwrite the column with the new bytes.
        """
        existing = await self._db.fetchone(
            "SELECT session_id FROM chief_sessions WHERE session_id = ?",
            (session_id,),
        )
        if existing is None:
            raise ChiefSessionNotFoundError(session_id)

        await self._db.execute(
            "UPDATE chief_sessions SET message_history_blob = ? "
            "WHERE session_id = ?",
            (blob, session_id),
        )
        await self._db.commit()

    async def get_message_history(self, session_id: str) -> bytes | None:
        """Return the raw message_history_blob bytes for ``session_id``.

        zone4-warmth.C.03 (#2297). Reader for the warm-reuse path.
        Reads directly from the BLOB column without joining or hydrating
        — deserialization via ``ModelMessagesTypeAdapter.validate_json``
        happens at the call site (``ChiefDispatcher._deserialize_history_safe``)
        so any adapter-side error is caught at the boundary that knows
        how to fall back to fresh-start.

        Returns ``None`` both when the row does not exist AND when the
        ``message_history_blob`` column is NULL. The dispatcher's reuse
        branch handles both as "no prior history" by treating the
        message_history as None on the chief run.
        """
        row = await self._db.fetchone(
            "SELECT message_history_blob FROM chief_sessions "
            "WHERE session_id = ?",
            (session_id,),
        )
        if row is None:
            return None
        return row["message_history_blob"]
