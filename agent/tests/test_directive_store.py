"""Unit tests for the Sprint 20 (Phase 5B) directive_store module.

Covers:
- ``new_directive_id()`` shape and uniqueness
- ``insert_directive()`` round-trips to ``get_directive()`` faithfully
- ``insert_directive()`` rejects invalid priority with ValueError before SQL
- Status transitions write ``directive_history`` rows in order
- ``update_status()`` raises ValueError on unknown directive_id
- ``list_active()`` filters terminal statuses
- ``list_by_chief()`` filters and respects ``include_terminal``
- ``list_all()`` honours ``limit``
- ``get_history()`` returns rows in transition order
- Parameterised queries resist SQL-injection-shaped inputs

All tests use a temp-file SQLite database via the real ``Database`` wrapper
so we exercise the migration #10 schema (CHECK constraints, indexes, FK).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import pytest_asyncio

from bridge.database import Database
from bridge.directive_store import (
    get_directive,
    get_history,
    get_status,
    insert_directive,
    list_active,
    list_all,
    list_by_chief,
    mark_accepted,
    mark_blocked,
    mark_cancelled,
    mark_done,
    mark_in_progress,
    new_directive_id,
    update_status,
)
from teams._types import (
    DIRECTIVE_PRIORITIES,
    Directive,
    DirectiveStatus,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def db(tmp_path: Path) -> Database:
    """A fresh, migrated Database backed by a temp-file SQLite.

    aiosqlite + ':memory:' has connection-isolation quirks for multi-call
    tests; using a tmp_path file dodges that without slowing the suite.
    """
    db_path = tmp_path / "test-directives.db"
    database = Database(db_path)
    await database.connect()
    await database.migrate()
    yield database
    await database.close()


def _make_directive(
    *,
    directive_id: str | None = None,
    to_chief: str = "strategy-product-chief",
    intent: str = "size the audio AI market",
    priority: str = "p1",
    constraints: tuple[str, ...] = (),
    deadline_offset_hours: int | None = None,
    context: dict | None = None,
    operator_id: str = "op-test",
    from_agent: str = "main",
) -> Directive:
    issued = datetime.now(timezone.utc)
    deadline = (
        issued + timedelta(hours=deadline_offset_hours)
        if deadline_offset_hours is not None
        else None
    )
    return Directive(
        directive_id=directive_id or new_directive_id(),
        from_agent=from_agent,
        to_chief=to_chief,
        intent=intent,
        constraints=constraints,
        deadline_utc=deadline,
        priority=priority,
        issued_at_utc=issued,
        context=context or {},
        operator_id=operator_id,
    )


# ---------------------------------------------------------------------------
# new_directive_id
# ---------------------------------------------------------------------------


class TestNewDirectiveId:
    def test_format(self) -> None:
        did = new_directive_id()
        assert did.startswith("dir-")
        assert len(did) == 4 + 12  # "dir-" + 12 hex
        # Body must be valid hex
        int(did[4:], 16)

    def test_uniqueness(self) -> None:
        ids = {new_directive_id() for _ in range(1000)}
        assert len(ids) == 1000


# ---------------------------------------------------------------------------
# insert_directive + get_directive
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestInsertAndGet:
    async def test_round_trip_minimal(self, db: Database) -> None:
        d = _make_directive(intent="round-trip me", priority="p2")
        await insert_directive(db, d)
        fetched = await get_directive(db, d.directive_id)
        assert fetched is not None
        assert fetched.directive_id == d.directive_id
        assert fetched.to_chief == d.to_chief
        assert fetched.intent == "round-trip me"
        assert fetched.priority == "p2"
        assert fetched.constraints == ()
        assert fetched.deadline_utc is None
        assert dict(fetched.context) == {}
        assert fetched.operator_id == "op-test"

    async def test_round_trip_full(self, db: Database) -> None:
        d = _make_directive(
            intent="full payload",
            priority="p0",
            constraints=("budget=$2", "deadline=24h"),
            deadline_offset_hours=24,
            context={"corr_id": "abc-123", "discord_msg": "msg-9"},
            operator_id="discord-12345",
            from_agent="main",
        )
        await insert_directive(db, d)
        fetched = await get_directive(db, d.directive_id)
        assert fetched is not None
        assert fetched.constraints == ("budget=$2", "deadline=24h")
        assert fetched.deadline_utc is not None
        # Round-trip the deadline through ISO string preserves the instant
        assert abs(
            (fetched.deadline_utc - d.deadline_utc).total_seconds()  # type: ignore[operator]
        ) < 1.0
        assert dict(fetched.context) == {"corr_id": "abc-123", "discord_msg": "msg-9"}

    async def test_initial_status_is_issued(self, db: Database) -> None:
        d = _make_directive()
        await insert_directive(db, d)
        status = await get_status(db, d.directive_id)
        assert status == DirectiveStatus.ISSUED

    async def test_initial_history_row_recorded(self, db: Database) -> None:
        d = _make_directive()
        await insert_directive(db, d)
        history = await get_history(db, d.directive_id)
        assert len(history) == 1
        assert history[0]["from_status"] is None
        assert history[0]["to_status"] == "issued"

    async def test_get_unknown_returns_none(self, db: Database) -> None:
        assert await get_directive(db, "dir-doesnotexist") is None
        assert await get_status(db, "dir-doesnotexist") is None


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestPriorityValidation:
    async def test_rejects_invalid_priority_before_sql(self, db: Database) -> None:
        d = _make_directive(priority="p9")
        with pytest.raises(ValueError) as excinfo:
            await insert_directive(db, d)
        assert "p9" in str(excinfo.value)
        # Confirm nothing was written (defence-in-depth: the CHECK would have
        # caught it too, but we want clean Python-side validation)
        assert await get_directive(db, d.directive_id) is None

    @pytest.mark.parametrize("p", DIRECTIVE_PRIORITIES)
    async def test_accepts_every_canonical_priority(self, db: Database, p: str) -> None:
        d = _make_directive(priority=p)
        await insert_directive(db, d)
        fetched = await get_directive(db, d.directive_id)
        assert fetched is not None
        assert fetched.priority == p


# ---------------------------------------------------------------------------
# Status transitions + history
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestStatusTransitions:
    async def test_full_lifecycle_writes_history_in_order(self, db: Database) -> None:
        d = _make_directive()
        await insert_directive(db, d)
        await mark_accepted(db, d.directive_id, note="chief acked")
        await mark_in_progress(db, d.directive_id)
        await mark_done(db, d.directive_id, note="synthesis complete")

        status = await get_status(db, d.directive_id)
        assert status == DirectiveStatus.DONE

        history = await get_history(db, d.directive_id)
        # 1 issue + 3 transitions
        assert [h["to_status"] for h in history] == [
            "issued", "accepted", "in_progress", "done",
        ]
        assert [h["from_status"] for h in history] == [
            None, "issued", "accepted", "in_progress",
        ]
        assert history[1]["note"] == "chief acked"
        assert history[3]["note"] == "synthesis complete"

    async def test_blocked_then_accepted_is_recoverable(self, db: Database) -> None:
        """A chief can BLOCK then re-ACCEPT — the audit must show the loop."""
        d = _make_directive()
        await insert_directive(db, d)
        await mark_accepted(db, d.directive_id)
        await mark_in_progress(db, d.directive_id)
        await mark_blocked(db, d.directive_id, note="needs operator input")
        await mark_accepted(db, d.directive_id, note="operator unblocked")
        await mark_done(db, d.directive_id)

        history = await get_history(db, d.directive_id)
        assert [h["to_status"] for h in history] == [
            "issued", "accepted", "in_progress", "blocked", "accepted", "done",
        ]

    async def test_cancel_terminates(self, db: Database) -> None:
        d = _make_directive()
        await insert_directive(db, d)
        await mark_cancelled(db, d.directive_id, note="operator cancelled")
        assert await get_status(db, d.directive_id) == DirectiveStatus.CANCELLED

    async def test_update_status_unknown_id_raises(self, db: Database) -> None:
        with pytest.raises(ValueError) as excinfo:
            await update_status(db, "dir-nope", DirectiveStatus.DONE)
        assert "dir-nope" in str(excinfo.value)

    async def test_noop_transition_still_appends_history_row(self, db: Database) -> None:
        """Re-accepting an already-accepted directive must record the retry.

        This is intentional — chiefs may emit acknowledge_directive() twice
        on retry; the audit log should make that visible rather than hide it.
        """
        d = _make_directive()
        await insert_directive(db, d)
        await mark_accepted(db, d.directive_id)
        await mark_accepted(db, d.directive_id, note="retry")
        history = await get_history(db, d.directive_id)
        assert len(history) == 3  # issue + 2 accepted rows
        assert history[2]["note"] == "retry"


# ---------------------------------------------------------------------------
# Listing
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestListing:
    async def test_list_active_filters_terminal(self, db: Database) -> None:
        a = _make_directive(intent="active-1")
        b = _make_directive(intent="active-2")
        c = _make_directive(intent="done-1")
        d = _make_directive(intent="cancelled-1")
        for x in (a, b, c, d):
            await insert_directive(db, x)
        await mark_done(db, c.directive_id)
        await mark_cancelled(db, d.directive_id)

        active = await list_active(db)
        ids = {x.directive_id for x in active}
        assert a.directive_id in ids
        assert b.directive_id in ids
        assert c.directive_id not in ids
        assert d.directive_id not in ids

    async def test_list_active_orders_by_issued_at_desc(self, db: Database) -> None:
        # Build two directives with issued_at_utc explicitly ordered
        now = datetime.now(timezone.utc)
        older = Directive(
            directive_id=new_directive_id(),
            from_agent="main", to_chief="strategy-product-chief", intent="older",
            constraints=(), deadline_utc=None, priority="p1",
            issued_at_utc=now - timedelta(hours=1),
            context={}, operator_id="op",
        )
        newer = Directive(
            directive_id=new_directive_id(),
            from_agent="main", to_chief="strategy-product-chief", intent="newer",
            constraints=(), deadline_utc=None, priority="p1",
            issued_at_utc=now,
            context={}, operator_id="op",
        )
        await insert_directive(db, older)
        await insert_directive(db, newer)
        active = await list_active(db)
        assert active[0].directive_id == newer.directive_id
        assert active[1].directive_id == older.directive_id

    async def test_list_by_chief_filters(self, db: Database) -> None:
        a = _make_directive(to_chief="strategy-product-chief", intent="s1")
        b = _make_directive(to_chief="qa-chief", intent="q1")
        c = _make_directive(to_chief="strategy-product-chief", intent="s2")
        for x in (a, b, c):
            await insert_directive(db, x)
        result = await list_by_chief(db, "strategy-product-chief")
        intents = {x.intent for x in result}
        assert intents == {"s1", "s2"}

    async def test_list_by_chief_excludes_terminal_by_default(
        self, db: Database
    ) -> None:
        a = _make_directive(to_chief="qa-chief", intent="active")
        b = _make_directive(to_chief="qa-chief", intent="done")
        await insert_directive(db, a)
        await insert_directive(db, b)
        await mark_done(db, b.directive_id)

        active_only = await list_by_chief(db, "qa-chief")
        assert {x.intent for x in active_only} == {"active"}

        all_of_them = await list_by_chief(db, "qa-chief", include_terminal=True)
        assert {x.intent for x in all_of_them} == {"active", "done"}

    async def test_list_all_respects_limit(self, db: Database) -> None:
        for i in range(5):
            await insert_directive(db, _make_directive(intent=f"intent-{i}"))
        result = await list_all(db, limit=3)
        assert len(result) == 3


# ---------------------------------------------------------------------------
# Security: parameterised queries resist SQL-injection-shaped input
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestSqlInjectionResistance:
    async def test_chief_name_with_sql_payload_is_stored_verbatim(
        self, db: Database
    ) -> None:
        """A chief name like ``'; DROP TABLE directives; --`` must round-trip
        as a literal string and must NOT execute."""
        evil_chief = "qa-chief'; DROP TABLE directives; --"
        d = _make_directive(to_chief=evil_chief, intent="probe")
        await insert_directive(db, d)
        # Table must still exist
        fetched = await get_directive(db, d.directive_id)
        assert fetched is not None
        assert fetched.to_chief == evil_chief

    async def test_intent_with_sql_payload_is_stored_verbatim(
        self, db: Database
    ) -> None:
        evil_intent = "do something'; UPDATE directives SET status='done'; --"
        d = _make_directive(intent=evil_intent)
        await insert_directive(db, d)
        fetched = await get_directive(db, d.directive_id)
        assert fetched is not None
        assert fetched.intent == evil_intent
        # Status MUST still be issued — the injection didn't run
        assert await get_status(db, d.directive_id) == DirectiveStatus.ISSUED

    async def test_directive_id_with_sql_payload_returns_none(
        self, db: Database
    ) -> None:
        """A nonsense directive_id including a SQL payload must just miss."""
        result = await get_directive(db, "dir-foo' OR '1'='1")
        assert result is None
        result = await get_status(db, "dir-foo' OR '1'='1")
        assert result is None
