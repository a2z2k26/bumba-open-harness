"""Tick-based proactive prompt injection.

Injects <tick> prompts into the Claude session when the agent has
nothing to do. The agent evaluates whether to act or sleep.

Enables autonomous action during idle periods.
"""
from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING, Awaitable, Callable

if TYPE_CHECKING:
    from bridge.proactive_safety import ProactiveGuard
    from bridge.tick_context import TickContextBuilder

logger = logging.getLogger(__name__)


class TickState(Enum):
    """Current state of the tick loop."""

    IDLE = "idle"          # No active work, ready to tick
    SLEEPING = "sleeping"  # Agent chose to sleep
    WORKING = "working"    # Agent is processing work
    PAUSED = "paused"      # Operator paused proactive mode


@dataclass
class TickContext:
    """Context provided with each tick prompt."""

    local_time: str
    pending_tasks: int
    recent_events: list[str]
    next_scheduled_service: str | None
    daily_log_summary: str  # Last 5 entries from today's log


# Regex patterns for sleep request parsing — ordered longest-unit first so
# "SLEEP 1h" matches hours before the bare-seconds pattern picks up "1".
_SLEEP_PATTERNS = [
    (re.compile(r"\bSLEEP\s+(\d+(?:\.\d+)?)h\b", re.IGNORECASE), 3600.0),
    (re.compile(r"\bSLEEP\s+(\d+(?:\.\d+)?)m\b", re.IGNORECASE), 60.0),
    (re.compile(r"\bSLEEP\s+(\d+(?:\.\d+)?)\b", re.IGNORECASE), 1.0),
]

# Proactive system prompt addendum injected when proactive mode is enabled
PROACTIVE_ADDENDUM = """
# Autonomous Work

You are running autonomously on a Mac mini. You receive <tick> prompts
that keep you alive between tasks. Each tick includes the current local
time, pending tasks, and recent activity.

## Pacing Rules

- If you have useful work to do: do it, then request sleep for an
  appropriate duration (e.g., 5 min after a quick check, 30 min after
  completing a task).
- If you have nothing to do: request sleep. Minimum 60 seconds.
- The operator can always interrupt your sleep by sending a message.
- Before sleeping, log what you decided and why to the daily log.

## What Counts as "Useful Work"

- Failed deploys or CI runs that need investigation
- GitHub issues assigned to you with no progress
- Stale PRs that need follow-up
- Knowledge that needs consolidation
- Service health issues detected in recent logs
- Upcoming calendar events that need preparation

## What Doesn't Count

- Checking things that were just checked
- Refreshing data with no reason to expect changes
- Any action without a clear benefit

## Sleep Format

To request sleep, include on its own line:
  SLEEP <seconds>   (e.g., SLEEP 300)
  SLEEP <N>m        (e.g., SLEEP 5m)
  SLEEP <N>h        (e.g., SLEEP 1h)
"""


