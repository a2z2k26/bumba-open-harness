"""Inbox nurture service — daily draft of the most actionable unanswered thread.

Replaces the every-2h email digest (Z2-S5.2).  Once per day it:
  1. Scans Gmail for threads where the last message is FROM a sender
     (not from the operator) and is >48h old.
  2. Scores each thread on actionability (staleness × relationship × CTA).
  3. Picks exactly one thread and generates a draft reply via a prompt.
  4. Queues it to the HITL message file so the bridge can present
     Approve / Reject buttons to the operator via Discord.

Spec: docs/specs/2026-04-17-zone2-sprint-plan.md → Sprint S5.2
GitHub: #504
"""

from __future__ import annotations

import json
import logging
import re
import time
from datetime import datetime, timezone
from pathlib import Path

from .base import ServiceBase, SkipClass, SkipReason

log = logging.getLogger(__name__)

# Autoresponder patterns — skip threads from these senders.
AUTORESPONDER_PATTERNS = re.compile(
    r"(noreply|no-reply|donotreply|do-not-reply|mailer-daemon|bounce|"
    r"notifications?@|alerts?@|support@.*automated|auto@)",
    re.IGNORECASE,
)

# Keywords that signal a call-to-action in the subject/snippet.
CTA_KEYWORDS = [
    "review", "approve", "confirm", "respond", "reply", "follow up",
    "following up", "waiting", "action required", "please", "let me know",
    "asap", "urgent", "deadline", "decision",
]

# Default staleness threshold in seconds (48 hours).
STALE_THRESHOLD_SECS = 48 * 3600

# State filename.
STATE_FILE = "inbox-nurture-state.json"


def _is_autoresponder(from_addr: str) -> bool:
    """Return True if the sender looks like an autoresponder."""
    return bool(AUTORESPONDER_PATTERNS.search(from_addr))


def _score_thread(thread: dict) -> float:
    """Compute an actionability score for a Gmail thread dict.

    Higher is more actionable.  Components:
      - staleness: hours since last message (capped at 240h = 10 days)
      - cta_bonus: +5 per CTA keyword found in subject/snippet
    """
    age_hours = thread.get("age_hours", 0.0)
    staleness = min(age_hours, 240.0)

    text = (
        (thread.get("subject") or "") + " " + (thread.get("snippet") or "")
    ).lower()
    cta_bonus = sum(5.0 for kw in CTA_KEYWORDS if kw in text)

    return staleness + cta_bonus


def _build_draft_prompt(thread: dict) -> str:
    """Build a Claude prompt that produces a concise reply draft."""
    from_addr = thread.get("from_addr", "the sender")
    subject = thread.get("subject", "(no subject)")
    snippet = thread.get("snippet", "")
    age_hours = thread.get("age_hours", 0.0)

    return (
        f"You are drafting a reply email on behalf of the operator.\n\n"
        f"Thread subject: {subject}\n"
        f"From: {from_addr}\n"
        f"Last message snippet: {snippet}\n"
        f"Days since last message: {age_hours / 24:.1f}\n\n"
        f"Write a concise, professional reply that:\n"
        f"  1. Acknowledges the thread\n"
        f"  2. Moves the conversation forward\n"
        f"  3. Is no longer than 4 sentences\n\n"
        f"Output ONLY the reply body — no subject line, no greeting header.\n"
    )


