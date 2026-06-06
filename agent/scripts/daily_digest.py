"""Daily drift digest — compare today's metrics to a 7-day baseline.

Sprint 4.7 — Phase 4 (Harness Hardening).

Reads ``bridge-metrics.jsonl``, computes a trailing 7-day baseline
(mean + stddev) for each metric, then compares today's records
against that baseline. Any metric exceeding 2 standard deviations
is flagged as an anomaly.

Can be run standalone::

    python daily_digest.py --metrics-path /path/to/bridge-metrics.jsonl

or imported as a library for use in the daily briefing service.

All functions are pure — they take inputs and return outputs with
no side effects. The ``main()`` entrypoint prints the digest to
stdout; the caller decides what to do with it (post to Discord,
log to file, etc.).
"""
from __future__ import annotations

import argparse
import math
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

# Resolve imports whether run as script or as part of the agent package.
# When invoked as ``python daily_digest.py``, the agent package is not
# on sys.path. We insert the repo root so the import works both ways.
_SCRIPT_DIR = Path(__file__).resolve().parent
_AGENT_DIR = _SCRIPT_DIR.parent
if str(_AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(_AGENT_DIR))

from bridge.drift_telemetry import (  # noqa: E402
    METRIC_FIELDS,
    MetricsRecord,
    load_metrics,
)


# ---------------------------------------------------------------------------
# Anomaly record
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Anomaly:
    """A single metric that exceeds 2 standard deviations from baseline.

    Attributes:
        metric: The metric field name (e.g. ``"velocity"``).
        current: Today's value for this metric.
        mean: Baseline mean over the trailing window.
        stddev: Baseline standard deviation.
        sigma: Number of standard deviations from the mean.
            Always >= 0. When stddev is 0 and current != mean,
            sigma is ``inf``.
    """

    metric: str
    current: float
    mean: float
    stddev: float
    sigma: float


# ---------------------------------------------------------------------------
# Baseline computation
# ---------------------------------------------------------------------------


def compute_baseline(
    records: list[MetricsRecord],
) -> dict[str, tuple[float, float]]:
    """Compute mean and stddev for each metric across a list of records.

    Returns a dict mapping metric field name to ``(mean, stddev)``.
    If the record list is empty, all means and stddevs are 0.0.

    Uses population stddev (divides by N, not N-1) — consistent with
    the existing ``metrics.py`` convention in this codebase.
    """
    n = len(records)
    if n == 0:
        return {field: (0.0, 0.0) for field in METRIC_FIELDS}

    result: dict[str, tuple[float, float]] = {}
    for field in METRIC_FIELDS:
        values = [getattr(r, field) for r in records]
        mean = sum(values) / n
        variance = sum((v - mean) ** 2 for v in values) / n
        stddev = math.sqrt(variance)
        result[field] = (mean, stddev)

    return result


# ---------------------------------------------------------------------------
# Anomaly detection
# ---------------------------------------------------------------------------

_SIGMA_THRESHOLD: float = 2.0


def detect_anomalies(
    today: MetricsRecord,
    baseline: dict[str, tuple[float, float]],
) -> list[Anomaly]:
    """Compare today's record against the baseline.

    Returns a list of ``Anomaly`` objects for any metric whose
    current value is more than 2 standard deviations from the
    baseline mean. Metrics not present in the baseline dict are
    skipped.

    When stddev is 0 and current != mean, sigma is ``inf`` and
    the metric is always flagged. When stddev is 0 and current ==
    mean, the metric passes (no deviation).
    """
    anomalies: list[Anomaly] = []
    for field in METRIC_FIELDS:
        if field not in baseline:
            continue
        mean, stddev = baseline[field]
        current = getattr(today, field)

        if stddev == 0.0:
            if current != mean:
                anomalies.append(
                    Anomaly(
                        metric=field,
                        current=current,
                        mean=mean,
                        stddev=stddev,
                        sigma=float("inf"),
                    )
                )
            continue

        sigma = abs(current - mean) / stddev
        if sigma >= _SIGMA_THRESHOLD:
            anomalies.append(
                Anomaly(
                    metric=field,
                    current=current,
                    mean=mean,
                    stddev=stddev,
                    sigma=round(sigma, 2),
                )
            )

    return anomalies


# ---------------------------------------------------------------------------
# Digest formatting — human-readable for Discord
# ---------------------------------------------------------------------------

_METRIC_LABELS: dict[str, str] = {
    "velocity": "Velocity (PRs/hr)",
    "bundling_indicator": "Bundling (lines/PR)",
    "work_depth": "Work depth (tools/PR)",
    "test_frequency": "Test frequency (s between tests)",
    "honesty_indicator": "Honesty (claim:evidence)",
    "dialogue_responsiveness": "Dialogue responsiveness (s)",
    "engagement_indicator": "Engagement (tool:dialogue)",
}


def format_digest(anomalies: list[Anomaly]) -> str:
    """Format anomalies into a human-readable digest.

    Returns a string suitable for posting to Discord or logging.
    If there are no anomalies, returns a short all-clear message.
    """
    if not anomalies:
        return "Daily drift digest: all metrics within normal range."

    lines: list[str] = [
        f"**Daily drift digest** -- {len(anomalies)} anomal{'y' if len(anomalies) == 1 else 'ies'} detected",
        "",
    ]
    for a in anomalies:
        label = _METRIC_LABELS.get(a.metric, a.metric)
        sigma_str = f"{a.sigma:.1f}" if not math.isinf(a.sigma) else "inf"
        lines.append(
            f"  {label}: {a.current:.2f} "
            f"(baseline {a.mean:.2f} +/- {a.stddev:.2f}, "
            f"{sigma_str} sigma)"
        )

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI entrypoint
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> None:
    """Run the daily digest from the command line."""
    parser = argparse.ArgumentParser(
        description="Daily drift digest -- compare today's metrics to 7-day baseline",
    )
    parser.add_argument(
        "--metrics-path",
        type=Path,
        default=Path("data/bridge-metrics.jsonl"),
        help="Path to bridge-metrics.jsonl (default: data/bridge-metrics.jsonl)",
    )
    parser.add_argument(
        "--baseline-days",
        type=int,
        default=7,
        help="Number of trailing days for baseline (default: 7)",
    )
    args = parser.parse_args(argv)

    all_records = load_metrics(args.metrics_path, days=args.baseline_days + 1)
    if not all_records:
        print("No metrics data found.")
        return

    # Partition: today's records vs. baseline records
    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    today_records = [r for r in all_records if r.timestamp.startswith(today_str)]
    baseline_records = [
        r for r in all_records if not r.timestamp.startswith(today_str)
    ]

    if not today_records:
        print("No metrics recorded today.")
        return

    baseline = compute_baseline(baseline_records)

    # Check each of today's records against the baseline
    all_anomalies: list[Anomaly] = []
    for record in today_records:
        anomalies = detect_anomalies(record, baseline)
        all_anomalies.extend(anomalies)

    # Deduplicate by metric name — keep the highest sigma
    seen: dict[str, Anomaly] = {}
    for a in all_anomalies:
        if a.metric not in seen or a.sigma > seen[a.metric].sigma:
            seen[a.metric] = a
    deduped = list(seen.values())

    print(format_digest(deduped))


if __name__ == "__main__":
    main()
