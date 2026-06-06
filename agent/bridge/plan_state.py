"""Structured plan state — machine-readable plans that persist across sessions.

Plans are immutable state machines: each step has a status, dependencies,
and checkpoint notes. Advancing a step returns a new PlanState instance.

Persistence: JSON files in data/plans/{plan_id}.json
Pattern: follows WorkOrder (frozen dataclasses, transition returns new instance)

Integration:
    - Created by /orc:plan-feature, /orc:quick
    - Updated by agent during execution
    - Loaded by session_context_builder on SessionStart
    - Checkpointed by workflow_checkpoint on Stop
"""
from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger(__name__)

VALID_STEP_STATUSES = frozenset({"pending", "in_progress", "completed", "blocked", "skipped"})

# E3.3 — module-level hook list for step-completion events.
# Callbacks receive (step_id: str, plan_id: str). Wrapped in try/except at callsite.
_completion_hooks: list[Callable[[str, str], None]] = []


def register_completion_hook(callback: Callable[[str, str], None]) -> None:
    """Register a callback to fire when a plan step reaches `completed` status."""
    _completion_hooks.append(callback)


@dataclass(frozen=True)
class PlanStep:
    """A single step in a plan."""
    id: str
    title: str
    status: str = "pending"
    dependencies: tuple[str, ...] = ()
    checkpoint: str | None = None
    started_at: str | None = None
    completed_at: str | None = None

    def __init__(
        self,
        id: str,
        title: str,
        status: str = "pending",
        dependencies: tuple[str, ...] | list[str] = (),
        checkpoint: str | None = None,
        started_at: str | None = None,
        completed_at: str | None = None,
    ) -> None:
        object.__setattr__(self, "id", id)
        object.__setattr__(self, "title", title)
        object.__setattr__(self, "status", status)
        object.__setattr__(self, "dependencies", tuple(dependencies))
        object.__setattr__(self, "checkpoint", checkpoint)
        object.__setattr__(self, "started_at", started_at)
        object.__setattr__(self, "completed_at", completed_at)


