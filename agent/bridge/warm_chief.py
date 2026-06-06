"""WarmChief async context manager — Z4-S11 (#1382).

Wraps the existing single-run chief invocation (``teams/_factory.py::
build_manager_agent`` + ``teams/_team.py::DepartmentTeam.run``) inside a
durable :class:`bridge.chief_session.ChiefSession` lifecycle.

The chief lifecycle itself remains WARM single-run — ``DepartmentTeam.run``
builds the chief, runs one ``manager.run(task, deps=deps)`` deliberation
(during which the chief may call ``delegate()`` 0..N times), and tears the
team down when the run returns. ``WarmChief`` does not change that. What it
adds is the *envelope*: a persisted ``ChiefSession`` row that tracks the
single chief run from the outside, transitioning through ``EXECUTING`` →
``AWAITING_EVALUATION`` (or ``FAILED``) and persisting cost so the next
reader's first lookup sees the run's full cost attribution.

Intended usage::

    session = ChiefSession(
        session_id=new_chief_session_id(),
        work_order_id=wo.id,
        department=config.name,
        chief_name=config.manager.name,
        state=ChiefSessionState.WARM,
    )
    await store.create(session)

    async with WarmChief(session, store, config, deps, task) as chief:
        pass  # the chief runs inside __aenter__
    result = chief.result  # TeamResult

State transitions (always via :meth:`ChiefSession.transition` — never
direct mutation, since the dataclass enforces a state machine and we
depend on its invalid-transition raises):

- on ``__aenter__``: incoming state (``WARM`` per the contract; the
  protocol allows transition only from ``WARM`` → ``EXECUTING``) →
  ``EXECUTING``, persisted via ``store.update``.
- on the chief run raising inside ``__aenter__``: ``EXECUTING`` →
  ``FAILED`` with the exception's str captured as ``error``, persisted,
  re-raise so the caller sees the original exception.
- on the chief run returning inside ``__aenter__``: stay in
  ``EXECUTING`` until ``__aexit__``, where success → ``AWAITING_EVALUATION``.
  Cost is added BEFORE the ``AWAITING_EVALUATION`` update so the persisted
  row reflects the run's full cost on the next reader's first lookup.
- on ``__aexit__`` with an exception (e.g. raised by the body of the
  ``async with`` *after* the chief run completed): leave the session
  state alone — ``__aenter__`` already drove transitions for the chief
  run itself; only the body's failure is observed here, and that is the
  caller's concern, not the chief lifecycle's.

Cost attribution:

- Read via ``result.total_cost_usd`` on the returned ``TeamResult``.
  Today (2026-05-09) ``DepartmentTeam.run`` does not populate that
  field (it threads cost via ``deps.cost_tracker.record()`` for the
  daily/weekly aggregator). The ``TeamResult`` default is ``0.0`` so
  the no-cost branch is the steady state today. When a future sprint
  populates ``total_cost_usd`` (e.g. from ``result.usage()`` × model
  pricing), this code starts attributing without modification.
- ``ChiefSession.add_cost(delta)`` returns a new ``ChiefSession`` with
  ``cost_usd`` incremented (immutable update — never mutates).

Cost-cap enforcement (Z4-S41 / #1399):

- An optional ``cost_tracker`` constructor argument enables pre/post-flight
  cap enforcement against ``config.constraints.cost_limit_usd``. When
  ``cost_tracker`` is None (default), enforcement is a no-op — preserves
  back-compat for the original Z4-S11 contract.
- Pre-flight (``__aenter__``): reads ``cost_tracker.get_session_cost(
  session_id)`` BEFORE invoking ``_run_chief``. If the prior spend
  already exceeds the cap (e.g. requeue path), raises
  ``CostCapExceededError`` which the existing exception handler routes
  to EXECUTING → FAILED. The chief never runs.
- Post-flight (``__aexit__`` success path): reads
  ``get_session_cost(session_id)`` AFTER the run returns. If the run
  pushed live spend over the cap, transitions EXECUTING → FAILED
  instead of AWAITING_EVALUATION. The ``TeamResult`` is still
  available via ``self.result`` so observers can inspect what was
  generated before the kill.
- Async polling DURING the run is intentionally out of scope here. It
  would require modifying ``DepartmentTeam.run`` to be cancellable
  mid-flight, which is a larger sprint. The pre/post-flight pattern is
  what Z4-S41 calls for.

Companion contracts (treated as shipped — read, don't modify):
- ``bridge/chief_session.py`` — Z4-S01 (#1385): ``ChiefSession`` +
  ``ChiefSessionState`` + state machine + ``transition()`` + ``add_cost()``.
- ``bridge/chief_session_store.py`` — Z4-S03 (#1387): ``ChiefSessionStore``
  Protocol + ``InMemoryChiefSessionStore``. Z4-S10 (#1381) adds the
  SQLite-backed impl in a parallel worktree; this module works against
  any conformant store.
- ``bridge/cost_tracker.py`` — Z4-S40 (#1398): ``CostTracker.get_session_cost``
  reads the live ledger by chief_session_id.
"""
from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any, Optional

