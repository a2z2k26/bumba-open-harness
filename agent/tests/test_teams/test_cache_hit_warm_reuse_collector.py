"""Regression test for #2313 — cached chief delegate closure capturing stale collector.

The bug: ``build_manager_agent`` caches chief Agents per (team, chief) (A.02 /
#2306). Before this fix, the chief's ``delegate`` tool closure-captured the
``employee_results_collector`` list passed at FIRST build. On every subsequent
cache-hit build (warm-reuse dispatches in production), the chief Agent returned
from cache still pointed at the FIRST team build's collector. ``DepartmentTeam.run``
reads from its own freshly-cleared collector list, so warm-reuse runs would
return an empty ``team.employee_results`` tuple — silently breaking Gate 8
(delegation floor) and chief synthesis quality.

The fix threads ``employee_results_collector`` through ``BridgeDeps`` so the
delegate tool reads it from ``ctx.deps`` at invocation time. ``DepartmentTeam.run``
constructs deps with the current run's collector on every call.

Test-suite isolation: the autouse fixture in ``conftest.py`` wipes
``GLOBAL_AGENT_CACHE`` BETWEEN tests, but NOT within a single test. So a test
that does two ``team.run`` calls inside one test body exercises exactly the
cache-hit path that production hits between warm-reuse dispatches.
"""
from __future__ import annotations

import pytest

from teams._agent_cache import GLOBAL_AGENT_CACHE
from teams._factory import build_employee_agents, build_manager_agent
from teams._team import DepartmentTeam
from teams._types import AgentSpec, Constraints, DepartmentConfig, EmployeeResult
from tests.test_teams.conftest import (
    make_chief_delegating_model,
    make_deps,
    make_specialist_text_model,
)


def _two_specialist_config() -> DepartmentConfig:
    return DepartmentConfig(
        name="cb-2313-dept",
        zone=4,
        description="warm-reuse regression dept",
        manager=AgentSpec(
            name="cb-2313-chief",
            model="anthropic:claude-opus-4-6",
            role="chief",
        ),
        employees=(
            AgentSpec(
                name="specialist-a",
                model="anthropic:claude-sonnet-4-6",
                role="a",
            ),
            AgentSpec(
                name="specialist-b",
                model="anthropic:claude-sonnet-4-6",
                role="b",
            ),
        ),
        constraints=Constraints(cost_limit_usd=1.0, timeout_seconds=60),
    )


@pytest.mark.asyncio
async def test_cache_hit_warm_reuse_populates_employee_results() -> None:
    """Regression #2313: two consecutive runs on cached chiefs must both populate results.

    This is the test that production-warmth-reuse needs and the rest of the
    suite cannot provide because conftest's autouse fixture invalidates the
    cache between every test (correct for isolation, hides this failure mode).

    Within ONE test body, the autouse fixture does NOT run, so:
      - Team A's first ``run`` builds-and-caches the chief
      - Team B (fresh instance, same config) calls ``DepartmentTeam._build()``
        which invokes ``build_manager_agent`` — that returns the CACHED chief
        from team A's build
      - Pre-fix: team B's run sees ``employee_results=()`` because the cached
        chief's ``delegate`` closure pointed at team A's collector
      - Post-fix: team B's run sees ``employee_results=(EmployeeResult(...),)``
        because the chief reads the collector from per-run deps
    """
    # Snapshot cache state before the test so this regression test is
    # robust regardless of the autouse fixture's exact ordering.
    GLOBAL_AGENT_CACHE.invalidate_all()

    config = _two_specialist_config()
    deps = make_deps(department=config.name)

    # First team — cache miss. This populates GLOBAL_AGENT_CACHE with
    # (team, chief) → chief Agent.
    team_a = DepartmentTeam(config, lazy_build=False)
    emp_model_a = make_specialist_text_model("alpha output")
    mgr_model_a = make_chief_delegating_model(
        [("specialist-a", "first run task")],
        final_answer="first synthesis",
    )
    with team_a.employees["specialist-a"].override(model=emp_model_a):
        with team_a.manager.override(model=mgr_model_a):
            result_a = await team_a.run("first run task", deps=deps)

    assert result_a.success is True, f"first run failed: {result_a.error!r}"
    assert len(result_a.employee_results) == 1, (
        "first run must populate employee_results (cache-miss build)"
    )
    assert result_a.employee_results[0].employee_name == "specialist-a"

    # Sanity check: the cache now has entries for our team. If it doesn't,
    # this whole test setup is wrong (the bug couldn't manifest at all).
    cache_stats = GLOBAL_AGENT_CACHE.stats()
    assert cache_stats.size > 0, (
        "GLOBAL_AGENT_CACHE should hold the chief Agent after first build"
    )

    # Second team — fresh DepartmentTeam instance, same config. _build()
    # calls build_manager_agent, which returns the CACHED chief from team_a.
    # The chief's ``delegate`` closure was bound at team_a's build time.
    # Pre-fix: the closure-captured collector is team_a's (now-cleared) list,
    # so team_b's run sees no results. Post-fix: deps carry team_b's collector,
    # the delegate tool reads from deps, and team_b's run populates correctly.
    team_b = DepartmentTeam(config, lazy_build=False)

    # Confirm the cache HIT actually happened — team_b should have gotten
    # the same chief Agent instance as team_a. If these are distinct objects,
    # the test is no longer exercising the bug.
    assert team_a.manager is team_b.manager, (
        "GLOBAL_AGENT_CACHE must return the SAME chief instance for team_b "
        "— if not, the cache-hit code path being tested is not active"
    )

    emp_model_b = make_specialist_text_model("beta output")
    mgr_model_b = make_chief_delegating_model(
        [("specialist-b", "second run task")],
        final_answer="second synthesis",
    )
    with team_b.employees["specialist-b"].override(model=emp_model_b):
        with team_b.manager.override(model=mgr_model_b):
            result_b = await team_b.run("second run task", deps=deps)

    # THE assertion this test exists to defend.
    assert result_b.success is True, f"second run failed: {result_b.error!r}"
    assert len(result_b.employee_results) == 1, (
        "REGRESSION #2313: cache-hit warm-reuse run returned empty "
        "employee_results. The cached chief's delegate tool is still "
        "appending to a stale closure-captured collector instead of reading "
        "from per-run deps."
    )
    assert result_b.employee_results[0].employee_name == "specialist-b"
    assert result_b.employee_results[0].output == "beta output"


