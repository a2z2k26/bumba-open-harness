"""TmuxExecutor — thin adapter over TmuxAgentManager (S02c #563)."""
from __future__ import annotations

from dataclasses import dataclass
from unittest.mock import AsyncMock, MagicMock

import pytest

from bridge.executors.tmux import TmuxExecutor
from bridge.work_order import Environment, WorkOrder, WorkOrderConstraints, WorkOrderStatus


def _make_wo(timeout_ms: int = 600_000) -> WorkOrder:
    wo = (
        WorkOrder.create(intent="run x", skill="ship-feature", project="p")
        .with_environment(Environment.TMUX, "long-running task")
        .transition(WorkOrderStatus.ASSIGNED)
    )
    from dataclasses import replace
    return replace(wo, constraints=WorkOrderConstraints(
        max_token_budget=100_000,
        timeout_ms=timeout_ms,
        quality_tier="standard",
    ))


@dataclass
class _FakeState:
    agent_id: str = "a1"
    session_name: str = "bumba-a1"
    status: str = "running"
    result_text: str = ""
    cost_usd: float = 0.0
    num_turns: int = 0


@pytest.mark.asyncio
async def test_tmux_executor_spawns_and_polls():
    """AC-1: spawns agent, polls until completed, returns result."""
    state = _FakeState()
    tmux_mgr = MagicMock()
    tmux_mgr.spawn_agent = AsyncMock(return_value=state)

    call_count = {"n": 0}

    async def monitor():
        call_count["n"] += 1
        if call_count["n"] >= 2:
            state.status = "completed"
            state.result_text = "task complete"
        return []

    tmux_mgr.monitor_agents = monitor

    executor = TmuxExecutor(tmux_mgr=tmux_mgr, poll_interval_s=0.01)
    result = await executor.execute(_make_wo())

    assert result.is_error is False
    assert result.response_text == "task complete"
    tmux_mgr.spawn_agent.assert_awaited_once()


@pytest.mark.asyncio
async def test_tmux_executor_errors_on_spawn_string():
    """AC-3: spawn_agent returning a string → RuntimeError."""
    tmux_mgr = MagicMock()
    tmux_mgr.spawn_agent = AsyncMock(return_value="Max concurrent agents reached")
    executor = TmuxExecutor(tmux_mgr=tmux_mgr)

    with pytest.raises(RuntimeError, match="spawn failed"):
        await executor.execute(_make_wo())


@pytest.mark.asyncio
async def test_tmux_executor_times_out():
    """AC-2: timeout kills agent, returns error_type=tmux_timeout."""
    state = _FakeState()
    tmux_mgr = MagicMock()
    tmux_mgr.spawn_agent = AsyncMock(return_value=state)
    tmux_mgr.kill_agent = AsyncMock(return_value=True)

    async def never_done():
        return []

    tmux_mgr.monitor_agents = never_done

    executor = TmuxExecutor(tmux_mgr=tmux_mgr, poll_interval_s=0.01)
    result = await executor.execute(_make_wo(timeout_ms=50))

    assert result.is_error is True
    assert result.error_type == "tmux_timeout"
    tmux_mgr.kill_agent.assert_awaited_once_with("a1")


@pytest.mark.asyncio
async def test_tmux_executor_raises_when_manager_missing():
    """RuntimeError if no tmux manager configured."""
    executor = TmuxExecutor(tmux_mgr=None)

    with pytest.raises(RuntimeError, match="no manager"):
        await executor.execute(_make_wo())


@pytest.mark.asyncio
async def test_tmux_executor_failed_agent_returns_error():
    """Agent status 'failed' → is_error=True result."""
    state = _FakeState()
    tmux_mgr = MagicMock()
    tmux_mgr.spawn_agent = AsyncMock(return_value=state)

    call_count = {"n": 0}

    async def monitor_fail():
        call_count["n"] += 1
        if call_count["n"] >= 2:
            state.status = "failed"
            state.result_text = ""
        return []

    tmux_mgr.monitor_agents = monitor_fail

    executor = TmuxExecutor(tmux_mgr=tmux_mgr, poll_interval_s=0.01)
    result = await executor.execute(_make_wo())

    assert result.is_error is True
    assert "tmux_failed" in result.error_type