from bridge.chief_session import ChiefSession, ChiefSessionState
from bridge.chief_session_store import ChiefSessionStore
from pydantic_ai.messages import ModelMessagesTypeAdapter
from teams._post_run import decide_post_run_hygiene
from teams._team import DepartmentTeam
from teams._types import BridgeDeps, DepartmentConfig, TeamResult

if TYPE_CHECKING:
    from bridge.cost_tracker import CostTracker
    from bridge.halt import HaltPolicy

# audit-2026-05-16.C.02 — surface label for HaltPolicy decisions originating
# inside the WarmChief lifecycle. Kept as a module constant so operator-log
# greps and any future call-site consistency check find it in one place.
HALT_SURFACE: str = "warm-chief"

# zone4-warmth.B.02 (#2294) — upper bound on a persisted message-history
# blob. A typical 20k-token conversation serializes to ~80-150 KB; anything
# over 1 MB suggests runaway accumulation or schema bloat and shouldn't be
# cached. Refused blobs log a WARNING and leave the column NULL; the next
# dispatch starts fresh, which is exactly the pre-B.02 behavior.
_MAX_MESSAGE_HISTORY_BYTES: int = 1_048_576

# Warm-chief history is useful while it stays small, but once it grows beyond
# this checkpoint threshold the next warm reuse risks feeding an expensive
# transcript back into the model. At that point we write a compact, searchable
# checkpoint to shared memory and clear the serialized message_history blob so
# the next run starts with a fresh system prompt instead of replaying the
# whole prior transcript.
_CHECKPOINT_HISTORY_BYTES: int = 262_144
_CHECKPOINT_OUTPUT_CHARS: int = 2_000
_CHECKPOINT_EMPLOYEE_CHARS: int = 600
_CHECKPOINT_MAX_EMPLOYEES: int = 12

logger = logging.getLogger(__name__)


class HaltBlockedError(Exception):
    """Raised when the shared HaltPolicy blocks a WarmChief from starting.

    audit-2026-05-16.C.02 (#2057). Carries the surface label and the
    operator-readable reason from the ``HaltDecision``. The string form is
    suitable for the ``error`` field on
    ``ChiefSession.transition(FAILED)`` — ``__aenter__`` catches this in
    the same handler that drives ``EXECUTING → FAILED`` for any other
    pre-flight failure, so the persisted row reflects the halt.

    Fires from ``__aenter__`` after the WARM → EXECUTING transition (so
    the FAILED transition is valid) but BEFORE any cost-cap check or
    ``_run_chief`` invocation. No chief subprocess work is started under
    a global halt.
    """

    def __init__(self, surface: str, reason: str) -> None:
        self.surface = surface
        self.reason = reason
        super().__init__(
            f"HaltPolicy blocked surface={surface}: {reason}"
        )


class CostCapExceededError(Exception):
    """Raised when a chief session's cost exceeds its configured cap.

    Carries the offending ``session_id``, the live ``attempted_cost`` that
    tripped the check, and the ``cap`` it breached. The string form is
    suitable for the ``error`` field on ``ChiefSession.transition(FAILED)``.

    Two firing points (Z4-S41 / #1399):
    - **Pre-flight** (``__aenter__``): raised before ``_run_chief`` is
      called when the session's prior recorded spend already exceeds the
      cap. Short-circuits the run so we don't burn budget we already
      know we can't afford.
    - **Post-flight** (``__aexit__``): raised after ``_run_chief`` returns
      cleanly when the run pushed total spend over the cap. Overrides
      the AWAITING_EVALUATION success-path transition with a FAILED
      transition. The ``TeamResult`` is still set on ``self._result`` so
      observers can inspect what was generated before the kill.
    """

    def __init__(
        self,
        session_id: str,
        attempted_cost: float,
        cap: float,
    ) -> None:
        self.session_id = session_id
        self.attempted_cost = attempted_cost
        self.cap = cap
        super().__init__(
            f"Session {session_id} cost ${attempted_cost:.4f} exceeds "
            f"cap ${cap:.4f}"
        )


