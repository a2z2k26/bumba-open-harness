"""Email digest service — periodic email summaries via Gmail API.

Extends ServiceBase. Runs every 2 hours during active hours (9am-10pm).
Gathers unread counts per account, compiles digest with top unread messages.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime
from pathlib import Path

from .base import ServiceBase, SkipClass, SkipReason

log = logging.getLogger(__name__)

# Email categories based on labels/flags
CATEGORY_URGENT = "urgent"
CATEGORY_ACTIONABLE = "actionable"
CATEGORY_INFO = "informational"


class EmailService(ServiceBase):
    """Periodic email digest service."""

    # Accounts to check (agent = own, personal/workspace = delegated read-only)
    ACCOUNTS = ["agent", "personal", "workspace"]

    def __init__(
        self,
        data_dir: str | Path,
        chat_id: str,
        *,
        event_callback=None,
        active_hours_start: int = 9,
        active_hours_end: int = 22,
        digest_interval: int = 7200,  # 2 hours
    ) -> None:
        super().__init__(data_dir, event_callback=event_callback)
        self.chat_id = chat_id
        self.active_hours_start = active_hours_start
        self.active_hours_end = active_hours_end
        self.digest_interval = digest_interval

    def should_run(self) -> bool:
        """Check guards: active hours and digest interval."""
        now = datetime.now()
        if not (self.active_hours_start <= now.hour < self.active_hours_end):
            return False

        state = self.load_state(filename="email-state.json")
        last_check = state.get("last_check_time", 0)
        if time.time() - last_check < self.digest_interval:
            return False

        return True

    def _categorize(self, msg: dict) -> str:
        """Categorize an email message."""
        labels = msg.get("labels", [])
        if "STARRED" in labels or "IMPORTANT" in labels:
            return CATEGORY_URGENT
        subject = msg.get("subject", "").lower()
        if any(word in subject for word in ["urgent", "action required", "asap", "deadline"]):
            return CATEGORY_URGENT
        if any(word in subject for word in ["please", "review", "approve", "confirm", "reply"]):
            return CATEGORY_ACTIONABLE
        return CATEGORY_INFO

    def compile(self) -> str | None:
        """Compile email digest from all accounts. Returns None if no new mail."""
        try:
            from .gmail_interface import get_unread_count, get_unread_messages
        except ImportError:
            log.error("Gmail interface not available")
            return None

        state = self.load_state(filename="email-state.json")
        last_count = state.get("last_digest_count", 0)

        sections = []
        total_unread = 0

        for account in self.ACCOUNTS:
            count = get_unread_count(account)
            if count == 0:
                continue

            total_unread += count
            messages = get_unread_messages(account, limit=5)
            if not messages:
                continue

            # Categorize messages
            urgent = []
            actionable = []
            info = []

            for msg in messages:
                cat = self._categorize(msg)
                entry = f"  - **{msg.get('from_addr', '?')}**: {msg.get('subject', '(no subject)')}"
                if cat == CATEGORY_URGENT:
                    urgent.append(entry)
                elif cat == CATEGORY_ACTIONABLE:
                    actionable.append(entry)
                else:
                    info.append(entry)

            account_section = f"**{account.title()} ({count} unread)**"
            if urgent:
                account_section += "\n  Urgent:\n" + "\n".join(urgent)
            if actionable:
                account_section += "\n  Actionable:\n" + "\n".join(actionable)
            if info:
                account_section += "\n  Info:\n" + "\n".join(info)

            sections.append(account_section)

        # Skip if no new mail since last digest
        if total_unread == 0:
            return None
        if total_unread == last_count:
            return None

        header = f"**Email Digest** ({total_unread} unread total)\n"
        return header + "\n\n".join(sections)

    def run(self) -> "ServiceResult":
        """Execute email digest (Z2-S0.1)."""
        from bridge.services.result import ServiceResult

        _start = time.monotonic()

        if not self.should_run():
            self.record_skipped(
                SkipReason(
                    SkipClass.NOT_DUE,
                    "outside active hours or within digest interval",
                ),
                filename="email-state.json",
            )
            return ServiceResult(
                service="email",
                ok=True,
                work_items=0,
                duration_ms=int((time.monotonic() - _start) * 1000),
                cost_usd=0.0,
                skip_reason="outside_active_hours_or_interval",
            )

        try:
            return self._run_inner(_start)
        except Exception as e:
            duration_ms = int((time.monotonic() - _start) * 1000)
            self.record_failure(str(e)[:500], filename="email-state.json")
            log.error("Email service failed after %dms: %s", duration_ms, e)
            raise

    def _run_inner(self, _start: float) -> "ServiceResult":
        """Inner run logic, separated for error tracking."""
        from bridge.services.result import ServiceResult

        digest = self.compile()

        # Update state regardless
        state = self.load_state(filename="email-state.json")
        state["last_check_time"] = time.time()

        if digest is None:
            self.save_state(state, filename="email-state.json")
            log.info("Email digest skipped: no new mail")
            self.record_skipped(
                SkipReason(
                    SkipClass.NOTHING_TO_DO,
                    "no new mail since last digest",
                ),
                filename="email-state.json",
            )
            return ServiceResult(
                service="email",
                ok=True,
                work_items=0,
                duration_ms=int((time.monotonic() - _start) * 1000),
                cost_usd=0.0,
                skip_reason="no_new_mail",
            )

        # Count total for dedup
        try:
            from .gmail_interface import get_unread_count
            total = sum(get_unread_count(a) for a in self.ACCOUNTS)
            state["last_digest_count"] = total
        except ImportError:
            total = 0
            state["last_digest_count"] = 0

        self.save_state(state, filename="email-state.json")

        self.deliver_message(self.chat_id, digest, source="email-digest")

        # Update context object inbox section
        try:
            from .context_builder import update_section
            from .gmail_interface import get_unread_messages
            urgent = sum(1 for a in self.ACCOUNTS for m in (get_unread_messages(a, limit=5) or [])
                         if self._categorize(m) == CATEGORY_URGENT)
            update_section("inbox", {
                "unread_total": total,
                "unread_urgent": urgent,
                "last_check": datetime.now().isoformat(),
            })
        except Exception:
            pass

        duration_ms = int((time.monotonic() - _start) * 1000)
        self.record_success(duration_ms, filename="email-state.json")
        log.info("Email digest sent (%dms)", duration_ms)
        return ServiceResult(
            service="email",
            ok=True,
            work_items=total,
            duration_ms=duration_ms,
            cost_usd=0.0,
        )