@dataclass(frozen=True)
class PlanState:
    """Immutable plan state. Mutations return new instances."""
    plan_id: str
    title: str
    project: str
    steps: tuple[PlanStep, ...]
    current_step_id: str | None = None
    created_at: str = ""
    updated_at: str = ""

    @classmethod
    def create(
        cls,
        *,
        title: str,
        project: str,
        steps: list[PlanStep],
    ) -> PlanState:
        now = datetime.now(timezone.utc).isoformat()
        return cls(
            plan_id=str(uuid.uuid4()),
            title=title,
            project=project,
            steps=tuple(steps),
            current_step_id=None,
            created_at=now,
            updated_at=now,
        )

    def get_step(self, step_id: str) -> PlanStep:
        """Retrieve a step by ID. Raises KeyError if not found."""
        for s in self.steps:
            if s.id == step_id:
                return s
        raise KeyError(f"Step {step_id!r} not found in plan {self.plan_id!r}")

    def advance(
        self,
        step_id: str,
        status: str,
        checkpoint: str | None = None,
    ) -> PlanState:
        """Return new PlanState with the given step updated.

        Raises:
            ValueError: If status is not a valid step status.
            KeyError: If step_id does not exist in this plan.
        """
        if status not in VALID_STEP_STATUSES:
            raise ValueError(f"Invalid step status: {status!r}. Must be one of {sorted(VALID_STEP_STATUSES)}")

        # Validate step exists (raises KeyError if not)
        self.get_step(step_id)

        now = datetime.now(timezone.utc).isoformat()
        new_steps: list[PlanStep] = []

        for s in self.steps:
            if s.id == step_id:
                kwargs: dict[str, Any] = {"status": status}
                if checkpoint is not None:
                    kwargs["checkpoint"] = checkpoint
                if status == "in_progress" and not s.started_at:
                    kwargs["started_at"] = now
                if status == "completed":
                    kwargs["completed_at"] = now
                new_steps.append(replace(s, **kwargs))
            else:
                new_steps.append(s)

        # Track current step when moving to in_progress
        current = step_id if status == "in_progress" else self.current_step_id

        result = replace(
            self,
            steps=tuple(new_steps),
            current_step_id=current,
            updated_at=now,
        )

        # E3.3 — fire completion hooks after the new state is assembled.
        if status == "completed":
            for hook in _completion_hooks:
                try:
                    hook(step_id, self.plan_id)
                except Exception as exc:
                    logger.warning("plan_state: completion hook %r failed: %s", hook, exc)

        return result

    def next_actionable(self) -> PlanStep | None:
        """Return next pending step whose dependencies are all completed.

        Steps in any non-pending status are skipped. Steps with unmet
        dependencies are skipped. Returns the first actionable step in
        declaration order.
        """
        completed_ids = frozenset(s.id for s in self.steps if s.status == "completed")

        for s in self.steps:
            if s.status != "pending":
                continue
            deps_met = all(d in completed_ids for d in s.dependencies)
            if deps_met:
                return s
        return None

    def to_dict(self) -> dict[str, Any]:
        """Serialize plan to a JSON-serializable dict."""
        return {
            "plan_id": self.plan_id,
            "title": self.title,
            "project": self.project,
            "current_step_id": self.current_step_id,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "steps": [
                {
                    "id": s.id,
                    "title": s.title,
                    "status": s.status,
                    "dependencies": list(s.dependencies),
                    "checkpoint": s.checkpoint,
                    "started_at": s.started_at,
                    "completed_at": s.completed_at,
                }
                for s in self.steps
            ],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PlanState:
        """Deserialize plan from a dict (as produced by to_dict)."""
        steps = [
            PlanStep(
                id=s["id"],
                title=s["title"],
                status=s.get("status", "pending"),
                dependencies=s.get("dependencies", []),
                checkpoint=s.get("checkpoint"),
                started_at=s.get("started_at"),
                completed_at=s.get("completed_at"),
            )
            for s in data.get("steps", [])
        ]
        return cls(
            plan_id=data["plan_id"],
            title=data["title"],
            project=data["project"],
            steps=tuple(steps),
            current_step_id=data.get("current_step_id"),
            created_at=data.get("created_at", ""),
            updated_at=data.get("updated_at", ""),
        )

    def save(self, plans_dir: str | Path) -> Path:
        """Persist plan state as JSON. Creates directory if needed.

        Returns the path of the written file.
        """
        d = Path(plans_dir)
        d.mkdir(parents=True, exist_ok=True)
        path = d / f"{self.plan_id}.json"
        path.write_text(json.dumps(self.to_dict(), indent=2))
        return path

    @classmethod
    def load(cls, plan_id: str, plans_dir: str | Path) -> PlanState | None:
        """Load plan state from JSON file.

        Returns None if the file does not exist or cannot be parsed.
        """
        path = Path(plans_dir) / f"{plan_id}.json"
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text())
            return cls.from_dict(data)
        except (json.JSONDecodeError, KeyError, OSError) as e:
            logger.warning("Failed to load plan %s: %s", plan_id, e)
            return None


# ---------------------------------------------------------------------------
# Sprint State — externalized sprint tracking (#261)
# ---------------------------------------------------------------------------

VALID_SPRINT_STATUSES = frozenset({
    "pending", "in_progress", "complete",
    "skipped_with_approval", "blocked",
})


class SprintBoundaryViolation(Exception):
    """Raised when the agent attempts to work on a non-actionable sprint."""


@dataclass(frozen=True)
class SprintRow:
    """A single row from sprint-state.md."""
    sprint_id: str
    phase: str
    status: str
    started: str = ""
    completed: str = ""
    operator_signature: str = ""
    notes: str = ""


