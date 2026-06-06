"""SQLite-backed FIFO message queue with rate limiting and send_failed recovery."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import Any

from .database import Database


@dataclass
class QueuedMessage:
    """A message from the queue."""
    id: int
    platform_message_id: int
    chat_id: str
    text: str
    received_at: str
    status: str
    attempt_count: int


class MessageQueue:
    """SQLite-backed FIFO message queue supporting 6 statuses.

    Statuses: pending, processing, completed, failed, rate_limited, send_failed.
    """

    def __init__(self, db: Database) -> None:
        self._db = db
        self._lock = asyncio.Lock()

    async def enqueue(
        self,
        platform_message_id: int,
        chat_id: str,
        text: str,
    ) -> int:
        """Add a message to the queue. Returns the queue row ID."""
        cursor = await self._db.execute(
            """INSERT INTO message_queue (platform_message_id, chat_id, text)
               VALUES (?, ?, ?)""",
            (platform_message_id, chat_id, text),
        )
        await self._db.commit()
        return cursor.lastrowid or 0

    async def dequeue(self) -> QueuedMessage | None:
        """Atomically fetch and lock the next pending message (FIFO)."""
        async with self._lock:
            row = await self._db.fetchone(
                """SELECT id, platform_message_id, chat_id, text, received_at,
                          status, attempt_count
                   FROM message_queue
                   WHERE status = 'pending'
                   ORDER BY received_at ASC
                   LIMIT 1""",
            )
            if not row:
                return None

            msg = QueuedMessage(
                id=row[0],
                platform_message_id=row[1],
                chat_id=row[2],
                text=row[3],
                received_at=row[4],
                status=row[5],
                attempt_count=row[6],
            )

            await self._db.execute(
                """UPDATE message_queue
                   SET status = 'processing', attempt_count = attempt_count + 1
                   WHERE id = ?""",
                (msg.id,),
            )
            await self._db.commit()
            msg.status = "processing"
            msg.attempt_count += 1
            return msg

    async def complete(self, message_id: int) -> None:
        """Mark a message as completed."""
        await self._db.execute(
            """UPDATE message_queue
               SET status = 'completed', completed_at = datetime('now')
               WHERE id = ?""",
            (message_id,),
        )
        await self._db.commit()

    async def fail(self, message_id: int, error_details: str | None = None) -> None:
        """Mark a message as failed."""
        details = json.dumps({"error": error_details}) if error_details else None
        await self._db.execute(
            """UPDATE message_queue
               SET status = 'failed', completed_at = datetime('now'), error_details = ?
               WHERE id = ?""",
            (details, message_id),
        )
        await self._db.commit()

    async def retry(self, message_id: int) -> None:
        """Reset a message back to pending for retry."""
        await self._db.execute(
            "UPDATE message_queue SET status = 'pending' WHERE id = ?",
            (message_id,),
        )
        await self._db.commit()

    async def rate_limit_all(self) -> int:
        """Batch-set all pending messages to rate_limited. Returns count affected."""
        cursor = await self._db.execute(
            "UPDATE message_queue SET status = 'rate_limited' WHERE status = 'pending'",
        )
        await self._db.commit()
        return cursor.rowcount

    async def mark_send_failed(self, message_id: int, response_text: str) -> None:
        """Store response for retry when Discord recovers."""
        await self._db.execute(
            """UPDATE message_queue
               SET status = 'send_failed', response_text = ?
               WHERE id = ?""",
            (response_text, message_id),
        )
        await self._db.commit()

    async def get_unsent_responses(self) -> list[tuple[int, str, str]]:
        """Get messages with status=send_failed and stored response text.

        Returns list of (id, chat_id, response_text).
        """
        rows = await self._db.fetchall(
            """SELECT id, chat_id, response_text
               FROM message_queue
               WHERE status = 'send_failed' AND response_text IS NOT NULL
               ORDER BY received_at ASC""",
        )
        return [(r[0], r[1], r[2]) for r in rows]

    async def reset_orphaned(self) -> int:
        """Reset processing messages back to pending (crash recovery). Returns count."""
        cursor = await self._db.execute(
            "UPDATE message_queue SET status = 'pending' WHERE status = 'processing'",
        )
        await self._db.commit()
        return cursor.rowcount

    async def get_queue_status(self) -> dict[str, Any]:
        """Get counts by status and list of pending messages."""
        rows = await self._db.fetchall(
            "SELECT status, COUNT(*) FROM message_queue GROUP BY status",
        )
        counts = {r[0]: r[1] for r in rows}

        pending = await self._db.fetchall(
            """SELECT id, text, received_at
               FROM message_queue
               WHERE status = 'pending'
               ORDER BY received_at ASC
               LIMIT 10""",
        )
        pending_list = [
            {"id": r[0], "text": r[1][:100], "received_at": r[2]}
            for r in pending
        ]

        return {"counts": counts, "pending": pending_list}

    async def get_position(self, chat_id: str) -> int:
        """Get the queue position for messages from this chat_id."""
        rows = await self._db.fetchall(
            """SELECT chat_id FROM message_queue
               WHERE status = 'pending'
               ORDER BY received_at ASC""",
        )
        for i, row in enumerate(rows):
            if row[0] == chat_id:
                return i + 1
        return 0
