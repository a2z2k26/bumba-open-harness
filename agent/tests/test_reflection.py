"""Tests for MS4.5: ACE Reflection Loops."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from bridge.reflection import (
    ReflectionResult,
    ReflectionStore,
    ReflexionContext,
    gather_week_data_from_dicts,
    make_week_key,
)


@pytest.fixture
def store(tmp_path):
    return ReflectionStore(tmp_path / "reflect.db")


# ── Week Key ──

class TestWeekKey:
    def test_format(self):
        dt = datetime(2026, 3, 14, tzinfo=timezone.utc)
        key = make_week_key(dt)
        assert key.startswith("reflection-2026-W")

    def test_default_uses_now(self):
        key = make_week_key()
        assert key.startswith("reflection-")
        assert "-W" in key


# ── WeekData Gathering ──

class TestGatherWeekData:
    def test_empty_data(self):
        wd = gather_week_data_from_dicts()
        assert wd.metrics_summaries == []
        assert wd.failure_patterns == []
        assert wd.few_shot_quality == {}
        assert wd.year > 0
        assert wd.week_number > 0

    def test_populated_data(self):
        wd = gather_week_data_from_dicts(
            metrics=[{"metric": "latency", "p50": 100}],
            failures=[{"type": "timeout", "count": 3}],
            examples_quality={"avg_score": 0.8, "count": 10},
            routing=[{"tool": "brave", "status": "healthy"}],
            proposals=[{"name": "retry-skill", "status": "proposed"}],
            feedback=["great job", "not quite"],
        )
        assert len(wd.metrics_summaries) == 1
        assert len(wd.failure_patterns) == 1
        assert wd.few_shot_quality["avg_score"] == 0.8
        assert len(wd.operator_feedback) == 2


# ── Reflection Store ──

class TestReflectionStore:
    def test_store_and_get(self, store):
        r = ReflectionResult(
            week_key="reflection-2026-W11",
            achievements=["Deployed voice pipeline"],
            improvements=["Reduce latency"],
            patterns=["Errors spike at midnight"],
            contradictions=[],
            recommendations=["Focus on caching"],
        )
        store.store_reflection(r)
        got = store.get_reflection("reflection-2026-W11")
        assert got is not None
        assert got.achievements == ["Deployed voice pipeline"]
        assert got.recommendations == ["Focus on caching"]

    def test_get_nonexistent(self, store):
        assert store.get_reflection("reflection-2099-W99") is None

    def test_count(self, store):
        assert store.count() == 0
        store.store_reflection(ReflectionResult(week_key="reflection-2026-W10"))
        assert store.count() == 1

    def test_get_recent(self, store):
        for w in range(10, 15):
            store.store_reflection(ReflectionResult(
                week_key=f"reflection-2026-W{w}",
                achievements=[f"Week {w} achievement"],
            ))
        recent = store.get_recent(limit=3)
        assert len(recent) == 3

    def test_upsert(self, store):
        store.store_reflection(ReflectionResult(
            week_key="reflection-2026-W11",
            achievements=["v1"],
        ))
        store.store_reflection(ReflectionResult(
            week_key="reflection-2026-W11",
            achievements=["v2"],
        ))
        got = store.get_reflection("reflection-2026-W11")
        assert got.achievements == ["v2"]
        assert store.count() == 1

    def test_key_format(self, store):
        r = ReflectionResult(week_key="reflection-2026-W11")
        store.store_reflection(r)
        got = store.get_reflection("reflection-2026-W11")
        assert got.week_key == "reflection-2026-W11"


# ── Reflection Formatting ──

class TestReflectionFormatting:
    def test_format_full(self, store):
        r = ReflectionResult(
            week_key="reflection-2026-W11",
            achievements=["Deployed v2"],
            improvements=["Reduce errors"],
            patterns=["Spikes at midnight"],
            recommendations=["Improve caching"],
            contradictions=[{"old_insight": "A", "new_insight": "B"}],
        )
        md = store.format_reflection(r)
        assert "Achievements" in md
        assert "Deployed v2" in md
        assert "Focus Next Week" in md
        assert "Contradictions Detected" in md

    def test_format_empty(self, store):
        r = ReflectionResult(week_key="reflection-2026-W11")
        md = store.format_reflection(r)
        assert "reflection-2026-W11" in md

    def test_format_no_contradictions(self, store):
        r = ReflectionResult(
            week_key="reflection-2026-W11",
            achievements=["A"],
        )
        md = store.format_reflection(r)
        assert "Contradictions" not in md


# ── In-Session Reflexion ──

class TestReflexionContext:
    def test_add_pair(self):
        ctx = ReflexionContext()
        ctx.add_pair("input", "failed output", "I should have done X instead")
        assert ctx.count == 1

    def test_get_context(self):
        ctx = ReflexionContext()
        ctx.add_pair("search for X", "timed out", "Should check tool health first")
        text = ctx.get_context()
        assert "Previous Attempt" in text
        assert "What went wrong" in text
        assert "Should check tool health first" in text

    def test_empty_context(self):
        ctx = ReflexionContext()
        assert ctx.get_context() == ""

    def test_max_pairs_cap(self):
        ctx = ReflexionContext(max_pairs=2)
        ctx.add_pair("FIRST_UNIQUE_INPUT", "b", "c")
        ctx.add_pair("SECOND_UNIQUE_INPUT", "e", "f")
        ctx.add_pair("THIRD_UNIQUE_INPUT", "h", "i")
        assert ctx.count == 2
        # Oldest removed
        text = ctx.get_context()
        assert "FIRST_UNIQUE_INPUT" not in text
        assert "SECOND_UNIQUE_INPUT" in text
        assert "THIRD_UNIQUE_INPUT" in text

    def test_clear(self):
        ctx = ReflexionContext()
        ctx.add_pair("a", "b", "c")
        ctx.clear()
        assert ctx.count == 0
        assert ctx.get_context() == ""

    def test_output_truncated(self):
        ctx = ReflexionContext()
        ctx.add_pair("input", "x" * 500, "reflection")
        # failed_output_summary should be truncated to 200 chars
        assert ctx._pairs[0].failed_output_summary == "x" * 200
