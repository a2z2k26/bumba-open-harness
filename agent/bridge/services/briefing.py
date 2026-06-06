"""Morning briefing service.

Sends a daily summary at a configured time with data from pluggable sources.
No Claude needed — direct DB queries only.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Callable

from .base import ServiceBase, SkipClass, SkipReason

log = logging.getLogger(__name__)

# Registry for briefing data sources
_SOURCES: list[tuple[str, Callable]] = []


def register_source(name: str):
    """Decorator to register a briefing data source."""
    def decorator(func: Callable):
        _SOURCES.append((name, func))
        return func
    return decorator


@register_source("Goals Summary")
def _goals_summary(conn: sqlite3.Connection) -> str | None:
    """Summarize active and overdue goals."""
    rows = conn.execute(
        """SELECT key, value FROM knowledge
           WHERE key LIKE 'goal:%'
           AND (archived IS NULL OR archived = 0)"""
    ).fetchall()

    if not rows:
        return None

    lines = []
    now = datetime.now()
    active = 0
    overdue = 0
    for row in rows:
        try:
            data = json.loads(row[1])
            desc = data.get("description", row[0])
            deadline_str = data.get("deadline")
            if deadline_str:
                deadline = datetime.fromisoformat(deadline_str)
                if deadline < now:
                    lines.append(f"  - OVERDUE: {desc} (was due {deadline.strftime('%b %d')})")
                    overdue += 1
                else:
                    lines.append(f"  - {desc} (due {deadline.strftime('%b %d')})")
                    active += 1
            else:
                lines.append(f"  - {desc}")
                active += 1
        except (json.JSONDecodeError, ValueError):
            lines.append(f"  - {row[0]}")
            active += 1

    header = f"**Goals** ({active} active"
    if overdue:
        header += f", {overdue} overdue"
    header += ")"

    return header + "\n" + "\n".join(lines)


@register_source("Recent Activity")
def _recent_activity(conn: sqlite3.Connection) -> str | None:
    """Summarize conversation activity in the last 24h."""
    row = conn.execute(
        """SELECT COUNT(*) as cnt FROM conversations
           WHERE created_at > datetime('now', '-24 hours')"""
    ).fetchone()
    msg_count = row[0] if row else 0

    row = conn.execute(
        """SELECT COUNT(*) as cnt FROM conversations
           WHERE created_at > datetime('now', '-24 hours') AND role = 'assistant'"""
    ).fetchone()
    assistant_count = row[0] if row else 0

    if msg_count == 0:
        return "**Activity**: No conversations in the last 24h"

    return f"**Activity**: {msg_count} messages ({assistant_count} from me) in the last 24h"


@register_source("Knowledge Updates")
def _knowledge_updates(conn: sqlite3.Connection) -> str | None:
    """Report knowledge base changes in the last 24h."""
    row = conn.execute(
        """SELECT COUNT(*) as cnt FROM knowledge
           WHERE updated_at > datetime('now', '-24 hours')"""
    ).fetchone()
    count = row[0] if row else 0

    if count == 0:
        return None

    return f"**Knowledge**: {count} entries updated in the last 24h"


@register_source("Today's Schedule")
def _todays_schedule(conn: sqlite3.Connection) -> str | None:
    """Include today's calendar events in the briefing.

    Sprint 02.11: Cal.com bookings are now fetched per-account so the briefing
    surfaces both ``personal`` and ``business`` (or whichever labels are
    configured). Each booking line is prefixed with ``[<account>]`` when more
    than one account exists so the operator can see which calendar is which.
    """
    try:
        from .calendar_interface import get_today_events
        from .calcom_interface import get_upcoming_bookings, list_all_accounts
    except ImportError:
        return None

    events = get_today_events()

    accounts = list_all_accounts()
    bookings_by_account: list[tuple[str, list[dict]]] = []
    for acct in accounts:
        try:
            acct_bookings = get_upcoming_bookings(days=1, account=acct)
        except Exception as exc:  # noqa: BLE001 — best-effort per-account
            log.warning("briefing.calcom_fetch_failed account=%s: %s", acct, exc)
            continue
        if acct_bookings:
            bookings_by_account.append((acct, acct_bookings))

    has_bookings = any(b for _, b in bookings_by_account)
    if not events and not has_bookings:
        return None

    lines = ["**Schedule**"]

    for e in events:
        if e.get("all_day"):
            lines.append(f"  - All day: {e['title']}")
        else:
            try:
                start = datetime.fromisoformat(e["start"].replace("Z", "+00:00"))
                end = datetime.fromisoformat(e["end"].replace("Z", "+00:00"))
                time_str = f"{start.strftime('%-I:%M %p')} - {end.strftime('%-I:%M %p')}"
            except (ValueError, TypeError):
                time_str = "TBD"
            location = f" @ {e['location']}" if e.get("location") else ""
            lines.append(f"  - {time_str}: {e['title']}{location}")

    show_label = len(bookings_by_account) > 1
    for acct, acct_bookings in bookings_by_account:
        for b in acct_bookings:
            try:
                start = datetime.fromisoformat(b["start"].replace("Z", "+00:00"))
                time_str = start.strftime("%-I:%M %p")
            except (ValueError, TypeError):
                time_str = "TBD"
            name = b.get("attendee_name", "someone")
            label = f"[{acct}] " if show_label else ""
            lines.append(f"  - {label}{time_str}: {b['title']} with {name} (Cal.com)")

    return "\n".join(lines)


@register_source("System Health")
def _system_health(conn: sqlite3.Connection) -> str | None:
    """Report system health indicators."""
    lines = []

    # Error count
    row = conn.execute(
        """SELECT COUNT(*) as cnt FROM audit_log
           WHERE event_type LIKE '%error%'
           AND timestamp > datetime('now', '-24 hours')"""
    ).fetchone()
    error_count = row[0] if row else 0

    # Pending messages
    row = conn.execute(
        "SELECT COUNT(*) as cnt FROM message_queue WHERE status = 'pending'"
    ).fetchone()
    pending = row[0] if row else 0

    if error_count > 0:
        lines.append(f"  - {error_count} errors in the last 24h")
    if pending > 0:
        lines.append(f"  - {pending} messages pending in queue")

    if not lines:
        return "**System**: All clear"

    return "**System**:\n" + "\n".join(lines)


class BriefingService(ServiceBase):
    """Morning briefing service with pluggable data sources."""

    def __init__(
        self,
        data_dir: str | Path,
        db_path: str | Path,
        chat_id: str,
        *,
        enabled: bool = True,
        delivery_hour: int = 7,
        delivery_minute: int = 30,
        event_callback=None,
    ) -> None:
        super().__init__(data_dir, event_callback=event_callback)
        self.db_path = Path(db_path)
        self.chat_id = chat_id
        self.enabled = enabled
        self.delivery_hour = delivery_hour
        self.delivery_minute = delivery_minute

    def should_run(self) -> bool:
        """Check if briefing should be sent (time window + dedup)."""
        now = datetime.now()

        # Check time window (within 30 minutes of delivery time)
        target_minutes = self.delivery_hour * 60 + self.delivery_minute
        current_minutes = now.hour * 60 + now.minute
        if abs(current_minutes - target_minutes) > 30:
            return False

        # Dedup: check if already sent today
        state = self.load_state(filename="briefing-state.json")
        last_briefing = state.get("last_briefing_date")
        today = now.strftime("%Y-%m-%d")
        if last_briefing == today:
            return False

        return True

    def compile(self) -> str:
        """Compile briefing from all registered sources."""
        sections = []

        try:
            conn = sqlite3.connect(str(self.db_path))
            conn.row_factory = sqlite3.Row

            for name, source_fn in _SOURCES:
                try:
                    result = source_fn(conn)
                    if result:
                        sections.append(result)
                except Exception as e:
                    log.warning("Briefing source '%s' failed: %s", name, e)

            conn.close()
        except Exception as e:
            log.error("Failed to compile briefing: %s", e)
            return "Good morning! I had trouble compiling today's briefing."

        if not sections:
            return "Good morning! Nothing notable to report today."

        header = f"Good morning! Here's your briefing for {datetime.now().strftime('%A, %B %d')}:\n"
        return header + "\n\n".join(sections)

    def run(self) -> "ServiceResult":
        """Execute the briefing. Returns a ServiceResult (Z2-S0.1)."""
        import time as _time

        from bridge.services.result import ServiceResult

        _start = _time.monotonic()

        if not self.enabled:
            self.record_skipped(
                SkipReason(
                    SkipClass.OPERATOR_DISABLED,
                    "briefing_enabled=False",
                ),
                filename="briefing-state.json",
            )
            return ServiceResult(
                service="briefing",
                ok=True,
                work_items=0,
                duration_ms=int((_time.monotonic() - _start) * 1000),
                cost_usd=0.0,
                skip_reason="briefing_enabled=False",
            )

        if not self.should_run():
            self.record_skipped(
                SkipReason(
                    SkipClass.NOT_DUE,
                    "outside briefing window or already sent today",
                ),
                filename="briefing-state.json",
            )
            return ServiceResult(
                service="briefing",
                ok=True,
                work_items=0,
                duration_ms=int((_time.monotonic() - _start) * 1000),
                cost_usd=0.0,
                skip_reason="outside_window_or_already_sent",
            )

        try:
            message = self.compile()

            # Build context object for ambient awareness
            try:
                from .context_builder import build_context
                ctx = build_context(db_path=self.db_path)
                overdue = len(ctx.get("goals", {}).get("overdue", []))
                if overdue:
                    message += f"\n\n**Escalation**: {overdue} overdue goal(s) — check-in will escalate."
            except Exception as e:
                log.warning("Context build during briefing failed: %s", e)

            self.deliver_message(self.chat_id, message, source="briefing")

            # Update state
            state = self.load_state(filename="briefing-state.json")
            state["last_briefing_date"] = datetime.now().strftime("%Y-%m-%d")
            self.save_state(state, filename="briefing-state.json")

            duration_ms = int((_time.monotonic() - _start) * 1000)
            self.record_success(duration_ms, filename="briefing-state.json")
            log.info("Briefing sent (%d chars, %dms)", len(message), duration_ms)
            return ServiceResult(
                service="briefing",
                ok=True,
                work_items=1,
                duration_ms=duration_ms,
                cost_usd=0.0,
            )

        except Exception as e:
            duration_ms = int((_time.monotonic() - _start) * 1000)
            self.record_failure(str(e)[:500], filename="briefing-state.json")
            log.error("Briefing failed after %dms: %s", duration_ms, e)
            raise

    @staticmethod
    def get_sources() -> list[str]:
        """Return names of all registered briefing sources."""
        return [name for name, _ in _SOURCES]
