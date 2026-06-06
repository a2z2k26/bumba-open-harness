"""Tests for MS1.8 + MS4.1: Operational Metrics & Regression Detection."""

from __future__ import annotations

import json
import time
import threading

import pytest

from bridge.metrics import (
    MetricsCollector,
    PerformanceBaseline,
    _percentile,
)


class TestCounter:
    """Counter operations."""

    def test_increment_default(self):
        m = MetricsCollector()
        m.increment("messages_total")
        assert m.get_counter("messages_total") == 1

    def test_increment_by_value(self):
        m = MetricsCollector()
        m.increment("messages_total", 5)
        assert m.get_counter("messages_total") == 5

    def test_increment_accumulates(self):
        m = MetricsCollector()
        m.increment("x")
        m.increment("x")
        m.increment("x", 3)
        assert m.get_counter("x") == 5

    def test_get_counter_missing(self):
        m = MetricsCollector()
        assert m.get_counter("nonexistent") == 0


class TestHistogram:
    """Histogram and percentile operations."""

    def test_observe_single(self):
        m = MetricsCollector()
        m.observe("latency", 1.5)
        assert m.get_histogram("latency") == [1.5]

    def test_observe_multiple(self):
        m = MetricsCollector()
        m.observe("latency", 1.0)
        m.observe("latency", 2.0)
        m.observe("latency", 3.0)
        assert len(m.get_histogram("latency")) == 3

    def test_get_histogram_missing(self):
        m = MetricsCollector()
        assert m.get_histogram("nonexistent") == []

    def test_percentiles_basic(self):
        values = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0]
        result = MetricsCollector.compute_percentiles(values)
        assert result["count"] == 10
        assert result["min"] == 1.0
        assert result["max"] == 10.0
        assert result["p50"] == 6.0  # index 5
        assert result["avg"] == 5.5

    def test_percentiles_empty(self):
        assert MetricsCollector.compute_percentiles([]) == {}

    def test_percentiles_single(self):
        result = MetricsCollector.compute_percentiles([42.0])
        assert result["count"] == 1
        assert result["min"] == 42.0
        assert result["max"] == 42.0
        assert result["p50"] == 42.0


class TestTimer:
    """Timer context manager."""

    def test_timer_records_elapsed(self):
        m = MetricsCollector()
        with m.timer("op_time"):
            time.sleep(0.01)
        values = m.get_histogram("op_time")
        assert len(values) == 1
        assert values[0] >= 0.01

    def test_timer_multiple(self):
        m = MetricsCollector()
        for _ in range(3):
            with m.timer("op_time"):
                pass
        assert len(m.get_histogram("op_time")) == 3


class TestSnapshot:
    """Snapshot (non-destructive read)."""

    def test_snapshot_includes_counters(self):
        m = MetricsCollector()
        m.increment("a", 10)
        snap = m.snapshot()
        assert snap["counters"]["a"] == 10

    def test_snapshot_includes_histograms(self):
        m = MetricsCollector()
        m.observe("lat", 1.0)
        m.observe("lat", 2.0)
        snap = m.snapshot()
        assert "lat" in snap["histograms"]
        assert snap["histograms"]["lat"]["count"] == 2

    def test_snapshot_has_timestamp(self):
        m = MetricsCollector()
        snap = m.snapshot()
        assert "timestamp" in snap

    def test_snapshot_non_destructive(self):
        m = MetricsCollector()
        m.increment("x")
        m.snapshot()
        assert m.get_counter("x") == 1  # Not reset


class TestFlush:
    """Flush to JSONL."""

    @pytest.mark.asyncio
    async def test_flush_writes_file(self, tmp_path):
        m = MetricsCollector(data_dir=str(tmp_path))
        m.increment("messages", 42)
        m.observe("latency", 1.5)
        path = await m.flush()
        assert path.exists()
        data = json.loads(path.read_text().strip())
        assert data["counters"]["messages"] == 42
        assert "latency" in data["histograms"]

    @pytest.mark.asyncio
    async def test_flush_resets(self, tmp_path):
        m = MetricsCollector(data_dir=str(tmp_path))
        m.increment("x", 10)
        m.observe("y", 5.0)
        await m.flush()
        assert m.get_counter("x") == 0
        assert m.get_histogram("y") == []

    @pytest.mark.asyncio
    async def test_flush_appends(self, tmp_path):
        m = MetricsCollector(data_dir=str(tmp_path))
        m.increment("a", 1)
        await m.flush()
        m.increment("b", 2)
        await m.flush()
        lines = (tmp_path / "metrics.jsonl").read_text().strip().split("\n")
        assert len(lines) == 2


