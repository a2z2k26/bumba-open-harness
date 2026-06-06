"""WorkOrder decomposition Protocol + default stub.

Sprint 07.01 — concept-only port of TinyAGI/fractals (MIT). Defines
the contract that future decomposers (07.02) will implement.

A decomposer answers two questions:

1. ``classify(wo) -> "atomic" | "composite"`` — is this WorkOrder
   small enough to execute directly, or does it need to be broken
   down into sub-WorkOrders?
2. ``decompose(wo) -> Decomposition`` — only called when classify
   returns ``"composite"``; produces the fan-out plan.

The recursive decomposer (07.02) drives this in a loop: composite
WorkOrders spawn sub-WorkOrders that re-enter ``classify``. Leaves
get executed in isolated worktrees per their ``BatchStrategy``
(07.03 wires the worktree side).

This sprint ships **only** the Protocol + a default stub that always
returns ``"atomic"``, so existing code paths see no behavior change
when the feature flag is off.
"""

from __future__ import annotations

from typing import Literal, Protocol, runtime_checkable

from bridge.work_order import BatchStrategy, Decomposition, WorkOrder

# Classification verdict — exposed as a type alias so callers don't
# have to import ``Literal`` everywhere.
Classification = Literal["atomic", "composite"]


@runtime_checkable
class Decomposer(Protocol):
    """Protocol for a WorkOrder decomposer.

    Implementations must be pure with respect to the input WorkOrder
    (frozen dataclass) — no mutation, return new instances. Side
    effects (LLM calls, store reads) are permitted but should be
    idempotent on retry.
    """

    def classify(self, wo: WorkOrder) -> Classification:
        """Decide whether ``wo`` is atomic or composite.

        Returns one of ``"atomic"`` or ``"composite"``. The recursive
        loop only calls ``decompose`` when this returns ``"composite"``.
        """
        ...

    def decompose(self, wo: WorkOrder) -> Decomposition:
        """Produce a sub-WorkOrder fan-out plan for a composite WO.

        Caller guarantees ``classify(wo) == "composite"``. The
        returned ``Decomposition`` carries the strategy and the
        children tuple (each child a fresh ``WorkOrder``).
        """
        ...


class _DefaultDecomposer:
    """Stub decomposer — every WorkOrder is atomic.

    Ships in 07.01 as the no-op default so the Protocol can be
    referenced from existing code without changing behavior. 07.02
    replaces this with the LLM-driven recursive decomposer.

    ``decompose`` raises by contract — it should never be called for
    an atomic WorkOrder, and a ``_DefaultDecomposer`` only ever
    classifies as atomic.
    """

    def classify(self, wo: WorkOrder) -> Classification:  # noqa: ARG002 — Protocol shape
        return "atomic"

    def decompose(self, wo: WorkOrder) -> Decomposition:
        raise RuntimeError(
            "_DefaultDecomposer.decompose called — every WorkOrder is "
            "classified as atomic; decompose should never be reached. "
            "If you need decomposition, install a real Decomposer "
            "implementation (Sprint 07.02)."
        )


__all__ = [
    "BatchStrategy",
    "Classification",
    "Decomposer",
    "Decomposition",
    "_DefaultDecomposer",
]
