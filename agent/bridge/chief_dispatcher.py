"""ChiefDispatcher orchestration layer — Z4-S21 (#1392).

The central coordinator for the Z4 chief-session epic. Given a ``WorkOrder``,
the dispatcher:

1. Calls a :class:`bridge.work_order_router.WorkOrderRouter` to pick a
   department + builds a ``RoutingDecision``.
2. Resolves the corresponding :class:`teams._types.DepartmentConfig` via the
   ``DepartmentRegistry`` (duck-typed — anything with ``get_config(name)``
   that returns a config or raises works).
3. Creates a :class:`bridge.chief_session.ChiefSession` row in the store
   and transitions COLD → WARM.
4. Hands the session + config + deps to a
   :class:`bridge.warm_chief.WarmChief` for execution. WarmChief drives
   WARM → EXECUTING → AWAITING_EVALUATION (or FAILED) and persists state
   on its own.
5. Publishes ``chief_dispatcher.routed`` / ``chief_dispatcher.rejected`` /
   ``chief_dispatcher.requeued`` events on the ``EventBus``.
6. Triggers a NUDGE escalation when the routing confidence is below 0.5
   (per ``RuleBasedWorkOrderRouter``'s tier-4 default-fallback confidence
   ``_CONFIDENCE_DEFAULT_FALLBACK = 0.3``).

The dispatcher is **stateless** between calls — every piece of state lives
in the store, the EventBus, or the escalation engine. It does NOT spawn
subprocesses or hold a reference to live ``DepartmentTeam`` objects.
Idle reaping lives in Z4-S30 (#1391). Retry-with-backoff for FAILED
sessions lives on this dispatcher (Z4-S60 #1404) as the
``retry_failed`` / ``retry_with_backoff`` orchestration pair —
operator-bounded, deterministic backoff, FAILED → WARM via the legal
state-machine arc.

Failure-handling discipline:

- **Routing error** → publish ``chief_dispatcher.rejected``, re-raise. No
  session is ever created. The store remains untouched.
- **Unknown department after routing** → ``RoutingError`` (config bug worth
  surfacing loudly). Emits ``chief_dispatcher.rejected`` like any router
  failure so the operator sees one consistent surface.
- **Chief raises during execution** → ``WarmChief.__aenter__`` already
  transitioned the row to FAILED and re-raised; the dispatcher catches,
  logs, and returns the persisted FAILED session. Routing still
  succeeded, so ``chief_dispatcher.routed`` was already published before
  the exception path.

Best-effort side channels:

- ``event_bus.publish()`` — if the bus is ``None`` or ``publish`` raises,
  log and continue. Never crash the dispatch path on observability.
- ``escalation.notify()`` — duck-typed; if absent or raises, log and
  continue. Same rationale: low-confidence NUDGE is a hint, not a gate.

Companion contracts (treated as shipped):

- ``bridge/chief_session.py`` (Z4-S01 #1385) — session row + state machine
- ``bridge/chief_session_store.py`` (Z4-S03 #1387 + Z4-S10 #1381) — store
  Protocol + in-memory + SQLite implementations
- ``bridge/work_order_router.py`` (Z4-S02 #1386 + Z4-S20 #1390) — router
  ABC + ``RuleBasedWorkOrderRouter``
- ``bridge/warm_chief.py`` (Z4-S11 #1382) — WarmChief context manager
- ``config/registry/events/chief-dispatcher.yaml`` (Z4-S04 #1389) —
  pre-cataloged events: routed / rejected / requeued
"""
from __future__ import annotations

import asyncio
import dataclasses
import logging
from typing import Any, Optional

from bridge.chief_session import (
    ChiefSession,
    ChiefSessionState,
    new_chief_session_id,
)
from bridge.chief_session_store import (
    ChiefSessionNotFoundError,
    ChiefSessionStore,
)
from bridge.circuit_breaker import CircuitBreaker, State as CircuitState
from bridge.cost_tracker import (
    CostMeasurement,
    is_chargeable_under_strict_budget,
)
from bridge.warm_chief import WarmChief
from bridge.work_order_router import (
    RoutingDecision,
    RoutingError,
    WorkOrderRouter,
)

logger = logging.getLogger(__name__)


# Confidence threshold below which the dispatcher fires a NUDGE alert to
# the operator. Per ``bridge.work_order_router``, the rule-based router's
# tier-4 default-fallback lands at 0.3 — below this threshold — so any
# WorkOrder routed by tier-4 produces a NUDGE. Tier-3 (BatchStrategy
# heuristic) at 0.5 sits exactly on the boundary and does NOT trigger;
# only confidence strictly less than 0.5 nudges.
_LOW_CONFIDENCE_THRESHOLD: float = 0.5


class InvalidRequeueError(ValueError):
    """Raised when ``ChiefDispatcher.requeue()`` is called on a session that
    is not in ``AWAITING_EVALUATION``.

    Subclasses ``ValueError`` so callers that already catch ``ValueError`` for
    bad input keep working, but the dedicated type lets routing logic
    distinguish "wrong-state requeue attempt" from "session does not exist"
    (which surfaces as ``ChiefSessionNotFoundError`` and is left to propagate).

    Attributes:
        session_id: The session id the caller asked us to requeue.
        actual_state: The state the session was actually in. Carried for
            audit trails and operator-visible error messages so the
            caller can decide whether to fail loud, requeue later, or
            shut the session down.
    """

    def __init__(
        self,
        session_id: str,
        actual_state: "ChiefSessionState",
    ) -> None:
        super().__init__(
            f"Cannot requeue session {session_id!r}: "
            f"current state is {actual_state.value!r}, "
            f"expected {ChiefSessionState.AWAITING_EVALUATION.value!r}"
        )
        self.session_id = session_id
        self.actual_state = actual_state


class MaxRetriesExceededError(Exception):
    """Raised when ``retry_with_backoff`` is called past ``retry_max_attempts``.

    This is a final-state failure, not a contract violation — the FAILED
    session has exhausted its retry budget and the orchestrator must
    escalate to the operator (or move on). Subclasses ``Exception``
    directly (NOT ``ValueError``) because the caller did nothing wrong:
    the policy budget is just empty.

    Attributes:
        session_id: The session id we stopped retrying.
        final_attempt: The attempt number that tripped the cap (i.e. the
            attempt the caller was about to perform when the budget said
            "no more"). For ``retry_max_attempts=3`` this is 4 — the
            value we refused to dispatch.
        last_error: Free-form note about why retries stopped here.
            Populated by the dispatcher with the active policy values
            for audit trails.
    """

    def __init__(
        self,
        session_id: str,
        *,
        final_attempt: int,
        last_error: str = "",
    ) -> None:
        super().__init__(
            f"Retry budget exhausted for session {session_id!r}: "
            f"attempt={final_attempt} exceeds policy. {last_error}".rstrip()
        )
        self.session_id = session_id
        self.final_attempt = final_attempt
        self.last_error = last_error


