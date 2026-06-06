"""WorkOrderRouter contract — Z4-S02 (#1386).

Abstract interface for routing ``WorkOrder`` rows into a department's
``ChiefSession``. The concrete ``RuleBasedWorkOrderRouter`` lands in
Z4-S20 (#1390); a model-based implementation may follow. This sprint
ships the interface only so downstream sprints have a stable contract
to build against.

Why an ABC, not a Protocol:

    The Z4-S03 store uses ``Protocol`` because the store is structurally
    typed — any class with the right async methods is a valid store.
    The router is *behaviourally* typed: implementations must enforce a
    "do not mutate the WorkOrder" invariant that's not expressible in
    the type system. Subclassing ABC documents that invariant + gives
    us a single place to put the docstring contract that future
    implementers must read.

The decision payload (``RoutingDecision``) is intentionally rich:

- ``department`` — must match a key in ``DepartmentRegistry``
- ``rationale`` — human-readable; logged + stored on the chief_session.metadata
- ``confidence`` — 0.0–1.0; values below 0.5 will trigger a NUDGE alert
  to the operator (wired in Z4-S21 ChiefDispatcher #1392)
- ``priority_override`` — optional override of the WorkOrder's batch
  strategy when the router has reason to escalate / de-prioritise
- ``fallback_departments`` — ordered list of alternates the dispatcher
  tries if the primary department's chief rejects the work order
  (cost-cap breach, idle-timeout, etc.)

Companion docs:
  - `agent/bridge/chief_session.py` — the row this router decides which
    department fills
  - `docs/zone4/team-playbook.md` — Section 4 (board.yaml schema) lists
    the allowed department slugs
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional

from bridge.work_order import WorkOrder


@dataclass(frozen=True)
class RoutingDecision:
    """The output of a ``WorkOrderRouter.route()`` call.

    Frozen so callers can't accidentally mutate a routing decision after
    receiving it — the dispatcher reads the same instance many times
    while it walks the fallback list.

    Attributes:
        department: The department slug to assign this work order to.
            Must match a key in ``DepartmentRegistry``.
        rationale: Human-readable explanation of why this department
            was chosen. Logged to the daily log and stored on
            ``ChiefSession.metadata`` for audit-trail purposes.
        confidence: Router's confidence in this decision (0.0–1.0).
            Values below 0.5 will trigger a NUDGE alert to the operator
            (wired in Z4-S21 ChiefDispatcher #1392). Default 1.0 so a
            router that doesn't reason about confidence (e.g. NullRouter,
            rule-based with explicit rules) lands at full confidence
            without having to opt in.
        priority_override: Optional priority string to apply to the
            ``ChiefSession`` (overrides the WorkOrder's batch strategy).
            ``None`` means use the WorkOrder's own priority.
        fallback_departments: Ordered list of alternative departments
            to try if the primary department's chief rejects the work
            order (cost cap, idle timeout, etc.). Empty list means no
            fallback — the dispatcher will raise rather than guess.
    """

    department: str
    rationale: str
    confidence: float = 1.0
    priority_override: Optional[str] = None
    fallback_departments: tuple[str, ...] = field(default_factory=tuple)


class RoutingError(Exception):
    """Raised when a router cannot determine a viable department.

    The dispatcher converts this into an ``[autonomous] BLOCKER`` surface
    (Z4-S21 #1392) so the operator sees a structured failure rather than
    a silent drop.
    """

    def __init__(self, work_order_id: str, reason: str) -> None:
        super().__init__(f"Cannot route work order {work_order_id}: {reason}")
        self.work_order_id = work_order_id
        self.reason = reason


class WorkOrderRouter(ABC):
    """Abstract interface for routing WorkOrders to departments.

    Implementations must be stateless or manage their own internal state
    — the dispatcher will not coordinate router state across calls. The
    ``route()`` method must NOT modify the WorkOrder; the WorkOrder is
    passed in as a frozen dataclass for that reason, but implementations
    are expected to honour the spirit of the contract (no mutation of
    nested mutable fields like ``input.context.metadata``).

    Concrete implementations:
        - ``NullRouter`` — test double; always returns a fixed department
        - ``RuleBasedWorkOrderRouter`` — Z4-S20 (#1390); rules table
        - (future) model-based router — uses an LLM to classify

    Lifetime model: the dispatcher instantiates one router at startup
    (operator-flag-gated) and reuses it for the lifetime of the bridge.
    No per-call setup; routers should be cheap to call.
    """

    @abstractmethod
    async def route(self, work_order: WorkOrder) -> RoutingDecision:
        """Determine which department should handle this WorkOrder.

        Args:
            work_order: The WorkOrder to route. Must not be modified by
                the router.

        Returns:
            A ``RoutingDecision`` with the target department and metadata.

        Raises:
            RoutingError: If no viable department can be determined and
                no fallback is available. The dispatcher converts this
                into an operator-visible BLOCKER surface.
        """
        ...


class NullRouter(WorkOrderRouter):
    """Test double that always routes to a fixed department.

    Use in unit tests where the router is a dependency but the routing
    logic itself is not under test (e.g. ChiefDispatcher tests in
    Z4-S21 #1392). The default ``department`` is ``"strategy"`` because
    that's the most-broadly-defined production department and any
    test exercising routing-into-a-real-department will accept it.

    Confidence is fixed at 1.0 — a NullRouter that reported low
    confidence would mask test signal about the dispatcher's NUDGE-on-
    low-confidence path. Tests that need to exercise that path should
    use a different test double or override `route()` directly.
    """

    def __init__(self, department: str = "strategy") -> None:
        self._department = department

    async def route(self, work_order: WorkOrder) -> RoutingDecision:
        return RoutingDecision(
            department=self._department,
            rationale=f"NullRouter: always routes to {self._department!r}",
            confidence=1.0,
        )


# ---------------------------------------------------------------------------
# Z4-S20 (#1390) — RuleBasedWorkOrderRouter
# ---------------------------------------------------------------------------

import re  # noqa: E402 — placed near the consumer for grep-locality
from typing import Any  # noqa: E402


# Confidence levels per rule tier. Frozen as module constants so tests
# and the dispatcher's NUDGE-on-low-confidence threshold (0.5, per
# Z4-S21 #1392) reference one source of truth.
_CONFIDENCE_EXPLICIT_HINT: float = 1.0
_CONFIDENCE_KEYWORD_MATCH: float = 0.75
_CONFIDENCE_STRATEGY_HEURISTIC: float = 0.5
_CONFIDENCE_DEFAULT_FALLBACK: float = 0.3

# BatchStrategy → department heuristic. Real BatchStrategy values per
# `bridge.work_order` (not the issue spec's imagined values):
#   SEQUENTIAL, PARALLEL_FANOUT, RACE         (concurrency)
#   DEPTH_FIRST, BREADTH_FIRST, LAYER_SEQUENTIAL  (traversal)
# The mapping reflects the operational reality: parallel/sequential
# multi-step work usually wants engineering specialists; race-pattern
# work (try-many-pick-one) maps to QA's adversarial reasoning;
# traversal strategies are decomposer-internal so they don't get
# strong routing signal — fall back to default.
# NOTE on the heuristic targets: the real Z4 departments today are
# board / design / job-search / ops / outreach / qa / strategy. There
# is no "engineering" department (the issue spec was written assuming
# one). "ops" is the closest live department for sequential /
# parallel-fanout multi-step work. RuleBasedWorkOrderRouter degrades
# gracefully if a target doesn't exist in the registry (the heuristic
# tier just doesn't fire and tier 4 takes over).
_BATCH_STRATEGY_HINTS: dict[str, str] = {
    "sequential": "ops",
    "parallel_fanout": "ops",
    "race": "qa",
}


class RuleBasedWorkOrderRouter(WorkOrderRouter):
    """Deterministic 4-tier rule-based WorkOrder router.

    Rule chain (highest priority first):

    1. **Explicit department_target** on the WorkOrder
       (``work_order.department_target``). Per `bridge.work_order` line
       236, this field is the canonical "this WO already names its dept"
       slot. Confidence 1.0 when set + the dept exists in the registry.

    2. **Keyword matching** against department descriptions from
       ``DepartmentRegistry``. Scores each department by the fraction
       of unique keywords (≥4 chars) from its description that appear
       in the WorkOrder's intent + input.text. Confidence 0.75. Tie
       break: alphabetically first dept wins.

    3. **BatchStrategy heuristic** when the WorkOrder has a
       ``decomposition`` and that decomposition's strategy maps to a
       known department per ``_BATCH_STRATEGY_HINTS``. Confidence 0.5.

    4. **Configured default** (``default_department``). Confidence 0.3.
       Populates ``fallback_departments`` with the next two registry
       entries so the dispatcher has options if the default rejects.

    The router does NOT call an LLM — every decision is computable
    from the WorkOrder + registry state. This keeps Z4 routing fast,
    deterministic, and free at the margin. Future model-based router
    implementations swap in by satisfying the same `WorkOrderRouter`
    ABC.

    Args:
        registry: ``DepartmentRegistry`` to read department names + descriptions
            from. Duck-typed (read via ``department_names()`` and
            ``get_config(name)``) so this module doesn't need to import
            from ``teams/`` and trigger a circular import at startup.
        default_department: Fallback department slug when no rule matches.
            Must exist in the registry — ``RoutingError`` raised at
            ``route()`` time if it doesn't, since a router with no viable
            default is a config bug worth surfacing loudly.
    """

    def __init__(
        self,
        registry: Any,  # DepartmentRegistry — duck-typed
        default_department: str = "strategy",
    ) -> None:
        self._registry = registry
        self._default = default_department

    async def route(self, work_order: WorkOrder) -> RoutingDecision:
        # Tier 1 — explicit department_target on the WorkOrder
        target = work_order.department_target
        if target and self._registry_has(target):
            return RoutingDecision(
                department=target,
                rationale=(
                    f"Tier 1: explicit department_target on WorkOrder "
                    f"({target!r})"
                ),
                confidence=_CONFIDENCE_EXPLICIT_HINT,
            )

        # Tier 2 — keyword matching against department descriptions
        description = self._extract_description(work_order)
        keyword_match = self._match_keywords(description)
        if keyword_match:
            dept, score = keyword_match
            others = [d for d in self._registry_departments() if d != dept]
            return RoutingDecision(
                department=dept,
                rationale=(
                    f"Tier 2: keyword match against {dept!r} description "
                    f"(score={score:.2f})"
                ),
                confidence=_CONFIDENCE_KEYWORD_MATCH,
                fallback_departments=tuple(others[:2]),
            )

        # Tier 3 — BatchStrategy heuristic from the decomposition plan
        decomposition = work_order.decomposition
        if decomposition is not None:
            strategy = decomposition.strategy
            strategy_key = (
                strategy.value if hasattr(strategy, "value") else str(strategy)
            )
            heuristic_dept = _BATCH_STRATEGY_HINTS.get(strategy_key.lower())
            if heuristic_dept and self._registry_has(heuristic_dept):
                return RoutingDecision(
                    department=heuristic_dept,
                    rationale=(
                        f"Tier 3: BatchStrategy heuristic "
                        f"({strategy_key!r} -> {heuristic_dept!r})"
                    ),
                    confidence=_CONFIDENCE_STRATEGY_HEURISTIC,
                    fallback_departments=(self._default,)
                    if self._registry_has(self._default)
                    else (),
                )

        # Tier 4 — configured default
        if not self._registry_has(self._default):
            raise RoutingError(
                work_order_id=work_order.id,
                reason=(
                    f"default department {self._default!r} not in registry; "
                    "no other rule matched"
                ),
            )
        others = [d for d in self._registry_departments() if d != self._default]
        return RoutingDecision(
            department=self._default,
            rationale="Tier 4: no rule matched — routing to configured default.",
            confidence=_CONFIDENCE_DEFAULT_FALLBACK,
            fallback_departments=tuple(others[:2]),
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _registry_has(self, department: str) -> bool:
        """True iff ``department`` is a known department in the registry.

        Wrapped in a try/except because a registry implementation that
        raises (e.g. on a stale config reload) shouldn't crash the
        router; the router degrades to Tier-4-default gracefully.
        """
        try:
            return department in self._registry_departments()
        except Exception:
            return False

    def _registry_departments(self) -> list[str]:
        """Return all known department names. Empty list on registry failure."""
        try:
            return list(self._registry.department_names())
        except Exception:
            return []

    def _extract_description(self, work_order: WorkOrder) -> str:
        """Concatenate intent + input.text into the routable description.

        ``WorkOrder.intent`` is the canonical short description. The
        ``input.text`` is the longer payload. Both are searched for
        keyword matches.
        """
        parts: list[str] = []
        if work_order.intent:
            parts.append(work_order.intent)
        if work_order.input and work_order.input.text:
            parts.append(work_order.input.text)
        return " ".join(parts)

    def _get_dept_description(self, department: str) -> str:
        """Return the department's description text, or empty on failure."""
        try:
            config = self._registry.get_config(department)
            return config.description if config else ""
        except Exception:
            return ""

    def _match_keywords(
        self, description: str
    ) -> tuple[str, float] | None:
        """Return ``(department, score)`` for the best keyword match, else None.

        Scoring: for each department, extract unique 4+ char words from
        its description, count how many appear in the WorkOrder
        description, divide by the count of unique department keywords.
        Departments with score 0 are excluded; departments with score <
        0.05 are also excluded (too noisy to be confident).

        Tie break: when two departments score equally, the
        alphabetically-first wins. This matches the issue spec's
        explicit ask and makes the router fully deterministic.
        """
        if not description:
            return None
        desc_lower = description.lower()
        scores: dict[str, float] = {}
        for dept in self._registry_departments():
            dept_desc = self._get_dept_description(dept).lower()
            words = set(re.findall(r"\b\w{4,}\b", dept_desc))
            if not words:
                continue
            matches = sum(1 for w in words if w in desc_lower)
            score = matches / len(words)
            if score >= 0.05:
                scores[dept] = score
        if not scores:
            return None
        # Sort by (-score, dept) so highest-score wins; ties broken
        # alphabetically by dept name.
        best_dept = min(scores.items(), key=lambda kv: (-kv[1], kv[0]))[0]
        return (best_dept, scores[best_dept])
