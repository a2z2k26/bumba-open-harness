"""Calendar digest service — morning schedule + upcoming event alerts.

Extends ServiceBase. Two modes:
1. Morning digest (7:00am, pairs with briefing) — full day timeline
2. Upcoming alert (30 min before events) — individual event alerts

Combines Google Calendar + Cal.com bookings.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from .base import ServiceBase

log = logging.getLogger(__name__)

EST = ZoneInfo("America/New_York")


class CalendarService(ServiceBase):
    """Calendar digest and alert service."""

    def __init__(
        self,
        data_dir: str | Path,
        chat_id: str,
        *,
        event_callback=None,
        morning_hour: int = 7,
        morning_minute: int = 0,
        alert_minutes_before: int = 30,
    ) -> None:
        super().__init__(data_dir, event_callback=event_callback)
        self.chat_id = chat_id
        self.morning_hour = morning_hour
        self.morning_minute = morning_minute
        self.alert_minutes_before = alert_minutes_before

    def should_run_morning(self) -> bool:
        """Check if morning digest should run."""
        now = datetime.now(EST)
        target = now.replace(
            hour=self.morning_hour,
            minute=self.morning_minute,
            second=0,
            microsecond=0,
        )
        # Within 30-minute window of target
        if abs((now - target).total_seconds()) > 1800:
            return False

        state = self.load_state(filename="calendar-state.json")
        last_morning = state.get("last_morning_date", "")
        return last_morning != now.strftime("%Y-%m-%d")

    def should_check_alerts(self) -> bool:
        """Check if alert polling should run (every 15 min during active hours)."""
        now = datetime.now(EST)
        if not (7 <= now.hour < 22):
            return False

        state = self.load_state(filename="calendar-state.json")
        last_alert_check = state.get("last_alert_check", 0)
        return time.time() - last_alert_check >= 900  # 15 min

    def _format_time(self, iso_str: str) -> str:
        """Format an ISO datetime string for display."""
        try:
            dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
            return dt.astimezone(EST).strftime("%-I:%M %p")
        except (ValueError, TypeError):
            return iso_str

    def _detect_conflicts(self, events: list[dict]) -> list[tuple[dict, dict]]:
        """Detect overlapping events."""
        conflicts = []
        for i, a in enumerate(events):
            for b in events[i + 1:]:
                if a.get("all_day") or b.get("all_day"):
                    continue
                # Simple overlap: a.start < b.end and b.start < a.end
                if a.get("start", "") < b.get("end", "") and b.get("start", "") < a.get("end", ""):
                    conflicts.append((a, b))
        return conflicts

    def compile_morning_digest(self) -> str | None:
        """Compile the full day schedule."""
        try:
            from .calendar_interface import get_today_events
            from .calcom_interface import get_upcoming_bookings
        except ImportError:
            log.error("Calendar interfaces not available")
            return None

        events = get_today_events()
        bookings = get_upcoming_bookings(days=1)

        if not events and not bookings:
            return None

        lines = ["**Today's Schedule**\n"]

        # All-day events first
        all_day = [e for e in events if e.get("all_day")]
        timed = [e for e in events if not e.get("all_day")]

        if all_day:
            lines.append("All day:")
            for e in all_day:
                lines.append(f"  - {e['title']}")
            lines.append("")

        # Timed events as timeline
        if timed:
            for e in timed:
                start = self._format_time(e.get("start", ""))
                end = self._format_time(e.get("end", ""))
                location = f" @ {e['location']}" if e.get("location") else ""
                lines.append(f"  {start} - {end}  {e['title']}{location}")

        # Cal.com bookings
        if bookings:
            lines.append("\n**Cal.com Bookings:**")
            for b in bookings:
                start = self._format_time(b.get("start", ""))
                name = b.get("attendee_name", "someone")
                lines.append(f"  {start}  {b['title']} with {name}")

        # Conflict detection
        conflicts = self._detect_conflicts(timed)
        if conflicts:
            lines.append("\n**Conflicts:**")
            for a, b in conflicts:
                lines.append(f"  - '{a['title']}' overlaps with '{b['title']}'")

        return "\n".join(lines)

    def check_upcoming_alerts(self) -> list[str]:
        """Check for events starting within alert_minutes_before."""
        try:
            from .calendar_interface import get_upcoming_events
        except ImportError:
            return []

        state = self.load_state(filename="calendar-state.json")
        alerted = set(state.get("alerted_events", []))

        alerts = []
        events = get_upcoming_events(hours=1)

        now = datetime.now(EST)
        for event in events:
            if event["id"] in alerted:
                continue

            try:
                start = datetime.fromisoformat(
                    event["start"].replace("Z", "+00:00")
                ).astimezone(EST)
            except (ValueError, TypeError):
                continue

            minutes_until = (start - now).total_seconds() / 60
            if 0 < minutes_until <= self.alert_minutes_before:
                time_str = start.strftime("%-I:%M %p")
                location = f" @ {event['location']}" if event.get("location") else ""
                alert = f"**Upcoming:** {event['title']} at {time_str}{location} ({int(minutes_until)} min)"
                alerts.append(alert)
                alerted.add(event["id"])

        # Save alerted events (cleanup: only keep last 50)
        state["alerted_events"] = list(alerted)[-50:]
        state["last_alert_check"] = time.time()
        self.save_state(state, filename="calendar-state.json")

        return alerts

    def run(self) -> "ServiceResult":
        """Execute calendar service (Z2-S0.1)."""
        _start = time.monotonic()

        try:
            return self._run_inner(_start)
        except Exception as e:
            duration_ms = int((time.monotonic() - _start) * 1000)
            self.record_failure(str(e)[:500], filename="calendar-state.json")
            log.error("Calendar service failed after %dms: %s", duration_ms, e)
            raise

    def _run_inner(self, _start: float) -> "ServiceResult":
        """Inner run logic, separated for error tracking."""
        from bridge.services.result import ServiceResult

        work_items = 0

        # Morning digest
        if self.should_run_morning():
            digest = self.compile_morning_digest()
            if digest:
                self.deliver_message(self.chat_id, digest, source="calendar")
                work_items += 1

                # Update context object schedule section
                try:
                    from .calendar_interface import get_today_events, get_upcoming_events
                    from .context_builder import update_section
                    today = get_today_events()
                    upcoming = get_upcoming_events(hours=4)
                    next_event = None
                    if upcoming:
                        ev = upcoming[0]
                        try:
                            start = datetime.fromisoformat(ev["start"].replace("Z", "+00:00"))
                            mins = int((start - datetime.now(EST)).total_seconds() / 60)
                            next_event = {
                                "title": ev["title"],
                                "start": ev["start"],
                                "location": ev.get("location", ""),
                                "minutes_until": max(0, mins),
                            }
                        except (ValueError, TypeError):
                            pass
                    update_section("schedule", {
                        "next_event": next_event,
                        "today_count": len(today),
                        "conflicts": [
                            f"{a['title']} / {b['title']}"
                            for a, b in self._detect_conflicts(
                                [e for e in today if not e.get("all_day")]
                            )
                        ],
                    })
                except Exception:
                    pass

            state = self.load_state(filename="calendar-state.json")
            state["last_morning_date"] = datetime.now(EST).strftime("%Y-%m-%d")
            self.save_state(state, filename="calendar-state.json")

        # Upcoming alerts
        if self.should_check_alerts():
            alerts = self.check_upcoming_alerts()
            for alert in alerts:
                self.deliver_message(self.chat_id, alert, source="calendar-alert")
                work_items += 1

        duration_ms = int((time.monotonic() - _start) * 1000)
        self.record_success(duration_ms, filename="calendar-state.json")

        if work_items == 0:
            return ServiceResult(
                service="calendar",
                ok=True,
                work_items=0,
                duration_ms=duration_ms,
                cost_usd=0.0,
                skip_reason="no_morning_digest_or_alerts_due",
            )
        return ServiceResult(
            service="calendar",
            ok=True,
            work_items=work_items,
            duration_ms=duration_ms,
            cost_usd=0.0,
        )
