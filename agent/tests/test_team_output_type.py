"""Test that build_manager_agent uses output_type=TeamOutput.

Sprint 12 (#632): 0/7 departments used structured output because _factory.py
hard-coded output_type=str for all managers.  This module verifies the fix at
both the source-code level (static inspection) and the runtime level
(TestModel integration).
"""
from __future__ import annotations

from pathlib import Path

import pytest
from pydantic_ai.models.test import TestModel

from teams._factory import build_employee_agents, build_manager_agent
from teams._types import AgentSpec, BridgeDeps, DepartmentConfig, TeamOutput
from tests.test_teams.conftest import make_deps


# ---------------------------------------------------------------------------
# Static inspection — catch regressions in the source text
# ---------------------------------------------------------------------------

def test_factory_uses_team_output_for_manager():
    """build_manager_agent must use output_type=TeamOutput, not str."""
    src = Path("teams/_factory.py").read_text()

    # TeamOutput must be imported
    assert "TeamOutput" in src, "TeamOutput not imported in _factory.py"

    # The build_manager_agent function body must not use output_type=str
    lines = src.splitlines()
    in_manager_fn = False
    for i, line in enumerate(lines):
        if "def build_manager_agent" in line:
            in_manager_fn = True
        if in_manager_fn and "output_type=str" in line:
            # This is the bug — manager should use TeamOutput
            context = "\n".join(lines[max(0, i - 2):i + 3])
            pytest.fail(
                f"build_manager_agent still uses output_type=str at line {i + 1}:\n{context}"
            )
        if in_manager_fn and line.startswith("def ") and "build_manager_agent" not in line:
            in_manager_fn = False


def test_factory_imports_team_output():
    """_factory.py must import TeamOutput."""
    src = Path("teams/_factory.py").read_text()
    assert "TeamOutput" in src, "_factory.py must import TeamOutput"
    # Ensure it is imported from _types, not just referenced as a string
    assert "from teams._types" in src and "TeamOutput" in src


def test_factory_manager_uses_team_output_keyword():
    """The Agent() call in build_manager_agent must specify output_type=TeamOutput."""
    src = Path("teams/_factory.py").read_text()
    lines = src.splitlines()
    in_manager_fn = False
    found_team_output = False
    for line in lines:
        if "def build_manager_agent" in line:
            in_manager_fn = True
        if in_manager_fn and "output_type=TeamOutput" in line:
            found_team_output = True
            break
        if in_manager_fn and line.startswith("def ") and "build_manager_agent" not in line:
            in_manager_fn = False
    assert found_team_output, (
        "build_manager_agent must contain 'output_type=TeamOutput' "
        "in the Agent() constructor call"
    )


def test_employee_agents_retain_str_output_type():
    """build_employee_agents must still use output_type=str — only manager uses TeamOutput."""
    src = Path("teams/_factory.py").read_text()
    lines = src.splitlines()
    employee_builders = (
        "def build_employee_agents",
        "def _build_employee_agent_uncached",
    )
    in_employee_fn = False
    found_str = False
    for line in lines:
        if any(fn in line for fn in employee_builders):
            in_employee_fn = True
        if in_employee_fn and "output_type=str" in line:
            found_str = True
            break
        if (
            in_employee_fn
            and line.startswith("def ")
            and not any(fn in line for fn in employee_builders)
        ):
            in_employee_fn = False
    assert found_str, (
        "build_employee_agents must use output_type=str "
        "(employees emit plain text; only the manager needs TeamOutput)"
    )


# ---------------------------------------------------------------------------
# Runtime integration — verify pydantic-ai enforces schema at LLM boundary
# ---------------------------------------------------------------------------

@pytest.fixture
def qa_config() -> DepartmentConfig:
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
async def test_manager_returns_team_output_instance(qa_config, deps):
    """Manager result.output must be a TeamOutput instance, not a plain string."""
    employees = build_employee_agents(qa_config)
    manager = build_manager_agent(qa_config, employees)

    test_model = TestModel(
        custom_output_args={"answer": "structured answer from manager"},
        call_tools=[],
    )
    with manager.override(model=test_model):
        result = await manager.run("test task", deps=deps)

    assert isinstance(result.output, TeamOutput), (
        f"Expected TeamOutput from manager, got {type(result.output).__name__}. "
        "output_type=TeamOutput must be set in build_manager_agent."
    )
    assert result.output.answer == "structured answer from manager"


@pytest.mark.asyncio
async def test_team_result_structured_always_set_on_success(qa_config, deps):
    """TeamResult.structured must be set on every successful run (Gate 3 always fires)."""
    from teams._team import DepartmentTeam

    team = DepartmentTeam(config=qa_config, lazy_build=False)

    test_model = TestModel(
        custom_output_args={"answer": "gate 3 fires now", "confidence": 0.9},
        call_tools=[],
    )
    with team.manager.override(model=test_model):
        team_result = await team.run("evaluate coverage", deps=deps)

    assert team_result.success is True
    assert team_result.structured is not None, (
        "Gate 3 (Structured output valid) must fire. "
        "TeamResult.structured must not be None on success."
    )
    assert isinstance(team_result.structured, TeamOutput)
    assert team_result.structured.answer == "gate 3 fires now"
    assert team_result.structured.confidence == 0.9


@pytest.mark.asyncio
async def test_manager_output_extracted_as_answer_field(qa_config, deps):
    """TeamResult.manager_output must equal TeamOutput.answer (not raw JSON)."""
    from teams._team import DepartmentTeam

    team = DepartmentTeam(config=qa_config, lazy_build=False)

    expected_answer = "All tests pass. Coverage at 87%."
    test_model = TestModel(
        custom_output_args={"answer": expected_answer},
        call_tools=[],
    )
    with team.manager.override(model=test_model):
        team_result = await team.run("check coverage", deps=deps)

    assert team_result.manager_output == expected_answer, (
        "manager_output must be TeamOutput.answer, not the raw JSON string"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("department", ["qa", "board", "design", "strategy", "ops"])
async def test_all_departments_use_team_output(department):
    """All 7 departments must return TeamOutput — 0/7 → 7/7 fix (#632)."""
    config = DepartmentConfig(
        name=department,
        zone=4,
        description=f"{department} department",
        manager=AgentSpec(name=f"{department}-chief", model="anthropic:claude-opus-4-6"),
        employees=(
            AgentSpec(name=f"{department}-worker", model="anthropic:claude-sonnet-4-6"),
        ),
    )
    deps_for_dept = make_deps(session_id="s1", department=department)

    from teams._team import DepartmentTeam

    team = DepartmentTeam(config=config, lazy_build=False)
    test_model = TestModel(
        custom_output_args={"answer": f"{department} complete"},
        call_tools=[],
    )
    with team.manager.override(model=test_model):
        result = await team.run("do work", deps=deps_for_dept)

    assert result.success is True, f"Department {department} run failed: {result.error}"
    assert result.structured is not None, (
        f"Department {department}: Gate 3 did not fire — structured is None"
    )
    assert result.structured.answer == f"{department} complete"
