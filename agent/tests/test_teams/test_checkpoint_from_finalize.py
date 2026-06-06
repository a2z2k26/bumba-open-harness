"""WS2.4 — checkpoint write from _finalize_run_relay under the should_checkpoint gate.

These tests drive the run-relay finalize seam directly: a checkpoint is written
beside the run-memory note, under the SAME should_checkpoint gate, best-effort
(a checkpoint-write failure logs WARNING and never breaks the run).
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from bridge.run_artifacts import create_run_workspace, load_checkpoint
from teams import _team
from teams._post_run import should_checkpoint
from teams._run_telemetry import RunTelemetry
from teams._team import _finalize_run_relay, _RunRelayContext, _memory_ref_for_run
from teams._types import EmployeeResult, TeamResult
from tests.test_teams.conftest import make_deps


def _relay(tmp_path: Path, department: str = "dept-s") -> _RunRelayContext:
    workspace = create_run_workspace(
        tmp_path / "zone4-runs",
        session_id="session-1",
        department=department,
        directive_id=None,
        chief="s-chief",
    )
    return _RunRelayContext(
        run_id=workspace.run_id,
        run_dir=workspace.run_dir,
        manifest_path=workspace.manifest_path,
        memory_ref=_memory_ref_for_run(department, workspace.run_id),
    )


def _timeout_result() -> TeamResult:
    """A failed run whose failure_class is the recoverable 'timeout'."""
    return TeamResult(
        department="dept-s",
        manager_output="",
        employee_results=(
            EmployeeResult(employee_name="alpha", output="partial", success=True),
        ),
        success=False,
        error="manager timeout after 60s",
        telemetry=RunTelemetry(
            department="dept-s",
            chief_name="s-chief",
            primary_model="anthropic:claude-opus-4-6",
            failure_class="timeout",
        ),
    )


def _empty_result() -> TeamResult:
    """A run with no signal at all — should_checkpoint() returns False."""
    return TeamResult(
        department="dept-s",
        manager_output="",
        success=False,
        error="",
        telemetry=None,
    )


@pytest.mark.asyncio
async def test_checkpoint_written_on_timeout(tmp_path: Path) -> None:
    relay = _relay(tmp_path)
    deps = make_deps(session_id="session-1", department="dept-s")
    result = _timeout_result()

    assert should_checkpoint(result, result.telemetry) is True

    out = await _finalize_run_relay(
        deps, result, relay, task="rescue this", run_result=None
    )

    record = load_checkpoint(relay.run_dir)
    assert record is not None
    assert record.run_id == relay.run_id
    assert record.task == "rescue this"
    assert record.failure_class == "timeout"
    assert record.resumable is True
    assert record.attempt == 1
    assert tuple(s.name for s in record.completed_specialists) == ("alpha",)
    # the finalize result is still returned unchanged in shape (success flag intact)
    assert out.success is False


@pytest.mark.asyncio
async def test_no_checkpoint_when_should_checkpoint_false(tmp_path: Path) -> None:
    relay = _relay(tmp_path)
    deps = make_deps(session_id="session-1", department="dept-s")
    result = _empty_result()

    # SEAM AUDIT: the note and the checkpoint must be gated identically. The
    # checkpoint helper sees the same result the note helper sees; when the gate
    # is False, neither writes. We exercise the helper directly here because
    # _finalize_run_relay injects a non-empty memory_ref before the gate runs
    # (which would trip should_checkpoint) — the gate's False branch lives at
    # the helper boundary.
    assert should_checkpoint(result, result.telemetry) is False

    await _team._write_run_checkpoint(
        deps, result, relay, task="noop", run_result=None
    )

    assert load_checkpoint(relay.run_dir) is None
    assert not (relay.run_dir / "checkpoint.json").exists()


@pytest.mark.asyncio
async def test_checkpoint_gate_matches_memory_note_gate(tmp_path: Path) -> None:
    """SEAM AUDIT: should_checkpoint gates the memory-note write AND the
    checkpoint write — they must never diverge. For the SAME result, the note
    helper and the checkpoint helper either both write or both skip."""
    memory_store = AsyncMock()
    memory_store.set = AsyncMock(return_value=None)
    deps = replace(
        make_deps(session_id="session-1", department="dept-s"),
        memory_store=memory_store,
    )

    # gate TRUE → note written AND checkpoint written (same result, same gate)
    relay_true = _relay(tmp_path / "true")
    result_true = replace(_timeout_result(), memory_ref=relay_true.memory_ref)
    assert should_checkpoint(result_true, result_true.telemetry) is True
    await _team._write_run_memory_note(
        deps, result_true, relay_true.manifest_path
    )
    await _team._write_run_checkpoint(
        deps, result_true, relay_true, task="t", run_result=None
    )
    memory_store.set.assert_awaited_once()
    assert load_checkpoint(relay_true.run_dir) is not None

    # gate FALSE → neither note nor checkpoint (same result, same gate)
    memory_store.set.reset_mock()
    relay_false = _relay(tmp_path / "false")
    result_false = _empty_result()  # no signal: gate is False
    assert should_checkpoint(result_false, result_false.telemetry) is False
    await _team._write_run_memory_note(
        deps, result_false, relay_false.manifest_path
    )
    await _team._write_run_checkpoint(
        deps, result_false, relay_false, task="t", run_result=None
    )
    memory_store.set.assert_not_awaited()
    assert load_checkpoint(relay_false.run_dir) is None


@pytest.mark.asyncio
async def test_checkpoint_write_failure_does_not_break_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    relay = _relay(tmp_path)
    deps = make_deps(session_id="session-1", department="dept-s")
    result = _timeout_result()

    def _boom(*args: object, **kwargs: object) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(_team, "write_checkpoint", _boom)

    # Must NOT raise: a checkpoint-write failure is best-effort.
    out = await _finalize_run_relay(
        deps, result, relay, task="rescue", run_result=None
    )

    # run is unaffected: manifest finalize still produced run_id + manifest_path
    assert out.run_id == relay.run_id
    assert out.manifest_path is not None
    assert out.success is False
    # no checkpoint landed because the write raised
    assert load_checkpoint(relay.run_dir) is None


@pytest.mark.asyncio
async def test_first_run_attempt_is_one(tmp_path: Path) -> None:
    relay = _relay(tmp_path)
    deps = make_deps(session_id="session-1", department="dept-s")
    result = _timeout_result()

    await _finalize_run_relay(
        deps, result, relay, task="first", run_result=None
    )

    record = load_checkpoint(relay.run_dir)
    assert record is not None
    assert record.attempt == 1
