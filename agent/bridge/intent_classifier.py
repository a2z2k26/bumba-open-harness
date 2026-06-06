"""Intent classifier adapter — canonical surface for intent classification.

This module is the **single canonical entry point** for intent classification
across the 4-layer routing stack (#1537). All callers (app.py, routing_brain,
routing_cascade, future routers) MUST go through ``classify(message_text)``
rather than instantiating ``CommandRouter`` directly. ``command_router`` is
the implementation; ``intent_classifier`` is the contract.

Severity classification (HALT/INFO/QUESTION) is a separate concern and lives
in ``bridge.operator_inbox.classify_severity``. The two surfaces are orthogonal
and must not be merged: intent classifies *what the operator wants done*;
severity classifies *how urgently the agent must respond*.

Exposes ``classify(message_text) -> IntentClassification`` without requiring
callers to import from ``bridge.command_router`` directly.
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

from .command_router import CommandRouter
# Re-export Intent so callers never need to reach into orchestration/
from .command_router import Intent  # noqa: F401
from bridge.dispatch_metrics import increment_module_counter


@dataclass(frozen=True)
class IntentClassification:
    """Result of classifying a message's intent."""
    intent: Intent
    confidence: float   # 0.0–1.0
    complexity: int     # 1–5


# Sprint D-R2 (#1932) — Zone 4 dispatcher gate. The dispatcher branch in
# ``invocation_pipeline`` only fires when a classified message's intent is
# in this set AND its confidence clears ``DISPATCHER_MIN_CONFIDENCE``. All
# other messages route directly to the warm process. Scaffolding wrapped by
# D-R4's MessageClassifier; constants remain load-bearing inside D-R4's
# ZONE4_EXPLICIT branch.
ZONE4_INTENTS: frozenset[Intent] = frozenset({
    Intent.BOARD_QUERY,
    Intent.QA_REVIEW,
    Intent.OPS_DIAGNOSE,
    Intent.STRATEGY_ANALYZE,
    Intent.DESIGN_REVIEW,
})

DISPATCHER_MIN_CONFIDENCE: float = 0.8


@lru_cache(maxsize=1)
def _get_router() -> CommandRouter:
    """Return a shared CommandRouter instance (created once)."""
    return CommandRouter()


def classify(message_text: str) -> IntentClassification:
    increment_module_counter("intent_classifier.classify", tier=2)
    """Classify the intent of a message.

    Args:
        message_text: The raw message text to classify.

    Returns:
        IntentClassification with intent, confidence (0–1), and complexity (1–5).
    """
    router = _get_router()
    match = router.route(message_text)
    return IntentClassification(
        intent=match.intent,
        confidence=match.confidence,
        complexity=match.complexity,
    )
