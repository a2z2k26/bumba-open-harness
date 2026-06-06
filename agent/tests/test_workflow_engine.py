"""Sprint P2.5 (#1721): assert the background task scheduled by
``WorkflowEngine.start`` is retained on ``self._pending_tasks`` for the
duration of its run. Source: combined-audit.md HI-8 (Lane A H-6).

Anti-pattern under repair: `asyncio.create_task(coro)` without a strong
reference means the task can be garbage-collected mid-flight. The fix
follows the named-task convention at ``app.py:3033-3203``.

Sprint audit-2026-05-16.C.06 (#2061): assert that ``WorkflowEngine.cancel``
cancels the executing asyncio task — not just the in-memory state flag —
and awaits the task's cleanup before recording the cancelled terminal
state. Source: 2026-05-16 whole-codebase audit (halt/cancel chain
finding).

Anti-pattern under repair: `cancel()` previously flipped the state to
``cancelled`` and returned, leaving the running step's coroutine in
flight. Operators saw the run marked cancelled while the underlying
work kept executing.
"""

from __future__ import annotations

import asyncio
import textwrap

import pytest

pytest.importorskip("pydantic")
pytest.importorskip("yaml")

from bridge.workflow_engine import WorkflowEngine
from config.workflows._schema import load_workflow_config


_PENDING_TASK_WORKFLOW = textwrap.dedent(
    """\
    name: pending-task-test
    trigger: explicit
    budget:
      max_cost_usd: 1.0
      max_duration_seconds: 5
    steps:
      - name: slow-step
        department: strategy
        intent: "Slow step that keeps the run alive long enough to observe."
        outputs: [r]
    """
)


class TestPendingTaskRetention:
    @pytest.mark.asyncio
    async def test_start_retains_execute_task_on_pending_tasks(self) -> None:
        """The background task scheduled by ``start`` MUST live on
        ``self._pending_tasks`` so the GC cannot drop it mid-flight."""
        cfg = load_workflow_config(_PENDING_TASK_WORKFLOW)

        # Department runner blocks long enough to observe the task while
        # it is in-flight (the slow-step waits on this event).
        release = asyncio.Event()

        async def dept_runner(dept, intent, ctx):
            await release.wait()
            return "result", 0.1

        engine = WorkflowEngine(department_runner=dept_runner)

        # P2.5 contract: every WorkflowEngine has a _pending_tasks set.
        assert hasattr(engine, "_pending_tasks"), (
            "WorkflowEngine must expose _pending_tasks for P2.5 task retention"
        )
        assert isinstance(engine._pending_tasks, set)
        assert len(engine._pending_tasks) == 0

        engine.start(cfg)

        # Yield to the event loop so the create_task call actually
        # registers on _pending_tasks. The execute coroutine is now
        # blocked on `release.wait()` inside the dept_runner.
        await asyncio.sleep(0.05)

        # Core assertion: the task is being held by the engine.
        assert len(engine._pending_tasks) == 1, (
            f"Expected 1 pending task while workflow runs, got "
            f"{len(engine._pending_tasks)}"
        )
        pending = next(iter(engine._pending_tasks))
        assert isinstance(pending, asyncio.Task)
        assert not pending.done()
        # Convention check: named task per P2.5.
        assert pending.get_name().startswith("workflow-execute-"), (
            f"Expected named task 'workflow-execute-<run_id>', got "
            f"{pending.get_name()!r}"
        )

        # Release the runner, let the task finish, and confirm the
        # done_callback drains the set.
        release.set()
        await pending
        await asyncio.sleep(0.05)
        assert len(engine._pending_tasks) == 0, (
            "done_callback should remove the task from _pending_tasks"
        )


# ---------------------------------------------------------------------------
# Sprint audit-2026-05-16.C.06 (#2061): cancel must cancel the asyncio task
# ---------------------------------------------------------------------------


_CANCEL_TEST_WORKFLOW = textwrap.dedent(
    """\
    name: cancel-test
    trigger: explicit
    budget:
      max_cost_usd: 1.0
      max_duration_seconds: 30
    steps:
      - name: long-running-step
        department: strategy
        intent: "Step that blocks long enough to be cancelled mid-flight."
        outputs: [r]
    """
)


_FAST_WORKFLOW = textwrap.dedent(
    """\
    name: fast-test
    trigger: explicit
    budget:
      max_cost_usd: 1.0
      max_duration_seconds: 5
    steps:
      - name: fast-step
        department: strategy
        intent: "Step that completes immediately."
        outputs: [r]
    """
)


