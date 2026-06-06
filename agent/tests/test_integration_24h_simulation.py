"""Sprint 16.1 — 24-hour simulation integration tests.

Exercises time progression, daily log rollover, consolidation triggers,
proactive tick state cycling, and cron jitter bounds across a simulated
24-hour bridge operation window.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from bridge.consolidation import (
    ConsolidationReport,
    ContradictionResult,
    DecayResult,
    InventoryReport,
    MergeResult,
    PromotionResult,
    decay,
    find_contradictions,
    inventory,
    merge_duplicates,
    promote_patterns,
    run_pipeline,
)
from bridge.cron_jitter import CronJitter, JitterConfig
from bridge.daily_log import DailyLogWriter
from bridge.tick_manager import TickContext, TickManager, TickState


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_config(tmp_path):
    """Build a minimal config namespace pointing data_dir at tmp_path."""
    return SimpleNamespace(data_dir=str(tmp_path))


_LOCAL_TZ = timezone.utc  # UTC — ensures .astimezone() never shifts the date in CI (UTC host)


def _fake_now(year, month, day, hour=12, minute=0, second=0):
    """Return a UTC-aware datetime.

    Using UTC with midday defaults ensures .astimezone() never crosses a date
    boundary regardless of the host timezone (safe from UTC-12 to UTC+12).
    """
    return datetime(year, month, day, hour, minute, second, tzinfo=_LOCAL_TZ)


def _build_knowledge_rows(n: int, *, category: str = "project", source: str = "agent") -> list[dict]:
    """Generate n synthetic knowledge rows for consolidation tests."""
    rows = []
    for i in range(n):
        rows.append({
            "key": f"k{i:04d}",
            "value": f"knowledge entry number {i} about project infrastructure and deployment pipeline",
            "category": category,
            "source": source,
            "salience": 1.0 - (i * 0.01),
            "access_count": i % 8,
            "created_at": f"2026-04-0{(i % 3) + 1}T{10 + (i % 12):02d}:00:00Z",
        })
    return rows


# ---------------------------------------------------------------------------
# Daily Log — Rollover Tests
# ---------------------------------------------------------------------------


class TestDailyLogRollover:
    """Verify log files split correctly at the midnight boundary."""

    def test_entries_land_in_correct_date_file(self, tmp_path):
        """Entries written at different simulated dates create separate files."""
        cfg = _make_config(tmp_path)
        writer = DailyLogWriter(cfg)

        april_2 = _fake_now(2026, 4, 2)   # midday UTC — safe in all timezones
        april_3 = _fake_now(2026, 4, 3)

        with patch("bridge.daily_log.datetime") as mock_dt:
            mock_dt.now.return_value = april_2
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            writer.append("april 2 entry", category="event")

            mock_dt.now.return_value = april_3
            writer.append("april 3 entry", category="event")

        log_apr2 = tmp_path / "logs" / "2026" / "04" / "2026-04-02.md"
        log_apr3 = tmp_path / "logs" / "2026" / "04" / "2026-04-03.md"

        assert log_apr2.exists(), "April 2 log file should exist"
        assert log_apr3.exists(), "April 3 log file should exist"

        text_apr2 = log_apr2.read_text()
        text_apr3 = log_apr3.read_text()

        assert "april 2 entry" in text_apr2
        assert "april 3 entry" in text_apr3
        assert "april 3 entry" not in text_apr2
        assert "april 2 entry" not in text_apr3

    def test_read_date_returns_correct_content(self, tmp_path):
        """read_date retrieves the right file for a given date."""
        cfg = _make_config(tmp_path)
        writer = DailyLogWriter(cfg)

        target_dt = _fake_now(2026, 4, 2, 14, 30)

        with patch("bridge.daily_log.datetime") as mock_dt:
            mock_dt.now.return_value = target_dt
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            writer.append("afternoon note")

        content = writer.read_date(target_dt)
        assert "afternoon note" in content

    def test_list_recent_spans_multiple_days(self, tmp_path):
        """list_recent returns log paths across a multi-day window."""
        cfg = _make_config(tmp_path)
        writer = DailyLogWriter(cfg)

        # Write one entry per day for 3 consecutive days
        for day_offset in range(3):
            dt = _fake_now(2026, 4, 1 + day_offset, 12, 0)
            with patch("bridge.daily_log.datetime") as mock_dt:
                mock_dt.now.return_value = dt
                mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
                writer.append(f"entry for day offset {day_offset}")

        # list_recent uses datetime.now internally; pin it to April 3
        with patch("bridge.daily_log.datetime") as mock_dt:
            mock_dt.now.return_value = _fake_now(2026, 4, 3, 18, 0)
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            recent = writer.list_recent(days=5)

        assert len(recent) == 3

    def test_category_tags_appear_in_output(self, tmp_path):
        """Category tags are written as [tag] prefixes in the log line."""
        cfg = _make_config(tmp_path)
        writer = DailyLogWriter(cfg)

        now = _fake_now(2026, 4, 3, 9, 15)
        with patch("bridge.daily_log.datetime") as mock_dt:
            mock_dt.now.return_value = now
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            writer.append("memory stored", category="memory")
            writer.append("plain entry")

        content = writer.read_date(now)
        assert "[memory]" in content
        # general category should NOT produce a tag
        assert "[general]" not in content


# ---------------------------------------------------------------------------
# Consolidation Pipeline Tests
# ---------------------------------------------------------------------------


class TestConsolidationPipeline:
    """Test the consolidation pipeline with accumulated knowledge rows."""

    def test_inventory_counts_categories(self):
        """Phase 1 inventory correctly counts by category and source."""
        rows = _build_knowledge_rows(20, category="project", source="agent")
        rows += _build_knowledge_rows(10, category="decision", source="operator")

        report = inventory(rows)

        assert isinstance(report, InventoryReport)
        assert report.total == 30
        assert report.by_category["project"] == 20
        assert report.by_category["decision"] == 10
        assert report.by_source["agent"] == 20
        assert report.by_source["operator"] == 10
        assert report.oldest_entry is not None
        assert report.newest_entry is not None

    def test_decay_reduces_salience_over_simulated_days(self):
        """Phase 2 decay reduces salience progressively over multiple days."""
        rows = _build_knowledge_rows(5, category="project", source="agent")
        original_saliences = [r["salience"] for r in rows]

        # Simulate 7 days of decay
        result = decay(rows, days_elapsed=7)

        assert isinstance(result, DecayResult)
        assert result.processed == 5

        for i, row in enumerate(rows):
            if row["_action"] == "decay":
                assert row["_new_salience"] < original_saliences[i]
            elif row["_action"] == "prune":
                assert row["_new_salience"] < 0.1  # Below prune threshold

    def test_decay_exempts_operator_source(self):
        """Entries from the operator source are exempt from decay."""
        rows = [
            {"key": "op1", "category": "project", "source": "operator", "salience": 0.5},
        ]

        result = decay(rows, days_elapsed=30)
        assert result.exempt == 1
        assert rows[0]["_action"] == "exempt"

    def test_contradiction_detection_with_negation(self):
        """Phase 3 finds contradictions when one entry negates another."""
        rows = [
            {"key": "k1", "value": "always deploy using the blue-green deployment strategy", "category": "decision"},
            {"key": "k2", "value": "never deploy using the blue-green deployment strategy", "category": "decision"},
        ]

        result = find_contradictions(rows)

        assert isinstance(result, ContradictionResult)
        assert result.contradictions_found >= 1
        assert result.details[0]["reason"] == "negation_mismatch"

    def test_merge_duplicates_archives_lower_salience(self):
        """Phase 4 merges near-duplicates, keeping the higher-salience entry."""
        rows = [
            {"key": "k1", "value": "deployment pipeline uses docker containers for isolation", "salience": 0.9, "category": "project"},
            {"key": "k2", "value": "deployment pipeline uses docker containers for isolation builds", "salience": 0.5, "category": "project"},
        ]

        result = merge_duplicates(rows, similarity_threshold=0.7)

        assert isinstance(result, MergeResult)
        assert result.merged >= 1
        # Higher salience entry (k1, 0.9) should be kept
        assert rows[0].get("_merge_action") == "keep"
        assert rows[1].get("_merge_action") == "archive"

    def test_promote_patterns_promotes_high_access(self):
        """Phase 5 promotes entries accessed frequently."""
        rows = [
            {"key": "k1", "access_count": 10, "salience": 1.0},
            {"key": "k2", "access_count": 0, "salience": 0.3},
            {"key": "k3", "access_count": 2, "salience": 1.0},
        ]

        result = promote_patterns(rows, access_threshold=5)

        assert isinstance(result, PromotionResult)
        assert result.promoted == 1  # k1
        assert result.demoted == 1   # k2 (access_count=0, salience<0.5)
        assert result.evaluated == 3
        assert rows[0]["_promotion_action"] == "promote"
        assert rows[1]["_promotion_action"] == "demote"
        assert rows[2]["_promotion_action"] == "none"

    def test_full_pipeline_standard_mode(self):
        """Full pipeline in standard mode runs all 5 phases and returns a report."""
        rows = _build_knowledge_rows(15)

        report = run_pipeline(rows, mode="standard")

        assert isinstance(report, ConsolidationReport)
        assert report.mode == "standard"
        assert "inventory" in report.phase_results
        assert "decay" in report.phase_results
        assert "contradictions" in report.phase_results
        assert "merge" in report.phase_results
        assert "promotion" in report.phase_results
        assert report.total_duration_ms >= 0

    def test_micro_mode_stops_after_decay(self):
        """Micro mode only runs inventory and decay phases."""
        rows = _build_knowledge_rows(10)

        report = run_pipeline(rows, mode="micro")

        assert report.mode == "micro"
        assert "inventory" in report.phase_results
        assert "decay" in report.phase_results
        assert "contradictions" not in report.phase_results
        assert "merge" not in report.phase_results


# ---------------------------------------------------------------------------
# Tick Manager — State Cycling
# ---------------------------------------------------------------------------


class TestTickManagerStateCycle:
    """Verify tick manager transitions through all states over simulated time."""

    def test_initial_state_is_paused(self):
        """Tick manager starts in PAUSED state."""
        tm = TickManager()
        assert tm.state == TickState.PAUSED
        assert not tm.enabled

    def test_enable_disable_cycle(self):
        """enable/disable transitions between IDLE and PAUSED."""
        tm = TickManager()

        tm.enable()
        assert tm.state == TickState.IDLE
        assert tm.enabled

        tm.disable()
        assert tm.state == TickState.PAUSED
        assert not tm.enabled

    def test_full_state_cycle(self):
        """Walk through: PAUSED -> IDLE -> WORKING -> IDLE -> SLEEPING -> IDLE."""
        tm = TickManager()

        # PAUSED -> IDLE
        tm.enable()
        assert tm.state == TickState.IDLE

        # IDLE -> WORKING
        tm.mark_working()
        assert tm.state == TickState.WORKING

        # WORKING -> IDLE (via wake)
        tm.wake()
        assert tm.state == TickState.IDLE

        # IDLE -> SLEEPING
        tm.sleep(120)
        assert tm.state == TickState.SLEEPING

        # SLEEPING -> IDLE (via wake)
        tm.wake()
        assert tm.state == TickState.IDLE

    def test_sleep_clamps_to_bounds(self):
        """Sleep duration is clamped to [min, max] range."""
        tm = TickManager(min_sleep_seconds=60, max_sleep_seconds=3600)

        # Below minimum
        tm.enable()
        tm.sleep(10)
        assert tm._sleep_duration == 60

        # Above maximum
        tm.wake()
        tm.sleep(9999)
        assert tm._sleep_duration == 3600

    @pytest.mark.asyncio
    async def test_wait_for_tick_returns_false_when_disabled(self):
        """wait_for_tick returns False immediately when proactive mode is off."""
        tm = TickManager()
        result = await tm.wait_for_tick()
        assert result is False

    @pytest.mark.asyncio
    async def test_wait_for_tick_returns_true_when_idle(self):
        """wait_for_tick returns True immediately when in IDLE state."""
        tm = TickManager()
        tm.enable()
        result = await tm.wait_for_tick()
        assert result is True

    @pytest.mark.asyncio
    async def test_wake_interrupts_sleep(self):
        """Calling wake() during a sleep cuts the wait short."""
        tm = TickManager(min_sleep_seconds=1, max_sleep_seconds=3600)
        tm.enable()
        tm.sleep(600)  # 10 minutes

        async def wake_after_short_delay():
            await asyncio.sleep(0.05)
            tm.wake()

        task = asyncio.create_task(wake_after_short_delay())
        result = await tm.wait_for_tick()
        await task

        assert result is True
        assert tm.state == TickState.IDLE

    def test_build_tick_prompt_format(self):
        """build_tick_prompt produces valid <tick> XML with context fields."""
        tm = TickManager()
        ctx = TickContext(
            local_time="2026-04-03T14:30:00",
            pending_tasks=3,
            recent_events=["deploy completed", "email sent", "PR merged"],
            next_scheduled_service="briefing",
            daily_log_summary="- 14:00 [event] deploy completed",
        )

        prompt = tm.build_tick_prompt(ctx)

        assert prompt.startswith('<tick time="2026-04-03T14:30:00">')
        assert "</tick>" in prompt
        assert "pending_tasks: 3" in prompt
        assert "next_scheduled: briefing" in prompt
        assert "deploy completed" in prompt
        assert "daily_log:" in prompt

    def test_parse_sleep_request_variants(self):
        """parse_sleep_request handles seconds, minutes, and hours formats."""
        tm = TickManager(min_sleep_seconds=60, max_sleep_seconds=3600)

        assert tm.parse_sleep_request("Nothing to do. SLEEP 300") == 300.0
        assert tm.parse_sleep_request("All clear. SLEEP 5m") == 300.0
        assert tm.parse_sleep_request("SLEEP 1h") == 3600.0
        # No match returns default (300)
        assert tm.parse_sleep_request("I will keep working") == 300.0

    def test_parse_sleep_request_clamps_values(self):
        """Parsed sleep durations are clamped to configured bounds."""
        tm = TickManager(min_sleep_seconds=60, max_sleep_seconds=3600)

        # 10 seconds -> clamped to 60
        assert tm.parse_sleep_request("SLEEP 10") == 60.0
        # 2 hours -> clamped to 3600
        assert tm.parse_sleep_request("SLEEP 2h") == 3600.0


# ---------------------------------------------------------------------------
# Cron Jitter — Bounded Interval Tests
# ---------------------------------------------------------------------------


class TestCronJitterBounds:
    """Verify jitter produces values within expected bounds."""

    def test_jitter_within_percentage_bound(self):
        """Jitter never exceeds base_interval * jitter_percent / 100."""
        config = JitterConfig(
            base_interval_seconds=600,
            jitter_percent=20.0,
            jitter_cap_seconds=300,
        )
        max_expected = 600 * 20.0 / 100.0  # 120 seconds

        jitter = CronJitter(config, seed=42)
        for _ in range(100):
            value = jitter.calculate_jitter()
            assert 0 <= value <= max_expected

    def test_jitter_respects_cap(self):
        """When percentage would exceed cap, jitter is bounded by cap."""
        config = JitterConfig(
            base_interval_seconds=6000,
            jitter_percent=50.0,
            jitter_cap_seconds=60,
        )
        # 50% of 6000 = 3000, but cap is 60
        jitter = CronJitter(config, seed=99)
        for _ in range(100):
            value = jitter.calculate_jitter()
            assert 0 <= value <= 60

    def test_deterministic_with_seed(self):
        """Same seed produces identical jitter sequences."""
        config = JitterConfig(
            base_interval_seconds=600,
            jitter_percent=15.0,
            jitter_cap_seconds=300,
        )

        seq_a = [CronJitter(config, seed=7).calculate_jitter() for _ in range(1)]
        seq_b = [CronJitter(config, seed=7).calculate_jitter() for _ in range(1)]

        assert seq_a == seq_b

    def test_jitter_varies_without_seed(self):
        """Without a fixed seed, consecutive CronJitter instances produce different values."""
        config = JitterConfig(
            base_interval_seconds=600,
            jitter_percent=20.0,
            jitter_cap_seconds=300,
        )

        values = set()
        for _ in range(20):
            j = CronJitter(config)
            values.add(j.calculate_jitter())

        # With 20 random samples it is virtually impossible to get all identical
        assert len(values) > 1


# ---------------------------------------------------------------------------
# End-to-End 24-Hour Simulation
# ---------------------------------------------------------------------------


class TestSimulated24HourCycle:
    """Simulate a full 24-hour bridge cycle tying all modules together."""

    def test_24h_daily_log_accumulation(self, tmp_path):
        """Simulate hourly log entries over 24 hours and verify accumulation."""
        cfg = _make_config(tmp_path)
        writer = DailyLogWriter(cfg)

        # Fixed noon UTC — all appends go to the same April 3 file in any timezone
        # (noon UTC stays April 3 even in UTC+12 or UTC-12)
        base = _fake_now(2026, 4, 3)  # default midday UTC
        categories = ["event", "memory", "service", "proactive", "session", "general"]

        with patch("bridge.daily_log.datetime") as mock_dt:
            mock_dt.now.return_value = base
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            for hour in range(24):
                writer.append(
                    f"hourly checkpoint at hour {hour}",
                    category=categories[hour % len(categories)],
                )

        content = writer.read_date(base)
        lines = [line for line in content.strip().split("\n") if line.startswith("- ")]
        assert len(lines) == 24

    def test_consolidation_after_day_of_knowledge_growth(self):
        """Run full consolidation on knowledge accumulated over a simulated day."""
        # Simulate knowledge accumulating: 50 rows across varied categories
        rows = (
            _build_knowledge_rows(20, category="project", source="agent")
            + _build_knowledge_rows(15, category="decision", source="operator")
            + _build_knowledge_rows(10, category="event", source="agent")
            + _build_knowledge_rows(5, category="preference", source="operator")
        )

        report = run_pipeline(rows, mode="standard")

        assert isinstance(report, ConsolidationReport)
        inv = report.phase_results["inventory"]
        assert inv.total == 50
        assert inv.by_category["project"] == 20
        assert inv.by_category["preference"] == 5

        # Preferences and operator entries should be decay-exempt
        dec = report.phase_results["decay"]
        assert dec.exempt > 0

    def test_tick_manager_simulated_work_sleep_cycles(self):
        """Simulate multiple work-sleep cycles as would occur over a day."""
        tm = TickManager(min_sleep_seconds=60, max_sleep_seconds=3600)
        tm.enable()

        states_visited = []

        for cycle in range(6):
            # Work phase
            tm.mark_working()
            states_visited.append(tm.state)

            # Back to idle
            tm.wake()
            states_visited.append(tm.state)

            # Sleep phase (varying durations)
            sleep_seconds = 300 * (cycle + 1)
            tm.sleep(sleep_seconds)
            states_visited.append(tm.state)

            # Wake from sleep
            tm.wake()
            states_visited.append(tm.state)

        assert TickState.WORKING in states_visited
        assert TickState.SLEEPING in states_visited
        assert TickState.IDLE in states_visited
        # Each cycle produces 4 states; 6 cycles = 24 transitions
        assert len(states_visited) == 24

    def test_jitter_across_24h_of_10min_intervals(self):
        """Simulate 144 cron ticks (every 10 min for 24h); all jitter values are bounded."""
        config = JitterConfig(
            base_interval_seconds=600,
            jitter_percent=15.0,
            jitter_cap_seconds=120,
        )
        max_jitter = 600 * 15.0 / 100.0  # 90 seconds (below cap of 120)

        jitter = CronJitter(config, seed=2026)
        values = [jitter.calculate_jitter() for _ in range(144)]

        assert all(0 <= v <= max_jitter for v in values)
        # Verify there is actual variance (not all identical)
        assert len(set(values)) > 1
