"""Structured Kanban task pipeline with state-machine transitions.

Provides a TaskPipeline that manages tasks through a well-defined
lifecycle: inbox -> assigned -> in_progress -> review -> quality_review -> done.
Failed tasks can be retried by moving them back to inbox.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bridge.database import Database

logger = logging.getLogger(__name__)


class TaskStatus(Enum):
    """Task lifecycle states in the Kanban pipeline."""

    inbox = "inbox"
    assigned = "assigned"
    in_progress = "in_progress"
    review = "review"
    quality_review = "quality_review"
    done = "done"
    failed = "failed"


class TaskPriority(Enum):
    """Task priority levels, ordered from lowest to highest urgency."""

    low = "low"
    medium = "medium"
    high = "high"
    critical = "critical"
    urgent = "urgent"


# Numeric weight for sorting — higher value = higher priority.
PRIORITY_ORDER: dict[str, int] = {
    TaskPriority.low.value: 0,
    TaskPriority.medium.value: 1,
    TaskPriority.high.value: 2,
    TaskPriority.critical.value: 3,
    TaskPriority.urgent.value: 4,
}

# Valid state transitions: source -> set of allowed targets.
VALID_TRANSITIONS: dict[TaskStatus, set[TaskStatus]] = {
    TaskStatus.inbox: {TaskStatus.assigned, TaskStatus.failed},
    TaskStatus.assigned: {TaskStatus.in_progress, TaskStatus.inbox, TaskStatus.failed},
    TaskStatus.in_progress: {TaskStatus.review, TaskStatus.inbox, TaskStatus.failed},
    TaskStatus.review: {TaskStatus.quality_review, TaskStatus.in_progress, TaskStatus.failed},
    TaskStatus.quality_review: {TaskStatus.done, TaskStatus.review, TaskStatus.failed},
    TaskStatus.failed: {TaskStatus.inbox},
    TaskStatus.done: set(),  # terminal — no transitions out
}

_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS task_pipeline (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    description TEXT DEFAULT '',
    status TEXT NOT NULL DEFAULT 'inbox',
    priority TEXT NOT NULL DEFAULT 'medium',
    assigned_to TEXT,
    source TEXT DEFAULT 'manual',
    project TEXT DEFAULT '',
    retry_count INTEGER DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
)
"""

_CREATE_INDEXES_SQL = [
    "CREATE INDEX IF NOT EXISTS idx_task_pipeline_status ON task_pipeline(status)",
    "CREATE INDEX IF NOT EXISTS idx_task_pipeline_priority ON task_pipeline(priority)",
    "CREATE INDEX IF NOT EXISTS idx_task_pipeline_assigned ON task_pipeline(assigned_to)",
    "CREATE INDEX IF NOT EXISTS idx_task_pipeline_project ON task_pipeline(project)",
]

_MIGRATIONS = [
    "ALTER TABLE task_pipeline ADD COLUMN project TEXT DEFAULT ''",
]


