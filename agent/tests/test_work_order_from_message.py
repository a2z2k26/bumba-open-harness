"""Tests for ``WorkOrder.from_message()`` (Sprint D-R2, #1932)."""
from __future__ import annotations

from bridge.work_order import WorkOrder, WorkOrderStatus


def test_from_message_returns_work_order():
    wo = WorkOrder.from_message("hello world", intent="board_query")
    assert isinstance(wo, WorkOrder)
    assert wo.id  # uuid generated
    assert wo.status == WorkOrderStatus.PENDING


def test_from_message_carries_text_and_trigger_source():
    wo = WorkOrder.from_message("deliberate the architecture", intent="board_query")
    assert wo.input.text == "deliberate the architecture"
    assert wo.trigger_source == "discord"


def test_from_message_default_cost_cap():
    wo = WorkOrder.from_message("review the QA report", intent="qa_review")
    assert wo.cost_cap_usd == 0.50


def test_from_message_intent_carried_verbatim():
    wo = WorkOrder.from_message("diagnose the outage", intent="ops_diagnose")
    assert wo.intent == "ops_diagnose"


def test_from_message_supports_explicit_cost_cap_override():
    wo = WorkOrder.from_message(
        "long deliberation",
        intent="board_query",
        cost_cap_usd=1.50,
    )
    assert wo.cost_cap_usd == 1.50
