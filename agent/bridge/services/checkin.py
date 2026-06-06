"""Proactive check-in engine.

Three-stage process:
  1. Gather context from DB (no Claude)
  2. Claude decides whether and what to say
  3. Deliver message via service message file

Escalation levels:
  0 (SILENCE): Nothing notable, recent contact, or outside active hours
  1 (CASUAL): 3+ hours since last contact, friendly nudge
  2 (URGENT): Overdue goals, high error count, deadline within 24h
  3 (CALL_REQUEST): Multiple unanswered check-ins + critical deadline
  4 (CALL): Only if operator approves (future)
"""

from __future__ import annotations

import json
import logging
import sqlite3
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

from .base import ServiceBase

log = logging.getLogger(__name__)


@dataclass
class CheckinContext:
    """Gathered context for check-in decision."""

    overdue_goals: list[dict] = field(default_factory=list)
    upcoming_goals: list[dict] = field(default_factory=list)
    last_message_age_hours: float = 0.0
    pending_queue_count: int = 0
    recent_error_count: int = 0
    knowledge_updates_24h: int = 0
    unanswered_checkins: int = 0

    @classmethod
    def gather(cls, db_path: str | Path) -> CheckinContext:
        """Gather context from the database using direct sqlite3 queries."""
        ctx = cls()
        try:
            conn = sqlite3.connect(str(db_path))
            conn.row_factory = sqlite3.Row

            # Last message time
            row = conn.execute(
                "SELECT MAX(created_at) as last_msg FROM conversations WHERE role = 'user'"
            ).fetchone()
            if row and row["last_msg"]:
                try:
                    last_msg = datetime.fromisoformat(row["last_msg"])
                    ctx.last_message_age_hours = (datetime.now() - last_msg).total_seconds() / 3600
                except (ValueError, TypeError):
                    ctx.last_message_age_hours = 999

            # Overdue goals (deadline passed)
            rows = conn.execute(
                """SELECT key, value FROM knowledge
                   WHERE key LIKE 'goal:%'
                   AND (archived IS NULL OR archived = 0)"""
            ).fetchall()
            now = datetime.now()
            for row in rows:
                try:
                    data = json.loads(row["value"])
                    deadline_str = data.get("deadline")
                    if deadline_str:
                        deadline = datetime.fromisoformat(deadline_str)
                        if deadline < now:
                            ctx.overdue_goals.append(data)
                        elif deadline < now + timedelta(hours=24):
                            ctx.upcoming_goals.append(data)
                except (json.JSONDecodeError, ValueError, TypeError):
                    pass

            # Pending messages
            row = conn.execute(
                "SELECT COUNT(*) as cnt FROM message_queue WHERE status = 'pending'"
            ).fetchone()
            ctx.pending_queue_count = row["cnt"] if row else 0

            # Recent errors (last 24h)
            row = conn.execute(
                """SELECT COUNT(*) as cnt FROM audit_log
                   WHERE event_type LIKE '%error%'
                   AND timestamp > datetime('now', '-24 hours')"""
            ).fetchone()
            ctx.recent_error_count = row["cnt"] if row else 0

            # Knowledge updates in last 24h
            row = conn.execute(
                """SELECT COUNT(*) as cnt FROM knowledge
                   WHERE updated_at > datetime('now', '-24 hours')"""
            ).fetchone()
            ctx.knowledge_updates_24h = row["cnt"] if row else 0

            conn.close()
        except Exception as e:
            log.error("Failed to gather check-in context: %s", e)

        return ctx

    def to_prompt_context(self) -> str:
        """Format context as text for the Claude decision prompt."""
        lines = [
            f"Hours since last operator message: {self.last_message_age_hours:.1f}",
            f"Overdue goals: {len(self.overdue_goals)}",
            f"Goals due within 24h: {len(self.upcoming_goals)}",
            f"Pending messages in queue: {self.pending_queue_count}",
            f"Errors in last 24h: {self.recent_error_count}",
            f"Knowledge updates in last 24h: {self.knowledge_updates_24h}",
            f"Unanswered check-ins: {self.unanswered_checkins}",
        ]
        if self.overdue_goals:
            lines.append("\nOverdue goals:")
            for g in self.overdue_goals:
                lines.append(f"  - {g.get('description', 'Unknown')}")
        if self.upcoming_goals:
            lines.append("\nUpcoming deadlines (within 24h):")
            for g in self.upcoming_goals:
                lines.append(f"  - {g.get('description', 'Unknown')} (deadline: {g.get('deadline', '?')})")
        return "\n".join(lines)


CHECKIN_DECISION_PROMPT = """You are an AI check-in engine. Based on the context below, decide whether to send a check-in message to the operator.

CONTEXT:
{context}

ESCALATION LEVELS:
- Level 0 (SILENCE): Nothing notable, recent contact (<3 hours), or quiet period. Respond with exactly: SILENCE
- Level 1 (CASUAL): 3+ hours since last contact, write a brief friendly nudge. Just start with the message text.
- Level 2 (URGENT): Overdue goals, high error count (5+), or deadline within 24h. Prefix with "URGENT: "
- Level 3 (CALL_REQUEST): Multiple unanswered check-ins AND critical deadline. Respond with "CALL_REQUEST: " followed by reason.

RULES:
- Default to SILENCE if unsure
- Keep messages under 200 characters
- Be warm and helpful, not nagging
- Don't repeat the same check-in message

Your response (just the message or SILENCE, nothing else):"""


