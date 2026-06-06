"""Tests for Sprint 05.07 — reflection_gatherer real-metric gatherer.

Each external data source is mocked to verify:
- Successful reads produce non-placeholder content.
- Empty data sources produce explicit "no data" achievement strings.
- Each try/except branch handles a source failure without crashing,
  recording the failure in WeekData.notes.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from bridge.reflection_gatherer import (
    GatherDeps,
    gather_week_data,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _cost_tracker_with(weekly_summary: dict) -> object:
    return SimpleNamespace(get_weekly_summary=lambda: weekly_summary)


def _cost_tracker_raising() -> object:
    def _raise() -> dict:
        raise RuntimeError("cost tracker boom")

    return SimpleNamespace(get_weekly_summary=_raise)


def _routing_with(model_perfs: dict[tuple[str, str], object]) -> object:
    """Return a fake routing engine that responds to get_model_performance."""

    class _ModelPerf:
        def __init__(self, attempts: int, success_rate: float):
            self.attempts = attempts
            self.success_rate = success_rate

    def _get_model_performance(tier: str, task_type: str):
        attempts, success = model_perfs.get((tier, task_type), (0, 1.0))
        return _ModelPerf(attempts=attempts, success_rate=success)

    return SimpleNamespace(get_model_performance=_get_model_performance)


def _routing_raising() -> object:
    def _raise(*args, **kwargs):
        raise RuntimeError("routing boom")

    return SimpleNamespace(get_model_performance=_raise)


def _few_shot_with(count: int, avg_quality: float | None) -> object:
    examples = [
        SimpleNamespace(quality_score=avg_quality) for _ in range(count)
    ] if avg_quality is not None else []

    def _list_all(limit: int = 100):
        return examples

    return SimpleNamespace(count=lambda: count, list_all=_list_all)


def _few_shot_raising() -> object:
    def _raise(*args, **kwargs):
        raise RuntimeError("few_shot boom")

    return SimpleNamespace(count=_raise, list_all=_raise)


def _event_bus_with(events_dir):
    return SimpleNamespace(_data_dir=events_dir)


# ---------------------------------------------------------------------------
# Cost tracker branch
# ---------------------------------------------------------------------------


class TestCostTrackerBranch:
    def test_records_weekly_cost(self):
        deps = GatherDeps(
            cost_tracker=_cost_tracker_with({"total_cost": 1.234}),
        )
        wd = gather_week_data(deps)
        assert wd.weekly_cost_usd == pytest.approx(1.234)
        assert any("$1.23" in a or "1.23" in a for a in wd.achievements), wd.achievements
        assert "system is learning" not in " ".join(wd.achievements)

    def test_missing_cost_tracker_marks_unavailable(self):
        deps = GatherDeps()
        wd = gather_week_data(deps)
        assert wd.weekly_cost_usd is None
        assert any("cost_tracker" in n for n in wd.notes), wd.notes

    def test_cost_tracker_exception_recorded_in_notes(self):
        deps = GatherDeps(cost_tracker=_cost_tracker_raising())
        wd = gather_week_data(deps)
        assert wd.weekly_cost_usd is None
        assert any("cost_tracker" in n for n in wd.notes)


# ---------------------------------------------------------------------------
# Routing feedback branch
# ---------------------------------------------------------------------------


class TestRoutingFeedbackBranch:
    def test_collects_success_rates_for_known_tiers(self):
        perfs = {
            ("haiku", "general"): (10, 0.9),
            ("sonnet", "general"): (5, 0.8),
        }
        deps = GatherDeps(routing_feedback=_routing_with(perfs))
        wd = gather_week_data(deps)
        # WeekData uses tuple-of-tuples to remain frozen-friendly.
        rates = dict(wd.model_success_rates)
        assert "haiku" in rates
        assert rates["haiku"] == pytest.approx(0.9)

    def test_routing_exception_recorded(self):
        deps = GatherDeps(routing_feedback=_routing_raising())
        wd = gather_week_data(deps)
        assert wd.model_success_rates == ()
        assert any("routing_feedback" in n for n in wd.notes)


# ---------------------------------------------------------------------------
# Memory branch (counts pre-resolved by caller)
# ---------------------------------------------------------------------------


class TestMemoryBranch:
    def test_counts_pass_through(self):
        deps = GatherDeps(knowledge_count=42, conversation_count=99)
        wd = gather_week_data(deps)
        assert wd.knowledge_count == 42
        assert wd.conversation_count == 99
        assert any("42 knowledge entries" in a for a in wd.achievements)

    def test_zero_counts_produce_no_data_marker(self):
        deps = GatherDeps(knowledge_count=0, conversation_count=0)
        wd = gather_week_data(deps)
        assert any("no data" in a.lower() and "knowledge" in a.lower()
                   for a in wd.achievements)


# ---------------------------------------------------------------------------
# Few-shot branch
# ---------------------------------------------------------------------------


class TestFewShotBranch:
    def test_collects_count_and_quality(self):
        deps = GatherDeps(few_shot_store=_few_shot_with(count=3, avg_quality=0.8))
        wd = gather_week_data(deps)
        assert wd.few_shot_example_count == 3
        assert wd.few_shot_avg_quality == pytest.approx(0.8)
        assert any("3" in a and "few-shot" in a.lower()
                   for a in wd.achievements), wd.achievements

    def test_few_shot_exception_recorded(self):
        deps = GatherDeps(few_shot_store=_few_shot_raising())
        wd = gather_week_data(deps)
        assert wd.few_shot_example_count == 0
        assert wd.few_shot_avg_quality is None
        assert any("few_shot" in n for n in wd.notes)


# ---------------------------------------------------------------------------
# Event bus branch — counts error-type events from JSONL
# ---------------------------------------------------------------------------


class TestEventBusBranch:
    def test_counts_error_events_in_last_7_days(self, tmp_path):
        events_dir = tmp_path / "events"
        events_dir.mkdir()
        from datetime import datetime, timezone, timedelta
        import json

        recent = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        old = (datetime.now(timezone.utc) - timedelta(days=30)).strftime("%Y-%m-%d")

        # recent file with two errors and one info
        (events_dir / f"{recent}.jsonl").write_text(
            json.dumps({"event_type": "department.task.failed",
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "payload": {}}) + "\n"
            + json.dumps({"event_type": "security.error",
                          "timestamp": datetime.now(timezone.utc).isoformat(),
                          "payload": {}}) + "\n"
            + json.dumps({"event_type": "session.started",
                          "timestamp": datetime.now(timezone.utc).isoformat(),
                          "payload": {}}) + "\n"
        )
        # old file — should not be counted
        (events_dir / f"{old}.jsonl").write_text(
            json.dumps({"event_type": "department.task.failed",
                        "timestamp": (datetime.now(timezone.utc)
                                      - timedelta(days=30)).isoformat(),
                        "payload": {}}) + "\n"
        )

        deps = GatherDeps(event_bus=_event_bus_with(tmp_path))
        wd = gather_week_data(deps)
        assert wd.error_event_count == 2

    def test_missing_event_bus_marks_unavailable(self):
        deps = GatherDeps()
        wd = gather_week_data(deps)
        assert wd.error_event_count == 0
        assert any("event_bus" in n for n in wd.notes)

    def test_event_bus_read_failure_recorded(self, tmp_path):
        # Point at a non-existent file structure but valid object — no events_dir
        deps = GatherDeps(event_bus=SimpleNamespace(_data_dir=tmp_path / "nope"))
        wd = gather_week_data(deps)
        # Missing dir is treated as "no events", not as exception.
        assert wd.error_event_count == 0


# ---------------------------------------------------------------------------
# Aggregate behaviour
# ---------------------------------------------------------------------------


class TestAggregateBehaviour:
    def test_all_sources_empty_produces_no_data_markers(self):
        deps = GatherDeps()
        wd = gather_week_data(deps)
        joined = " ".join(wd.achievements).lower()
        # Must NOT contain the old placeholder string.
        assert "system is learning" not in joined
        # Must contain explicit "no data" markers for at least cost + knowledge.
        assert "no data" in joined
        assert wd.weekly_cost_usd is None
        assert wd.knowledge_count == 0

    def test_returned_weekdata_is_frozen(self):
        wd = gather_week_data(GatherDeps())
        with pytest.raises(Exception):
            wd.knowledge_count = 999  # type: ignore[misc]

    def test_achievements_is_tuple(self):
        wd = gather_week_data(GatherDeps(knowledge_count=5))
        assert isinstance(wd.achievements, tuple)
        assert isinstance(wd.notes, tuple)