def load_sprint_state(state_path: str | Path) -> list[SprintRow]:
    """Parse sprint-state.md into a list of SprintRow objects.

    Reads the markdown table, skipping header rows and non-table lines.
    Returns rows in declaration order.
    """
    path = Path(state_path)
    if not path.exists():
        logger.warning("Sprint state file not found: %s", path)
        return []

    rows: list[SprintRow] = []
    in_table = False

    for line in path.read_text().splitlines():
        stripped = line.strip()
        if not stripped.startswith("|"):
            if in_table:
                break  # end of table
            continue

        cells = [c.strip() for c in stripped.split("|")]
        # Remove empty first/last from leading/trailing pipes
        cells = [c for c in cells if c or cells.index(c) not in (0, len(cells) - 1)]
        if len(cells) < 1:
            cells = [c.strip() for c in stripped.strip("|").split("|")]

        # Skip header row
        if cells[0].lower() in ("sprint", ""):
            in_table = True
            continue
        # Skip separator row (----)
        if all(c.replace("-", "").replace(":", "").strip() == "" for c in cells):
            continue

        in_table = True
        if len(cells) >= 3:
            rows.append(SprintRow(
                sprint_id=cells[0].strip(),
                phase=cells[1].strip() if len(cells) > 1 else "",
                status=cells[2].strip() if len(cells) > 2 else "pending",
                started=cells[3].strip() if len(cells) > 3 else "",
                completed=cells[4].strip() if len(cells) > 4 else "",
                operator_signature=cells[5].strip() if len(cells) > 5 else "",
                notes=cells[6].strip() if len(cells) > 6 else "",
            ))

    return rows


def next_actionable_sprint(rows: list[SprintRow]) -> SprintRow | None:
    """Return the next sprint that should be worked on.

    Priority:
    1. First in_progress sprint (resume it)
    2. First pending sprint (start it)

    Skipped, complete, and blocked sprints are not actionable.
    """
    # Resume any in-progress sprint first
    for r in rows:
        if r.status == "in_progress":
            return r
    # Then find first pending
    for r in rows:
        if r.status == "pending":
            return r
    return None


def verify_sprint_boundary(
    rows: list[SprintRow],
    requested_sprint_id: str,
) -> None:
    """Verify that the requested sprint is the next actionable one.

    Raises SprintBoundaryViolation if the agent is trying to work on
    a sprint that isn't the next-actionable one.
    """
    actionable = next_actionable_sprint(rows)
    if actionable is None:
        raise SprintBoundaryViolation(
            f"No actionable sprints remain. Cannot work on {requested_sprint_id!r}."
        )
    if actionable.sprint_id != requested_sprint_id:
        raise SprintBoundaryViolation(
            f"Sprint {requested_sprint_id!r} is not actionable. "
            f"Next actionable sprint is {actionable.sprint_id!r} "
            f"(status: {actionable.status})."
        )


def format_sprint_context(rows: list[SprintRow]) -> str:
    """Format sprint state for injection into session context.

    Returns a human-readable summary of the current sprint state
    suitable for injection into the agent's system prompt.
    """
    actionable = next_actionable_sprint(rows)
    if actionable is None:
        return "All sprints are complete or blocked. No actionable work."

    completed = sum(1 for r in rows if r.status == "complete")
    total = len(rows)
    pending = sum(1 for r in rows if r.status == "pending")
    blocked = sum(1 for r in rows if r.status == "blocked")

    lines = [
        f"## Sprint State ({completed}/{total} complete, {pending} pending, {blocked} blocked)",
        "",
        f"**Next actionable:** Sprint {actionable.sprint_id} (Phase {actionable.phase})",
        f"**Status:** {actionable.status}",
    ]
    if actionable.notes and actionable.notes != "—":
        lines.append(f"**Notes:** {actionable.notes}")

    lines.append("")
    lines.append("You MUST work on this sprint only. Do not skip or reorder.")
    lines.append("Skipping requires operator signature in sprint-state.md.")

    return "\n".join(lines)
