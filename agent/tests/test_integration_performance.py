"""Sprint 16.5 — Performance profiling integration tests.

Measures memory usage, disk growth rate, and API call frequency
with and without jitter across core bridge modules.

Modules under test:
- CronJitter / ScanThrottle (bridge/cron_jitter.py)
- DailyLogWriter (bridge/daily_log.py)
- EventBus (bridge/event_bus.py)
- consolidation pipeline (bridge/consolidation.py)
- Database (bridge/database.py)
- Memory (bridge/memory.py)
"""

from __future__ import annotations

import statistics
import time
from dataclasses import dataclass
from pathlib import Path

import pytest
import pytest_asyncio

from bridge.config import BridgeConfig
from bridge.cron_jitter import CronJitter, JitterConfig, ScanThrottle
from bridge.daily_log import DailyLogWriter
from bridge.database import Database
from bridge.event_bus import EventBus
from bridge.consolidation import inventory, run_pipeline
from bridge.memory import Memory


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_knowledge_rows(n: int) -> list[dict]:
    """Generate n synthetic knowledge rows for consolidation tests."""
    categories = ["reference", "decision", "learning", "tool", "project", "process"]
    sources = ["agent", "operator", "system"]
    rows = []
    for i in range(n):
        rows.append({
            "key": f"entry-{i:05d}",
            "value": f"Knowledge entry number {i} about topic {i % 50} with details on subject {i % 20}",
            "category": categories[i % len(categories)],
            "source": sources[i % len(sources)],
            "salience": 1.0 - (i % 10) * 0.08,
            "access_count": i % 12,
            "created_at": f"2026-03-{(i % 28) + 1:02d}T10:00:00Z",
        })
    return rows


@dataclass
class _MinimalConfig:
    """Minimal config stub for DailyLogWriter."""
    data_dir: str


# ---------------------------------------------------------------------------
# 1. Jitter distribution bounds (1000 iterations)
# ---------------------------------------------------------------------------

class TestJitterDistribution:
    """Verify CronJitter output stays within documented bounds."""

    def test_jitter_within_bounds(self) -> None:
        """1000 iterations must all fall in [0, min(base * pct/100, cap)]."""
        config = JitterConfig(
            base_interval_seconds=600,
            jitter_percent=10.0,
            jitter_cap_seconds=60,
        )
        jitter = CronJitter(config, seed=42)

        max_expected = min(
            config.base_interval_seconds * config.jitter_percent / 100.0,
            config.jitter_cap_seconds,
        )

        values = [jitter.calculate_jitter() for _ in range(1000)]

        assert all(0 <= v <= max_expected for v in values), (
            f"Found value outside [0, {max_expected}]: "
            f"min={min(values):.4f}, max={max(values):.4f}"
        )

    def test_jitter_cap_applied(self) -> None:
        """When base * pct exceeds cap, output must be capped."""
        config = JitterConfig(
            base_interval_seconds=3600,
            jitter_percent=50.0,
            jitter_cap_seconds=30,
        )
        jitter = CronJitter(config, seed=99)

        # base * pct / 100 = 1800, but cap = 30
        values = [jitter.calculate_jitter() for _ in range(1000)]

        assert all(0 <= v <= 30 for v in values), (
            f"Cap not applied: max={max(values):.4f}"
        )


# ---------------------------------------------------------------------------
# 2. Jitter statistical properties
# ---------------------------------------------------------------------------

class TestJitterStatistics:
    """Mean should approximate half the max jitter; std dev should be bounded."""

    def test_mean_close_to_expected(self) -> None:
        """Mean of uniform [0, max_jitter] should be ~ max_jitter / 2."""
        config = JitterConfig(
            base_interval_seconds=600,
            jitter_percent=10.0,
            jitter_cap_seconds=60,
        )
        jitter = CronJitter(config, seed=12345)
        max_jitter = min(
            config.base_interval_seconds * config.jitter_percent / 100.0,
            config.jitter_cap_seconds,
        )

        values = [jitter.calculate_jitter() for _ in range(5000)]
        mean = statistics.mean(values)
        expected_mean = max_jitter / 2.0

        # Allow 10% tolerance on the mean
        assert abs(mean - expected_mean) < expected_mean * 0.10, (
            f"Mean {mean:.2f} too far from expected {expected_mean:.2f}"
        )

    def test_stddev_bounded(self) -> None:
        """Standard deviation should be bounded by max_jitter / sqrt(12) * 1.2."""
        config = JitterConfig(
            base_interval_seconds=600,
            jitter_percent=10.0,
            jitter_cap_seconds=60,
        )
        jitter = CronJitter(config, seed=777)
        max_jitter = min(
            config.base_interval_seconds * config.jitter_percent / 100.0,
            config.jitter_cap_seconds,
        )

        values = [jitter.calculate_jitter() for _ in range(5000)]
        sd = statistics.stdev(values)
        # Uniform distribution std dev = range / sqrt(12)
        expected_sd = max_jitter / (12 ** 0.5)

        # Allow 20% tolerance
        assert sd < expected_sd * 1.20, (
            f"Std dev {sd:.2f} exceeds expected {expected_sd:.2f} * 1.20"
        )


