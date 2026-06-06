"""Tests for RR.2 (#2593) — registry overlay in roster_from_department_config
plus the cache-invalidation seam (the spec's #1-risk).

The chief's Roster is YAML-derived; RR.2 appends operator-registered specialists
(the overlay) at roster-build time, resolving each ``agent_ref`` to the same
employee config the YAML path uses. The load-bearing seam: the chief agent is
``AgentCache``-keyed on ``(team, agent)`` only, so a registration is invisible
until the team's cached chief is invalidated — register/unregister fire
``on_change`` → ``AgentCache.invalidate`` to force a rebuild.
"""

from __future__ import annotations

from dataclasses import dataclass

from teams._agent_cache import AgentCache
from teams._factory import build_manager_agent, roster_from_department_config
from teams._types import AgentSpec, DepartmentConfig


@dataclass(frozen=True)
class _Reg:
    """Minimal RegisteredSpecialist stand-in (duck-typed: department/name/agent_ref)."""

    department: str
    name: str
    agent_ref: str
    registered_at: str = "2026-06-03T00:00:00+00:00"
    registered_by: str = "operator"


def _config() -> DepartmentConfig:
    return DepartmentConfig(
        name="engineering",
        zone=4,
        description="Engineering department",
        manager=AgentSpec(
            name="engineering-chief",
            model="anthropic:claude-sonnet-4-6",
            role="Orchestrates engineering",
        ),
        employees=(
            AgentSpec(
                name="backend-architect",
                model="anthropic:claude-sonnet-4-6",
                role="Backend design",
            ),
            AgentSpec(
                name="performance-engineer",
                model="anthropic:claude-sonnet-4-6",
                role="Perf tuning",
            ),
        ),
    )


# ── overlay merge ───────────────────────────────────────────────────────────


class TestRosterOverlay:
    def test_overlay_empty_is_identical_to_yaml(self):
        cfg = _config()
        base = roster_from_department_config(cfg)
        overlaid = roster_from_department_config(cfg, registered=())
        assert overlaid.names() == base.names()
        assert overlaid.specialists == base.specialists

    def test_overlay_appends_registered(self):
        cfg = _config()
        reg = (_Reg("engineering", "perf-2", "performance-engineer"),)
        roster = roster_from_department_config(cfg, registered=reg)
        assert "perf-2" in roster.names()
        spec = roster.get("perf-2")
        # inherits the referenced employee's role/expertise, operator-chosen name
        assert spec is not None
        assert spec.role == "Perf tuning"

    def test_overlay_preserves_yaml_order_builtins_first(self):
        cfg = _config()
        reg = (_Reg("engineering", "perf-2", "performance-engineer"),)
        roster = roster_from_department_config(cfg, registered=reg)
        # YAML built-ins keep their order and position; registered appended after
        assert roster.names() == ("backend-architect", "performance-engineer", "perf-2")

    def test_overlay_builtin_wins_on_collision(self):
        cfg = _config()
        # A registered entry whose name shadows a built-in is skipped (registration
        # rejects this at write time; this is belt-and-suspenders).
        reg = (_Reg("engineering", "backend-architect", "performance-engineer"),)
        roster = roster_from_department_config(cfg, registered=reg)
        # still exactly the two built-ins, no duplicate
        assert roster.names() == ("backend-architect", "performance-engineer")

    def test_overlay_unresolvable_agent_ref_skipped(self):
        cfg = _config()
        reg = (_Reg("engineering", "ghost", "no-such-agent"),)
        roster = roster_from_department_config(cfg, registered=reg)
        assert "ghost" not in roster.names()
        assert roster.names() == ("backend-architect", "performance-engineer")


# ── cache-invalidation seam (the #1-risk) ────────────────────────────────────


class TestCacheInvalidationSeam:
    def test_register_invalidates_cache_and_rebuild_shows_specialist(self):
        """Without invalidation a registration is invisible (stale cached chief).
        With on_change → AgentCache.invalidate, the next build shows it.
        """
        cfg = _config()
        cache = AgentCache()

        # An overlay store stand-in: holds registrations + invalidates the cache
        # on write (exactly how RosterRegistryStore.on_change is wired in prod).
        overlay: list[_Reg] = []

        def register(reg: _Reg) -> None:
            overlay.append(reg)
            cache.invalidate(reg.department)  # the on_change wire

        def current_overlay() -> tuple[_Reg, ...]:
            return tuple(overlay)

        # First build: no registrations → roster is YAML base only.
        m1 = build_manager_agent(
            cfg, {}, agent_cache=cache, registered=current_overlay()
        )
        # Cache hit returns the SAME instance for the same overlay.
        m1b = build_manager_agent(
            cfg, {}, agent_cache=cache, registered=current_overlay()
        )
        assert m1 is m1b  # cached

        # Register a specialist — fires invalidation.
        register(_Reg("engineering", "perf-2", "performance-engineer"))

        # Next build rebuilds (cache was invalidated) and the roster reflects it.
        m2 = build_manager_agent(
            cfg, {}, agent_cache=cache, registered=current_overlay()
        )
        assert m2 is not m1  # rebuilt, not the stale cached instance
        roster = roster_from_department_config(cfg, registered=current_overlay())
        assert "perf-2" in roster.names()

    def test_without_invalidation_cache_is_stale(self):
        """Control: prove the seam matters — no invalidation = stale roster.

        Same registration but WITHOUT calling cache.invalidate returns the
        cached chief, so a fresh roster build is the only way to see the
        change. This documents why on_change is load-bearing.
        """
        cfg = _config()
        cache = AgentCache()
        m1 = build_manager_agent(cfg, {}, agent_cache=cache, registered=())
        # Register but do NOT invalidate.
        m2 = build_manager_agent(cfg, {}, agent_cache=cache, registered=())
        assert m1 is m2  # stale cached instance — exactly what invalidation fixes
