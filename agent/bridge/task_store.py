"""Task persistence for Phase 5 Sprint 21 (chief → specialist protocol).

Stores ``Task`` records and lifecycle transitions for tasks issued by a
department chief to one of its specialists. Mirrors the design of
``directive_store`` (Sprint 20) — every status transition appends a row to
``task_history`` so the lifecycle is reconstructible after a bridge
restart.

All queries are parameterised. The CHECK constraint on ``tasks.status``
(migration #11) is a defence-in-depth backstop, not the primary
validation layer.

Invariants:
- ``task_id`` is the primary key, generated server-side via
  ``new_task_id()``. Callers MUST use the helper.
- ``directive_id`` is a foreign key to ``directives``. NULL is allowed —
  it indicates the chief was invoked outside a directive flow (legacy
  ``/route``, cron path).
- Tasks are immutable once issued. Status moves on the row, history rows
  accumulate; the original ``Task`` envelope is never rewritten.
- All timestamps are ISO-8601 UTC strings.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Optional
from uuid import uuid4

from teams._types import Task, TaskStatus

if TYPE_CHECKING:
    from bridge.database import Database

log = logging.getLogger(__name__)


def new_task_id() -> str:
    """Generate a fresh task_id of the form ``task-<12-hex>``."""
    return f"task-{uuid4().hex[:12]}"


def _safe_publish(event_type: str, payload: dict, correlation_id: str) -> None:
    """Best-effort EventBus publish for task lifecycle events (Sprint 23)."""
    try:
        from bridge.event_bus import EventBus
        EventBus.get_instance().publish(
            event_type, payload, source="task_store",
            correlation_id=correlation_id,
        )
    except Exception as exc:  # noqa: BLE001
        log.debug("task_store.publish_failed type=%s error=%s", event_type, exc)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


async def insert_task(db: "Database", t: Task) -> None:
    """Persist a fresh Task in ``ASSIGNED`` status + first history row."""
    issued_at = t.issued_at_utc.isoformat()
    deadline = t.deadline_utc.isoformat() if t.deadline_utc else None
    now = _now_iso()
    await db.execute(
        """INSERT INTO tasks (
            task_id, directive_id, from_chief, to_specialist, description,
            constraints_json, deadline_utc, issued_at_utc, status,
            updated_at_utc
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            t.task_id,
            t.directive_id,
            t.from_chief,
            t.to_specialist,
            t.description,
            json.dumps(list(t.constraints)),
            deadline,
            issued_at,
            TaskStatus.ASSIGNED.value,
            now,
        ),
    )
    await db.execute(
        """INSERT INTO task_history (
            task_id, from_status, to_status, note, transitioned_at_utc
        ) VALUES (?, ?, ?, ?, ?)""",
        (t.task_id, None, TaskStatus.ASSIGNED.value, "assigned", now),
    )
    await db.commit()
    log.info(
        "task.inserted id=%s directive_id=%s to_specialist=%s",
        t.task_id, t.directive_id, t.to_specialist,
    )
    # Sprint 23: dashboard live-update event — emitted as
    # task.status_changed so /ws/events subscribers get a uniform event
    # shape across the lifecycle (insert is "→ assigned").
    _safe_publish(
        "task.status_changed",
        {
            "task_id": t.task_id,
            "directive_id": t.directive_id,
            "from_chief": t.from_chief,
            "to_specialist": t.to_specialist,
            "from_status": None,
            "to_status": TaskStatus.ASSIGNED.value,
        },
        t.directive_id or t.task_id,
    )


async def update_status(
    db: "Database",
    task_id: str,
    new_status: TaskStatus,
    *,
    note: Optional[str] = None,
) -> None:
    """Transition a task's status and append a history row atomically.

    Raises ``ValueError`` if ``task_id`` is unknown. No-op transitions
    (e.g. IN_PROGRESS → IN_PROGRESS on a retry) still append a history
    row so the audit log shows the retry.
    """
    row = await db.fetchone(
        "SELECT status FROM tasks WHERE task_id = ?", (task_id,)
    )
    if row is None:
        raise ValueError(f"Unknown task_id: {task_id}")

    prior_status = row["status"]
    now = _now_iso()
    await db.execute(
        "UPDATE tasks SET status = ?, updated_at_utc = ? WHERE task_id = ?",
        (new_status.value, now, task_id),
    )
    await db.execute(
        """INSERT INTO task_history (
            task_id, from_status, to_status, note, transitioned_at_utc
        ) VALUES (?, ?, ?, ?, ?)""",
        (task_id, prior_status, new_status.value, note, now),
    )
    await db.commit()
    log.info(
        "task.status_changed id=%s %s→%s", task_id, prior_status, new_status.value,
    )
    # Sprint 23: dashboard live-update event
    _safe_publish(
        "task.status_changed",
        {
            "task_id": task_id,
            "from_status": prior_status,
            "to_status": new_status.value,
            "note": note,
        },
        task_id,
    )


