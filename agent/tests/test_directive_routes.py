"""Tests for Sprint 23 — directive lifecycle dashboard REST routes.

Builds an aiohttp test client around a bare ``web.Application`` with a
fresh-migrated SQLite database and the four routes registered. Skips
the auth middleware because the existing Bearer-token middleware is
exercised in ``tests/test_api_server.py``; this suite focuses on the
new route shapes, filters, and error paths.

WebSocket event flow is covered by the existing
``tests/test_api_server*.py`` infrastructure plus the ``_safe_publish``
hooks in the stores; the publish hooks are exercised directly in the
store tests.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import AsyncIterator

import pytest
import pytest_asyncio
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from bridge.api.directives_routes import DirectiveRoutes
from bridge.database import Database
from bridge.directive_store import insert_directive, mark_done, new_directive_id
from bridge.surface_store import insert_surface, new_surface_id
from bridge.task_store import insert_task, new_task_id
from teams._types import (
    Directive,
    Surface,
    SurfaceKind,
    Task,
    Urgency,
)

pytestmark = pytest.mark.socket  # binds localhost sockets via aiohttp TestServer


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def db(tmp_path: Path) -> Database:
    db_path = tmp_path / "test-routes.db"
    database = Database(db_path)
    await database.connect()
    await database.migrate()
    yield database
    await database.close()


@pytest_asyncio.fixture
async def client(db: Database) -> AsyncIterator[TestClient]:
    """A TestClient with the directive routes mounted, no auth middleware."""
    app = web.Application()
    DirectiveRoutes(db=db).register(app)
    server = TestServer(app)
    test_client = TestClient(server)
    await test_client.start_server()
    try:
        yield test_client
    finally:
        await test_client.close()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _seed_directive(
    db: Database,
    *,
    directive_id: str | None = None,
    to_chief: str = "strategy-product-chief",
    intent: str = "size the audio AI market",
    priority: str = "p1",
) -> Directive:
    d = Directive(
        directive_id=directive_id or new_directive_id(),
        from_agent="main",
        to_chief=to_chief,
        intent=intent,
        constraints=("budget=$2",),
        deadline_utc=None,
        priority=priority,
        issued_at_utc=datetime.now(timezone.utc),
        context={"chat_id": "op"},
        operator_id="op",
    )
    await insert_directive(db, d)
    return d


async def _seed_task(
    db: Database, *, directive_id: str | None, to_specialist: str = "alpha",
) -> Task:
    t = Task(
        task_id=new_task_id(),
        directive_id=directive_id,
        from_chief="strategy-product-chief",
        to_specialist=to_specialist,
        description="research item",
        constraints=(),
        deadline_utc=None,
        issued_at_utc=datetime.now(timezone.utc),
    )
    await insert_task(db, t)
    return t


async def _seed_surface(
    db: Database,
    *,
    correlation_id: str | None,
    kind: SurfaceKind = SurfaceKind.RESULT,
    urgency: Urgency = Urgency.FYI,
    from_agent: str = "alpha",
    to_agent: str = "strategy-product-chief",
    summary: str = "result",
) -> Surface:
    s = Surface(
        surface_id=new_surface_id(),
        from_agent=from_agent,
        to_agent=to_agent,
        kind=kind,
        urgency=urgency,
        correlation_id=correlation_id,
        payload={"summary": summary},
        created_at_utc=datetime.now(timezone.utc),
    )
    await insert_surface(db, s)
    return s


# ---------------------------------------------------------------------------
# GET /api/directives
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestListDirectives:
    async def test_empty_returns_empty_list(self, client: TestClient) -> None:
        resp = await client.get("/api/directives")
        assert resp.status == 200
        body = await resp.json()
        assert body == {"directives": []}

    async def test_default_status_is_active(
        self, client: TestClient, db: Database
    ) -> None:
        active = await _seed_directive(db, intent="active-one")
        done = await _seed_directive(db, intent="done-one")
        await mark_done(db, done.directive_id)

        resp = await client.get("/api/directives")
        assert resp.status == 200
        body = await resp.json()
        ids = {d["directive_id"] for d in body["directives"]}
        assert active.directive_id in ids
        assert done.directive_id not in ids

    async def test_status_all_includes_terminal(
        self, client: TestClient, db: Database
    ) -> None:
        a = await _seed_directive(db, intent="a")
        b = await _seed_directive(db, intent="b")
        await mark_done(db, b.directive_id)
        resp = await client.get("/api/directives?status=all")
        body = await resp.json()
        ids = {d["directive_id"] for d in body["directives"]}
        assert a.directive_id in ids
        assert b.directive_id in ids

    async def test_unknown_status_returns_400(
        self, client: TestClient
    ) -> None:
        resp = await client.get("/api/directives?status=nonsense")
        assert resp.status == 400
        body = await resp.json()
        assert "unknown status" in body["error"]

    async def test_serialised_shape(
        self, client: TestClient, db: Database
    ) -> None:
        d = await _seed_directive(
            db, intent="probe shape", priority="p0",
        )
        resp = await client.get("/api/directives")
        body = await resp.json()
        item = next(
            x for x in body["directives"]
            if x["directive_id"] == d.directive_id
        )
        assert item["intent"] == "probe shape"
        assert item["priority"] == "p0"
        assert item["constraints"] == ["budget=$2"]
        # ISO-8601 round trip
        assert item["issued_at_utc"].endswith("+00:00")

    async def test_limit_clamps_high(
        self, client: TestClient, db: Database
    ) -> None:
        for i in range(3):
            await _seed_directive(db, intent=f"intent-{i}")
        resp = await client.get("/api/directives?status=all&limit=999")
        assert resp.status == 200
        body = await resp.json()
        # 3 seeded ≤ 200 clamp ceiling — at most 3 returned anyway
        assert len(body["directives"]) == 3

    async def test_limit_handles_garbage(
        self, client: TestClient, db: Database
    ) -> None:
        await _seed_directive(db, intent="x")
        resp = await client.get("/api/directives?limit=not-a-number")
        # Falls back to default; doesn't 500
        assert resp.status == 200


# ---------------------------------------------------------------------------
# GET /api/directives/{id}/tree
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestDirectiveTree:
    async def test_404_unknown_id(self, client: TestClient) -> None:
        resp = await client.get("/api/directives/dir-doesnotexist/tree")
        assert resp.status == 404
        body = await resp.json()
        assert body["error"] == "not found"

    async def test_returns_directive_tasks_surfaces(
        self, client: TestClient, db: Database
    ) -> None:
        d = await _seed_directive(db, intent="parent")
        t1 = await _seed_task(db, directive_id=d.directive_id, to_specialist="alpha")
        t2 = await _seed_task(db, directive_id=d.directive_id, to_specialist="beta")

        # Surfaces at chief tier (correlation_id = directive_id)
        chief_s = await _seed_surface(
            db, correlation_id=d.directive_id,
            from_agent="strategy-product-chief", to_agent="main",
            summary="chief synthesis",
        )
        # Surfaces at specialist tier (correlation_id = task_id)
        a_result = await _seed_surface(
            db, correlation_id=t1.task_id, summary="alpha result",
        )

        resp = await client.get(f"/api/directives/{d.directive_id}/tree")
        assert resp.status == 200
        body = await resp.json()

        assert body["directive"]["directive_id"] == d.directive_id
        task_ids = {t["task_id"] for t in body["tasks"]}
        assert task_ids == {t1.task_id, t2.task_id}
        surface_ids = {s["surface_id"] for s in body["surfaces"]}
        assert {chief_s.surface_id, a_result.surface_id} <= surface_ids

    async def test_surfaces_sorted_chronologically(
        self, client: TestClient, db: Database
    ) -> None:
        d = await _seed_directive(db, intent="parent")
        t = await _seed_task(db, directive_id=d.directive_id)

        # Insert task-tier first, then chief-tier — but chief was created
        # later in real time, so chronological order should reflect that.
        first = await _seed_surface(
            db, correlation_id=t.task_id, summary="early"
        )
        second = await _seed_surface(
            db, correlation_id=d.directive_id, summary="late"
        )

        resp = await client.get(f"/api/directives/{d.directive_id}/tree")
        body = await resp.json()
        ordered_ids = [s["surface_id"] for s in body["surfaces"]]
        assert ordered_ids.index(first.surface_id) < ordered_ids.index(second.surface_id)


# ---------------------------------------------------------------------------
# GET /api/surfaces
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestListSurfaces:
    async def test_default_unread_active(
        self, client: TestClient, db: Database
    ) -> None:
        a = await _seed_surface(db, correlation_id=None, summary="alive")
        b = await _seed_surface(db, correlation_id=None, summary="dead")
        from bridge.surface_store import mark_read
        await mark_read(db, b.surface_id)

        resp = await client.get("/api/surfaces")
        body = await resp.json()
        ids = {s["surface_id"] for s in body["surfaces"]}
        assert a.surface_id in ids
        assert b.surface_id not in ids

    async def test_unread_to_agent_main(
        self, client: TestClient, db: Database
    ) -> None:
        to_main = await _seed_surface(
            db, correlation_id=None, to_agent="main", summary="for-op",
        )
        to_chief = await _seed_surface(
            db, correlation_id=None, to_agent="some-chief", summary="for-chief",
        )

        resp = await client.get("/api/surfaces?unread=true&to_agent=main")
        body = await resp.json()
        ids = {s["surface_id"] for s in body["surfaces"]}
        assert to_main.surface_id in ids
        assert to_chief.surface_id not in ids

    async def test_kind_filter(
        self, client: TestClient, db: Database
    ) -> None:
        b = await _seed_surface(
            db, correlation_id=None, kind=SurfaceKind.BLOCKER,
            summary="blocked",
        )
        r = await _seed_surface(
            db, correlation_id=None, kind=SurfaceKind.RESULT,
            summary="result",
        )
        resp = await client.get("/api/surfaces?kind=blocker")
        body = await resp.json()
        ids = {s["surface_id"] for s in body["surfaces"]}
        assert b.surface_id in ids
        assert r.surface_id not in ids

    async def test_kind_invalid_returns_400(
        self, client: TestClient
    ) -> None:
        resp = await client.get("/api/surfaces?kind=bogus")
        assert resp.status == 400


# ---------------------------------------------------------------------------
# POST /api/surfaces/{id}/ack
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestAckSurface:
    async def test_acks_unread_returns_updated_true(
        self, client: TestClient, db: Database
    ) -> None:
        s = await _seed_surface(db, correlation_id=None)
        resp = await client.post(f"/api/surfaces/{s.surface_id}/ack")
        assert resp.status == 200
        body = await resp.json()
        assert body == {"updated": True}

    async def test_re_ack_returns_updated_false(
        self, client: TestClient, db: Database
    ) -> None:
        s = await _seed_surface(db, correlation_id=None)
        await client.post(f"/api/surfaces/{s.surface_id}/ack")
        resp = await client.post(f"/api/surfaces/{s.surface_id}/ack")
        body = await resp.json()
        assert body == {"updated": False}

    async def test_unknown_id_returns_404(
        self, client: TestClient
    ) -> None:
        resp = await client.post("/api/surfaces/surf-doesnotexist/ack")
        assert resp.status == 404


# ---------------------------------------------------------------------------
# Registration tolerates frozen router
# ---------------------------------------------------------------------------


def test_register_tolerates_frozen_router() -> None:
    """If register() is called after the app starts, it must log + return
    rather than raising — graceful-degradation pattern shared with
    Zone4Routes."""
    import asyncio

    async def _go() -> None:
        from bridge.database import Database
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            db = Database(Path(tmp) / "x.db")
            await db.connect()
            await db.migrate()
            try:
                app = web.Application()
                runner = web.AppRunner(app)
                await runner.setup()
                # Now the router is frozen
                site = web.TCPSite(runner, "127.0.0.1", 0)
                await site.start()
                try:
                    # Must not raise
                    DirectiveRoutes(db=db).register(app)
                finally:
                    await runner.cleanup()
            finally:
                await db.close()

    asyncio.run(_go())
