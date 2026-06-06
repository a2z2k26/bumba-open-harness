"""Weekly review service.

Runs Sunday at ~6:00 PM (configurable). Trend/pattern analysis across 7 days.
Distinct from:
- Morning briefing: no schedule, no single-day recap
- EOD retro: no day-level granularity, broader arcs and health signals

Data sources (direct SQLite, no Claude needed):
- 7-day activity volume and patterns (messages, sessions, voice vs. text)
- Goal lifecycle over the week (completed, opened, overdue, abandoned)
- Knowledge base growth rate and health
- Service reliability (error rates per service across the week)
- System health summary (uptime indicators, error trends)
"""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Callable

from .base import ServiceBase

log = logging.getLogger(__name__)

_SOURCES: list[tuple[str, Callable]] = []


def register_source(name: str):
    def decorator(func: Callable):
        _SOURCES.append((name, func))
        return func
    return decorator


@register_source("Week at a Glance")
def _week_at_a_glance(conn: sqlite3.Connection) -> str | None:
    """High-level activity volume for the past 7 days."""
    row = conn.execute(
        """SELECT COUNT(*) FROM conversations
           WHERE created_at > datetime('now', '-7 days')"""
    ).fetchone()
    total_msgs = row[0] if row else 0

    row = conn.execute(
        """SELECT COUNT(*) FROM conversations
           WHERE created_at > datetime('now', '-7 days') AND role = 'user'"""
    ).fetchone()
    user_msgs = row[0] if row else 0

    row = conn.execute(
        """SELECT COUNT(DISTINCT session_id) FROM conversations
           WHERE created_at > datetime('now', '-7 days')"""
    ).fetchone()
    sessions = row[0] if row else 0

    row = conn.execute(
        """SELECT COUNT(DISTINCT date(created_at)) FROM conversations
           WHERE created_at > datetime('now', '-7 days') AND role = 'user'"""
    ).fetchone()
    active_days = row[0] if row else 0

    if total_msgs == 0:
        return "**Week at a Glance**: No conversations this week"

    lines = [
        f"**Week at a Glance** ({active_days}/7 active days)",
        f"  - {user_msgs} messages across {sessions} sessions",
    ]

    # Day-by-day breakdown
    rows = conn.execute(
        """SELECT date(created_at) as day, COUNT(*) as cnt
           FROM conversations
           WHERE created_at > datetime('now', '-7 days') AND role = 'user'
           GROUP BY day
           ORDER BY day"""
    ).fetchall()

    if rows:
        day_summary = ", ".join(
            f"{row[0][5:]}({row[1]})" for row in rows  # MM-DD(count)
        )
        lines.append(f"  - By day: {day_summary}")

    return "\n".join(lines)


@register_source("Goals This Week")
def _goals_this_week(conn: sqlite3.Connection) -> str | None:
    """Goal lifecycle over the past 7 days."""
    # Goals completed this week (archived with completed marker)
    row = conn.execute(
        """SELECT COUNT(*) FROM knowledge
           WHERE key LIKE 'goal:%'
           AND archived = 1
           AND updated_at > datetime('now', '-7 days')"""
    ).fetchone()
    completed = row[0] if row else 0

    # Goals opened this week
    row = conn.execute(
        """SELECT COUNT(*) FROM knowledge
           WHERE key LIKE 'goal:%'
           AND created_at > datetime('now', '-7 days')
           AND (archived IS NULL OR archived = 0)"""
    ).fetchone()
    opened = row[0] if row else 0

    # Goals currently overdue
    rows = conn.execute(
        """SELECT value FROM knowledge
           WHERE key LIKE 'goal:%'
           AND (archived IS NULL OR archived = 0)"""
    ).fetchall()

    now = datetime.now()
    overdue_count = 0
    for row in rows:
        try:
            data = json.loads(row[0])
            deadline_str = data.get("deadline")
            if deadline_str:
                deadline = datetime.fromisoformat(deadline_str)
                if deadline < now:
                    overdue_count += 1
        except (json.JSONDecodeError, ValueError):
            pass

    if completed == 0 and opened == 0 and overdue_count == 0:
        return None

    lines = ["**Goals This Week**"]
    if completed:
        lines.append(f"  - {completed} completed")
    if opened:
        lines.append(f"  - {opened} new goal(s) opened")
    if overdue_count:
        lines.append(f"  - {overdue_count} currently overdue — attention needed")

    return "\n".join(lines)