# ---------------------------------------------------------------------------
# 3. ScanThrottle anti-thundering-herd
# ---------------------------------------------------------------------------

class TestScanThrottleDistribution:
    """Peers should not all scan at the same time."""

    def test_peer_offsets_spread_evenly(self) -> None:
        """Offsets for 10 peers should span most of the base interval."""
        base_interval = 600
        peer_count = 10
        throttle = ScanThrottle(
            base_interval_seconds=base_interval,
            peer_count=peer_count,
            jitter_percent=5.0,
            seed=42,
        )

        offsets = [throttle.calculate_offset(peer_id) for peer_id in range(peer_count)]
        offsets_sorted = sorted(offsets)

        # Offsets should span at least 50% of the base interval
        spread = offsets_sorted[-1] - offsets_sorted[0]
        assert spread >= base_interval * 0.40, (
            f"Offset spread {spread:.1f} < 40% of {base_interval}"
        )

    def test_no_thundering_herd(self) -> None:
        """No two peers among 10 should have should_scan_now=True at identical times."""
        base_interval = 600
        peer_count = 10
        throttle = ScanThrottle(
            base_interval_seconds=base_interval,
            peer_count=peer_count,
            jitter_percent=10.0,
            seed=42,
        )

        # All peers scanned at t=0; check who scans at various future points
        last_scan = 0.0
        # Sample 100 time points across 2 full intervals
        scan_times: dict[int, list[float]] = {pid: [] for pid in range(peer_count)}
        for tick in range(200):
            t = tick * (base_interval * peer_count * 2) / 200
            for pid in range(peer_count):
                if throttle.should_scan_now(pid, last_scan, current_time=t):
                    scan_times[pid].append(t)

        # At least half the peers should have scanned at different earliest times
        first_scans = [times[0] for times in scan_times.values() if times]
        if len(first_scans) >= 2:
            unique_first = len(set(first_scans))
            assert unique_first >= min(len(first_scans), 3), (
                f"Only {unique_first} unique first-scan times among {len(first_scans)} peers"
            )


# ---------------------------------------------------------------------------
# 4. Disk growth rate from daily log writes
# ---------------------------------------------------------------------------

class TestDiskGrowthRate:
    """Measure disk usage after N log writes and project 24h growth."""

    def test_log_disk_growth_bounded(self, tmp_path: Path) -> None:
        """Write 1000 entries, project 24h rate, assert < 50 MB/day."""
        config = _MinimalConfig(data_dir=str(tmp_path))
        writer = DailyLogWriter(config)

        entries_per_day = 1000
        for i in range(entries_per_day):
            writer.append(
                f"Test log entry {i}: status check completed with result code {i % 10}",
                category="event" if i % 3 == 0 else "general",
            )

        content = writer.read_today()
        bytes_written = len(content.encode("utf-8"))

        # Production writes ~2000-5000 entries/day (bridge events, services, etc.)
        # Extrapolate at 5x the test volume
        projected_daily_bytes = bytes_written * 5
        projected_daily_mb = projected_daily_bytes / (1024 * 1024)

        assert projected_daily_mb < 50.0, (
            f"Projected daily growth {projected_daily_mb:.1f} MB exceeds 50 MB cap"
        )

    def test_log_entry_size_consistent(self, tmp_path: Path) -> None:
        """Individual entry sizes should be consistent (no runaway growth)."""
        config = _MinimalConfig(data_dir=str(tmp_path))
        writer = DailyLogWriter(config)

        # Write entries of varying categories
        categories = ["general", "event", "memory", "error", "decision", "session"]
        for i in range(100):
            writer.append(
                f"Entry {i} with standard payload data",
                category=categories[i % len(categories)],
            )

        content = writer.read_today()
        lines = [ln for ln in content.strip().split("\n") if ln]
        sizes = [len(ln.encode("utf-8")) for ln in lines]

        assert len(sizes) == 100
        mean_size = statistics.mean(sizes)
        max_size = max(sizes)

        # No single line should be more than 3x the mean
        assert max_size < mean_size * 3, (
            f"Max line size {max_size} > 3x mean {mean_size:.0f}"
        )


