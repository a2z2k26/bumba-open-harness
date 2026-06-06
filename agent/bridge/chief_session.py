"""ChiefSession types and state machine — Z4-S01 (#1385).

Foundational type contract for Phase 1 (persistence) and Phase 2 (routing) of
the Z4 chief-session epic (#1381-#1410). Today's chief lifecycle is WARM
single-run: ``build_manager_agent()`` creates the chief, ``DepartmentTeam.run()``
drives it, and the chief is garbage-collected when ``run()`` returns. There
is no durable record of a chief's work across a work order's lifetime.

A ``ChiefSession`` is the durable envelope that fixes this. It is scoped to
one ``WorkOrder``, transitions through the state machine documented on
``ChiefSessionState``, and is **archived (not deleted)** when the work order
closes.

The chief agent itself remains a single-run in-process call; ``ChiefSession``
is the SQLite row that tracks that call's lifecycle from the outside.

Companion docs:
  - ``docs/zone4/team-playbook.md`` — when the playbook says "WARM single-run,"
    that constraint is on the *chief agent*, not on the ChiefSession envelope.
    The session row may live across multiple chief runs (requeue path).
  - ``docs/architecture/zone4-three-tier-autonomy.md`` — the three-tier model
    the session sits underneath at Tier 2.
"""
from __future__ import annotations

import dataclasses
import secrets
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional


class ChiefSessionState(str, Enum):
    """Lifecycle states for a ChiefSession.

    State machine (allowed transitions)::

        COLD ──► WARM ──► EXECUTING
                            │
                ┌───────────┼───────────┐
                ▼           ▼           ▼
        AWAITING_EVALUATION  FAILED  TIMED_OUT
                │
        ┌───────┼───────┬───────┐
        ▼       ▼       ▼       ▼
       DONE  FAILED  TIMED_OUT  WARM (requeue)
        │       │       │
        └───────┴───────┴────► SHUTDOWN

    ``TIMED_OUT`` is set by the idle-timeout reaper (Z4-S30 / #1391).
    ``SHUTDOWN`` is the terminal state for all paths — the row is
    archived, never deleted.
    """

    COLD = "cold"
    WARM = "warm"
    EXECUTING = "executing"
    AWAITING_EVALUATION = "awaiting_evaluation"
    DONE = "done"
    FAILED = "failed"
    TIMED_OUT = "timed_out"
    SHUTDOWN = "shutdown"


# Allowed state transitions: from_state -> set of allowed to_states.
# Keep this in sync with the state-diagram comment on `ChiefSessionState`.
_ALLOWED_TRANSITIONS: dict[ChiefSessionState, frozenset[ChiefSessionState]] = {
    ChiefSessionState.COLD: frozenset({
        ChiefSessionState.WARM,
        ChiefSessionState.SHUTDOWN,
    }),
    ChiefSessionState.WARM: frozenset({
        ChiefSessionState.EXECUTING,
        ChiefSessionState.SHUTDOWN,
    }),
    ChiefSessionState.EXECUTING: frozenset({
        ChiefSessionState.AWAITING_EVALUATION,
        ChiefSessionState.FAILED,
        ChiefSessionState.TIMED_OUT,
    }),
    ChiefSessionState.AWAITING_EVALUATION: frozenset({
        ChiefSessionState.DONE,
        ChiefSessionState.FAILED,
        ChiefSessionState.TIMED_OUT,
        # Requeue path: a session that finished one run can be re-warmed
        # for another. ``run_count`` increments on each WARM -> EXECUTING.
        ChiefSessionState.WARM,
    }),
    ChiefSessionState.DONE: frozenset({
        ChiefSessionState.SHUTDOWN,
    }),
    ChiefSessionState.FAILED: frozenset({
        ChiefSessionState.SHUTDOWN,
        # Recovery path: a failed session may be re-warmed for retry.
        # The retry policy (Z4-S60 / #1404) decides when this fires.
        ChiefSessionState.WARM,
    }),
    ChiefSessionState.TIMED_OUT: frozenset({
        ChiefSessionState.SHUTDOWN,
    }),
    # Terminal — once a session is SHUTDOWN, no further transitions.
    ChiefSessionState.SHUTDOWN: frozenset(),
}


