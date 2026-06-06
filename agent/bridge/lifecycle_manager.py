"""
WorkLifecycleManager — experimental DECOMPOSE → ASSIGN → EXECUTE → VERIFY → SYNTHESIZE pipeline.

This module has no production callers. It is retained as an experimental Zone 3
orchestration prototype with fail-loud execution and verification seams. Callers
must pass ``experimental_ack=EXPERIMENTAL_USE_ACK`` to construct it.
"""

import time
from dataclasses import dataclass
from enum import Enum
from typing import Callable, Dict, List, Optional

from . import model_defaults  # P0.01 canonical default-model constants
from .work_order import WorkOrder, WorkOrderStatus
from .dependency_manager import DependencyManager
from .routing_cascade import RoutingCascade


class PipelineStage(str, Enum):
    """Ordered pipeline stages."""
    DECOMPOSE = "decompose"
    ASSIGN = "assign"
    EXECUTE = "execute"
    VERIFY = "verify"
    SYNTHESIZE = "synthesize"


@dataclass
class PipelineResult:
    """Outcome of a pipeline stage or full pipeline run."""
    work_order_id: str
    stage: PipelineStage
    status: str          # "completed" | "failed" | "partial"
    output: Optional[Dict] = None
    error: Optional[str] = None
    duration_seconds: float = 0.0


Executor = Callable[[WorkOrder], Dict]
Verifier = Callable[[WorkOrder, Dict], bool]
EXPERIMENTAL_USE_ACK = "experimental-work-lifecycle-manager"


