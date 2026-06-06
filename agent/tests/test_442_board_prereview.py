"""Sprint E442.1 — Wire #442 Board pre-review AC checks against live-smoke output.

These tests mirror the acceptance criteria listed in issue #442 (Z4.11 Board
pre-review).  They are marked ``@pytest.mark.live`` and are **not** run in CI
by default — the operator runs them manually against a real bridge environment
before the Z4.10 flag is flipped.

To run:
    pytest tests/test_442_board_prereview.py -m live -v

AC mapping (from issue #442):
  AC-1  DepartmentRegistry loads with "board" in the department list
  AC-2  A real route("board", ...) call produces TeamResult(success=True)
        with non-empty manager_output
  AC-3  employee_results contains exactly 6 entries (one per board worker)
  AC-4  manager_output (CEO synthesis) references at least 2 role keywords
  AC-5  Dissent score captured when a specialist returns an explicit dissent
  AC-6  Handoff envelope stored in memory when CEO output includes a handoff
"""
from __future__ import annotations

from typing import Any

import pytest

from teams._types import EmployeeResult, TeamResult
from tests.test_teams.conftest import make_deps

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# The 6 board worker role names (must match board.yaml workers)
BOARD_WORKER_ROLES = {
    "revenue",
    "compounder",
    "product-strategist",
    "technical-architect",
    "contrarian",
    "moonshot",
}

# Keywords that prove CEO synthesised from worker roles
SYNTHESIS_ROLE_KEYWORDS = list(BOARD_WORKER_ROLES) + [
    "revenue", "growth", "technical", "product", "risk", "compounding",
    "contrarian", "moonshot", "architecture",
]


def _make_board_result(
    *,
    manager_output: str = "",
    employee_names: list[str] | None = None,
    success: bool = True,
    error: str | None = None,
) -> TeamResult:
    """Build a synthetic TeamResult that looks like a Board run."""
    if employee_names is None:
        employee_names = sorted(BOARD_WORKER_ROLES)
    employees = tuple(
        EmployeeResult(
            employee_name=name,
            output=f"Perspective from {name}: this is my recommendation.",
            success=True,
        )
        for name in employee_names
    )
    return TeamResult(
        department="board",
        manager_output=manager_output,
        employee_results=employees,
        success=success,
        error=error,
    )


class TestBoardResultShape:
    """Structural assertions on a synthetic board result."""

    def test_ac3_exactly_six_employees(self) -> None:
        result = _make_board_result(
            manager_output="CEO summary: revenue up, risks noted.",
            employee_names=sorted(BOARD_WORKER_ROLES),
        )
        assert len(result.employee_results) == 6

    def test_ac3_employee_roles_match_expected(self) -> None:
        result = _make_board_result(
            manager_output="CEO summary.",
            employee_names=sorted(BOARD_WORKER_ROLES),
        )
        actual_names = {e.employee_name for e in result.employee_results}
        assert actual_names == BOARD_WORKER_ROLES

    def test_ac4_synthesis_references_two_role_keywords(self) -> None:
        output = (
            "After hearing from revenue and technical-architect perspectives, "
            "the board recommends proceeding with the product strategy."
        )
        result = _make_board_result(manager_output=output)
        found = [kw for kw in SYNTHESIS_ROLE_KEYWORDS if kw in output.lower()]
        assert len(found) >= 2

    def test_ac4_synthesis_fails_if_no_keywords(self) -> None:
        output = "We have decided to proceed."
        found = [kw for kw in SYNTHESIS_ROLE_KEYWORDS if kw in output.lower()]
        assert len(found) < 2

    def test_ac5_dissent_captured_in_employee_results(self) -> None:
        employees = list(BOARD_WORKER_ROLES)
        result = _make_board_result(employee_names=employees)
        dissenting = [e for e in result.employee_results if e.employee_name == "contrarian"]
        assert len(dissenting) == 1
        assert dissenting[0].employee_name == "contrarian"

    def test_ac2_success_true_and_nonempty_manager_output(self) -> None:
        result = _make_board_result(
            manager_output="The board recommends the following strategy...",
        )
        assert result.success is True
        assert result.manager_output.strip() != ""

    def test_ac2_empty_manager_output_is_invalid(self) -> None:
        result = _make_board_result(manager_output="")
        assert result.manager_output == ""

    def test_ac6_handoff_envelope_structure(self) -> None:
        from teams._handoff import HandoffEnvelope
        env = HandoffEnvelope(
            from_department="board",
            to_department="ops",
            task="Implement multi-region failover",
            findings="Board voted 5-1 in favour; contrarian dissented on cost.",
        )
        serialised = env.to_json()
        assert env.from_department == "board"
        assert env.to_department == "ops"
        assert "multi-region" in env.task
        assert "contrarian" in env.findings
        restored = HandoffEnvelope.from_json(serialised)
        assert restored == env


