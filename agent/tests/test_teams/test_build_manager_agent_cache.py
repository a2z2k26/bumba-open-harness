"""Tests for `build_manager_agent` cache-aware behavior (Sprint A.02 #2291).

A.01 (#2290) shipped the ``AgentCache`` primitive in isolation. This sprint
wires ``build_manager_agent`` to consult ``GLOBAL_AGENT_CACHE`` (or a test-
injected cache) so repeat calls for the same ``(team_name, chief_name)``
return the SAME ``Agent`` instance.

Behavior is byte-identical to pre-cache: same system prompt, same tools,
same model resolution. The cache only avoids re-running the construction
body. These tests pin that contract.
"""

from __future__ import annotations

import time

from teams._agent_cache import GLOBAL_AGENT_CACHE, AgentCache
from teams._factory import build_employee_agents, build_manager_agent
from teams._types import AgentSpec, DepartmentConfig


def _make_config(name: str, chief_name: str | None = None) -> DepartmentConfig:
    """Build a minimal DepartmentConfig for cache tests.

    Two specialists is enough to exercise the roster + delegate tool
    construction path; tests here do not run the agent — only build it.
    """
    return DepartmentConfig(
        name=name,
        zone=4,
        description=f"{name} department for cache tests",
        manager=AgentSpec(
            name=chief_name or f"{name}-chief",
            model="anthropic:claude-opus-4-6",
            role=f"Orchestrates {name} work",
        ),
        employees=(
            AgentSpec(
                name=f"{name}-worker-a",
                model="anthropic:claude-sonnet-4-6",
                role="First specialist",
            ),
            AgentSpec(
                name=f"{name}-worker-b",
                model="anthropic:claude-sonnet-4-6",
                role="Second specialist",
            ),
        ),
    )


def test_two_calls_same_config_return_same_agent_instance():
    """Cache hit: same (team, chief) → same Agent object."""
    cache = AgentCache()  # isolated, not the global
    config = _make_config("board")
    employees = build_employee_agents(config)

    a1 = build_manager_agent(config, employees, agent_cache=cache)
    a2 = build_manager_agent(config, employees, agent_cache=cache)
    assert a1 is a2


def test_two_calls_different_teams_return_distinct_agents():
    """Cache miss on different team → distinct Agent objects."""
    cache = AgentCache()
    board_cfg = _make_config("board")
    design_cfg = _make_config("design")

    a_board = build_manager_agent(
        board_cfg, build_employee_agents(board_cfg), agent_cache=cache
    )
    a_design = build_manager_agent(
        design_cfg, build_employee_agents(design_cfg), agent_cache=cache
    )
    assert a_board is not a_design


def test_cached_chief_has_same_system_prompt_as_fresh_build():
    """Regression guard: caching MUST NOT alter the system prompt content.

    Two isolated caches build the same config twice. Within a cache, the
    second call returns the cached instance. Across caches, the two Agents
    are distinct objects but their ``_system_prompts`` tuples are byte-
    identical because the construction body is unchanged.
    """
    cache_a = AgentCache()
    cache_b = AgentCache()
    config = _make_config("strategy")
    employees = build_employee_agents(config)

    cached = build_manager_agent(config, employees, agent_cache=cache_a)
    cached_again = build_manager_agent(config, employees, agent_cache=cache_a)
    fresh = build_manager_agent(config, employees, agent_cache=cache_b)

    # Same-cache → same instance.
    assert cached is cached_again
    # Different-cache → different instance, identical prompt content.
    assert cached is not fresh
    # PydanticAI stores the constructor-passed system_prompt on
    # ``_system_prompts`` (verified against pydantic-ai 1.0.x).
    assert cached._system_prompts == fresh._system_prompts


def test_invalidate_team_forces_rebuild_on_next_call():
    """Explicit invalidation evicts the cached chief; next call rebuilds."""
    cache = AgentCache()
    config = _make_config("board")
    employees = build_employee_agents(config)

    a1 = build_manager_agent(config, employees, agent_cache=cache)
    evicted = cache.invalidate("board")
    assert evicted == 1
    a2 = build_manager_agent(config, employees, agent_cache=cache)
    assert a1 is not a2


def test_default_agent_cache_is_global_singleton():
    """No ``agent_cache`` arg → routes through ``GLOBAL_AGENT_CACHE``.

    The autouse fixture in conftest invalidates the global cache before
    this test runs, so the first call here is a guaranteed cold miss.
    """
    # Defensive: the autouse fixture clears the global cache, but be
    # explicit here so this test is robust to fixture reordering.
    GLOBAL_AGENT_CACHE.invalidate_all()

    config = _make_config("ops")
    employees = build_employee_agents(config)

    a1 = build_manager_agent(config, employees)
    a2 = build_manager_agent(config, employees)

    assert a1 is a2
    assert GLOBAL_AGENT_CACHE.stats().size >= 1


def test_cache_hit_is_observably_faster_than_cold_build():
    """Timing check: ``second build < first build * 0.5``.

    The first call pays system-prompt assembly + tool registration. The
    second call returns the cached instance via a single dict lookup.
    A 0.5x ceiling is generous; cache-hit is typically <1% of cold-build.
    """
    cache = AgentCache()
    config = _make_config("qa")
    employees = build_employee_agents(config)

    t0 = time.monotonic()
    build_manager_agent(config, employees, agent_cache=cache)
    t_first = time.monotonic() - t0

    t0 = time.monotonic()
    build_manager_agent(config, employees, agent_cache=cache)
    t_second = time.monotonic() - t0

    assert t_second < t_first * 0.5, (
        f"Cache hit should be measurably faster: "
        f"first={t_first * 1000:.2f}ms second={t_second * 1000:.2f}ms"
    )
