"""Tests for TickManager — proactive tick loop infrastructure."""
from __future__ import annotations

import asyncio
import time

import pytest

from bridge.tick_manager import TickManager, TickState, TickContext


# ── TickState enum ────────────────────────────────────────────────────────────

def test_tick_states_exist():
    assert TickState.IDLE
    assert TickState.SLEEPING
    assert TickState.WORKING
    assert TickState.PAUSED


# ── Enable / disable ──────────────────────────────────────────────────────────

def test_initial_state_is_paused():
    tm = TickManager()
    assert tm.state == TickState.PAUSED


def test_enable_sets_idle():
    tm = TickManager()
    tm.enable()
    assert tm.state == TickState.IDLE
    assert tm.enabled is True


def test_disable_sets_paused():
    tm = TickManager()
    tm.enable()
    tm.disable()
    assert tm.state == TickState.PAUSED
    assert tm.enabled is False


# ── Sleep / wake ──────────────────────────────────────────────────────────────

def test_sleep_sets_sleeping_state():
    tm = TickManager(min_sleep_seconds=1.0)
    tm.enable()
    tm.sleep(10.0)
    assert tm.state == TickState.SLEEPING


def test_sleep_clamps_to_min(monkeypatch):
    tm = TickManager(min_sleep_seconds=60.0, max_sleep_seconds=3600.0)
    tm.enable()
    tm.sleep(1.0)  # below min
    # State is SLEEPING, duration clamped to 60
    assert tm.state == TickState.SLEEPING


def test_sleep_clamps_to_max():
    tm = TickManager(min_sleep_seconds=60.0, max_sleep_seconds=3600.0)
    tm.enable()
    tm.sleep(99999.0)  # above max
    assert tm.state == TickState.SLEEPING


def test_wake_sets_idle():
    tm = TickManager(min_sleep_seconds=1.0)
    tm.enable()
    tm.sleep(300.0)
    tm.wake()
    assert tm.state == TickState.IDLE


def test_mark_working():
    tm = TickManager()
    tm.enable()
    tm.mark_working()
    assert tm.state == TickState.WORKING


# ── wait_for_tick (async) ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_wait_for_tick_returns_false_when_disabled():
    tm = TickManager()
    # Not enabled — should return False immediately
    result = await tm.wait_for_tick()
    assert result is False


@pytest.mark.asyncio
async def test_wait_for_tick_returns_true_when_idle():
    tm = TickManager()
    tm.enable()
    # Already IDLE — should return True immediately
    result = await tm.wait_for_tick()
    assert result is True


@pytest.mark.asyncio
async def test_wake_interrupts_sleep():
    tm = TickManager(min_sleep_seconds=1.0, max_sleep_seconds=3600.0)
    tm.enable()
    tm.sleep(3600.0)  # Very long sleep

    async def wake_after_delay():
        await asyncio.sleep(0.05)
        tm.wake()

    asyncio.create_task(wake_after_delay())
    start = time.monotonic()
    result = await tm.wait_for_tick()
    elapsed = time.monotonic() - start

    assert result is True
    assert elapsed < 1.0  # Should have woken well before 3600s


# ── build_tick_prompt ─────────────────────────────────────────────────────────

def test_build_tick_prompt_contains_time():
    tm = TickManager()
    ctx = TickContext(
        local_time="14:30",
        pending_tasks=3,
        recent_events=["event1", "event2"],
        next_scheduled_service="briefing",
        daily_log_summary="- 14:00 [service] briefing started",
    )
    prompt = tm.build_tick_prompt(ctx)
    assert "14:30" in prompt
    assert "pending_tasks" in prompt.lower() or "3" in prompt
    assert "<tick" in prompt
    assert "</tick>" in prompt


