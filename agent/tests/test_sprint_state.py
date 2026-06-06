"""Tests for sprint state (#261) and sprint-mode lifecycle (#262)."""

from __future__ import annotations

import textwrap
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bridge.plan_state import (
    SprintBoundaryViolation,
    format_sprint_context,
    load_sprint_state,
    next_actionable_sprint,
    verify_sprint_boundary,
)
from bridge.session_context_builder import build_sprint_context


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SAMPLE_STATE = textwrap.dedent("""\
    # Sprint State

    | Sprint | Phase | Status | Started | Completed | Operator Signature | Notes |
    |--------|-------|--------|---------|-----------|-------------------|-------|
    | 0.1 | 0 | complete | 2026-04-08 | 2026-04-08 | — | PR #271 |
    | 0.2 | 0 | complete | 2026-04-08 | 2026-04-08 | — | PR #272 |
    | 1.1 | 1 | in_progress | 2026-04-09 | — | — | — |
    | 1.2 | 1 | pending | — | — | — | — |
    | 1.3 | 1 | blocked | — | — | — | Needs credentials |
    | 2.1 | 2 | pending | — | — | — | — |
""")


@pytest.fixture
def state_file(tmp_path: Path) -> Path:
    p = tmp_path / "sprint-state.md"
    p.write_text(SAMPLE_STATE)
    return p


# ---------------------------------------------------------------------------
# load_sprint_state
# ---------------------------------------------------------------------------

class TestLoadSprintState:
    def test_parses_all_rows(self, state_file: Path):
        rows = load_sprint_state(state_file)
        assert len(rows) == 6

    def test_first_row_fields(self, state_file: Path):
        rows = load_sprint_state(state_file)
        r = rows[0]
        assert r.sprint_id == "0.1"
        assert r.phase == "0"
        assert r.status == "complete"
        assert r.started == "2026-04-08"
        assert r.completed == "2026-04-08"

    def test_in_progress_row(self, state_file: Path):
        rows = load_sprint_state(state_file)
        r = rows[2]
        assert r.sprint_id == "1.1"
        assert r.status == "in_progress"

    def test_missing_file_returns_empty(self, tmp_path: Path):
        rows = load_sprint_state(tmp_path / "nonexistent.md")
        assert rows == []

    def test_empty_file_returns_empty(self, tmp_path: Path):
        p = tmp_path / "empty.md"
        p.write_text("# No table here\nJust text.")
        rows = load_sprint_state(p)
        assert rows == []


# ---------------------------------------------------------------------------
# next_actionable_sprint
# ---------------------------------------------------------------------------

class TestNextActionableSprint:
    def test_returns_in_progress_first(self, state_file: Path):
        rows = load_sprint_state(state_file)
        result = next_actionable_sprint(rows)
        assert result is not None
        assert result.sprint_id == "1.1"
        assert result.status == "in_progress"

    def test_returns_pending_when_no_in_progress(self, tmp_path: Path):
        md = textwrap.dedent("""\
            | Sprint | Phase | Status |
            |--------|-------|--------|
            | 0.1 | 0 | complete |
            | 1.1 | 1 | pending |
        """)
        p = tmp_path / "state.md"
        p.write_text(md)
        rows = load_sprint_state(p)
        result = next_actionable_sprint(rows)
        assert result is not None
        assert result.sprint_id == "1.1"

    def test_returns_none_when_all_complete(self, tmp_path: Path):
        md = textwrap.dedent("""\
            | Sprint | Phase | Status |
            |--------|-------|--------|
            | 0.1 | 0 | complete |
            | 0.2 | 0 | complete |
        """)
        p = tmp_path / "state.md"
        p.write_text(md)
        rows = load_sprint_state(p)
        result = next_actionable_sprint(rows)
        assert result is None

    def test_skips_blocked(self, tmp_path: Path):
        md = textwrap.dedent("""\
            | Sprint | Phase | Status |
            |--------|-------|--------|
            | 1.1 | 1 | blocked |
            | 1.2 | 1 | pending |
        """)
        p = tmp_path / "state.md"
        p.write_text(md)
        rows = load_sprint_state(p)
        result = next_actionable_sprint(rows)
        assert result is not None
        assert result.sprint_id == "1.2"


# ---------------------------------------------------------------------------
# verify_sprint_boundary
# ---------------------------------------------------------------------------

class TestVerifySprintBoundary:
    def test_passes_for_correct_sprint(self, state_file: Path):
        rows = load_sprint_state(state_file)
        # 1.1 is in_progress, so it's the actionable one
        verify_sprint_boundary(rows, "1.1")  # should not raise

    def test_raises_for_wrong_sprint(self, state_file: Path):
        rows = load_sprint_state(state_file)
        with pytest.raises(SprintBoundaryViolation, match="1.2.*not actionable"):
            verify_sprint_boundary(rows, "1.2")

    def test_raises_when_no_actionable(self, tmp_path: Path):
        md = textwrap.dedent("""\
            | Sprint | Phase | Status |
            |--------|-------|--------|
            | 0.1 | 0 | complete |
        """)
        p = tmp_path / "state.md"
        p.write_text(md)
        rows = load_sprint_state(p)
        with pytest.raises(SprintBoundaryViolation, match="No actionable"):
            verify_sprint_boundary(rows, "0.1")


# ---------------------------------------------------------------------------
# format_sprint_context
# ---------------------------------------------------------------------------

