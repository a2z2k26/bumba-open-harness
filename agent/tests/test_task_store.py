"""Unit tests for the Sprint 21 (Phase 5B) task_store module.

Mirrors test_directive_store.py — same shape (CRUD round-trip, lifecycle
transitions, listing filters, SQL-injection resistance) against a
fresh-migrated SQLite database via the real Database wrapper, so we
exercise migration #11's schema (CHECK constraint, indexes, FK to
directives).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import pytest_asyncio

from bridge.database import Database
from bridge.directive_store import (
    insert_directive as insert_directive_record,
    new_directive_id,
)
from bridge.task_store import (
    get_history,
    get_status,
    get_task,
    insert_task,
    list_active,
    list_all,
    list_by_chief,
    list_by_directive,
    mark_blocked,
    mark_cancelled,
    mark_done,
    mark_in_progress,
    new_task_id,
    update_status,
)
from teams._types import Directive, Task, TaskStatus


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def db(tmp_path: Path) -> Database:
    db_path = tmp_path / "test-tasks.db"
    database = Database(db_path)
    await database.connect()
    await database.migrate()
    yield database
    await database.close()


def _make_task(
    *,
    task_id: str | None = None,
    directive_id: str | None = None,
    from_chief: str = "strategy-product-chief",
    to_specialist: str = "strategy-market-researcher",
    description: str = "research the audio AI market",
    constraints: tuple[str, ...] = (),
    deadline_offset_seconds: int | None = None,
) -> Task:
    issued = datetime.now(timezone.utc)
    deadline = (
        issued + timedelta(seconds=deadline_offset_seconds)
        if deadline_offset_seconds is not None
        else None
    )
    return Task(
        task_id=task_id or new_task_id(),
        directive_id=directive_id,
        from_chief=from_chief,
        to_specialist=to_specialist,
        description=description,
        constraints=constraints,
        deadline_utc=deadline,
        issued_at_utc=issued,
    )


async def _seed_directive(db: Database) -> str:
    """Create a real directive row so FK references work."""
    d = Directive(
        directive_id=new_directive_id(),
        from_agent="main",
        to_chief="strategy-product-chief",
        intent="parent directive",
        constraints=(),
        deadline_utc=None,
        priority="p1",
        issued_at_utc=datetime.now(timezone.utc),
        context={},
        operator_id="op",
    )
    await insert_directive_record(db, d)
    return d.directive_id


# ---------------------------------------------------------------------------
# new_task_id
# ---------------------------------------------------------------------------


class TestNewTaskId:
    def test_format(self) -> None:
        tid = new_task_id()
        assert tid.startswith("task-")
        assert len(tid) == 5 + 12  # "task-" + 12 hex
        int(tid[5:], 16)

    def test_uniqueness(self) -> None:
        ids = {new_task_id() for _ in range(1000)}
        assert len(ids) == 1000


# ---------------------------------------------------------------------------
# insert + get
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestInsertAndGet:
    async def test_round_trip_minimal(self, db: Database) -> None:
        t = _make_task(description="probe me")
        await insert_task(db, t)
        fetched = await get_task(db, t.task_id)
        assert fetched is not None
        assert fetched.task_id == t.task_id
        assert fetched.description == "probe me"
        assert fetched.directive_id is None  # FK can be NULL
        assert fetched.constraints == ()
        assert fetched.deadline_utc is None

    async def test_round_trip_full(self, db: Database) -> None:
        directive_id = await _seed_directive(db)
        t = _make_task(
            directive_id=directive_id,
            constraints=("budget=$1", "timebox=10m"),
            deadline_offset_seconds=600,
        )
        await insert_task(db, t)
        fetched = await get_task(db, t.task_id)
        assert fetched is not None
        assert fetched.directive_id == directive_id
        assert fetched.constraints == ("budget=$1", "timebox=10m")
        assert fetched.deadline_utc is not None

    async def test_initial_status_assigned(self, db: Database) -> None:
        t = _make_task()
        await insert_task(db, t)
        assert await get_status(db, t.task_id) == TaskStatus.ASSIGNED

    async def test_initial_history_row_recorded(self, db: Database) -> None:
        t = _make_task()
        await insert_task(db, t)
        history = await get_history(db, t.task_id)
        assert len(history) == 1
        assert history[0]["from_status"] is None
        assert history[0]["to_status"] == "assigned"

    async def test_get_unknown_returns_none(self, db: Database) -> None:
        assert await get_task(db, "task-doesnotexist") is None
        assert await get_status(db, "task-doesnotexist") is None


# ---------------------------------------------------------------------------
# Status transitions
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestStatusTransitions:
    async def test_full_lifecycle(self, db: Database) -> None:
        t = _make_task()
        await insert_task(db, t)
        await mark_in_progress(db, t.task_id, note="invoke begun")
        await mark_done(db, t.task_id, note="returned")

        assert await get_status(db, t.task_id) == TaskStatus.DONE
        history = await get_history(db, t.task_id)
        assert [h["to_status"] for h in history] == [
            "assigned", "in_progress", "done",
        ]

    async def test_blocked_path(self, db: Database) -> None:
        t = _make_task()
        await insert_task(db, t)
        await mark_in_progress(db, t.task_id)
        await mark_blocked(db, t.task_id, note="specialist exception")

        assert await get_status(db, t.task_id) == TaskStatus.BLOCKED

    async def test_cancel_path(self, db: Database) -> None:
        t = _make_task()
        await insert_task(db, t)
        await mark_cancelled(db, t.task_id)
        assert await get_status(db, t.task_id) == TaskStatus.CANCELLED

    async def test_unknown_id_raises(self, db: Database) -> None:
        with pytest.raises(ValueError) as excinfo:
            await update_status(db, "task-nope", TaskStatus.DONE)
        assert "task-nope" in str(excinfo.value)

    async def test_noop_transition_records_history_row(
        self, db: Database
    ) -> None:
        t = _make_task()
        await insert_task(db, t)
        await mark_in_progress(db, t.task_id)
        await mark_in_progress(db, t.task_id, note="retry")
        history = await get_history(db, t.task_id)
        assert len(history) == 3  # assign + 2 in_progress
        assert history[2]["note"] == "retry"


# ---------------------------------------------------------------------------
# Listing
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestListing:
    async def test_list_active_filters_terminal(self, db: Database) -> None:
        a = _make_task(description="active")
        b = _make_task(description="done")
        c = _make_task(description="cancelled")
        for x in (a, b, c):
            await insert_task(db, x)
        await mark_done(db, b.task_id)
        await mark_cancelled(db, c.task_id)

        active = await list_active(db)
        ids = {x.task_id for x in active}
        assert a.task_id in ids
        assert b.task_id not in ids
        assert c.task_id not in ids

    async def test_list_by_directive_chronological(self, db: Database) -> None:
        directive_id = await _seed_directive(db)
        # Build two tasks under the same directive with explicit ordering
        now = datetime.now(timezone.utc)
        first = Task(
            task_id=new_task_id(),
            directive_id=directive_id,
            from_chief="strategy-product-chief",
            to_specialist="strategy-market-researcher",
            description="first",
            constraints=(),
            deadline_utc=None,
            issued_at_utc=now - timedelta(seconds=5),
        )
        second = Task(
            task_id=new_task_id(),
            directive_id=directive_id,
            from_chief="strategy-product-chief",
            to_specialist="strategy-competitive-intelligence-analyst",
            description="second",
            constraints=(),
            deadline_utc=None,
            issued_at_utc=now,
        )
        await insert_task(db, first)
        await insert_task(db, second)

        result = await list_by_directive(db, directive_id)
        assert [x.task_id for x in result] == [first.task_id, second.task_id]

    async def test_list_by_chief_filters(self, db: Database) -> None:
        a = _make_task(from_chief="strategy-product-chief", description="s1")
        b = _make_task(from_chief="qa-chief", description="q1")
        for x in (a, b):
            await insert_task(db, x)
        result = await list_by_chief(db, "qa-chief")
        assert [x.description for x in result] == ["q1"]

    async def test_list_by_chief_include_terminal(self, db: Database) -> None:
        a = _make_task(from_chief="qa-chief", description="active")
        b = _make_task(from_chief="qa-chief", description="finished")
        await insert_task(db, a)
        await insert_task(db, b)
        await mark_done(db, b.task_id)

        active = await list_by_chief(db, "qa-chief")
        assert [x.description for x in active] == ["active"]

        all_ = await list_by_chief(db, "qa-chief", include_terminal=True)
        assert {x.description for x in all_} == {"active", "finished"}

    async def test_list_all_respects_limit(self, db: Database) -> None:
        for i in range(5):
            await insert_task(db, _make_task(description=f"t{i}"))
        result = await list_all(db, limit=3)
        assert len(result) == 3


# ---------------------------------------------------------------------------
# Security: parameterised queries
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestSqlInjectionResistance:
    async def test_to_specialist_with_payload_stored_verbatim(
        self, db: Database
    ) -> None:
        evil = "researcher'; DROP TABLE tasks; --"
        t = _make_task(to_specialist=evil)
        await insert_task(db, t)
        fetched = await get_task(db, t.task_id)
        assert fetched is not None
        assert fetched.to_specialist == evil

    async def test_description_with_payload_stored_verbatim(
        self, db: Database
    ) -> None:
        evil = "do x'; UPDATE tasks SET status='done'; --"
        t = _make_task(description=evil)
        await insert_task(db, t)
        fetched = await get_task(db, t.task_id)
        assert fetched is not None
        assert fetched.description == evil
        assert await get_status(db, t.task_id) == TaskStatus.ASSIGNED

    async def test_unknown_id_with_payload_returns_none(
        self, db: Database
    ) -> None:
        assert await get_task(db, "task-foo' OR '1'='1") is None
