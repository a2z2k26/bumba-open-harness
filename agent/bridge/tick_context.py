"""Tick context builder for proactive prompt enrichment.

Gathers current system state to build actionable TickContext objects
for injection into tick prompts.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any

from bridge.tick_manager import TickContext

if TYPE_CHECKING:
    from bridge.orientation import Orientation


@dataclass
class ServiceSchedule:
    """Schedule entry for a bridge service."""

    name: str
    next_run_at: float  # Unix timestamp
    interval_seconds: int


class TickContextBuilder:
    """Builds enriched TickContext objects for the tick prompt.

    Aggregates: local time, pending task count, recent event bus activity,
    next scheduled service, and daily log summary.
    """

    cache_ttl_seconds: int = 300  # 5-minute cache for expensive queries

    def __init__(self, config: Any) -> None:
        """Initialize with a config object."""
        self._config = config
        self._event_bus: Any | None = None
        self._daily_log: Any | None = None
        self._task_pipeline: Any | None = None
        self._schedules: dict[str, ServiceSchedule] = {}
        self._last_task_count: int = 0
        self._last_task_scan: float = 0.0

    def set_event_bus(self, bus: Any) -> None:
        """Wire in the event bus for recent event collection."""
        self._event_bus = bus

    def set_daily_log(self, writer: Any) -> None:
        """Wire in the daily log writer for summary generation."""
        self._daily_log = writer

    def set_task_pipeline(self, pipeline: Any) -> None:
        """Wire in the task pipeline for pending task counting."""
        self._task_pipeline = pipeline

    def add_service_schedule(
        self,
        name: str,
        interval_seconds: int,
        next_run_at: float | None = None,
    ) -> None:
        """Register a service schedule for next-service calculation."""
        if next_run_at is None:
            next_run_at = time.time() + interval_seconds
        self._schedules[name] = ServiceSchedule(
            name=name,
            next_run_at=next_run_at,
            interval_seconds=interval_seconds,
        )

    def get_schedules(self) -> dict[str, ServiceSchedule]:
        """Return registered service schedules."""
        return dict(self._schedules)

    def is_nothing_to_do(self, ctx: TickContext) -> bool:
        """Heuristic: return True if the agent appears to have nothing urgent.

        Used to suggest longer sleep durations in the tick prompt.
        """
        return (
            ctx.pending_tasks == 0
            and len(ctx.recent_events) == 0
            and ctx.next_scheduled_service is None
        )

    async def build(self) -> TickContext:
        """Build a TickContext with current system state.

        Returns:
            Populated TickContext ready for tick prompt injection.
        """
        local_time = datetime.now().strftime("%H:%M")
        pending_tasks = await self._get_pending_tasks()
        recent_events = self._get_recent_events()
        next_service = self._get_next_scheduled_service()
        log_summary = self._get_daily_log_summary()

        return TickContext(
            local_time=local_time,
            pending_tasks=pending_tasks,
            recent_events=recent_events,
            next_scheduled_service=next_service,
            daily_log_summary=log_summary,
        )

    async def _get_pending_tasks(self) -> int:
        """Count pending tasks from the task pipeline (cached)."""
        now = time.time()
        if now - self._last_task_scan < self.cache_ttl_seconds:
            return self._last_task_count

        if self._task_pipeline is None:
            return 0

        try:
            if hasattr(self._task_pipeline, "list_pending"):
                tasks = await self._task_pipeline.list_pending()
                self._last_task_count = len(tasks)
            else:
                self._last_task_count = 0
        except Exception:
            self._last_task_count = 0

        self._last_task_scan = now
        return self._last_task_count

    def _get_recent_events(self) -> list[str]:
        """Get recent event types from the event bus (last 10)."""
        if self._event_bus is None:
            return []

        try:
            events = getattr(self._event_bus, "recent_events", [])
            result = []
            for ev in events[-10:]:
                etype = getattr(ev, "event_type", str(ev))
                ts = getattr(ev, "timestamp", None)
                if ts:
                    from datetime import datetime
                    dt = datetime.fromtimestamp(ts).strftime("%H:%M")
                    result.append(f"{dt} {etype}")
                else:
                    result.append(etype)
            return result
        except Exception:
            return []

    def _get_next_scheduled_service(self) -> str | None:
        """Return the name of the soonest scheduled service, or None."""
        if not self._schedules:
            return None

        now = time.time()
        soonest = min(self._schedules.values(), key=lambda s: s.next_run_at)
        if soonest.next_run_at > now + 86400:  # More than a day away — skip
            return None
        return soonest.name

    def _get_daily_log_summary(self) -> str:
        """Return the last 5 lines of today's daily log."""
        if self._daily_log is None:
            return ""

        try:
            content = self._daily_log.read_today()
            if not content:
                return ""
            lines = [l for l in content.splitlines() if l.strip()]
            return "\n".join(lines[-5:])
        except Exception:
            return ""


def build_orientation_brief(
    ctx: TickContext,
    orientation: "Orientation",
) -> str:
    """Build the operator-facing status update for a proactive tick.

    Per operator decision E-O8: this is a Discord-posted status update,
    NOT autonomous work execution. The agent surfaces what it would do
    if the operator approves; it does not act.
    """
    focus = orientation.current_focus or "(no focus set)"
    top_priority = (
        orientation.priorities[0].title
        if orientation.priorities
        else "(no priorities set)"
    )
    activity = ", ".join(ctx.recent_events[-3:]) if ctx.recent_events else "(quiet)"
    return (
        f"Status check {ctx.local_time}.\n"
        f"Focus: {focus}\n"
        f"Top priority: {top_priority}\n"
        f"Recent: {activity}\n"
        f"Pending tasks: {ctx.pending_tasks}\n"
        f"Want me to proceed on the top priority, or redirect?"
    )
