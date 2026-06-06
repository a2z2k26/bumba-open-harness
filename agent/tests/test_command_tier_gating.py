"""Tests for #1071 Part 2 — slash-command tier classification + flag gating.

Tier 1 + Tier 2 are always present in BRIDGE_COMMANDS. Tier 3 entries
register only when opted in via the `[commands]` toml table. Disabled
Tier 3 commands return a friendly hint when invoked rather than the
generic "Unknown command".
"""
from __future__ import annotations

from pathlib import Path

import pytest

from bridge.commands import (
    BRIDGE_COMMANDS,
    CommandHandler,
    _TIER_1_ESSENTIAL,
    _TIER_2_ALWAYS,
    _TIER_2_Z3,
    _TIER_2_Z4,
    _TIER_3_POWER_USER,
    apply_command_tier_gating,
    load_commands_section,
)


def _bare_handler() -> CommandHandler:
    import time

    h = CommandHandler.__new__(CommandHandler)
    h._departments = None
    h._start_time = time.monotonic()
    return h


@pytest.fixture(autouse=True)
def _reset_bridge_commands():
    """Each test starts from the default tier-gated state and is restored."""
    snapshot = set(BRIDGE_COMMANDS)
    apply_command_tier_gating(None)
    yield
    BRIDGE_COMMANDS.clear()
    BRIDGE_COMMANDS.update(snapshot)


class TestTierStructure:
    def test_tiers_are_disjoint(self) -> None:
        # Apart from `board` (in Tier 2 because it's a per-department
        # command but already had a hand-written handler), tiers must
        # not overlap or the gating logic gets ambiguous.
        assert _TIER_1_ESSENTIAL.isdisjoint(_TIER_3_POWER_USER)
        assert _TIER_2_Z4.isdisjoint(_TIER_3_POWER_USER)
        assert _TIER_2_Z3.isdisjoint(_TIER_3_POWER_USER)
        assert _TIER_1_ESSENTIAL.isdisjoint(_TIER_2_Z4)
        assert _TIER_1_ESSENTIAL.isdisjoint(_TIER_2_Z3)
        assert _TIER_2_Z4.isdisjoint(_TIER_2_Z3)

    def test_tier_1_carries_lifecycle_essentials(self) -> None:
        # If the operator can't /halt, /resume, /restart, /status, /log,
        # the bridge is unmanageable. These are non-negotiable.
        for required in {
            "ping", "status", "halt", "resume", "restart", "log",
            "queue", "health", "cost",
        }:
            assert required in _TIER_1_ESSENTIAL

    def test_tier_2_carries_phase5_lifecycle(self) -> None:
        # Phase 5 directive/task/surface lifecycle must stay always-on
        # for the 7-day PoOL soak.
        for required in {
            "directives", "direct", "surfaces", "ack", "z4_tasks",
            "departments", "route", "handoff",
        }:
            assert required in _TIER_2_Z4

    def test_engineering_is_zone3_shortcut_not_z4_department(self) -> None:
        assert "engineering" in _TIER_2_Z3
        assert "engineering" not in _TIER_2_Z4
        assert "engineering" in BRIDGE_COMMANDS

    def test_tier_3_carries_power_user_scaffolds(self) -> None:
        # Sample of commands that should be flag-gated (operator
        # autocomplete clutter when always-on).
        # NOTE: ``skills`` was promoted to Tier 2 in Sprint 4.04 / #2151
        # (per-agent SkillAllocator discovery is now an operational need).
        for required in {
            "spawn", "agents", "kill_agent",
            "digest", "proposals",
            "trace", "events", "edits",
        }:
            assert required in _TIER_3_POWER_USER