class WarmChief:
    """Async context manager wrapping one chief run inside a durable session.

    Construction stores references; the actual chief invocation happens
    in ``__aenter__``. The body of the ``async with`` runs *after* the
    chief returned but *before* the ``AWAITING_EVALUATION`` transition,
    so callers may inspect ``self.result`` and act on it (e.g. evaluate,
    requeue) before the session is marked idle.

    The class is single-shot: a given instance drives exactly one
    transition cycle. To run the chief again on the same ``WorkOrder``,
    construct a new ``WarmChief`` against a new ``ChiefSession`` row
    (the requeue path is ``AWAITING_EVALUATION`` → ``WARM`` →
    ``EXECUTING`` per the state diagram on ``ChiefSessionState``).
    """

    def __init__(
        self,
        session: ChiefSession,
        store: ChiefSessionStore,
        config: DepartmentConfig,
        deps: BridgeDeps,
        task: str,
        cost_tracker: Optional["CostTracker"] = None,
        *,
        event_bus: Optional[object] = None,
        correlation_id: Optional[str] = None,
        halt_policy: Optional["HaltPolicy"] = None,
        skill_allocator: Optional[Any] = None,
        message_history: Optional[list[Any]] = None,
    ) -> None:
        self._session = session
        self._store = store
        self._config = config
        self._deps = deps
        self._task = task
        self._result: Optional[TeamResult] = None
        # zone4-warmth.C.03 (#2297) — optional pre-loaded message_history,
        # threaded down to ``manager.run(message_history=...)`` inside
        # ``_run_chief``. When None (the default), the chief bootstraps a
        # fresh system prompt as before — no behavior change vs B.02.
        # When non-None, PydanticAI's ``Agent.run`` skips system-prompt
        # regeneration (the prior history already includes one) and the
        # chief reasons forward from its previous state. This is the
        # token-saving wire on a warm-reuse dispatch.
        self._message_history: Optional[list[Any]] = message_history
        # zone4-warmth.B.02 (#2294) — the PydanticAI RunResult captured from
        # the most recent ``manager.run`` inside ``_run_chief``. Distinct from
        # ``self._result`` (which is a ``TeamResult`` — the wrapped output the
        # caller consumes). Used by ``_try_persist_message_history`` to call
        # ``.all_messages()`` for the serialized blob. None when no run has
        # completed yet OR the team layer didn't surface the RunResult — both
        # cases are no-ops at persistence time.
        self._run_result: Optional[Any] = None
        # Z4-S41 (#1399): optional cost-cap enforcement. When ``cost_tracker``
        # is None (the default — preserves Z4-S11 back-compat for tests
        # that don't supply one), the pre/post-flight checks are no-ops.
        # When wired, ``__aenter__`` reads ``cost_tracker.get_session_cost(
        # session_id)`` BEFORE calling ``_run_chief`` and raises
        # ``CostCapExceededError`` if already over cap. ``__aexit__`` reads
        # again AFTER the run and overrides the AWAITING_EVALUATION success
        # transition with FAILED if the run pushed total over cap.
        self._cost_tracker: Optional["CostTracker"] = cost_tracker
        self._cost_cap_usd: float = float(config.constraints.cost_limit_usd)
        # P3.3 (#1584) — optional observability surface. When wired (by
        # ChiefDispatcher.dispatch with the bridge's EventBus), each
        # state transition publishes ``chief_session.state_changed`` with
        # the WO id as ``correlation_id``. When None (the default — back-
        # compat for tests that construct WarmChief without a bus), the
        # publish is a no-op.
        self._event_bus: Optional[object] = event_bus
        self._correlation_id: Optional[str] = correlation_id
        # audit-2026-05-16.C.02 (#2057). Optional shared HaltPolicy. When
        # wired, ``__aenter__`` consults ``check_start(HALT_SURFACE)``
        # AFTER the WARM → EXECUTING transition (so the FAILED transition
        # is valid) but BEFORE the cost-cap check and ``_run_chief``. A
        # blocked decision raises ``HaltBlockedError``, which flows into
        # the existing exception handler and drives EXECUTING → FAILED.
        # No chief subprocess work runs under a global halt. None (the
        # default) preserves back-compat for callers that haven't migrated.
        self._halt_policy: Optional["HaltPolicy"] = halt_policy
        # Sprint #1112/4.03 (#2150) — SkillAllocator handed down by
        # ChiefDispatcher. Threaded into DepartmentTeam at run time so the
        # chief + employees are filtered by manifest at construction. None
        # (the default) preserves back-compat for existing tests that
        # construct WarmChief without an allocator — DepartmentTeam treats
        # None as "no allocator wired, skip filter."
        self._skill_allocator: Optional[Any] = skill_allocator

    @property
    def session(self) -> ChiefSession:
        """Return the current ChiefSession (post-transition during the lifecycle)."""
        return self._session

    @property
    def result(self) -> TeamResult:
        """Return the TeamResult produced by the chief run.

        Raises ``RuntimeError`` if accessed before the run completes.
        """
        if self._result is None:
            raise RuntimeError(
                "WarmChief.result accessed before the chief run completed. "
                "Use it inside or after the `async with` body."
            )
        return self._result

    async def __aenter__(self) -> "WarmChief":
        # Transition WARM → EXECUTING and persist before invoking the
        # chief. If the store update itself raises (e.g. the row was
        # never create()d), surface that early — we have not yet started
        # the chief run, so there is no cleanup transition required.
        previous_state = self._session.state
        self._session = self._session.transition(ChiefSessionState.EXECUTING)
        await self._store.update(self._session)
        # P3.3 (#1584) — observability publish for WARM → EXECUTING.
        self._publish_state_changed(previous_state, self._session.state)

        try:
            # audit-2026-05-16.C.02 (#2057) HaltPolicy pre-flight check.
            # When wired, a blocked decision short-circuits the run before
            # any subprocess/team work. ``HaltBlockedError`` flows into
            # the same handler that drives EXECUTING → FAILED below.
            self._enforce_halt_policy_preflight()
            # Z4-S41 (#1399) pre-flight cost-cap check: if a prior run
            # (requeue path) already pushed this session over its cap,
            # short-circuit before burning budget on another _run_chief.
            # CostCapExceededError flows into the same handler that drives
            # EXECUTING → FAILED below.
            self._enforce_cost_cap_preflight()
            self._result = await self._run_chief()
        except Exception as exc:  # noqa: BLE001
            # The chief raised. Transition to FAILED and persist so the
            # next reader sees the failure cause, then re-raise so the
            # caller sees the original exception.
            logger.warning(
                "warm_chief.run_failed session=%s department=%s chief=%s error=%s",
                self._session.session_id,
                self._session.department,
                self._session.chief_name,
                exc,
            )
            previous_state = self._session.state
            self._session = self._session.transition(
                ChiefSessionState.FAILED,
                error=f"{type(exc).__name__}: {exc}",
            )
            await self._store.update(self._session)
            # P3.3 (#1584) — observability publish for EXECUTING → FAILED.
            self._publish_state_changed(previous_state, self._session.state)
            raise

        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> bool:
        # The chief itself ran inside __aenter__. If we got here without
        # an exception, the chief returned cleanly; transition to
        # AWAITING_EVALUATION. If the body of the `async with` raised
        # AFTER a clean chief run, that's the caller's concern — the
        # chief lifecycle already completed, so we still mark
        # AWAITING_EVALUATION (the chief did its job; whatever the
        # caller does next is a separate transition).
        if self._result is not None:
            # Add cost BEFORE the AWAITING_EVALUATION update so the
            # persisted row reflects the run's full cost on the next
            # reader's first lookup. ``transition`` and ``add_cost``
            # both return new instances per the immutable-update
            # convention; assignment threads the new state forward.
            cost_delta = float(self._result.total_cost_usd or 0.0)
            if cost_delta:
                self._session = self._session.add_cost(cost_delta)

            # Z4-S41 (#1399) post-flight cost-cap check. If the run
            # pushed live spend over the cap, override the
            # AWAITING_EVALUATION success transition with FAILED. The
            # ``_result`` attribute stays populated so observers (and
            # ``self.result``) can still see what the chief produced
            # before the kill.
            cap_breach = self._compute_cost_cap_breach()
            if cap_breach is not None:
                live_cost, cap = cap_breach
                logger.warning(
                    "warm_chief.cost_cap_exceeded_postflight session=%s "
                    "department=%s chief=%s live_cost=%.4f cap=%.4f",
                    self._session.session_id,
                    self._session.department,
                    self._session.chief_name,
                    live_cost,
                    cap,
                )
                previous_state = self._session.state
                self._session = self._session.transition(
                    ChiefSessionState.FAILED,
                    error=(
                        f"CostCapExceededError: Session "
                        f"{self._session.session_id} cost "
                        f"${live_cost:.4f} exceeds cap ${cap:.4f}"
                    ),
                )
                await self._store.update(self._session)
                # P3.3 (#1584) — observability publish for EXECUTING → FAILED.
                self._publish_state_changed(previous_state, self._session.state)
                return False

            previous_state = self._session.state
            self._session = self._session.transition(
                ChiefSessionState.AWAITING_EVALUATION,
            )
            await self._store.update(self._session)
            # P3.3 (#1584) — observability publish for
            # EXECUTING → AWAITING_EVALUATION.
            self._publish_state_changed(previous_state, self._session.state)

            # zone4-warmth.B.02 (#2294) — serialize message_history on
            # the success path only. Skipped when the body of the
            # `async with` raised (exc_type is not None); a failed body
            # invalidates the chief run from the caller's perspective
            # and we should not cache a partial transcript that may
            # never be consumed. Non-fatal: any serialization or store
            # failure logs a WARNING and leaves the blob NULL, which
            # is exactly the pre-B.02 behavior (fresh start next dispatch).
            if exc_type is None:
                await self._try_persist_message_history(
                    self._session.session_id
                )

        # Never suppress an exception raised inside the `async with`
        # body — return False (or implicitly None, which Python treats
        # the same).
        return False

    async def _try_persist_message_history(self, session_id: str) -> None:
        """Serialize the RunResult's message history and persist to the row.

        zone4-warmth.B.02 (#2294). Non-fatal — every failure mode logs a
        WARNING and returns cleanly. The blob column is nullable, so a
        missing blob means "fresh start on next dispatch", which is the
        pre-B.02 behavior.

        Reads from ``self._run_result`` — the PydanticAI RunResult captured
        in ``_run_chief`` from ``DepartmentTeam._last_run_result``. Distinct
        from ``self._result`` (which is the ``TeamResult`` wrapper and does
        not expose ``.all_messages()``).

        Failure modes handled:
        - ``self._run_result`` is None — chief never produced a RunResult
          (e.g., the team layer didn't surface it, or test fixture).
        - ``self._run_result.all_messages()`` raises — defensive against
          adapter-side bugs we haven't seen yet.
        - ``ModelMessagesTypeAdapter.dump_json`` raises — schema-drift or
          unserializable payload.
        - Serialized blob exceeds ``_MAX_MESSAGE_HISTORY_BYTES`` —
          guardrail against runaway accumulation.
        - ``store.update_message_history`` raises — DB write failure
          (locked, disk full, etc.).
        """
        if self._run_result is None:
            checkpoint_written = await self._try_write_memory_checkpoint(
                session_id,
                history_blob_bytes=0,
                reason="missing_run_result",
            )
            await self._try_clear_message_history_by_policy(
                session_id,
                history_blob_bytes=0,
                checkpoint_written=checkpoint_written,
            )
            return

        try:
            messages_callable = getattr(
                self._run_result, "all_messages", None
            )
            if not callable(messages_callable):
                checkpoint_written = await self._try_write_memory_checkpoint(
                    session_id,
                    history_blob_bytes=0,
                    reason="missing_all_messages",
                )
                await self._try_clear_message_history_by_policy(
                    session_id,
                    history_blob_bytes=0,
                    checkpoint_written=checkpoint_written,
                )
                return
            messages = messages_callable()
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "warm_chief.persist_history.all_messages_failed "
                "session=%s error=%s",
                session_id,
                exc,
            )
            checkpoint_written = await self._try_write_memory_checkpoint(
                session_id,
                history_blob_bytes=0,
                reason="all_messages_failed",
            )
            await self._try_clear_message_history_by_policy(
                session_id,
                history_blob_bytes=0,
                checkpoint_written=checkpoint_written,
            )
            return

        try:
            blob = ModelMessagesTypeAdapter.dump_json(messages)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "warm_chief.persist_history.serialization_failed "
                "session=%s error=%s",
                session_id,
                exc,
            )
            checkpoint_written = await self._try_write_memory_checkpoint(
                session_id,
                history_blob_bytes=0,
                reason="serialization_failed",
            )
            await self._try_clear_message_history_by_policy(
                session_id,
                history_blob_bytes=0,
                checkpoint_written=checkpoint_written,
            )
            return

        if len(blob) > _MAX_MESSAGE_HISTORY_BYTES:
            logger.warning(
                "warm_chief.persist_history.blob_too_large "
                "session=%s bytes=%d cap=%d",
                session_id,
                len(blob),
                _MAX_MESSAGE_HISTORY_BYTES,
            )
            checkpoint_written = await self._try_write_memory_checkpoint(
                session_id,
                history_blob_bytes=len(blob),
                reason="blob_too_large",
            )
            await self._try_clear_message_history(
                session_id,
                reason="blob_too_large",
                history_blob_bytes=len(blob),
                checkpoint_written=checkpoint_written,
            )
            return

        checkpoint_written = await self._try_write_memory_checkpoint(
            session_id,
            history_blob_bytes=len(blob),
            reason="post_run",
        )

        if await self._try_clear_message_history_by_policy(
            session_id,
            history_blob_bytes=len(blob),
            checkpoint_written=checkpoint_written,
        ):
            return

        if len(blob) > _CHECKPOINT_HISTORY_BYTES:
            await self._try_clear_message_history(
                session_id,
                reason="checkpoint_threshold",
                history_blob_bytes=len(blob),
                checkpoint_written=checkpoint_written,
            )
            return

        try:
            await self._store.update_message_history(session_id, blob)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "warm_chief.persist_history.store_update_failed "
                "session=%s error=%s",
                session_id,
                exc,
            )

    async def _try_clear_message_history_by_policy(
        self,
        session_id: str,
        *,
        history_blob_bytes: int,
        checkpoint_written: bool,
    ) -> bool:
        """Clear warm history when post-run policy says reuse is risky."""
        if self._result is None:
            return False

        decision = decide_post_run_hygiene(self._result, self._result.telemetry)
        if not decision.clear_message_history:
            return False

        await self._try_clear_message_history(
            session_id,
            reason="post_run_policy",
            history_blob_bytes=history_blob_bytes,
            input_tokens=decision.input_tokens,
            manifest_path=decision.manifest_path,
            checkpoint_written=checkpoint_written,
        )
        return checkpoint_written

    async def _try_write_memory_checkpoint(
        self,
        session_id: str,
        *,
        history_blob_bytes: int,
        reason: str,
    ) -> bool:
        """Write a compact post-run checkpoint to shared memory.

        This is the internal lifecycle hook for warm-chief memory cadence.
        It is deliberately bounded and best-effort: the checkpoint gives the
        operator and future tools a durable run summary, while failures never
        block message-history persistence or the chief session transition.
        """
        result = self._result
        if result is None:
            return False

        memory_store = getattr(self._deps, "memory_store", None)
        set_memory = getattr(memory_store, "set", None)
        if not callable(set_memory):
            return False

        key = f"z4:checkpoint:{self._session.department}:{session_id}"
        value = self._build_memory_checkpoint(
            session_id,
            history_blob_bytes=history_blob_bytes,
            reason=reason,
        )
        try:
            maybe_awaitable = set_memory(key, value)
            if hasattr(maybe_awaitable, "__await__"):
                await maybe_awaitable
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "warm_chief.memory_checkpoint_failed session=%s key=%s error=%s",
                session_id,
                key,
                exc,
            )
            return False

        self._publish_event(
            "chief_session.memory_checkpointed",
            {
                "session_id": session_id,
                "work_order_id": self._session.work_order_id,
                "department": self._session.department,
                "chief_name": self._session.chief_name,
                "key": key,
                "reason": reason,
                "history_blob_bytes": history_blob_bytes,
            },
        )
        return True

    async def _try_clear_message_history(
        self,
        session_id: str,
        *,
        reason: str,
        history_blob_bytes: int,
        input_tokens: int | None = None,
        manifest_path: str | None = None,
        checkpoint_written: bool = True,
    ) -> None:
        """Clear persisted warm history after checkpointing crosses a threshold."""
        if not checkpoint_written:
            logger.warning(
                "post_run.context_clear_skipped session=%s reason=%s "
                "checkpoint_written=false",
                session_id,
                reason,
            )
            return

        try:
            await self._store.update_message_history(session_id, None)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "warm_chief.persist_history.clear_failed "
                "session=%s reason=%s error=%s",
                session_id,
                reason,
                exc,
            )
            return

        logger.info(
            "post_run.context_cleared department=%s session_id=%s "
            "input_tokens=%d manifest_path=%s reason=%s",
            self._session.department,
            session_id,
            input_tokens or 0,
            manifest_path or "",
            reason,
        )

        compacted_payload: dict[str, Any] = {
            "session_id": session_id,
            "work_order_id": self._session.work_order_id,
            "department": self._session.department,
            "chief_name": self._session.chief_name,
            "reason": reason,
            "history_blob_bytes": history_blob_bytes,
            "checkpoint_threshold_bytes": _CHECKPOINT_HISTORY_BYTES,
            "max_history_bytes": _MAX_MESSAGE_HISTORY_BYTES,
        }
        if input_tokens is not None:
            compacted_payload["input_tokens"] = input_tokens
        if manifest_path is not None:
            compacted_payload["manifest_path"] = manifest_path

        self._publish_event(
            "chief_session.history_compacted",
            compacted_payload,
        )

    def _build_memory_checkpoint(
        self,
        session_id: str,
        *,
        history_blob_bytes: int,
        reason: str,
    ) -> str:
        """Return a bounded JSON summary of the completed chief run."""
        assert self._result is not None
        result = self._result
        employees = [
            {
                "employee_name": employee.employee_name,
                "success": employee.success,
                "error": employee.error,
                "output_excerpt": _truncate_text(
                    employee.output,
                    _CHECKPOINT_EMPLOYEE_CHARS,
                ),
            }
            for employee in result.employee_results[:_CHECKPOINT_MAX_EMPLOYEES]
        ]
        checkpoint = {
            "version": 1,
            "session_id": session_id,
            "work_order_id": self._session.work_order_id,
            "department": self._session.department,
            "chief_name": self._session.chief_name,
            "run_count": self._session.run_count,
            "success": result.success,
            "error": result.error,
            "total_tokens": result.total_tokens,
            "total_cost_usd": result.total_cost_usd,
            "duration_seconds": result.duration_seconds,
            "history_blob_bytes": history_blob_bytes,
            "checkpoint_reason": reason,
            "manifest_path": result.manifest_path,
            "memory_ref": result.memory_ref,
            "manager_output_excerpt": _truncate_text(
                result.manager_output,
                _CHECKPOINT_OUTPUT_CHARS,
            ),
            "employee_result_count": len(result.employee_results),
            "employee_results": employees,
        }
        return json.dumps(checkpoint, sort_keys=True, separators=(",", ":"))

    def _enforce_halt_policy_preflight(self) -> None:
        """Raise HaltBlockedError when the wired HaltPolicy blocks start.

        audit-2026-05-16.C.02 (#2057). No-op when no policy was supplied
        at construction time (back-compat for callers that haven't
        migrated to the shared contract). Called from ``__aenter__`` after
        the WARM → EXECUTING transition has been written, so the FAILED
        transition reached by the exception handler is valid.
        """
        if self._halt_policy is None:
            return
        decision = self._halt_policy.check_start(HALT_SURFACE)
        if decision.blocked:
            raise HaltBlockedError(
                HALT_SURFACE,
                decision.reason or "halt flag set",
            )

    def _enforce_cost_cap_preflight(self) -> None:
        """Raise CostCapExceededError if prior recorded spend already breaches cap.

        Z4-S41 (#1399). No-op when ``cost_tracker`` was not supplied
        (back-compat for tests and call sites that don't wire enforcement).
        Reads the live ledger via ``CostTracker.get_session_cost`` —
        already-shipped contract, never raises on missing files.
        """
        if self._cost_tracker is None:
            return
        prior_cost = float(
            self._cost_tracker.get_session_cost(self._session.session_id)
        )
        if prior_cost > self._cost_cap_usd:
            raise CostCapExceededError(
                self._session.session_id,
                prior_cost,
                self._cost_cap_usd,
            )

    def _compute_cost_cap_breach(self) -> Optional[tuple[float, float]]:
        """Return ``(live_cost, cap)`` if the post-flight check trips.

        Z4-S41 (#1399). Returns ``None`` when ``cost_tracker`` is unset
        or when live spend is at or under the cap. Called from
        ``__aexit__`` after the cost delta has already been added to the
        in-memory session row but before the AWAITING_EVALUATION update
        is persisted.
        """
        if self._cost_tracker is None:
            return None
        live_cost = float(
            self._cost_tracker.get_session_cost(self._session.session_id)
        )
        if live_cost > self._cost_cap_usd:
            return live_cost, self._cost_cap_usd
        return None

    def _publish_state_changed(
        self,
        previous_state: ChiefSessionState,
        new_state: ChiefSessionState,
    ) -> None:
        """Publish ``chief_session.state_changed`` to the wired EventBus.

        P3.3 (#1584). No-op when ``event_bus`` was not supplied at
        construction time (back-compat for tests that drive WarmChief
        without observability). The dispatcher path always wires this
        — see ``ChiefDispatcher.dispatch``. Failures are swallowed so
        broken observability never derails the chief lifecycle.

        ``correlation_id`` is forwarded as the top-level Event field so
        an operator subscribing to ``/ws/events?filter=chief_session.``
        can correlate the state transition back to the WorkOrder id.
        """
        payload = {
            "session_id": self._session.session_id,
            "work_order_id": self._session.work_order_id,
            "department": self._session.department,
            "from_state": previous_state.value,
            "to_state": new_state.value,
            "run_count": self._session.run_count,
        }
        self._publish_event("chief_session.state_changed", payload)

    def _publish_event(self, event_type: str, payload: dict[str, Any]) -> None:
        """Publish one EventBus event without letting observability break runs."""
        bus = self._event_bus
        if bus is None:
            return
        try:
            try:
                bus.publish(
                    event_type,
                    payload,
                    correlation_id=self._correlation_id,
                )
            except TypeError:
                bus.publish(event_type, payload)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "warm_chief.event_publish_failed type=%s session=%s error=%s",
                event_type,
                self._session.session_id,
                exc,
            )

    async def _run_chief(self) -> TeamResult:
        """Build the department team and drive a single chief run.

        Extracted so tests can patch the team-building path independently
        of the lifecycle transitions. Mirrors the production call site
        in ``teams/_team.py::DepartmentTeam.run`` exactly: ``run`` never
        raises in normal operation (it catches exceptions and returns a
        ``TeamResult`` with ``success=False``). The exception path on
        ``__aenter__`` covers the construction-time failures
        (``DepartmentTeam._build`` raising) where ``run`` is never reached.

        Sprint audit-2026-05-16.D.05 (#2066, audit M-2): pass
        ``chief_session_id`` so the team's cost-record call attributes
        spend to this ChiefSession. ``cost_tracker.last_session_measurement``
        then has data to read for the dispatcher's strict-mode budget
        gate (D.04).
        """
        team = DepartmentTeam(
            self._config,
            lazy_build=False,
            chief_session_id=self._session.session_id,
            skill_allocator=self._skill_allocator,
        )
        # zone4-warmth.C.03 (#2297) — thread the optional message_history
        # through to ``DepartmentTeam.run``, which forwards it to
        # ``manager.run(message_history=...)``. When None (the default)
        # we omit the kwarg entirely so test fakes that assert on
        # ``team.run`` kwargs see the pre-C.03 call shape and existing
        # tests stay green without amendment.
        team_run_kwargs: dict[str, Any] = {"deps": self._deps}
        if self._message_history is not None:
            team_run_kwargs["message_history"] = self._message_history
        team_result = await team.run(self._task, **team_run_kwargs)
        # zone4-warmth.B.02 (#2294) — capture the team's underlying
        # PydanticAI RunResult so ``_try_persist_message_history`` can call
        # ``.all_messages()`` on the success path. ``getattr`` keeps this
        # defensive: if the team layer ever stops setting the attribute
        # (or a non-conformant stub team is used in tests), the persistence
        # helper degrades to a no-op rather than crashing.
        self._run_result = getattr(team, "_last_run_result", None)
        return team_result


def _truncate_text(value: str, max_chars: int) -> str:
    """Return a single bounded text field for memory checkpoints."""
    if max_chars <= 0:
        return ""
    if len(value) <= max_chars:
        return value
    return value[: max_chars - 15].rstrip() + "\n[...truncated]"
