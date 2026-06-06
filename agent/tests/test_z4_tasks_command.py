"""Tests for the Sprint 21 /z4_tasks operator command.

Mirrors test_directives_command.py — exercises the four modes
(active/all/directive/chief) end-to-end through the real task_store
against a fresh-migrated SQLite, with a hand-constructed CommandHandler
so we don't drag in BridgeApp.

Disambiguated as ``z4_tasks`` to avoid collision with the existing
/tasks (goal/task management) command.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest
import pytest_asyncio

from bridge.commands import CommandHandler
from bridge.database import Database
from bridge.directive_store import insert_directive, new_directive_id
from bridge.task_store import insert_task, mark_done, new_task_id
from teams._types import Directive, Task


@pytest_asyncio.fixture
async def db(tmp_path: Path) -> Database:
    db_path = tmp_path / "test-z4-tasks.db"
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


def _seed_task(
    *,
    directive_id: str | None = None,
    from_chief: str = "strategy-product-chief",
    to_specialist: str = "strategy-market-researcher",
    description: str = "research item",
) -> Task:
    return Task(
        task_id=new_task_id(),
        directive_id=directive_id,
        from_chief=from_chief,
        to_specialist=to_specialist,
        description=description,
        constraints=(),
        deadline_utc=None,
        issued_at_utc=datetime.now(timezone.utc),
    )


async def _seed_directive(db: Database, *, to_chief: str = "strategy-product-chief") -> str:
    d = Directive(
        directive_id=new_directive_id(),
        from_agent="main",
        to_chief=to_chief,
        intent="parent",
        constraints=(),
        deadline_utc=None,
        priority="p1",
        issued_at_utc=datetime.now(timezone.utc),
        context={},
        operator_id="op",
    )
    await insert_directive(db, d)
    return d.directive_id


@pytest.mark.asyncio
class TestZ4TasksCommand:
    async def test_command_registered(self) -> None:
        from bridge.commands import BRIDGE_COMMANDS
        assert "z4_tasks" in BRIDGE_COMMANDS

    async def test_empty_returns_friendly_message(
        self, handler: CommandHandler
    ) -> None:
        out = await handler._cmd_z4_tasks(chat_id="op", args="")
        assert "Active tasks" in out
        assert "No tasks found" in out

    async def test_default_mode_is_active(
        self, handler: CommandHandler, db: Database
    ) -> None:
        t = _seed_task(description="active-thing")
        await insert_task(db, t)
        out = await handler._cmd_z4_tasks(chat_id="op", args="")
        assert t.task_id in out
        assert "active-thing" in out

    async def test_active_excludes_terminal(
        self, handler: CommandHandler, db: Database
    ) -> None:
        a = _seed_task(description="alive")
        b = _seed_task(description="dead")
        await insert_task(db, a)
        await insert_task(db, b)
        await mark_done(db, b.task_id)
        out = await handler._cmd_z4_tasks(chat_id="op", args="active")
        assert a.task_id in out
        assert b.task_id not in out

    async def test_all_mode_includes_terminal(
        self, handler: CommandHandler, db: Database
    ) -> None:
        a = _seed_task(description="alive")
        b = _seed_task(description="dead")
        await insert_task(db, a)
        await insert_task(db, b)
        await mark_done(db, b.task_id)
        out = await handler._cmd_z4_tasks(chat_id="op", args="all")
        assert a.task_id in out
        assert b.task_id in out

    async def test_directive_mode_filters(
        self, handler: CommandHandler, db: Database
    ) -> None:
        directive_id = await _seed_directive(db)
        other = await _seed_directive(db)
        a = _seed_task(directive_id=directive_id, description="under-dir")
        b = _seed_task(directive_id=other, description="other-dir")
        c = _seed_task(directive_id=None, description="orphan")
        for x in (a, b, c):
            await insert_task(db, x)

        out = await handler._cmd_z4_tasks(
            chat_id="op", args=f"directive {directive_id}"
        )
        assert "under-dir" in out
        assert "other-dir" not in out
        assert "orphan" not in out

    async def test_directive_mode_missing_arg(
        self, handler: CommandHandler
    ) -> None:
        out = await handler._cmd_z4_tasks(chat_id="op", args="directive")
        assert "Usage" in out

    async def test_chief_mode_filters(
        self, handler: CommandHandler, db: Database
    ) -> None:
        a = _seed_task(from_chief="qa-chief", description="qa-task")
        b = _seed_task(from_chief="ops-chief", description="ops-task")
        await insert_task(db, a)
        await insert_task(db, b)
        out = await handler._cmd_z4_tasks(chat_id="op", args="chief qa-chief")
        assert "qa-task" in out
        assert "ops-task" not in out

    async def test_chief_mode_missing_arg(
        self, handler: CommandHandler
    ) -> None:
        out = await handler._cmd_z4_tasks(chat_id="op", args="chief")
        assert "Usage" in out

    async def test_unknown_mode_shows_usage(
        self, handler: CommandHandler
    ) -> None:
        out = await handler._cmd_z4_tasks(chat_id="op", args="bogus-mode")
        assert "Usage" in out
        assert "active" in out and "directive" in out and "chief" in out

    async def test_directive_marker_in_output(
        self, handler: CommandHandler, db: Database
    ) -> None:
        directive_id = await _seed_directive(db)
        t = _seed_task(directive_id=directive_id, description="parented")
        await insert_task(db, t)
        out = await handler._cmd_z4_tasks(chat_id="op", args="active")
        assert directive_id in out
        assert "parent=" in out