class TestCancelAsyncioTask:
    """C.06 (#2061): cancel must actually cancel the executing task,
    await its cleanup, and only then record the cancelled terminal
    state."""

    @pytest.mark.asyncio
    async def test_cancel_actually_cancels_the_executing_task(self) -> None:
        """Cancelling a running workflow must cancel the underlying
        asyncio Task, not just flip the in-memory state flag."""
        cfg = load_workflow_config(_CANCEL_TEST_WORKFLOW)

        # The dept_runner blocks forever; only task.cancel() will
        # release it. A cooperative state-only "cancel" cannot.
        runner_entered = asyncio.Event()
        cancellation_observed = asyncio.Event()

        async def dept_runner(dept, intent, ctx):
            runner_entered.set()
            try:
                await asyncio.sleep(3600)  # blocks until cancelled
            except asyncio.CancelledError:
                cancellation_observed.set()
                raise
            return "result", 0.0

        engine = WorkflowEngine(department_runner=dept_runner)
        run_id = engine.start(cfg)

        # Wait until the runner is actually executing (i.e. the task is
        # blocked inside the dept_runner, not just scheduled).
        await asyncio.wait_for(runner_entered.wait(), timeout=2.0)
        assert run_id in engine._tasks, (
            "engine._tasks must be keyed by run_id for cancellation lookup"
        )
        task = engine._tasks[run_id]
        assert not task.done()

        # The act under test: cancel must propagate to the asyncio Task.
        result = await engine.cancel(run_id)

        assert result is True
        assert cancellation_observed.is_set(), (
            "The inner coroutine MUST observe CancelledError — a "
            "state-only flip cannot wake a blocked await"
        )
        assert task.done()
        # Task may be cancelled() or have completed via finally/except.
        # The contract is: it is no longer running.

    @pytest.mark.asyncio
    async def test_cancel_awaits_cleanup_before_terminal_state(self) -> None:
        """Terminal state must be recorded only AFTER the task ack's
        cancellation — so cleanup (finally blocks, store writes) runs
        before the operator sees ``cancelled``."""
        cfg = load_workflow_config(_CANCEL_TEST_WORKFLOW)

        cleanup_done = asyncio.Event()
        runner_entered = asyncio.Event()

        async def dept_runner(dept, intent, ctx):
            runner_entered.set()
            try:
                await asyncio.sleep(3600)
            except asyncio.CancelledError:
                # Simulate a real cleanup window — the engine MUST wait
                # for this to finish before declaring the run cancelled.
                await asyncio.sleep(0.05)
                cleanup_done.set()
                raise

        engine = WorkflowEngine(department_runner=dept_runner)
        run_id = engine.start(cfg)
        await asyncio.wait_for(runner_entered.wait(), timeout=2.0)

        await engine.cancel(run_id)

        # By the time cancel() returns, the task's cleanup must have
        # run AND the state must be cancelled. These two facts together
        # are the post-condition the spec requires.
        assert cleanup_done.is_set(), (
            "cancel() returned before the task finished cleanup"
        )
        state = engine.get_run_state(run_id)
        assert state is not None
        assert state.status == "cancelled"
        assert state.completed_at is not None

    @pytest.mark.asyncio
    async def test_cancel_already_finished_workflow_is_noop(self) -> None:
        """Cancelling a workflow that already terminated must NOT
        raise, and must NOT flip its terminal state to cancelled."""
        cfg = load_workflow_config(_FAST_WORKFLOW)

        async def fast_runner(dept, intent, ctx):
            return "done", 0.0

        engine = WorkflowEngine(department_runner=fast_runner)
        run_id = engine.start(cfg)

        # Let the workflow run to completion.
        await asyncio.sleep(0.1)
        state = engine.get_run_state(run_id)
        assert state is not None
        assert state.status == "completed", (
            f"workflow should have completed; got {state.status}"
        )

        # Cancelling now is a no-op. Must not raise, must return False,
        # must NOT clobber the completed state.
        result = await engine.cancel(run_id)
        assert result is False
        assert state.status == "completed"

    @pytest.mark.asyncio
    async def test_cancel_unknown_workflow_id_is_idempotent(self) -> None:
        """Cancelling a workflow_id the engine has never seen must NOT
        raise KeyError; it returns False and is otherwise inert."""
        engine = WorkflowEngine()
        result = await engine.cancel("wfrun-does-not-exist")
        assert result is False

    @pytest.mark.asyncio
    async def test_multiple_cancels_are_idempotent(self) -> None:
        """A second cancel() on the same workflow must NOT raise and
        must NOT re-trigger task.cancel() side-effects. Returns False
        the second time because the state is already terminal."""
        cfg = load_workflow_config(_CANCEL_TEST_WORKFLOW)

        runner_entered = asyncio.Event()

        async def dept_runner(dept, intent, ctx):
            runner_entered.set()
            await asyncio.sleep(3600)

        engine = WorkflowEngine(department_runner=dept_runner)
        run_id = engine.start(cfg)
        await asyncio.wait_for(runner_entered.wait(), timeout=2.0)

        first = await engine.cancel(run_id)
        assert first is True

        # Second cancel: state is already cancelled, no task lookup
        # succeeds. Must not raise; must return False (no-op).
        second = await engine.cancel(run_id)
        assert second is False

        # Third call for good measure.
        third = await engine.cancel(run_id)
        assert third is False
