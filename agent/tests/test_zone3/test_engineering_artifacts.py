"""Z3-05 tests — engineering artifacts, memory pointers, worktree hygiene.

Reuses the shared Zone 4 artifact primitives (bridge/run_artifacts.py, landed
in Z4-03/Z4-05) and layers engineering-specific manifest fields (zone 3,
worktree, branch, changed files, validation). Verifies the memory note shape
and worktree cleanliness reporting.
"""

from __future__ import annotations

import json
from pathlib import Path

from zone3.engineering_artifacts import (
    EngineeringValidation,
    WorktreeStatus,
    build_engineering_memory_note,
    summarize_worktree_status,
    write_engineering_manifest,
)


def test_manifest_lives_under_artifact_root_with_zone_3(tmp_path: Path) -> None:
    workspace = write_engineering_manifest(
        tmp_path / "runs",
        session_id="sess-1",
        specialist="engineering-backend-architect",
        worktree="/tmp/bumba-z3",
        branch="feat/z3-engineering-dispatcher",
        changed_files=("agent/zone3/engineering_dispatcher.py",),
        validation=(
            EngineeringValidation(
                command="python -m pytest agent/tests/test_zone3 -q",
                status="pass",
            ),
        ),
        entropy="unit-test",
    )
    payload = json.loads(workspace.manifest_path.read_text(encoding="utf-8"))
    assert payload["department"] == "engineering"
    eng = payload["engineering"]
    assert eng["zone"] == 3
    assert eng["worktree"] == "/tmp/bumba-z3"
    assert eng["branch"] == "feat/z3-engineering-dispatcher"
    assert eng["changed_files"] == ["agent/zone3/engineering_dispatcher.py"]
    assert eng["validation"][0]["status"] == "pass"
    # Shared run-id convention preserved (Z4 relay can point to it).
    assert payload["run_id"].startswith("run-")


def test_manifest_run_dir_is_under_given_root(tmp_path: Path) -> None:
    workspace = write_engineering_manifest(
        tmp_path / "runs",
        session_id="s",
        specialist="engineering-code-reviewer",
        worktree="/tmp/x",
        branch="b",
        changed_files=(),
        validation=(),
        entropy="unit-test",
    )
    assert (tmp_path / "runs") in workspace.run_dir.parents


def test_memory_note_contains_run_metadata(tmp_path: Path) -> None:
    note = build_engineering_memory_note(
        run_id="run-20260521-160000-engineering-a1b2c3",
        specialist="engineering-backend-architect",
        manifest_path=tmp_path / "manifest.json",
        changed_files=("agent/zone3/engineering_dispatcher.py",),
        validation_status="pass",
    )
    assert "run-20260521-160000-engineering-a1b2c3" in note
    assert "engineering-backend-architect" in note
    assert "agent/zone3/engineering_dispatcher.py" in note
    assert "pass" in note


def test_memory_note_handles_no_changed_files(tmp_path: Path) -> None:
    note = build_engineering_memory_note(
        run_id="run-x",
        specialist="x",
        manifest_path=tmp_path / "m.json",
        changed_files=(),
        validation_status="fail",
    )
    assert "none" in note


def test_clean_worktree_is_ready_to_pr() -> None:
    status = WorktreeStatus(clean=True, dirty_files=())
    summary = summarize_worktree_status(status)
    assert status.ready_to_pr is True
    assert "clean" in summary.lower()


def test_dirty_worktree_surfaced_not_hidden() -> None:
    status = WorktreeStatus(clean=False, dirty_files=("agent/foo.py", "agent/bar.py"))
    summary = summarize_worktree_status(status)
    assert status.ready_to_pr is False
    assert "agent/foo.py" in summary
    assert "agent/bar.py" in summary


def test_failure_manifest_preserves_error_surface(tmp_path: Path) -> None:
    workspace = write_engineering_manifest(
        tmp_path / "runs",
        session_id="s",
        specialist="engineering-code-reviewer",
        worktree="/tmp/x",
        branch="b",
        changed_files=(),
        validation=(
            EngineeringValidation(command="pytest", status="fail"),
        ),
        entropy="unit-test",
        status="failed",
        error_class="claude_p_failed",
        exit_code=2,
        stderr_excerpt="boom",
    )
    payload = json.loads(workspace.manifest_path.read_text(encoding="utf-8"))
    eng = payload["engineering"]
    assert eng["status"] == "failed"
    assert eng["error_class"] == "claude_p_failed"
    assert eng["exit_code"] == 2
    assert eng["stderr_excerpt"] == "boom"


def test_record_engineering_run_composes_all_artifacts(tmp_path: Path) -> None:
    from zone3.engineering_artifacts import record_engineering_run

    record = record_engineering_run(
        tmp_path / "runs",
        session_id="s",
        specialist="engineering-backend-architect",
        worktree="/tmp/bumba-z3",
        branch="feat/x",
        changed_files=("agent/zone3/engineering_dispatcher.py",),
        validation=(EngineeringValidation(command="pytest", status="pass"),),
        worktree_status=WorktreeStatus(clean=True),
        entropy="unit-test",
    )
    assert record.run_id.startswith("run-")
    assert record.manifest_path.is_file()
    assert "engineering-backend-architect" in record.memory_note
    assert record.ready_to_pr is True


def test_record_engineering_run_surfaces_dirty_worktree(tmp_path: Path) -> None:
    from zone3.engineering_artifacts import record_engineering_run

    record = record_engineering_run(
        tmp_path / "runs",
        session_id="s",
        specialist="x",
        worktree="/tmp/x",
        branch="b",
        changed_files=(),
        validation=(EngineeringValidation(command="pytest", status="fail"),),
        worktree_status=WorktreeStatus(clean=False, dirty_files=("agent/x.py",)),
        status="failed",
        error_class="claude_p_failed",
        exit_code=2,
        stderr_excerpt="boom",
        entropy="unit-test",
    )
    assert record.ready_to_pr is False
    assert "agent/x.py" in record.worktree_summary
    assert "fail" in record.memory_note
