"""Z3-05 — engineering artifacts, memory pointers, worktree hygiene.

Reuses the shared Zone 4 artifact primitives (``bridge.run_artifacts``, landed
in Z4-03/Z4-05) so the main-agent relay can point at engineering artifacts the
same way it points at Zone 4 artifacts. On top of the shared manifest this adds
an ``engineering`` block carrying zone (3), worktree, branch, changed files,
validation results, and — on failure — the preserved error surface.

This module does NOT modify ``bridge/run_artifacts.py`` (Zone 4 depends on its
frozen ``RunManifest`` shape); it composes it and augments the on-disk JSON.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal

from bridge.run_artifacts import RunWorkspace, create_run_workspace

ValidationStatus = Literal["pass", "fail", "skipped"]


@dataclass(frozen=True)
class EngineeringValidation:
    """One validation command and its terminal status."""

    command: str
    status: ValidationStatus


@dataclass(frozen=True)
class WorktreeStatus:
    """Worktree cleanliness snapshot. Dirty state is surfaced, never hidden."""

    clean: bool
    dirty_files: tuple[str, ...] = ()

    @property
    def ready_to_pr(self) -> bool:
        return self.clean and not self.dirty_files


def summarize_worktree_status(status: WorktreeStatus) -> str:
    if status.ready_to_pr:
        return "Worktree clean — ready to PR."
    listed = "\n".join(f"  - {path}" for path in status.dirty_files) or "  - (unknown)"
    return "Worktree dirty — NOT ready to PR. Uncommitted changes:\n" + listed


def build_engineering_memory_note(
    *,
    run_id: str,
    specialist: str,
    manifest_path: Path,
    changed_files: tuple[str, ...],
    validation_status: str,
) -> str:
    """Build the operator-readable memory pointer for an engineering run."""
    files = "\n".join(f"- {path}" for path in changed_files) or "- none"
    return "\n".join(
        [
            f"Zone3 engineering run: {run_id}",
            f"Specialist: {specialist}",
            f"Manifest: {manifest_path}",
            f"Validation: {validation_status}",
            "Changed files:",
            files,
        ]
    )


def write_engineering_manifest(
    artifact_root: Path | str,
    *,
    session_id: str,
    specialist: str,
    worktree: str,
    branch: str,
    changed_files: tuple[str, ...],
    validation: tuple[EngineeringValidation, ...],
    chief: str | None = None,
    directive_id: str | None = None,
    status: str = "complete",
    error_class: str | None = None,
    exit_code: int | None = None,
    stderr_excerpt: str | None = None,
    now: datetime | None = None,
    entropy: str | None = None,
) -> RunWorkspace:
    """Create a shared run workspace and augment it with engineering fields.

    The shared manifest keeps its Z4-compatible shape; an ``engineering`` block
    is added with ``zone: 3`` plus worktree/branch/changed-files/validation and
    (on failure) the preserved error surface.
    """
    workspace = create_run_workspace(
        artifact_root,
        session_id=session_id,
        department="engineering",
        directive_id=directive_id,
        chief=chief or specialist,
        now=now,
        entropy=entropy,
    )

    engineering_block: dict[str, object] = {
        "zone": 3,
        "specialist": specialist,
        "worktree": worktree,
        "branch": branch,
        "changed_files": list(changed_files),
        "validation": [
            {"command": item.command, "status": item.status} for item in validation
        ],
        "status": status,
    }
    if error_class is not None:
        engineering_block["error_class"] = error_class
    if exit_code is not None:
        engineering_block["exit_code"] = exit_code
    if stderr_excerpt is not None:
        engineering_block["stderr_excerpt"] = stderr_excerpt

    payload = json.loads(workspace.manifest_path.read_text(encoding="utf-8"))
    payload["engineering"] = engineering_block
    workspace.manifest_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return workspace


@dataclass(frozen=True)
class EngineeringRunRecord:
    """Composed artifacts of one engineering run: manifest + memory + hygiene."""

    run_id: str
    manifest_path: Path
    memory_note: str
    worktree_summary: str
    ready_to_pr: bool


def record_engineering_run(
    artifact_root: Path | str,
    *,
    session_id: str,
    specialist: str,
    worktree: str,
    branch: str,
    changed_files: tuple[str, ...],
    validation: tuple[EngineeringValidation, ...],
    worktree_status: WorktreeStatus,
    status: str = "complete",
    error_class: str | None = None,
    exit_code: int | None = None,
    stderr_excerpt: str | None = None,
    entropy: str | None = None,
) -> EngineeringRunRecord:
    """One call to persist a manifest, derive a memory note, and report hygiene.

    Convenience seam for the dispatcher / ``/engineering`` command path so the
    pure dispatcher stays I/O-free and tests inject the artifact root.
    """
    workspace = write_engineering_manifest(
        artifact_root,
        session_id=session_id,
        specialist=specialist,
        worktree=worktree,
        branch=branch,
        changed_files=changed_files,
        validation=validation,
        status=status,
        error_class=error_class,
        exit_code=exit_code,
        stderr_excerpt=stderr_excerpt,
        entropy=entropy,
    )
    validation_status = (
        "fail" if any(v.status == "fail" for v in validation) else status
    )
    note = build_engineering_memory_note(
        run_id=workspace.run_id,
        specialist=specialist,
        manifest_path=workspace.manifest_path,
        changed_files=changed_files,
        validation_status=validation_status,
    )
    return EngineeringRunRecord(
        run_id=workspace.run_id,
        manifest_path=workspace.manifest_path,
        memory_note=note,
        worktree_summary=summarize_worktree_status(worktree_status),
        ready_to_pr=worktree_status.ready_to_pr,
    )


__all__ = [
    "EngineeringRunRecord",
    "EngineeringValidation",
    "WorktreeStatus",
    "build_engineering_memory_note",
    "record_engineering_run",
    "summarize_worktree_status",
    "write_engineering_manifest",
]
