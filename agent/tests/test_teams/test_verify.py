"""Tests for the 7 verification gates (sprint B2.3)."""
from __future__ import annotations

import pytest

from teams._types import (
    AgentSpec,
    Constraints,
    DepartmentConfig,
    EmployeeResult,
    TeamOutput,
    TeamResult,
)
from teams._verify import verify_team_result


def _config(name: str = "test", n_employees: int = 1) -> DepartmentConfig:
    return DepartmentConfig(
        name=name,
        zone=4,
        description="",
        manager=AgentSpec(name="chief", model="anthropic:claude-opus-4-6", role="chief"),
        employees=tuple(
            AgentSpec(name=f"worker-{i}", model="anthropic:claude-sonnet-4-6", role="w")
            for i in range(n_employees)
        ),
        constraints=Constraints(cost_limit_usd=3.0, timeout_seconds=600),
    )


def _good_result(config: DepartmentConfig) -> TeamResult:
    return TeamResult(
        department=config.name,
        manager_output=(
            "This is a comprehensive answer explaining the synthesis and decision."
        ),
        employee_results=tuple(
            EmployeeResult(
                employee_name=e.name,
                output="specialist says stuff",
                success=True,
                tokens_used=100,
                duration_seconds=1.0,
            )
            for e in config.employees
        ),
        total_tokens=500,
        total_cost_usd=0.15,
        duration_seconds=10.0,
        success=True,
        structured=TeamOutput(answer="comprehensive answer"),
    )


# ---------------------------------------------------------------------------
# Gate 0 — all pass
# ---------------------------------------------------------------------------

def test_gate_all_pass_returns_empty() -> None:
    config = _config()
    violations = verify_team_result(_good_result(config), config)
    assert violations == [], f"Expected no violations; got: {violations}"


# ---------------------------------------------------------------------------
# Gate 1 — non-empty output
# ---------------------------------------------------------------------------

def test_gate1_empty_output_fails() -> None:
    config = _config()
    result = TeamResult(
        department=config.name,
        manager_output="   ",  # whitespace only
        total_cost_usd=0.0,
        duration_seconds=1.0,
        success=True,
        structured=TeamOutput(answer="x"),
    )
    violations = verify_team_result(result, config)
    assert any("Gate 1" in v for v in violations), violations


def test_gate1_nonempty_output_passes() -> None:
    config = _config()
    result = TeamResult(
        department=config.name,
        manager_output="Some answer.",
        total_cost_usd=0.0,
        duration_seconds=1.0,
        success=True,
    )
    violations = verify_team_result(result, config)
    assert not any("Gate 1" in v for v in violations), violations


# ---------------------------------------------------------------------------
# Gate 2 — no error keywords
# ---------------------------------------------------------------------------

def test_gate2_error_keyword_fails() -> None:
    config = _config()
    result = TeamResult(
        department=config.name,
        manager_output="Traceback (most recent call last): ...",
        total_cost_usd=0.0,
        duration_seconds=1.0,
        success=True,
    )
    violations = verify_team_result(result, config)
    assert any("Gate 2" in v for v in violations), violations


def test_gate2_clean_output_passes() -> None:
    config = _config()
    result = TeamResult(
        department=config.name,
        manager_output="All systems nominal. No issues detected.",
        total_cost_usd=0.0,
        duration_seconds=1.0,
        success=True,
    )
    violations = verify_team_result(result, config)
    assert not any("Gate 2" in v for v in violations), violations


# ---------------------------------------------------------------------------
# Gate 3 — structured output valid
# ---------------------------------------------------------------------------

def test_gate3_empty_structured_answer_fails() -> None:
    config = _config()
    result = TeamResult(
        department=config.name,
        manager_output="some output",
        total_cost_usd=0.0,
        duration_seconds=1.0,
        success=True,
        structured=TeamOutput(answer="   "),  # whitespace only
    )
    violations = verify_team_result(result, config)
    assert any("Gate 3" in v for v in violations), violations


def test_gate3_none_structured_passes() -> None:
    """structured=None means manager returned plain str — gate 3 is skipped."""
    config = _config()
    result = TeamResult(
        department=config.name,
        manager_output="some output",
        total_cost_usd=0.0,
        duration_seconds=1.0,
        success=True,
        structured=None,
    )
    violations = verify_team_result(result, config)
    assert not any("Gate 3" in v for v in violations), violations


# ---------------------------------------------------------------------------
# Gate 4 — cost within budget
# ---------------------------------------------------------------------------

