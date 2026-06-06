"""Staleness detection constants and helpers for MS1.4."""

from __future__ import annotations

from datetime import datetime, timezone


# Expected run intervals per service, in seconds.
SERVICE_INTERVALS: dict[str, int] = {
    "briefing": 86400,
    "email": 7200,
    "calendar": 900,
    "knowledge_review": 86400,
    "job_search": 86400,
    "job_search_execute": 7200,
    "checkin": 14400,
}

# Knowledge freshness thresholds per category, in days.
# Categories not listed here are exempt from freshness checks.
KNOWLEDGE_FRESHNESS_THRESHOLDS: dict[str, int] = {
    "project": 7,
    "decision": 7,
    "process": 30,
    "learning": 30,
    "tool": 30,
    "reference": 60,
}

# Categories exempt from freshness checks.
EXEMPT_CATEGORIES: frozenset[str] = frozenset({"preference", "person"})


def is_service_stale(last_run_iso: str | None, service_name: str) -> bool:
    """Return True if a service has not run within 2x its expected interval.

    A service with no last_run (None) is always considered stale.
    A service not listed in SERVICE_INTERVALS is never considered stale.
    """
    if last_run_iso is None:
        return service_name in SERVICE_INTERVALS

    interval = SERVICE_INTERVALS.get(service_name)
    if interval is None:
        return False

    try:
        last_run = datetime.fromisoformat(last_run_iso)
        # If the timestamp is naive, assume UTC
        if last_run.tzinfo is None:
            last_run = last_run.replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        elapsed = (now - last_run).total_seconds()
        return elapsed > (interval * 2)
    except (ValueError, TypeError):
        return True
