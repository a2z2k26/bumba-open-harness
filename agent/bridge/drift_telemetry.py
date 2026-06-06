"""Drift telemetry — per-session metrics for behavioural drift detection.

Sprint 4.7 — Phase 4 (Harness Hardening).

Tracks seven per-session metrics that together form a behavioural
fingerprint of the agent's work style. When the fingerprint shifts
beyond 2 standard deviations of its trailing 7-day baseline, the
daily digest flags the anomaly for operator review.

The seven metrics:

    velocity              PRs opened per hour
    bundling_indicator    Average lines per PR
    work_depth            Tool calls per PR
    test_frequency        Seconds between evidence-capture commands
    honesty_indicator     Claim-to-evidence ratio
    dialogue_responsiveness   Operator message response latency (s)
    engagement_indicator  Tool-call-to-dialogue ratio

Architecture:

    - ``MetricsRecord`` is a frozen dataclass — one per session.
    - ``record_metrics`` appends a single JSON line to
      ``bridge-metrics.jsonl``. Append-only, never modified.
    - ``load_metrics`` reads and filters by age. Returns new list
      each call — no mutation of shared state.

Integration surface (deferred to a wiring sprint):

    1. At session end, assemble a ``MetricsRecord`` from the
       session's counters and invoke ``record_metrics``.
    2. Wire the daily digest script into the daily briefing
       service or a standalone LaunchDaemon.
"""
from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Metric field names — stable keys for JSON serialization
# ---------------------------------------------------------------------------

METRIC_FIELDS: tuple[str, ...] = (
    "velocity",
    "bundling_indicator",
    "work_depth",
    "test_frequency",
    "honesty_indicator",
    "dialogue_responsiveness",
    "engagement_indicator",
)


# ---------------------------------------------------------------------------
# Data record
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class MetricsRecord:
    """One session's behavioural metrics snapshot.

    Frozen so records are immutable after construction. The seven
    metric fields default to 0.0 so callers can omit metrics that
    don't apply to a given session (e.g. a session with no PRs has
    velocity=0.0 and bundling_indicator=0.0).
    """

    session_id: str
    timestamp: str  # ISO 8601 UTC

    velocity: float = 0.0
    bundling_indicator: float = 0.0
    work_depth: float = 0.0
    test_frequency: float = 0.0
    honesty_indicator: float = 0.0
    dialogue_responsiveness: float = 0.0
    engagement_indicator: float = 0.0


# ---------------------------------------------------------------------------
# Write — append-only JSONL
# ---------------------------------------------------------------------------


def record_metrics(record: MetricsRecord, path: Path) -> None:
    """Append a single metrics record as a JSON line.

    Creates parent directories if they don't exist. Never modifies
    existing lines — strictly append-only.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(asdict(record), separators=(",", ":"))
    with open(path, "a", encoding="utf-8") as f:
        f.write(line + "\n")


# ---------------------------------------------------------------------------
# Read — filter by age
# ---------------------------------------------------------------------------


def load_metrics(path: Path, days: int = 7) -> list[MetricsRecord]:
    """Load metrics records from a JSONL file, filtered to the last N days.

    Returns an empty list if the file doesn't exist or is empty.
    Malformed lines are skipped with a debug log — they don't raise.
    Each call returns a new list; no shared mutable state.
    """
    if not path.exists():
        return []

    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    cutoff_iso = cutoff.isoformat()

    records: list[MetricsRecord] = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            for raw_line in f:
                stripped = raw_line.strip()
                if not stripped:
                    continue
                try:
                    obj = json.loads(stripped)
                except json.JSONDecodeError:
                    logger.debug(
                        "drift_telemetry: skipping malformed line: %r",
                        stripped[:80],
                    )
                    continue
                if not isinstance(obj, dict):
                    continue
                ts = obj.get("timestamp", "")
                if ts < cutoff_iso:
                    continue
                records.append(
                    MetricsRecord(
                        session_id=str(obj.get("session_id", "")),
                        timestamp=str(ts),
                        velocity=float(obj.get("velocity", 0.0)),
                        bundling_indicator=float(
                            obj.get("bundling_indicator", 0.0)
                        ),
                        work_depth=float(obj.get("work_depth", 0.0)),
                        test_frequency=float(obj.get("test_frequency", 0.0)),
                        honesty_indicator=float(
                            obj.get("honesty_indicator", 0.0)
                        ),
                        dialogue_responsiveness=float(
                            obj.get("dialogue_responsiveness", 0.0)
                        ),
                        engagement_indicator=float(
                            obj.get("engagement_indicator", 0.0)
                        ),
                    )
                )
    except OSError as e:
        logger.warning("drift_telemetry: cannot read %s: %s", path, e)
        return []

    return records