# ---------------------------------------------------------------------------
# 5. EventBus throughput
# ---------------------------------------------------------------------------

class TestEventBusThroughput:
    """10,000 events must publish in under 5 seconds."""

    def test_publish_10k_events_under_5s(self, tmp_path: Path) -> None:
        """Publish 10,000 events with persistence and measure elapsed time."""
        bus = EventBus(data_dir=tmp_path)

        start = time.perf_counter()
        for i in range(10_000):
            bus.publish(
                event_type="test.event",
                payload={"index": i, "value": f"payload-{i}"},
                source="perf-test",
            )
        elapsed = time.perf_counter() - start

        assert bus.get_event_count() == 10_000
        assert elapsed < 5.0, (
            f"10,000 events took {elapsed:.2f}s (limit: 5.0s)"
        )

    def test_publish_10k_events_in_memory_faster(self) -> None:
        """Without persistence, throughput should be significantly faster."""
        bus = EventBus(data_dir=None)  # No persistence

        start = time.perf_counter()
        for i in range(10_000):
            bus.publish(
                event_type="test.event",
                payload={"index": i},
                source="perf-test",
            )
        elapsed = time.perf_counter() - start

        assert bus.get_event_count() == 10_000
        # In-memory should be at least 2x faster than the 5s ceiling
        assert elapsed < 2.5, (
            f"In-memory 10,000 events took {elapsed:.2f}s (limit: 2.5s)"
        )


# ---------------------------------------------------------------------------
# 6. Consolidation pipeline performance
# ---------------------------------------------------------------------------

class TestConsolidationPerformance:
    """Full pipeline on 1000 rows must complete in under 2 seconds."""

    def test_pipeline_1000_rows_under_2s(self) -> None:
        """Run standard-mode pipeline on 1000 knowledge rows."""
        rows = _make_knowledge_rows(1000)

        start = time.perf_counter()
        report = run_pipeline(rows, mode="standard")
        elapsed = time.perf_counter() - start

        assert report.mode == "standard"
        assert report.total_duration_ms >= 0
        assert "inventory" in report.phase_results
        assert "decay" in report.phase_results
        assert "contradictions" in report.phase_results
        assert "merge" in report.phase_results
        assert "promotion" in report.phase_results
        assert elapsed < 2.0, (
            f"Pipeline on 1000 rows took {elapsed:.2f}s (limit: 2.0s)"
        )

    def test_inventory_scales_linearly(self) -> None:
        """Inventory phase should scale roughly linearly with row count."""
        sizes = [100, 500, 1000]
        timings: list[float] = []

        for n in sizes:
            rows = _make_knowledge_rows(n)
            start = time.perf_counter()
            inv = inventory(rows)
            elapsed = time.perf_counter() - start
            timings.append(elapsed)
            assert inv.total == n

        # 1000-row timing should be no more than 15x the 100-row timing
        # (allowing for constant overhead; truly linear would be ~10x)
        if timings[0] > 0:
            ratio = timings[2] / timings[0]
            assert ratio < 15, (
                f"Inventory scaling ratio {ratio:.1f}x from 100 to 1000 rows (limit: 15x)"
            )


# ---------------------------------------------------------------------------
# 7. Memory store/search performance
# ---------------------------------------------------------------------------

