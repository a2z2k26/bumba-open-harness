"""Meeting prebrief service (Z2-S4.2 + Z2-S5.1).

Flagship event-driven service: posts a Discord card 30 minutes before every
Cal.com event, giving the operator context to walk into the call prepared.

Two trigger modes:
1. EventBus subscription — ``calcom.booking.created`` / ``calcom.booking.rescheduled``
   schedules a prebrief at T-30min.
2. Poll scan — runs on service startup and on every `run()` call to catch
   missed prebriefs (bridge was down, clock skew, etc.).

Z2-S5.1 Backfill:
   On ``run()`` / startup, scan bookings that started in the last 2 hours.
   If a prebrief was not sent for them, send one now (marked as "Late prebrief").
   This handles bridge restarts during the T-30min window.

Research stubs (S4.2 happy-path, real research deferred to S5.2+):
- Last email thread with attendee — returns None (stub)
- Company research — returns None (stub)
- Talking points — generated from available data via a short Claude subprocess
  call IF available, else omitted

Card format (Discord Markdown)::

    **Meeting in 30 min: <title>**
    When: <start_time>
    Who: <attendee_name> <attendee_email>
    ---
    <research_snippet if any>
    <talking_points if any>
"""

from __future__ import annotations

import json
import logging
import subprocess
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .base import ServiceBase

log = logging.getLogger(__name__)

# How many minutes before the event to fire the prebrief
PREBRIEF_MINUTES = 30
# Tolerance window: send prebrief if we're within ±5 min of T-30min
PREBRIEF_TOLERANCE_MINUTES = 5
# Backfill window: check events that started in the last N hours
BACKFILL_WINDOW_HOURS = 2
# Cap on Claude subprocess call for talking points
CLAUDE_TIMEOUT_SECONDS = 30


def _fmt_dt(iso_str: str) -> str:
    """Format an ISO datetime string to a human-readable local time."""
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        from zoneinfo import ZoneInfo
        est = ZoneInfo("America/New_York")
        return dt.astimezone(est).strftime("%-I:%M %p %Z, %b %d")
    except (ValueError, TypeError):
        return iso_str


def _minutes_until(iso_str: str) -> float | None:
    """Return minutes until the given ISO datetime, or None if unparseable."""
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        delta = (dt - datetime.now(timezone.utc)).total_seconds() / 60.0
        return delta
    except (ValueError, TypeError):
        return None


def _compose_card(
    booking: dict[str, Any],
    *,
    late: bool = False,
    email_snippet: str | None = None,
    company_info: str | None = None,
    talking_points: list[str] | None = None,
) -> str:
    """Compose the Discord prebrief card from booking + research data."""
    title = booking.get("title", "(no title)")
    start = booking.get("start_time") or booking.get("start", "")
    attendee_name = booking.get("attendee_name", "")
    attendee_email = booking.get("attendee_email", "")
    meeting_url = booking.get("meeting_url", "")

    prefix = "**Late prebrief** — " if late else ""
    header = f"{prefix}**Meeting in {PREBRIEF_MINUTES} min: {title}**"

    lines = [header]
    lines.append(f"When: {_fmt_dt(start)}")

    who_parts = [p for p in [attendee_name, attendee_email] if p]
    if who_parts:
        lines.append(f"Who: {' '.join(who_parts)}")

    if meeting_url:
        lines.append(f"Link: {meeting_url}")

    if email_snippet or company_info or talking_points:
        lines.append("---")

    if email_snippet:
        lines.append(f"**Last thread:** {email_snippet}")

    if company_info:
        lines.append(f"**Company:** {company_info}")

    if talking_points:
        lines.append("**Talking points:**")
        for pt in talking_points[:5]:
            lines.append(f"  • {pt}")

    return "\n".join(lines)


def _get_last_email_snippet(attendee_email: str) -> str | None:
    """Stub: look up last email thread with attendee (S5.2+)."""
    # Real implementation would query Gmail interface
    return None


def _get_company_info(attendee_email: str) -> str | None:
    """Stub: look up company info for attendee email domain (S5.2+)."""
    # Real implementation would query Brave search + Pinecone cache
    return None