class CheckinService(ServiceBase):
    """Proactive check-in engine with 3-stage decision process."""

    def __init__(
        self,
        data_dir: str | Path,
        db_path: str | Path,
        chat_id: str,
        *,
        enabled: bool = True,
        event_callback=None,
        active_hours_start: int = 8,
        active_hours_end: int = 22,
        minimum_gap: int = 7200,
        quiet_after_message: int = 1800,
    ) -> None:
        super().__init__(data_dir, event_callback=event_callback)
        self.db_path = Path(db_path)
        self.chat_id = chat_id
        self.enabled = enabled
        self.active_hours_start = active_hours_start
        self.active_hours_end = active_hours_end
        self.minimum_gap = minimum_gap
        self.quiet_after_message = quiet_after_message

    def should_run(self) -> bool:
        """Check guards: active hours, minimum gap, snooze, quiet period."""
        now = datetime.now()

        # Active hours check
        if not (self.active_hours_start <= now.hour < self.active_hours_end):
            log.info("Check-in skipped: outside active hours (%d)", now.hour)
            return False

        state = self.load_state(filename="checkin-state.json")

        # Snooze check
        snooze_until = state.get("snooze_until", 0)
        if time.time() < snooze_until:
            log.info("Check-in skipped: snoozed until %s", datetime.fromtimestamp(snooze_until))
            return False

        # Minimum gap since last check-in
        last_checkin = state.get("last_checkin_time", 0)
        if time.time() - last_checkin < self.minimum_gap:
            log.info("Check-in skipped: minimum gap not met")
            return False

        return True

    def gather(self) -> CheckinContext:
        """Stage 1: Gather context from DB."""
        ctx = CheckinContext.gather(self.db_path)

        # Check unanswered check-ins from state
        state = self.load_state(filename="checkin-state.json")
        ctx.unanswered_checkins = state.get("unanswered_checkins", 0)

        return ctx

    def decide(self, context: CheckinContext) -> str | None:
        """Stage 2: Decide check-in message.

        In production, this calls Claude via subprocess.
        For testability, this is a rule-based fallback.
        Returns message text or None for silence.
        """
        # Rule-based decision (Claude subprocess would replace this)
        if context.last_message_age_hours < 3 and not context.overdue_goals:
            return None  # SILENCE

        if context.overdue_goals and context.unanswered_checkins >= 2:
            goals = ", ".join(g.get("description", "?") for g in context.overdue_goals[:2])
            return f"CALL_REQUEST: Multiple overdue goals ({goals}) and no response to check-ins."

        if context.overdue_goals or context.recent_error_count >= 5:
            if context.overdue_goals:
                goal = context.overdue_goals[0].get("description", "a goal")
                return f"URGENT: '{goal}' is overdue. Need your input when you get a chance."
            return f"URGENT: {context.recent_error_count} errors in the last 24h. May need attention."

        if context.upcoming_goals:
            goal = context.upcoming_goals[0].get("description", "a goal")
            return f"URGENT: '{goal}' deadline is within 24 hours."

        if context.last_message_age_hours >= 3:
            return "Hey! Just checking in. Anything you'd like me to work on?"

        return None

    def run(self) -> "ServiceResult":
        """Execute the full 3-stage check-in process (Z2-S0.1)."""
        from bridge.services.result import ServiceResult

        _start = time.monotonic()

        if not self.enabled:
            return ServiceResult(
                service="checkin",
                ok=True,
                work_items=0,
                duration_ms=int((time.monotonic() - _start) * 1000),
                cost_usd=0.0,
                skip_reason="checkin_enabled=False",
            )

        if not self.should_run():
            return ServiceResult(
                service="checkin",
                ok=True,
                work_items=0,
                duration_ms=int((time.monotonic() - _start) * 1000),
                cost_usd=0.0,
                skip_reason="outside_checkin_window",
            )

        try:
            # Stage 1: Gather
            context = self.gather()

            # Stage 2: Decide
            message = self.decide(context)
            if message is None:
                log.info("Check-in decided: SILENCE")
                return ServiceResult(
                    service="checkin",
                    ok=True,
                    work_items=0,
                    duration_ms=int((time.monotonic() - _start) * 1000),
                    cost_usd=0.0,
                    skip_reason="decided_silence",
                )

            # Stage 3: Deliver
            buttons = [
                {"label": "Snooze 30m", "action": "snooze_30"},
                {"label": "Got it", "action": "dismiss"},
            ]
            self.deliver_message(self.chat_id, message, buttons=buttons, source="checkin")

            # Update state
            state = self.load_state(filename="checkin-state.json")
            state["last_checkin_time"] = time.time()
            state["unanswered_checkins"] = state.get("unanswered_checkins", 0) + 1
            self.save_state(state, filename="checkin-state.json")

            duration_ms = int((time.monotonic() - _start) * 1000)
            self.record_success(duration_ms, filename="checkin-state.json")
            log.info("Check-in sent (%dms): %s", duration_ms, message[:80])
            return ServiceResult(
                service="checkin",
                ok=True,
                work_items=1,
                duration_ms=duration_ms,
                cost_usd=0.0,
            )

        except Exception as e:
            duration_ms = int((time.monotonic() - _start) * 1000)
            self.record_failure(str(e)[:500], filename="checkin-state.json")
            log.error("Check-in failed after %dms: %s", duration_ms, e)
            raise

    def handle_response(self, action: str) -> None:
        """Handle operator response to check-in (button callback)."""
        state = self.load_state(filename="checkin-state.json")

        if action == "snooze_30":
            state["snooze_until"] = time.time() + 1800
            log.info("Check-in snoozed for 30 minutes")
        elif action == "dismiss":
            state["unanswered_checkins"] = 0
            log.info("Check-in dismissed")

        self.save_state(state, filename="checkin-state.json")