class ChiefDispatcher:
    """Orchestrates ``WorkOrder`` → ``ChiefSession`` → ``WarmChief`` execution.

    Construction takes injected dependencies (router, store, registry,
    optional event bus, optional escalation). The dispatcher is stateless
    — a single instance can serve the lifetime of the bridge.

    Args:
        router: A ``WorkOrderRouter`` implementation. ``route(work_order)``
            returns a ``RoutingDecision`` or raises ``RoutingError``.
        session_store: A ``ChiefSessionStore`` (Protocol). The dispatcher
            calls ``create(session)`` once per dispatch and reads the final
            state via ``get(session_id)`` after ``WarmChief`` exits.
        dept_registry: Duck-typed registry. Must expose
            ``get_config(name) -> DepartmentConfig`` (may raise / return
            ``None`` for unknown departments — both are handled).
        event_bus: Optional ``EventBus``. If ``None``, events are dropped
            silently (with a one-line debug log). ``publish()`` is sync
            per the bridge's bus contract.
        escalation: Optional duck-typed escalation engine. If present,
            the dispatcher calls ``notify(level, source, message)`` on
            low-confidence routing (best-effort).
    """

    def __init__(
        self,
        *,
        router: WorkOrderRouter,
        session_store: ChiefSessionStore,
        dept_registry: Any,
        event_bus: Optional[Any] = None,
        escalation: Optional[Any] = None,
        budget_guard: Optional[Any] = None,
        cost_tracker: Optional[Any] = None,
        strict_budget_enforcement: bool = False,
        retry_max_attempts: int = 3,
        retry_initial_backoff_seconds: float = 5.0,
        retry_max_backoff_seconds: float = 300.0,
        retry_backoff_multiplier: float = 2.0,
        circuit_failure_threshold: int = 3,
        circuit_recovery_timeout_seconds: float = 300.0,
        skill_allocator: Optional[Any] = None,
        # Sprint 5.00c (#2155) — workflow-first dispatch
        workflow_registry: Optional[Any] = None,
        workflow_engine: Optional[Any] = None,
        workflow_first_dispatch_enabled: bool = False,
        workflow_match_threshold: float = 0.6,
        # zone4-warmth.C.02 (#2296) — warmth-reuse lookup
        warmth_reuse_enabled: bool = False,
        warmth_idle_window_seconds: float = 1800.0,
    ) -> None:
        self._router = router
        self._store = session_store
        self._registry = dept_registry
        self._event_bus = event_bus
        self._escalation = escalation
        # audit-2026-05-16.D.04 (#2065) — wire cost-cap dependencies into the
        # dispatcher so they reach ``WarmChief``. Before this sprint the
        # dispatcher constructed WarmChief without a ``cost_tracker``,
        # silently disabling the pre/post-flight cap enforcement that
        # WarmChief was written to perform (audit M-1 in
        # ``docs/audits/2026-05-16-whole-codebase-audit.md``). Both are
        # optional — default ``None`` / ``False`` preserves back-compat for
        # every existing test fixture and call site that does not yet wire
        # cost enforcement.
        #
        # ``cost_tracker`` is duck-typed: anything that exposes
        # ``get_session_cost(session_id) -> float`` satisfies WarmChief's
        # existing pre/post-flight contract. When the tracker additionally
        # exposes ``last_session_measurement(session_id) -> CostMeasurement
        # | None`` AND ``strict_budget_enforcement`` is True, the dispatcher
        # performs a strict-mode pre-flight: if the most recent measurement
        # for this session is ``source='unknown'``, the dispatch fails
        # closed BEFORE WarmChief is invoked (the strict CostMeasurement
        # contract per audit-2026-05-16.D.01 #2062 — we refuse to charge
        # against a cap when we cannot trust the prior cost).
        self._cost_tracker = cost_tracker
        self._strict_budget_enforcement = bool(strict_budget_enforcement)
        # P3.4 (#1586) — optional daily-budget pre-flight enforcement. Duck-
        # typed against ``bridge.budget.BudgetGuard``: anything that exposes
        # ``async check() -> dict`` with an ``allowed`` key works. When None
        # (default — back-compat for unit tests and call sites that haven't
        # opted in), the pre-flight check is a no-op and dispatch proceeds
        # exactly as before. When wired, ``dispatch()`` consults
        # ``budget_guard.check()`` BEFORE creating the session row; if the
        # daily budget is exhausted, the dispatch is rejected, a session row
        # is recorded in COLD → SHUTDOWN with ``metadata.block_reason =
        # "daily_budget_exhausted"`` for observability, ``chief_dispatcher.
        # rejected`` fires with the reason, and an URGENT escalation surfaces
        # to the operator.
        self._budget_guard = budget_guard
        # Z4-S60 (#1404) — retry policy. Defaults mirror BridgeConfig so
        # ad-hoc construction (tests, scripts) gets the same shape the
        # production wiring uses. BridgeApp passes the BridgeConfig values
        # explicitly when it stands the dispatcher up.
        self._retry_max_attempts = retry_max_attempts
        self._retry_initial_backoff_seconds = retry_initial_backoff_seconds
        self._retry_max_backoff_seconds = retry_max_backoff_seconds
        self._retry_backoff_multiplier = retry_backoff_multiplier
        # Z4-S64 (#1408) — per-department circuit breakers. One breaker per
        # department slug, lazily created on first use. After a chief run
        # we record success (AWAITING_EVALUATION) or failure (FAILED) on
        # the breaker for the department we ran on; before each dispatch
        # we skip departments whose breaker is OPEN and try
        # ``decision.fallback_departments`` in order.
        self._circuit_breakers: dict[str, CircuitBreaker] = {}
        self._circuit_failure_threshold = circuit_failure_threshold
        self._circuit_recovery_timeout_seconds = circuit_recovery_timeout_seconds
        # Sprint #1112/4.03 (#2150) — SkillAllocator handle threaded down
        # to WarmChief on every dispatch. None (the default) preserves
        # back-compat for tests that construct the dispatcher without one;
        # production wiring (bridge.app_init) always passes the live
        # allocator. WarmChief / DepartmentTeam / build_*_agent treat None
        # as "no allocator wired — skip filter, log nothing" (back-compat).
        self._skill_allocator = skill_allocator
        # Sprint 5.00c (#2155) — workflow-first dispatch handles. When the
        # flag is True AND a directive matches a registered workflow above
        # ``workflow_match_threshold``, ``dispatch()`` short-circuits before
        # routing/chief construction: it fires the workflow via the engine
        # and returns a synthesized ChiefSession (SHUTDOWN, metadata.workflow_run_id)
        # so callers see a stable contract. When the flag is False (default),
        # all four handles are ignored and dispatch behaves as before #2155.
        self._workflow_registry = workflow_registry
        self._workflow_engine = workflow_engine
        self._workflow_first_dispatch_enabled = bool(workflow_first_dispatch_enabled)
        self._workflow_match_threshold = float(workflow_match_threshold)
        # zone4-warmth.C.02 (#2296) — warmth-reuse handles. When the flag
        # is True, ``dispatch()`` consults ``store.find_warm_session`` after
        # routing succeeds; a match short-circuits into a row-reuse path
        # (AWAITING_EVALUATION → WARM, run_count bump, publish
        # ``chief_dispatcher.warmth_reused``, return). When the flag is
        # False (default), the lookup is never called and dispatch behaves
        # byte-identically to today. C.01 (#2295) introduced the flag on
        # ``BridgeConfig``; we capture both values here so wiring callers
        # only need to pass them once at construction.
        self._warmth_reuse_enabled = bool(warmth_reuse_enabled)
        self._warmth_idle_window_seconds = float(warmth_idle_window_seconds)

    async def dispatch(self, work_order: Any, deps: Any) -> ChiefSession:
        """Route, execute, and persist a single ``WorkOrder``.

        Args:
            work_order: The ``WorkOrder`` to dispatch. Read-only — the
                dispatcher never mutates it.
            deps: A ``BridgeDeps`` instance (or duck-typed equivalent)
                threaded through to the chief run via ``WarmChief``.

        Returns:
            The final ``ChiefSession`` after ``WarmChief`` exits — state
            is ``AWAITING_EVALUATION`` on success, ``FAILED`` if the chief
            raised during execution.

        Raises:
            RoutingError: If the router could not pick a department, or
                if the picked department is not registered. In both cases
                ``chief_dispatcher.rejected`` is published before the
                exception propagates and NO ``ChiefSession`` row is
                created.

        Note (zone4-warmth.C.03 #2297): on the warm-reuse path the
        dispatcher also loads + deserializes the prior
        ``message_history`` blob from the store and threads it as a
        construction argument into ``WarmChief`` so the chief picks up
        its prior context instead of bootstrapping fresh. Observability
        of "did history actually carry forward?" lives on the
        ``chief_dispatcher.warmth_reused`` event payload
        (``message_history_present`` + ``message_history_count``) — the
        public ``dispatch`` return shape stays a ``ChiefSession`` so the
        ~40+ test sites and 4 production callers of this method don't
        need to change. The spec's "Option 2" pattern: signature stays
        stable, observability rides on the event bus.
        """
        # P3.3 (#1584) — every event in the dispatch chain carries the
        # WorkOrder id as its top-level ``correlation_id`` so an operator
        # subscribing to ``/ws/events`` can pivot from a WO id to the full
        # routed → created → state_changed lineage in one filter.
        correlation_id = _wo_id(work_order)

        # Sprint 5.00c (#2155) — workflow-first dispatch hook. When the
        # operator has opted in AND a registered workflow matches the
        # directive above the configured threshold, short-circuit chief
        # deliberation: fire the workflow directly via WorkflowEngine and
        # return a synthesized ChiefSession in SHUTDOWN state with
        # ``metadata.workflow_run_id`` so callers see a stable contract.
        # Flag-off (default) makes this block a one-line no-op.
        if (
            self._workflow_first_dispatch_enabled
            and self._workflow_registry is not None
            and self._workflow_engine is not None
        ):
            directive_text = self._extract_directive_text(work_order)
            match = self._workflow_registry.match(directive_text)
            if (
                match is not None
                and match.get("confidence", 0.0) >= self._workflow_match_threshold
            ):
                workflow_short = await self._workflow_first_dispatch(
                    work_order=work_order,
                    match=match,
                    correlation_id=correlation_id,
                )
                if workflow_short is not None:
                    return workflow_short

        # Step 1 — route. RoutingError → rejected event + re-raise.
        try:
            decision = await self._router.route(work_order)
        except RoutingError as exc:
            self._publish(
                "chief_dispatcher.rejected",
                {
                    "work_order_id": _wo_id(work_order),
                    "reason": exc.reason,
                },
                correlation_id=correlation_id,
            )
            raise

        logger.info(
            "chief_dispatcher.routed wo=%s -> %s (confidence=%.2f)",
            _wo_id(work_order),
            decision.department,
            decision.confidence,
        )

        # Step 1.4 — zone4-warmth.C.02 (#2296) warmth-reuse lookup +
        # zone4-warmth.C.03 (#2297) message_history reload.
        #
        # When the flag is True, ask the store for an existing
        # AWAITING_EVALUATION session for (department, operator) inside
        # the configured warm window. A match transitions
        # AWAITING_EVALUATION → WARM (C.02), loads + deserializes the
        # persisted message_history blob (C.03), publishes
        # ``chief_dispatcher.warmth_reused`` with the history-present
        # signal, and short-circuits the cold-start path: we re-use the
        # existing row instead of creating a new one. The chief still
        # runs via WarmChief further down — but with the loaded
        # message_history threaded into ``manager.run(message_history=...)``
        # so PydanticAI skips the system-prompt regeneration that would
        # otherwise re-cost the prompt at every dispatch. That's the
        # token-saving wire warmth was designed to enable.
        #
        # Flag-off path is byte-identical to before C.02: the
        # ``find_warm_session`` method is never called and no new code
        # executes.
        reused_session: Optional[ChiefSession] = None
        message_history: Optional[list[Any]] = None
        if self._warmth_reuse_enabled:
            operator = self._extract_operator(work_order)
            warm_session = await self._store.find_warm_session(
                department=decision.department,
                operator=operator,
                max_age_seconds=self._warmth_idle_window_seconds,
            )
            if warm_session is not None:
                reused = warm_session.transition(ChiefSessionState.WARM)
                # State-machine WARM transition does NOT increment
                # run_count (that only happens on WARM → EXECUTING, per
                # ``ChiefSession.transition``). WarmChief's __aenter__
                # will perform the WARM → EXECUTING transition below,
                # which DOES bump run_count via the state machine —
                # exactly what we want for accurate accounting of "how
                # many times has this conversation been resumed".
                await self._store.update(reused)
                # C.03 (#2297) — load + deserialize the prior history.
                # Non-fatal: corruption falls back to None and the chief
                # boots fresh, matching cold-start semantics.
                blob = await self._store.get_message_history(
                    warm_session.session_id,
                )
                message_history = self._deserialize_history_safe(
                    blob, warm_session.session_id,
                )
                age_seconds = self._warm_age_seconds(warm_session)
                history_count = (
                    len(message_history) if message_history else 0
                )
                self._publish(
                    "chief_dispatcher.warmth_reused",
                    {
                        "session_id": reused.session_id,
                        "work_order_id": _wo_id(work_order),
                        "department": decision.department,
                        "operator": operator,
                        "age_seconds": age_seconds,
                        "run_count": reused.run_count,
                        # C.03 (#2297) — observability of the reload
                        # actually carrying conversation forward.
                        "message_history_present": (
                            message_history is not None
                        ),
                        "message_history_count": history_count,
                    },
                    correlation_id=correlation_id,
                )
                logger.info(
                    "chief_dispatcher.warmth_reused session=%s wo=%s "
                    "department=%s age_seconds=%.2f run_count=%d "
                    "history_present=%s history_count=%d",
                    reused.session_id,
                    _wo_id(work_order),
                    decision.department,
                    age_seconds,
                    reused.run_count,
                    message_history is not None,
                    history_count,
                )
                reused_session = reused

        # Step 1.5 — P3.4 (#1586) daily-budget pre-flight reject. Consult
        # the wired BudgetGuard (if any) before creating the session row.
        # On a budget-exhausted reply we record a SHUTDOWN session with
        # ``metadata.block_reason="daily_budget_exhausted"`` so the
        # operator can observe what was rejected, publish the rejected
        # event with the reason, fire an URGENT escalation surface, and
        # return the persisted blocked session. The chief never runs.
        blocked = await self._reject_if_daily_budget_exhausted(
            work_order, decision,
        )
        if blocked is not None:
            return blocked

        # Step 1.6 — audit-2026-05-16.D.04 (#2065) strict-budget pre-flight.
        # When the dispatcher was constructed with
        # ``strict_budget_enforcement=True`` AND a ``cost_tracker`` that
        # exposes ``last_session_measurement(session_id)``, refuse to
        # dispatch if the most recent CostMeasurement for the WO's prior
        # chief session carries ``source='unknown'``. Audit M-1 (and the
        # CostMeasurement contract from D.01) says: the strict gate must
        # not charge against a cap it cannot trust. ``is_chargeable_under_
        # strict_budget`` is the authoritative predicate — same module
        # the contract was introduced in. The reject mirrors the daily-
        # budget reject above: rejected event + structured log, no session
        # row created, no chief run.
        if (
            self._strict_budget_enforcement
            and self._cost_tracker is not None
            and hasattr(self._cost_tracker, "last_session_measurement")
        ):
            last_measurement = self._cost_tracker.last_session_measurement(
                _wo_id(work_order),
            )
            if (
                isinstance(last_measurement, CostMeasurement)
                and not is_chargeable_under_strict_budget(last_measurement)
                and last_measurement.source == "unknown"
            ):
                reason = (
                    f"strict_budget_unknown_cost: prior measurement source="
                    f"{last_measurement.source!r} backend="
                    f"{last_measurement.backend!r}"
                )
                logger.warning(
                    "chief_dispatcher.strict_budget_reject wo=%s reason=%s",
                    _wo_id(work_order),
                    reason,
                )
                self._publish(
                    "chief_dispatcher.rejected",
                    {
                        "work_order_id": _wo_id(work_order),
                        "reason": reason,
                        "department": decision.department,
                        "block_reason": "strict_budget_unknown_cost",
                        "measurement_source": last_measurement.source,
                        "measurement_backend": last_measurement.backend,
                    },
                    correlation_id=correlation_id,
                )
                raise RoutingError(_wo_id(work_order), reason)

        # Step 2 — resolve the department config. The registry is duck-
        # typed; some implementations raise (DepartmentRegistry uses
        # ``KeyError``), others return ``None`` (the work_order_router
        # test fakes do this). Treat both the same: if we can't get a
        # config, route the WorkOrder is unsatisfiable. Surface as a
        # rejected event + RoutingError so the failure path mirrors the
        # router-side rejection above.
        config = self._resolve_config(decision.department)
        if config is None:
            reason = f"department {decision.department!r} not registered"
            self._publish(
                "chief_dispatcher.rejected",
                {
                    "work_order_id": _wo_id(work_order),
                    "reason": reason,
                    "department": decision.department,
                },
                correlation_id=correlation_id,
            )
            raise RoutingError(_wo_id(work_order), reason)

        # Step 3 — pick or build the session row.
        #
        # zone4-warmth.C.03 (#2297): when ``reused_session`` was set
        # above by the warmth-reuse lookup, skip the new-row creation
        # and run the chief on top of the existing session. The reused
        # row was already transitioned AWAITING_EVALUATION → WARM and
        # persisted via ``update`` (Step 1.4) so WarmChief's __aenter__
        # picks up a WARM row exactly as it does on the cold-start path.
        # No ``chief_session.created`` event fires on reuse — the row
        # was created on a prior dispatch; a state_changed event is
        # published instead for the AWAITING_EVALUATION → WARM arc.
        #
        # Cold-start path (no reused_session): build a new COLD row,
        # transition COLD → WARM, persist via ``create``. WARM is the
        # state WarmChief expects (its __aenter__ transitions WARM →
        # EXECUTING).
        if reused_session is not None:
            session = reused_session
            session_id = session.session_id
            chief_name = session.chief_name
            self._publish(
                "chief_session.state_changed",
                {
                    "session_id": session_id,
                    "work_order_id": _wo_id(work_order),
                    "from_state": (
                        ChiefSessionState.AWAITING_EVALUATION.value
                    ),
                    "to_state": ChiefSessionState.WARM.value,
                },
                correlation_id=correlation_id,
            )
        else:
            session_id = new_chief_session_id()
            chief_name = getattr(config.manager, "name", "")
            # zone4-warmth.C.02 (#2296) — stamp the operator into
            # metadata so the AWAITING_EVALUATION row this session
            # eventually becomes is eligible for warmth-reuse next time
            # the same operator dispatches against the same department.
            # The find_warm_session lookup keys on this exact metadata
            # field. The value is computed by the same
            # ``_extract_operator`` helper the warmth lookup uses, so
            # the write side and the read side agree on the fallback.
            session = ChiefSession(
                session_id=session_id,
                work_order_id=_wo_id(work_order),
                department=decision.department,
                chief_name=chief_name,
                metadata={
                    "operator": self._extract_operator(work_order),
                    "routing_decision": {
                        "rationale": decision.rationale,
                        "confidence": decision.confidence,
                        "fallback_departments": list(
                            decision.fallback_departments
                        ),
                    },
                },
            )
            # COLD → WARM via the state machine; never mutate state directly.
            session = session.transition(ChiefSessionState.WARM)
            await self._store.create(session)

            # Step 3.5 — P3.3 (#1584): publish ``chief_session.created`` once
            # the session row is durable. Mirrors the catalog entry at
            # ``agent/config/registry/events/chief-session.yaml`` (declared in
            # Z4-S01 #1385). The COLD → WARM transition that just happened is
            # surfaced separately via ``chief_session.state_changed`` so a
            # subscriber sees creation and lifecycle as two distinct signals.
            self._publish(
                "chief_session.created",
                {
                    "session_id": session_id,
                    "work_order_id": _wo_id(work_order),
                    "department": decision.department,
                    "chief_name": chief_name,
                    "state": session.state.value,
                },
                correlation_id=correlation_id,
            )
            self._publish(
                "chief_session.state_changed",
                {
                    "session_id": session_id,
                    "work_order_id": _wo_id(work_order),
                    "from_state": ChiefSessionState.COLD.value,
                    "to_state": ChiefSessionState.WARM.value,
                },
                correlation_id=correlation_id,
            )

        # Step 4 — publish chief_dispatcher.routed BEFORE the run starts.
        # This pairs with the WorkOrder's lifecycle: the routing decision
        # is durable as soon as the session row exists; whether the chief
        # later succeeds or fails is a separate signal (the WarmChief-
        # driven AWAITING_EVALUATION / FAILED transitions cover that).
        self._publish(
            "chief_dispatcher.routed",
            {
                "work_order_id": _wo_id(work_order),
                "session_id": session_id,
                "department": decision.department,
                "rationale": decision.rationale,
                "confidence": decision.confidence,
                "fallback_departments": list(decision.fallback_departments),
            },
            correlation_id=correlation_id,
        )

        # Step 5 — low-confidence NUDGE escalation. Fires when the router
        # could not commit to a high-confidence decision (tier-4 default
        # fallback at 0.3 is the canonical case). Best-effort: never
        # crash the dispatch path on an escalation failure.
        if decision.confidence < _LOW_CONFIDENCE_THRESHOLD:
            self._nudge_low_confidence(work_order, decision, session_id)

        # Step 6 — circuit-breaker check (Z4-S64 #1408). If the chosen
        # department's breaker is OPEN, walk ``decision.fallback_departments``
        # in order until one is not OPEN. If all candidates are OPEN, surface
        # a RoutingError so the caller learns the dispatch could not run —
        # the session row already exists in WARM and stays there for the
        # reaper or the operator to deal with.
        breaker = self._get_breaker(decision.department)
        run_department = decision.department
        run_config = config
        if breaker.state == CircuitState.OPEN:
            fallback = self._pick_fallback_department(decision)
            if fallback is None:
                reason = (
                    f"all candidate departments OPEN: "
                    f"{[decision.department, *decision.fallback_departments]}"
                )
                logger.warning(
                    "chief_dispatcher.all_circuits_open session=%s wo=%s",
                    session_id,
                    _wo_id(work_order),
                )
                raise RoutingError(_wo_id(work_order), reason)
            fallback_config = self._resolve_config(fallback)
            if fallback_config is None:
                # Fallback named but not registered. Treat the same as
                # "all OPEN" — the operator-visible message names what
                # we actually walked.
                reason = (
                    f"fallback department {fallback!r} not registered "
                    f"(primary {decision.department!r} circuit OPEN)"
                )
                raise RoutingError(_wo_id(work_order), reason)
            run_department = fallback
            run_config = fallback_config
            breaker = self._get_breaker(run_department)
            logger.info(
                "chief_dispatcher.fallback session=%s primary=%s -> %s",
                session_id,
                decision.department,
                run_department,
            )
            # F1 fix (#1501): record the actual run-department on the session
            # row's metadata so /api/chief_sessions reflects which chief
            # actually ran. The top-level `department` field stays at the
            # primary (it records the routing DECISION); metadata records
            # the routing OUTCOME. Best-effort: a metadata-update failure
            # does not change the run-department; we still execute the chief.
            try:
                session = await self._store.get(session_id)
                updated_metadata = dict(session.metadata)
                updated_metadata["actual_run_department"] = run_department
                updated_metadata["fallback_used"] = True
                updated_metadata["fallback_reason"] = (
                    f"primary {decision.department!r} circuit OPEN"
                )
                session = dataclasses.replace(session, metadata=updated_metadata)
                await self._store.update(session)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "chief_dispatcher.fallback_metadata_update_failed "
                    "session=%s error=%s — chief still runs on %s",
                    session_id,
                    exc,
                    run_department,
                )

        # Step 7 — execute via WarmChief. WarmChief drives:
        #   WARM → EXECUTING (on __aenter__)
        #   EXECUTING → AWAITING_EVALUATION (on __aexit__, success)
        #   EXECUTING → FAILED (on chief raising, re-raises)
        # We catch the chief-raising case so a single dispatch always
        # returns a persisted ChiefSession instead of a half-handled
        # exception. Routing already succeeded; the executor failure is
        # a separate concern that surfaces via the FAILED row + future
        # error-handling sprints.
        task = _task_from_work_order(work_order)
        try:
            # P3.3 (#1584) — pass event_bus + correlation_id so WarmChief
            # publishes ``chief_session.state_changed`` for each
            # WARM → EXECUTING → AWAITING_EVALUATION/FAILED transition,
            # tagged with the WO id as correlation_id.
            #
            # audit-2026-05-16.D.04 (#2065) — pass ``cost_tracker`` so
            # WarmChief's optional pre/post-flight cap enforcement at
            # ``bridge/warm_chief.py:_enforce_cost_cap_preflight`` and
            # ``_compute_cost_cap_breach`` becomes a no-op only when the
            # dispatcher was constructed without one (the back-compat
            # default). The prior shape silently passed ``None`` here,
            # disabling enforcement on every dispatcher-driven path —
            # audit finding M-1.
            async with WarmChief(
                session,
                self._store,
                run_config,
                deps,
                task,
                cost_tracker=self._cost_tracker,
                event_bus=self._event_bus,
                correlation_id=correlation_id,
                # Sprint #1112/4.03 (#2150) — thread allocator down to the
                # team build path so each chief/specialist gets its allowed
                # skills filtered at construction time.
                skill_allocator=self._skill_allocator,
                # zone4-warmth.C.03 (#2297) — pass the pre-loaded message
                # history on warm-reuse so the chief resumes prior context
                # via ``manager.run(message_history=...)``. None on cold-
                # start; WarmChief treats None as "fresh boot, no kwarg".
                message_history=message_history,
            ):
                pass
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "chief_dispatcher.run_failed session=%s wo=%s error=%s",
                session_id,
                _wo_id(work_order),
                exc,
            )

        # Step 8 — re-fetch the final state. WarmChief's __aexit__ wrote
        # AWAITING_EVALUATION (or its __aenter__ wrote FAILED on the
        # exception path). Either way, the store has the truth.
        try:
            final = await self._store.get(session_id)
        except ChiefSessionNotFoundError:
            # Defensive — the row was created above; if we can't read it
            # back, the store is broken. Log and return the in-memory
            # snapshot we last knew about so the caller still sees
            # something valid.
            logger.error(
                "chief_dispatcher.store_lost session=%s — returning local snapshot",
                session_id,
            )
            return session

        # Step 9 — record the outcome on the per-department circuit breaker
        # (Z4-S64 #1408). Best-effort: a broken breaker must not change the
        # session row we return. Emit ``circuit_open`` / ``circuit_closed``
        # only on a state transition so subscribers don't see chatter on
        # every dispatch.
        self._record_breaker_outcome(run_department, breaker, final)

        return final

    async def requeue(self, session_id: str) -> ChiefSession:
        """Requeue a session from AWAITING_EVALUATION back to WARM.

        Z4-S31 (#1393) hardens the original Z4-S21 stub. The dispatcher
        looks up the live session row in the store rather than trusting
        a caller-supplied snapshot — stale snapshots were the obvious
        foot-gun in the prior signature, and the operator command path
        (``/requeue_chief <session_id>``) only knows the id.

        State-machine contract:

        - AWAITING_EVALUATION → WARM is the only legal arc. Any other
          source state raises :class:`InvalidRequeueError` (ValueError
          subclass) carrying the actual state for the caller to log /
          surface. We do NOT silently degrade to a no-op — re-running a
          chief is consequential, and a caller asking us to requeue a
          mid-run session has a bookkeeping bug.
        - ``run_count`` is NOT incremented here. The state machine only
          increments on WARM → EXECUTING (per ``ChiefSession.transition``);
          requeueing twice without a run in between is therefore the
          same as requeueing once for accounting purposes. This sprint
          does NOT add a separate "attempted-requeue" counter — the
          published event carries the current ``run_count`` as
          ``attempt`` so subscribers can audit the requeue sequence
          themselves.

        Persistence is mandatory — if ``store.update`` raises, the
        caller learns about it. Event publish is best-effort (matches
        the dispatcher's discipline elsewhere): a broken EventBus does
        not block the requeue from taking effect.

        Args:
            session_id: The session to requeue. The session is read
                from ``store.get(session_id)``; ``ChiefSessionNotFoundError``
                propagates so the caller can decide whether the missing
                row is a fatal error or a stale id.

        Returns:
            The updated ``ChiefSession`` (now in WARM, same ``run_count``).

        Raises:
            ChiefSessionNotFoundError: If the store has no row with
                ``session_id``. Propagated as-is.
            InvalidRequeueError: If the session is not in
                AWAITING_EVALUATION. Carries ``session_id`` and
                ``actual_state`` for audit.
        """
        session = await self._store.get(session_id)

        if session.state != ChiefSessionState.AWAITING_EVALUATION:
            raise InvalidRequeueError(session_id, session.state)

        new_session = session.transition(ChiefSessionState.WARM)
        # store.update is NOT best-effort — callers must know if the
        # requeue failed to persist. Publish IS best-effort below.
        await self._store.update(new_session)
        self._publish(
            "chief_dispatcher.requeued",
            {
                "session_id": new_session.session_id,
                "work_order_id": new_session.work_order_id,
                "attempt": new_session.run_count,
            },
            correlation_id=new_session.work_order_id,
        )
        logger.info(
            "chief_dispatcher.requeued session=%s attempt=%d",
            new_session.session_id,
            new_session.run_count,
        )
        return new_session

    def _compute_backoff_seconds(self, attempt: int) -> float:
        """Compute the deterministic backoff for retry attempt ``attempt``.

        Formula: ``min(initial * (multiplier ** (attempt - 1)), max_backoff)``.

        Indexing rationale: ``attempt=1`` is the FIRST retry (after the
        initial run failed), so the first backoff equals ``initial`` —
        no exponentiation on the first hop. The cap is applied AFTER the
        exponentiation, so a runaway multiplier never produces a
        multi-hour wait.

        Args:
            attempt: 1-indexed retry attempt. Negative or zero produces
                an out-of-range exponent and would invert the math; the
                caller is responsible for staying ≥ 1. ``retry_with_backoff``
                bumps from 1 onwards.

        Returns:
            The wait, in seconds, before the requeue happens.
        """
        raw = self._retry_initial_backoff_seconds * (
            self._retry_backoff_multiplier ** (attempt - 1)
        )
        return min(raw, self._retry_max_backoff_seconds)

    async def retry_failed(self, session_id: str) -> ChiefSession:
        """Re-warm a FAILED session for another run. FAILED → WARM.

        Companion to :meth:`requeue`, kept narrow on purpose:
        ``requeue`` is the operator-driven re-warm of a successful
        AWAITING_EVALUATION session; ``retry_failed`` is the
        retry-policy re-warm of a FAILED session. Both end at WARM but
        the entry contract differs, and folding them into one method
        with an ``allow_failed=True`` parameter would muddy the audit
        trail. The state-machine arc FAILED → WARM is already legal per
        ``chief_session._ALLOWED_TRANSITIONS[FAILED]`` (Z4-S01 #1385).

        Like ``requeue``, this:

        - reads the session row from the store (no caller-supplied snapshot)
        - persists the new WARM row
        - publishes ``chief_dispatcher.requeued`` (the existing event covers
          the retry path too — same audit trail; subscribers see ``attempt``
          climb across the sequence)

        Args:
            session_id: The session to re-warm. ``ChiefSessionNotFoundError``
                propagates so the caller distinguishes "missing row" from
                "wrong state".

        Returns:
            The updated ``ChiefSession`` (now in WARM, same ``run_count``).

        Raises:
            ChiefSessionNotFoundError: If the store has no row with
                ``session_id``. Propagated as-is.
            InvalidRequeueError: If the session is not in FAILED. The
                error carries ``session_id`` and ``actual_state``; we
                reuse the same exception type as ``requeue`` so callers
                that already log it get one consistent surface.
        """
        session = await self._store.get(session_id)

        if session.state != ChiefSessionState.FAILED:
            raise InvalidRequeueError(session_id, session.state)

        new_session = session.transition(ChiefSessionState.WARM)
        # store.update is NOT best-effort — callers must know if the
        # re-warm failed to persist. Publish IS best-effort below.
        await self._store.update(new_session)
        self._publish(
            "chief_dispatcher.requeued",
            {
                "session_id": new_session.session_id,
                "work_order_id": new_session.work_order_id,
                "attempt": new_session.run_count,
            },
            correlation_id=new_session.work_order_id,
        )
        logger.info(
            "chief_dispatcher.retry_failed session=%s attempt=%d",
            new_session.session_id,
            new_session.run_count,
        )
        return new_session

    async def retry_with_backoff(
        self,
        session_id: str,
        *,
        attempt: int = 1,
    ) -> ChiefSession:
        """Wait, then re-warm a FAILED session — bounded by the retry policy.

        Higher-level orchestration around :meth:`retry_failed`. Computes
        the backoff via :meth:`_compute_backoff_seconds`, ``await``-sleeps
        for that duration, then re-warms the session. The sleep happens
        BEFORE the requeue (operator-visible: "wait, then retry"), so a
        downstream observer of ``chief_dispatcher.requeued`` sees the
        event at the moment the chief is back on the queue, not at the
        moment the policy decided to retry.

        Backoff is computed deterministically — the formula is documented
        on :meth:`_compute_backoff_seconds` and unit-tested. The sleep
        uses ``asyncio.sleep`` directly (not a custom wrapper) so test
        suites can ``unittest.mock.patch("asyncio.sleep")`` to keep the
        suite fast.

        Args:
            session_id: The FAILED session to retry.
            attempt: 1-indexed retry attempt. Defaults to 1 (the first
                retry after the initial run failed). Past
                ``retry_max_attempts`` we raise — the budget is exhausted.

        Returns:
            The re-warmed ``ChiefSession`` (now in WARM).

        Raises:
            MaxRetriesExceededError: When ``attempt`` exceeds the
                configured ``retry_max_attempts``. Carries ``session_id``
                and ``final_attempt`` for audit / escalation.
            ChiefSessionNotFoundError: If the session does not exist.
            InvalidRequeueError: If the session is not in FAILED state
                (e.g. caller asked us to retry an EXECUTING session).
        """
        if attempt > self._retry_max_attempts:
            raise MaxRetriesExceededError(
                session_id,
                final_attempt=attempt,
                last_error=(
                    f"retry_max_attempts={self._retry_max_attempts} reached"
                ),
            )

        backoff_seconds = self._compute_backoff_seconds(attempt)
        logger.info(
            "chief_dispatcher.retry_backoff session=%s attempt=%d "
            "backoff_seconds=%.2f",
            session_id,
            attempt,
            backoff_seconds,
        )
        # asyncio.sleep is mockable in tests via unittest.mock.patch.
        await asyncio.sleep(backoff_seconds)
        return await self.retry_failed(session_id)

    async def shutdown_session(
        self,
        session_id: str,
        note: str = "bridge exit",
    ) -> None:
        """Force-transition a session to SHUTDOWN. Idempotent on already-SHUTDOWN.

        SHUTDOWN is reachable only from terminal states (DONE / FAILED /
        TIMED_OUT) and from COLD / WARM. From mid-run states (EXECUTING,
        AWAITING_EVALUATION) the state machine routes through FAILED
        first to keep the audit trail honest about the cause: a
        force-shutdown of a still-running session is recorded as a
        failure with an explanatory error string.

        Args:
            session_id: The session to shut down.
            note: Free-form note included in the synthetic FAILED error
                when the session was non-terminal. Surfaces in the
                stored row's ``error`` field for post-mortem.
        """
        try:
            session = await self._store.get(session_id)
        except ChiefSessionNotFoundError:
            return  # nothing to shut down

        if session.state == ChiefSessionState.SHUTDOWN:
            return  # idempotent

        # Sessions in EXECUTING / AWAITING_EVALUATION cannot transition
        # directly to SHUTDOWN. Route them through FAILED first so the
        # state machine accepts the move and the audit trail records
        # the force-shutdown cause.
        if session.state in (
            ChiefSessionState.EXECUTING,
            ChiefSessionState.AWAITING_EVALUATION,
        ):
            session = session.transition(
                ChiefSessionState.FAILED,
                error=f"force-shutdown: {note}",
            )
            await self._store.update(session)

        session = session.transition(ChiefSessionState.SHUTDOWN)
        await self._store.update(session)
        logger.info(
            "chief_dispatcher.shutdown session=%s note=%s",
            session_id,
            note,
        )

    # ------------------------------------------------------------------
    # Internal helpers (best-effort side channels)
    # ------------------------------------------------------------------

    async def _reject_if_daily_budget_exhausted(
        self,
        work_order: Any,
        decision: RoutingDecision,
    ) -> Optional[ChiefSession]:
        """P3.4 (#1586) — pre-flight daily-budget reject.

        Returns ``None`` when the guard is not wired or the daily budget
        has headroom — the dispatch proceeds. Returns a persisted
        SHUTDOWN ``ChiefSession`` row when the budget is exhausted; the
        caller should return that row directly to its caller without
        running the chief.

        Best-effort against guard failures: if ``budget_guard.check()``
        raises (e.g. SQLite connection just dropped), we log and return
        ``None`` so the chief still runs. The daily-budget signal is a
        safety rail, not a gate the dispatcher relies on for correctness.

        Side effects on the exhausted path:
        - Creates a ChiefSession row in COLD then transitions COLD →
          SHUTDOWN with ``metadata.block_reason="daily_budget_exhausted"``
          plus the budget telemetry (``spent_today``, ``daily_limit``).
        - Publishes ``chief_dispatcher.rejected`` with
          ``reason="daily_budget_exhausted"`` plus the same telemetry.
        - Fires an URGENT escalation via the duck-typed engine — the
          operator-visible surface of the budget block. Best-effort:
          escalation failures never change the returned session.
        """
        if self._budget_guard is None:
            return None
        try:
            status = await self._budget_guard.check()
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "chief_dispatcher.budget_check_failed wo=%s error=%s — "
                "proceeding with dispatch (fail-open)",
                _wo_id(work_order),
                exc,
            )
            return None
        if status.get("allowed", True):
            return None

        spent_today = float(status.get("spent_today", 0.0) or 0.0)
        daily_limit = float(status.get("daily_limit", 0.0) or 0.0)
        reason = "daily_budget_exhausted"

        # Build a blocked session row so /api/chief_sessions can show the
        # operator what was rejected. COLD → SHUTDOWN is the legal arc;
        # the budget telemetry lives in metadata + the routing decision
        # is captured the same way the happy path captures it.
        session_id = new_chief_session_id()
        chief_name = ""  # config not resolved yet — keep blank
        session = ChiefSession(
            session_id=session_id,
            work_order_id=_wo_id(work_order),
            department=decision.department,
            chief_name=chief_name,
            metadata={
                "routing_decision": {
                    "rationale": decision.rationale,
                    "confidence": decision.confidence,
                    "fallback_departments": list(decision.fallback_departments),
                },
                "block_reason": reason,
                "block_telemetry": {
                    "spent_today": spent_today,
                    "daily_limit": daily_limit,
                    "alert_level": status.get("alert_level", ""),
                },
            },
        )
        await self._store.create(session)
        session = session.transition(ChiefSessionState.SHUTDOWN)
        await self._store.update(session)

        self._publish(
            "chief_dispatcher.rejected",
            {
                "work_order_id": _wo_id(work_order),
                "session_id": session_id,
                "department": decision.department,
                "reason": reason,
                "spent_today": spent_today,
                "daily_limit": daily_limit,
            },
            correlation_id=_wo_id(work_order),
        )
        logger.warning(
            "chief_dispatcher.daily_budget_exhausted wo=%s session=%s "
            "spent=%.4f limit=%.4f",
            _wo_id(work_order),
            session_id,
            spent_today,
            daily_limit,
        )
        # Fire an URGENT operator-visible surface. Mirrors the
        # ``_nudge_low_confidence`` duck-typing so any escalation engine
        # that exposes ``notify`` or ``trigger_alert`` works.
        self._surface_budget_block(
            session_id=session_id,
            work_order=work_order,
            decision=decision,
            spent_today=spent_today,
            daily_limit=daily_limit,
        )
        return session

    def _surface_budget_block(
        self,
        *,
        session_id: str,
        work_order: Any,
        decision: RoutingDecision,
        spent_today: float,
        daily_limit: float,
    ) -> None:
        """Fire an URGENT escalation when a dispatch is daily-budget-blocked.

        P3.4 (#1586). Duck-typed against the escalation engine — same
        contract as ``_nudge_low_confidence``: prefers ``notify``, falls
        back to ``trigger_alert``, swallows every failure. Operator-side
        observability of the block is layered (event + log + escalation)
        because a budget block is consequential — work isn't running.
        """
        if self._escalation is None:
            return
        try:
            from bridge.escalation import EscalationLevel
            level: Any = EscalationLevel.URGENT
        except Exception:  # noqa: BLE001
            level = "URGENT"  # string fallback for fake engines in tests

        message = (
            f"Daily budget exhausted: WorkOrder {_wo_id(work_order)} "
            f"(department={decision.department}) blocked. "
            f"Spent ${spent_today:.4f} / limit ${daily_limit:.4f}."
        )
        source = f"chief_dispatcher:{decision.department}:budget"

        notify = getattr(self._escalation, "notify", None)
        trigger = getattr(self._escalation, "trigger_alert", None)
        try:
            if callable(notify):
                notify(level=level, source=source, message=message)
            elif callable(trigger):
                trigger(level=level, source=source, message=message)
            else:
                logger.debug(
                    "chief_dispatcher.budget_escalation_no_method "
                    "session=%s — skipped",
                    session_id,
                )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "chief_dispatcher.budget_escalation_failed session=%s error=%s",
                session_id,
                exc,
            )

    def _resolve_config(self, department: str) -> Any:
        """Look up a DepartmentConfig, swallowing the registry's "missing" raise.

        ``DepartmentRegistry.get_config`` raises ``KeyError`` on missing
        names; the work_order_router test fakes return ``None``. We treat
        both as "department not registered" and let the caller convert
        that into a ``RoutingError`` + rejected event. Any other
        exception propagates — a registry that's failing for a reason
        other than "name not found" is a real bug we want loud.
        """
        try:
            return self._registry.get_config(department)
        except KeyError:
            return None

    def _get_breaker(self, department: str) -> CircuitBreaker:
        """Return the circuit breaker for ``department``, creating on first use.

        Z4-S64 (#1408). One breaker per department slug. Configured with
        ``failure_threshold`` and ``recovery_timeout`` from the dispatcher's
        constructor; the rest of ``CircuitBreakerConfig`` keeps its defaults
        (success_threshold=1 — one good run from HALF_OPEN closes the
        circuit; window_seconds=120 — failure window).
        """
        breaker = self._circuit_breakers.get(department)
        if breaker is None:
            breaker = CircuitBreaker(
                failure_threshold=self._circuit_failure_threshold,
                recovery_timeout=self._circuit_recovery_timeout_seconds,
            )
            self._circuit_breakers[department] = breaker
        return breaker

    def _pick_fallback_department(
        self, decision: RoutingDecision,
    ) -> Optional[str]:
        """Return the first fallback whose breaker is not OPEN, or None.

        Z4-S64 (#1408). Iterates ``decision.fallback_departments`` in the
        order the router supplied. We accept CLOSED and HALF_OPEN as
        "runnable" — HALF_OPEN sends one probe call and the breaker's own
        guard handles a concurrent probe.
        """
        for candidate in decision.fallback_departments:
            cand_breaker = self._get_breaker(candidate)
            if cand_breaker.state != CircuitState.OPEN:
                return candidate
        return None

    def _record_breaker_outcome(
        self,
        department: str,
        breaker: CircuitBreaker,
        final: ChiefSession,
    ) -> None:
        """Record success/failure on ``breaker`` and emit transition events.

        Z4-S64 (#1408). Best-effort: any exception is logged and swallowed
        — the dispatcher must return the persisted session row regardless
        of what the breaker does. Transition events
        (``chief_dispatcher.circuit_open`` /
        ``chief_dispatcher.circuit_closed``) fire only when the state
        actually changed.
        """
        try:
            previous_state = breaker.state
            if final.state == ChiefSessionState.AWAITING_EVALUATION:
                breaker.record_success()
            elif final.state == ChiefSessionState.FAILED:
                breaker.record_failure()
            else:
                # Other terminal states (TIMED_OUT, SHUTDOWN) — don't
                # influence the breaker. The reaper / shutdown paths own
                # those transitions and the breaker tracks chief-run
                # outcomes specifically.
                return
            new_state = breaker.state
            if previous_state != CircuitState.OPEN and new_state == CircuitState.OPEN:
                self._publish(
                    "chief_dispatcher.circuit_open",
                    {
                        "department": department,
                        "session_id": final.session_id,
                        "work_order_id": final.work_order_id,
                        "failure_count": breaker.failure_count,
                    },
                    correlation_id=final.work_order_id,
                )
                logger.warning(
                    "chief_dispatcher.circuit_open department=%s failures=%d",
                    department,
                    breaker.failure_count,
                )
            elif previous_state != CircuitState.CLOSED and new_state == CircuitState.CLOSED:
                self._publish(
                    "chief_dispatcher.circuit_closed",
                    {
                        "department": department,
                        "session_id": final.session_id,
                        "work_order_id": final.work_order_id,
                    },
                    correlation_id=final.work_order_id,
                )
                logger.info(
                    "chief_dispatcher.circuit_closed department=%s",
                    department,
                )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "chief_dispatcher.breaker_record_failed department=%s error=%s",
                department,
                exc,
            )

    def _deserialize_history_safe(
        self,
        blob: bytes | None,
        session_id: str,
    ) -> list[Any] | None:
        """Deserialize a message_history blob, returning None on any failure.

        zone4-warmth.C.03 (#2297). Fault-tolerant wrapper around
        ``ModelMessagesTypeAdapter.validate_json``. Returns:
        - ``None`` for absent/empty input (the cold-start case).
        - The deserialized list on success.
        - ``None`` plus a WARNING log on schema-drift, corruption,
          adapter import failure, or any other exception. The chief
          still runs in that case — just without prior context, which
          is exactly the pre-C.03 (and pre-B.02) behavior.

        Never raises. The dispatcher's reuse branch relies on this
        method to be a clean fall-through so a bad blob never blocks a
        dispatch the chief could otherwise serve. The import is lazy
        inside the try block so a PydanticAI version that lacks the
        adapter degrades to fresh-start rather than crashing
        ``ChiefDispatcher`` at module-import time.
        """
        if blob is None or len(blob) == 0:
            return None
        try:
            from pydantic_ai.messages import ModelMessagesTypeAdapter
            result = ModelMessagesTypeAdapter.validate_json(blob)
            # ``validate_json`` returns a list-like — coerce to list for
            # downstream code that expects mutation-free indexing. None
            # check is defensive; the adapter never returns None in
            # practice, but a future schema change shouldn't crash us.
            if result is None:
                return None
            return list(result)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "chief_dispatcher.deserialize_history session=%s — "
                "corrupted or unreadable blob, falling back to "
                "fresh-start (no history): %s",
                session_id,
                exc,
            )
            return None

    def _extract_operator(self, work_order: Any) -> str:
        """Return the operator identity used to scope warmth-reuse.

        zone4-warmth.C.02 (#2296). Reads ``metadata["operator"]`` off the
        WorkOrder when present (sprint spec's Option 2); falls back to
        the string constant ``"default-operator"`` when the WorkOrder
        carries no ``metadata`` mapping or has no ``operator`` key.
        bumba-open-harness is single-operator today, so the fallback is the
        common case; the field-check is the seam multi-operator support
        will lean on without the dispatcher having to change.

        Operator equality is exact string match against
        ``ChiefSession.metadata["operator"]`` as persisted by the same
        helper at session-create time (see Step 3 of dispatch — the
        new-session path stamps the operator into metadata).
        """
        metadata = getattr(work_order, "metadata", None)
        if isinstance(metadata, dict):
            value = metadata.get("operator")
            if isinstance(value, str) and value:
                return value
        return "default-operator"

    def _warm_age_seconds(self, warm_session: ChiefSession) -> float:
        """Return the age of a warm session in seconds, from idle_since_utc to now.

        zone4-warmth.C.02 (#2296). The session was returned by
        ``find_warm_session`` with ``state == AWAITING_EVALUATION``, so
        ``idle_since_utc`` is guaranteed non-None per the state machine
        (``ChiefSession.transition`` sets it on the
        ``→ AWAITING_EVALUATION`` arc). Defensive ``0.0`` fallback is for
        the unlikely test-double case where the field has been zeroed
        out — the warmth_reused event is observability, not a gate, so
        a degraded age value never blocks reuse.
        """
        from datetime import datetime, timezone as _tz
        idle = warm_session.idle_since_utc
        if idle is None:
            return 0.0
        return (datetime.now(_tz.utc) - idle).total_seconds()

    def _publish(
        self,
        event_type: str,
        payload: dict,
        correlation_id: Optional[str] = None,
    ) -> None:
        """Publish to the EventBus, swallowing failures.

        ``EventBus.publish`` is synchronous and returns the published
        event; we don't propagate that here. Failures are logged at
        warning level so a broken bus doesn't take down dispatching.

        P3.3 (#1584): ``correlation_id`` is forwarded to
        ``EventBus.publish`` as the top-level Event.correlation_id field.
        Across the dispatch lifecycle this is the WorkOrder id, which
        threads through ``chief_dispatcher.routed`` →
        ``chief_session.created`` → ``chief_session.state_changed`` so an
        operator subscribing to ``/ws/events`` can reconstruct the full
        chain from a single WO id.
        """
        if self._event_bus is None:
            logger.debug(
                "chief_dispatcher.event_dropped type=%s (no event_bus wired)",
                event_type,
            )
            return
        try:
            # Best-effort kwargs; older EventBus shims (tests) might not
            # accept correlation_id. Fall back to the positional form when
            # the kwarg is rejected.
            try:
                self._event_bus.publish(
                    event_type, payload, correlation_id=correlation_id,
                )
            except TypeError:
                self._event_bus.publish(event_type, payload)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "chief_dispatcher.event_publish_failed type=%s error=%s",
                event_type,
                exc,
            )

    def _nudge_low_confidence(
        self,
        work_order: Any,
        decision: RoutingDecision,
        session_id: str,
    ) -> None:
        """Trigger a NUDGE alert when routing confidence is below threshold.

        Duck-typed against the escalation engine: we call ``notify`` if
        present, falling back to ``trigger_alert`` if not. Both forms
        accept ``level=`` + ``source=`` + ``message=`` kwargs so the
        engine implementation can pick one. If neither method exists,
        log and skip — observability without the operator-visible nudge
        is still better than an exception.
        """
        if self._escalation is None:
            return

        # Lazy-import to avoid pulling escalation.py into modules that
        # only consume the dispatcher contract.
        try:
            from bridge.escalation import EscalationLevel
            level: Any = EscalationLevel.NUDGE
        except Exception:  # noqa: BLE001
            level = "NUDGE"  # string fallback for fake engines in tests

        message = (
            f"Low-confidence routing for WorkOrder {_wo_id(work_order)}: "
            f"{decision.rationale} (confidence={decision.confidence:.2f})"
        )
        source = f"chief_dispatcher:{decision.department}"

        notify = getattr(self._escalation, "notify", None)
        trigger = getattr(self._escalation, "trigger_alert", None)
        try:
            if callable(notify):
                notify(level=level, source=source, message=message)
            elif callable(trigger):
                trigger(level=level, source=source, message=message)
            else:
                logger.debug(
                    "chief_dispatcher.escalation_no_method session=%s — skipped",
                    session_id,
                )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "chief_dispatcher.escalation_failed session=%s error=%s",
                session_id,
                exc,
            )

    # ------------------------------------------------------------------
    # Sprint 5.00c (#2155) — workflow-first dispatch helpers
    # ------------------------------------------------------------------

    def _extract_directive_text(self, work_order: Any) -> str:
        """Concatenate intent + input.text into the directive text used
        for workflow matching. Mirrors WorkOrderRouter._extract_description.
        """
        parts: list[str] = []
        intent = getattr(work_order, "intent", "") or ""
        if intent:
            parts.append(intent)
        input_obj = getattr(work_order, "input", None)
        if input_obj is not None:
            text = getattr(input_obj, "text", "") or ""
            if text:
                parts.append(text)
        return " ".join(parts)

    async def _workflow_first_dispatch(
        self,
        *,
        work_order: Any,
        match: dict[str, Any],
        correlation_id: str,
    ) -> ChiefSession | None:
        """Fire a matched workflow + return a synthesized SHUTDOWN ChiefSession.

        Returns the session row on success; returns None to fall through to
        the regular routing path on any failure (defensive — workflow
        short-circuit should never block a dispatch that would have worked
        via the chief).

        Persists a ChiefSession row with metadata pointing at the workflow
        run so the caller contract (dispatch → ChiefSession) is preserved
        and observers can pivot from the WO id to the workflow_run_id via
        the standard /api/chief_sessions surface.
        """
        workflow_name = match["name"]
        try:
            run_id = self._workflow_registry.trigger(
                name=workflow_name,
                inputs={"work_order_id": _wo_id(work_order), "directive": self._extract_directive_text(work_order)},
                engine=self._workflow_engine,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "chief_dispatcher.workflow_first_dispatch_failed wo=%s workflow=%s error=%s — falling through to chief",
                _wo_id(work_order),
                workflow_name,
                exc,
            )
            return None

        # Synthesize a SHUTDOWN session row so callers see a consistent contract.
        # Use the work_order's department_target if set, else "workflow".
        import uuid
        from datetime import datetime, timezone
        session_id = f"cs-{uuid.uuid4().hex[:12]}"
        now = datetime.now(timezone.utc)
        department = getattr(work_order, "department_target", None) or "workflow"

        # Build the session with workflow-run metadata. ChiefSession dataclass
        # accepts only its declared fields per agent/bridge/chief_session.py:182.
        try:
            session = ChiefSession(
                session_id=session_id,
                work_order_id=_wo_id(work_order),
                department=department,
                chief_name=f"workflow:{workflow_name}",
                state=ChiefSessionState.SHUTDOWN,
                created_at_utc=now,
                completed_at_utc=now,
                run_count=1,
                cost_usd=0.0,
                metadata={
                    "workflow_run_id": run_id,
                    "workflow_name": workflow_name,
                    "workflow_match_confidence": match.get("confidence"),
                    "workflow_matched_token": match.get("matched_token"),
                    "dispatch_path": "workflow_first",
                },
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "chief_dispatcher.workflow_first_session_construct_failed wo=%s error=%s — falling through",
                _wo_id(work_order),
                exc,
            )
            return None

        # Best-effort persist. If the store rejects, log and continue
        # returning the in-memory session — the caller's contract is the
        # returned object, not the persisted row.
        try:
            await self._store.create(session)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "chief_dispatcher.workflow_first_persist_failed wo=%s session=%s error=%s",
                _wo_id(work_order),
                session_id,
                exc,
            )

        self._publish(
            "chief_dispatcher.workflow_first_dispatched",
            {
                "work_order_id": _wo_id(work_order),
                "workflow_name": workflow_name,
                "workflow_run_id": run_id,
                "confidence": match.get("confidence"),
                "session_id": session_id,
            },
            correlation_id=correlation_id,
        )
        logger.info(
            "chief_dispatcher.workflow_first_dispatched wo=%s workflow=%s run=%s confidence=%.2f",
            _wo_id(work_order),
            workflow_name,
            run_id,
            match.get("confidence", 0.0),
        )
        return session


# ---------------------------------------------------------------------------
# Module-level helpers (kept private; the dispatcher is the only consumer)
# ---------------------------------------------------------------------------


def _wo_id(work_order: Any) -> str:
    """Return the WorkOrder's id, defensively.

    Production WorkOrders use ``id`` (per ``bridge.work_order``). Some
    test doubles ape the older spec's ``work_order_id`` shape. Accept
    either to keep the dispatcher robust to test-time variation.
    """
    return (
        getattr(work_order, "id", None)
        or getattr(work_order, "work_order_id", None)
        or ""
    )


def _task_from_work_order(work_order: Any) -> str:
    """Build the task string the chief receives.

    Per the spec: the task is ``intent`` if present, else ``input.text``.
    A WorkOrder with neither produces an empty string, which is then the
    chief's problem to handle (it'll typically refuse with "no task
    given"). Logging that as a warning here would just duplicate the
    chief's own output.
    """
    intent = getattr(work_order, "intent", "") or ""
    if intent:
        return intent
    input_obj = getattr(work_order, "input", None)
    if input_obj is not None:
        text = getattr(input_obj, "text", "") or ""
        if text:
            return text
    return ""
