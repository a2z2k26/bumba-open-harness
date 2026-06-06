"""Tests for deep consolidation pipeline with DreamAgent integration."""

from __future__ import annotations


from bridge.consolidation import (
    ConsolidationReport,
    DeepResolutionResult,
    run_pipeline,
)
from bridge.dream_agent import DreamResult


SAMPLE_ROWS = [
    {"key": "k1", "category": "preference", "source": "manual", "value": "Use dark mode", "salience": 1.0, "access_count": 3, "created_at": "2026-01-01T00:00:00"},
    {"key": "k2", "category": "preference", "source": "manual", "value": "Do not use dark mode", "salience": 0.9, "access_count": 1, "created_at": "2026-01-02T00:00:00"},
    {"key": "k3", "category": "fact", "source": "conversation", "value": "Operator is based in New York", "salience": 0.8, "access_count": 0, "created_at": "2026-01-03T00:00:00"},
]


class TestDeepResolutionResult:
    def test_is_dataclass(self):
        import dataclasses
        assert dataclasses.is_dataclass(DeepResolutionResult)

    def test_has_status_field(self):
        r = DeepResolutionResult(status="unavailable")
        assert r.status == "unavailable"

    def test_has_resolved_field_defaults_empty(self):
        r = DeepResolutionResult(status="ok")
        assert r.resolved == []

    def test_resolved_can_be_set(self):
        r = DeepResolutionResult(status="ok", resolved=["item1", "item2"])
        assert len(r.resolved) == 2


class TestRunPipelineSignature:
    def test_accepts_session_ids_kwarg(self):
        report = run_pipeline(SAMPLE_ROWS, mode="deep", session_ids=["s1"])
        assert isinstance(report, ConsolidationReport)

    def test_accepts_dream_agent_none_kwarg(self):
        report = run_pipeline(SAMPLE_ROWS, mode="deep", session_ids=["s1"], _dream_agent=None)
        assert isinstance(report, ConsolidationReport)

    def test_session_ids_defaults_to_none(self):
        report = run_pipeline(SAMPLE_ROWS, mode="deep")
        assert isinstance(report, ConsolidationReport)

    def test_standard_mode_unaffected(self):
        report = run_pipeline(SAMPLE_ROWS, mode="standard")
        assert isinstance(report, ConsolidationReport)
        assert report.mode == "standard"


class TestDeepResolutionPhase:
    def test_deep_mode_has_deep_resolution_phase(self):
        report = run_pipeline(SAMPLE_ROWS, mode="deep", session_ids=["s1"], _dream_agent=None)
        assert "deep_resolution" in report.phase_results

    def test_deep_resolution_unavailable_when_no_agent(self):
        report = run_pipeline(SAMPLE_ROWS, mode="deep", session_ids=["s1"], _dream_agent=None)
        result = report.phase_results.get("deep_resolution")
        assert result is not None
        assert result["status"] == "unavailable"

    def test_deep_resolution_also_unavailable_with_no_session_ids(self):
        report = run_pipeline(SAMPLE_ROWS, mode="deep", _dream_agent=None)
        result = report.phase_results.get("deep_resolution")
        assert result["status"] == "unavailable"

    def test_standard_mode_emits_skipped_deep_resolution(self):
        # Sprint 05.09: standard mode now emits a `skipped` stub so dashboards
        # can disambiguate "non-deep run" from "deep ran" / "deep unavailable".
        report = run_pipeline(SAMPLE_ROWS, mode="standard")
        deep = report.phase_results.get("deep_resolution")
        assert deep is not None
        assert deep["status"] == "skipped"

    def test_micro_mode_no_deep_resolution_phase(self):
        # Micro mode still returns early before deep_resolution is set,
        # preserving the documented "Inventory + Decay only" contract.
        report = run_pipeline(SAMPLE_ROWS, mode="micro")
        assert "deep_resolution" not in report.phase_results

    def test_deep_mode_still_runs_all_other_phases(self):
        report = run_pipeline(SAMPLE_ROWS, mode="deep", session_ids=["s1"], _dream_agent=None)
        assert "inventory" in report.phase_results
        assert "decay" in report.phase_results
        assert "contradictions" in report.phase_results
        assert "merge" in report.phase_results
        assert "promotion" in report.phase_results

    def test_report_mode_is_deep(self):
        report = run_pipeline(SAMPLE_ROWS, mode="deep", session_ids=["s1"], _dream_agent=None)
        assert report.mode == "deep"


class TestDreamResultPresent:
    """Verify DreamResult is importable from bridge.dream_agent."""

    def test_dream_result_importable(self):
        assert DreamResult is not None

    def test_dream_result_is_dataclass(self):
        import dataclasses
        assert dataclasses.is_dataclass(DreamResult)

    def test_dream_result_success_field(self):
        r = DreamResult(
            success=True,
            summary="done",
            files_touched=[],
            entries_pruned=0,
            contradictions_resolved=0,
            merges_performed=0,
        )
        assert r.success is True
