"""Tests for bridge.intent_classifier adapter."""
from __future__ import annotations

import pytest
from bridge.intent_classifier import classify, Intent, IntentClassification


@pytest.mark.parametrize("text,expected_intent", [
    ("fix the bug in auth.py", Intent.FIX),
    ("build a new feature for payments", Intent.BUILD),
    ("run the test suite", Intent.TEST),
    ("deploy to production", Intent.DEPLOY),
    ("analyze the logs for errors", Intent.ANALYZE),
    ("optimize the query performance", Intent.OPTIMIZE),
    ("document the API endpoints", Intent.DOCUMENT),
    ("what is the weather today", Intent.UNKNOWN),
])
def test_classify_intent(text, expected_intent):
    result = classify(text)
    assert isinstance(result, IntentClassification)
    assert result.intent == expected_intent, (
        f"Expected {expected_intent} for '{text}', got {result.intent}"
    )


def test_confidence_range():
    for text in ["fix the auth bug", "build a dashboard", "run tests"]:
        result = classify(text)
        assert 0.0 <= result.confidence <= 1.0, (
            f"confidence {result.confidence} out of range for '{text}'"
        )


def test_complexity_range():
    for text in ["fix the auth bug", "build a dashboard", "run tests"]:
        result = classify(text)
        assert 1 <= result.complexity <= 5, (
            f"complexity {result.complexity} out of range for '{text}'"
        )


def test_intent_reexported():
    """Intent enum must be importable directly from bridge.intent_classifier."""
    from bridge.intent_classifier import Intent as I
    assert hasattr(I, "FIX")
    assert hasattr(I, "BUILD")
    assert hasattr(I, "TEST")
    assert hasattr(I, "DEPLOY")
    assert hasattr(I, "ANALYZE")
    assert hasattr(I, "OPTIMIZE")
    assert hasattr(I, "DOCUMENT")
    assert hasattr(I, "UNKNOWN")


def test_returns_intent_classification_type():
    result = classify("fix the login issue")
    assert isinstance(result, IntentClassification)


def test_frozen_dataclass():
    """IntentClassification must be immutable (frozen=True)."""
    result = classify("build a new API")
    with pytest.raises((AttributeError, TypeError)):
        result.intent = Intent.UNKNOWN  # type: ignore[misc]


def test_classify_returns_consistent_results():
    """Same input must produce the same classification."""
    text = "deploy the service to staging"
    r1 = classify(text)
    r2 = classify(text)
    assert r1 == r2


def test_router_singleton():
    """_get_router must return the same instance on repeated calls."""
    from bridge.intent_classifier import _get_router
    assert _get_router() is _get_router()