class TestDailySummary:
    """Daily summary with anomaly detection."""

    def test_anomaly_detected(self):
        m = MetricsCollector()
        # Historical: values around 10
        week = [
            {"counters": {"messages": 10}},
            {"counters": {"messages": 11}},
            {"counters": {"messages": 9}},
            {"counters": {"messages": 10}},
            {"counters": {"messages": 10}},
        ]
        # Today: value of 100 — 3σ+ deviation
        today = [{"counters": {"messages": 100}}]
        summary = m.generate_daily_summary(today, week)
        assert summary["counters"]["messages"]["anomaly"] is True
        assert "counter:messages" in summary["anomalies"]

    def test_no_anomaly_normal(self):
        m = MetricsCollector()
        week = [
            {"counters": {"messages": 10}},
            {"counters": {"messages": 11}},
            {"counters": {"messages": 9}},
            {"counters": {"messages": 10}},
        ]
        today = [{"counters": {"messages": 10}}]
        summary = m.generate_daily_summary(today, week)
        assert summary["counters"]["messages"]["anomaly"] is False

    def test_anomaly_insufficient_data(self):
        m = MetricsCollector()
        # Less than 3 historical points → no anomaly
        week = [{"counters": {"messages": 10}}]
        today = [{"counters": {"messages": 1000}}]
        summary = m.generate_daily_summary(today, week)
        assert summary["counters"]["messages"]["anomaly"] is False

    def test_histogram_anomaly(self):
        m = MetricsCollector()
        week = [
            {"histograms": {"latency": {"avg": 1.0}}},
            {"histograms": {"latency": {"avg": 1.1}}},
            {"histograms": {"latency": {"avg": 0.9}}},
            {"histograms": {"latency": {"avg": 1.0}}},
        ]
        # Today: latency spike
        today = [{"histograms": {"latency": {"avg": 10.0}}}]
        summary = m.generate_daily_summary(today, week)
        assert summary["histograms"]["latency"]["anomaly"] is True

    def test_empty_today(self):
        m = MetricsCollector()
        summary = m.generate_daily_summary([], [])
        assert summary["anomalies"] == []


@pytest.mark.perf
class TestPerformance:
    """Verify metrics overhead is acceptable.

    Marked ``perf`` (Sprint R7.2, #1910) — deselected from coverage runs
    because pytest-cov instrumentation distorts the wall-clock budgets
    below by 10-30%. Budgets are intentionally generous (catch
    order-of-magnitude regressions, not micro-optimizations); see
    ``docs/testing/performance-budgets.md`` for the rationale and
    update protocol.
    """

    def test_observe_overhead(self):
        m = MetricsCollector()
        start = time.monotonic()
        for i in range(10000):
            m.observe("latency", float(i))
        elapsed = time.monotonic() - start
        # 10000 observations should complete in <100ms
        assert elapsed < 0.1, f"10000 observe() calls took {elapsed:.3f}s"

    def test_increment_overhead(self):
        m = MetricsCollector()
        start = time.monotonic()
        for _ in range(10000):
            m.increment("messages")
        elapsed = time.monotonic() - start
        assert elapsed < 0.1, f"10000 increment() calls took {elapsed:.3f}s"


# ═══════════════════════════════════════════════════════════════════════════
# MS4.1: PerformanceBaseline — SQLite-backed regression detection
# ═══════════════════════════════════════════════════════════════════════════