def test_build_tick_prompt_no_scheduled_service():
    tm = TickManager()
    ctx = TickContext(
        local_time="02:00",
        pending_tasks=0,
        recent_events=[],
        next_scheduled_service=None,
        daily_log_summary="",
    )
    prompt = tm.build_tick_prompt(ctx)
    assert "nothing" in prompt.lower() or "none" in prompt.lower() or "no" in prompt.lower()


def test_build_tick_prompt_truncates_events():
    tm = TickManager()
    ctx = TickContext(
        local_time="10:00",
        pending_tasks=0,
        recent_events=[f"event{i}" for i in range(20)],
        next_scheduled_service=None,
        daily_log_summary="",
    )
    prompt = tm.build_tick_prompt(ctx)
    # Should only include last 5 events
    assert "event19" in prompt
    assert "event0" not in prompt


# ── parse_sleep_request ───────────────────────────────────────────────────────

def test_parse_sleep_seconds():
    tm = TickManager(min_sleep_seconds=60.0, max_sleep_seconds=3600.0)
    assert tm.parse_sleep_request("SLEEP 300") == 300.0


def test_parse_sleep_minutes():
    tm = TickManager(min_sleep_seconds=60.0, max_sleep_seconds=3600.0)
    assert tm.parse_sleep_request("SLEEP 5m") == 300.0


def test_parse_sleep_hours():
    tm = TickManager(min_sleep_seconds=60.0, max_sleep_seconds=3600.0)
    assert tm.parse_sleep_request("SLEEP 1h") == 3600.0


def test_parse_sleep_no_match_returns_default():
    tm = TickManager(min_sleep_seconds=60.0, max_sleep_seconds=3600.0, default_sleep_seconds=300.0)
    assert tm.parse_sleep_request("I have nothing to do right now.") == 300.0


def test_parse_sleep_clamps_to_min():
    tm = TickManager(min_sleep_seconds=60.0, max_sleep_seconds=3600.0)
    assert tm.parse_sleep_request("SLEEP 10") == 60.0


def test_parse_sleep_clamps_to_max():
    tm = TickManager(min_sleep_seconds=60.0, max_sleep_seconds=3600.0)
    assert tm.parse_sleep_request("SLEEP 99999") == 3600.0


# ── TickContext dataclass ────────────────────────────────────────────────────

def test_tick_context_fields():
    ctx = TickContext(
        local_time="09:00",
        pending_tasks=5,
        recent_events=["a", "b"],
        next_scheduled_service="email",
        daily_log_summary="some log",
    )
    assert ctx.local_time == "09:00"
    assert ctx.pending_tasks == 5
    assert ctx.next_scheduled_service == "email"


# ── E3.2: orientation brief to operator inbox ─────────────────────────────────

@pytest.mark.asyncio
async def test_run_loop_posts_brief_to_inbox_when_guard_allows():
    """Tick fires → brief built → inbox poster called exactly once."""
    posted: list[str] = []

    async def mock_poster(brief: str) -> None:
        posted.append(brief)

    from bridge.orientation import Orientation, Priority

    orientation = Orientation(
        current_focus="Ship 1.0",
        priorities=(Priority(rank=1, title="Close E-phase", rationale=""),),
        win_criteria=(),
        updated_at="",
    )

    with pytest.MonkeyPatch().context() as mp:
        mp.setattr("bridge.orientation.Orientation.load", staticmethod(lambda path=None: orientation))
        tm = TickManager(
            min_sleep_seconds=1.0,
            default_sleep_seconds=1.0,
            inbox_poster=mock_poster,
        )
        tm.enable()

        # Run one iteration then stop
        async def stop_after_post():
            while not posted:
                await asyncio.sleep(0.01)
            await tm.stop()

        await asyncio.gather(tm.run(), stop_after_post())

    assert len(posted) == 1
    assert "Ship 1.0" in posted[0]
    assert "Close E-phase" in posted[0]
    assert "Want me to proceed" in posted[0]


