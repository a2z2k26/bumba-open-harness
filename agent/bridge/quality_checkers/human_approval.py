"""HUMAN_APPROVAL gate — delegates to quality_gate.py for operator sign-off.

Returns requires_human=True so the dispatcher parks the WorkOrder.
The WorkOrder waits in VERIFYING until POST /api/reviews/{id}/decide is called.
"""
from __future__ import annotations

import logging
import uuid

from bridge.quality_chain import GateCheckResult, GateLevel

log = logging.getLogger(__name__)


class HumanApprovalChecker:
    """Gate 7: HUMAN_APPROVAL — operator must approve before COMPLETE.

    Like CodeReviewChecker, always returns requires_human=True.
    The dispatcher parks the WorkOrder; resume happens via the review API.
    """

    def __call__(self, project: str, files: list[str]) -> GateCheckResult:
        approval_id = str(uuid.uuid4())
        log.info(
            "HUMAN_APPROVAL gate: requesting operator approval %s for project=%s",
            approval_id[:8], project,
        )
        return GateCheckResult(
            passed=True,
            gate_level=GateLevel.HUMAN_APPROVAL,
            reason=f"Awaiting operator approval (approval_id={approval_id})",
            requires_human=True,
            escalation_reason=(
                f"Human approval required for project={project} "
                f"(approval_id={approval_id})"
            ),
        )