def test_gate4_cost_exceeded_fails() -> None:
    config = _config()  # cost_limit_usd=3.0
    result = TeamResult(
        department=config.name,
        manager_output="answer",
        total_cost_usd=5.0,  # over limit
        duration_seconds=1.0,
        success=True,
    )
    violations = verify_team_result(result, config)
    assert any("Gate 4" in v for v in violations), violations


def test_gate4_cost_at_limit_passes() -> None:
    config = _config()
    result = TeamResult(
        department=config.name,
        manager_output="answer",
        total_cost_usd=3.0,  # exactly at limit
        duration_seconds=1.0,
        success=True,
    )
    violations = verify_team_result(result, config)
    assert not any("Gate 4" in v for v in violations), violations


# ---------------------------------------------------------------------------
# Gate 5 — duration within timeout
# ---------------------------------------------------------------------------

def test_gate5_duration_exceeded_fails() -> None:
    config = _config()  # timeout_seconds=600
    result = TeamResult(
        department=config.name,
        manager_output="answer",
        total_cost_usd=0.0,
        duration_seconds=601.0,  # over limit
        success=True,
    )
    violations = verify_team_result(result, config)
    assert any("Gate 5" in v for v in violations), violations


def test_gate5_within_timeout_passes() -> None:
    config = _config()
    result = TeamResult(
        department=config.name,
        manager_output="answer",
        total_cost_usd=0.0,
        duration_seconds=10.0,
        success=True,
    )
    violations = verify_team_result(result, config)
    assert not any("Gate 5" in v for v in violations), violations


# ---------------------------------------------------------------------------
# Gate 6 — specialist count matches
# ---------------------------------------------------------------------------

def test_gate6_more_results_than_employees_fails() -> None:
    config = _config(n_employees=1)  # 1 employee
    result = TeamResult(
        department=config.name,
        manager_output="answer",
        total_cost_usd=0.0,
        duration_seconds=1.0,
        success=True,
        employee_results=(
            EmployeeResult(employee_name="w0", output="x", success=True),
            EmployeeResult(employee_name="ghost", output="y", success=True),  # extra
        ),
    )
    violations = verify_team_result(result, config)
    assert any("Gate 6" in v for v in violations), violations


def test_gate6_fewer_results_than_employees_passes() -> None:
    """Fewer results than employees is fine (some may not have been invoked)."""
    config = _config(n_employees=3)
    result = TeamResult(
        department=config.name,
        manager_output="answer",
        total_cost_usd=0.0,
        duration_seconds=1.0,
        success=True,
        employee_results=(
            EmployeeResult(employee_name="w0", output="x", success=True),
        ),
    )
    violations = verify_team_result(result, config)
    assert not any("Gate 6" in v for v in violations), violations


# ---------------------------------------------------------------------------
# Gate 7 — no hallucination markers
# ---------------------------------------------------------------------------

def test_gate7_hallucination_marker_fails() -> None:
    config = _config()
    result = TeamResult(
        department=config.name,
        manager_output="As an AI language model, I cannot assist with this.",
        total_cost_usd=0.0,
        duration_seconds=1.0,
        success=True,
    )
    violations = verify_team_result(result, config)
    assert any("Gate 7" in v for v in violations), violations


def test_gate7_clean_output_passes() -> None:
    config = _config()
    result = TeamResult(
        department=config.name,
        manager_output="The analysis is complete. Revenue projections look strong.",
        total_cost_usd=0.0,
        duration_seconds=1.0,
        success=True,
    )
    violations = verify_team_result(result, config)
    assert not any("Gate 7" in v for v in violations), violations


# ---------------------------------------------------------------------------
# Integration: verify is called by DepartmentTeam.run()
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_team_run_marks_failure_on_verification_violation() -> None:
    """If verify_team_result finds violations, TeamResult.success must be False."""

    from pydantic_ai.models.test import TestModel

    from teams._team import DepartmentTeam
    from tests.test_teams.conftest import make_deps

    config = _config()
    team = DepartmentTeam(config, lazy_build=False)
    deps = make_deps(department="test")

    # Use a halucination marker to trigger Gate 7 (can't use empty string — pydantic-ai rejects it)
    hallucinated_output = "As an AI language model, I cannot assist with this request."
    test_model = TestModel(custom_output_args={"answer": hallucinated_output}, call_tools=[])
    with team.manager.override(model=test_model):
        result = await team.run("task", deps=deps)

    assert result.success is False
    assert result.error is not None
    # Gate 7 fires for the hallucination marker
    assert "Gate 7" in result.error