def _generate_talking_points(
    title: str,
    attendee_name: str,
    email_snippet: str | None,
    company_info: str | None,
) -> list[str] | None:
    """Generate 3-5 talking points via Claude subprocess (best-effort).

    Returns None if the subprocess is unavailable or times out.
    """
    prompt_parts = [
        f"Meeting: {title}",
        f"Attendee: {attendee_name}",
    ]
    if email_snippet:
        prompt_parts.append(f"Last email context: {email_snippet}")
    if company_info:
        prompt_parts.append(f"Company context: {company_info}")

    prompt = (
        "Generate 3-5 concise talking points for this upcoming meeting. "
        "Be specific and actionable. Return them as a JSON array of strings.\n\n"
        + "\n".join(prompt_parts)
    )

    try:
        result = subprocess.run(
            ["claude", "-p", "--output-format", "text", prompt],
            capture_output=True,
            text=True,
            timeout=CLAUDE_TIMEOUT_SECONDS,
        )
        if result.returncode != 0:
            return None
        output = result.stdout.strip()
        # Try to parse as JSON array
        if output.startswith("["):
            points = json.loads(output)
            if isinstance(points, list):
                return [str(p) for p in points[:5]]
        # Fallback: split on newlines
        lines = [ln.lstrip("•- ").strip() for ln in output.splitlines() if ln.strip()]
        return lines[:5] if lines else None
    except (subprocess.TimeoutExpired, FileNotFoundError, json.JSONDecodeError, OSError):
        return None