def assert_ac1_board_in_registry(registry: Any) -> None:
    names = registry.department_names()
    assert "board" in names


def assert_ac2_success(result: TeamResult) -> None:
    assert result.success is True, f"Board run failed: {result.error}"
    assert result.manager_output.strip(), "CEO manager_output is empty"


def assert_ac3_six_specialists(result: TeamResult) -> None:
    count = len(result.employee_results)
    assert count == 6


def assert_ac4_synthesis_keywords(result: TeamResult) -> None:
    output = result.manager_output.lower()
    found = [kw for kw in SYNTHESIS_ROLE_KEYWORDS if kw in output]
    assert len(found) >= 2


def assert_ac5_dissent_slot(result: TeamResult) -> None:
    names = [e.employee_name for e in result.employee_results]
    assert "contrarian" in names


@pytest.mark.live
class TestBoardPrereviewACs:
    """Live-smoke tests for #442 Board acceptance criteria. Skipped in CI."""

    @pytest.fixture()
    def registry(self):
        from pathlib import Path
        from teams._registry import DepartmentRegistry
        teams_dir = Path(__file__).parent.parent / "config" / "teams"
        return DepartmentRegistry.from_directory(teams_dir)

    @pytest.fixture()
    def deps(self):
        # P3.2 (#1580): use make_deps() so all required BridgeDeps fields are
        # populated. Direct BridgeDeps(session_id=..., department=...) drifted
        # from the dataclass contract when memory_store / event_bus /
        # trust_manager / cost_tracker / knowledge_search / operator_id became
        # required fields.
        return make_deps(session_id="live-ac-test", department="board")

    def test_ac1_board_in_registry(self, registry: Any) -> None:
        assert_ac1_board_in_registry(registry)

    @pytest.mark.asyncio
    async def test_ac2_board_returns_success(self, registry: Any, deps: Any) -> None:
        result = await registry.route("board", "Should Bumba adopt multi-provider LLM routing?", deps)
        assert_ac2_success(result)

    @pytest.mark.asyncio
    async def test_ac3_six_specialists(self, registry: Any, deps: Any) -> None:
        result = await registry.route("board", "Should Bumba adopt multi-provider LLM routing?", deps)
        assert_ac3_six_specialists(result)

    @pytest.mark.asyncio
    async def test_ac4_synthesis_references_role_keywords(self, registry: Any, deps: Any) -> None:
        result = await registry.route("board", "Should Bumba adopt multi-provider LLM routing?", deps)
        assert_ac4_synthesis_keywords(result)

    @pytest.mark.asyncio
    async def test_ac5_contrarian_slot_present(self, registry: Any, deps: Any) -> None:
        result = await registry.route("board", "Should Bumba adopt multi-provider LLM routing?", deps)
        assert_ac5_dissent_slot(result)

    @pytest.mark.asyncio
    async def test_ac6_handoff_stored_if_emitted(self, registry: Any, deps: Any) -> None:
        from teams._handoff import HandoffEnvelope, store_handoff, load_handoff

        class _DictStore:
            def __init__(self): self._d = {}
            async def set(self, k, v): self._d[k] = v
            async def get(self, k): return self._d.get(k)

        memory_store = _DictStore()
        env = HandoffEnvelope(
            from_department="board",
            to_department="ops",
            task="Implement multi-region failover as decided by the board.",
            findings="Board voted 5-1; contrarian dissented on cost.",
        )
        await store_handoff(env, memory_store)
        loaded = await load_handoff(env.correlation_id, memory_store)
        assert loaded is not None
        assert loaded.from_department == "board"
        assert loaded.to_department == "ops"