class InvalidTransitionError(Exception):
    """Raised when a state transition is not allowed by the state machine."""

    def __init__(
        self,
        from_state: ChiefSessionState,
        to_state: ChiefSessionState,
    ) -> None:
        super().__init__(
            f"Invalid ChiefSession transition: "
            f"{from_state.value} -> {to_state.value}"
        )
        self.from_state = from_state
        self.to_state = to_state


def new_chief_session_id() -> str:
    """Generate a unique ChiefSession ID in the format ``cs-<12-hex>``.

    The 12-hex token is generated via ``secrets.token_hex(6)`` (96 bits of
    entropy — ample for a per-process counter that never exceeds millions
    of rows). Format mirrors the ``msg_<ts>_<seq>`` convention used by
    ``operator_inbox`` so log-grep is consistent.
    """
    return f"cs-{secrets.token_hex(6)}"


def _utc_now() -> datetime:
    """Return a tz-aware UTC datetime.

    Wraps ``datetime.now(timezone.utc)`` in one place so the entire module
    speaks tz-aware UTC consistently. Naive datetimes leak into stores that
    later misinterpret them as local time; we never let that happen here.
    """
    return datetime.now(timezone.utc)


@dataclass
class ChiefSession:
    """Durable envelope for a chief agent's work on a single WorkOrder.

    Created by ``ChiefDispatcher`` (Z4-S21 / #1392) when a WorkOrder is
    assigned to a department. Archived (state=SHUTDOWN) when the work order
    closes — never deleted.

    Attributes:
        session_id: Unique identifier (``cs-<12-hex>``).
        work_order_id: The WorkOrder this session serves.
        department: Department slug (e.g. ``"strategy"``).
        chief_name: The ``AgentSpec.name`` of the chief
            (e.g. ``"strategy-product-chief"``).
        state: Current lifecycle state.
        created_at_utc: When the session was created.
        warmed_at_utc: When the chief was first warmed (COLD -> WARM).
        execution_started_at_utc: When the most recent execution began
            (WARM -> EXECUTING). Overwritten on requeue.
        completed_at_utc: When the session reached a terminal state.
        idle_since_utc: Last time the chief returned from an EXECUTING run
            without transitioning to SHUTDOWN. Used by the idle-timeout
            reaper (Z4-S30 / #1391).
        run_count: Number of times EXECUTING was entered. Incremented on
            each WARM -> EXECUTING transition to support requeue flows.
        cost_usd: Accumulated cost charged to this session across all runs.
        error: Last error message, populated on FAILED transition.
        metadata: Arbitrary JSON-serialisable mapping for future extensions.

    Mutation discipline:
        ``ChiefSession`` is NOT a frozen dataclass. ``transition()`` returns
        a new instance via ``dataclasses.replace()`` — callers must use the
        returned value, not mutate the original. The "not frozen" choice is
        intentional so the SQLite-backed store (Z4-S03 / #1387) can update
        ``cost_usd`` in place without rebuilding the row, but ``transition()``
        itself follows the immutable-update convention.
    """

    session_id: str
    work_order_id: str
    department: str
    chief_name: str
    state: ChiefSessionState = ChiefSessionState.COLD
    created_at_utc: datetime = field(default_factory=_utc_now)
    warmed_at_utc: Optional[datetime] = None
    execution_started_at_utc: Optional[datetime] = None
    completed_at_utc: Optional[datetime] = None
    idle_since_utc: Optional[datetime] = None
    run_count: int = 0
    cost_usd: float = 0.0
    error: Optional[str] = None
    metadata: dict = field(default_factory=dict)

    def transition(
        self,
        new_state: ChiefSessionState,
        *,
        error: Optional[str] = None,
    ) -> "ChiefSession":
        """Return a new ChiefSession with the updated state.

        Raises ``InvalidTransitionError`` if the transition is not allowed
        by ``_ALLOWED_TRANSITIONS``. The original session is NOT mutated.
        Timestamps are updated automatically:

        - ``WARM``: ``warmed_at_utc`` set on first warming only (re-warm
          via requeue path does not overwrite the original)
        - ``EXECUTING``: ``execution_started_at_utc`` set; ``run_count``
          incremented; ``idle_since_utc`` cleared
        - ``DONE`` / ``FAILED`` / ``TIMED_OUT`` / ``SHUTDOWN``:
          ``completed_at_utc`` set
        - ``AWAITING_EVALUATION``: ``idle_since_utc`` set
        - ``FAILED`` (with ``error`` argument): ``error`` field populated

        Args:
            new_state: The state to transition to.
            error: Optional error message; populated only when
                transitioning to ``FAILED``.
        """
        allowed = _ALLOWED_TRANSITIONS.get(self.state, frozenset())
        if new_state not in allowed:
            raise InvalidTransitionError(self.state, new_state)

        now = _utc_now()
        updates: dict = {"state": new_state}

        if new_state == ChiefSessionState.WARM and self.warmed_at_utc is None:
            updates["warmed_at_utc"] = now
        if new_state == ChiefSessionState.EXECUTING:
            updates["execution_started_at_utc"] = now
            updates["run_count"] = self.run_count + 1
            updates["idle_since_utc"] = None
        if new_state == ChiefSessionState.AWAITING_EVALUATION:
            updates["idle_since_utc"] = now
        if new_state in (
            ChiefSessionState.DONE,
            ChiefSessionState.FAILED,
            ChiefSessionState.TIMED_OUT,
            ChiefSessionState.SHUTDOWN,
        ):
            updates["completed_at_utc"] = now
        if new_state == ChiefSessionState.FAILED and error is not None:
            updates["error"] = error

        return dataclasses.replace(self, **updates)

    def is_terminal(self) -> bool:
        """Return True if the session has reached the SHUTDOWN state.

        Used by the store (Z4-S03 / #1387) to decide when a row may be
        moved from the active table to the archive table.
        """
        return self.state == ChiefSessionState.SHUTDOWN

    def is_idle(self) -> bool:
        """Return True if the session is idle and eligible for timeout reaping.

        A session is "idle" when it is in AWAITING_EVALUATION (the chief
        finished an execution but the orchestrator hasn't decided whether
        to requeue or terminate) AND ``idle_since_utc`` is set. The
        idle-timeout reaper (Z4-S30 / #1391) reads this to decide which
        sessions to TIMED_OUT.
        """
        return (
            self.state == ChiefSessionState.AWAITING_EVALUATION
            and self.idle_since_utc is not None
        )

    def add_cost(self, delta_usd: float) -> "ChiefSession":
        """Return a new ChiefSession with ``cost_usd`` incremented.

        Helper for the cost-charging path (Z4-S40 / #1398). Negative
        deltas are accepted (refund / reconciliation paths) but ``cost_usd``
        is not floored at zero — callers are expected to keep accounting
        consistent. Returns a new instance per the immutable-update
        convention.
        """
        return dataclasses.replace(self, cost_usd=self.cost_usd + delta_usd)

    def to_dict(self) -> dict:
        """Return a JSON-safe dict representation of the session.

        Used by the REST API (Z4-S12 / #1383) to serialise sessions for
        Mission Control. Datetime fields are emitted as ISO-8601 strings
        (matching the ``+00:00`` offset format the SQLite store round-trips
        through), the state enum is rendered as its lowercase string value,
        and ``metadata`` is included verbatim — callers are responsible
        for ensuring its contents are JSON-serialisable.

        Returns a plain ``dict`` (not a frozen view): mutations on the
        returned mapping do not affect the source ``ChiefSession``.
        """
        return {
            "session_id": self.session_id,
            "work_order_id": self.work_order_id,
            "department": self.department,
            "chief_name": self.chief_name,
            "state": self.state.value,
            "created_at_utc": (
                self.created_at_utc.isoformat()
                if self.created_at_utc is not None
                else None
            ),
            "warmed_at_utc": (
                self.warmed_at_utc.isoformat()
                if self.warmed_at_utc is not None
                else None
            ),
            "execution_started_at_utc": (
                self.execution_started_at_utc.isoformat()
                if self.execution_started_at_utc is not None
                else None
            ),
            "completed_at_utc": (
                self.completed_at_utc.isoformat()
                if self.completed_at_utc is not None
                else None
            ),
            "idle_since_utc": (
                self.idle_since_utc.isoformat()
                if self.idle_since_utc is not None
                else None
            ),
            "run_count": self.run_count,
            "cost_usd": self.cost_usd,
            "error": self.error,
            "metadata": dict(self.metadata),
        }
