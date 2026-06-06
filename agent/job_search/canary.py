"""Post-Submit Funnel Canary — Z2-S2.5.

After each PREPARE run, call check_funnel_canary(day) to detect silent
pipeline failures.  Returns a CanaryAlert (with a tag and human message)
when an anomaly is found, or None when the funnel shape looks healthy.

Three anomaly classes
---------------------
submitted_no_stage
    submitted > 0 AND staged == 0
    → Submission pipeline is silently broken; listings submitted but none
      landed in Notion.

dedup_dropped_all
    scraped > DEDUP_SCRAPE_THRESHOLD AND deduped == 0
    → Deduplicator dropped every listing; probably a code bug or overly
      aggressive dedup rule.  Only fires when enough listings were scraped
      to make "0 deduped" implausible.

covered_no_submit
    covered > 0 AND submitted == 0
    → Cover letters generated but submit step returned zero; usually
      Playwright / ATS selector drift.

DM deduplication
----------------
Alerts are keyed by (date_key, anomaly_tag) and stored in
``<data_dir>/service_state/canary_alerts.json`` with a 24-hour window.
``check_funnel_canary`` is a pure function; callers pass in the dedup
store separately via ``CanaryDedupe``.

Usage
-----
    from job_search.canary import check_funnel_canary, CanaryDedupe
    from job_search.funnel import FunnelStore

    store = FunnelStore(data_dir)
    day = store.get(today_key())
    alert = check_funnel_canary(day)
    if alert:
        dedup = CanaryDedupe(data_dir)
        if dedup.should_fire(today_key(), alert.tag):
            # send Discord DM
            dedup.record(today_key(), alert.tag)
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from job_search.funnel import FunnelDay

log = logging.getLogger(__name__)

# Only fire dedup_dropped_all when we scraped at least this many listings.
DEDUP_SCRAPE_THRESHOLD = 50

_CANARY_FILE = "canary_alerts.json"


# ---------------------------------------------------------------------------
# Alert type
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class CanaryAlert:
    """A detected funnel-shape anomaly.

    tag:     Short machine-readable identifier.
    message: Human-readable description for Discord.
    """

    tag: str
    message: str


# ---------------------------------------------------------------------------
# Pure check function (no I/O)
# ---------------------------------------------------------------------------

def check_funnel_canary(
    day: FunnelDay,
    *,
    dedup_scrape_threshold: int = DEDUP_SCRAPE_THRESHOLD,
) -> CanaryAlert | None:
    """Inspect *day* for funnel-shape anomalies.

    Returns a CanaryAlert if an anomaly is detected, None if the shape
    looks healthy (including a genuinely zero-activity day).
    """
    # A day with no activity at all is not anomalous.
    if day.scraped == 0 and day.covered == 0 and day.submitted == 0:
        return None

    # submitted_no_stage: listings submitted but none reached Notion
    if day.submitted > 0 and day.staged == 0:
        return CanaryAlert(
            tag="submitted_no_stage",
            message=(
                f"CANARY: {day.submitted} listing(s) submitted but 0 staged in Notion. "
                "Submission pipeline may be silently broken. "
                "Check Playwright / Notion write path."
            ),
        )

    # dedup_dropped_all: deduplicator swallowed everything
    if day.scraped > dedup_scrape_threshold and day.deduped == 0:
        return CanaryAlert(
            tag="dedup_dropped_all",
            message=(
                f"CANARY: {day.scraped} listings scraped but 0 survived dedup. "
                "Deduplication logic may have a bug or overly aggressive rule."
            ),
        )

    # covered_no_submit: cover letters generated but submit step returned 0
    if day.covered > 0 and day.submitted == 0:
        return CanaryAlert(
            tag="covered_no_submit",
            message=(
                f"CANARY: {day.covered} cover letter(s) generated but 0 submitted. "
                "ATS detection or Playwright submit step may be broken."
            ),
        )

    return None


# ---------------------------------------------------------------------------
# DM deduplication store (24-hour window per date+tag pair)
# ---------------------------------------------------------------------------

class CanaryDedupe:
    """Tracks fired canary alerts to prevent duplicate DMs within 24 hours."""

    def __init__(self, data_dir: Path | str) -> None:
        self._state_dir = Path(data_dir) / "service_state"
        self._state_dir.mkdir(parents=True, exist_ok=True)
        self._path = self._state_dir / _CANARY_FILE

    def should_fire(self, date_key: str, tag: str) -> bool:
        """Return True if this (date_key, tag) pair has not fired today."""
        data = self._load()
        key = f"{date_key}:{tag}"
        return key not in data

    def record(self, date_key: str, tag: str) -> None:
        """Mark this (date_key, tag) pair as fired."""
        data = self._load()
        key = f"{date_key}:{tag}"
        data[key] = datetime.now(timezone.utc).isoformat()
        self._save(data)
        log.info("Canary alert recorded: %s", key)

    def _load(self) -> dict:
        if not self._path.exists():
            return {}
        try:
            raw = json.loads(self._path.read_text())
            return raw if isinstance(raw, dict) else {}
        except (json.JSONDecodeError, OSError):
            return {}

    def _save(self, data: dict) -> None:
        fd, tmp = tempfile.mkstemp(dir=self._state_dir, suffix=".tmp")
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(data, f, indent=2, sort_keys=True)
            os.replace(tmp, self._path)
        except Exception:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
