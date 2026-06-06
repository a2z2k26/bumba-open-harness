"""Tests for run_parallel() partial-failure handling in DepartmentTeam and DepartmentRegistry."""

from __future__ import annotations

import unittest.mock as mock

import pytest
from pydantic_ai.models.test import TestModel

from teams._registry import DepartmentRegistry
from teams._team import DepartmentTeam
from tests.test_teams.conftest import make_deps
from teams._types import AgentSpec, BridgeDeps, DepartmentConfig, TeamResult


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def config() -> DepartmentConfig:
    return DepartmentConfig(
        name="qa",
        zone=4,
        description="QA department",
        manager=AgentSpec(name="qa-chief", model="anthropic:claude-opus-4-6"),
        employees=(
            AgentSpec(name="qa-engineer", model="anthropic:claude-sonnet-4-6"),
        ),
    )


@pytest.fixture
def deps() -> BridgeDeps:
    return make_deps(session_id="s-parallel", department="qa")


@pytest.fixture
def team(config: DepartmentConfig) -> DepartmentTeam:
    return DepartmentTeam(config=config, lazy_build=False)


@pytest.fixture
def registry(config: DepartmentConfig) -> DepartmentRegistry:
    return DepartmentRegistry(configs={"qa": config})


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _make_success_result(department: str, idx: int) -> TeamResult:
    return TeamResult(
        department=department,
        manager_output=f"task-{idx} done",
        success=True,
    )


# ---------------------------------------------------------------------------
# 1. All tasks succeed
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_all_succeed(team: DepartmentTeam, deps: BridgeDeps) -> None:
    """Three tasks all return success=True."""
    tasks = ["task-0", "task-1", "task-2"]
    side_effects = [_make_success_result("qa", i) for i in range(3)]

    with mock.patch.object(team, "run", side_effect=side_effects):
        results = await team.run_parallel(tasks, deps=deps)

    assert len(results) == 3
    assert all(r.success for r in results)
    assert all(r.department == "qa" for r in results)


# ---------------------------------------------------------------------------
# 2. One task fails, others succeed
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_one_fails_others_succeed(team: DepartmentTeam, deps: BridgeDeps) -> None:
    """One subtask raises; the batch must not raise and returns 2 success + 1 failure."""

    call_count = 0

    async def _run(task: str, deps=None) -> TeamResult:
        nonlocal call_count
        idx = call_count
        call_count += 1
        if idx == 1:
            raise RuntimeError("simulated model crash")
        return _make_success_result("qa", idx)

    with mock.patch.object(team, "run", side_effect=_run):
        results = await team.run_parallel(["t0", "t1", "t2"], deps=deps)

    assert len(results) == 3
    successes = [r for r in results if r.success]
    failures = [r for r in results if not r.success]
    assert len(successes) == 2
    assert len(failures) == 1
    assert "simulated model crash" in failures[0].error


# ---------------------------------------------------------------------------
# 3. All tasks fail
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_all_fail(team: DepartmentTeam, deps: BridgeDeps) -> None:
    """All subtasks raise; no exception propagates and all results have success=False."""

    async def _always_fail(task: str, deps=None) -> TeamResult:
        raise ValueError(f"boom for {task}")

    with mock.patch.object(team, "run", side_effect=_always_fail):
        results = await team.run_parallel(["a", "b", "c"], deps=deps)

    assert len(results) == 3
    assert all(not r.success for r in results)
    assert all(r.error is not None for r in results)


# ---------------------------------------------------------------------------
# 4. Results are ordered identically to input tasks
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_results_ordered(team: DepartmentTeam, deps: BridgeDeps) -> None:
    """Results must be returned in the same order as the input task list."""
    import asyncio

    tasks = [f"task-{i}" for i in range(5)]

    async def _run_with_delay(task: str, deps=None) -> TeamResult:
        # Reverse the natural completion order: task-0 is slowest
        idx = int(task.split("-")[1])
        await asyncio.sleep((4 - idx) * 0.01)
        return TeamResult(department="qa", manager_output=task, success=True)

    with mock.patch.object(team, "run", side_effect=_run_with_delay):
        results = await team.run_parallel(tasks, deps=deps)

    assert [r.manager_output for r in results] == tasks


# ---------------------------------------------------------------------------
# 5. DepartmentRegistry.run_parallel end-to-end
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_registry_run_parallel(
    registry: DepartmentRegistry,
    config: DepartmentConfig,
    deps: BridgeDeps,
) -> None:
    """Call registry.run_parallel('qa', [...]) with TestModel end-to-end."""
    team = registry.get_team("qa")

    test_model = TestModel(custom_output_args={"answer": "registry result"}, call_tools=[])
    with team.manager.override(model=test_model):
        results = await registry.run_parallel("qa", ["check A", "check B"], deps=deps)

    assert len(results) == 2
    assert all(r.success for r in results)
    assert all(r.department == "qa" for r in results)
    assert all("registry result" in r.manager_output for r in results)


# ---------------------------------------------------------------------------
# 6. Empty task list returns empty list
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_empty_tasks(team: DepartmentTeam, deps: BridgeDeps) -> None:
    """Empty task list must return an empty list without raising."""
    results = await team.run_parallel([], deps=deps)
    assert results == []
