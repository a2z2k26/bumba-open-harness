"""Integration tests for the proactive system (Sprint 8)."""
from __future__ import annotations

import asyncio
import time
from unittest.mock import MagicMock

import pytest

from bridge.tick_manager import TickManager, TickState
from bridge.tick_context import TickContextBuilder
from bridge.proactive_safety import ProactiveGuard
from bridge.proactive_metrics import ProactiveMetrics


# ── ProactiveMetrics unit tests ───────────────────────────────────────────────

def test_metrics_initial_state():
    m = ProactiveMetrics()
    assert m.ticks_sent == 0
    assert m.actions_taken == 0
    assert m.wake_interrupts == 0
    assert m.sleep_durations == []


def test_metrics_record_tick():
    m = ProactiveMetrics()
    m.record_tick()
    m.record_tick()
    assert m.ticks_sent == 2


def test_metrics_record_action():
    m = ProactiveMetrics()
    m.record_action("investigate_failure")
    assert m.actions_taken == 1


def test_metrics_record_sleep():
    m = ProactiveMetrics()
    m.record_sleep(300.0)
    m.record_sleep(600.0)
    assert len(m.sleep_durations) == 2
    assert m.average_sleep == 450.0


def test_metrics_record_wake():
    m = ProactiveMetrics()
    m.record_wake_interrupt()
    m.record_wake_interrupt()
    assert m.wake_interrupts == 2


def test_metrics_average_sleep_empty():
    m = ProactiveMetrics()
    assert m.average_sleep == 0.0


def test_metrics_to_dict():
    m = ProactiveMetrics()
    m.record_tick()
    m.record_action("update_knowledge")
    m.record_sleep(300.0)
    d = m.to_dict()
    assert d["ticks_sent"] == 1
    assert d["actions_taken"] == 1
    assert d["wake_interrupts"] == 0
    assert d["average_sleep_seconds"] == 300.0


def test_metrics_reset():
    m = ProactiveMetrics()
    m.record_tick()
    m.record_action("investigate_failure")
    m.reset()
    assert m.ticks_sent == 0
    assert m.actions_taken == 0


# ── Tick loop integration ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_tick_fires_when_enabled():
    """TickManager fires when enabled and idle."""
    tm = TickManager(min_sleep_seconds=1.0)
    tm.enable()
    result = await asyncio.wait_for(tm.wait_for_tick(), timeout=1.0)
    assert result is True


@pytest.mark.asyncio
async def test_tick_does_not_fire_when_disabled():
    """TickManager returns False immediately when disabled."""
    tm = TickManager()
    result = await tm.wait_for_tick()
    assert result is False


@pytest.mark.asyncio
async def test_sleep_then_wake_cycle():
    """Full sleep -> wake cycle completes correctly."""
    tm = TickManager(min_sleep_seconds=0.1, max_sleep_seconds=10.0)
    tm.enable()

    # Start sleeping
    tm.sleep(5.0)
    assert tm.state == TickState.SLEEPING

    # Wake early
    async def wake_soon():
        await asyncio.sleep(0.05)
        tm.wake()

    asyncio.create_task(wake_soon())
    result = await asyncio.wait_for(tm.wait_for_tick(), timeout=2.0)
    assert result is True
    assert tm.state == TickState.IDLE


@pytest.mark.asyncio
async def test_guard_resets_consecutive_on_sleep():
    """ProactiveGuard consecutive counter resets when agent sleeps."""
    guard = ProactiveGuard()

    # Take 3 actions (the limit)
    for _ in range(3):
        guard.record_action("investigate_failure", cost_usd=0.01)

    # Should be blocked now
    verdict = guard.check_action("investigate_failure")
    assert verdict.allowed is False

    # Sleep resets it
    guard.reset_consecutive()
    verdict = guard.check_action("investigate_failure")
    assert verdict.allowed is True


@pytest.mark.asyncio
async def test_context_builder_integrates_with_tick_manager():
    """TickContextBuilder produces valid context for tick prompt."""
    from unittest.mock import MagicMock
    config = MagicMock()
    config.data_dir = "/tmp/test_data"

    builder = TickContextBuilder(config)
    ctx = await builder.build()

    tm = TickManager()
    prompt = tm.build_tick_prompt(ctx)

    assert "<tick" in prompt
    assert "</tick>" in prompt
    assert ctx.local_time in prompt


# ── Scenario tests ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_idle_scenario_no_pending_work():
    """When nothing is pending, is_nothing_to_do() returns True."""
    config = MagicMock()
    config.data_dir = "/tmp"
    builder = TickContextBuilder(config)

    ctx = await builder.build()
    # No event bus, no tasks, no schedules
    assert builder.is_nothing_to_do(ctx) is True


@pytest.mark.asyncio
async def test_busy_scenario_with_events():
    """When events exist, is_nothing_to_do() returns False."""
    config = MagicMock()
    config.data_dir = "/tmp"
    builder = TickContextBuilder(config)

    mock_bus = MagicMock()
    mock_bus.recent_events = [
        MagicMock(event_type="message.received", timestamp=time.time())
    ]
    builder.set_event_bus(mock_bus)

    ctx = await builder.build()
    assert builder.is_nothing_to_do(ctx) is False


# ── Sleep duration parsing integration ───────────────────────────────────────

def test_parse_various_sleep_formats():
    """All sleep formats parse correctly with clamping."""
    tm = TickManager(min_sleep_seconds=60.0, max_sleep_seconds=3600.0)

    assert tm.parse_sleep_request("SLEEP 300") == 300.0
    assert tm.parse_sleep_request("SLEEP 5m") == 300.0
    assert tm.parse_sleep_request("sleep 1h") == 3600.0  # case insensitive
    assert tm.parse_sleep_request("No work to do.") == 300.0   # default
    assert tm.parse_sleep_request("SLEEP 10") == 60.0    # clamped to min
    assert tm.parse_sleep_request("SLEEP 9999") == 3600.0  # clamped to max