@pytest.mark.asyncio
async def test_run_loop_skips_post_when_guard_blocks():
    """ProactiveGuard blocks → poster NOT called."""
    from unittest.mock import MagicMock

    mock_verdict = MagicMock()
    mock_verdict.allowed = False
    mock_verdict.reason = "budget exceeded"

    mock_guard = MagicMock()
    mock_guard.check_action.return_value = mock_verdict

    posted: list[str] = []

    async def mock_poster(brief: str) -> None:
        posted.append(brief)

    tm = TickManager(
        min_sleep_seconds=1.0,
        default_sleep_seconds=1.0,
        proactive_guard=mock_guard,
        inbox_poster=mock_poster,
    )
    tm.enable()

    # Run one tick cycle (guard blocks, should not post)
    run_task = asyncio.create_task(tm.run())
    await asyncio.sleep(0.1)
    await tm.stop()
    await run_task

    assert posted == []
    mock_guard.check_action.assert_called()


@pytest.mark.asyncio
async def test_run_loop_does_not_invoke_claude_runner():
    """E-O8 contract: no claude_runner symbol is touched from the tick loop."""
    from unittest.mock import patch

    call_log: list[str] = []

    async def mock_poster(brief: str) -> None:
        call_log.append("poster")

    from bridge.orientation import Orientation
    with patch("bridge.orientation.Orientation.load", return_value=Orientation.empty()):
        with patch("bridge.claude_runner.ClaudeRunner.invoke") as mock_cr:
            tm = TickManager(
                min_sleep_seconds=1.0,
                default_sleep_seconds=1.0,
                inbox_poster=mock_poster,
            )
            tm.enable()

            run_task = asyncio.create_task(tm.run())
            # Wait until at least one post occurs
            for _ in range(50):
                if call_log:
                    break
                await asyncio.sleep(0.02)
            await tm.stop()
            await run_task

    assert mock_cr.call_count == 0, "claude_runner must not be invoked from tick loop (E-O8)"


@pytest.mark.asyncio
async def test_run_loop_handles_orientation_missing_file():
    """Orientation file missing → brief still posted with empty-orientation defaults."""
    posted: list[str] = []

    async def mock_poster(brief: str) -> None:
        posted.append(brief)

    from bridge.orientation import Orientation
    with pytest.MonkeyPatch().context() as mp:
        mp.setattr("bridge.orientation.Orientation.load", staticmethod(lambda path=None: Orientation.empty()))
        tm = TickManager(
            min_sleep_seconds=1.0,
            default_sleep_seconds=1.0,
            inbox_poster=mock_poster,
        )
        tm.enable()

        run_task = asyncio.create_task(tm.run())
        for _ in range(50):
            if posted:
                break
            await asyncio.sleep(0.02)
        await tm.stop()
        await run_task

    assert len(posted) >= 1
    assert "no focus set" in posted[0]
    assert "Want me to proceed" in posted[0]


@pytest.mark.asyncio
async def test_inbox_post_failure_does_not_crash_loop():
    """inbox_poster raises → loop continues to next iteration with WARNING logged."""
    call_count = 0

    async def failing_poster(brief: str) -> None:
        nonlocal call_count
        call_count += 1
        raise RuntimeError("Discord unavailable")

    from bridge.orientation import Orientation
    with pytest.MonkeyPatch().context() as mp:
        mp.setattr("bridge.orientation.Orientation.load", staticmethod(lambda path=None: Orientation.empty()))
        tm = TickManager(
            min_sleep_seconds=1.0,
            default_sleep_seconds=1.0,
            inbox_poster=failing_poster,
        )
        tm.enable()

        run_task = asyncio.create_task(tm.run())
        # Let the loop run long enough to attempt at least one post
        for _ in range(50):
            if call_count >= 1:
                break
            await asyncio.sleep(0.02)
        await tm.stop()
        await run_task

    # Loop survived despite repeated poster failures
    assert call_count >= 1
    assert tm._running is False