def _row_to_task(row: Any) -> Task:
    """Hydrate a SQLite row into a Task dataclass."""
    deadline_raw = row["deadline_utc"]
    deadline = (
        datetime.fromisoformat(deadline_raw) if deadline_raw else None
    )
    return Task(
        task_id=row["task_id"],
        directive_id=row["directive_id"],
        from_chief=row["from_chief"],
        to_specialist=row["to_specialist"],
        description=row["description"],
        constraints=tuple(json.loads(row["constraints_json"])),
        deadline_utc=deadline,
        issued_at_utc=datetime.fromisoformat(row["issued_at_utc"]),
    )


async def get_task(db: "Database", task_id: str) -> Optional[Task]:
    """Fetch a task envelope by id. Returns None if not found."""
    row = await db.fetchone(
        """SELECT task_id, directive_id, from_chief, to_specialist, description,
                  constraints_json, deadline_utc, issued_at_utc
           FROM tasks WHERE task_id = ?""",
        (task_id,),
    )
    if row is None:
        return None
    return _row_to_task(row)


async def get_status(db: "Database", task_id: str) -> Optional[TaskStatus]:
    """Fetch the live status of a task. Returns None if not found."""
    row = await db.fetchone(
        "SELECT status FROM tasks WHERE task_id = ?", (task_id,)
    )
    if row is None:
        return None
    return TaskStatus(row["status"])


_ACTIVE_STATUSES: tuple[str, ...] = (
    TaskStatus.ASSIGNED.value,
    TaskStatus.IN_PROGRESS.value,
)


async def list_active(db: "Database") -> list[Task]:
    """Return all tasks whose status is not terminal (DONE/BLOCKED/CANCELLED).

    Ordered by ``issued_at_utc`` descending so freshest work surfaces first.
    """
    placeholders = ", ".join("?" for _ in _ACTIVE_STATUSES)
    rows = await db.fetchall(
        f"""SELECT task_id, directive_id, from_chief, to_specialist, description,
                   constraints_json, deadline_utc, issued_at_utc
            FROM tasks
            WHERE status IN ({placeholders})
            ORDER BY issued_at_utc DESC""",
        _ACTIVE_STATUSES,
    )
    return [_row_to_task(r) for r in rows]


async def list_by_directive(
    db: "Database", directive_id: str
) -> list[Task]:
    """Return tasks tied to ``directive_id`` in chronological (issue) order."""
    rows = await db.fetchall(
        """SELECT task_id, directive_id, from_chief, to_specialist, description,
                  constraints_json, deadline_utc, issued_at_utc
           FROM tasks
           WHERE directive_id = ?
           ORDER BY issued_at_utc ASC""",
        (directive_id,),
    )
    return [_row_to_task(r) for r in rows]


async def list_by_chief(
    db: "Database", from_chief: str, *, include_terminal: bool = False
) -> list[Task]:
    """Return tasks issued by ``from_chief``, optionally including terminal ones."""
    if include_terminal:
        rows = await db.fetchall(
            """SELECT task_id, directive_id, from_chief, to_specialist, description,
                      constraints_json, deadline_utc, issued_at_utc
               FROM tasks
               WHERE from_chief = ?
               ORDER BY issued_at_utc DESC""",
            (from_chief,),
        )
    else:
        placeholders = ", ".join("?" for _ in _ACTIVE_STATUSES)
        rows = await db.fetchall(
            f"""SELECT task_id, directive_id, from_chief, to_specialist, description,
                       constraints_json, deadline_utc, issued_at_utc
                FROM tasks
                WHERE from_chief = ? AND status IN ({placeholders})
                ORDER BY issued_at_utc DESC""",
            (from_chief, *_ACTIVE_STATUSES),
        )
    return [_row_to_task(r) for r in rows]


async def list_all(db: "Database", *, limit: int = 100) -> list[Task]:
    """Return the most recent ``limit`` tasks regardless of status."""
    rows = await db.fetchall(
        """SELECT task_id, directive_id, from_chief, to_specialist, description,
                  constraints_json, deadline_utc, issued_at_utc
           FROM tasks
           ORDER BY issued_at_utc DESC
           LIMIT ?""",
        (limit,),
    )
    return [_row_to_task(r) for r in rows]


async def get_history(db: "Database", task_id: str) -> list[dict[str, Any]]:
    """Return the full lifecycle history for a task in transition order."""
    rows = await db.fetchall(
        """SELECT id, from_status, to_status, note, transitioned_at_utc
           FROM task_history
           WHERE task_id = ?
           ORDER BY id ASC""",
        (task_id,),
    )
    return [dict(r) for r in rows]


# Convenience wrappers used by the chief delegation path.


async def mark_in_progress(
    db: "Database", task_id: str, *, note: Optional[str] = None
) -> None:
    await update_status(db, task_id, TaskStatus.IN_PROGRESS, note=note)


async def mark_done(
    db: "Database", task_id: str, *, note: Optional[str] = None
) -> None:
    await update_status(db, task_id, TaskStatus.DONE, note=note)


async def mark_blocked(
    db: "Database", task_id: str, *, note: Optional[str] = None
) -> None:
    await update_status(db, task_id, TaskStatus.BLOCKED, note=note)


async def mark_cancelled(
    db: "Database", task_id: str, *, note: Optional[str] = None
) -> None:
    await update_status(db, task_id, TaskStatus.CANCELLED, note=note)
