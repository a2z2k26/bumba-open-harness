"""Tests for Phase 4: Per-Agent Cost Attribution (GitHub Issue #4).

Verifies that CostEntry carries agent_id/session_id fields, that
CostTracker.record() accepts and persists them, that backward
compatibility is maintained for callers that omit the new params,
and that get_cost_by_agent() returns correct per-agent aggregations.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from bridge.cost_tracker import CostEntry, CostTracker, estimate_cost


# ------------------------------------------------------------------
# Fixtures
# ------------------------------------------------------------------


@pytest.fixture()
def tracker(tmp_path: Path) -> CostTracker:
    """Return a CostTracker backed by an isolated temp directory."""
    return CostTracker(data_dir=tmp_path)


# ------------------------------------------------------------------
# CostEntry dataclass fields
# ------------------------------------------------------------------


class TestCostEntryFields:
    """CostEntry must carry agent_id and session_id with safe defaults."""

    def test_agent_id_field_exists(self) -> None:
        entry = CostEntry(
            timestamp="2026-03-28T12:00:00+00:00",
            model="sonnet",
            input_tokens=100,
            output_tokens=50,
            estimated_cost=0.001,
            task_type="test",
            was_override=False,
            agent_id="agent-alpha",
        )
        assert entry.agent_id == "agent-alpha"

    def test_session_id_field_exists(self) -> None:
        entry = CostEntry(
            timestamp="2026-03-28T12:00:00+00:00",
            model="sonnet",
            input_tokens=100,
            output_tokens=50,
            estimated_cost=0.001,
            task_type="test",
            was_override=False,
            session_id="sess-001",
        )
        assert entry.session_id == "sess-001"

    def test_defaults_are_empty_strings(self) -> None:
        entry = CostEntry(
            timestamp="2026-03-28T12:00:00+00:00",
            model="haiku",
            input_tokens=10,
            output_tokens=5,
            estimated_cost=0.0,
            task_type="",
            was_override=False,
        )
        assert entry.agent_id == ""
        assert entry.session_id == ""


# ------------------------------------------------------------------
# record() with new params
# ------------------------------------------------------------------


class TestRecordWithAttribution:
    """record() must accept, persist, and round-trip agent_id / session_id."""

    def test_record_with_agent_and_session(self, tracker: CostTracker) -> None:
        entry = tracker.record(
            model="sonnet",
            input_tokens=1000,
            output_tokens=500,
            task_type="code_review",
            agent_id="agent-beta",
            session_id="sess-42",
        )
        assert entry.agent_id == "agent-beta"
        assert entry.session_id == "sess-42"
        assert entry.model == "sonnet"
        assert entry.input_tokens == 1000
        assert entry.output_tokens == 500
        assert entry.estimated_cost > 0

    def test_record_persists_agent_id_to_jsonl(self, tracker: CostTracker) -> None:
        tracker.record(
            model="haiku",
            input_tokens=200,
            output_tokens=100,
            agent_id="agent-gamma",
            session_id="sess-99",
        )
        raw = tracker.path.read_text(encoding="utf-8").strip()
        data = json.loads(raw)
        assert data["agent_id"] == "agent-gamma"
        assert data["session_id"] == "sess-99"

    def test_record_round_trips_through_read(self, tracker: CostTracker) -> None:
        tracker.record(
            model="opus",
            input_tokens=500,
            output_tokens=250,
            agent_id="agent-delta",
            session_id="sess-77",
        )
        entries = tracker._read_entries()
        assert len(entries) == 1
        assert entries[0].agent_id == "agent-delta"
        assert entries[0].session_id == "sess-77"


# ------------------------------------------------------------------
# Backward compatibility
# ------------------------------------------------------------------


class TestBackwardCompatibility:
    """Existing callers that omit agent_id/session_id must still work."""

    def test_record_without_agent_id(self, tracker: CostTracker) -> None:
        entry = tracker.record(
            model="sonnet",
            input_tokens=100,
            output_tokens=50,
        )
        assert entry.agent_id == ""
        assert entry.session_id == ""

    def test_record_positional_args_unchanged(self, tracker: CostTracker) -> None:
        """The first three positional args (model, in, out) still work."""
        entry = tracker.record("haiku", 300, 150)
        assert entry.model == "haiku"
        assert entry.input_tokens == 300
        assert entry.output_tokens == 150
        assert entry.agent_id == ""
        assert entry.session_id == ""

    def test_legacy_jsonl_without_new_fields_loads(self, tracker: CostTracker) -> None:
        """JSONL lines written before this feature (no agent_id/session_id)
        must still parse via _read_entries thanks to dataclass defaults."""
        legacy_line = json.dumps({
            "timestamp": "2026-03-01T00:00:00+00:00",
            "model": "sonnet",
            "input_tokens": 100,
            "output_tokens": 50,
            "estimated_cost": 0.001,
            "task_type": "chat",
            "was_override": False,
        })
        tracker.path.write_text(legacy_line + "\n", encoding="utf-8")
        entries = tracker._read_entries()
        assert len(entries) == 1
        assert entries[0].agent_id == ""
        assert entries[0].session_id == ""

    def test_daily_summary_unaffected(self, tracker: CostTracker) -> None:
        """Existing summary methods must still work with new fields present."""
        tracker.record("sonnet", 100, 50, agent_id="agent-x")
        summary = tracker.get_daily_summary()
        assert summary["request_count"] == 1
        assert summary["total_cost"] > 0


# ------------------------------------------------------------------
# get_cost_by_agent()
# ------------------------------------------------------------------


class TestGetCostByAgent:
    """get_cost_by_agent() returns correct per-agent aggregations."""

    def test_single_agent_aggregation(self, tracker: CostTracker) -> None:
        tracker.record("sonnet", 1000, 500, agent_id="agent-a", session_id="s1")
        tracker.record("sonnet", 2000, 1000, agent_id="agent-a", session_id="s2")

        result = tracker.get_cost_by_agent()

        assert "agent-a" in result
        stats = result["agent-a"]
        assert stats["count"] == 2
        assert stats["input_tokens"] == 3000
        assert stats["output_tokens"] == 1500
        expected_cost = estimate_cost("sonnet", 1000, 500) + estimate_cost("sonnet", 2000, 1000)
        assert stats["cost"] == pytest.approx(expected_cost, abs=1e-6)

    def test_multiple_agents(self, tracker: CostTracker) -> None:
        tracker.record("haiku", 100, 50, agent_id="agent-a")
        tracker.record("sonnet", 200, 100, agent_id="agent-b")
        tracker.record("opus", 300, 150, agent_id="agent-a")

        result = tracker.get_cost_by_agent()

        assert len(result) == 2
        assert result["agent-a"]["count"] == 2
        assert result["agent-a"]["input_tokens"] == 400
        assert result["agent-a"]["output_tokens"] == 200
        assert result["agent-b"]["count"] == 1
        assert result["agent-b"]["input_tokens"] == 200
        assert result["agent-b"]["output_tokens"] == 100

    def test_excludes_empty_agent_id(self, tracker: CostTracker) -> None:
        tracker.record("sonnet", 100, 50)  # no agent_id
        tracker.record("sonnet", 200, 100, agent_id="")  # explicit empty
        tracker.record("haiku", 300, 150, agent_id="agent-only")

        result = tracker.get_cost_by_agent()

        assert len(result) == 1
        assert "agent-only" in result
        assert "" not in result

    def test_empty_tracker_returns_empty_dict(self, tracker: CostTracker) -> None:
        result = tracker.get_cost_by_agent()
        assert result == {}

    def test_all_entries_without_agent_id_returns_empty(self, tracker: CostTracker) -> None:
        tracker.record("sonnet", 100, 50)
        tracker.record("haiku", 200, 100)

        result = tracker.get_cost_by_agent()
        assert result == {}

    def test_cost_values_are_rounded(self, tracker: CostTracker) -> None:
        """Cost values in the result must be rounded to 6 decimal places."""
        tracker.record("sonnet", 1, 1, agent_id="precise-agent")
        result = tracker.get_cost_by_agent()
        cost_str = str(result["precise-agent"]["cost"])
        # After the decimal, at most 6 digits
        if "." in cost_str:
            decimals = len(cost_str.split(".")[1])
            assert decimals <= 6
