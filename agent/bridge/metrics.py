"""Lightweight operational metrics collection for baseline and regression detection.

Phase 1: In-memory counters/histograms flushed to JSONL (MetricsCollector).
Phase 4 (MS4.1): SQLite-backed recording, rolling baselines, 2σ regression
detection, alert cooldowns, daily markdown summaries (PerformanceBaseline).
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import sqlite3
import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# MS4.1 constants
# ---------------------------------------------------------------------------

MAX_RETENTION_DAYS = 90
MAX_QUERY_ROWS = 10_000
BASELINE_CACHE_TTL = 3600  # seconds
MIN_BASELINE_SAMPLES = 10

# Metric name constants
RESPONSE_LATENCY_MS = "response_latency_ms"
TOKEN_COST_USD = "token_cost_usd"
SEARCH_RECALL = "search_recall"
SCRAPER_YIELD = "scraper_yield"
ERROR_RATE = "error_rate"
BUDGET_BURN_RATE = "budget_burn_rate"

# Candidate module usage counters (#22)
FEW_SHOT_INJECTIONS = "few_shot_injections"
MODEL_ROUTER_OVERRIDES = "model_router_overrides"
DEPARTMENT_DETECTIONS = "department_detections"
TEMPORAL_KB_QUERIES = "temporal_kb_queries"
SELF_EDIT_REQUESTS = "self_edit_requests"
REFLECTION_RETRIEVALS = "reflection_retrievals"

VALID_METRIC_NAMES = frozenset({
    RESPONSE_LATENCY_MS, TOKEN_COST_USD, SEARCH_RECALL,
    SCRAPER_YIELD, ERROR_RATE, BUDGET_BURN_RATE,
    FEW_SHOT_INJECTIONS, MODEL_ROUTER_OVERRIDES, DEPARTMENT_DETECTIONS,
    TEMPORAL_KB_QUERIES, SELF_EDIT_REQUESTS, REFLECTION_RETRIEVALS,
})

# Candidate module display names for /redundancy command
CANDIDATE_MODULE_KEYS = [
    FEW_SHOT_INJECTIONS,
    MODEL_ROUTER_OVERRIDES,
    DEPARTMENT_DETECTIONS,
    TEMPORAL_KB_QUERIES,
    SELF_EDIT_REQUESTS,
    REFLECTION_RETRIEVALS,
]

CANDIDATE_MODULE_LABELS = {
    FEW_SHOT_INJECTIONS: "few_shot",
    MODEL_ROUTER_OVERRIDES: "model_router",
    DEPARTMENT_DETECTIONS: "departments",
    TEMPORAL_KB_QUERIES: "temporal_knowledge",
    SELF_EDIT_REQUESTS: "self_edit_memory",
    REFLECTION_RETRIEVALS: "reflection",
}

_PERF_CREATE_TABLE = """\
CREATE TABLE IF NOT EXISTS perf_metrics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    value REAL NOT NULL,
    timestamp TEXT NOT NULL DEFAULT (datetime('now')),
    session_id TEXT,
    tags TEXT DEFAULT '{}'
);"""
_PERF_IDX_NAME_TS = (
    "CREATE INDEX IF NOT EXISTS idx_perf_metrics_name_ts "
    "ON perf_metrics(name, timestamp);"
)
_PERF_IDX_NAME_SID = (
    "CREATE INDEX IF NOT EXISTS idx_perf_metrics_name_sid "
    "ON perf_metrics(name, session_id);"
)


# ---------------------------------------------------------------------------
# MS4.1 data classes
# ---------------------------------------------------------------------------

@dataclass
class BaselineStats:
    """Rolling baseline statistics for a single metric."""
    mean: float = 0.0
    stddev: float = 0.0
    min: float = 0.0
    max: float = 0.0
    p50: float = 0.0
    p95: float = 0.0
    p99: float = 0.0
    sample_count: int = 0


@dataclass
class RegressionResult:
    """Result of a regression check against a baseline."""
    is_regression: bool = False
    severity: str = ""  # "warning" | "critical" | ""
    baseline_mean: float = 0.0
    baseline_stddev: float = 0.0
    current_value: float = 0.0
    deviation_sigma: float = 0.0
    metric_name: str = ""


@dataclass
class MetricRecord:
    """A single metric data point from SQLite."""
    name: str
    value: float
    timestamp: str = ""
    session_id: str | None = None
    tags: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Percentile helper (numpy-free)
# ---------------------------------------------------------------------------

def _percentile(sorted_values: list[float], p: float) -> float:
    """Compute percentile from a pre-sorted list (0-100 scale)."""
    if not sorted_values:
        return 0.0
    n = len(sorted_values)
    k = (p / 100.0) * (n - 1)
    f = math.floor(k)
    c = math.ceil(k)
    if f == c:
        return sorted_values[int(k)]
    return sorted_values[int(f)] * (c - k) + sorted_values[int(c)] * (k - f)


# ---------------------------------------------------------------------------
# MS4.1: PerformanceBaseline — SQLite-backed regression detection
# ---------------------------------------------------------------------------

class PerformanceBaseline:
    """SQLite-backed metrics with rolling baselines and regression detection.

    Thread-safe via connection-per-call pattern.
    """

    def __init__(self, db_path: str | Path | None = None) -> None:
        self._db_path = str(db_path) if db_path else ":memory:"
        self._baseline_cache: dict[str, tuple[float, BaselineStats]] = {}
        self._alert_cooldowns: dict[str, float] = {}
        self._lock = threading.Lock()
        self._ensure_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path, timeout=10)
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA busy_timeout=5000;")
        return conn

    def _ensure_schema(self) -> None:
        conn = self._connect()
        try:
            conn.execute(_PERF_CREATE_TABLE)
            conn.execute(_PERF_IDX_NAME_TS)
            conn.execute(_PERF_IDX_NAME_SID)
            conn.commit()
        finally:
            conn.close()

    # -- record -------------------------------------------------------------

    def record(
        self,
        name: str,
        value: float,
        session_id: str | None = None,
        tags: dict | None = None,
    ) -> None:
        """Record a metric value to SQLite."""
        tags_json = json.dumps(tags or {})
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        conn = self._connect()
        try:
            conn.execute(
                "INSERT INTO perf_metrics (name, value, timestamp, session_id, tags) "
                "VALUES (?, ?, ?, ?, ?)",
                (name, value, ts, session_id, tags_json),
            )
            conn.commit()
        finally:
            conn.close()

    # -- query --------------------------------------------------------------

    def query(
        self,
        name: str,
        start: str | None = None,
        end: str | None = None,
        limit: int = 1000,
    ) -> list[MetricRecord]:
        """Query metric records by name and optional time range."""
        clauses = ["name = ?"]
        params: list = [name]
        if start:
            clauses.append("timestamp >= ?")
            params.append(start)
        if end:
            clauses.append("timestamp <= ?")
            params.append(end)
        sql = (
            f"SELECT name, value, timestamp, session_id, tags "
            f"FROM perf_metrics WHERE {' AND '.join(clauses)} "
            f"ORDER BY timestamp DESC LIMIT ?"
        )
        params.append(limit)
        conn = self._connect()
        try:
            rows = conn.execute(sql, params).fetchall()
        finally:
            conn.close()
        results = []
        for row in rows:
            tags = {}
            try:
                tags = json.loads(row[4]) if row[4] else {}
            except (json.JSONDecodeError, TypeError):
                pass
            results.append(MetricRecord(
                name=row[0], value=row[1], timestamp=row[2],
                session_id=row[3], tags=tags,
            ))
        return results

    # -- baseline -----------------------------------------------------------

    def compute_baseline(
        self, name: str, window_days: int = 7,
    ) -> BaselineStats:
        """Compute rolling baseline stats.  Cached with 1-hour TTL."""
        cache_key = f"{name}:{window_days}"
        with self._lock:
            cached = self._baseline_cache.get(cache_key)
            if cached and (time.monotonic() - cached[0]) < BASELINE_CACHE_TTL:
                return cached[1]

        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT value FROM perf_metrics WHERE name = ? "
                "AND timestamp >= datetime('now', ?) "
                "ORDER BY timestamp DESC LIMIT ?",
                (name, f"-{window_days} days", MAX_QUERY_ROWS),
            ).fetchall()
        finally:
            conn.close()

        if not rows:
            return BaselineStats()

        values = [r[0] for r in rows]
        n = len(values)
        mean = sum(values) / n
        variance = sum((v - mean) ** 2 for v in values) / n if n > 1 else 0.0
        stddev = math.sqrt(variance)
        sorted_vals = sorted(values)

        stats = BaselineStats(
            mean=mean, stddev=stddev,
            min=sorted_vals[0], max=sorted_vals[-1],
            p50=_percentile(sorted_vals, 50),
            p95=_percentile(sorted_vals, 95),
            p99=_percentile(sorted_vals, 99),
            sample_count=n,
        )
        with self._lock:
            self._baseline_cache[cache_key] = (time.monotonic(), stats)
        return stats

    def invalidate_cache(self, name: str | None = None) -> None:
        """Clear baseline cache."""
        with self._lock:
            if name is None:
                self._baseline_cache.clear()
            else:
                keys = [k for k in self._baseline_cache if k.startswith(f"{name}:")]
                for k in keys:
                    del self._baseline_cache[k]

    # -- regression detection -----------------------------------------------

    def check_regression(
        self,
        name: str,
        current_value: float,
        sigma_threshold: float = 2.0,
        window_days: int = 7,
    ) -> RegressionResult:
        """Check if current_value is a regression relative to baseline."""
        baseline = self.compute_baseline(name, window_days)
        result = RegressionResult(
            metric_name=name,
            current_value=current_value,
            baseline_mean=baseline.mean,
            baseline_stddev=baseline.stddev,
        )
        if baseline.sample_count < MIN_BASELINE_SAMPLES:
            return result
        if baseline.stddev == 0:
            if current_value != baseline.mean:
                result.is_regression = True
                result.deviation_sigma = float("inf")
                result.severity = "critical"
            return result
        deviation = abs(current_value - baseline.mean) / baseline.stddev
        result.deviation_sigma = deviation
        if deviation >= sigma_threshold:
            result.is_regression = True
            result.severity = "critical" if deviation > 3.0 else "warning"
        return result

    # -- alert cooldown -----------------------------------------------------

    def should_alert(self, metric_name: str, cooldown_s: float = 3600.0) -> bool:
        """True if enough time has passed since last alert for this metric."""
        with self._lock:
            last = self._alert_cooldowns.get(metric_name, -float("inf"))
            now = time.monotonic()
            if now - last >= cooldown_s:
                self._alert_cooldowns[metric_name] = now
                return True
            return False

    # -- daily summary (markdown) -------------------------------------------

    def generate_summary_table(self) -> str:
        """Generate a markdown summary of all metrics in the last 24 hours."""
        conn = self._connect()
        try:
            names = conn.execute(
                "SELECT DISTINCT name FROM perf_metrics "
                "WHERE timestamp >= datetime('now', '-1 day')"
            ).fetchall()
        finally:
            conn.close()

        if not names:
            return "_No metrics recorded in the last 24 hours._"

        lines = [
            "| Metric | Min | Max | Mean | P50 | P95 | P99 | Count |",
            "|--------|-----|-----|------|-----|-----|-----|-------|",
        ]
        for (name,) in sorted(names):
            conn = self._connect()
            try:
                rows = conn.execute(
                    "SELECT value FROM perf_metrics WHERE name = ? "
                    "AND timestamp >= datetime('now', '-1 day')",
                    (name,),
                ).fetchall()
            finally:
                conn.close()
            if not rows:
                continue
            values = [r[0] for r in rows]
            n = len(values)
            mean = sum(values) / n
            sv = sorted(values)
            lines.append(
                f"| {name} | {sv[0]:.3f} | {sv[-1]:.3f} | {mean:.3f} "
                f"| {_percentile(sv, 50):.3f} | {_percentile(sv, 95):.3f} "
                f"| {_percentile(sv, 99):.3f} | {n} |"
            )
        return "\n".join(lines)

    # -- utilities ----------------------------------------------------------

    def list_metric_names(self) -> list[str]:
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT DISTINCT name FROM perf_metrics ORDER BY name"
            ).fetchall()
        finally:
            conn.close()
        return [r[0] for r in rows]

    def count(self, name: str | None = None) -> int:
        conn = self._connect()
        try:
            if name:
                row = conn.execute(
                    "SELECT COUNT(*) FROM perf_metrics WHERE name = ?", (name,)
                ).fetchone()
            else:
                row = conn.execute("SELECT COUNT(*) FROM perf_metrics").fetchone()
        finally:
            conn.close()
        return row[0] if row else 0

    def cleanup_old(self, retention_days: int = MAX_RETENTION_DAYS) -> int:
        """Delete metrics older than retention_days."""
        conn = self._connect()
        try:
            cur = conn.execute(
                "DELETE FROM perf_metrics WHERE timestamp < datetime('now', ?)",
                (f"-{retention_days} days",),
            )
            conn.commit()
            deleted = cur.rowcount
        finally:
            conn.close()
        return deleted


class MetricsCollector:
    """Collects counters and histograms, flushes to JSONL periodically.

    Thread-safe for single-writer async use. Not designed for multi-process.
    """

    def __init__(self, data_dir: str | Path = "data", flush_interval: int = 300) -> None:
        self._counters: dict[str, int] = defaultdict(int)
        self._histograms: dict[str, list[float]] = defaultdict(list)
        self._data_dir = Path(data_dir)
        self._flush_interval = flush_interval
        self._flush_task: asyncio.Task[None] | None = None
        self._last_used: dict[str, str] = {}  # metric → ISO timestamp of last increment
        self._last_used_minute = -1
        self._last_used_stamp = ""

    # -- Counter operations --

    def increment(self, metric: str, value: int = 1) -> None:
        """Increment a counter metric."""
        self._counters[metric] += value
        self._last_used[metric] = self._current_minute_stamp()

    def get_counter(self, metric: str) -> int:
        """Get current counter value."""
        return self._counters.get(metric, 0)

    def get_last_used(self, metric: str) -> str:
        """Get the ISO timestamp of the last increment for a metric, or empty string."""
        return self._last_used.get(metric, "")

    def _current_minute_stamp(self) -> str:
        """Return a cached UTC minute stamp for the counter hot path."""
        now = time.time()
        minute = int(now // 60)
        if minute != self._last_used_minute:
            self._last_used_minute = minute
            self._last_used_stamp = datetime.fromtimestamp(
                now, timezone.utc
            ).strftime("%Y-%m-%d %H:%M")
        return self._last_used_stamp

    # -- Histogram operations --

    def observe(self, metric: str, value: float) -> None:
        """Record a histogram observation (e.g. latency in seconds)."""
        self._histograms[metric].append(value)

    def get_histogram(self, metric: str) -> list[float]:
        """Get current histogram values."""
        return list(self._histograms.get(metric, []))

    # -- Timer context manager --

    def timer(self, metric: str) -> _Timer:
        """Context manager for timing operations. Records elapsed seconds."""
        return _Timer(self, metric)

    # -- Percentile computation --

    @staticmethod
    def compute_percentiles(values: list[float]) -> dict[str, float | int]:
        """Compute P50/P95/P99/min/max/avg from a list of values."""
        if not values:
            return {}
        s = sorted(values)
        n = len(s)
        return {
            "count": n,
            "min": round(s[0], 6),
            "p50": round(s[n // 2], 6),
            "p95": round(s[int(n * 0.95)], 6),
            "p99": round(s[int(n * 0.99)], 6),
            "max": round(s[-1], 6),
            "avg": round(sum(s) / n, 6),
        }

    # -- Snapshot (non-destructive read) --

    def snapshot(self) -> dict[str, Any]:
        """Return current metrics state without resetting."""
        return {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "counters": dict(self._counters),
            "histograms": {
                k: self.compute_percentiles(v)
                for k, v in self._histograms.items()
                if v
            },
        }

    # -- Flush to disk --

    async def flush(self) -> Path:
        """Write current metrics to JSONL file and reset."""
        entry = self.snapshot()
        metrics_file = self._data_dir / "metrics.jsonl"

        try:
            await asyncio.to_thread(self._write_jsonl_sync, metrics_file, entry)
        except Exception as e:
            logger.error("Failed to flush metrics to %s: %s", metrics_file, e)

        # Reset for next period
        self._counters.clear()
        self._histograms.clear()

        return metrics_file

    @staticmethod
    def _write_jsonl_sync(path: Path, entry: dict[str, Any]) -> None:
        """Synchronous JSONL append."""
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a") as f:
            f.write(json.dumps(entry) + "\n")

    # -- Background flush loop --

    async def start_flush_loop(self) -> None:
        """Start background task that flushes metrics every flush_interval seconds."""
        if self._flush_task is not None:
            return
        self._flush_task = asyncio.create_task(self._flush_loop(), name="metrics-flush")

    async def _flush_loop(self) -> None:
        """Periodic flush loop."""
        try:
            while True:
                await asyncio.sleep(self._flush_interval)
                if self._counters or self._histograms:
                    await self.flush()
        except asyncio.CancelledError:
            # Final flush on shutdown
            if self._counters or self._histograms:
                await self.flush()

    async def stop(self) -> None:
        """Stop the flush loop."""
        if self._flush_task and not self._flush_task.done():
            self._flush_task.cancel()
            try:
                await self._flush_task
            except asyncio.CancelledError:
                pass
        self._flush_task = None

    # -- Daily summary with anomaly detection --

    def load_metrics_file(self, path: Path | None = None) -> list[dict[str, Any]]:
        """Load all entries from a metrics JSONL file."""
        if path is None:
            path = self._data_dir / "metrics.jsonl"
        if not path.exists():
            return []
        entries = []
        for line in path.read_text().strip().split("\n"):
            if line.strip():
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        return entries

    def generate_daily_summary(
        self, today_entries: list[dict[str, Any]], week_entries: list[dict[str, Any]]
    ) -> dict[str, Any]:
        """Generate daily metrics summary with anomaly detection.

        Compares today's aggregated metrics against the 7-day historical average.
        Flags metrics with >2σ deviation as anomalies.
        """
        # Aggregate today's counters
        today_counters: dict[str, int] = defaultdict(int)
        today_histograms: dict[str, list[float]] = defaultdict(list)

        for entry in today_entries:
            for k, v in entry.get("counters", {}).items():
                today_counters[k] += v
            for k, hist in entry.get("histograms", {}).items():
                if "avg" in hist:
                    today_histograms[k].append(hist["avg"])

        # Aggregate weekly per-day averages
        week_daily: dict[str, list[float]] = defaultdict(list)
        for entry in week_entries:
            for k, v in entry.get("counters", {}).items():
                week_daily[f"counter:{k}"].append(v)
            for k, hist in entry.get("histograms", {}).items():
                if "avg" in hist:
                    week_daily[f"histogram:{k}"].append(hist["avg"])

        summary: dict[str, Any] = {"counters": {}, "histograms": {}, "anomalies": []}

        # Counter anomaly detection
        for k, v in today_counters.items():
            historical = week_daily.get(f"counter:{k}", [])
            anomaly_info = self._check_anomaly(float(v), historical)
            summary["counters"][k] = {"current": v, **anomaly_info}
            if anomaly_info.get("anomaly"):
                summary["anomalies"].append(f"counter:{k}")

        # Histogram anomaly detection
        for k, values in today_histograms.items():
            if not values:
                continue
            current_avg = sum(values) / len(values)
            historical = week_daily.get(f"histogram:{k}", [])
            anomaly_info = self._check_anomaly(current_avg, historical)
            summary["histograms"][k] = {"current": round(current_avg, 6), **anomaly_info}
            if anomaly_info.get("anomaly"):
                summary["anomalies"].append(f"histogram:{k}")

        return summary

    @staticmethod
    def _check_anomaly(current: float, historical: list[float]) -> dict[str, Any]:
        """Check if current value deviates >2σ from historical mean."""
        if not historical or len(historical) < 3:
            return {"7day_avg": None, "deviation_sigma": None, "anomaly": False}

        mean = sum(historical) / len(historical)
        variance = sum((x - mean) ** 2 for x in historical) / len(historical)
        stddev = variance ** 0.5

        if stddev == 0:
            deviation = 0.0
        else:
            deviation = abs(current - mean) / stddev

        return {
            "7day_avg": round(mean, 4),
            "deviation_sigma": round(deviation, 2),
            "anomaly": deviation > 2.0,
        }


class _Timer:
    """Context manager that records elapsed time to a MetricsCollector histogram."""

    def __init__(self, collector: MetricsCollector, metric: str) -> None:
        self._collector = collector
        self._metric = metric
        self._start = 0.0

    def __enter__(self) -> _Timer:
        self._start = time.monotonic()
        return self

    def __exit__(self, *args: object) -> None:
        elapsed = time.monotonic() - self._start
        self._collector.observe(self._metric, elapsed)