@pytest.mark.asyncio
async def test_cache_hit_three_consecutive_runs_each_populate() -> None:
    """Stronger guard: 3 consecutive cache-hit runs all populate independently.

    Variations of the bug could let the first cache-hit run pass and only fail
    on the second-and-beyond. This pins all three runs to N=1 result each.
    """
    GLOBAL_AGENT_CACHE.invalidate_all()
    config = _two_specialist_config()
    deps = make_deps(department=config.name)

    expected_specialists = ["specialist-a", "specialist-b", "specialist-a"]
    expected_outputs = ["a1 output", "b2 output", "a3 output"]

    last_chief = None
    for i, (spec_name, output) in enumerate(
        zip(expected_specialists, expected_outputs, strict=True)
    ):
        team = DepartmentTeam(config, lazy_build=False)
        if last_chief is not None:
            # From run 2 onwards we MUST be hitting the cache.
            assert team.manager is last_chief, (
                f"run {i}: cache-hit expected but got a fresh chief Agent"
            )
        last_chief = team.manager

        emp_model = make_specialist_text_model(output)
        mgr_model = make_chief_delegating_model(
            [(spec_name, f"task {i}")],
            final_answer=f"synthesis {i}",
        )
        with team.employees[spec_name].override(model=emp_model):
            with team.manager.override(model=mgr_model):
                result = await team.run(f"task {i}", deps=deps)

        assert result.success is True, f"run {i} failed: {result.error!r}"
        assert len(result.employee_results) == 1, (
            f"run {i}: empty employee_results — cache-hit collector regression"
        )
        assert result.employee_results[0].employee_name == spec_name
        assert result.employee_results[0].output == output


@pytest.mark.asyncio
async def test_cache_hit_direct_manager_uses_latest_fallback_collector() -> None:
    """Direct ``manager.run`` callers without deps collectors still stay isolated.

    ``DepartmentTeam.run`` is the production path and supplies the collector on
    ``ctx.deps``. Direct factory callers rely on the fallback collector passed
    into ``build_manager_agent``. On a cache hit, that fallback must update to
    the latest direct caller's list instead of staying pinned to the cold build.
    """
    GLOBAL_AGENT_CACHE.invalidate_all()
    config = _two_specialist_config()
    employees = build_employee_agents(config)

    collector_a: list[EmployeeResult] = []
    manager_a = build_manager_agent(
        config,
        employees,
        employee_results_collector=collector_a,
    )

    collector_b: list[EmployeeResult] = []
    manager_b = build_manager_agent(
        config,
        employees,
        employee_results_collector=collector_b,
    )

    assert manager_a is manager_b, "test must exercise the cached chief path"

    deps = make_deps(department=config.name)
    emp_model = make_specialist_text_model("direct fallback output")
    mgr_model = make_chief_delegating_model(
        [("specialist-b", "direct fallback task")],
        final_answer="direct fallback synthesis",
    )
    with employees["specialist-b"].override(model=emp_model):
        with manager_b.override(model=mgr_model):
            result = await manager_b.run("direct fallback task", deps=deps)

    assert result.output.answer == "direct fallback synthesis"
    assert collector_a == []
    assert len(collector_b) == 1
    assert collector_b[0].employee_name == "specialist-b"
    assert collector_b[0].output == "direct fallback output"
