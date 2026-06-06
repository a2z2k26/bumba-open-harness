"""Unit tests for the Sprint 22 (Phase 5C) surface_store module.

Mirrors the test shape of test_directive_store.py and test_task_store.py.
Real Database fixture, migration #12 schema, parameterised query
verification, lifecycle (insert + mark_read), listing filters, and
SQL-injection resistance.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest
import pytest_asyncio

from bridge.database import Database
from bridge.surface_store import (
    get_surface,
    insert_surface,
    is_read,
    list_active,
    list_all,
    list_by_correlation,
    list_by_kind,
    list_unread_for_agent,
    mark_read,
    new_surface_id,
    task_has_result_surface,
)
from teams._types import (
    SURFACE_KINDS,
    SURFACE_URGENCIES,
    Surface,
    SurfaceKind,
    Urgency,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def db(tmp_path: Path) -> Database:
    db_path = tmp_path / "test-surfaces.db"
    database = Database(db_path)
    await database.connect()
    await database.migrate()
    yield database
    await database.close()


def _make_surface(
    *,
    surface_id: str | None = None,
    from_agent: str = "alpha",
    to_agent: str = "strategy-product-chief",
    kind: SurfaceKind = SurfaceKind.RESULT,
    urgency: Urgency = Urgency.FYI,
    correlation_id: str | None = "task-test12345678",
    payload: dict | None = None,
) -> Surface:
    return Surface(
        surface_id=surface_id or new_surface_id(),
        from_agent=from_agent,
        to_agent=to_agent,
        kind=kind,
        urgency=urgency,
        correlation_id=correlation_id,
        payload=payload or {},
        created_at_utc=datetime.now(timezone.utc),
    )


# ---------------------------------------------------------------------------
# new_surface_id
# ---------------------------------------------------------------------------


class TestNewSurfaceId:
    def test_format(self) -> None:
        sid = new_surface_id()
        assert sid.startswith("surf-")
        assert len(sid) == 5 + 12  # "surf-" + 12 hex
        int(sid[5:], 16)

    def test_uniqueness(self) -> None:
        ids = {new_surface_id() for _ in range(1000)}
        assert len(ids) == 1000


# ---------------------------------------------------------------------------
# insert + get
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestInsertAndGet:
    async def test_round_trip_minimal(self, db: Database) -> None:
        s = _make_surface()
        await insert_surface(db, s)
        fetched = await get_surface(db, s.surface_id)
        assert fetched is not None
        assert fetched.surface_id == s.surface_id
        assert fetched.kind == SurfaceKind.RESULT
        assert fetched.urgency == Urgency.FYI

    async def test_round_trip_full_payload(self, db: Database) -> None:
        s = _make_surface(
            kind=SurfaceKind.BLOCKER,
            urgency=Urgency.IMMEDIATE,
            payload={"summary": "out of credits", "metric": 0},
        )
        await insert_surface(db, s)
        fetched = await get_surface(db, s.surface_id)
        assert fetched is not None
        assert dict(fetched.payload) == {"summary": "out of credits", "metric": 0}

    async def test_correlation_id_can_be_null(self, db: Database) -> None:
        s = _make_surface(correlation_id=None)
        await insert_surface(db, s)
        fetched = await get_surface(db, s.surface_id)
        assert fetched is not None
        assert fetched.correlation_id is None

    async def test_initial_read_at_is_null(self, db: Database) -> None:
        s = _make_surface()
        await insert_surface(db, s)
        assert await is_read(db, s.surface_id) is False

    async def test_get_unknown_returns_none(self, db: Database) -> None:
        assert await get_surface(db, "surf-doesnotexist") is None
        assert await is_read(db, "surf-doesnotexist") is None


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestValidation:
    @pytest.mark.parametrize("kind_value", SURFACE_KINDS)
    async def test_accepts_every_canonical_kind(
        self, db: Database, kind_value: str
    ) -> None:
        s = _make_surface(kind=SurfaceKind(kind_value))
        await insert_surface(db, s)
        fetched = await get_surface(db, s.surface_id)
        assert fetched is not None

    @pytest.mark.parametrize("urgency_value", SURFACE_URGENCIES)
    async def test_accepts_every_canonical_urgency(
        self, db: Database, urgency_value: str
    ) -> None:
        s = _make_surface(urgency=Urgency(urgency_value))
        await insert_surface(db, s)
        fetched = await get_surface(db, s.surface_id)
        assert fetched is not None


# ---------------------------------------------------------------------------
# mark_read / /ack semantics
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestMarkRead:
    async def test_first_ack_returns_true(self, db: Database) -> None:
        s = _make_surface()
        await insert_surface(db, s)
        assert await mark_read(db, s.surface_id) is True
        assert await is_read(db, s.surface_id) is True

    async def test_second_ack_is_idempotent(self, db: Database) -> None:
        s = _make_surface()
        await insert_surface(db, s)
        await mark_read(db, s.surface_id)
        # Re-acking returns False — the row was already flagged read
        assert await mark_read(db, s.surface_id) is False

    async def test_unknown_id_raises(self, db: Database) -> None:
        with pytest.raises(ValueError):
            await mark_read(db, "surf-nope")


# ---------------------------------------------------------------------------
# Listing
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestListing:
    async def test_list_by_correlation_chronological(
        self, db: Database
    ) -> None:
        from datetime import timedelta

        now = datetime.now(timezone.utc)
        a = Surface(
            surface_id=new_surface_id(),
            from_agent="alpha",
            to_agent="chief",
            kind=SurfaceKind.RESULT,
            urgency=Urgency.FYI,
            correlation_id="task-shared",
            payload={"label": "first"},
            created_at_utc=now - timedelta(seconds=5),
        )
        b = Surface(
            surface_id=new_surface_id(),
            from_agent="alpha",
            to_agent="chief",
            kind=SurfaceKind.FLAG,
            urgency=Urgency.ATTENTION,
            correlation_id="task-shared",
            payload={"label": "second"},
            created_at_utc=now,
        )
        await insert_surface(db, a)
        await insert_surface(db, b)

        result = await list_by_correlation(db, "task-shared")
        assert [r.surface_id for r in result] == [a.surface_id, b.surface_id]

    async def test_list_unread_for_agent(self, db: Database) -> None:
        a = _make_surface(to_agent="main", correlation_id="dir-1")
        b = _make_surface(to_agent="main", correlation_id="dir-2")
        c = _make_surface(to_agent="some-chief", correlation_id="dir-3")
        for x in (a, b, c):
            await insert_surface(db, x)
        await mark_read(db, b.surface_id)

        result = await list_unread_for_agent(db, "main")
        ids = {r.surface_id for r in result}
        assert ids == {a.surface_id}

    async def test_list_active_filters_read(self, db: Database) -> None:
        a = _make_surface()
        b = _make_surface()
        await insert_surface(db, a)
        await insert_surface(db, b)
        await mark_read(db, a.surface_id)
        result = await list_active(db)
        ids = {r.surface_id for r in result}
        assert b.surface_id in ids
        assert a.surface_id not in ids

    async def test_list_by_kind_filters(self, db: Database) -> None:
        a = _make_surface(kind=SurfaceKind.RESULT)
        b = _make_surface(kind=SurfaceKind.BLOCKER)
        c = _make_surface(kind=SurfaceKind.RESULT)
        for x in (a, b, c):
            await insert_surface(db, x)
        result = await list_by_kind(db, SurfaceKind.BLOCKER)
        assert [r.surface_id for r in result] == [b.surface_id]

    async def test_list_by_kind_invalid_raises(self, db: Database) -> None:
        with pytest.raises(ValueError):
            await list_by_kind(db, "nonsense")

    async def test_list_all_respects_limit(self, db: Database) -> None:
        for _ in range(5):
            await insert_surface(db, _make_surface())
        result = await list_all(db, limit=3)
        assert len(result) == 3


# ---------------------------------------------------------------------------
# task_has_result_surface — used by _team.py for synthesis
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestTaskHasResultSurface:
    async def test_returns_true_when_result_exists(self, db: Database) -> None:
        s = _make_surface(
            kind=SurfaceKind.RESULT, correlation_id="task-yes"
        )
        await insert_surface(db, s)
        assert await task_has_result_surface(db, "task-yes") is True

    async def test_returns_false_when_only_other_kinds(
        self, db: Database
    ) -> None:
        s = _make_surface(kind=SurfaceKind.FLAG, correlation_id="task-no")
        await insert_surface(db, s)
        assert await task_has_result_surface(db, "task-no") is False

    async def test_returns_false_when_no_surfaces(self, db: Database) -> None:
        assert await task_has_result_surface(db, "task-empty") is False


# ---------------------------------------------------------------------------
# Security
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestSqlInjectionResistance:
    async def test_payload_with_sql_string_stored_verbatim(
        self, db: Database
    ) -> None:
        evil = {
            "summary": "x'; UPDATE surfaces SET read_at_utc='now'; --",
        }
        s = _make_surface(payload=evil)
        await insert_surface(db, s)
        fetched = await get_surface(db, s.surface_id)
        assert fetched is not None
        assert dict(fetched.payload) == evil
        # Injection didn't run — surface is still unread
        assert await is_read(db, s.surface_id) is False

    async def test_correlation_id_with_payload_returns_empty(
        self, db: Database
    ) -> None:
        result = await list_by_correlation(db, "task-x' OR '1'='1")
        assert result == []

    async def test_from_agent_with_payload_stored_verbatim(
        self, db: Database
    ) -> None:
        evil = "alpha'; DROP TABLE surfaces; --"
        s = _make_surface(from_agent=evil)
        await insert_surface(db, s)
        fetched = await get_surface(db, s.surface_id)
        assert fetched is not None
        assert fetched.from_agent == evil
