"""Tests for the operator checkpoint surface — /checkpoints + /resume <run_id>.

WS2.6 (#2570). The operator surface for the Zone 4 run-checkpoint feature:

- ``/checkpoints`` scans ``artifact_root`` for ``checkpoint.json`` records
  where ``resumable == True`` and lists them (run_id, department,
  failure_class, age), newest first; empty-state message when none.
- ``/resume <run_id>`` re-dispatches the checkpoint's department through the
  same ``DepartmentRegistry.route`` path /route uses, threading
  ``resume_from=<run_id>``, and reports the new run_id.

The handlers are exercised against a real on-disk artifact_root populated via
``write_checkpoint`` so the listing logic is verified end-to-end, and a mock
DepartmentRegistry so the re-dispatch seam is asserted without invoking a chief.
"""
from __future__ import annotations

import unittest.mock as mock
from pathlib import Path

import pytest

from bridge.commands import CommandHandler
from bridge.run_artifacts import (
    CHECKPOINT_SCHEMA_VERSION,
    CheckpointRecord,
    write_checkpoint,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_record(
    *,
    run_id: str,
    department: str = "qa",
    failure_class: str | None = "usage_limit",
    resumable: bool = True,
    checkpoint_at_utc: str = "2026-06-02T12:00:00+00:00",
    task: str = "audit the auth module",
) -> CheckpointRecord:
    return CheckpointRecord(
        schema_version=CHECKPOINT_SCHEMA_VERSION,
        run_id=run_id,
        department=department,
        chief=f"{department}-chief",
        task=task,
        directive_id=None,
        checkpoint_at_utc=checkpoint_at_utc,
        failure_class=failure_class,
        resumable=resumable,
        completed_specialists=(),
        message_history_ref="message_history.json",
        attempt=1,
    )


def _write(artifact_root: Path, record: CheckpointRecord) -> None:
    write_checkpoint(artifact_root / record.run_id, record)


def _handler(artifact_root: Path, registry=None) -> CommandHandler:
    h = CommandHandler.__new__(CommandHandler)
    h._departments = registry
    h._app = mock.MagicMock()
    h._app.config.zone4_artifact_root = str(artifact_root)
    return h


# ---------------------------------------------------------------------------
# /checkpoints
# ---------------------------------------------------------------------------

class TestCheckpointsCommand:
    @pytest.mark.asyncio
    async def test_checkpoints_command_lists_resumable(self, tmp_path):
        """Lists resumable checkpoints (run_id, department, failure_class), newest first."""
        root = tmp_path / "artifacts"
        _write(
            root,
            _make_record(
                run_id="run-old",
                department="qa",
                failure_class="usage_limit",
                checkpoint_at_utc="2026-06-01T08:00:00+00:00",
            ),
        )
        _write(
            root,
            _make_record(
                run_id="run-new",
                department="ops",
                failure_class="timeout",
                checkpoint_at_utc="2026-06-02T20:00:00+00:00",
            ),
        )
        # A non-resumable checkpoint must be filtered OUT.
        _write(
            root,
            _make_record(
                run_id="run-dead",
                department="design",
                failure_class="validation_error",
                resumable=False,
            ),
        )

        handler = _handler(root)
        out = await handler._cmd_checkpoints("chat1", "")

        assert "run-new" in out
        assert "run-old" in out
        assert "qa" in out
        assert "ops" in out
        assert "usage_limit" in out
        assert "timeout" in out
        # Non-resumable record is excluded.
        assert "run-dead" not in out
        # Newest first: run-new appears before run-old.
        assert out.index("run-new") < out.index("run-old")

    @pytest.mark.asyncio
    async def test_checkpoints_empty_state(self, tmp_path):
        """Empty-state message when no resumable checkpoints exist."""
        root = tmp_path / "artifacts"
        root.mkdir(parents=True, exist_ok=True)
        # Only a non-resumable checkpoint present → still empty for the operator.
        _write(root, _make_record(run_id="run-dead", resumable=False))

        handler = _handler(root)
        out = await handler._cmd_checkpoints("chat1", "")

        assert "no resumable" in out.lower()

    @pytest.mark.asyncio
    async def test_checkpoints_missing_artifact_root(self):
        """Friendly message when artifact_root is not configured."""
        h = CommandHandler.__new__(CommandHandler)
        h._departments = None
        h._app = mock.MagicMock()
        h._app.config.zone4_artifact_root = None

        out = await h._cmd_checkpoints("chat1", "")
        assert "artifact" in out.lower()

    @pytest.mark.asyncio
    async def test_checkpoints_in_bridge_commands(self):
        """checkpoints is registered in BRIDGE_COMMANDS (Tier 2 Z4)."""
        from bridge.commands import BRIDGE_COMMANDS

        assert "checkpoints" in BRIDGE_COMMANDS


# ---------------------------------------------------------------------------
# /resume <run_id>
# ---------------------------------------------------------------------------

class TestResumeCommand:
    @pytest.mark.asyncio
    async def test_resume_command_dispatches(self, tmp_path):
        """/resume <run_id> re-dispatches the department with resume_from set."""
        root = tmp_path / "artifacts"
        _write(
            root,
            _make_record(
                run_id="run-42",
                department="qa",
                task="audit the auth module",
            ),
        )

        registry = mock.MagicMock()
        registry.department_names.return_value = ["qa", "ops"]
        result = mock.MagicMock()
        result.success = True
        result.duration_seconds = 1.5
        result.manager_output = "resumed and finished"
        result.run_id = "run-99"
        registry.route = mock.AsyncMock(return_value=result)

        handler = _handler(root, registry=registry)

        with mock.patch(
            "teams._types.BridgeDeps.from_app",
            return_value=mock.MagicMock(),
        ):
            out = await handler._cmd_resume("chat1", "run-42")

        # Routed to the checkpoint's department with resume_from threaded.
        registry.route.assert_awaited_once()
        call = registry.route.await_args
        assert call.args[0] == "qa"
        assert call.kwargs.get("resume_from") == "run-42"
        # New run_id surfaced to the operator.
        assert "run-99" in out

    @pytest.mark.asyncio
    async def test_resume_no_args_clears_halt(self):
        """/resume with no args preserves the legacy halt-clear behaviour."""
        h = CommandHandler.__new__(CommandHandler)
        h._halted = True

        out = await h._cmd_resume("chat1", "")
        assert h._halted is False
        assert "resumed" in out.lower()

    @pytest.mark.asyncio
    async def test_resume_unknown_run_id(self, tmp_path):
        """/resume <run_id> with no matching checkpoint returns a friendly error."""
        root = tmp_path / "artifacts"
        root.mkdir(parents=True, exist_ok=True)
        registry = mock.MagicMock()
        registry.department_names.return_value = ["qa"]
        registry.route = mock.AsyncMock()

        handler = _handler(root, registry=registry)
        out = await handler._cmd_resume("chat1", "run-nope")

        assert "run-nope" in out
        assert "no" in out.lower() or "not" in out.lower()
        registry.route.assert_not_awaited()
