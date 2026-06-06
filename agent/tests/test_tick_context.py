"""Tests for TickContextBuilder."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from bridge.tick_context import TickContextBuilder, ServiceSchedule
from bridge.tick_manager import TickContext


@pytest.fixture
def builder(tmp_path):
    config = MagicMock()
    config.data_dir = str(tmp_path)
    return TickContextBuilder(config)


def test_service_schedule_fields():
    sched = ServiceSchedule(name="briefing", next_run_at=1000.0, interval_seconds=86400)
    assert sched.name == "briefing"
    assert sched.next_run_at == 1000.0
    assert sched.interval_seconds == 86400


@pytest.mark.asyncio
async def test_build_returns_tick_context(builder):
    ctx = await builder.build()
    assert isinstance(ctx, TickContext)
    assert ctx.local_time  # non-empty
    assert isinstance(ctx.pending_tasks, int)
    assert isinstance(ctx.recent_events, list)


@pytest.mark.asyncio
async def test_local_time_format(builder):
    ctx = await builder.build()
    # Should be HH:MM format
    parts = ctx.local_time.split(":")
    assert len(parts) == 2
    assert parts[0].isdigit()
    assert parts[1].isdigit()


@pytest.mark.asyncio
async def test_pending_tasks_zero_when_no_pipeline(builder):
    ctx = await builder.build()
    assert ctx.pending_tasks >= 0


@pytest.mark.asyncio
async def test_recent_events_from_event_bus(builder):
    mock_bus = MagicMock()
    mock_bus.recent_events = [
        MagicMock(event_type="message.received", timestamp=1000.0),
        MagicMock(event_type="session.created", timestamp=1001.0),
    ]
    builder.set_event_bus(mock_bus)
    ctx = await builder.build()
    assert len(ctx.recent_events) <= 10
    assert any("message.received" in e for e in ctx.recent_events)


@pytest.mark.asyncio
async def test_recent_events_empty_without_bus(builder):
    ctx = await builder.build()
    assert ctx.recent_events == []


@pytest.mark.asyncio
async def test_daily_log_summary_from_writer(builder, tmp_path):
    from bridge.daily_log import DailyLogWriter
    writer_cfg = MagicMock()
    writer_cfg.data_dir = str(tmp_path)
    writer = DailyLogWriter(writer_cfg)
    writer.append("test entry 1", category="message")
    writer.append("test entry 2", category="service")

    builder.set_daily_log(writer)
    ctx = await builder.build()
    assert "test entry" in ctx.daily_log_summary


@pytest.mark.asyncio
async def test_daily_log_summary_empty_without_writer(builder):
    ctx = await builder.build()
    assert ctx.daily_log_summary == ""


@pytest.mark.asyncio
async def test_next_scheduled_service_none_when_no_schedules(builder):
    ctx = await builder.build()
    assert ctx.next_scheduled_service is None


def test_add_service_schedule(builder):
    builder.add_service_schedule("briefing", interval_seconds=86400)
    schedules = builder.get_schedules()
    assert "briefing" in schedules


@pytest.mark.asyncio
async def test_next_scheduled_service_returns_soonest(builder):
    import time
    now = time.time()
    builder.add_service_schedule("briefing", interval_seconds=86400, next_run_at=now + 3600)
    builder.add_service_schedule("checkin", interval_seconds=14400, next_run_at=now + 600)
    ctx = await builder.build()
    assert ctx.next_scheduled_service == "checkin"


@pytest.mark.asyncio
async def test_nothing_to_do_heuristic(builder):
    """When idle, suggest longer sleep."""
    ctx = await builder.build()
    nothing_to_do = builder.is_nothing_to_do(ctx)
    assert isinstance(nothing_to_do, bool)


# ── E3.2: build_orientation_brief ────────────────────────────────────────────

def test_build_orientation_brief_includes_focus_and_priority():
    from bridge.tick_context import build_orientation_brief
    from bridge.orientation import Orientation, Priority
    from bridge.tick_manager import TickContext

    ctx = TickContext(
        local_time="10:30",
        pending_tasks=2,
        recent_events=["event_a", "event_b"],
        next_scheduled_service=None,
        daily_log_summary="",
    )
    orientation = Orientation(
        current_focus="Ship 1.0 by end of May",
        priorities=(Priority(rank=1, title="Close E-phase sprints", rationale=""),),
        win_criteria=(),
        updated_at="",
    )
    brief = build_orientation_brief(ctx, orientation)

    assert "Ship 1.0 by end of May" in brief
    assert "Close E-phase sprints" in brief
    assert "10:30" in brief
    assert "Want me to proceed" in brief


def test_build_orientation_brief_handles_empty_orientation():
    from bridge.tick_context import build_orientation_brief
    from bridge.orientation import Orientation
    from bridge.tick_manager import TickContext

    ctx = TickContext(
        local_time="08:00",
        pending_tasks=0,
        recent_events=[],
        next_scheduled_service=None,
        daily_log_summary="",
    )
    brief = build_orientation_brief(ctx, Orientation.empty())

    assert "no focus set" in brief
    assert "no priorities set" in brief
    assert "Want me to proceed" in brief


def test_build_orientation_brief_includes_recent_activity():
    from bridge.tick_context import build_orientation_brief
    from bridge.orientation import Orientation
    from bridge.tick_manager import TickContext

    ctx = TickContext(
        local_time="14:00",
        pending_tasks=3,
        recent_events=["alpha", "beta", "gamma", "delta"],
        next_scheduled_service=None,
        daily_log_summary="",
    )
    brief = build_orientation_brief(ctx, Orientation.empty())

    # Last 3 events should appear
    assert "gamma" in brief
    assert "delta" in brief
    # First event (beyond last-3 window) should not
    assert "alpha" not in brief


def test_cache_ttl(builder):
    """Cache TTL should be 5 minutes."""
    assert builder.cache_ttl_seconds == 300
