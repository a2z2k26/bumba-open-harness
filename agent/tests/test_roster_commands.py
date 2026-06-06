"""Tests for the RR.4 roster operator commands (issue #2593).

Exercises ``/register-specialist``, ``/unregister-specialist``, and
``/roster`` end-to-end through a real ``RosterRegistryStore`` against a fresh
tmp SQLite database, with a hand-constructed ``CommandHandler`` so we don't
drag in BridgeApp (mirrors ``test_directives_command.py``).

The load-bearing seam (the spec's #1 risk): the chief agent is AgentCache-keyed
on ``(team, agent)`` only — the roster overlay is NOT in the key. So a
registration is invisible until the team cache is invalidated. ``register``
fires ``on_change(department)``; in production that is wired to
``AgentCache.invalidate``. ``test_register_command_invalidates_cache`` proves
the register path runs that callback so the next chief build picks up the
overlay.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from bridge.commands import CommandHandler
from bridge.roster_registry_store import RosterRegistryStore


# ---------------------------------------------------------------------------
# Fakes / fixtures
# ---------------------------------------------------------------------------


class _FakeEmployee:
    def __init__(self, name: str) -> None:
        self.name = name


class _FakeConfig:
    def __init__(self, employees: list[str]) -> None:
        self.employees = [_FakeEmployee(n) for n in employees]


def _config_lookup(department: str):
    """Two known departments; everything else is unknown (None)."""
    table = {
        "engineering": _FakeConfig(["backend-architect", "frontend-developer"]),
        "qa": _FakeConfig(["qa-engineer"]),
    }
    return table.get(department)


class _RecordingBus:
    """Captures published events for assertions."""

    def __init__(self) -> None:
        self.published: list[tuple[str, dict, str]] = []

    def publish(self, event_type, payload=None, source="", correlation_id=None):
        self.published.append((event_type, payload or {}, source))


class _FakeAutonomy:
    def __init__(self, bus) -> None:
        self.event_bus = bus


@pytest.fixture
def store(tmp_path: Path) -> RosterRegistryStore:
    s = RosterRegistryStore(
        tmp_path / "roster-cmd.db", config_lookup=_config_lookup
    )
    yield s
    s.close()


@pytest.fixture
def handler(store: RosterRegistryStore) -> CommandHandler:
    """A CommandHandler with only the attrs the roster commands reach for."""
    h = CommandHandler.__new__(CommandHandler)
    h._roster_registry = store
    h._autonomy = None
    return h


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestRegisterCommand:
    async def test_register_command_registered(self) -> None:
        from bridge.commands import BRIDGE_COMMANDS

        assert "register_specialist" in BRIDGE_COMMANDS

    async def test_register_command(
        self, handler: CommandHandler, store: RosterRegistryStore
    ) -> None:
        out = await handler._cmd_register_specialist(
            chat_id="op",
            args="engineering perf-guru backend-architect",
        )
        assert "perf-guru" in out
        assert "engineering" in out
        # Persisted into the store.
        names = {s.name for s in store.list_for_department("engineering")}
        assert "perf-guru" in names

    async def test_register_command_usage_on_missing_args(
        self, handler: CommandHandler
    ) -> None:
        out = await handler._cmd_register_specialist(chat_id="op", args="eng x")
        assert "Usage" in out

    async def test_register_command_surfaces_validation_error(
        self, handler: CommandHandler
    ) -> None:
        # Unknown department — the store rejects; the operator sees the reason.
        out = await handler._cmd_register_specialist(
            chat_id="op", args="nosuchdept foo backend-architect"
        )
        assert "nosuchdept" in out
        assert "perf-guru" not in out

    async def test_register_command_rejects_unresolvable_agent_ref(
        self, handler: CommandHandler
    ) -> None:
        out = await handler._cmd_register_specialist(
            chat_id="op", args="engineering foo not-an-employee"
        )
        assert "not-an-employee" in out

    async def test_register_command_emits_event(
        self, tmp_path: Path, store: RosterRegistryStore
    ) -> None:
        bus = _RecordingBus()
        h = CommandHandler.__new__(CommandHandler)
        h._roster_registry = store
        h._autonomy = _FakeAutonomy(bus)

        await h._cmd_register_specialist(
            chat_id="op", args="engineering perf-guru backend-architect"
        )
        assert len(bus.published) == 1
        event_type, payload, _ = bus.published[0]
        assert event_type == "z4.roster.specialist_registered"
        assert payload["department"] == "engineering"
        assert payload["name"] == "perf-guru"
        assert payload["agent_ref"] == "backend-architect"

    async def test_register_command_invalidates_cache(
        self, tmp_path: Path
    ) -> None:
        """The load-bearing seam: register fires on_change(department) so the
        team's cached chief is invalidated and the next build sees the overlay.
        """
        invalidated: list[str] = []
        store = RosterRegistryStore(
            tmp_path / "seam.db",
            config_lookup=_config_lookup,
            on_change=invalidated.append,
        )
        try:
            h = CommandHandler.__new__(CommandHandler)
            h._roster_registry = store
            h._autonomy = None

            await h._cmd_register_specialist(
                chat_id="op", args="engineering perf-guru backend-architect"
            )
            assert invalidated == ["engineering"]
        finally:
            store.close()

    async def test_register_command_no_store(self) -> None:
        h = CommandHandler.__new__(CommandHandler)
        h._roster_registry = None
        h._autonomy = None
        out = await h._cmd_register_specialist(
            chat_id="op", args="engineering perf-guru backend-architect"
        )
        assert "not" in out.lower()


# ---------------------------------------------------------------------------
# Unregistration
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestUnregisterCommand:
    async def test_unregister_command_registered(self) -> None:
        from bridge.commands import BRIDGE_COMMANDS

        assert "unregister_specialist" in BRIDGE_COMMANDS

    async def test_unregister_command(
        self, handler: CommandHandler, store: RosterRegistryStore
    ) -> None:
        store.register("engineering", "perf-guru", "backend-architect")
        out = await handler._cmd_unregister_specialist(
            chat_id="op", args="engineering perf-guru"
        )
        assert "perf-guru" in out
        assert not store.list_for_department("engineering")

    async def test_unregister_command_usage_on_missing_args(
        self, handler: CommandHandler
    ) -> None:
        out = await handler._cmd_unregister_specialist(
            chat_id="op", args="engineering"
        )
        assert "Usage" in out

    async def test_unregister_when_absent_empty_state(
        self, handler: CommandHandler
    ) -> None:
        out = await handler._cmd_unregister_specialist(
            chat_id="op", args="engineering ghost"
        )
        assert "ghost" in out
        assert "not registered" in out.lower()

    async def test_unregister_command_no_store(self) -> None:
        h = CommandHandler.__new__(CommandHandler)
        h._roster_registry = None
        h._autonomy = None
        out = await h._cmd_unregister_specialist(
            chat_id="op", args="engineering perf-guru"
        )
        assert "not" in out.lower()


# ---------------------------------------------------------------------------
# Listing
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestRosterCommand:
    async def test_roster_command_registered(self) -> None:
        from bridge.commands import BRIDGE_COMMANDS

        assert "roster" in BRIDGE_COMMANDS

    async def test_roster_command_lists(
        self, handler: CommandHandler, store: RosterRegistryStore
    ) -> None:
        store.register("engineering", "perf-guru", "backend-architect")
        store.register("qa", "fuzz-hunter", "qa-engineer")
        out = await handler._cmd_roster(chat_id="op", args="")
        assert "perf-guru" in out
        assert "fuzz-hunter" in out
        assert "engineering" in out
        assert "qa" in out

    async def test_roster_command_filters_by_department(
        self, handler: CommandHandler, store: RosterRegistryStore
    ) -> None:
        store.register("engineering", "perf-guru", "backend-architect")
        store.register("qa", "fuzz-hunter", "qa-engineer")
        out = await handler._cmd_roster(chat_id="op", args="engineering")
        assert "perf-guru" in out
        assert "fuzz-hunter" not in out

    async def test_roster_command_empty_state(
        self, handler: CommandHandler
    ) -> None:
        out = await handler._cmd_roster(chat_id="op", args="")
        assert "No" in out or "no" in out

    async def test_roster_command_empty_state_for_department(
        self, handler: CommandHandler
    ) -> None:
        out = await handler._cmd_roster(chat_id="op", args="engineering")
        assert "engineering" in out
        assert "No" in out or "no" in out

    async def test_roster_command_no_store(self) -> None:
        h = CommandHandler.__new__(CommandHandler)
        h._roster_registry = None
        h._autonomy = None
        out = await h._cmd_roster(chat_id="op", args="")
        assert "not" in out.lower()
