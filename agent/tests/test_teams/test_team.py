"""Tests for teams._team.DepartmentTeam."""

from __future__ import annotations

import asyncio
import unittest.mock as mock

import pytest
from pydantic_ai.models.test import TestModel

from teams._circuit import CircuitState, get_registry
from teams._team import DepartmentTeam
from tests.test_teams.conftest import make_deps
from teams._types import (
    AgentSpec,
    BridgeDeps,
    Constraints,
    DepartmentConfig,
    EmployeeResult,
)


@pytest.fixture
def config() -> DepartmentConfig:
    return DepartmentConfig(
        name="qa",
        zone=4,
        description="QA",
        manager=AgentSpec(name="qa-chief", model="anthropic:claude-opus-4-6"),
        employees=(
            AgentSpec(name="qa-engineer", model="anthropic:claude-sonnet-4-6"),
        ),
    )


@pytest.fixture
def deps() -> BridgeDeps:
    return make_deps(session_id="s1", department="qa")


@pytest.mark.asyncio
async def test_team_run_returns_team_result(config, deps):
    team = DepartmentTeam(config=config, lazy_build=False)

    # call_tools=[] prevents the manager from invoking employee delegation tools,
    # which would try to use the real Anthropic API (override does not propagate
    # into nested agent.run() calls per pydantic-ai 1.80.0 behaviour).
    test_model = TestModel(custom_output_args={"answer": "QA complete"}, call_tools=[])
    with team.manager.override(model=test_model):
        result = await team.run("Review module", deps=deps)

    assert result.department == "qa"
    assert result.success is True
    assert "QA complete" in result.manager_output
    assert result.error is None


@pytest.mark.asyncio
async def test_team_run_catches_exceptions(config, deps):
    team = DepartmentTeam(config=config, lazy_build=False)

    import unittest.mock as mock

    async def failing_run(*args, **kwargs):
        raise RuntimeError("simulated model failure")

    with mock.patch.object(team.manager, "run", side_effect=failing_run):
        result = await team.run("task", deps=deps)

    assert result.success is False
    assert result.error is not None
    assert "RuntimeError" in result.error or "simulated" in result.error


@pytest.mark.asyncio
async def test_team_respects_timeout(config, deps):
    # Shrink the timeout via constraints
    tight_config = DepartmentConfig(
        name=config.name,
        zone=config.zone,
        description=config.description,
        manager=config.manager,
        employees=config.employees,
        constraints=Constraints(timeout_seconds=1),
    )
    team = DepartmentTeam(config=tight_config, lazy_build=False)

    import asyncio
    import unittest.mock as mock

    async def slow_run(*args, **kwargs):
        await asyncio.sleep(5)
        return mock.MagicMock(output="too late")

    with mock.patch.object(team.manager, "run", side_effect=slow_run):
        result = await team.run("task", deps=deps)

    assert result.success is False
    assert "timeout" in (result.error or "").lower()


@pytest.mark.asyncio
async def test_team_timeout_reports_partial_specialist_progress(config, deps):
    """Timeout errors should distinguish pre-delegation from partial progress."""
    tight_config = DepartmentConfig(
        name=config.name,
        zone=config.zone,
        description=config.description,
        manager=config.manager,
        employees=config.employees,
        constraints=Constraints(timeout_seconds=1),
    )
    team = DepartmentTeam(config=tight_config, lazy_build=False)

    async def slow_run(*args, **kwargs):
        run_deps = kwargs["deps"]
        run_deps.employee_results_collector.append(
            EmployeeResult(
                employee_name="qa-engineer",
                output="partial",
                success=True,
                duration_seconds=0.2,
            )
        )
        run_deps.employee_results_collector.append(
            EmployeeResult(
                employee_name="security-auditor",
                output="",
                success=False,
                error="bandit unavailable",
                duration_seconds=0.1,
            )
        )
        await asyncio.sleep(5)

    with mock.patch.object(team.manager, "run", side_effect=slow_run):
        result = await team.run("task", deps=deps)

    assert result.success is False
    assert result.employee_results[0].employee_name == "qa-engineer"
    assert "partial_specialists=2" in (result.error or "")
    assert "successful=1" in (result.error or "")
    assert "failed=1" in (result.error or "")
    assert "last_failure=security-auditor: bandit unavailable" in (result.error or "")


def test_team_lazy_build(config):
    team = DepartmentTeam(config=config, lazy_build=True)
    # Manager and employees should not be built yet
    assert team._manager is None
    assert team._employees is None

    # Accessing .manager triggers build
    _ = team.manager
    assert team._manager is not None
    assert team._employees is not None


# ---------------------------------------------------------------------------
# Circuit breaker integration tests
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _reset_circuit_registry():
    """Reset the module-level circuit breaker registry before each test."""
    get_registry().reset_all()
    yield
    get_registry().reset_all()


