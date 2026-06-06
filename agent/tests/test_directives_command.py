"""Tests for the Sprint 20 /directives operator command.

Exercises the three modes (active / all / chief) end-to-end through the
real ``directive_store`` against a fresh migrated SQLite database, with
a hand-constructed ``CommandHandler`` so we don't drag in BridgeApp.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest
import pytest_asyncio

from bridge.commands import CommandHandler
from bridge.database import Database
from bridge.directive_store import (
    insert_directive,
    mark_done,
    mark_in_progress,
    new_directive_id,
)
from teams._types import Directive


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def db(tmp_path: Path) -> Database:
    db_path = tmp_path / "test-cmd-directives.db"
    database = Database(db_path)
    await database.connect()
    await database.migrate()
    yield database
    await database.close()


@pytest.fixture
def handler(db: Database) -> CommandHandler:
    """A CommandHandler with only the attrs /directives reaches for."""
    h = CommandHandler.__new__(CommandHandler)
    h._db = db
    return h


def _seed(
    *,
    to_chief: str = "strategy-product-chief",
    intent: str = "intent",
    priority: str = "p1",
) -> Directive:
    return Directive(
        directive_id=new_directive_id(),
        from_agent="main",
        to_chief=to_chief,
        intent=intent,
        constraints=(),
        deadline_utc=None,
        priority=priority,
        issued_at_utc=datetime.now(timezone.utc),
        context={},
        operator_id="op-test",
    )


# ---------------------------------------------------------------------------
# Empty / default
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestDirectivesCommand:
    async def test_empty_active_returns_friendly_message(
        self, handler: CommandHandler
    ) -> None:
        out = await handler._cmd_directives(chat_id="op", args="")
        assert "Active directives" in out
        assert "0" in out
        assert "No directives found" in out

    async def test_default_mode_is_active(
        self, handler: CommandHandler, db: Database
    ) -> None:
        d = _seed(intent="probe-active")
        await insert_directive(db, d)
        out = await handler._cmd_directives(chat_id="op", args="")
        assert "Active directives" in out
        assert d.directive_id in out
        assert "probe-active" in out

    async def test_active_excludes_terminal(
        self, handler: CommandHandler, db: Database
    ) -> None:
        a = _seed(intent="active-one")
        b = _seed(intent="done-one")
        await insert_directive(db, a)
        await insert_directive(db, b)
        await mark_done(db, b.directive_id)

        out = await handler._cmd_directives(chat_id="op", args="active")
        assert a.directive_id in out
        assert "active-one" in out
        assert b.directive_id not in out

    async def test_all_mode_includes_terminal(
        self, handler: CommandHandler, db: Database
    ) -> None:
        a = _seed(intent="alive")
        b = _seed(intent="dead")
        await insert_directive(db, a)
        await insert_directive(db, b)
        await mark_done(db, b.directive_id)

        out = await handler._cmd_directives(chat_id="op", args="all")
        assert a.directive_id in out
        assert b.directive_id in out
        assert "All directives" in out

    async def test_chief_mode_filters(
        self, handler: CommandHandler, db: Database
    ) -> None:
        s = _seed(to_chief="strategy-product-chief", intent="strategy-task")
        q = _seed(to_chief="qa-chief", intent="qa-task")
        await insert_directive(db, s)
        await insert_directive(db, q)

        out = await handler._cmd_directives(
            chat_id="op", args="chief qa-chief"
        )
        assert "qa-task" in out
        assert "strategy-task" not in out
        assert "qa-chief" in out

    async def test_chief_mode_missing_arg_shows_usage(
        self, handler: CommandHandler
    ) -> None:
        out = await handler._cmd_directives(chat_id="op", args="chief")
        assert "Usage" in out
        assert "chief" in out

    async def test_unknown_mode_shows_usage(
        self, handler: CommandHandler
    ) -> None:
        out = await handler._cmd_directives(
            chat_id="op", args="totally-bogus"
        )
        assert "Usage" in out
        assert "active" in out and "all" in out and "chief" in out

    async def test_status_label_reflects_lifecycle(
        self, handler: CommandHandler, db: Database
    ) -> None:
        d = _seed(intent="watch-me")
        await insert_directive(db, d)
        await mark_in_progress(db, d.directive_id)

        out = await handler._cmd_directives(chat_id="op", args="active")
        assert "in_progress" in out
        assert d.directive_id in out

    async def test_directives_command_registered(self) -> None:
        """`directives` must be in BRIDGE_COMMANDS so handle() routes it."""
        from bridge.commands import BRIDGE_COMMANDS
        assert "directives" in BRIDGE_COMMANDS


# ---------------------------------------------------------------------------
# /direct — Sprint 20 PR B
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestDirectCommand:
    async def test_direct_command_registered(self) -> None:
        from bridge.commands import BRIDGE_COMMANDS
        assert "direct" in BRIDGE_COMMANDS

    async def test_missing_args_shows_usage(
        self, handler: CommandHandler
    ) -> None:
        # Departments must be present for the handler to enter the args check
        import unittest.mock as mock
        handler._departments = mock.MagicMock()
        handler._departments.department_names.return_value = ["qa-chief"]
        out = await handler._cmd_direct(chat_id="op", args="")
        assert "Usage" in out
        out = await handler._cmd_direct(chat_id="op", args="qa-chief")
        assert "Usage" in out

    async def test_unknown_chief_returns_friendly_error(
        self, handler: CommandHandler
    ) -> None:
        import unittest.mock as mock
        handler._departments = mock.MagicMock()
        handler._departments.department_names.return_value = ["qa-chief", "ops-chief"]
        out = await handler._cmd_direct(
            chat_id="op", args="not-a-chief do something"
        )
        assert "Unknown chief" in out
        assert "qa-chief" in out

    async def test_no_departments_returns_friendly_error(
        self, handler: CommandHandler
    ) -> None:
        handler._departments = None
        out = await handler._cmd_direct(chat_id="op", args="any thing")
        assert "not wired" in out.lower() or "not wired" in out
