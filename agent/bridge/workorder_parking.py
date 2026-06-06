"""Parked-WorkOrder registry: review_id → WO resume callback.

Thread-safe for the aiohttp single-event-loop model.
WorkOrders are parked when a human-review gate returns requires_human=True.
They resume when POST /api/reviews/{id}/decide is called.

STATUS — DORMANT (P8.2 sub-decision 1, #1748, 2026-05-12). The
public API surface is preserved by `tests/test_workorder_public_api.py`
as a stable contract; `quality_checkers/code_review.py:19` references
this module in docstrings as the intended handoff target. Wiring into
the live quality-gate flow is deferred to a future human-review-gate
sprint. Do not import this module from production code paths until
that sprint files the wiring decision.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Awaitable, Callable

log = logging.getLogger(__name__)


@dataclass
class ParkedWorkOrder:
    """An in-flight WorkOrder waiting for human review."""

    workorder_id: str
    review_id: str
    gate_level_name: str  # "CODE_REVIEW" | "HUMAN_APPROVAL"
    resume: Callable[[bool, str], Awaitable[None]]  # (approved, reason) -> None


class WorkOrderParkingManager:
    """Registry of WorkOrders parked at human-review gates.

    Uses asyncio.Lock for safe concurrent access within the event loop.
    """

    def __init__(self) -> None:
        self._parked: dict[str, ParkedWorkOrder] = {}
        self._lock = asyncio.Lock()

    async def park(self, pwo: ParkedWorkOrder) -> None:
        """Register a WorkOrder as parked pending human review."""
        async with self._lock:
            self._parked[pwo.review_id] = pwo
        log.info(
            "Parked WO %s at gate %s (review_id=%s)",
            pwo.workorder_id[:8],
            pwo.gate_level_name,
            pwo.review_id[:8],
        )

    async def resume(self, review_id: str, approved: bool, reason: str = "") -> bool:
        """Resume a parked WorkOrder by calling its callback.

        Returns True if a matching parked WO was found, False otherwise.
        """
        async with self._lock:
            pwo = self._parked.pop(review_id, None)

        if pwo is None:
            log.warning("WorkOrderParkingManager.resume: no WO parked for review %s", review_id[:8])
            return False

        log.info(
            "Resuming WO %s from gate %s: approved=%s reason=%r",
            pwo.workorder_id[:8],
            pwo.gate_level_name,
            approved,
            reason,
        )
        try:
            await pwo.resume(approved, reason)
        except Exception:
            log.exception(
                "Resume callback failed for WO %s (review %s)",
                pwo.workorder_id[:8],
                review_id[:8],
            )
            return False
        return True

    async def list_parked(self) -> list[dict]:
        """Return a summary of all currently parked WorkOrders."""
        async with self._lock:
            return [
                {
                    "workorder_id": pwo.workorder_id,
                    "review_id": pwo.review_id,
                    "gate": pwo.gate_level_name,
                }
                for pwo in self._parked.values()
            ]

    async def cancel_all(self) -> int:
        """Cancel all parked WorkOrders (e.g. on shutdown). Returns count."""
        async with self._lock:
            count = len(self._parked)
            for pwo in self._parked.values():
                try:
                    asyncio.create_task(pwo.resume(False, "cancelled: system shutdown"))
                except Exception:
                    pass
            self._parked.clear()
        return count


# ---------------------------------------------------------------------------
# Module-level singleton for bridge wiring
# ---------------------------------------------------------------------------

_parking_manager: WorkOrderParkingManager | None = None


def get_parking_manager() -> WorkOrderParkingManager:
    """Return the module-level parking manager singleton."""
    global _parking_manager
    if _parking_manager is None:
        _parking_manager = WorkOrderParkingManager()
    return _parking_manager


def reset_parking_manager() -> None:
    """Reset the singleton (for testing)."""
    global _parking_manager
    _parking_manager = None