class MeetingPrebriefService(ServiceBase):
    """Posts a Discord prebrief card 30 minutes before every Cal.com event.

    Args:
        data_dir: Path to the data directory (state, messages).
        chat_id: Discord channel ID for delivery.
        calcom_interface: Module or object exposing ``get_upcoming_bookings()``.
            Defaults to ``bridge.services.calcom_interface``.
        event_callback: Optional event bus callback from ServiceBase.
        prebrief_minutes: How many minutes before the event to fire.
        enable_talking_points: If True, attempt Claude subprocess for talking
            points. Defaults to True.
    """

    def __init__(
        self,
        data_dir: str | Path,
        chat_id: str,
        *,
        calcom_interface: Any = None,
        event_callback=None,
        prebrief_minutes: int = PREBRIEF_MINUTES,
        enable_talking_points: bool = True,
    ) -> None:
        super().__init__(data_dir, event_callback=event_callback)
        self.chat_id = chat_id
        self.prebrief_minutes = prebrief_minutes
        self.enable_talking_points = enable_talking_points
        self._calcom: Any = calcom_interface

    def _calcom_interface(self) -> Any:
        """Lazy-import calcom_interface if not injected."""
        if self._calcom is not None:
            return self._calcom
        from bridge.services import calcom_interface as ci
        return ci

    def _already_sent(self, booking_uid: str) -> bool:
        """Return True if a prebrief was already sent for this booking uid."""
        state = self.load_state("prebrief-state.json")
        sent: list[str] = state.get("sent_uids", [])
        return booking_uid in sent

    def _mark_sent(self, booking_uid: str) -> None:
        """Record that a prebrief was sent for this booking uid."""
        state = self.load_state("prebrief-state.json")
        sent: list[str] = state.get("sent_uids", [])
        if booking_uid not in sent:
            sent.append(booking_uid)
        # Keep only last 200 UIDs to bound memory
        state["sent_uids"] = sent[-200:]
        self.save_state(state, "prebrief-state.json")

    def _send_prebrief(self, booking: dict[str, Any], *, late: bool = False) -> bool:
        """Compose and deliver the prebrief card. Returns True on success."""
        attendee_name = booking.get("attendee_name", "")
        attendee_email = booking.get("attendee_email", "")

        email_snippet = _get_last_email_snippet(attendee_email)
        company_info = _get_company_info(attendee_email)

        talking_points: list[str] | None = None
        if self.enable_talking_points and (
            booking.get("title") or attendee_name
        ):
            talking_points = _generate_talking_points(
                booking.get("title", ""),
                attendee_name,
                email_snippet,
                company_info,
            )

        card = _compose_card(
            booking,
            late=late,
            email_snippet=email_snippet,
            company_info=company_info,
            talking_points=talking_points,
        )

        self.deliver_message(self.chat_id, card, source="meeting_prebrief")
        uid = booking.get("uid") or booking.get("id", "")
        if uid:
            self._mark_sent(str(uid))
        log.info(
            "meeting_prebrief.sent uid=%s title=%r late=%s",
            uid, booking.get("title", ""), late,
        )
        return True

    def check_upcoming(self) -> int:
        """Scan upcoming bookings and fire prebriefs for those at T-30min.

        Returns count of prebriefs sent.
        """
        try:
            ci = self._calcom_interface()
            bookings = ci.get_upcoming_bookings(days=2)
        except Exception as exc:
            log.warning("meeting_prebrief.calcom_fetch_failed: %s", exc)
            return 0

        sent_count = 0
        for booking in bookings:
            uid = str(booking.get("uid") or booking.get("id", ""))
            start = booking.get("start_time") or booking.get("start", "")
            if not start:
                continue

            mins = _minutes_until(start)
            if mins is None:
                continue

            # Within [PREBRIEF_MINUTES-TOLERANCE, PREBRIEF_MINUTES+TOLERANCE]
            target = self.prebrief_minutes
            tol = PREBRIEF_TOLERANCE_MINUTES
            if not (target - tol <= mins <= target + tol):
                continue

            if uid and self._already_sent(uid):
                continue

            try:
                self._send_prebrief(booking, late=False)
                sent_count += 1
            except Exception as exc:
                log.warning("meeting_prebrief.send_failed uid=%s: %s", uid, exc)

        return sent_count

    def backfill_missed(self) -> int:
        """Check for meetings that started in the last BACKFILL_WINDOW_HOURS.

        If a prebrief was not sent for them (e.g. bridge was restarting),
        send one now marked as late. Returns count of backfill prebriefs sent.
        """
        try:
            ci = self._calcom_interface()
            # Fetch a wider window that includes past + upcoming
            bookings = ci.get_upcoming_bookings(days=1)
        except Exception as exc:
            log.warning("meeting_prebrief.backfill_fetch_failed: %s", exc)
            return 0

        now_utc = datetime.now(timezone.utc)
        cutoff = now_utc - timedelta(hours=BACKFILL_WINDOW_HOURS)
        sent_count = 0

        for booking in bookings:
            uid = str(booking.get("uid") or booking.get("id", ""))
            start_str = booking.get("start_time") or booking.get("start", "")
            if not start_str:
                continue

            try:
                start_dt = datetime.fromisoformat(start_str.replace("Z", "+00:00"))
                if start_dt.tzinfo is None:
                    start_dt = start_dt.replace(tzinfo=timezone.utc)
            except (ValueError, TypeError):
                continue

            # Only backfill events that have already started (in the past)
            # within the window
            if not (cutoff <= start_dt <= now_utc):
                continue

            if uid and self._already_sent(uid):
                continue

            try:
                self._send_prebrief(booking, late=True)
                sent_count += 1
            except Exception as exc:
                log.warning("meeting_prebrief.backfill_send_failed uid=%s: %s", uid, exc)

        return sent_count

    def handle_booking_event(
        self,
        booking_id: str,
        *,
        account: str | None = None,
    ) -> "ServiceResult":
        """Targeted prebrief invocation for a single booking by uid.

        Wired to the EventBus ``calcom.booking.created`` topic via BridgeApp:
        the producer is ``CalcomWebhookHandler`` (calcom_webhook.py). This is
        the consumer-half that turns webhook arrivals into a Discord card —
        no polling, no full scan, just the one booking.

        Lookup path: fetch upcoming bookings from ``calcom_interface`` and
        find the entry with matching ``uid``/``id``. If the booking is gone
        (cancelled, not yet visible, etc.) we return an ``ok=True`` skip
        rather than failing — the polling fallback will catch it next cycle.

        Args:
            booking_id: Cal.com booking uid (e.g. ``payload['raw_uid']`` or
                ``payload['booking']['uid']`` from the event bus event).
            account: Optional Cal.com account label (e.g. ``"personal"`` /
                ``"business"``) to scope the lookup. When ``None`` the
                interface picks the alphabetically-first configured account
                and emits a WARNING (Sprint 02.11 multi-account contract).

        Returns:
            ``ServiceResult`` describing the outcome. Never raises — event
            handlers must not crash the bus, so all exceptions are caught
            and surfaced as ``ok=False`` results.
        """
        from bridge.services.result import ServiceResult

        _start = time.monotonic()
        booking_id = str(booking_id or "").strip()

        if not booking_id:
            duration_ms = int((time.monotonic() - _start) * 1000)
            return ServiceResult(
                service="meeting_prebrief",
                ok=True,
                work_items=0,
                duration_ms=duration_ms,
                cost_usd=0.0,
                skip_reason="empty_booking_id",
            )

        if self._already_sent(booking_id):
            duration_ms = int((time.monotonic() - _start) * 1000)
            log.info("meeting_prebrief.event_dedup uid=%s", booking_id)
            return ServiceResult(
                service="meeting_prebrief",
                ok=True,
                work_items=0,
                duration_ms=duration_ms,
                cost_usd=0.0,
                skip_reason="already_sent",
            )

        try:
            ci = self._calcom_interface()
            # account=None falls through to the interface's default-with-warning.
            bookings = (
                ci.get_upcoming_bookings(days=2, account=account)
                if account is not None
                else ci.get_upcoming_bookings(days=2)
            )
        except Exception as exc:
            duration_ms = int((time.monotonic() - _start) * 1000)
            log.warning(
                "meeting_prebrief.event_fetch_failed uid=%s: %s",
                booking_id, exc,
            )
            return ServiceResult(
                service="meeting_prebrief",
                ok=False,
                work_items=0,
                duration_ms=duration_ms,
                cost_usd=0.0,
                narration=f"Cal.com fetch failed: {exc}"[:500],
            )

        match: dict[str, Any] | None = None
        for booking in bookings:
            uid = str(booking.get("uid") or booking.get("id", ""))
            if uid == booking_id:
                match = booking
                break

        if match is None:
            duration_ms = int((time.monotonic() - _start) * 1000)
            log.info(
                "meeting_prebrief.event_no_match uid=%s — polling fallback will retry",
                booking_id,
            )
            return ServiceResult(
                service="meeting_prebrief",
                ok=True,
                work_items=0,
                duration_ms=duration_ms,
                cost_usd=0.0,
                skip_reason="booking_not_found",
            )

        try:
            self._send_prebrief(match, late=False)
        except Exception as exc:
            duration_ms = int((time.monotonic() - _start) * 1000)
            log.warning(
                "meeting_prebrief.event_send_failed uid=%s: %s",
                booking_id, exc,
            )
            return ServiceResult(
                service="meeting_prebrief",
                ok=False,
                work_items=0,
                duration_ms=duration_ms,
                cost_usd=0.0,
                narration=f"Send failed: {exc}"[:500],
            )

        duration_ms = int((time.monotonic() - _start) * 1000)
        log.info(
            "meeting_prebrief.event_ok uid=%s title=%r (%dms)",
            booking_id, match.get("title", ""), duration_ms,
        )
        return ServiceResult(
            service="meeting_prebrief",
            ok=True,
            work_items=1,
            duration_ms=duration_ms,
            cost_usd=0.0,
            narration=f"Sent event-driven prebrief for {match.get('title', booking_id)}",
        )

    def run(self) -> "ServiceResult":
        """Run the prebrief scan — check upcoming + backfill missed meetings.

        This method is called by the runner on every calendar poll cycle.
        """
        from bridge.services.result import ServiceResult

        _start = time.monotonic()
        sent = 0
        backfilled = 0

        try:
            sent = self.check_upcoming()
            backfilled = self.backfill_missed()
        except Exception as exc:
            duration_ms = int((time.monotonic() - _start) * 1000)
            self.record_failure(str(exc)[:500], "prebrief-state.json")
            log.error("meeting_prebrief.run_failed: %s", exc)
            raise

        total = sent + backfilled
        duration_ms = int((time.monotonic() - _start) * 1000)

        if total == 0:
            self.record_skipped("no_prebriefs_due", "prebrief-state.json")
            return ServiceResult(
                service="meeting_prebrief",
                ok=True,
                work_items=0,
                duration_ms=duration_ms,
                cost_usd=0.0,
                skip_reason="no_prebriefs_due",
            )

        self.record_success(duration_ms, "prebrief-state.json")
        narration = (
            f"Sent {sent} prebrief card{'s' if sent != 1 else ''}"
            + (f", backfilled {backfilled}" if backfilled else "")
            + f" ({duration_ms}ms)"
        )
        log.info("meeting_prebrief.run_ok sent=%d backfilled=%d", sent, backfilled)

        return ServiceResult(
            service="meeting_prebrief",
            ok=True,
            work_items=total,
            duration_ms=duration_ms,
            cost_usd=0.0,
            narration=narration,
        )
