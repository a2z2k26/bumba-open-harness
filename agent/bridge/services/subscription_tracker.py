"""Subscription tracker service — discover and surface recurring charges.

Scans Gmail for subscription-related emails, maintains
``data/subscriptions.json`` as the authoritative registry, posts a weekly
Discord summary on Sundays at 17:00, and fires 7-day / 1-day renewal
warnings for upcoming charges.

Spec: docs/specs/2026-04-17-zone2-sprint-plan.md → Sprint S5.3
GitHub: #505
"""

from __future__ import annotations

import json
import logging
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import TypedDict

from .base import ServiceBase

log = logging.getLogger(__name__)

SUBSCRIPTIONS_FILE = "subscriptions.json"
STATE_FILE = "subscription-tracker-state.json"

# Dollar threshold above which a subscription is flagged cancellable by default.
HIGH_COST_THRESHOLD_USD = 50.0

# Regex patterns for subscription-related email subjects.
RENEWAL_PATTERNS = [
    re.compile(r"renew", re.IGNORECASE),
    re.compile(r"next charge", re.IGNORECASE),
    re.compile(r"subscription confirmed", re.IGNORECASE),
    re.compile(r"billing reminder", re.IGNORECASE),
    re.compile(r"payment receipt", re.IGNORECASE),
    re.compile(r"invoice", re.IGNORECASE),
    re.compile(r"auto.?renew", re.IGNORECASE),
    re.compile(r"your (monthly|annual|yearly) (plan|subscription|membership)", re.IGNORECASE),
    re.compile(r"charged.*\$[\d,.]+", re.IGNORECASE),
]

# Regex to extract dollar amounts from email snippets/subjects.
AMOUNT_PATTERN = re.compile(r"\$\s*([\d,]+(?:\.\d{1,2})?)")

# Regex to loosely detect a date in various formats within text.
DATE_PATTERN = re.compile(
    r"\b(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?"
    r"|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)"
    r"\s+\d{1,2},?\s+\d{4}\b",
    re.IGNORECASE,
)

# Regex to detect a cancellation event.
CANCEL_PATTERNS = [
    re.compile(r"cancel", re.IGNORECASE),
    re.compile(r"unsubscribe", re.IGNORECASE),
    re.compile(r"subscription ended", re.IGNORECASE),
    re.compile(r"refund", re.IGNORECASE),
]

# Module-level import so tests can patch this name. Gracefully absent when
# gmail_interface is not importable (CI, unit-test context).
try:
    from .gmail_interface import get_unread_messages
except ImportError:
    get_unread_messages = None  # type: ignore[assignment]


class Subscription(TypedDict, total=False):
    vendor: str
    amount_usd: float
    renewal_date: str          # ISO date YYYY-MM-DD or empty
    status: str                # "active" | "cancelled"
    last_seen: str             # ISO datetime
    cancellable_flag: bool


def _is_renewal_email(subject: str, snippet: str) -> bool:
    text = (subject + " " + snippet).lower()
    return any(p.search(text) for p in RENEWAL_PATTERNS)


def _is_cancellation_email(subject: str, snippet: str) -> bool:
    text = (subject + " " + snippet).lower()
    return any(p.search(text) for p in CANCEL_PATTERNS)


def _extract_amount(text: str) -> float | None:
    m = AMOUNT_PATTERN.search(text)
    if m:
        try:
            return float(m.group(1).replace(",", ""))
        except ValueError:
            pass
    return None


def _extract_vendor(from_addr: str, subject: str) -> str:
    """Best-effort vendor name from sender address or subject."""
    # Try domain part of email.
    m = re.search(r"@([\w.-]+)", from_addr)
    if m:
        domain = m.group(1)
        # Strip TLD and common prefixes.
        parts = domain.split(".")
        candidates = [p for p in parts if p not in ("com", "net", "org", "io", "co")]
        if candidates:
            return candidates[0].title()
    # Fall back to first word of subject.
    first_word = re.split(r"\W+", subject.strip())[0]
    return first_word.title() if first_word else from_addr


def _extract_renewal_date(text: str) -> str:
    """Return ISO date if found in text, else ''."""
    m = DATE_PATTERN.search(text)
    if m:
        try:
            dt = datetime.strptime(m.group(0).replace(",", ""), "%B %d %Y")
            return dt.date().isoformat()
        except ValueError:
            pass
    return ""


