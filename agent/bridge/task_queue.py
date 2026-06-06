"""Human-in-the-Loop task queue for async question/answer flows.

When Claude responds with numbered options, the bridge detects them,
creates a task, presents buttons to the user, and resumes the Claude
session with the user's choice.

Z4/F-W.4 — Operator Gate Primitive
-----------------------------------
``set_awaiting_approval(task_id, question, options)`` puts a task in the
``awaiting_approval`` state and signals a paired ``asyncio.Event`` when the
operator calls ``/approve`` or ``/reject``.

Workflow engine usage::

    gate_event = asyncio.Event()
    task_id = await tq.create(chat_id, ...)
    await tq.set_awaiting_approval(task_id, "Approve?", gate_event)
    await asyncio.wait_for(gate_event.wait(), timeout=3600)
    result_task = await tq.get(task_id)
    approved = result_task.approval_granted
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from dataclasses import dataclass
from typing import Any

from .database import Database

log = logging.getLogger(__name__)

# In-memory registry mapping task_id → asyncio.Event for pending gates.
# Populated by set_awaiting_approval, cleared by approve/reject.
_approval_events: dict[int, asyncio.Event] = {}


@dataclass
class AsyncTask:
    """A task awaiting human input or completion."""

    id: int
    status: str  # pending, needs_input, awaiting_approval, completed, failed
    prompt: str | None
    session_id: str | None
    claude_session_id: str | None
    pending_question: str | None
    pending_options: list[str] | None
    user_response: str | None
    result: str | None
    chat_id: str
    created_at: str
    updated_at: str
    # Gate-specific fields (populated when status='awaiting_approval')
    approval_granted: bool | None = None  # True=approved, False=rejected
    approval_reason: str | None = None    # Rejection reason from operator


class TaskQueue:
    """Manages async tasks that require human input."""

    def __init__(self, db: Database) -> None:
        self._db = db

    async def create(
        self,
        chat_id: str,
        *,
        prompt: str | None = None,
        session_id: str | None = None,
        claude_session_id: str | None = None,
        pending_question: str | None = None,
        pending_options: list[str] | None = None,
    ) -> int:
        """Create a new task. Returns the task ID."""
        options_json = json.dumps(pending_options) if pending_options else None
        cursor = await self._db.execute(
            """INSERT INTO async_tasks
               (status, prompt, session_id, claude_session_id,
                pending_question, pending_options, chat_id)
               VALUES ('needs_input', ?, ?, ?, ?, ?, ?)""",
            (prompt, session_id, claude_session_id, pending_question, options_json, chat_id),
        )
        await self._db.commit()
        task_id = cursor.lastrowid or 0
        log.info("Created HITL task %d for chat %s", task_id, chat_id)
        return task_id

    async def get(self, task_id: int) -> AsyncTask | None:
        """Get a task by ID."""
        row = await self._db.fetchone(
            "SELECT * FROM async_tasks WHERE id = ?", (task_id,),
        )
        if not row:
            return None
        return self._row_to_task(row)

    async def set_needs_input(
        self, task_id: int, question: str, options: list[str]
    ) -> None:
        """Mark a task as needing user input."""
        await self._db.execute(
            """UPDATE async_tasks
               SET status = 'needs_input',
                   pending_question = ?,
                   pending_options = ?,
                   updated_at = datetime('now')
               WHERE id = ?""",
            (question, json.dumps(options), task_id),
        )
        await self._db.commit()

    async def submit_response(self, task_id: int, response: str) -> None:
        """Submit the user's response to a task."""
        await self._db.execute(
            """UPDATE async_tasks
               SET status = 'pending',
                   user_response = ?,
                   updated_at = datetime('now')
               WHERE id = ?""",
            (response, task_id),
        )
        await self._db.commit()
        log.info("Task %d: user responded with '%s'", task_id, response[:50])

    async def complete(self, task_id: int, result: str) -> None:
        """Mark a task as completed with a result."""
        await self._db.execute(
            """UPDATE async_tasks
               SET status = 'completed',
                   result = ?,
                   updated_at = datetime('now')
               WHERE id = ?""",
            (result, task_id),
        )
        await self._db.commit()

    async def fail(self, task_id: int, error: str) -> None:
        """Mark a task as failed."""
        await self._db.execute(
            """UPDATE async_tasks
               SET status = 'failed',
                   result = ?,
                   updated_at = datetime('now')
               WHERE id = ?""",
            (error, task_id),
        )
        await self._db.commit()

    async def get_next_pending_with_response(self) -> AsyncTask | None:
        """Get the oldest task that has a user response and is pending."""
        row = await self._db.fetchone(
            """SELECT * FROM async_tasks
               WHERE status = 'pending'
               AND user_response IS NOT NULL
               ORDER BY created_at ASC
               LIMIT 1""",
        )
        if not row:
            return None
        return self._row_to_task(row)

    # ------------------------------------------------------------------
    # Operator gate primitives (Z4/F-W.4)
    # ------------------------------------------------------------------

    async def set_awaiting_approval(
        self,
        task_id: int,
        question: str,
        gate_event: asyncio.Event,
    ) -> None:
        """Pause a task pending operator approval.

        Records the question in ``pending_question``, sets ``status`` to
        ``awaiting_approval``, and registers ``gate_event`` in the in-memory
        registry.  The calling coroutine should then ``await gate_event.wait()``
        with an appropriate timeout.

        The operator unblocks execution via ``/approve <task_id>`` or
        ``/reject <task_id> <reason>``.
        """
        await self._db.execute(
            """UPDATE async_tasks
               SET status = 'awaiting_approval',
                   pending_question = ?,
                   updated_at = datetime('now')
               WHERE id = ?""",
            (question, task_id),
        )
        await self._db.commit()
        _approval_events[task_id] = gate_event
        log.info("Task %d set to awaiting_approval: %s", task_id, question[:80])

    async def approve(self, task_id: int) -> bool:
        """Mark a gate task as approved and wake the waiting workflow.

        Returns True if the task was in awaiting_approval state.
        Returns False if the task was not found or not in the right state.
        """
        task = await self.get(task_id)
        if task is None or task.status != "awaiting_approval":
            return False

        await self._db.execute(
            """UPDATE async_tasks
               SET status = 'pending',
                   result = 'approved',
                   updated_at = datetime('now')
               WHERE id = ?""",
            (task_id,),
        )
        await self._db.commit()
        log.info("Task %d approved by operator", task_id)

        event = _approval_events.pop(task_id, None)
        if event is not None:
            event.set()
        return True

    async def reject(self, task_id: int, reason: str = "") -> bool:
        """Mark a gate task as rejected and wake (with rejection) the waiting workflow.

        Returns True if the task was in awaiting_approval state.
        Returns False if the task was not found or not in the right state.
        """
        task = await self.get(task_id)
        if task is None or task.status != "awaiting_approval":
            return False

        rejection_note = f"rejected: {reason}" if reason else "rejected"
        await self._db.execute(
            """UPDATE async_tasks
               SET status = 'failed',
                   result = ?,
                   updated_at = datetime('now')
               WHERE id = ?""",
            (rejection_note, task_id),
        )
        await self._db.commit()
        log.info("Task %d rejected by operator: %s", task_id, reason)

        event = _approval_events.pop(task_id, None)
        if event is not None:
            event.set()
        return True

    async def get_awaiting_approval(self) -> list[AsyncTask]:
        """Return all tasks currently waiting for operator approval."""
        rows = await self._db.fetchall(
            "SELECT * FROM async_tasks WHERE status = 'awaiting_approval' "
            "ORDER BY created_at ASC",
        )
        return [self._row_to_task(r) for r in rows]

    async def get_stale(self, max_age_hours: float = 2.0) -> list[AsyncTask]:
        """Get tasks stuck in needs_input for too long."""
        rows = await self._db.fetchall(
            """SELECT * FROM async_tasks
               WHERE status = 'needs_input'
               AND updated_at < datetime('now', ? || ' hours')
               ORDER BY created_at ASC""",
            (f"-{max_age_hours}",),
        )
        return [self._row_to_task(r) for r in rows]

    async def get_tasks_for_chat(
        self, chat_id: str, limit: int = 10
    ) -> list[AsyncTask]:
        """Get recent tasks for a chat."""
        rows = await self._db.fetchall(
            """SELECT * FROM async_tasks
               WHERE chat_id = ?
               ORDER BY created_at DESC
               LIMIT ?""",
            (chat_id, limit),
        )
        return [self._row_to_task(r) for r in rows]

    def _row_to_task(self, row: Any) -> AsyncTask:
        """Convert a database row to an AsyncTask."""
        options = None
        if row[6]:  # pending_options
            try:
                options = json.loads(row[6])
            except json.JSONDecodeError:
                options = None
        return AsyncTask(
            id=row[0],
            status=row[1],
            prompt=row[2],
            session_id=row[3],
            claude_session_id=row[4],
            pending_question=row[5],
            pending_options=options,
            user_response=row[7],
            result=row[8],
            chat_id=row[9],
            created_at=row[10],
            updated_at=row[11],
        )


def detect_question_with_options(text: str) -> tuple[str, list[str]] | None:
    """Detect a numbered option block in Claude's response.

    Looks for patterns like:
        1. Option A
        2. Option B
        3. Option C

    Returns (question_text, [options]) or None.
    """
    # Find numbered options block (at least 2 options)
    option_pattern = re.compile(r"^\s*(\d+)[.)]\s+(.+)$", re.MULTILINE)
    matches = list(option_pattern.finditer(text))

    if len(matches) < 2:
        return None

    # Verify options are sequential
    numbers = [int(m.group(1)) for m in matches]
    if numbers != list(range(numbers[0], numbers[0] + len(numbers))):
        return None

    options = [m.group(2).strip() for m in matches]

    # Extract the question (text before the first option)
    first_option_start = matches[0].start()
    question = text[:first_option_start].strip()

    # If no clear question text, use a generic prompt
    if not question:
        question = "Please choose an option:"

    return (question, options)