class TestApplyTierGating:
    def test_default_state_is_tier_1_plus_tier_2(self) -> None:
        apply_command_tier_gating(None)
        assert BRIDGE_COMMANDS == set(_TIER_1_ESSENTIAL) | set(_TIER_2_ALWAYS)

    def test_empty_dict_same_as_none(self) -> None:
        apply_command_tier_gating({})
        assert BRIDGE_COMMANDS == set(_TIER_1_ESSENTIAL) | set(_TIER_2_ALWAYS)

    def test_individual_opt_in(self) -> None:
        apply_command_tier_gating({"spawn": True, "trace": True})
        assert "spawn" in BRIDGE_COMMANDS
        assert "trace" in BRIDGE_COMMANDS
        # Other Tier 3 commands stay off
        assert "events" not in BRIDGE_COMMANDS
        assert "digest" not in BRIDGE_COMMANDS
        # Tier 1/2 unaffected
        assert "status" in BRIDGE_COMMANDS
        assert "directives" in BRIDGE_COMMANDS

    def test_all_shortcut_enables_every_tier_3(self) -> None:
        apply_command_tier_gating({"all": True})
        for cmd in _TIER_3_POWER_USER:
            assert cmd in BRIDGE_COMMANDS, f"{cmd} missing under all=true"

    def test_all_false_keeps_tier_3_off(self) -> None:
        apply_command_tier_gating({"all": False, "spawn": True})
        # all=False is not equivalent to enabling — but individual
        # opt-ins still work. Spawn is on, others stay off.
        assert "spawn" in BRIDGE_COMMANDS
        assert "trace" not in BRIDGE_COMMANDS

    def test_unknown_keys_silently_ignored(self) -> None:
        apply_command_tier_gating({"frobnicate": True, "spawn": True})
        assert "spawn" in BRIDGE_COMMANDS
        assert "frobnicate" not in BRIDGE_COMMANDS

    def test_tier_1_cannot_be_disabled(self) -> None:
        # Even an explicit `status = false` does nothing — Tier 1 is
        # immutable. (The gating logic only adds; never removes from
        # the always-on tiers.)
        apply_command_tier_gating({"status": False, "halt": False})
        assert "status" in BRIDGE_COMMANDS
        assert "halt" in BRIDGE_COMMANDS

    def test_falsy_value_skips_command(self) -> None:
        apply_command_tier_gating({"spawn": False})
        assert "spawn" not in BRIDGE_COMMANDS

    def test_idempotent_repeated_calls(self) -> None:
        apply_command_tier_gating({"spawn": True})
        first = set(BRIDGE_COMMANDS)
        apply_command_tier_gating({"spawn": True})
        assert BRIDGE_COMMANDS == first


class TestLoadCommandsSection:
    def test_missing_file_returns_empty(self, tmp_path: Path) -> None:
        section = load_commands_section(tmp_path / "does-not-exist.toml")
        assert section == {}

    def test_section_present(self, tmp_path: Path) -> None:
        toml = tmp_path / "bridge.toml"
        toml.write_text(
            "[commands]\n"
            "spawn = true\n"
            "trace = true\n"
            'all = false\n'
        )
        section = load_commands_section(toml)
        assert section == {"spawn": True, "trace": True, "all": False}

    def test_section_missing_returns_empty(self, tmp_path: Path) -> None:
        toml = tmp_path / "bridge.toml"
        toml.write_text("[bridge]\ndata_dir = \"/tmp/x\"\n")
        section = load_commands_section(toml)
        assert section == {}

    def test_malformed_toml_returns_empty(self, tmp_path: Path) -> None:
        toml = tmp_path / "bridge.toml"
        toml.write_text("[commands\nspawn = true\n")  # missing ]
        section = load_commands_section(toml)
        assert section == {}


class TestHandleFriendlyHint:
    @pytest.mark.asyncio
    async def test_disabled_tier_3_returns_hint(self) -> None:
        apply_command_tier_gating(None)  # spawn is off
        h = _bare_handler()
        out = await h.handle("op", "spawn", "")
        assert "disabled by default" in out
        assert "[commands]" in out
        assert "spawn = true" in out

    @pytest.mark.asyncio
    async def test_enabled_tier_3_dispatches(self) -> None:
        apply_command_tier_gating({"spawn": True})
        h = _bare_handler()
        # _cmd_spawn exists on the class; we just need to confirm
        # handle() routes there instead of returning the hint. We
        # don't care about the actual output (it'll error on missing
        # state), only that we don't see the hint message.
        try:
            out = await h.handle("op", "spawn", "")
        except Exception:
            return  # routing reached the handler — that's the proof
        assert "disabled by default" not in out

    @pytest.mark.asyncio
    async def test_unknown_command_still_unknown(self) -> None:
        apply_command_tier_gating(None)
        h = _bare_handler()
        out = await h.handle("op", "frobnicate", "")
        assert "Unknown command" in out

    @pytest.mark.asyncio
    async def test_tier_1_unaffected_by_gating(self) -> None:
        apply_command_tier_gating(None)
        h = _bare_handler()
        out = await h.handle("op", "ping", "")
        assert "pong" in out


class TestEngineeringStaysZone3:
    """Z3-03 regression: engineering must never reach the Zone 4 registry."""

    def test_engineering_absent_from_zone4_department_registry(self) -> None:
        from teams._registry import DepartmentRegistry

        teams_dir = Path(__file__).resolve().parents[1] / "config" / "teams"
        registry = DepartmentRegistry.from_directory(teams_dir)
        assert "engineering" not in registry.department_names()

    @pytest.mark.asyncio
    async def test_readiness_short_circuits_without_dispatcher(self) -> None:
        # No _dispatcher set; readiness must still return a roster (not the
        # WorkOrder dispatch fallback), proving zero Claude spawn.
        h = _bare_handler()
        h._dispatcher = None
        out = await h.handle("op", "engineering", "ready to work?")
        assert "engineering-chief" in out
        assert "Zone 3" in out

    @pytest.mark.asyncio
    async def test_cross_zone_handoff_short_circuits(self) -> None:
        h = _bare_handler()
        h._dispatcher = None
        out = await h.handle("op", "engineering", "verify this needs broader QA coverage")
        assert "handoff" in out.lower()
        assert "qa" in out.lower()
