"""Tests for Z4/E-O.1 — DepartmentTeam.run emits daily log lines.

Sprint E-O.1: Every department run appends one [Z4][DEPT][OK|FAIL ...] line
to the daily log via the injected daily_log writer.
"""
from __future__ import annotations

import unittest.mock as mock

import pytest
from pydantic_ai.models.test import TestModel

from teams._team import DepartmentTeam, _emit_daily_log
from teams._types import AgentSpec, BridgeDeps, Constraints, DepartmentConfig, TeamResult
from tests.test_teams.conftest import make_deps


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
            AgentSpec(name="qa-eng-1", model="anthropic:claude-sonnet-4-6"),
            AgentSpec(name="qa-eng-2", model="anthropic:claude-sonnet-4-6"),
        ),
        constraints=Constraints(timeout_seconds=30),
    )


@pytest.fixture
def deps() -> BridgeDeps:
    return make_deps(session_id="abcdef1234567890", department="qa")


@pytest.fixture
def mock_log() -> mock.MagicMock:
    return mock.MagicMock()


# ---------------------------------------------------------------------------
# Unit tests for _emit_daily_log helper
# ---------------------------------------------------------------------------

def test_emit_daily_log_noop_when_none(config):
    """Test 1: _emit_daily_log is a no-op when daily_log is None."""
    result = TeamResult(
        department="qa",
        manager_output="done",
        success=True,
        duration_seconds=1.5,
        total_cost_usd=0.05,
    )
    # daily_log is the no-op signal — confirm the helper returns None
    # cleanly (the bool-coerced return is False) without raising.
    assert _emit_daily_log(None, config, result, "session123") is None


def test_emit_daily_log_calls_append_on_success(config, mock_log):
    """Test 2: _emit_daily_log calls daily_log.append with category='z4' on success."""
    result = TeamResult(
        department="qa",
        manager_output="done",
        success=True,
        duration_seconds=3.7,
        total_cost_usd=0.123,
        employee_results=(),
    )
    _emit_daily_log(mock_log, config, result, "abc12345")

    mock_log.append.assert_called_once()
    call_kwargs = mock_log.append.call_args
    assert call_kwargs.kwargs.get("category") == "z4"
    entry = call_kwargs.kwargs.get("entry") or call_kwargs.args[0]
    assert "[Z4]" in entry
    assert "[QA]" in entry
    assert "[OK" in entry


def test_emit_daily_log_calls_append_on_failure(config, mock_log):
    """Test 3: _emit_daily_log calls daily_log.append with FAIL on failure."""
    result = TeamResult(
        department="qa",
        manager_output="",
        success=False,
        error="Timeout after 30s",
        duration_seconds=30.0,
        total_cost_usd=0.0,
        employee_results=(),
    )
    _emit_daily_log(mock_log, config, result, "sess9999")

    mock_log.append.assert_called_once()
    call_kwargs = mock_log.append.call_args
    entry = call_kwargs.kwargs.get("entry") or call_kwargs.args[0]
    assert "[FAIL" in entry


def test_emit_daily_log_truncates_correlation_id(config, mock_log):
    """Test 4: correlation_id is passed as first 8 chars of session_id."""
    result = TeamResult(
        department="qa",
        manager_output="ok",
        success=True,
        duration_seconds=1.0,
        total_cost_usd=0.01,
        employee_results=(),
    )
    _emit_daily_log(mock_log, config, result, "abcdef1234567890")

    call_kwargs = mock_log.append.call_args
    corr = call_kwargs.kwargs.get("correlation_id")
    assert corr == "abcdef12"  # first 8 chars


def test_emit_daily_log_includes_cost_and_duration(config, mock_log):
    """Test 5: Log entry includes cost and duration fields."""
    result = TeamResult(
        department="qa",
        manager_output="done",
        success=True,
        duration_seconds=8.2,
        total_cost_usd=0.142,
        employee_results=(),
    )
    _emit_daily_log(mock_log, config, result, "s1")

    call_kwargs = mock_log.append.call_args
    entry = call_kwargs.kwargs.get("entry") or call_kwargs.args[0]
    assert "cost=$0.142" in entry
    assert "dur=8.2s" in entry