@register_source("Knowledge Base Growth")
def _knowledge_growth(conn: sqlite3.Connection) -> str | None:
    """Knowledge base health and growth this week."""
    row = conn.execute(
        """SELECT COUNT(*) FROM knowledge
           WHERE created_at > datetime('now', '-7 days')
           AND (archived IS NULL OR archived = 0)"""
    ).fetchone()
    new_entries = row[0] if row else 0

    row = conn.execute(
        """SELECT COUNT(*) FROM knowledge
           WHERE archived = 1
           AND updated_at > datetime('now', '-7 days')"""
    ).fetchone()
    archived = row[0] if row else 0

    row = conn.execute(
        """SELECT COUNT(*) FROM knowledge
           WHERE archived IS NULL OR archived = 0"""
    ).fetchone()
    total_active = row[0] if row else 0

    if new_entries == 0 and archived == 0:
        return f"**Knowledge Base**: {total_active} active entries, no changes this week"

    lines = [f"**Knowledge Base** ({total_active} active entries)"]
    if new_entries:
        lines.append(f"  - {new_entries} new entries added")
    if archived:
        lines.append(f"  - {archived} entries archived (salience decay)")

    return "\n".join(lines)


@register_source("System Reliability")
def _system_reliability(conn: sqlite3.Connection) -> str | None:
    """Error rates and system health signals for the week."""
    row = conn.execute(
        """SELECT COUNT(*) FROM audit_log
           WHERE event_type LIKE '%error%'
           AND timestamp > datetime('now', '-7 days')"""
    ).fetchone()
    errors_week = row[0] if row else 0

    row = conn.execute(
        """SELECT COUNT(*) FROM audit_log
           WHERE event_type LIKE '%error%'
           AND timestamp > datetime('now', '-24 hours')"""
    ).fetchone()
    errors_today = row[0] if row else 0

    # Session error counts
    row = conn.execute(
        """SELECT COUNT(*) FROM sessions
           WHERE error_count > 0
           AND started_at > datetime('now', '-7 days')"""
    ).fetchone()
    error_sessions = row[0] if row else 0

    row = conn.execute(
        """SELECT COUNT(*) FROM sessions
           WHERE started_at > datetime('now', '-7 days')"""
    ).fetchone()
    total_sessions = row[0] if row else 0

    lines = ["**System Reliability**"]

    if errors_week == 0:
        lines.append("  - Zero errors logged this week")
    else:
        lines.append(f"  - {errors_week} errors this week ({errors_today} in last 24h)")

    if total_sessions > 0:
        error_rate = int((error_sessions / total_sessions) * 100)
        lines.append(f"  - {total_sessions} sessions, {error_rate}% had errors")

    return "\n".join(lines)


@register_source("Patterns & Observations")
def _patterns(conn: sqlite3.Connection) -> str | None:
    """Light pattern detection — busiest day, peak hours."""
    # Busiest day of the week
    rows = conn.execute(
        """SELECT strftime('%w', created_at) as dow,
                  strftime('%A', created_at) as day_name,
                  COUNT(*) as cnt
           FROM conversations
           WHERE created_at > datetime('now', '-7 days') AND role = 'user'
           GROUP BY dow
           ORDER BY cnt DESC
           LIMIT 1"""
    ).fetchone()

    if not rows or rows[2] == 0:
        return None

    lines = ["**Patterns**"]
    lines.append(f"  - Busiest day: {rows[1]} ({rows[2]} messages)")

    # Peak hour
    row = conn.execute(
        """SELECT strftime('%H', created_at) as hr, COUNT(*) as cnt
           FROM conversations
           WHERE created_at > datetime('now', '-7 days') AND role = 'user'
           GROUP BY hr
           ORDER BY cnt DESC
           LIMIT 1"""
    ).fetchone()

    if row and row[1] > 0:
        hour = int(row[0])
        ampm = "AM" if hour < 12 else "PM"
        hour_12 = hour if hour <= 12 else hour - 12
        hour_12 = 12 if hour_12 == 0 else hour_12
        lines.append(f"  - Peak hour: {hour_12}:00 {ampm}")

    return "\n".join(lines)


