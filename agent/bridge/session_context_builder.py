"""Session context builder — assembles task state for SessionStart injection.

Queries task_pipeline, work_orders, and pending edits to build a
structured context that tells the agent what work is pending when
a new session starts.

E1.3: adds capsule discovery + verbatim injection. When a hard-stop
capsule exists for the session being resumed, it is prepended to the
assembled context as a fenced JSON block so the agent sees the exact
sprint/PR/files from the previous session on its first turn.

Integration:
    - memory-session-start.sh calls this via Python subprocess
    - Output is JSON with tasks, approvals, stale items
    - Hook formats this into systemMessage
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

STALE_THRESHOLD_HOURS = 24


@dataclass(frozen=True)
class SessionContext:
    """Assembled session context for injection."""
    active_tasks: list[dict[str, Any]]
    pending_approvals: list[dict[str, Any]]
    stale_tasks: list[dict[str, Any]]
    recent_decisions: int
    capsule_block: str

    def __init__(
        self,
        active_tasks: list[dict[str, Any]] | None = None,
        pending_approvals: list[dict[str, Any]] | None = None,
        stale_tasks: list[dict[str, Any]] | None = None,
        recent_decisions: int = 0,
        capsule_block: str = "",
    ) -> None:
        object.__setattr__(self, "active_tasks", active_tasks if active_tasks is not None else [])
        object.__setattr__(self, "pending_approvals", pending_approvals if pending_approvals is not None else [])
        object.__setattr__(self, "stale_tasks", stale_tasks if stale_tasks is not None else [])
        object.__setattr__(self, "recent_decisions", recent_decisions)
        object.__setattr__(self, "capsule_block", capsule_block)


def load_capsule_for_session(
    session_id: str,
    checkpoint_dir: str | Path,
) -> dict[str, Any] | None:
    """Read and validate a v1 capsule from disk.

    Returns the raw capsule dict when a valid v1 capsule exists for
    *session_id*, or None if the file is absent, unreadable, or not v1.
    Unknown extra keys are accepted (forward-compatible no-op).
    """
    cp_path = Path(checkpoint_dir) / f"{session_id}.json"
    if not cp_path.exists():
        return None
    try:
        capsule = json.loads(cp_path.read_text())
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("E1.3: failed to read capsule %s: %s", cp_path, e)
        return None
    if not isinstance(capsule, dict):
        return None
    if capsule.get("capsule_version") != 1:
        logger.debug("E1.3: capsule %s has version != 1, skipping", cp_path)
        return None
    return capsule


def format_capsule_block(capsule: dict[str, Any]) -> str:
    """Render a v1 capsule dict as a fenced JSON block for injection."""
    header = "RESUMED FROM CAPSULE (capsule_version=1):"
    body = json.dumps(capsule, indent=2)
    return f"{header}\n```json\n{body}\n```"


async def build_session_context(
    db: Any,
    session_id: str = "",
    checkpoint_dir: str | Path = "",
) -> SessionContext:
    """Query database for active work state.

    Args:
        db: Async Database instance with fetchall/fetchone.
        session_id: Optional session ID for capsule discovery (E1.3).
        checkpoint_dir: Directory containing capsule JSON files (E1.3).

    Returns:
        SessionContext with active tasks, pending approvals, stale items,
        and (if a capsule exists) a pre-formatted capsule_block.
    """
    active_tasks: list[dict[str, Any]] = []
    stale_tasks: list[dict[str, Any]] = []
    pending_approvals: list[dict[str, Any]] = []
    recent_decisions = 0
    capsule_block = ""

    if session_id and checkpoint_dir:
        capsule = load_capsule_for_session(session_id, checkpoint_dir)
        if capsule is not None:
            capsule_block = format_capsule_block(capsule)

    # Active tasks (in_progress, review, or assigned)
    try:
        rows = await db.fetchall(
            "SELECT id, title, status, priority, assigned_to, project, updated_at "
            "FROM task_pipeline WHERE status IN ('in_progress', 'review', 'assigned') "
            "ORDER BY CASE priority "
            "WHEN 'urgent' THEN 4 WHEN 'critical' THEN 3 "
            "WHEN 'high' THEN 2 WHEN 'medium' THEN 1 ELSE 0 END DESC"
        )
        for row in rows:
            task = dict(row)
            active_tasks.append(task)

            # Check staleness
            updated = task.get("updated_at", "")
            if updated:
                try:
                    updated_dt = datetime.fromisoformat(updated.replace("Z", "+00:00"))
                    age = datetime.now(timezone.utc) - updated_dt
                    if age > timedelta(hours=STALE_THRESHOLD_HOURS):
                        stale_tasks.append(task)
                except ValueError:
                    pass
    except Exception as e:
        logger.warning("Failed to query task_pipeline: %s", e)

    # Pending memory edit approvals (Tier B)
    try:
        rows = await db.fetchall(
            "SELECT id, key, action, new_value, reason, created_at "
            "FROM memory_pending_edits ORDER BY created_at DESC LIMIT 5"
        )
        pending_approvals = [dict(r) for r in rows]
    except Exception:
        pass  # Table may not exist

    # Recent decision count
    try:
        row = await db.fetchone(
            "SELECT COUNT(*) as cnt FROM knowledge "
            "WHERE key LIKE 'decision:%' AND created_at > datetime('now', '-24 hours')"
        )
        recent_decisions = row["cnt"] if row else 0
    except Exception:
        pass

    return SessionContext(
        active_tasks=active_tasks,
        pending_approvals=pending_approvals,
        stale_tasks=stale_tasks,
        recent_decisions=recent_decisions,
        capsule_block=capsule_block,
    )


def format_session_context(ctx: SessionContext) -> str | None:
    """Format session context as text for hook systemMessage.

    Returns None if there's nothing to report.
    """
    parts: list[str] = []

    if ctx.capsule_block:
        parts.append(ctx.capsule_block)

    if ctx.active_tasks:
        parts.append("ACTIVE TASKS:")
        for task in ctx.active_tasks:
            tid = task.get("id", "?")
            title = task.get("title", "Untitled")
            status = task.get("status", "unknown")
            project = task.get("project", "")
            proj_label = f", project: {project}" if project else ""
            parts.append(f"  - [#{tid}] \"{title}\" ({status}{proj_label})")

    if ctx.stale_tasks:
        parts.append("\nSTALE TASKS (>24h without update):")
        for task in ctx.stale_tasks:
            tid = task.get("id", "?")
            title = task.get("title", "Untitled")
            updated = task.get("updated_at", "unknown")
            parts.append(f"  - [#{tid}] \"{title}\" (last updated: {updated})")

    if ctx.pending_approvals:
        parts.append(f"\nPENDING APPROVALS: {len(ctx.pending_approvals)} memory edit(s) awaiting operator review")

    if ctx.recent_decisions:
        parts.append(f"\n{ctx.recent_decisions} decision(s) recorded in last 24h")

    if not parts:
        return None

    return "\n".join(parts)


def build_sprint_context(state_path: str | Path) -> str | None:
    """Read sprint-state.md and return formatted context for injection.

    Returns None if the file doesn't exist or has no actionable sprints.
    """
    from .plan_state import load_sprint_state, format_sprint_context

    rows = load_sprint_state(state_path)
    if not rows:
        return None

    return format_sprint_context(rows)
