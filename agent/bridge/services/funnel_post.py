"""Funnel post service — daily 22:00 Discord summary of job-search funnel (Z2-S2.1 FR-005).

Reuses ``job_search.funnel`` for the FunnelStore and ``format_funnel_discord``
formatting. This service only owns the schedule + delivery path.

Closes FR-005 of issue #493 — which was not shipped in #588.
"""

from __future__ import annotations

import logging
import time as _time
from datetime import datetime
from pathlib import Path

from .base import ServiceBase
from .result import ServiceResult

log = logging.getLogger(__name__)


class FunnelPostService(ServiceBase):
    """Daily Discord post of the job-search funnel summary."""

    def __init__(
        self,
        data_dir: str | Path,
        chat_id: str,
        *,
        event_callback=None,
        post_hour: int = 22,
        post_minute: int = 0,
    ) -> None:
        super().__init__(data_dir, event_callback=event_callback)
        self.chat_id = chat_id
        self.post_hour = post_hour
        self.post_minute = post_minute

    def should_run(self) -> bool:
        """Fire only in the configured time window and only once per day."""
        now = datetime.now()
        target = now.replace(
            hour=self.post_hour,
            minute=self.post_minute,
            second=0,
            microsecond=0,
        )
        if abs((now - target).total_seconds()) > 1800:
            return False

        state = self.load_state(filename="funnel_post-state.json")
        last_date = state.get("last_post_date", "")
        return last_date != now.strftime("%Y-%m-%d")

    def run(self) -> ServiceResult:
        """Post today's funnel summary to Discord.

        Returns:
            ServiceResult: OK with work_items=1 on successful post,
                OK with skip_reason set when outside the window, already ran,
                or the day has no activity; FAIL only on hard errors.
        """
        start = _time.monotonic()

        if not self.should_run():
            self.record_skipped(
                "outside post window or already posted today",
                filename="funnel_post-state.json",
            )
            return ServiceResult(
                service="funnel_post",
                ok=True,
                work_items=0,
                duration_ms=int((_time.monotonic() - start) * 1000),
                cost_usd=0.0,
                skip_reason="outside_window_or_already_ran",
            )

        # Import lazily so the module imports cleanly even if job_search is
        # trimmed in a future refactor.
        from job_search.canary import CanaryDedupe, check_funnel_canary
        from job_search.funnel import (
            FunnelStore,
            format_funnel_discord,
            today_key,
        )

        try:
            store = FunnelStore(self.data_dir)
            date_key = today_key()
            day = store.get(date_key)

            # Sprint 02.10: run the post-submit canary BEFORE rendering the
            # summary so the operator sees anomalies inline with counts.
            # ``check_funnel_canary`` returns a ``CanaryAlert | None``;
            # ``CanaryDedupe`` keeps repeated alerts from spamming the chat.
            alert = check_funnel_canary(day)
            alert_block = ""
            if alert is not None:
                dedup = CanaryDedupe(self.data_dir)
                if dedup.should_fire(date_key, alert.tag):
                    dedup.record(date_key, alert.tag)
                    alert_block = f"\n\n**ALERT — {alert.tag}**\n{alert.message}"
                    # Surface the anomaly on the event bus for downstream
                    # observability (also makes it grep-able in the cron
                    # event stream).
                    try:
                        from bridge.event_bus import EventBus
                        event_bus = EventBus(data_dir=self.data_dir)
                        event_bus.publish(
                            "funnel.anomaly_detected",
                            {
                                "date_key": date_key,
                                "tag": alert.tag,
                                "message": alert.message,
                            },
                        )
                    except Exception:  # pragma: no cover — defensive
                        log.exception("Failed to publish funnel.anomaly_detected event")

            message = format_funnel_discord(day, date_key) + alert_block

            # The no_activity path is communicated *inside* the message via the
            # format helper, but we still want the ServiceResult to carry the
            # skip_reason so /services shows "skipped: no_activity" instead of
            # "ok: 1 work item" on quiet days (matches FR-007 from the spec).
            is_empty = all(
                getattr(day, stage, 0) == 0
                for stage in (
                    "scraped", "deduped", "covered",
                    "submitted", "staged", "approved",
                    "sent", "replied",
                )
            ) and not getattr(day, "extras", None)

            if is_empty:
                self.record_skipped(
                    "no funnel activity today",
                    filename="funnel_post-state.json",
                )
                # Still mark the day as "posted" so we do not re-check on
                # every cron tick. Operator sees the no-activity line once.
                self._mark_posted_today()
                self.deliver_message(self.chat_id, message, source="funnel-post")
                return ServiceResult(
                    service="funnel_post",
                    ok=True,
                    work_items=0,
                    duration_ms=int((_time.monotonic() - start) * 1000),
                    cost_usd=0.0,
                    skip_reason="no_activity",
                    narration="Daily funnel post — no activity recorded today.",
                )

            self.deliver_message(self.chat_id, message, source="funnel-post")
            self._mark_posted_today()

            duration_ms = int((_time.monotonic() - start) * 1000)
            self.record_success(duration_ms, filename="funnel_post-state.json")
            log.info("Funnel post delivered (%dms)", duration_ms)

            return ServiceResult(
                service="funnel_post",
                ok=True,
                work_items=1,
                duration_ms=duration_ms,
                cost_usd=0.0,
                narration=(
                    f"Daily funnel: scraped={day.scraped} "
                    f"submitted={day.submitted} staged={day.staged} "
                    f"sent={day.sent}"
                ),
            )

        except Exception as exc:
            duration_ms = int((_time.monotonic() - start) * 1000)
            self.record_failure(str(exc)[:500], filename="funnel_post-state.json")
            log.error("Funnel post failed after %dms: %s", duration_ms, exc)
            raise

    def _mark_posted_today(self) -> None:
        """Persist today's post date so we don't re-post on the same day."""
        state = self.load_state(filename="funnel_post-state.json")
        state["last_post_date"] = datetime.now().strftime("%Y-%m-%d")
        self.save_state(state, filename="funnel_post-state.json")