class TestPercentileHelper:
    """Numpy-free percentile computation."""

    def test_p50_odd(self):
        assert _percentile([1, 2, 3, 4, 5], 50) == 3.0

    def test_p50_even(self):
        assert abs(_percentile([1, 2, 3, 4], 50) - 2.5) < 1e-6

    def test_p0_and_p100(self):
        vals = [10, 20, 30]
        assert _percentile(vals, 0) == 10
        assert _percentile(vals, 100) == 30

    def test_empty(self):
        assert _percentile([], 50) == 0.0


class TestPerformanceBaselineRecordQuery:
    """Record and query operations."""

    def test_record_and_query(self, tmp_path):
        pb = PerformanceBaseline(tmp_path / "metrics.db")
        for i in range(100):
            pb.record("latency", float(i), session_id="s1")
        records = pb.query("latency", limit=1000)
        assert len(records) == 100

    def test_query_time_range(self, tmp_path):
        pb = PerformanceBaseline(tmp_path / "metrics.db")
        pb.record("latency", 10.0)
        pb.record("latency", 20.0)
        # Query with very old start — should return both
        records = pb.query("latency", start="2000-01-01 00:00:00")
        assert len(records) == 2

    def test_query_limit(self, tmp_path):
        pb = PerformanceBaseline(tmp_path / "metrics.db")
        for i in range(20):
            pb.record("latency", float(i))
        records = pb.query("latency", limit=5)
        assert len(records) == 5

    def test_record_with_tags(self, tmp_path):
        pb = PerformanceBaseline(tmp_path / "metrics.db")
        pb.record("latency", 42.0, tags={"model": "sonnet"})
        records = pb.query("latency")
        assert records[0].tags == {"model": "sonnet"}

    def test_count(self, tmp_path):
        pb = PerformanceBaseline(tmp_path / "metrics.db")
        assert pb.count() == 0
        pb.record("a", 1.0)
        pb.record("b", 2.0)
        assert pb.count() == 2
        assert pb.count("a") == 1

    def test_list_metric_names(self, tmp_path):
        pb = PerformanceBaseline(tmp_path / "metrics.db")
        pb.record("alpha", 1.0)
        pb.record("beta", 2.0)
        pb.record("alpha", 3.0)
        names = pb.list_metric_names()
        assert names == ["alpha", "beta"]


class TestBaselineComputation:
    """Rolling baseline computation."""

    def test_compute_baseline_stats(self, tmp_path):
        pb = PerformanceBaseline(tmp_path / "metrics.db")
        # Known dataset: 1..100
        for i in range(1, 101):
            pb.record("val", float(i))
        stats = pb.compute_baseline("val")
        assert stats.sample_count == 100
        assert abs(stats.mean - 50.5) < 0.01
        assert stats.min == 1.0
        assert stats.max == 100.0
        assert stats.stddev > 0

    def test_baseline_empty(self, tmp_path):
        pb = PerformanceBaseline(tmp_path / "metrics.db")
        stats = pb.compute_baseline("missing")
        assert stats.sample_count == 0
        assert stats.mean == 0.0

    def test_baseline_cache_hit(self, tmp_path):
        pb = PerformanceBaseline(tmp_path / "metrics.db")
        for i in range(20):
            pb.record("val", float(i))
        s1 = pb.compute_baseline("val")
        # Add more data
        pb.record("val", 999.0)
        # Should return cached (same object)
        s2 = pb.compute_baseline("val")
        assert s1.sample_count == s2.sample_count  # cached

    def test_invalidate_cache(self, tmp_path):
        pb = PerformanceBaseline(tmp_path / "metrics.db")
        for i in range(20):
            pb.record("val", float(i))
        pb.compute_baseline("val")
        pb.invalidate_cache("val")
        pb.record("val", 999.0)
        s = pb.compute_baseline("val")
        assert s.sample_count == 21  # includes new value


