"""Tests for the learning knowledge store (Board Phase 3 WS1, #2392).

Covers the producer/consumer seam: ``used_count`` is written by
``increment_used_count`` / ``RecallTracker.mark_used`` and read by both
``boost_by_used_count`` (recall rank) and ``flag_stale_unused`` (consolidation).
The pure functions are tested in isolation; the DB-backed pieces use the shared
``migrated_db`` fixture so migration 17's columns are present.
"""

from __future__ import annotations

import pytest

from bridge.memory.recall_learning import (
    USED_COUNT_BOOST_THRESHOLD,
    RecallTracker,
    boost_by_used_count,
    flag_stale_unused,
    get_used_counts,
    increment_used_count,
)


# --------------------------------------------------------------------------- #
# Pure functions
# --------------------------------------------------------------------------- #

class TestBoostByUsedCount:
    def test_boosts_above_threshold_to_top(self):
        results = [
            {"key": "a", "rank": 1},
            {"key": "b", "rank": 2},
            {"key": "c", "rank": 3},
        ]
        used = {"a": 0, "b": 5, "c": 1}
        out = boost_by_used_count(results, used)
        assert out[0]["key"] == "b"
        # used_count annotated on each result.
        assert out[0]["used_count"] == 5

    def test_stable_within_bands(self):
        results = [
            {"key": "a"}, {"key": "b"}, {"key": "c"}, {"key": "d"},
        ]
        used = {"a": 4, "b": 0, "c": 9, "d": 0}
        out = boost_by_used_count(results, used)
        # boosted band keeps a-before-c order; rest keeps b-before-d.
        keys = [r["key"] for r in out]
        assert keys == ["a", "c", "b", "d"]

    def test_does_not_mutate_input(self):
        results = [{"key": "a"}]
        used = {"a": 5}
        out = boost_by_used_count(results, used)
        assert "used_count" not in results[0]
        assert out[0]["used_count"] == 5

    def test_threshold_constant(self):
        assert USED_COUNT_BOOST_THRESHOLD == 3


class TestRecallTrackerWindow:
    def test_recent_keys_prunes_expired(self):
        tracker = RecallTracker(window_seconds=300.0)
        tracker.record_recall(["a", "b"], now=1000.0)
        # Within window.
        assert set(tracker.recent_keys(now=1200.0)) == {"a", "b"}
        # Outside window -> pruned.
        assert tracker.recent_keys(now=2000.0) == []

    def test_empty_record_is_noop(self):
        tracker = RecallTracker()
        tracker.record_recall([])
        assert tracker.recent_keys() == []


# --------------------------------------------------------------------------- #
# DB-backed (migration 17 columns)
# --------------------------------------------------------------------------- #

@pytest.mark.asyncio
class TestUsedCountPersistence:
    async def test_increment_and_read(self, migrated_db, sample_config):
        from bridge.memory import Memory

        memory = Memory(migrated_db, sample_config)
        await memory.store_knowledge("k1", "value one")
        await memory.store_knowledge("k2", "value two")

        await increment_used_count(migrated_db, ["k1", "k1", "k2"])
        counts = await get_used_counts(migrated_db, ["k1", "k2"])
        assert counts["k1"] == 2
        assert counts["k2"] == 1

    async def test_mark_used_only_credits_recently_recalled(self, migrated_db, sample_config):
        from bridge.memory import Memory

        memory = Memory(migrated_db, sample_config)
        await memory.store_knowledge("k1", "alpha")
        await memory.store_knowledge("k2", "beta")

        tracker = RecallTracker(window_seconds=300.0)
        tracker.record_recall(["k1"], now=1000.0)

        # Operator acts on k1 (recalled) and k2 (never recalled) within window.
        credited = await tracker.mark_used(migrated_db, ["k1", "k2"], now=1100.0)
        assert credited == ["k1"]
        counts = await get_used_counts(migrated_db, ["k1", "k2"])
        assert counts["k1"] == 1
        assert counts["k2"] == 0

    async def test_mark_used_outside_window_credits_nothing(self, migrated_db, sample_config):
        from bridge.memory import Memory

        memory = Memory(migrated_db, sample_config)
        await memory.store_knowledge("k1", "alpha")
        tracker = RecallTracker(window_seconds=300.0)
        tracker.record_recall(["k1"], now=1000.0)
        credited = await tracker.mark_used(migrated_db, ["k1"], now=5000.0)
        assert credited == []

    async def test_flag_stale_unused(self, migrated_db, sample_config):
        from bridge.memory import Memory

        memory = Memory(migrated_db, sample_config)
        await memory.store_knowledge("fresh", "new")
        await memory.store_knowledge("old_unused", "ancient")
        await memory.store_knowledge("old_used", "ancient but useful")

        # Age the two "old" rows past 90 days and mark one as used.
        await migrated_db.execute(
            "UPDATE knowledge SET created_at = datetime('now', '-120 days') "
            "WHERE key IN ('old_unused', 'old_used')"
        )
        await migrated_db.commit()
        await increment_used_count(migrated_db, ["old_used"])

        stale = await flag_stale_unused(migrated_db, age_days=90)
        keys = {r["key"] for r in stale}
        assert "old_unused" in keys
        assert "old_used" not in keys  # used_count > 0 -> excluded
        assert "fresh" not in keys     # too young


@pytest.mark.asyncio
class TestSearchBoostIntegration:
    async def test_search_boosts_used_entries(self, migrated_db, sample_config):
        from bridge.memory import Memory
        from bridge.memory.recall_learning import RecallTracker

        memory = Memory(migrated_db, sample_config)
        await memory.store_knowledge("low", "shared keyword apple")
        await memory.store_knowledge("high", "shared keyword apple")
        # Make "high" a frequently-used memory.
        await increment_used_count(migrated_db, ["high", "high", "high"])

        memory.set_recall_tracker(RecallTracker())
        results = await memory.search_knowledge("apple", limit=10)
        keys = [r["key"] for r in results]
        assert "high" in keys and "low" in keys
        # high (used_count 3) must rank before low (used_count 0).
        assert keys.index("high") < keys.index("low")

    async def test_search_without_tracker_is_unboosted(self, migrated_db, sample_config):
        from bridge.memory import Memory

        memory = Memory(migrated_db, sample_config)  # no tracker
        await memory.store_knowledge("k1", "shared keyword apple")
        results = await memory.search_knowledge("apple", limit=10)
        # No used_count annotation when the learning step is not wired.
        assert all("used_count" not in r for r in results)
