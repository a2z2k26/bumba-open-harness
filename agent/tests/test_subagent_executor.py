"""SubagentExecutor behavior — lift-and-shift regression tests (S02a #561).

AC-2: SubagentExecutor.execute(wo) is byte-for-byte equivalent to the
pre-sprint dispatcher._dispatch_subagent(wo) when claude_runner is present.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from bridge.executors.subagent import SubagentExecutor
from bridge.work_order import (
    Environment,
    WorkOrder,
    WorkOrderAssignment,
    WorkOrderStatus,
)


@pytest.fixture
def assigned_wo() -> WorkOrder:
    wo = WorkOrder.create(intent="hello world", skill="chat", project="test-proj")
    return wo.with_environment(Environment.SUBAGENT, "quick task").transition(
        WorkOrderStatus.ASSIGNED
    )


@pytest.mark.asyncio
async def test_subagent_executor_invokes_claude_runner_with_system_prompt(
    assigned_wo: WorkOrder,
) -> None:
    """Executor calls runner.invoke with message=intent and session_id prefix."""
    runner = MagicMock()
    runner.invoke = AsyncMock(
        return_value=MagicMock(is_error=False, response_text="done", error_type="")
    )
    executor = SubagentExecutor(claude_runner=runner)

    result = await executor.execute(assigned_wo)

    assert result.is_error is False
    runner.invoke.assert_awaited_once()
    kwargs = runner.invoke.await_args.kwargs
    assert kwargs["message"] == "hello world"
    # #2345: one-shot dispatch passes no session_id (a synthetic non-UUID
    # would reach `claude -p --resume` and be rejected). claude starts fresh.
    assert kwargs["session_id"] is None


@pytest.mark.asyncio
async def test_subagent_executor_uses_assigned_engineering_agent_prompt(
    assigned_wo: WorkOrder,
) -> None:
    """Assigned Zone 3 agents run through their named Claude prompt file."""
    runner = MagicMock()
    runner.invoke = AsyncMock(
        return_value=MagicMock(is_error=False, response_text="done", error_type="")
    )
    executor = SubagentExecutor(claude_runner=runner)
    assigned = assigned_wo.with_assignment(
        WorkOrderAssignment(
            agent_type="engineering",
            agent_id="engineering-chief",
            model="claude-sonnet-4-5",
        )
    )

    await executor.execute(assigned)

    kwargs = runner.invoke.await_args.kwargs
    assert kwargs["system_prompt_file"].endswith(
        "agent/config/claude-files/agents/engineering-chief.md"
    )


@pytest.mark.asyncio
async def test_subagent_executor_raises_when_runner_missing(
    assigned_wo: WorkOrder,
) -> None:
    """Without a runner, executor raises RuntimeError (not silently fallthroughs)."""
    executor = SubagentExecutor(claude_runner=None)
    with pytest.raises(RuntimeError, match="no runner"):
        await executor.execute(assigned_wo)


@pytest.mark.asyncio
async def test_subagent_executor_propagates_runner_exceptions(
    assigned_wo: WorkOrder,
) -> None:
    """Exceptions from runner are re-raised, not swallowed."""
    runner = MagicMock()
    runner.invoke = AsyncMock(side_effect=TimeoutError("connection timed out"))
    executor = SubagentExecutor(claude_runner=runner)

    with pytest.raises(TimeoutError, match="timed out"):
        await executor.execute(assigned_wo)


@pytest.mark.asyncio
async def test_subagent_executor_returns_result_on_success(
    assigned_wo: WorkOrder,
) -> None:
    """Successful invoke returns the ClaudeResult directly."""
    mock_result = MagicMock(is_error=False, response_text="the answer", error_type="")
    runner = MagicMock()
    runner.invoke = AsyncMock(return_value=mock_result)
    executor = SubagentExecutor(claude_runner=runner)

    result = await executor.execute(assigned_wo)

    assert result is mock_result


@pytest.mark.asyncio
async def test_subagent_executor_does_not_pass_synthetic_session_id(
    assigned_wo: WorkOrder,
) -> None:
    """#2345: a one-shot dispatch must NOT pass a synthetic non-UUID session_id.

    Passing `subagent-<wo.id[:8]>` reached `claude -p --resume`, which requires
    a real UUID and rejected it (exit 1, num_turns 0). The WO id is still in the
    log line for traceability, but session_id to invoke() is None so claude
    starts a fresh session.
    """
    runner = MagicMock()
    runner.invoke = AsyncMock(
        return_value=MagicMock(is_error=False, response_text="ok", error_type="")
    )
    executor = SubagentExecutor(claude_runner=runner)

    await executor.execute(assigned_wo)

    kwargs = runner.invoke.await_args.kwargs
    assert kwargs["session_id"] is None
    assert not str(kwargs["session_id"] or "").startswith("subagent-")