def _days_until(date_str: str) -> int | None:
    """Return days until date_str (ISO), or None if unparseable."""
    if not date_str:
        return None
    try:
        target = datetime.fromisoformat(date_str).date()
        delta = (target - datetime.now(timezone.utc).date()).days
        return delta
    except (ValueError, TypeError):
        return None


class SubscriptionTrackerService(ServiceBase):
    """Discover subscriptions in Gmail and surface renewal alerts."""

    def __init__(
        self,
        data_dir: str | Path,
        chat_id: str,
        *,
        event_callback=None,
    ) -> None:
        super().__init__(data_dir, event_callback=event_callback)
        self.chat_id = chat_id
        self._subs_path = Path(data_dir) / SUBSCRIPTIONS_FILE

    # ------------------------------------------------------------------
    # Registry helpers
    # ------------------------------------------------------------------

    def load_subscriptions(self) -> dict[str, Subscription]:
        """Load subscription registry from data/subscriptions.json."""
        if not self._subs_path.exists():
            return {}
        try:
            return json.loads(self._subs_path.read_text())
        except (json.JSONDecodeError, OSError):
            return {}

    def save_subscriptions(self, subs: dict[str, Subscription]) -> None:
        """Atomically save subscription registry."""
        import os
        import tempfile

        tmp_fd, tmp_path = tempfile.mkstemp(dir=self._subs_path.parent, suffix=".tmp")
        try:
            with os.fdopen(tmp_fd, "w") as f:
                json.dump(subs, f, indent=2, sort_keys=True)
            os.replace(tmp_path, self._subs_path)
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

    # ------------------------------------------------------------------
    # Scanning
    # ------------------------------------------------------------------

    def scan_gmail(self) -> int:
        """Scan Gmail for subscription emails; update the registry.

        Returns the number of subscriptions updated/added.
        """
        import bridge.services.subscription_tracker as _self_mod
        _fetch = _self_mod.get_unread_messages
        if _fetch is None:
            log.error("gmail_interface unavailable — cannot scan")
            return 0

        # Scan a larger window than usual to catch renewal emails.
        messages = _fetch("agent", limit=100)
        subs = self.load_subscriptions()
        updated = 0

        for msg in messages:
            subject = msg.get("subject", "")
            snippet = msg.get("snippet", "")
            from_addr = msg.get("from_addr", "")

            if _is_cancellation_email(subject, snippet):
                vendor = _extract_vendor(from_addr, subject)
                if vendor in subs:
                    subs[vendor]["status"] = "cancelled"
                    subs[vendor]["last_seen"] = datetime.now(timezone.utc).isoformat()
                    updated += 1
                continue

            if not _is_renewal_email(subject, snippet):
                continue

            vendor = _extract_vendor(from_addr, subject)
            amount = _extract_amount(snippet + " " + subject) or (
                subs.get(vendor, {}).get("amount_usd", 0.0)
            )
            renewal_date = _extract_renewal_date(snippet + " " + subject)

            existing: Subscription = subs.get(vendor, {})  # type: ignore[assignment]
            prev_amount = existing.get("amount_usd", 0.0)

            subs[vendor] = Subscription(
                vendor=vendor,
                amount_usd=amount,
                renewal_date=renewal_date or existing.get("renewal_date", ""),
                status="active",
                last_seen=datetime.now(timezone.utc).isoformat(),
                cancellable_flag=(
                    existing.get("cancellable_flag", False)
                    or amount > HIGH_COST_THRESHOLD_USD
                ),
            )

            # Flag a price change in the log.
            if prev_amount and abs(prev_amount - amount) > 0.01:
                log.info(
                    "Subscription price change: %s $%.2f → $%.2f",
                    vendor, prev_amount, amount,
                )
            updated += 1

        if updated:
            self.save_subscriptions(subs)

        return updated

    # ------------------------------------------------------------------
    # Renewal warnings
    # ------------------------------------------------------------------

    def send_renewal_warnings(self) -> int:
        """DM operator for renewals due in 7 or 1 day. Returns count sent."""
        subs = self.load_subscriptions()
        sent = 0

        for vendor, sub in subs.items():
            if sub.get("status") == "cancelled":
                continue
            days = _days_until(sub.get("renewal_date", ""))
            if days is None:
                continue
            if days in (7, 1):
                amount = sub.get("amount_usd", 0.0)
                msg = (
                    f"**Renewal alert — {vendor}**\n"
                    f"Renews in {days} day{'s' if days > 1 else ''} "
                    f"(${amount:.2f}/period).\n"
                    f"Cancel before then if you no longer need it."
                )
                self.deliver_message(self.chat_id, msg, source="subscription-tracker")
                sent += 1

        return sent

    # ------------------------------------------------------------------
    # Weekly summary
    # ------------------------------------------------------------------

    def build_weekly_summary(self) -> str:
        """Build a Discord-friendly weekly subscriptions summary."""
        subs = self.load_subscriptions()
        active = {k: v for k, v in subs.items() if v.get("status") != "cancelled"}

        if not active:
            return "**Subscription Summary** — no active subscriptions found yet."

        total_usd = sum(s.get("amount_usd", 0.0) for s in active.values())
        cancellable = [v for v in active.values() if v.get("cancellable_flag")]

        lines = [
            f"**Subscription Summary** ({len(active)} active, ${total_usd:.2f}/mo total)",
            "```",
        ]
        for vendor, sub in sorted(active.items()):
            amount = sub.get("amount_usd", 0.0)
            renewal = sub.get("renewal_date", "unknown")
            flag = " [consider cancelling]" if sub.get("cancellable_flag") else ""
            lines.append(f"{vendor:<25s} ${amount:>7.2f}   renews {renewal}{flag}")
        lines.append("```")

        if cancellable:
            names = ", ".join(s.get("vendor", "?") for s in cancellable)
            lines.append(f"\n_Consider cancelling: {names}_")

        return "\n".join(lines)

    def should_send_weekly_summary(self) -> bool:
        """True if today is Sunday and the weekly summary hasn't been sent yet today."""
        now = datetime.now(timezone.utc)
        if now.weekday() != 6:  # 6 = Sunday
            return False
        state = self.load_state(STATE_FILE)
        last_weekly = state.get("last_weekly_summary")
        if not last_weekly:
            return True
        try:
            last_dt = datetime.fromisoformat(last_weekly)
            return last_dt.date() < now.date()
        except (ValueError, TypeError):
            return True

    # ------------------------------------------------------------------
    # Public run()
    # ------------------------------------------------------------------

    def run(self) -> "ServiceResult":
        """Daily scan + optional weekly summary + renewal warnings."""

        _start = time.monotonic()

        try:
            return self._run_inner(_start)
        except Exception as exc:
            self.record_failure(str(exc)[:500], STATE_FILE)
            log.error("SubscriptionTrackerService failed: %s", exc)
            raise

    def _run_inner(self, _start: float) -> "ServiceResult":
        from bridge.services.result import ServiceResult

        updated = self.scan_gmail()
        warnings_sent = self.send_renewal_warnings()

        weekly_sent = False
        if self.should_send_weekly_summary():
            summary = self.build_weekly_summary()
            self.deliver_message(self.chat_id, summary, source="subscription-tracker")
            state = self.load_state(STATE_FILE)
            state["last_weekly_summary"] = datetime.now(timezone.utc).isoformat()
            self.save_state(state, STATE_FILE)
            weekly_sent = True

        work_items = updated + warnings_sent + (1 if weekly_sent else 0)
        duration_ms = int((time.monotonic() - _start) * 1000)

        if work_items == 0:
            self.record_skipped("no subscription emails or actions today", STATE_FILE)
            return ServiceResult(
                service="subscription_tracker",
                ok=True,
                work_items=0,
                duration_ms=duration_ms,
                cost_usd=0.0,
                skip_reason="no_actions_today",
                narration="Subscription tracker: nothing new today.",
            )

        self.record_success(duration_ms, STATE_FILE)
        narration = (
            f"Subscription tracker: {updated} updated, "
            f"{warnings_sent} renewal warning(s) sent"
            + (", weekly summary posted." if weekly_sent else ".")
        )
        return ServiceResult(
            service="subscription_tracker",
            ok=True,
            work_items=work_items,
            duration_ms=duration_ms,
            cost_usd=0.0,
            narration=narration,
        )