class TaskPipeline:
    """Manages tasks through a Kanban pipeline backed by SQLite.

    Parameters
    ----------
    db:
        An async Database instance that exposes ``execute``, ``fetchone``,
        ``fetchall``, and ``commit`` coroutines.
    """

    def __init__(self, db: Database) -> None:
        self.db = db

    # ------------------------------------------------------------------
    # Schema
    # ------------------------------------------------------------------

    async def initialize(self) -> None:
        """Create the ``task_pipeline`` table and indexes if they do not exist."""
        await self.db.execute(_CREATE_TABLE_SQL)
        # Run migrations before indexes (indexes may reference new columns)
        for migration in _MIGRATIONS:
            try:
                await self.db.execute(migration)
            except Exception:
                pass  # Column already exists
        for idx_sql in _CREATE_INDEXES_SQL:
            await self.db.execute(idx_sql)
        await self.db.commit()
        logger.info("task_pipeline table initialized")

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    async def create_task(
        self,
        title: str,
        description: str = "",
        priority: str = "medium",
        assigned_to: str | None = None,
        source: str = "manual",
        project: str = "",
    ) -> int:
        """Insert a new task into the pipeline and return its id.

        Raises
        ------
        ValueError
            If *priority* is not a recognised ``TaskPriority`` value.
        """
        # Validate priority
        if priority not in {p.value for p in TaskPriority}:
            raise ValueError(
                f"Invalid priority '{priority}'. "
                f"Must be one of: {', '.join(p.value for p in TaskPriority)}"
            )

        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        cursor = await self.db.execute(
            """
            INSERT INTO task_pipeline (title, description, priority, assigned_to, source, project, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (title, description, priority, assigned_to, source, project, now, now),
        )
        await self.db.commit()
        task_id: int = cursor.lastrowid
        logger.info("Created task %d: %s (priority=%s, source=%s)", task_id, title, priority, source)
        return task_id

    async def get_task(self, task_id: int) -> dict | None:
        """Return a single task as a dict, or ``None`` if not found."""
        row = await self.db.fetchone(
            "SELECT * FROM task_pipeline WHERE id = ?",
            (task_id,),
        )
        if row is None:
            return None
        return dict(row)

    # ------------------------------------------------------------------
    # State machine
    # ------------------------------------------------------------------

    async def move_task(self, task_id: int, new_status: str) -> bool:
        """Transition a task to *new_status*, enforcing the state machine.

        Returns ``True`` on success.

        Raises
        ------
        ValueError
            If the transition is not permitted by the state machine, or if
            *new_status* is not a valid ``TaskStatus`` value, or if the task
            does not exist.
        """
        # Validate new_status
        try:
            target = TaskStatus(new_status)
        except ValueError:
            raise ValueError(
                f"Invalid status '{new_status}'. "
                f"Must be one of: {', '.join(s.value for s in TaskStatus)}"
            )

        task = await self.get_task(task_id)
        if task is None:
            raise ValueError(f"Task {task_id} not found")

        current = TaskStatus(task["status"])
        allowed = VALID_TRANSITIONS.get(current, set())

        if target not in allowed:
            raise ValueError(
                f"Invalid transition: {current.value} -> {target.value}. "
                f"Allowed targets from '{current.value}': "
                f"{', '.join(s.value for s in allowed) or '(none — terminal state)'}"
            )

        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

        # Increment retry_count when recovering from failed back to inbox
        if current == TaskStatus.failed and target == TaskStatus.inbox:
            await self.db.execute(
                """
                UPDATE task_pipeline
                SET status = ?, retry_count = retry_count + 1, updated_at = ?
                WHERE id = ?
                """,
                (target.value, now, task_id),
            )
        else:
            await self.db.execute(
                """
                UPDATE task_pipeline
                SET status = ?, updated_at = ?
                WHERE id = ?
                """,
                (target.value, now, task_id),
            )

        await self.db.commit()
        logger.info("Task %d: %s -> %s", task_id, current.value, target.value)
        return True

    async def assign_task(self, task_id: int, assigned_to: str) -> bool:
        """Set the ``assigned_to`` field on a task.

        Returns ``True`` on success, ``False`` if the task does not exist.
        """
        task = await self.get_task(task_id)
        if task is None:
            return False

        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        await self.db.execute(
            "UPDATE task_pipeline SET assigned_to = ?, updated_at = ? WHERE id = ?",
            (assigned_to, now, task_id),
        )
        await self.db.commit()
        logger.info("Task %d assigned to %s", task_id, assigned_to)
        return True

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    async def list_tasks(self, status: str | None = None) -> list[dict]:
        """Return tasks ordered by priority (urgent first), then creation time.

        If *status* is provided, only tasks with that status are returned.
        """
        # Build a CASE expression so SQLite sorts by priority weight descending.
        when_clauses = " ".join(
            f"WHEN '{pval}' THEN {weight}" for pval, weight in PRIORITY_ORDER.items()
        )
        order_clause = f"ORDER BY (CASE priority {when_clauses} ELSE 0 END) DESC, created_at ASC"

        if status is not None:
            rows = await self.db.fetchall(
                f"SELECT * FROM task_pipeline WHERE status = ? {order_clause}",
                (status,),
            )
        else:
            rows = await self.db.fetchall(
                f"SELECT * FROM task_pipeline {order_clause}",
            )

        return [dict(r) for r in rows]

    async def list_by_project(self, project: str) -> list[dict]:
        """List all tasks for a specific project, ordered by priority then creation time."""
        when_clauses = " ".join(
            f"WHEN '{pval}' THEN {weight}" for pval, weight in PRIORITY_ORDER.items()
        )
        order_clause = f"ORDER BY (CASE priority {when_clauses} ELSE 0 END) DESC, created_at ASC"
        rows = await self.db.fetchall(
            f"SELECT * FROM task_pipeline WHERE project = ? {order_clause}",
            (project,),
        )
        return [dict(r) for r in rows]

    async def get_pipeline_summary(self) -> dict[str, int]:
        """Return a dict mapping each status to its task count.

        Statuses with zero tasks are included with a count of ``0``.
        """
        rows = await self.db.fetchall(
            "SELECT status, COUNT(*) as count FROM task_pipeline GROUP BY status",
        )
        summary: dict[str, int] = {s.value: 0 for s in TaskStatus}
        for row in rows:
            summary[row["status"]] = row["count"]
        return summary
