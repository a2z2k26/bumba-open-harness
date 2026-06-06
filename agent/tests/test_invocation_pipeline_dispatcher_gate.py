"""Tests for the D-R2 dispatcher intent gate (Sprint D-R2, #1932).

The gate sits in ``invocation_pipeline.invoke_claude_pipeline``: when the
dispatcher feature flag is on, the gate classifies the operator's
message and only enters the dispatcher branch when the intent is in
``ZONE4_INTENTS`` with confidence ≥ ``DISPATCHER_MIN_CONFIDENCE``. All
other traffic falls through to the warm process.

These tests cover the decision logic in isolation — the full pipeline
integration is covered indirectly by the existing ``test_app*`` suites.
"""
from __future__ import annotations

import pytest

from bridge.dispatcher import Dispatcher
from bridge.intent_classifier import (
    DISPATCHER_MIN_CONFIDENCE,
    ZONE4_INTENTS,
    Intent,
    classify,
)


# ---------------------------------------------------------------------------
# Constants surface
# ---------------------------------------------------------------------------


def test_zone4_intents_contents() -> None:
    """The five Zone 4 chief intents and exactly those should gate."""
    assert ZONE4_INTENTS == frozenset({
        Intent.BOARD_QUERY,
        Intent.QA_REVIEW,
        Intent.OPS_DIAGNOSE,
        Intent.STRATEGY_ANALYZE,
        Intent.DESIGN_REVIEW,
    })


def test_dispatcher_min_confidence_is_strict() -> None:
    """0.8 is the threshold — high enough that an ambiguous match doesn't
    accidentally trigger Z4 routing for a conversational message."""
    assert DISPATCHER_MIN_CONFIDENCE == 0.8
    assert 0.0 < DISPATCHER_MIN_CONFIDENCE <= 1.0


def test_unknown_intent_is_not_in_zone4() -> None:
    """The fallback intent for unclassifiable text never enters the gate."""
    assert Intent.UNKNOWN not in ZONE4_INTENTS


def test_zone3_engineering_intents_not_in_zone4() -> None:
    """Pure engineering intents (BUILD/FIX/TEST/DEPLOY/etc.) bypass the
    dispatcher under D-R2 and route directly to warm — those should not
    accidentally land in the Z4 gate."""
    for non_z4 in (
        Intent.BUILD, Intent.FIX, Intent.TEST,
        Intent.DEPLOY, Intent.ANALYZE, Intent.OPTIMIZE, Intent.DOCUMENT,
    ):
        assert non_z4 not in ZONE4_INTENTS


# ---------------------------------------------------------------------------
# Gate decision — applied to real classifier outputs
# ---------------------------------------------------------------------------


def _gate_pass(message: str) -> bool:
    """Replicate the gate decision in invocation_pipeline for testing."""
    classification = classify(message)
    return (
        classification.intent in ZONE4_INTENTS
        and classification.confidence >= DISPATCHER_MIN_CONFIDENCE
    )


@pytest.mark.parametrize("greeting", [
    "hi", "hey", "hello", "ok", "thanks", "got it", "lgtm",
])
def test_conversational_greetings_do_not_pass_gate(greeting: str) -> None:
    """Greetings should not enter the dispatcher — they're conversational."""
    assert _gate_pass(greeting) is False, (
        f"'{greeting}' must not pass the dispatcher gate "
        "— greetings are conversational and route to warm directly."
    )


@pytest.mark.parametrize("status_query", [
    "what's my status",
    "what is the queue depth",
    "how are things going",
])
def test_status_questions_do_not_pass_gate(status_query: str) -> None:
    """Status questions are conversational, not Zone 4 chief work."""
    assert _gate_pass(status_query) is False


def test_low_confidence_zone4_match_does_not_pass_gate() -> None:
    """A keyword that could be ambiguous (low confidence) must not enter
    the dispatcher. We assert the threshold semantics by inspecting a
    classification that lands in Zone 4 but with confidence < 0.8."""
    # Construct a fake-low-confidence path through the gate decision
    # without coupling to actual classifier output (which is dataset-dependent).
    from bridge.intent_classifier import IntentClassification

    fake_low = IntentClassification(
        intent=Intent.BOARD_QUERY,
        confidence=0.5,
        complexity=2,
    )
    gate_pass = (
        fake_low.intent in ZONE4_INTENTS
        and fake_low.confidence >= DISPATCHER_MIN_CONFIDENCE
    )
    assert gate_pass is False


def test_high_confidence_zone4_match_passes_gate() -> None:
    """A high-confidence Zone 4 match (intent in set, confidence ≥ 0.8)
    must enter the dispatcher branch."""
    from bridge.intent_classifier import IntentClassification

    fake_high = IntentClassification(
        intent=Intent.BOARD_QUERY,
        confidence=0.9,
        complexity=2,
    )
    gate_pass = (
        fake_high.intent in ZONE4_INTENTS
        and fake_high.confidence >= DISPATCHER_MIN_CONFIDENCE
    )
    assert gate_pass is True


# ---------------------------------------------------------------------------
# Dispatcher type guard (D-R2 boundary check)
# ---------------------------------------------------------------------------


def test_dispatch_rejects_raw_string() -> None:
    """``Dispatcher.dispatch()`` must raise TypeError on non-WorkOrder
    input — defense against pre-D-R2's pattern of passing raw text."""
    import asyncio

    dispatcher = Dispatcher.__new__(Dispatcher)  # bypass __init__ for unit test

    with pytest.raises(TypeError, match="WorkOrder instance"):
        asyncio.run(dispatcher.dispatch("hi this is a conversation"))  # type: ignore[arg-type]


def test_dispatch_typeerror_mentions_epic() -> None:
    """The TypeError message must direct the reader to the epic so a
    future debugger doesn't repeat the dispatcher-on-strings mistake."""
    import asyncio

    dispatcher = Dispatcher.__new__(Dispatcher)

    with pytest.raises(TypeError) as excinfo:
        asyncio.run(dispatcher.dispatch(42))  # type: ignore[arg-type]

    msg = str(excinfo.value)
    assert "dispatcher-re-envision" in msg
    assert "warm process" in msg.lower()