class WorkLifecycleManager:
    """
    Experimental WorkOrder orchestration pipeline.

    Decompose   — split complex tasks into sub-orders
    Assign      — route each order to an agent
    Execute     — invoke an explicitly injected executor
    Verify      — validate with an explicitly injected verifier
    Synthesize  — merge outputs of sub-orders
    """

    # Default stub agents available for assignment
    _DEFAULT_AGENTS = [
        {"agent_id": "eng-01", "department": "engineering", "capabilities": ["build", "code", "fix", "deploy", "test"]},
        {"agent_id": "qa-01",  "department": "qa",          "capabilities": ["verify", "check", "review", "audit"]},
        {"agent_id": "res-01", "department": "research",    "capabilities": ["analyze", "research", "investigate"]},
    ]

    def __init__(
        self,
        available_agents: Optional[List[Dict]] = None,
        max_retries: int = 3,
        executor: Optional[Executor] = None,
        verifier: Optional[Verifier] = None,
        experimental_ack: str | None = None,
    ) -> None:
        if experimental_ack != EXPERIMENTAL_USE_ACK:
            raise RuntimeError(
                "WorkLifecycleManager is experimental and has no production "
                "callers; pass experimental_ack=EXPERIMENTAL_USE_ACK only "
                "from tests or an explicit activation sprint."
            )
        self._agents = available_agents or self._DEFAULT_AGENTS
        self._max_retries = max_retries
        self._executor = executor
        self._verifier = verifier
        self._routing_cascade = RoutingCascade()
        self._dep_manager = DependencyManager()

    # ------------------------------------------------------------------
    # Full pipeline
    # ------------------------------------------------------------------

    def execute(self, work_order: WorkOrder) -> PipelineResult:
        """
        Run the full DECOMPOSE → ASSIGN → EXECUTE → VERIFY → SYNTHESIZE pipeline.

        Returns a PipelineResult reflecting the final status.
        """
        t0 = time.monotonic()
        stage = PipelineStage.DECOMPOSE

        try:
            # DECOMPOSE
            sub_orders = self.decompose(work_order)

            # ASSIGN + EXECUTE + VERIFY each sub-order
            outputs: List[Dict] = []
            for sub in sub_orders:
                stage = PipelineStage.ASSIGN
                assigned = self.assign(sub)
                stage = PipelineStage.EXECUTE
                raw_output = self.execute_work(assigned)
                stage = PipelineStage.VERIFY
                verified = self.verify(assigned, raw_output)
                if verified:
                    outputs.append(raw_output)
                else:
                    # Non-critical: collect anyway but flag it
                    outputs.append({**raw_output, "verification_failed": True})

            # SYNTHESIZE
            stage = PipelineStage.SYNTHESIZE
            final_output = self.synthesize(outputs)

            duration = time.monotonic() - t0
            return PipelineResult(
                work_order_id=work_order.id,
                stage=PipelineStage.SYNTHESIZE,
                status="completed",
                output=final_output,
                duration_seconds=round(duration, 4),
            )

        except Exception as exc:
            duration = time.monotonic() - t0
            return PipelineResult(
                work_order_id=work_order.id,
                stage=stage,
                status="failed",
                error=str(exc),
                duration_seconds=round(duration, 4),
            )

    # ------------------------------------------------------------------
    # Individual stages
    # ------------------------------------------------------------------

    def decompose(self, work_order: WorkOrder) -> List[WorkOrder]:
        """
        Split a complex WorkOrder into sub-orders.

        Stub: returns [work_order] for simple tasks (no sub-order decomposition).
        A real implementation would inspect intent and constraints.
        """
        return [work_order]

    def assign(self, work_order: WorkOrder) -> WorkOrder:
        """
        Route and assign a WorkOrder to an agent.

        Uses RoutingCascade to select the best agent, then returns a new
        WorkOrder with ASSIGNED status and assignment metadata.
        """
        decision = self._routing_cascade.route(work_order.intent, self._agents)
        assigned_at = time.time()

        # Build a new WorkOrder with assignment info injected into the
        # existing assignment dict (WorkOrder is frozen, so we use from_dict)
        data = work_order.to_dict()
        data["status"] = WorkOrderStatus.ASSIGNED.value
        data["assignment"] = {
            "agent_id": decision.agent_id,
            # Sourced from canonical constant (P0.01); the documented paid
            # default is preserved unchanged in bridge.model_defaults.
            "model": model_defaults.DEFAULT_PAID_MODEL,
            "assigned_at": assigned_at,
            "routing_confidence": decision.confidence,
            "routing_tier": decision.tier_used,
        }
        return WorkOrder.from_dict(data)

    def execute_work(self, work_order: WorkOrder) -> Dict:
        """
        Execute the work order.

        Real execution must be injected by the caller. Returning a stub success
        here would fabricate completed work.
        """
        if self._executor is None:
            raise NotImplementedError(
                "No lifecycle executor configured; cannot execute work order"
            )
        return self._executor(work_order)

    def verify(self, work_order: WorkOrder, output: Dict) -> bool:
        """
        Verify the output of a work order.

        Real verification must be injected by the caller. Returning ``True`` by
        default would fabricate successful verification.
        """
        if self._verifier is None:
            raise NotImplementedError(
                "No lifecycle verifier configured; cannot verify work order output"
            )
        return self._verifier(work_order, output)

    def synthesize(self, outputs: List[Dict]) -> Dict:
        """
        Merge the outputs of all sub-orders into a single result.

        Simple concatenation stub: joins result strings and averages confidence.
        """
        if not outputs:
            return {"result": "", "confidence": 0.0}

        results = [str(o.get("result", "")) for o in outputs]
        confidences = [float(o.get("confidence", 0.8)) for o in outputs]
        avg_confidence = sum(confidences) / len(confidences)

        return {
            "result": "\n".join(results),
            "confidence": round(avg_confidence, 4),
            "source_count": len(outputs),
        }

    # ------------------------------------------------------------------
    # Error handling
    # ------------------------------------------------------------------

    def handle_timeout(self, work_order: WorkOrder) -> WorkOrder:
        """Mark a work order as failed due to timeout."""
        data = work_order.to_dict()
        data["status"] = WorkOrderStatus.FAILED.value
        data["execution"] = {
            **(work_order.execution or {}),
            "failure_reason": "timeout",
        }
        return WorkOrder.from_dict(data)

    def handle_retry(
        self,
        work_order: WorkOrder,
        max_retries: int = 3,
    ) -> bool:
        """
        Decide whether to retry a failed work order.

        Returns True if a retry should be attempted (i.e. attempts so far
        is below max_retries), False otherwise.
        """
        attempts = (work_order.execution or {}).get("attempts", 0)
        return int(attempts) < max_retries
