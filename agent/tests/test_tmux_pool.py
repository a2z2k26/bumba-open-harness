"""Tests for TMUX pre-warm pool (#579)."""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock

from bridge.tmux_pool import TmuxPrewarmPool, WarmSlot


def _make_agent_state(session_name: str = "tmux-123", agent_id: str = "agent-abc"):
    state = MagicMock()
    state.session_name = session_name
    state.agent_id = agent_id
    return state


@pytest.mark.asyncio
async def test_fill_creates_warm_slots():
    mgr = MagicMock()
    mgr.spawn_agent = AsyncMock(return_value=_make_agent_state("sess-1", "ag-1"))
    mgr.spawn_idle_session = None  # disable so pool falls back to spawn_agent

    pool = TmuxPrewarmPool(tmux_mgr=mgr, target_size=2)
    await pool.fill()

    assert pool.size == 2


@pytest.mark.asyncio
async def test_acquire_returns_warm_slot():
    mgr = MagicMock()
    mgr.spawn_agent = AsyncMock(return_value=_make_agent_state("sess-1", "ag-1"))
    mgr.spawn_idle_session = None  # disable so pool falls back to spawn_agent

    pool = TmuxPrewarmPool(tmux_mgr=mgr, target_size=1)
    await pool.fill()

    slot = await pool.acquire()
    assert slot is not None
    assert isinstance(slot, WarmSlot)
    assert pool.size == 0


@pytest.mark.asyncio
async def test_acquire_returns_none_when_empty():
    pool = TmuxPrewarmPool(tmux_mgr=None, target_size=2)
    slot = await pool.acquire()
    assert slot is None


@pytest.mark.asyncio
async def test_fill_without_manager_is_noop():
    pool = TmuxPrewarmPool(tmux_mgr=None, target_size=2)
    await pool.fill()
    assert pool.size == 0


@pytest.mark.asyncio
async def test_shutdown_kills_warm_slots():
    mgr = MagicMock()
    mgr.spawn_agent = AsyncMock(return_value=_make_agent_state())
    mgr.kill_agent = AsyncMock()
    mgr.spawn_idle_session = None  # disable so pool falls back to spawn_agent

    pool = TmuxPrewarmPool(tmux_mgr=mgr, target_size=2)
    await pool.fill()
    assert pool.size == 2

    await pool.shutdown()
    assert pool.size == 0
    assert mgr.kill_agent.call_count == 2


@pytest.mark.asyncio
async def test_spawn_failure_returns_none():
    mgr = MagicMock()
    mgr.spawn_agent = AsyncMock(return_value="spawn error message")  # str = failure
    mgr.spawn_idle_session = None  # disable so pool falls back to spawn_agent

    pool = TmuxPrewarmPool(tmux_mgr=mgr, target_size=2)
    await pool.fill()
    # Should not crash; slots remain 0 because spawn returned an error string
    assert pool.size == 0


@pytest.mark.asyncio
async def test_spawn_idle_session_used_if_available():
    mgr = MagicMock()
    idle_state = _make_agent_state("idle-1", "idle-agent-1")
    mgr.spawn_idle_session = AsyncMock(return_value=idle_state)
    mgr.spawn_agent = AsyncMock()

    pool = TmuxPrewarmPool(tmux_mgr=mgr, target_size=1)
    await pool.fill()

    mgr.spawn_idle_session.assert_called_once()
    mgr.spawn_agent.assert_not_called()


def test_pool_target():
    pool = TmuxPrewarmPool(tmux_mgr=None, target_size=3)
    assert pool.target == 3
