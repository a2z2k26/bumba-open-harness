"""Tests for synthesizer strategies (#572 sub-bet 1)."""
from __future__ import annotations

import json

from bridge.synthesis_strategies import (
    TextConcat,
    StructuredMerge,
    LLMSynthesis,
    FirstResult,
    get_strategy,
    register_strategy,
)
from bridge.synthesizer import SynthesisMode, SynthesisResult
from bridge.work_order import WorkOrder, WorkOrderOutput, WorkOrderStatus
from dataclasses import replace


def _make_wo(intent: str, result: str, status: WorkOrderStatus = WorkOrderStatus.COMPLETE) -> WorkOrder:
    wo = WorkOrder.create(intent=intent, skill="test", project="proj")
    wo = replace(wo, status=status, output=WorkOrderOutput(result=result))
    return wo


# ---------------------------------------------------------------------------
# TextConcat
# ---------------------------------------------------------------------------

def test_text_concat_combines_outputs():
    strategy = TextConcat()
    wos = [_make_wo("task-1", "output-1"), _make_wo("task-2", "output-2")]
    result = strategy.combine(wos)
    assert result.success is True
    assert "output-1" in result.combined
    assert "output-2" in result.combined
    assert result.mode == SynthesisMode.CONCATENATE


def test_text_concat_warns_on_incomplete():
    strategy = TextConcat()
    wos = [
        _make_wo("task-1", "output-1"),
        _make_wo("task-2", "output-2", status=WorkOrderStatus.FAILED),
    ]
    result = strategy.combine(wos)
    assert result.success is True
    assert len(result.warnings) == 1
    assert "incomplete" in result.warnings[0]


def test_text_concat_empty():
    strategy = TextConcat()
    result = strategy.combine([])
    assert result.success is True
    assert result.combined == ""


# ---------------------------------------------------------------------------
# StructuredMerge
# ---------------------------------------------------------------------------

def test_structured_merge_with_key():
    strategy = StructuredMerge()
    wos = [
        _make_wo("task-1", json.dumps({"items": ["a", "b"]})),
        _make_wo("task-2", json.dumps({"items": ["c"]})),
    ]
    result = strategy.combine(wos, merge_key="items")
    assert result.success is True
    data = json.loads(result.combined)
    assert set(data["items"]) == {"a", "b", "c"}


def test_structured_merge_invalid_json():
    strategy = StructuredMerge()
    wos = [_make_wo("task-1", "not json")]
    result = strategy.combine(wos, merge_key="items")
    assert result.success is True
    assert len(result.warnings) > 0


# ---------------------------------------------------------------------------
# LLMSynthesis (stub)
# ---------------------------------------------------------------------------

def test_llm_synthesis_falls_back_to_concat():
    strategy = LLMSynthesis()
    wos = [_make_wo("task", "result")]
    result = strategy.combine(wos)
    assert result.success is True
    assert "result" in result.combined


# ---------------------------------------------------------------------------
# FirstResult
# ---------------------------------------------------------------------------

def test_first_result_returns_first_complete():
    strategy = FirstResult()
    wos = [
        _make_wo("task-1", "first-output"),
        _make_wo("task-2", "second-output"),
    ]
    result = strategy.combine(wos)
    assert result.success is True
    assert result.combined == "first-output"


def test_first_result_no_complete():
    strategy = FirstResult()
    wos = [_make_wo("task", "", status=WorkOrderStatus.FAILED)]
    result = strategy.combine(wos)
    assert result.success is False


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

def test_get_strategy_returns_correct_type():
    assert isinstance(get_strategy(SynthesisMode.CONCATENATE), TextConcat)
    assert isinstance(get_strategy(SynthesisMode.STRUCTURED_MERGE), StructuredMerge)
    assert isinstance(get_strategy(SynthesisMode.LLM_SYNTHESIS), LLMSynthesis)


def test_register_strategy_overrides():
    class MyStrategy:
        mode = SynthesisMode.CONCATENATE
        def combine(self, wos, **opts):
            return SynthesisResult(success=True, combined="custom")

    register_strategy(MyStrategy())
    assert isinstance(get_strategy(SynthesisMode.CONCATENATE), MyStrategy)
    # Restore
    register_strategy(TextConcat())