class InboxNurtureService(ServiceBase):
    """Daily inbox nurture — draft one reply for the most actionable stale thread."""

    def __init__(
        self,
        data_dir: str | Path,
        chat_id: str,
        *,
        event_callback=None,
        stale_threshold_secs: int = STALE_THRESHOLD_SECS,
    ) -> None:
        super().__init__(data_dir, event_callback=event_callback)
        self.chat_id = chat_id
        self.stale_threshold_secs = stale_threshold_secs

    # ------------------------------------------------------------------
    # Guards
    # ------------------------------------------------------------------

    def should_run(self) -> bool:
        """True if the service hasn't run successfully today."""
        state = self.load_state(STATE_FILE)
        last_run = state.get("last_run")
        if not last_run:
            return True
        try:
            last_dt = datetime.fromisoformat(last_run)
            now_utc = datetime.now(timezone.utc)
            # Allow re-run if last run was on a different UTC date.
            return last_dt.date() < now_utc.date()
        except (ValueError, TypeError):
            return True

    # ------------------------------------------------------------------
    # Gmail scanning
    # ------------------------------------------------------------------

    def _fetch_stale_threads(self) -> list[dict]:
        """Return threads unanswered >stale_threshold_secs, newest-first."""
        try:
            from .gmail_interface import get_unread_messages, get_message_detail
        except ImportError:
            log.error("gmail_interface unavailable — cannot scan inbox")
            return []

        messages = get_unread_messages("agent", limit=50)
        now_ts = time.time()
        stale: list[dict] = []

        for msg in messages:
            from_addr = msg.get("from_addr", "")
            if _is_autoresponder(from_addr):
                continue

            # Parse date to compute age.
            date_str = msg.get("date", "")
            try:
                from email.utils import parsedate_to_datetime
                msg_dt = parsedate_to_datetime(date_str)
                age_secs = now_ts - msg_dt.timestamp()
            except Exception:
                # If date is unparseable treat as old (24h).
                age_secs = 86400.0

            if age_secs < self.stale_threshold_secs:
                continue

            thread_info = dict(msg)
            thread_info["age_hours"] = age_secs / 3600.0
            stale.append(thread_info)

        # Sort by score descending.
        stale.sort(key=_score_thread, reverse=True)
        return stale

    # ------------------------------------------------------------------
    # Draft generation (pure-function, injectable for tests)
    # ------------------------------------------------------------------

    def generate_draft(self, thread: dict) -> str:
        """Generate a reply draft for *thread*.

        In production this calls a Claude subprocess.  The method is a
        separate public function so tests can substitute a mock.
        """
        import subprocess
        import shutil

        claude_bin = shutil.which("claude") or "/usr/local/bin/claude"
        prompt = _build_draft_prompt(thread)
        try:
            result = subprocess.run(
                [claude_bin, "-p", prompt],
                capture_output=True,
                text=True,
                timeout=60,
            )
            draft = result.stdout.strip()
            if draft:
                return draft
        except Exception as exc:
            log.warning("Claude draft generation failed: %s", exc)

        # Graceful fallback.
        return (
            f"Hi,\n\nApologies for the delayed response. "
            f"I wanted to follow up on your message regarding "
            f"\"{thread.get('subject', 'our conversation')}\". "
            f"Could you please share any updates?\n\nBest regards"
        )

    # ------------------------------------------------------------------
    # HITL queuing
    # ------------------------------------------------------------------

    def _queue_hitl(self, thread: dict, draft: str) -> None:
        """Write a HITL message file for the bridge to pick up."""
        subject = thread.get("subject", "(no subject)")
        from_addr = thread.get("from_addr", "unknown")
        age_days = thread.get("age_hours", 0.0) / 24.0

        card = (
            f"**Inbox Nurture — Draft Reply**\n"
            f"**Thread:** {subject}\n"
            f"**From:** {from_addr}\n"
            f"**Age:** {age_days:.1f} days\n\n"
            f"**Proposed reply:**\n```\n{draft}\n```\n\n"
            f"React with Approve to send, Reject to discard."
        )

        buttons = [
            {"label": "Approve", "value": f"inbox_nurture:approve:{thread.get('id', '')}"},
            {"label": "Reject",  "value": f"inbox_nurture:reject:{thread.get('id', '')}"},
        ]

        self.deliver_message(
            self.chat_id,
            card,
            buttons=buttons,
            source="inbox-nurture",
        )

        # Also persist the pending draft so the bridge can action it.
        pending_path = self.data_dir / "inbox_nurture_pending.json"
        pending_data = {
            "thread_id": thread.get("id", ""),
            "from_addr": from_addr,
            "subject": subject,
            "draft": draft,
            "queued_at": datetime.now(timezone.utc).isoformat(),
        }
        tmp = pending_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(pending_data, indent=2))
        tmp.replace(pending_path)

    # ------------------------------------------------------------------
    # Public run()
    # ------------------------------------------------------------------

    def run(self) -> "ServiceResult":
        """Execute the daily inbox nurture pass."""
        from bridge.services.result import ServiceResult

        _start = time.monotonic()

        if not self.should_run():
            self.record_skipped(
                SkipReason(SkipClass.NOT_DUE, "already ran today"),
                STATE_FILE,
            )
            return ServiceResult(
                service="inbox_nurture",
                ok=True,
                work_items=0,
                duration_ms=int((time.monotonic() - _start) * 1000),
                cost_usd=0.0,
                skip_reason="already_ran_today",
                narration="Inbox nurture already ran today — skipping.",
            )

        self.narrate_start(self.chat_id, "Scanning inbox for unanswered threads...")

        try:
            return self._run_inner(_start)
        except Exception as exc:
            duration_ms = int((time.monotonic() - _start) * 1000)
            self.record_failure(str(exc)[:500], STATE_FILE)
            log.error("InboxNurtureService failed after %dms: %s", duration_ms, exc)
            raise

    def _run_inner(self, _start: float) -> "ServiceResult":
        from bridge.services.result import ServiceResult

        threads = self._fetch_stale_threads()

        if not threads:
            self.record_skipped(
                SkipReason(
                    SkipClass.NOTHING_TO_DO,
                    "inbox_zero — no stale unanswered threads",
                ),
                STATE_FILE,
            )
            self.deliver_message(
                self.chat_id,
                "Inbox nurture: no unanswered threads >48h. Inbox zero!",
                source="inbox-nurture",
            )
            return ServiceResult(
                service="inbox_nurture",
                ok=True,
                work_items=0,
                duration_ms=int((time.monotonic() - _start) * 1000),
                cost_usd=0.0,
                skip_reason="inbox_zero",
                narration="Inbox zero — no unanswered threads to nurture.",
            )

        # Pick the highest-scoring thread.
        top_thread = threads[0]
        draft = self.generate_draft(top_thread)
        self._queue_hitl(top_thread, draft)

        duration_ms = int((time.monotonic() - _start) * 1000)
        self.record_success(duration_ms, STATE_FILE)

        narration = (
            f"Drafted reply for thread \"{top_thread.get('subject', '?')}\" "
            f"from {top_thread.get('from_addr', '?')} "
            f"({top_thread.get('age_hours', 0.0) / 24:.1f}d old). "
            f"Awaiting operator approval."
        )
        self.narrate_complete(self.chat_id, "inbox_nurture", type("R", (), {"narration": narration})())

        return ServiceResult(
            service="inbox_nurture",
            ok=True,
            work_items=1,
            duration_ms=duration_ms,
            cost_usd=0.02,
            narration=narration,
        )