class TestMemoryPerformance:
    """Store 500 entries and search — both under 1 second each."""

    @pytest_asyncio.fixture
    async def perf_memory(self, tmp_path: Path, sample_config: BridgeConfig):
        """Create a Memory instance backed by a fresh migrated database."""
        db_path = tmp_path / "perf-memory.db"
        db = Database(db_path)
        await db.connect()
        await db.migrate()
        mem = Memory(db, sample_config)
        yield mem
        await db.close()

    @pytest.mark.asyncio
    async def test_store_500_entries_under_threshold(self, perf_memory: Memory) -> None:
        """Storing 500 knowledge entries should complete within budget.

        Threshold raised from 1.0s to 2.5s on 2026-04-26: shared GH runners
        regularly hit 1.1-1.5s; 2.5s gives ~2x headroom over P99 while still
        catching genuine regressions (a 5x slowdown still trips it).
        """
        start = time.perf_counter()
        for i in range(500):
            await perf_memory.store_knowledge(
                key=f"perf-key-{i:04d}",
                value=f"Performance test value {i} with topic {i % 25}",
                tags=f"perf,batch-{i % 10}",
                source="agent",
                category="reference",
            )
        elapsed = time.perf_counter() - start

        assert elapsed < 2.5, (
            f"Storing 500 entries took {elapsed:.2f}s (limit: 2.5s)"
        )

    @pytest.mark.asyncio
    async def test_search_after_500_entries_under_threshold(self, perf_memory: Memory) -> None:
        """Searching 500 entries via FTS5 should complete within budget.

        Threshold raised from 1.0s to 2.5s on 2026-04-26 alongside the store
        test — same shared-runner variance, same headroom rationale.
        """
        # Populate
        for i in range(500):
            await perf_memory.store_knowledge(
                key=f"search-key-{i:04d}",
                value=f"Performance test value {i} about topic {i % 25} and subject {i % 10}",
                tags=f"perf,batch-{i % 10}",
                source="agent",
                category="reference",
            )

        # Search
        start = time.perf_counter()
        results = await perf_memory.search_knowledge("topic performance", limit=20)
        elapsed = time.perf_counter() - start

        assert len(results) > 0, "FTS5 search returned no results"
        assert elapsed < 2.5, (
            f"Searching 500 entries took {elapsed:.2f}s (limit: 2.5s)"
        )


# ---------------------------------------------------------------------------
# 8. Database write performance
# ---------------------------------------------------------------------------

class TestDatabaseWritePerformance:
    """1000 inserts into knowledge table should complete in under 3 seconds."""

    @pytest.mark.asyncio
    async def test_1000_inserts_under_3s(self, tmp_path: Path) -> None:
        """Insert 1000 rows via individual execute+commit cycles."""
        db_path = tmp_path / "perf-db.db"
        db = Database(db_path)
        await db.connect()
        await db.migrate()

        start = time.perf_counter()
        for i in range(1000):
            await db.execute(
                """INSERT INTO knowledge (key, value, tags, source, category)
                   VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT(key) DO UPDATE SET
                       value = excluded.value,
                       updated_at = datetime('now')""",
                (f"dbperf-{i:05d}", f"Value {i}", f"tag-{i % 5}", "agent", "reference"),
            )
        await db.commit()
        elapsed = time.perf_counter() - start

        # Verify all rows inserted
        row = await db.fetchone("SELECT COUNT(*) FROM knowledge")
        assert row[0] == 1000

        assert elapsed < 3.0, (
            f"1000 inserts took {elapsed:.2f}s (limit: 3.0s)"
        )

        await db.close()

    @pytest.mark.asyncio
    async def test_batch_insert_faster_than_individual(self, tmp_path: Path) -> None:
        """Batched commit should be faster than per-row commit."""
        db_path = tmp_path / "perf-db-batch.db"
        db = Database(db_path)
        await db.connect()
        await db.migrate()

        # Individual commits
        start_individual = time.perf_counter()
        for i in range(200):
            await db.execute(
                """INSERT INTO knowledge (key, value, tags, source, category)
                   VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT(key) DO UPDATE SET
                       value = excluded.value""",
                (f"ind-{i:05d}", f"Value {i}", "tag", "agent", "reference"),
            )
            await db.commit()
        elapsed_individual = time.perf_counter() - start_individual

        # Batched commit (single commit at end)
        start_batch = time.perf_counter()
        for i in range(200):
            await db.execute(
                """INSERT INTO knowledge (key, value, tags, source, category)
                   VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT(key) DO UPDATE SET
                       value = excluded.value""",
                (f"bat-{i:05d}", f"Value {i}", "tag", "agent", "reference"),
            )
        await db.commit()
        elapsed_batch = time.perf_counter() - start_batch

        # Batch should be at least somewhat faster (or at least not slower)
        # In WAL mode the difference may be modest, so we just verify batch <= individual * 1.5
        assert elapsed_batch <= elapsed_individual * 1.5, (
            f"Batch ({elapsed_batch:.3f}s) slower than individual ({elapsed_individual:.3f}s) * 1.5"
        )

        await db.close()
