"""Zone 4 Layer 2 WorkflowEngine.

Executes workflow definitions loaded by WorkflowRegistry.  Handles:

- Sequential and parallel step execution
- Shared context dictionary passed between steps
- Operator gate steps (asyncio.Event-based pause/resume)
- Failure compensation (on_failure rollback steps in reverse order)
- Workflow-level budget aggregate cost cap (sprint F-W.7)

This module is intentionally decoupled from the Discord / bridge runtime so
it can be unit-tested without live infrastructure.  Department calls are
delegated to an optional ``department_runner`` callable.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from contextlib import suppress
from datetime import datetime, timezone
from typing import Any, Callable
from bridge.dispatch_metrics import increment_module_counter

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class WorkflowBudgetExceeded(Exception):
    """Raised when a step would push the workflow over its cost cap."""

    def __init__(self, run_id: str, current_cost: float, cap: float) -> None:
        self.run_id = run_id
        self.current_cost = current_cost
        self.cap = cap
        super().__init__(
            f"Workflow run {run_id!r} budget exceeded: "
            f"${current_cost:.4f} / ${cap:.4f}"
        )


class WorkflowGateRejected(Exception):
    """Raised when an operator gate is rejected."""

    def __init__(self, run_id: str, step_name: str, reason: str = "") -> None:
        self.run_id = run_id
        self.step_name = step_name
        self.reason = reason
        super().__init__(
            f"Workflow run {run_id!r} gate '{step_name}' rejected: {reason}"
        )


class WorkflowGateTimeout(Exception):
    """Raised when an operator gate times out."""

    def __init__(self, run_id: str, step_name: str, timeout_seconds: int) -> None:
        self.run_id = run_id
        self.step_name = step_name
        self.timeout_seconds = timeout_seconds
        super().__init__(
            f"Workflow run {run_id!r} gate '{step_name}' timed out "
            f"after {timeout_seconds}s"
        )


# ---------------------------------------------------------------------------
# Run state
# ---------------------------------------------------------------------------


class WorkflowRunState:
    """In-memory state for a single workflow execution."""

    def __init__(self, run_id: str, workflow_name: str) -> None:
        self.run_id = run_id
        self.workflow_name = workflow_name
        self.status: str = "running"
        self.current_step: str | None = None
        self.context: dict[str, Any] = {}
        self.cost_usd: float = 0.0
        self.completed_steps: list[str] = []
        self.created_at: str = datetime.now(timezone.utc).isoformat()
        self.completed_at: str | None = None


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------


class WorkflowEngine:
    """Execute workflow definitions.

    Parameters
    ----------
    department_runner:
        Async callable ``(department, intent, context) -> (result_text, cost_usd)``.
        Called for every DepartmentStep.  Defaults to a stub that returns
        an empty result at zero cost (useful for testing).
    task_queue:
        Optional ``TaskQueue`` instance for operator gate steps.
    store:
        Optional ``WorkOrderStore`` instance for persisting run state.
    event_bus:
        Optional event bus for publishing ``z4.workflow.*`` events.
    discord_callback:
        Async callable ``(channel, message)`` for ``publish_discord`` action steps.
    """

    def __init__(
        self,
        department_runner: Callable[..., Any] | None = None,
        task_queue: Any | None = None,
        store: Any | None = None,
        event_bus: Any | None = None,
        discord_callback: Callable[..., Any] | None = None,
    ) -> None:
        self._department_runner = department_runner or _stub_department_runner
        self._task_queue = task_queue
        self._store = store
        self._event_bus = event_bus
        self._discord_callback = discord_callback
        self._active_runs: dict[str, WorkflowRunState] = {}
        # P2.5 (#1721) — retain background task references so the run
        # coroutine cannot be GC'd mid-flight. Pattern mirrors
        # ``app.py:3033-3203``.
        self._pending_tasks: set[asyncio.Task] = set()
        # audit-2026-05-16.C.06 (#2061) — keyed lookup so ``cancel(run_id)``
        # can reach the actual executing Task and not just flip state.
        # Entries are removed in the ``_execute`` finally block.
        self._tasks: dict[str, asyncio.Task] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start(self, cfg: Any, inputs: dict[str, Any] | None = None) -> str:
        """Schedule a workflow run and return its run_id.

        The run is executed as a background asyncio task.  The returned
        run_id can be used to track progress via ``get_run_state`` or
        cancel via ``cancel``.
        """
        increment_module_counter("workflow_engine.start", tier=1)
        run_id = f"wfrun-{uuid.uuid4().hex[:12]}"
        state = WorkflowRunState(run_id, cfg.name)
        state.context.update(inputs or {})
        self._active_runs[run_id] = state

        # Persist initial state
        self._persist_run(state)

        # Schedule background execution. P2.5 (#1721) — retain the task
        # reference on ``self._pending_tasks`` so it cannot be GC'd
        # mid-flight, and auto-discard on completion.
        task = asyncio.create_task(
            self._execute(cfg, state),
            name=f"workflow-execute-{run_id}",
        )
        self._pending_tasks.add(task)
        task.add_done_callback(self._pending_tasks.discard)
        # C.06 (#2061) — keyed handle for ``cancel(run_id)`` lookup. The
        # ``_execute`` finally block removes the entry on normal or
        # cancelled completion; we register the same drop as a safety
        # net so a crash inside finally still cleans the map.
        self._tasks[run_id] = task
        task.add_done_callback(lambda _t, rid=run_id: self._tasks.pop(rid, None))
        log.info("Workflow run %s started for '%s'", run_id, cfg.name)
        return run_id

    async def cancel(self, run_id: str) -> bool:
        """Cancel an active run.

        C.06 (#2061): cancels the executing asyncio Task (not just the
        in-memory state flag), awaits its cleanup under
        ``contextlib.suppress(asyncio.CancelledError)``, and only then
        records the cancelled terminal state. Returns True if the run
        was found and cancellation was driven through to completion;
        False if the run is unknown or already in a terminal state.
        """
        state = self._active_runs.get(run_id)
        if state is None or state.status not in {"running", "awaiting_approval"}:
            return False

        task = self._tasks.get(run_id)
        if task is not None and not task.done():
            # Drive the executing coroutine to cancel — this is what
            # makes the difference from the pre-C.06 state-only flip.
            task.cancel()
            # Awaiting the task gives the ``_execute`` CancelledError
            # branch + finally block a chance to run BEFORE we declare
            # the terminal state to the caller.
            with suppress(asyncio.CancelledError):
                await task
            # ``_execute`` has set state.status/completed_at and
            # persisted via _complete_run in its finally block. We are
            # done.
            log.info("Workflow run %s cancelled", run_id)
            return True

        # No live task — either the task already finished or the entry
        # was never recorded. Fall back to the legacy state-only flip
        # so the API stays consistent (operator sees ``cancelled``).
        state.status = "cancelled"
        state.completed_at = datetime.now(timezone.utc).isoformat()
        self._complete_run(state)
        log.info("Workflow run %s cancelled (no live task)", run_id)
        return True

    def get_run_state(self, run_id: str) -> WorkflowRunState | None:
        """Return the in-memory run state, or None if not found."""
        return self._active_runs.get(run_id)

    def active_run_ids(self) -> list[str]:
        """Return IDs of all non-terminal in-memory runs."""
        return [
            rid
            for rid, s in self._active_runs.items()
            if s.status in {"running", "awaiting_approval"}
        ]

    # ------------------------------------------------------------------
    # Execution core
    # ------------------------------------------------------------------

    async def _execute(self, cfg: Any, state: WorkflowRunState) -> None:
        """Run all steps, handling parallelism, gates, and compensation."""
        budget_cap = cfg.budget.max_cost_usd
        steps_by_name: dict[str, Any] = {s.name: s for s in cfg.steps}
        executed: set[str] = set()

        try:
            async with asyncio.timeout(cfg.budget.max_duration_seconds):
                i = 0
                while i < len(cfg.steps):
                    if state.status == "cancelled":
                        return

                    step = cfg.steps[i]

                    # Check if this step should be run in parallel with the previous
                    # (for simplicity: parallel steps are collected and awaited together)
                    parallel_group = [step]
                    while (
                        i + len(parallel_group) < len(cfg.steps)
                        and getattr(cfg.steps[i + len(parallel_group)], "parallel_with", None)
                        == step.name
                    ):
                        parallel_group.append(cfg.steps[i + len(parallel_group)])

                    if len(parallel_group) > 1:
                        await self._run_parallel_group(
                            parallel_group, state, budget_cap, steps_by_name
                        )
                        for s in parallel_group:
                            executed.add(s.name)
                        i += len(parallel_group)
                    else:
                        await self._run_step(step, state, budget_cap, steps_by_name)
                        executed.add(step.name)
                        i += 1

            state.status = "completed"
            state.completed_at = datetime.now(timezone.utc).isoformat()
            self._publish("z4.workflow.completed", state)

        except WorkflowBudgetExceeded as exc:
            log.warning("Workflow %s: budget exceeded — %s", state.run_id, exc)
            state.status = "failed"
            state.completed_at = datetime.now(timezone.utc).isoformat()
            self._publish("z4.workflow.budget_exceeded", state)
            await self._run_compensation(cfg.steps, executed, steps_by_name, state)

        except (WorkflowGateRejected, WorkflowGateTimeout) as exc:
            log.info("Workflow %s: gate did not pass — %s", state.run_id, exc)
            state.status = "failed"
            state.completed_at = datetime.now(timezone.utc).isoformat()
            self._publish("z4.workflow.gate_failed", state)
            await self._run_compensation(cfg.steps, executed, steps_by_name, state)

        except asyncio.TimeoutError:
            log.warning("Workflow %s: duration timeout", state.run_id)
            state.status = "failed"
            state.completed_at = datetime.now(timezone.utc).isoformat()
            self._publish("z4.workflow.timeout", state)

        except asyncio.CancelledError:
            # C.06 (#2061): cooperative cancel. Mark state and publish;
            # the ``finally`` block writes the terminal record. Re-raise
            # so the awaiting ``cancel()`` caller observes the task as
            # truly cancelled.
            log.info("Workflow %s: cancelled", state.run_id)
            state.status = "cancelled"
            state.completed_at = datetime.now(timezone.utc).isoformat()
            self._publish("z4.workflow.cancelled", state)
            raise

        except Exception as exc:  # noqa: BLE001
            log.error("Workflow %s: unhandled error — %s", state.run_id, exc)
            state.status = "failed"
            state.completed_at = datetime.now(timezone.utc).isoformat()
            self._publish("z4.workflow.failed", state)
            await self._run_compensation(cfg.steps, executed, steps_by_name, state)

        finally:
            self._complete_run(state)
            self._tasks.pop(state.run_id, None)

    async def _run_parallel_group(
        self,
        group: list[Any],
        state: WorkflowRunState,
        budget_cap: float,
        steps_by_name: dict[str, Any],
    ) -> None:
        """Run a group of steps concurrently, then merge their context outputs."""
        tasks = [
            self._run_step(s, state, budget_cap, steps_by_name, parallel=True)
            for s in group
        ]
        await asyncio.gather(*tasks)

    async def _run_step(
        self,
        step: Any,
        state: WorkflowRunState,
        budget_cap: float,
        steps_by_name: dict[str, Any],
        parallel: bool = False,
    ) -> None:
        """Dispatch a single step to the correct handler."""
        if state.status == "cancelled":
            return

        state.current_step = step.name
        log.debug("Workflow %s: running step '%s'", state.run_id, step.name)
        self._persist_run(state)

        step_type = getattr(step, "type", None)

        if step_type == "department":
            await self._run_department_step(step, state, budget_cap)
        elif step_type == "gate":
            await self._run_gate_step(step, state)
        elif step_type == "action":
            await self._run_action_step(step, state)
        else:
            log.warning(
                "Workflow %s: unknown step type '%s' for step '%s'",
                state.run_id,
                step_type,
                step.name,
            )

    async def _run_department_step(
        self,
        step: Any,
        state: WorkflowRunState,
        budget_cap: float,
    ) -> None:
        """Run a DepartmentStep: budget-check, invoke, update context."""
        # F-W.7: budget check before dispatching
        step_cap = getattr(step, "cost_limit_usd", None) or 0.0
        if step_cap > 0 and state.cost_usd + step_cap > budget_cap:
            raise WorkflowBudgetExceeded(state.run_id, state.cost_usd + step_cap, budget_cap)

        # Render intent with context placeholders
        intent = _render_template(step.intent, state.context)

        # Inject input context values
        step_context = {k: state.context.get(k) for k in (step.inputs or [])}

        # WS3.2 (#2570): carry the running workflow name to the runner under a
        # reserved underscore key (mirrors the existing ``_chat_id`` reserved
        # key). The app.py shim threads it onto BridgeDeps so the team_run cost
        # row that route() already records is TAGGED with the workflow — no
        # second cost record, so the daily total never double-counts.
        step_context["_workflow_name"] = state.workflow_name

        # Call department runner
        result_text, cost = await self._department_runner(
            step.department, intent, step_context
        )

        # Update aggregate cost
        state.cost_usd += cost

        # F-W.7: aggregate check after each step
        if state.cost_usd > budget_cap:
            raise WorkflowBudgetExceeded(state.run_id, state.cost_usd, budget_cap)

        # Write outputs to context
        for key in (step.outputs or []):
            state.context[key] = result_text

        log.debug(
            "Workflow %s: step '%s' completed (cost: $%.4f)",
            state.run_id,
            step.name,
            cost,
        )

    async def _run_gate_step(self, step: Any, state: WorkflowRunState) -> None:
        """Run a GateStep: evaluate condition, wait for operator approval."""
        # Evaluate condition (skip gate if condition is False)
        condition = getattr(step, "condition", None)
        if condition is not None:
            should_gate = _eval_condition(condition, state.context)
            if not should_gate:
                log.debug(
                    "Workflow %s: gate '%s' skipped (condition false)",
                    state.run_id,
                    step.name,
                )
                return

        if self._task_queue is None:
            log.warning(
                "Workflow %s: gate '%s' has no task_queue — auto-approving",
                state.run_id,
                step.name,
            )
            return

        # Create HITL task and wait
        message = _render_template(step.message, state.context)
        chat_id = state.context.get("_chat_id", "operator")
        task_id = await self._task_queue.create(
            chat_id,
            prompt=f"[workflow-gate] {message}",
            pending_question=message,
        )

        gate_event = asyncio.Event()
        state.status = "awaiting_approval"
        await self._task_queue.set_awaiting_approval(task_id, message, gate_event)
        self._persist_run(state)

        try:
            await asyncio.wait_for(gate_event.wait(), timeout=step.timeout_seconds)
        except asyncio.TimeoutError:
            raise WorkflowGateTimeout(state.run_id, step.name, step.timeout_seconds)

        # Re-fetch task to check outcome
        state.status = "running"
        task = await self._task_queue.get(task_id)
        if task is not None and task.status == "failed":
            reason = task.result or ""
            raise WorkflowGateRejected(state.run_id, step.name, reason)

    async def _run_action_step(self, step: Any, state: WorkflowRunState) -> None:
        """Run an ActionStep (Discord post, GitHub comment, etc.)."""
        message = _render_template(step.message, state.context)
        action = step.action

        if action == "publish_discord":
            channel = getattr(step, "channel", "operator") or "operator"
            if self._discord_callback is not None:
                await self._discord_callback(channel, message)
            else:
                log.info(
                    "Workflow %s: publish_discord(channel=%s): %s",
                    state.run_id,
                    channel,
                    message[:100],
                )

        elif action == "publish_github_comment":
            target = getattr(step, "target", "pr") or "pr"
            log.info(
                "Workflow %s: publish_github_comment(target=%s): %s",
                state.run_id,
                target,
                message[:100],
            )
        else:
            log.warning(
                "Workflow %s: unknown action '%s' in step '%s'",
                state.run_id,
                action,
                step.name,
            )

    # ------------------------------------------------------------------
    # F-W.6: Failure compensation
    # ------------------------------------------------------------------

    async def _run_compensation(
        self,
        all_steps: list[Any],
        completed: set[str],
        steps_by_name: dict[str, Any],
        state: WorkflowRunState,
    ) -> None:
        """Run compensating (rollback) steps in reverse order.

        For each completed step that declares ``on_failure``, the named
        compensating steps are executed in reverse step order.
        """
        compensation_steps: list[str] = []
        for step in reversed(all_steps):
            if step.name not in completed:
                continue
            on_failure = getattr(step, "on_failure", []) or []
            compensation_steps.extend(on_failure)

        if not compensation_steps:
            return

        log.info(
            "Workflow %s: running %d compensation step(s): %s",
            state.run_id,
            len(compensation_steps),
            compensation_steps,
        )

        for comp_name in compensation_steps:
            comp_step = steps_by_name.get(comp_name)
            if comp_step is None:
                log.warning(
                    "Workflow %s: compensation step '%s' not found",
                    state.run_id,
                    comp_name,
                )
                continue
            try:
                # Run compensation action (no budget check — compensations must run)
                await self._run_action_step(comp_step, state)
            except Exception as exc:  # noqa: BLE001
                log.error(
                    "Workflow %s: compensation step '%s' failed — %s",
                    state.run_id,
                    comp_name,
                    exc,
                )

    # ------------------------------------------------------------------
    # Persistence helpers
    # ------------------------------------------------------------------

    def _persist_run(self, state: WorkflowRunState) -> None:
        """Save current run state to store (best-effort)."""
        if self._store is None:
            return
        from bridge.work_order_store import WorkflowRun

        run = WorkflowRun(
            id=state.run_id,
            workflow_name=state.workflow_name,
            status=state.status,
            current_step=state.current_step,
            context=state.context,
            cost_usd=state.cost_usd,
            created_at=state.created_at,
            completed_at=state.completed_at,
        )
        try:
            self._store.save_workflow_run(run)
        except Exception as exc:  # noqa: BLE001
            log.error("Workflow %s: failed to persist run state — %s", state.run_id, exc)

    def _complete_run(self, state: WorkflowRunState) -> None:
        """Finalise a run in the store."""
        if self._store is None:
            return
        try:
            self._store.complete_run(
                state.run_id,
                status=state.status if state.status in {"completed", "failed", "cancelled"} else "failed",
                context=state.context,
                cost_usd=state.cost_usd,
            )
        except Exception as exc:  # noqa: BLE001
            log.error(
                "Workflow %s: failed to finalise run in store — %s",
                state.run_id,
                exc,
            )

    def _publish(self, event_type: str, state: WorkflowRunState) -> None:
        """Publish an event to EventBus (best-effort)."""
        if self._event_bus is None:
            return
        try:
            self._event_bus.publish(
                event_type=event_type,
                payload={
                    "run_id": state.run_id,
                    "workflow_name": state.workflow_name,
                    "status": state.status,
                    "cost_usd": state.cost_usd,
                },
                source="workflow_engine",
            )
        except Exception as exc:  # noqa: BLE001
            log.debug("WorkflowEngine: EventBus publish failed — %s", exc)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _stub_department_runner(
    department: str, intent: str, context: dict[str, Any]
) -> tuple[str, float]:
    """Default no-op department runner for testing without live infrastructure."""
    log.debug("Stub department_runner(%s): %s", department, intent[:80])
    return f"[stub result from {department}]", 0.0


def _render_template(template: str, context: dict[str, Any]) -> str:
    """Replace ``{key}`` placeholders in a template string with context values."""
    try:
        return template.format_map({k: str(v) for k, v in context.items()})
    except (KeyError, ValueError):
        return template


def _eval_condition(condition: str, context: dict[str, Any]) -> bool:
    """Evaluate a simple condition string against context.

    Supported patterns:
    - ``"{key} < value"``  — numeric less-than
    - ``"{key} > value"``  — numeric greater-than
    - ``"{key} == value"`` — equality

    Returns True if condition is met (gate should activate),
    False if condition is not met (gate should be skipped).
    Falls back to True (conservative — always gate) on parse errors.
    """
    import re

    # Render placeholders first
    rendered = _render_template(condition, context)

    # Try simple numeric comparisons
    m = re.match(r"^\s*(.+?)\s*(<|>|==|!=|<=|>=)\s*(.+?)\s*$", rendered)
    if m:
        left_str, op, right_str = m.groups()
        try:
            left = float(left_str)
            right = float(right_str)
            result = {
                "<": left < right,
                ">": left > right,
                "==": left == right,
                "!=": left != right,
                "<=": left <= right,
                ">=": left >= right,
            }.get(op, True)
            return result
        except ValueError:
            pass

    # Fallback: gate activates
    return True