class TestRegressionDetection:
    """Regression detection via sigma thresholds."""

    def test_no_regression_normal(self, tmp_path):
        pb = PerformanceBaseline(tmp_path / "metrics.db")
        for i in range(50):
            pb.record("latency", 100.0 + (i % 5))
        result = pb.check_regression("latency", 102.0)
        assert result.is_regression is False

    def test_regression_warning(self, tmp_path):
        pb = PerformanceBaseline(tmp_path / "metrics.db")
        # Record tight cluster around 100
        for _ in range(50):
            pb.record("latency", 100.0)
        for _ in range(50):
            pb.record("latency", 101.0)
        pb.invalidate_cache()
        stats = pb.compute_baseline("latency")
        # 2.5 sigma above mean
        spike = stats.mean + 2.5 * stats.stddev
        result = pb.check_regression("latency", spike)
        assert result.is_regression is True
        assert result.severity == "warning"

    def test_regression_critical(self, tmp_path):
        pb = PerformanceBaseline(tmp_path / "metrics.db")
        for _ in range(50):
            pb.record("latency", 100.0)
        for _ in range(50):
            pb.record("latency", 102.0)
        pb.invalidate_cache()
        stats = pb.compute_baseline("latency")
        spike = stats.mean + 4.0 * stats.stddev
        result = pb.check_regression("latency", spike)
        assert result.is_regression is True
        assert result.severity == "critical"

    def test_regression_insufficient_data(self, tmp_path):
        pb = PerformanceBaseline(tmp_path / "metrics.db")
        for i in range(5):  # < MIN_BASELINE_SAMPLES
            pb.record("latency", 100.0)
        result = pb.check_regression("latency", 999.0)
        assert result.is_regression is False

    def test_regression_zero_stddev(self, tmp_path):
        pb = PerformanceBaseline(tmp_path / "metrics.db")
        for _ in range(20):
            pb.record("val", 50.0)
        result = pb.check_regression("val", 51.0)
        assert result.is_regression is True
        assert result.severity == "critical"

    def test_no_regression_zero_stddev_same(self, tmp_path):
        pb = PerformanceBaseline(tmp_path / "metrics.db")
        for _ in range(20):
            pb.record("val", 50.0)
        result = pb.check_regression("val", 50.0)
        assert result.is_regression is False


class TestAlertCooldown:
    """Alert cooldown prevents spam."""

    def test_first_alert_allowed(self, tmp_path):
        pb = PerformanceBaseline(tmp_path / "metrics.db")
        assert pb.should_alert("latency") is True

    def test_second_alert_blocked(self, tmp_path):
        pb = PerformanceBaseline(tmp_path / "metrics.db")
        assert pb.should_alert("latency", cooldown_s=3600.0) is True
        assert pb.should_alert("latency", cooldown_s=3600.0) is False

    def test_different_metrics_independent(self, tmp_path):
        pb = PerformanceBaseline(tmp_path / "metrics.db")
        assert pb.should_alert("a") is True
        assert pb.should_alert("b") is True  # Different metric, allowed

    def test_cooldown_expires(self, tmp_path):
        pb = PerformanceBaseline(tmp_path / "metrics.db")
        assert pb.should_alert("latency", cooldown_s=0.01) is True
        time.sleep(0.02)
        assert pb.should_alert("latency", cooldown_s=0.01) is True


class TestSummaryTable:
    """Daily summary markdown generation."""

    def test_summary_no_data(self, tmp_path):
        pb = PerformanceBaseline(tmp_path / "metrics.db")
        result = pb.generate_summary_table()
        assert "No metrics" in result

    def test_summary_has_header(self, tmp_path):
        pb = PerformanceBaseline(tmp_path / "metrics.db")
        pb.record("latency", 100.0)
        pb.record("latency", 200.0)
        result = pb.generate_summary_table()
        assert "Metric" in result
        assert "Min" in result
        assert "latency" in result


class TestConcurrentRecording:
    """Thread safety."""

    def test_concurrent_writes(self, tmp_path):
        pb = PerformanceBaseline(tmp_path / "metrics.db")
        errors = []

        def writer(thread_id: int):
            try:
                for i in range(50):
                    pb.record("latency", float(thread_id * 100 + i))
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=writer, args=(t,)) for t in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, f"Thread errors: {errors}"
        assert pb.count("latency") == 500


class TestCleanup:
    """Retention cleanup."""

    def test_cleanup_returns_count(self, tmp_path):
        pb = PerformanceBaseline(tmp_path / "metrics.db")
        pb.record("x", 1.0)
        # Recent data won't be cleaned up
        deleted = pb.cleanup_old(retention_days=90)
        assert deleted == 0