class WeeklyReviewService(ServiceBase):
    """Weekly review service — Sunday EOD trend analysis."""

    def __init__(
        self,
        data_dir: str | Path,
        db_path: str | Path,
        chat_id: str,
        *,
        event_callback=None,
        delivery_weekday: int = 6,   # 0=Monday … 6=Sunday
        delivery_hour: int = 18,
        delivery_minute: int = 0,
    ) -> None:
        super().__init__(data_dir, event_callback=event_callback)
        self.db_path = Path(db_path)
        self.chat_id = chat_id
        self.delivery_weekday = delivery_weekday
        self.delivery_hour = delivery_hour
        self.delivery_minute = delivery_minute

    def should_run(self) -> bool:
        """Check if weekly review should run (right day, right time, once-per-week dedup)."""
        now = datetime.now()

        # Day of week check (0=Monday, 6=Sunday in Python)
        if now.weekday() != self.delivery_weekday:
            return False

        # Time window check
        target_minutes = self.delivery_hour * 60 + self.delivery_minute
        current_minutes = now.hour * 60 + now.minute
        if abs(current_minutes - target_minutes) > 30:
            return False

        # Once-per-week dedup: check ISO week number
        state = self.load_state(filename="weekly-review-state.json")
        last_week = state.get("last_review_week")
        current_week = now.strftime("%Y-W%W")
        if last_week == current_week:
            return False

        return True

    def compile(self) -> str:
        """Compile weekly review from all registered sources."""
        sections = []
        week_label = datetime.now().strftime("Week of %B %d")

        try:
            conn = sqlite3.connect(str(self.db_path))
            conn.row_factory = sqlite3.Row

            for name, source_fn in _SOURCES:
                try:
                    result = source_fn(conn)
                    if result:
                        sections.append(result)
                except Exception as e:
                    log.warning("Weekly review source '%s' failed: %s", name, e)

            conn.close()
        except Exception as e:
            log.error("Failed to compile weekly review: %s", e)
            return f"Weekly review ({week_label}): couldn't compile data."

        if not sections:
            return f"**Weekly Review — {week_label}**\nQuiet week — nothing notable to report."

        header = f"**Weekly Review — {week_label}**\n"
        return header + "\n\n".join(sections)

    def run(self) -> "ServiceResult":
        """Execute the weekly review (Z2-S0.1)."""
        import time as _time

        from bridge.services.result import ServiceResult

        _start = _time.monotonic()

        if not self.should_run():
            return ServiceResult(
                service="weekly_review",
                ok=True,
                work_items=0,
                duration_ms=int((_time.monotonic() - _start) * 1000),
                cost_usd=0.0,
                skip_reason="wrong_day_or_already_ran_this_week",
            )

        try:
            message = self.compile()
            self.deliver_message(self.chat_id, message, source="weekly_review")

            state = self.load_state(filename="weekly-review-state.json")
            state["last_review_week"] = datetime.now().strftime("%Y-W%W")
            self.save_state(state, filename="weekly-review-state.json")

            duration_ms = int((_time.monotonic() - _start) * 1000)
            self.record_success(duration_ms, filename="weekly-review-state.json")
            log.info("Weekly review sent (%d chars, %dms)", len(message), duration_ms)
            return ServiceResult(
                service="weekly_review",
                ok=True,
                work_items=1,
                duration_ms=duration_ms,
                cost_usd=0.0,
            )

        except Exception as e:
            duration_ms = int((_time.monotonic() - _start) * 1000)
            self.record_failure(str(e)[:500], filename="weekly-review-state.json")
            log.error("Weekly review failed after %dms: %s", duration_ms, e)
            raise

    @staticmethod
    def get_sources() -> list[str]:
        return [name for name, _ in _SOURCES]
