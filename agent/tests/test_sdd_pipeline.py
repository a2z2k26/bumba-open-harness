"""Tests for SDD/TDD pipeline state machine."""

from __future__ import annotations

import pytest

from bridge.sdd_pipeline import (
    SDDPipeline,
    SDDStage,
    GateResult,
    InvalidStageTransitionError,
)


def test_stage_enum_values() -> None:
    assert SDDStage.SPECIFY.value == "specify"
    assert SDDStage.PLAN.value == "plan"
    assert SDDStage.TASKS.value == "tasks"
    assert SDDStage.IMPLEMENT.value == "implement"
    assert SDDStage.VERIFY.value == "verify"
    assert SDDStage.COMPLETE.value == "complete"


def test_initial_stage() -> None:
    pipeline = SDDPipeline(project="test")
    assert pipeline.current_stage == SDDStage.SPECIFY


def test_valid_forward_transition() -> None:
    pipeline = SDDPipeline(project="test")
    result = pipeline.advance(SDDStage.PLAN)
    assert result.passed is True
    assert pipeline.current_stage == SDDStage.PLAN


def test_invalid_skip_transition() -> None:
    pipeline = SDDPipeline(project="test")
    with pytest.raises(InvalidStageTransitionError):
        pipeline.advance(SDDStage.IMPLEMENT)


def test_reject_goes_back() -> None:
    pipeline = SDDPipeline(project="test")
    pipeline.advance(SDDStage.PLAN)
    pipeline.advance(SDDStage.TASKS)
    pipeline.reject(SDDStage.PLAN)
    assert pipeline.current_stage == SDDStage.PLAN


def test_reject_to_non_previous_raises() -> None:
    pipeline = SDDPipeline(project="test")
    pipeline.advance(SDDStage.PLAN)
    with pytest.raises(InvalidStageTransitionError):
        pipeline.reject(SDDStage.COMPLETE)


def test_full_pipeline_traversal() -> None:
    pipeline = SDDPipeline(project="test")
    for stage in [SDDStage.PLAN, SDDStage.TASKS, SDDStage.IMPLEMENT, SDDStage.VERIFY, SDDStage.COMPLETE]:
        result = pipeline.advance(stage)
        assert result.passed is True
    assert pipeline.current_stage == SDDStage.COMPLETE


def test_gate_check_with_custom_checker() -> None:
    def require_spec_exists(project: str) -> GateResult:
        return GateResult(passed=False, reason="No spec found")

    pipeline = SDDPipeline(project="test")
    pipeline.register_gate(SDDStage.SPECIFY, SDDStage.PLAN, require_spec_exists)
    result = pipeline.advance(SDDStage.PLAN)
    assert result.passed is False
    assert "No spec found" in result.reason
    assert pipeline.current_stage == SDDStage.SPECIFY


def test_gate_check_passes() -> None:
    def always_pass(project: str) -> GateResult:
        return GateResult(passed=True)

    pipeline = SDDPipeline(project="test")
    pipeline.register_gate(SDDStage.SPECIFY, SDDStage.PLAN, always_pass)
    result = pipeline.advance(SDDStage.PLAN)
    assert result.passed is True
    assert pipeline.current_stage == SDDStage.PLAN


def test_warning_mode_gate() -> None:
    def failing_gate(project: str) -> GateResult:
        return GateResult(passed=False, reason="Would block in strict mode")

    pipeline = SDDPipeline(project="test", strict_gates=False)
    pipeline.register_gate(SDDStage.SPECIFY, SDDStage.PLAN, failing_gate)
    result = pipeline.advance(SDDStage.PLAN)
    assert result.passed is True
    assert len(result.warnings) > 0
    assert pipeline.current_stage == SDDStage.PLAN


def test_history_tracking() -> None:
    pipeline = SDDPipeline(project="test")
    pipeline.advance(SDDStage.PLAN)
    pipeline.advance(SDDStage.TASKS)
    history = pipeline.get_history()
    assert len(history) == 2
    assert history[0]["to"] == "plan"
    assert history[1]["to"] == "tasks"