def test_emit_daily_log_includes_specialist_count(config, mock_log):
    """Test 6: Log entry includes specialists used/total."""
    from teams._types import EmployeeResult
    emp_results = (
        EmployeeResult(employee_name="qa-eng-1", output="ok", success=True),
    )
    result = TeamResult(
        department="qa",
        manager_output="done",
        success=True,
        duration_seconds=2.0,
        total_cost_usd=0.05,
        employee_results=emp_results,
    )
    _emit_daily_log(mock_log, config, result, "s1")

    call_kwargs = mock_log.append.call_args
    entry = call_kwargs.kwargs.get("entry") or call_kwargs.args[0]
    # config has 2 employees, 1 employee_result
    assert "specialists=1/2" in entry


def test_emit_daily_log_survives_append_exception(config):
    """Test 7: _emit_daily_log never raises even if daily_log.append raises."""
    bad_log = mock.MagicMock()
    bad_log.append.side_effect = RuntimeError("disk full")
    result = TeamResult(
        department="qa",
        manager_output="ok",
        success=True,
        duration_seconds=1.0,
        total_cost_usd=0.0,
        employee_results=(),
    )
    # Must not propagate the RuntimeError
    _emit_daily_log(bad_log, config, result, "s1")


# ---------------------------------------------------------------------------
# Integration tests: DepartmentTeam.run emits log via injected writer
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_run_emits_log_on_success(config, deps, mock_log):
    """Test 8: DepartmentTeam.run emits daily log line on successful run."""
    team = DepartmentTeam(config=config, lazy_build=False, daily_log=mock_log)
    test_model = TestModel(custom_output_args={"answer": "QA passed"}, call_tools=[])

    with team.manager.override(model=test_model):
        result = await team.run("review module", deps=deps)

    assert result.success is True
    mock_log.append.assert_called_once()
    call_kwargs = mock_log.append.call_args
    entry = call_kwargs.kwargs.get("entry") or call_kwargs.args[0]
    assert "[Z4]" in entry
    assert "[OK" in entry


@pytest.mark.asyncio
async def test_run_emits_log_on_failure(config, deps, mock_log):
    """Test 9: DepartmentTeam.run emits daily log line on failure."""
    team = DepartmentTeam(config=config, lazy_build=False, daily_log=mock_log)

    async def failing_run(*args, **kwargs):
        raise RuntimeError("model error")

    with mock.patch.object(team.manager, "run", side_effect=failing_run):
        result = await team.run("review module", deps=deps)

    assert result.success is False
    mock_log.append.assert_called_once()
    call_kwargs = mock_log.append.call_args
    entry = call_kwargs.kwargs.get("entry") or call_kwargs.args[0]
    assert "[FAIL" in entry


@pytest.mark.asyncio
async def test_run_no_log_when_daily_log_is_none(config, deps):
    """Test 10: DepartmentTeam.run with daily_log=None does not raise."""
    team = DepartmentTeam(config=config, lazy_build=False, daily_log=None)
    test_model = TestModel(custom_output_args={"answer": "ok"}, call_tools=[])

    with team.manager.override(model=test_model):
        result = await team.run("task", deps=deps)

    assert result.success is True


@pytest.mark.asyncio
async def test_run_emits_department_name_uppercase(config, deps, mock_log):
    """Test 11: Department name in log entry is UPPERCASED."""
    team = DepartmentTeam(config=config, lazy_build=False, daily_log=mock_log)
    test_model = TestModel(custom_output_text="ok", call_tools=[])

    with team.manager.override(model=test_model):
        await team.run("task", deps=deps)

    call_kwargs = mock_log.append.call_args
    entry = call_kwargs.kwargs.get("entry") or call_kwargs.args[0]
    assert "[QA]" in entry  # config.name is "qa", should be uppercased