class TestFormatSprintContext:
    def test_includes_next_actionable(self, state_file: Path):
        rows = load_sprint_state(state_file)
        ctx = format_sprint_context(rows)
        assert "Sprint 1.1" in ctx
        assert "Phase 1" in ctx

    def test_all_complete_message(self, tmp_path: Path):
        md = textwrap.dedent("""\
            | Sprint | Phase | Status |
            |--------|-------|--------|
            | 0.1 | 0 | complete |
        """)
        p = tmp_path / "state.md"
        p.write_text(md)
        rows = load_sprint_state(p)
        ctx = format_sprint_context(rows)
        assert "All sprints are complete" in ctx

    def test_includes_enforcement_warning(self, state_file: Path):
        rows = load_sprint_state(state_file)
        ctx = format_sprint_context(rows)
        assert "MUST work on this sprint only" in ctx


# ---------------------------------------------------------------------------
# build_sprint_context (session_context_builder)
# ---------------------------------------------------------------------------

class TestBuildSprintContext:
    def test_returns_context_for_valid_file(self, state_file: Path):
        result = build_sprint_context(state_file)
        assert result is not None
        assert "Sprint 1.1" in result

    def test_returns_none_for_missing_file(self, tmp_path: Path):
        result = build_sprint_context(tmp_path / "missing.md")
        assert result is None


# ---------------------------------------------------------------------------
# run_sprint_mode (#262)
# ---------------------------------------------------------------------------

class TestRunSprintMode:
    @pytest.mark.asyncio
    async def test_runs_one_sprint_per_iteration(self, tmp_path: Path):
        from bridge.autonomy import run_sprint_mode

        # State with one pending sprint
        md = textwrap.dedent("""\
            | Sprint | Phase | Status |
            |--------|-------|--------|
            | 0.1 | 0 | complete |
            | 1.1 | 1 | pending |
        """)
        state_path = tmp_path / "sprint-state.md"
        state_path.write_text(md)
        plan_path = tmp_path / "plan.md"
        plan_path.write_text("# Plan")

        # Mock claude_runner
        mock_result = MagicMock()
        mock_result.response_text = "Sprint complete"
        runner = MagicMock()
        runner.invoke = AsyncMock(return_value=mock_result)

        # After invoke, the sprint should still be pending in state file
        # (the subprocess would normally update it)
        # Patch load_sprint_state to simulate the sprint being marked complete
        # after one iteration
        call_count = 0
        original_load = load_sprint_state

        def load_with_progression(path):
            nonlocal call_count
            call_count += 1
            if call_count > 1:
                # After first run, mark sprint as complete
                new_md = textwrap.dedent("""\
                    | Sprint | Phase | Status |
                    |--------|-------|--------|
                    | 0.1 | 0 | complete |
                    | 1.1 | 1 | complete |
                """)
                Path(path).write_text(new_md)
            return original_load(path)

        with patch("bridge.plan_state.load_sprint_state", side_effect=load_with_progression):
            results = await run_sprint_mode(plan_path, state_path, runner)

        assert len(results) == 1
        assert results[0]["sprint_id"] == "1.1"
        runner.invoke.assert_called_once()
        # Verify fresh session (session_id=None)
        call_kwargs = runner.invoke.call_args
        assert call_kwargs.kwargs.get("session_id") is None

    @pytest.mark.asyncio
    async def test_phase_boundary_callback(self, tmp_path: Path):
        from bridge.autonomy import run_sprint_mode

        md = textwrap.dedent("""\
            | Sprint | Phase | Status |
            |--------|-------|--------|
            | 1.1 | 1 | pending |
        """)
        state_path = tmp_path / "sprint-state.md"
        state_path.write_text(md)
        plan_path = tmp_path / "plan.md"
        plan_path.write_text("# Plan")

        runner = MagicMock()
        mock_result = MagicMock()
        mock_result.response_text = "done"
        runner.invoke = AsyncMock(return_value=mock_result)

        call_count = 0
        original_load = load_sprint_state

        def load_with_phase_change(path):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return original_load(path)
            elif call_count == 2:
                # After first sprint, switch to phase 2
                new_md = textwrap.dedent("""\
                    | Sprint | Phase | Status |
                    |--------|-------|--------|
                    | 1.1 | 1 | complete |
                    | 2.1 | 2 | pending |
                """)
                Path(path).write_text(new_md)
                return original_load(path)
            else:
                # After second sprint, all complete
                new_md = textwrap.dedent("""\
                    | Sprint | Phase | Status |
                    |--------|-------|--------|
                    | 1.1 | 1 | complete |
                    | 2.1 | 2 | complete |
                """)
                Path(path).write_text(new_md)
                return original_load(path)

        boundary_cb = AsyncMock()

        with patch("bridge.plan_state.load_sprint_state", side_effect=load_with_phase_change):
            results = await run_sprint_mode(
                plan_path, state_path, runner,
                on_phase_boundary=boundary_cb,
            )

        assert len(results) == 2
        boundary_cb.assert_called_once_with("1", "2")

    @pytest.mark.asyncio
    async def test_stops_on_no_actionable(self, tmp_path: Path):
        from bridge.autonomy import run_sprint_mode

        md = textwrap.dedent("""\
            | Sprint | Phase | Status |
            |--------|-------|--------|
            | 0.1 | 0 | complete |
        """)
        state_path = tmp_path / "sprint-state.md"
        state_path.write_text(md)
        plan_path = tmp_path / "plan.md"
        plan_path.write_text("# Plan")

        runner = MagicMock()
        results = await run_sprint_mode(plan_path, state_path, runner)
        assert results == []
        runner.invoke.assert_not_called()
