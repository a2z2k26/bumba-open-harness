"""Quality review gates for task approval workflows.

Provides a review lifecycle (pending -> approved/rejected/needs_changes)
that blocks task progression until all reviewers have signed off.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bridge.database import Database

logger = logging.getLogger(__name__)

VALID_DECISIONS = frozenset({"approved", "rejected", "needs_changes"})


class QualityGate:
    """Gate that enforces review approval before a task can proceed."""

    def __init__(self, db: Database) -> None:
        self._db = db

    async def initialize(self) -> None:
        """Create the quality_reviews table and indexes."""
        await self._db.execute(
            """
            CREATE TABLE IF NOT EXISTS quality_reviews (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id INTEGER NOT NULL,
                reviewer TEXT DEFAULT '',
                review_type TEXT DEFAULT 'quality',
                status TEXT NOT NULL DEFAULT 'pending',
                decision TEXT,
                comment TEXT DEFAULT '',
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                decided_at TEXT
            )
            """
        )
        await self._db.execute(
            "CREATE INDEX IF NOT EXISTS idx_quality_reviews_task "
            "ON quality_reviews(task_id)"
        )
        await self._db.execute(
            "CREATE INDEX IF NOT EXISTS idx_quality_reviews_status "
            "ON quality_reviews(status)"
        )
        await self._db.commit()
        logger.info("quality_reviews table initialized")

    async def request_review(
        self,
        task_id: int,
        reviewer: str = "",
        review_type: str = "quality",
    ) -> int:
        """Open a new review request for a task.

        Returns:
            The auto-generated review ID.
        """
        cursor = await self._db.execute(
            "INSERT INTO quality_reviews (task_id, reviewer, review_type) "
            "VALUES (?, ?, ?)",
            (task_id, reviewer, review_type),
        )
        await self._db.commit()
        review_id: int = cursor.lastrowid
        logger.info(
            "review requested: id=%d task=%d reviewer=%s type=%s",
            review_id,
            task_id,
            reviewer or "(unassigned)",
            review_type,
        )
        return review_id

    async def submit_decision(
        self,
        review_id: int,
        decision: str,
        comment: str = "",
    ) -> bool:
        """Record a reviewer's decision on an open review.

        Args:
            review_id: ID of the review to decide.
            decision: One of ``approved``, ``rejected``, ``needs_changes``.
            comment: Optional reviewer comment.

        Returns:
            True if the review was found and updated, False otherwise.

        Raises:
            ValueError: If *decision* is not a recognised value.
        """
        if decision not in VALID_DECISIONS:
            raise ValueError(
                f"Invalid decision '{decision}'. "
                f"Must be one of: {', '.join(sorted(VALID_DECISIONS))}"
            )

        decided_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        cursor = await self._db.execute(
            "UPDATE quality_reviews "
            "SET status = ?, decision = ?, comment = ?, decided_at = ? "
            "WHERE id = ? AND status = 'pending'",
            (decision, decision, comment, decided_at, review_id),
        )
        await self._db.commit()

        updated = cursor.rowcount > 0
        if updated:
            logger.info(
                "review decided: id=%d decision=%s comment=%s",
                review_id,
                decision,
                comment or "(none)",
            )
        else:
            logger.warning(
                "review decision skipped: id=%d not found or already decided",
                review_id,
            )
        return updated

    async def get_pending_reviews(
        self, task_id: int | None = None
    ) -> list[dict]:
        """Return all reviews still in *pending* status.

        Args:
            task_id: When provided, restricts results to a single task.

        Returns:
            List of review dicts with all column values.
        """
        if task_id is not None:
            rows = await self._db.fetchall(
                "SELECT id, task_id, reviewer, review_type, status, "
                "decision, comment, created_at, decided_at "
                "FROM quality_reviews WHERE status = 'pending' AND task_id = ?",
                (task_id,),
            )
        else:
            rows = await self._db.fetchall(
                "SELECT id, task_id, reviewer, review_type, status, "
                "decision, comment, created_at, decided_at "
                "FROM quality_reviews WHERE status = 'pending'",
            )

        return [
            {
                "id": row["id"],
                "task_id": row["task_id"],
                "reviewer": row["reviewer"],
                "review_type": row["review_type"],
                "status": row["status"],
                "decision": row["decision"],
                "comment": row["comment"],
                "created_at": row["created_at"],
                "decided_at": row["decided_at"],
            }
            for row in rows
        ]

    async def is_task_approved(self, task_id: int) -> bool:
        """Check whether every review for *task_id* has been approved.

        Returns False when:
        - Any review is still pending.
        - No reviews exist at all (nothing to approve against).
        """
        row = await self._db.fetchone(
            "SELECT COUNT(*) AS total, "
            "SUM(CASE WHEN status = 'pending' THEN 1 ELSE 0 END) AS pending "
            "FROM quality_reviews WHERE task_id = ?",
            (task_id,),
        )
        if row is None or row["total"] == 0:
            return False
        return row["pending"] == 0