@pytest.mark.asyncio
async def test_circuit_opens_after_consecutive_failures(config, deps):
    """3 failures should open the circuit; the 4th call returns circuit-open TeamResult."""
    team = DepartmentTeam(config=config, lazy_build=False)

    async def failing_run(*args, **kwargs):
        raise RuntimeError("simulated failure")

    with mock.patch.object(team.manager, "run", side_effect=failing_run):
        # Trigger 3 failures (default threshold)
        for _ in range(3):
            result = await team.run("task", deps=deps)
            assert result.success is False

    # Circuit should now be OPEN
    breaker = get_registry().get(config.name)
    assert breaker.state == CircuitState.OPEN

    # 4th call should be fast-failed by the circuit breaker without
    # touching the manager at all
    result = await team.run("task", deps=deps)
    assert result.success is False
    assert "circuit open" in result.error


@pytest.mark.asyncio
async def test_circuit_half_open_recovers_on_success(config, deps):
    """After cooldown (HALF_OPEN), a successful call closes the circuit."""
    team = DepartmentTeam(config=config, lazy_build=False)

    # Force the breaker into HALF_OPEN state
    breaker = get_registry().get(config.name)
    breaker._state = CircuitState.HALF_OPEN

    test_model = TestModel(custom_output_args={"answer": "recovered"}, call_tools=[])
    with team.manager.override(model=test_model):
        result = await team.run("task", deps=deps)

    assert result.success is True
    assert breaker.state == CircuitState.CLOSED
    assert breaker._consecutive_failures == 0


# ---------------------------------------------------------------------------
# Sprint audit-2026-05-16.D.05 (#2066) — chief_session_id attribution
#
# The audit M-2 finding is that team-originated cost entries don't carry
# ``chief_session_id``. The team's cost-record call must thread it through
# so ``CostTracker.last_session_measurement(chief_session_id)`` returns a
# populated value (which D.04's strict-mode budget gate consults).
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_team_records_cost_with_chief_session_id(config, tmp_path):
    """When the team is constructed with ``chief_session_id``, the
    cost-record call attributes the entry to that ChiefSession id."""
    from bridge.cost_tracker import CostTracker

    cost_tracker = CostTracker(data_dir=tmp_path)
    deps = make_deps(
        session_id="op-session-1",
        department="qa",
        cost_tracker=cost_tracker,
    )

    team = DepartmentTeam(
        config=config,
        lazy_build=False,
        chief_session_id="cs-d05-attribution",
    )

    test_model = TestModel(custom_output_args={"answer": "ok"}, call_tools=[])
    with team.manager.override(model=test_model):
        result = await team.run("Review module", deps=deps)

    assert result.success is True
    # The team's cost-record call wrote one entry to the real tracker.
    entries = cost_tracker._read_entries()
    assert len(entries) == 1
    latest = entries[-1]
    assert latest.chief_session_id == "cs-d05-attribution"
    assert latest.team == config.name
    assert latest.task_type == "team_run"
    # The accessor D.04 reads against now sees the attributed entry.
    measurement = cost_tracker.last_session_measurement("cs-d05-attribution")
    assert measurement is not None
    assert measurement.source == "measured"


@pytest.mark.asyncio
async def test_team_default_chief_session_id_is_empty(config, tmp_path):
    """Constructing the team without ``chief_session_id`` (legacy path)
    leaves the field empty on the recorded entry — the un-attributed bucket
    used by call sites outside the dispatcher path."""
    from bridge.cost_tracker import CostTracker

    cost_tracker = CostTracker(data_dir=tmp_path)
    deps = make_deps(
        session_id="op-session-2",
        department="qa",
        cost_tracker=cost_tracker,
    )

    team = DepartmentTeam(config=config, lazy_build=False)

    test_model = TestModel(custom_output_args={"answer": "ok"}, call_tools=[])
    with team.manager.override(model=test_model):
        result = await team.run("Review module", deps=deps)

    assert result.success is True
    entries = cost_tracker._read_entries()
    assert len(entries) == 1
    assert entries[-1].chief_session_id == ""


# ---------------------------------------------------------------------------
# WS3.2 (#2570) — workflow attribution on the team_run row
#
# The workflow department path already records its spend on the team_run row
# (via the ct.record call below). WS3.2 only TAGS that existing row with the
# workflow name carried on deps.workflow — it must NOT add a second row, or
# the daily total would double-count the same route() call's tokens.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_team_run_row_carries_workflow_tag(config, tmp_path):
    """When deps.workflow is set, the team_run cost row carries that tag."""
    from bridge.cost_tracker import CostTracker

    cost_tracker = CostTracker(data_dir=tmp_path)
    deps = make_deps(
        session_id="op-session-wf",
        department="qa",
        cost_tracker=cost_tracker,
        workflow="wf-x",
    )

    team = DepartmentTeam(config=config, lazy_build=False)

    test_model = TestModel(custom_output_args={"answer": "ok"}, call_tools=[])
    with team.manager.override(model=test_model):
        result = await team.run("Review module", deps=deps)

    assert result.success is True
    entries = cost_tracker._read_entries()
    assert len(entries) == 1
    latest = entries[-1]
    assert latest.task_type == "team_run"
    assert latest.workflow == "wf-x"
    # The by-workflow aggregate (WS3.1) now sees this entry.
    by_wf = cost_tracker.get_cost_by_workflow()
    assert "wf-x" in by_wf
    assert by_wf["wf-x"]["count"] == 1


