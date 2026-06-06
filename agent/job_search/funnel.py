"""Job Search Funnel — 8-stage daily counter store.

FunnelDay tracks one day's job-search pipeline counters:

  scraped → deduped → covered → lint_passed → lint_failed →
  submitted → staged → approved → sent → replied

Counters are stored in data/service_state/funnel.json keyed by ISO date.
Writes are atomic (temp + os.replace) so concurrent PREPARE / EXECUTE bumps
never corrupt the file.

Usage:
    from bridge.paths import data_root
    from job_search.funnel import FunnelStore, FunnelDay

    store = FunnelStore(data_dir=data_root())
    store.bump(date.today().isoformat(), "scraped", 45)
    day = store.get(date.today().isoformat())
    print(day.scraped)  # 45

Discord summary:
    from job_search.funnel import format_funnel_discord
    msg = format_funnel_discord(day, date.today().isoformat())
"""
from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import date
from pathlib import Path


_FUNNEL_FILE = "funnel.json"

# Ordered pipeline stage names — used for display.
STAGE_ORDER = [
    "scraped",
    "deduped",
    "covered",
    "lint_passed",
    "lint_failed",
    "submitted",
    "staged",
    "approved",
    "sent",
    "replied",
]


@dataclass
class FunnelDay:
    """One day's job-search funnel counters."""

    scraped: int = 0
    deduped: int = 0
    covered: int = 0
    lint_passed: int = 0
    lint_failed: int = 0
    submitted: int = 0
    staged: int = 0
    approved: int = 0
    sent: int = 0
    replied: int = 0
    # Overflow dict for forward-compat: any stage name not listed above
    # will land here instead of raising an error.
    extras: dict[str, int] = field(default_factory=dict)

    def bump(self, stage: str, count: int = 1) -> None:
        """Increment a stage counter in place (used by FunnelStore)."""
        if hasattr(self, stage) and stage != "extras":
            setattr(self, stage, getattr(self, stage) + count)
        else:
            self.extras[stage] = self.extras.get(stage, 0) + count

    def to_dict(self) -> dict:
        d = asdict(self)
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "FunnelDay":
        known = {k: d.get(k, 0) for k in STAGE_ORDER}
        extras = {k: v for k, v in d.items() if k not in STAGE_ORDER and k != "extras"}
        # Merge any stored extras field too
        extras.update(d.get("extras", {}))
        return cls(**known, extras=extras)


class FunnelStore:
    """Persistent per-day funnel counter store.

    Thread/process safety: uses atomic write (tempfile + os.replace).
    Two processes bumping the same stage concurrently will each read the
    current file, increment, and write back.  Under very high concurrency
    (dozens of concurrent bumps) the last writer wins, but the job-search
    pipeline is serial enough that this is acceptable.  A file lock is NOT
    used to keep the implementation dependency-free.
    """

    def __init__(self, data_dir: Path | str) -> None:
        self._state_dir = Path(data_dir) / "service_state"
        self._state_dir.mkdir(parents=True, exist_ok=True)
        self._path = self._state_dir / _FUNNEL_FILE

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get(self, date_key: str) -> FunnelDay:
        """Return the FunnelDay for *date_key* (ISO date string).

        Returns a zeroed FunnelDay if the date has no data yet.
        """
        data = self._load()
        raw = data.get(date_key, {})
        return FunnelDay.from_dict(raw)

    def bump(self, date_key: str, stage: str, count: int = 1) -> FunnelDay:
        """Atomically increment *stage* by *count* for *date_key*.

        Returns the updated FunnelDay.
        """
        data = self._load()
        raw = data.get(date_key, {})
        day = FunnelDay.from_dict(raw)
        day.bump(stage, count)
        data[date_key] = day.to_dict()
        self._save(data)
        return day

    def set_day(self, date_key: str, day: FunnelDay) -> None:
        """Overwrite the entire FunnelDay for *date_key*."""
        data = self._load()
        data[date_key] = day.to_dict()
        self._save(data)

    def all_dates(self) -> list[str]:
        """Return all stored date keys, sorted ascending."""
        return sorted(self._load().keys())

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Discord formatting
# ---------------------------------------------------------------------------

def format_funnel_discord(day: FunnelDay, date_key: str) -> str:
    """Render a FunnelDay as a Discord-friendly daily summary.

    Emits a SKIP notice when all counters are zero.
    """
    all_zero = all(
        getattr(day, s) == 0 for s in STAGE_ORDER
    ) and not day.extras

    if all_zero:
        return (
            f"**Job Search Funnel — {date_key}**\n"
            "No activity recorded today. `reason=no_activity`"
        )

    lines = [f"**Job Search Funnel — {date_key}**", "```"]
    labels = {
        "scraped":     "Scraped     ",
        "deduped":     "Deduped     ",
        "covered":     "Covered     ",
        "lint_passed": "Lint passed ",
        "lint_failed": "Lint failed ",
        "submitted":   "Submitted   ",
        "staged":      "Staged      ",
        "approved":    "Approved    ",
        "sent":        "Sent        ",
        "replied":     "Replied     ",
    }
    for stage in STAGE_ORDER:
        val = getattr(day, stage)
        if val > 0 or stage in ("scraped", "deduped", "submitted", "staged"):
            lines.append(f"  {labels[stage]} {val:>5}")
    for k, v in day.extras.items():
        lines.append(f"  {k:<20} {v:>5}")
    lines.append("```")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Convenience: today's key