class TickManager:
    """Manages the proactive tick loop.

    State machine::

        PAUSED ──enable()──► IDLE ──mark_working()──► WORKING
          ▲                    │ ▲                        │
          │                    │ └──────wake()────────────┘
        disable()           sleep()
                                │
                                ▼
                           SLEEPING ──wake() / timeout──► IDLE
    """

    def __init__(
        self,
        *,
        default_sleep_seconds: float = 300.0,
        min_sleep_seconds: float = 60.0,
        max_sleep_seconds: float = 3600.0,
        proactive_guard: "ProactiveGuard | None" = None,
        inbox_poster: "Callable[[str], Awaitable[None]] | None" = None,
        tick_context_builder: "TickContextBuilder | None" = None,
    ) -> None:
        """Initialize the tick manager.

        Args:
            default_sleep_seconds: Sleep duration when no explicit request found.
            min_sleep_seconds: Minimum allowed sleep duration (clamps shorter requests).
            max_sleep_seconds: Maximum allowed sleep duration (clamps longer requests).
            proactive_guard: Optional ProactiveGuard — gates tick frequency/cost.
            inbox_poster: E3.2 — async callable that posts a string to the operator
                inbox. When set, each permitted tick builds an orientation brief and
                awaits this callable. When None, the loop falls back to a bare info log.
            tick_context_builder: E3.2 — optional TickContextBuilder. When set,
                ``_build_tick_context()`` calls ``builder.build()``. When None,
                a minimal TickContext with only the current time is returned.
        """
        self._state = TickState.PAUSED
        # Clamped duration stored at sleep() call time; deadline set in wait_for_tick().
        self._sleep_duration: float = 0.0
        self._default_sleep = default_sleep_seconds
        self._min_sleep = min_sleep_seconds
        self._max_sleep = max_sleep_seconds
        self._wake_event: asyncio.Event | None = None
        self._enabled = False
        self._proactive_guard: "ProactiveGuard | None" = proactive_guard
        self._inbox_poster: "Callable[[str], Awaitable[None]] | None" = inbox_poster
        self._tick_context_builder: "TickContextBuilder | None" = tick_context_builder
        # Sprint 09.13 — background loop lifecycle. ``run()`` is started by
        # BridgeApp.start() under the proactive_enabled flag and shuts down
        # via ``stop()`` from BridgeApp.stop().
        self._stop_event: asyncio.Event | None = None
        self._running: bool = False

    # ── Properties ────────────────────────────────────────────────────────────

    @property
    def state(self) -> TickState:
        """Current tick loop state."""
        return self._state

    @property
    def enabled(self) -> bool:
        """Whether proactive mode is enabled."""
        return self._enabled

    @property
    def proactive_guard(self) -> "ProactiveGuard | None":
        """Return the wired ProactiveGuard, or None if not provided.

        Sprint 09.13 — exposes the guard so /proactive status output can
        surface its budget state once the consumer pipeline matures.
        """
        return self._proactive_guard

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _get_wake_event(self) -> asyncio.Event:
        """Return (or lazily create) the wake event for the current event loop."""
        if self._wake_event is None:
            self._wake_event = asyncio.Event()
        return self._wake_event

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def enable(self) -> None:
        """Enable proactive mode, setting state to IDLE."""
        self._enabled = True
        self._state = TickState.IDLE
        # Reset wake event so it binds to the active event loop on next use.
        self._wake_event = None

    def disable(self) -> None:
        """Disable proactive mode, setting state to PAUSED."""
        self._enabled = False
        self._state = TickState.PAUSED

    # ── State transitions ─────────────────────────────────────────────────────

    def sleep(self, seconds: float) -> None:
        """Agent requests sleep for N seconds.

        Duration is clamped to [min_sleep_seconds, max_sleep_seconds].
        The actual asyncio deadline is computed inside wait_for_tick() where
        a running event loop is guaranteed to be present.
        """
        self._sleep_duration = max(self._min_sleep, min(seconds, self._max_sleep))
        self._state = TickState.SLEEPING

    def wake(self) -> None:
        """External signal wakes the agent (operator message, notification)."""
        self._state = TickState.IDLE
        if self._wake_event is not None:
            self._wake_event.set()

    def mark_working(self) -> None:
        """Mark that the agent is actively processing work."""
        self._state = TickState.WORKING

    # ── Async tick gate ───────────────────────────────────────────────────────

    async def wait_for_tick(self) -> bool:
        """Block until the next tick should fire.

        If proactive mode is disabled, returns False immediately.
        If sleeping, waits out the remainder of the sleep (or until woken).
        If idle or working, returns True immediately.

        Returns:
            True if a tick should be sent to the agent, False if disabled.
        """
        if not self._enabled:
            return False

        if self._state == TickState.SLEEPING:
            duration = self._sleep_duration
            if duration > 0:
                wake_event = self._get_wake_event()
                wake_event.clear()
                try:
                    await asyncio.wait_for(wake_event.wait(), timeout=duration)
                    # Woken early by external signal — fall through to IDLE
                except asyncio.TimeoutError:
                    pass  # Sleep completed naturally

        self._state = TickState.IDLE
        return True

    # ── Prompt building ───────────────────────────────────────────────────────

    def build_tick_prompt(self, ctx: TickContext) -> str:
        """Build the <tick> prompt for injection into the Claude session.

        Includes only the last 5 recent events to keep context concise.
        """
        scheduled = ctx.next_scheduled_service or "nothing"
        events_text = "\n".join(f"  - {e}" for e in ctx.recent_events[-5:])
        if not events_text:
            events_text = "  (none)"

        return (
            f'<tick time="{ctx.local_time}">\n'
            f"pending_tasks: {ctx.pending_tasks}\n"
            f"next_scheduled: {scheduled}\n"
            f"recent_activity:\n{events_text}\n"
            f"daily_log:\n{ctx.daily_log_summary or '(empty)'}\n"
            f"</tick>"
        )

    # ── Sleep request parsing ─────────────────────────────────────────────────

    def parse_sleep_request(self, response_text: str) -> float:
        """Parse the agent's response for a sleep duration request.

        Recognises::

            SLEEP 300        → 300 seconds
            SLEEP 5m         → 300 seconds
            SLEEP 1h         → 3600 seconds

        Returns the default sleep duration when no pattern matches.
        The returned value is clamped to [min_sleep_seconds, max_sleep_seconds].
        """
        for pattern, multiplier in _SLEEP_PATTERNS:
            m = pattern.search(response_text)
            if m:
                raw = float(m.group(1)) * multiplier
                return max(self._min_sleep, min(raw, self._max_sleep))
        return self._default_sleep

    # ── Background loop ───────────────────────────────────────────────────────

    async def run(self) -> None:
        """Run the tick loop until stop() is called.

        Sprint 09.13 — minimal wedge that closes the construction gap.
        The loop:

        1. Waits on ``wait_for_tick()`` (returns False when proactive mode is
           disabled — used to gate the operator's runtime ``/proactive on``
           switch without recreating the task).
        2. Asks the optional ``ProactiveGuard.check_action`` for an
           ``investigate_failure`` verdict (the stand-in tick action).
        3. Logs the tick. Actual injection of the ``<tick>`` prompt into the
           Claude session is deliberately deferred — operator-inbox-aware
           injection is Phase 4B / dialogue-first work.

        The loop exits cleanly when ``stop()`` sets ``_stop_event``.
        """
        self._stop_event = asyncio.Event()
        self._running = True
        logger.info(
            "TickManager.run started (enabled=%s, default_sleep=%.0fs)",
            self._enabled,
            self._default_sleep,
        )
        try:
            while not self._stop_event.is_set():
                # When proactive is disabled, wait_for_tick() returns False
                # immediately. Sleep briefly so we don't busy-loop while the
                # operator considers flipping /proactive on.
                if not self._enabled:
                    try:
                        await asyncio.wait_for(
                            self._stop_event.wait(), timeout=self._default_sleep
                        )
                        return
                    except asyncio.TimeoutError:
                        continue

                should_tick = await self.wait_for_tick()
                if not should_tick:
                    continue

                if self._stop_event.is_set():
                    return

                # Sprint 09.13 — ProactiveGuard check before any tick action.
                # Plan 06 §9 item 7 flagged ProactiveGuard as never-invoked;
                # this is the production callsite that closes the gap.
                if self._proactive_guard is not None:
                    verdict = self._proactive_guard.check_action(
                        "investigate_failure"
                    )
                    if not verdict.allowed:
                        logger.debug(
                            "TickManager: proactive guard blocked tick (%s); "
                            "sleeping default",
                            verdict.reason,
                        )
                        self.sleep(self._default_sleep)
                        continue

                # E3.2 — post orientation brief to operator inbox (E-O8).
                # This branch NEVER invokes claude_runner or executes work.
                if self._inbox_poster is not None:
                    try:
                        from bridge.orientation import Orientation
                        from bridge.tick_context import build_orientation_brief
                        ctx = await self._build_tick_context()
                        orientation = Orientation.load()
                        brief = build_orientation_brief(ctx, orientation)
                        await self._inbox_poster(brief)
                        logger.info("TickManager: posted orientation brief to operator inbox")
                    except Exception as exc:  # noqa: BLE001 — tick must never crash the loop
                        logger.warning("TickManager: brief post failed: %s", exc)
                else:
                    logger.info(
                        "TickManager: tick fired (state=%s, no inbox poster wired)",
                        self._state.value,
                    )
                self.sleep(self._default_sleep)
        except asyncio.CancelledError:
            logger.info("TickManager.run cancelled")
            raise
        finally:
            self._running = False

    async def _build_tick_context(self) -> TickContext:
        """Return a TickContext from the wired builder, or a minimal fallback."""
        if self._tick_context_builder is not None:
            try:
                return await self._tick_context_builder.build()
            except Exception as exc:
                logger.warning("TickManager: context build failed, using fallback: %s", exc)
        return TickContext(
            local_time=datetime.now().strftime("%H:%M"),
            pending_tasks=0,
            recent_events=[],
            next_scheduled_service=None,
            daily_log_summary="",
        )

    async def stop(self) -> None:
        """Signal the background loop to exit.

        Idempotent: calling stop() before run() (or twice) is safe.
        """
        if self._stop_event is not None:
            self._stop_event.set()
        # Also wake the agent if it's currently sleeping inside wait_for_tick.
        if self._wake_event is not None:
            self._wake_event.set()
