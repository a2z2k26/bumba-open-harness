"""Tests for the Sprint 22 /surfaces and /ack operator commands.

Mirrors the test shape of test_directives_command.py and
test_z4_tasks_command.py — exercises every mode end-to-end through the
real surface_store against a fresh-migrated SQLite, with a
hand-constructed CommandHandler.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest
import pytest_asyncio

from bridge.commands import CommandHandler
from bridge.database import Database
from bridge.surface_store import (
    insert_surface,
    is_read,
    mark_read,
    new_surface_id,
)
from teams._types import Surface, SurfaceKind, Urgency


@pytest_asyncio.fixture
async def db(tmp_path: Path) -> Database:
    db_path = tmp_path / "test-cmd-surfaces.db"
    database = Database(db_path)
    await database.connect()
    await database.migrate()
    yield database
    await database.close()


@pytest.fixture
def handler(db: Database) -> CommandHandler:
    h = CommandHandler.__new__(CommandHandler)
    h._db = db
    return h


def _seed(
    *,
    from_agent: str = "alpha",
    to_agent: str = "strategy-product-chief",
    kind: SurfaceKind = SurfaceKind.RESULT,
    urgency: Urgency = Urgency.FYI,
    correlation_id: str | None = None,
    payload: dict | None = None,
) -> Surface:
    return Surface(
        surface_id=new_surface_id(),
        from_agent=from_agent,
        to_agent=to_agent,
        kind=kind,
        urgency=urgency,
        correlation_id=correlation_id,
        payload=payload or {"summary": "test"},
        created_at_utc=datetime.now(timezone.utc),
    )


# ---------------------------------------------------------------------------
# /surfaces
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestSurfacesCommand:
    async def test_command_registered(self) -> None:
        from bridge.commands import BRIDGE_COMMANDS
        assert "surfaces" in BRIDGE_COMMANDS

    async def test_empty_returns_friendly_message(
        self, handler: CommandHandler
    ) -> None:
        out = await handler._cmd_surfaces(chat_id="op", args="")
        assert "Active surfaces" in out
        assert "No surfaces found" in out

    async def test_default_mode_is_active(
        self, handler: CommandHandler, db: Database
    ) -> None:
        s = _seed()
        await insert_surface(db, s)
        out = await handler._cmd_surfaces(chat_id="op", args="")
        assert s.surface_id in out

    async def test_unread_filters_to_main(
        self, handler: CommandHandler, db: Database
    ) -> None:
        a = _seed(to_agent="main", payload={"summary": "to-main"})
        b = _seed(to_agent="some-chief", payload={"summary": "to-chief"})
        await insert_surface(db, a)
        await insert_surface(db, b)
        out = await handler._cmd_surfaces(chat_id="op", args="unread")
        assert "to-main" in out
        assert "to-chief" not in out

    async def test_active_excludes_read(
        self, handler: CommandHandler, db: Database
    ) -> None:
        a = _seed(payload={"summary": "alive"})
        b = _seed(payload={"summary": "dead"})
        await insert_surface(db, a)
        await insert_surface(db, b)
        await mark_read(db, b.surface_id)
        out = await handler._cmd_surfaces(chat_id="op", args="active")
        assert "alive" in out
        assert "dead" not in out

    async def test_all_includes_read(
        self, handler: CommandHandler, db: Database
    ) -> None:
        a = _seed(payload={"summary": "alive"})
        b = _seed(payload={"summary": "dead"})
        await insert_surface(db, a)
        await insert_surface(db, b)
        await mark_read(db, b.surface_id)
        out = await handler._cmd_surfaces(chat_id="op", args="all")
        assert "alive" in out
        assert "dead" in out

    async def test_directive_filter(
        self, handler: CommandHandler, db: Database
    ) -> None:
        a = _seed(correlation_id="dir-abc", payload={"summary": "first"})
        b = _seed(correlation_id="dir-xyz", payload={"summary": "second"})
        await insert_surface(db, a)
        await insert_surface(db, b)
        out = await handler._cmd_surfaces(
            chat_id="op", args="directive dir-abc"
        )
        assert "first" in out
        assert "second" not in out

    async def test_directive_missing_arg(
        self, handler: CommandHandler
    ) -> None:
        out = await handler._cmd_surfaces(chat_id="op", args="directive")
        assert "Usage" in out

    async def test_kind_filter(
        self, handler: CommandHandler, db: Database
    ) -> None:
        a = _seed(kind=SurfaceKind.BLOCKER, payload={"summary": "blocked"})
        b = _seed(kind=SurfaceKind.RESULT, payload={"summary": "result"})
        await insert_surface(db, a)
        await insert_surface(db, b)
        out = await handler._cmd_surfaces(chat_id="op", args="kind blocker")
        assert "blocked" in out
        assert "result" not in out

    async def test_kind_invalid(
        self, handler: CommandHandler
    ) -> None:
        out = await handler._cmd_surfaces(chat_id="op", args="kind nonsense")
        assert "Invalid kind" in out

    async def test_kind_missing_arg(
        self, handler: CommandHandler
    ) -> None:
        out = await handler._cmd_surfaces(chat_id="op", args="kind")
        assert "Usage" in out

    async def test_unknown_mode_shows_usage(
        self, handler: CommandHandler
    ) -> None:
        out = await handler._cmd_surfaces(chat_id="op", args="bogus")
        assert "Usage" in out


# ---------------------------------------------------------------------------
# /ack
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestAckCommand:
    async def test_command_registered(self) -> None:
        from bridge.commands import BRIDGE_COMMANDS
        assert "ack" in BRIDGE_COMMANDS

    async def test_missing_arg_shows_usage(
        self, handler: CommandHandler
    ) -> None:
        out = await handler._cmd_ack(chat_id="op", args="")
        assert "Usage" in out

    async def test_acks_unread_surface(
        self, handler: CommandHandler, db: Database
    ) -> None:
        s = _seed()
        await insert_surface(db, s)
        out = await handler._cmd_ack(chat_id="op", args=s.surface_id)
        assert "Acknowledged" in out
        assert s.surface_id in out
        assert await is_read(db, s.surface_id) is True

    async def test_re_ack_is_idempotent(
        self, handler: CommandHandler, db: Database
    ) -> None:
        s = _seed()
        await insert_surface(db, s)
        await handler._cmd_ack(chat_id="op", args=s.surface_id)
        out2 = await handler._cmd_ack(chat_id="op", args=s.surface_id)
        assert "already acknowledged" in out2

    async def test_unknown_id_returns_error(
        self, handler: CommandHandler
    ) -> None:
        out = await handler._cmd_ack(chat_id="op", args="surf-doesnotexist")
        assert "Error" in out