# ---------------------------------------------------------------------------

def today_key() -> str:
    return date.today().isoformat()


# ── D5.8: structured aggregator over the new JSONL signals ───────────────

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

log = logging.getLogger(__name__)

from bridge.paths import data_root  # noqa: E402
from job_search.contracts import FunnelBucket, FunnelReport  # noqa: E402

CONVERSATIONS_ROOT = data_root() / "teams" / "job_search" / "conversations"


def aggregate_funnel(
    *,
    window: str = "7d",
    now_utc: Optional[datetime] = None,
    conversations_root: Path = CONVERSATIONS_ROOT,
) -> FunnelReport:
    """Read conversation-log JSONL files and return a structured FunnelReport.

    Pure function over filesystem. Failure-soft: missing files / bad lines
    are skipped. Returns zero-count FunnelReport if no data found.

    window: "7d" | "30d" | "all"
    """
    now = now_utc or datetime.now(timezone.utc)
    cutoff = _resolve_cutoff(window, now)

    # Accumulate: key=(board, ats, submit_step) → mutable counter dict
    counts: dict[tuple[str, str, str], dict[str, int]] = {}

    glob_iter = sorted(conversations_root.glob("*.jsonl")) if conversations_root.exists() else []
    for jsonl_path in glob_iter:
        try:
            _process_conversation_log(jsonl_path, cutoff, counts)
        except Exception as exc:
            log.warning("D5.8 aggregator: skipping %s: %s", jsonl_path.name, exc)

    buckets = []
    for (board, ats, step), c in counts.items():
        buckets.append(FunnelBucket(
            board=board, ats=ats, submit_step=step,
            submitted=c.get("submitted", 0),
            blocked=c.get("blocked", 0),
            requires_email_verify=c.get("requires_email_verify", 0),
            requires_login=c.get("requires_login", 0),
            error=c.get("error", 0),
        ))

    sorted_buckets = tuple(sorted(buckets, key=lambda b: (-b.submission_rate, -b.attempts_total)))

    total_submitted = sum(b.submitted for b in sorted_buckets)
    total_blocked = sum(b.blocked for b in sorted_buckets)
    total_rev = sum(b.requires_email_verify for b in sorted_buckets)
    total_login = sum(b.requires_login for b in sorted_buckets)
    total_error = sum(b.error for b in sorted_buckets)
    total_attempts = total_submitted + total_blocked + total_rev + total_login + total_error

    return FunnelReport(
        window_start_iso=cutoff.isoformat() if cutoff else "",
        window_end_iso=now.isoformat(),
        window_label=_window_label(window),
        buckets=sorted_buckets,
        total_attempts=total_attempts,
        total_submitted=total_submitted,
        total_blocked=total_blocked,
        total_requires_email_verify=total_rev,
        total_requires_login=total_login,
        total_error=total_error,
    )


def _resolve_cutoff(window: str, now: datetime) -> Optional[datetime]:
    if window == "all":
        return None
    delta = {"7d": timedelta(days=7), "30d": timedelta(days=30)}.get(window)
    if delta is None:
        raise ValueError(f"window must be 7d/30d/all; got {window!r}")
    return now - delta


def _window_label(window: str) -> str:
    return {"7d": "last 7 days", "30d": "last 30 days", "all": "all-time"}.get(window, window)


def _process_conversation_log(
    path: Path,
    cutoff: Optional[datetime],
    counts: dict,
) -> None:
    """Read one conversation log JSONL and update the counts dict in-place."""
    import json as _json
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                record = _json.loads(line)
            except Exception:
                continue
            ts = record.get("ts")
            if cutoff and ts:
                try:
                    line_dt = datetime.fromtimestamp(float(ts), tz=timezone.utc)
                    if line_dt < cutoff:
                        continue
                except Exception:
                    pass

            event = record.get("event", "")
            if event == "browser_completed":
                board = str(record.get("board") or "unknown")
                ats = str(record.get("ats_kind") or "unknown")
                step = str(record.get("last_step") or "unknown")
                status = str(record.get("status") or "error").lower()
                key = (board, ats, step)
                c = counts.setdefault(key, {})
                c[status] = c.get(status, 0) + 1


def format_funnel_report_text(report: FunnelReport) -> str:
    """Format a FunnelReport as a human-readable text block for Discord / slash command."""
    lines = [
        f"**Job Search Funnel — {report.window_label}**",
        f"Attempts: {report.total_attempts}  |  "
        f"Submitted: {report.total_submitted} ({report.overall_submission_rate:.0%})  |  "
        f"Blocked: {report.total_blocked}  |  "
        f"Email verify: {report.total_requires_email_verify}  |  "
        f"Login wall: {report.total_requires_login}  |  "
        f"Error: {report.total_error}",
    ]
    if report.buckets:
        lines.append("\n**Top buckets (board / ATS / step):**")
        for b in report.buckets[:10]:
            lines.append(
                f"  {b.board}/{b.ats}/{b.submit_step}: "
                f"{b.submitted}✓ {b.blocked}✗ "
                f"({b.submission_rate:.0%} rate, {b.attempts_total} total)"
            )
    else:
        lines.append("No data in window.")
    return "\n".join(lines)
