"""CODE_REVIEW gate — creates a review entry and parks the WorkOrder.

Returns requires_human=True so the dispatcher parks rather than blocks.
"""
from __future__ import annotations

import logging
import uuid

from bridge.quality_chain import GateCheckResult, GateLevel

log = logging.getLogger(__name__)


class CodeReviewChecker:
    """Gate 6: CODE_REVIEW — files a review request and parks the WorkOrder.

    The gate always returns requires_human=True.  The dispatcher detects this
    and parks the WorkOrder via WorkOrderParkingManager instead of completing
    the dispatch immediately.
    """

    def __call__(self, project: str, files: list[str]) -> GateCheckResult:
        review_id = str(uuid.uuid4())
        log.info(
            "CODE_REVIEW gate: requesting review %s for project=%s files=%d",
            review_id[:8], project, len(files),
        )
        return GateCheckResult(
            passed=True,
            gate_level=GateLevel.CODE_REVIEW,
            reason=f"Awaiting code review (review_id={review_id})",
            requires_human=True,
            escalation_reason=f"Code review requested for project={project} (review_id={review_id})",
        )