@pytest.mark.asyncio
async def test_no_second_cost_row_for_workflow_step(config, tmp_path):
    """The workflow tag rides the EXISTING team_run row — exactly one row per
    route() call. Guards against the double-count of adding a second record."""
    from bridge.cost_tracker import CostTracker

    cost_tracker = CostTracker(data_dir=tmp_path)
    deps = make_deps(
        session_id="op-session-wf2",
        department="qa",
        cost_tracker=cost_tracker,
        workflow="wf-y",
    )

    team = DepartmentTeam(config=config, lazy_build=False)

    test_model = TestModel(custom_output_args={"answer": "ok"}, call_tools=[])
    with team.manager.override(model=test_model):
        result = await team.run("Review module", deps=deps)

    assert result.success is True
    entries = cost_tracker._read_entries()
    # Exactly ONE row — the tagged team_run, no separate workflow record.
    assert len(entries) == 1
    assert entries[-1].task_type == "team_run"
    assert entries[-1].workflow == "wf-y"


@pytest.mark.asyncio
async def test_team_run_row_default_workflow_empty(config, tmp_path):
    """Legacy path (no deps.workflow) leaves the team_run row's workflow
    empty — the un-attributed bucket, excluded from get_cost_by_workflow."""
    from bridge.cost_tracker import CostTracker

    cost_tracker = CostTracker(data_dir=tmp_path)
    deps = make_deps(
        session_id="op-session-wf3",
        department="qa",
        cost_tracker=cost_tracker,
    )

    team = DepartmentTeam(config=config, lazy_build=False)

    test_model = TestModel(custom_output_args={"answer": "ok"}, call_tools=[])
    with team.manager.override(model=test_model):
        result = await team.run("Review module", deps=deps)

    assert result.success is True
    entries = cost_tracker._read_entries()
    assert len(entries) == 1
    assert entries[-1].workflow == ""
    assert cost_tracker.get_cost_by_workflow() == {}


@pytest.mark.asyncio
async def test_workflow_cost_reconciles(config, tmp_path):
    """WS3.6 (#2570) — three-way cost reconciliation invariant.

    For a workflow step, the spend recorded on the team_run cost row (the
    single ct.record(...) call inside DepartmentTeam.run) is exactly the value
    that get_cost_by_workflow() aggregates under the workflow name. Because
    WS3.2 TAGS that one existing row rather than adding a second, the workflow's
    aggregated cost equals the recorded team_run estimated_cost — no double
    count, no drift.

    This proves the bottom edge of the invariant documented in
    docs/audits/2026-06-04-ws3-cost-reconciliation.md: the same number flows
    into WorkflowRunState.cost_usd and workflow_runs.cost_usd at runtime, which
    a live mini run_id capture is the operator's confirmation step for."""
    from bridge.cost_tracker import CostTracker

    cost_tracker = CostTracker(data_dir=tmp_path)
    deps = make_deps(
        session_id="op-session-recon",
        department="qa",
        cost_tracker=cost_tracker,
        workflow="wf-recon",
    )

    team = DepartmentTeam(config=config, lazy_build=False)

    test_model = TestModel(custom_output_args={"answer": "ok"}, call_tools=[])
    with team.manager.override(model=test_model):
        result = await team.run("Review module", deps=deps)

    assert result.success is True
    entries = cost_tracker._read_entries()
    # Exactly one team_run row carries the spend (WS3.2: no double-count).
    assert len(entries) == 1
    team_run_row = entries[-1]
    assert team_run_row.task_type == "team_run"
    assert team_run_row.workflow == "wf-recon"

    # The reconciliation invariant: the by-workflow aggregate's cost for this
    # workflow equals the recorded team_run row's estimated_cost, to the same
    # 6-dp rounding get_cost_by_workflow applies.
    by_wf = cost_tracker.get_cost_by_workflow()
    assert "wf-recon" in by_wf
    assert by_wf["wf-recon"]["count"] == 1
    assert by_wf["wf-recon"]["cost"] == round(team_run_row.estimated_cost, 6)
    assert by_wf["wf-recon"]["input_tokens"] == team_run_row.input_tokens
    assert by_wf["wf-recon"]["output_tokens"] == team_run_row.output_tokens
