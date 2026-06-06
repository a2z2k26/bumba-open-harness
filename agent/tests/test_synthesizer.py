"""Tests for result synthesis."""

from __future__ import annotations

import pytest

from bridge.synthesizer import Synthesizer, SynthesisMode
from bridge.work_order import WorkOrder, WorkOrderOutput, WorkOrderStatus


@pytest.fixture
def synthesizer() -> Synthesizer:
    return Synthesizer()


def _completed_wo(intent: str, result: str) -> WorkOrder:
    wo = WorkOrder.create(intent=intent, skill="test", project="p")
    wo = wo.transition(WorkOrderStatus.ASSIGNED)
    wo = wo.transition(WorkOrderStatus.EXECUTING)
    wo = wo.transition(WorkOrderStatus.VERIFYING)
    wo = wo.transition(WorkOrderStatus.COMPLETE)
    return wo.with_output(WorkOrderOutput(result=result))


def test_concatenate_mode(synthesizer: Synthesizer) -> None:
    wo1 = _completed_wo("Build backend", "Backend API complete with 3 endpoints")
    wo2 = _completed_wo("Build frontend", "Frontend components created: Header, Footer, Main")
    result = synthesizer.synthesize([wo1, wo2], mode=SynthesisMode.CONCATENATE)
    assert result.success is True
    assert "Backend API complete" in result.combined
    assert "Frontend components created" in result.combined


def test_concatenate_empty_list(synthesizer: Synthesizer) -> None:
    result = synthesizer.synthesize([], mode=SynthesisMode.CONCATENATE)
    assert result.success is True
    assert result.combined == ""


def test_concatenate_single_item(synthesizer: Synthesizer) -> None:
    wo = _completed_wo("Single task", "Done")
    result = synthesizer.synthesize([wo], mode=SynthesisMode.CONCATENATE)
    assert result.success is True
    assert "Done" in result.combined


def test_structured_merge_mode(synthesizer: Synthesizer) -> None:
    wo1 = _completed_wo("Tests A", '{"tests": ["test_a1", "test_a2"]}')
    wo2 = _completed_wo("Tests B", '{"tests": ["test_b1"]}')
    result = synthesizer.synthesize([wo1, wo2], mode=SynthesisMode.STRUCTURED_MERGE, merge_key="tests")
    assert result.success is True
    assert "test_a1" in result.combined
    assert "test_b1" in result.combined


def test_flags_incomplete_work_orders(synthesizer: Synthesizer) -> None:
    complete = _completed_wo("Done task", "result")
    incomplete = WorkOrder.create(intent="Not done", skill="test", project="p")
    result = synthesizer.synthesize([complete, incomplete], mode=SynthesisMode.CONCATENATE)
    assert result.success is True
    assert len(result.warnings) > 0
    assert "Not done" in result.warnings[0] or "incomplete" in result.warnings[0].lower()


def test_flags_context_incomplete(synthesizer: Synthesizer) -> None:
    wo = _completed_wo("Task", "result")
    result = synthesizer.synthesize(
        [wo],
        mode=SynthesisMode.CONCATENATE,
        context_complete_flags={"context-incomplete": [wo.id]},
    )
    assert len(result.warnings) > 0
