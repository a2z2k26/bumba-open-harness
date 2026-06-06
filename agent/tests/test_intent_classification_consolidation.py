"""Consolidation invariants for the 4-layer routing stack (#1537).

These tests pin three properties that the routing stack relies on:

1. ``bridge.intent_classifier.classify`` is the canonical entry point for
   intent classification. All routing layers delegate through it.
2. ``bridge.operator_inbox.classify_severity`` classifies severity only
   (HALT/INFO/QUESTION) and shares no regex patterns with
   ``bridge.command_router.INTENT_PATTERNS``.
3. ``bridge.routing_cascade.RoutingCascade`` does not import or instantiate
   ``CommandRouter`` — the cascade does department-keyword routing, not
   intent routing, so the two layers stay decoupled.

If any of these break, intent classification is at risk of drifting into
multiple parallel implementations again — the exact failure mode the
consolidation eliminated.
"""
from __future__ import annotations

import inspect

import pytest


# ---------------------------------------------------------------------------
# Invariant 1: intent_classifier.classify is the canonical surface
# ---------------------------------------------------------------------------


def test_intent_classifier_exports_classify_and_intent() -> None:
    """intent_classifier exposes ``classify`` and re-exports ``Intent``."""
    from bridge import intent_classifier

    assert callable(intent_classifier.classify)
    assert hasattr(intent_classifier, "Intent")
    assert hasattr(intent_classifier, "IntentClassification")


def test_intent_classifier_returns_immutable_result() -> None:
    """The returned IntentClassification is frozen — caller cannot mutate."""
    from bridge.intent_classifier import Intent, classify

    result = classify("fix the auth bug")
    with pytest.raises((AttributeError, TypeError)):
        result.intent = Intent.UNKNOWN  # type: ignore[misc]


def test_routing_brain_delegates_through_intent_classifier() -> None:
    """routing_brain.py imports from intent_classifier, not command_router."""
    import bridge.routing_brain as rb

    source = inspect.getsource(rb)
    assert "from bridge.intent_classifier import" in source, (
        "routing_brain must delegate intent classification via intent_classifier"
    )
    # And must NOT reach into command_router directly for intent classification.
    # (A top-level import of CommandRouter would be the regression.)
    assert "from bridge.command_router import CommandRouter" not in source
    assert "from .command_router import CommandRouter" not in source


# ---------------------------------------------------------------------------
# Invariant 2: classify_severity is severity-only, no intent regex overlap
# ---------------------------------------------------------------------------


def test_classify_severity_returns_message_severity_not_intent() -> None:
    """classify_severity is on the severity axis, not the intent axis."""
    from bridge.command_router import Intent
    from bridge.operator_inbox import MessageSeverity, classify_severity

    result = classify_severity("fix the auth bug")
    assert isinstance(result, MessageSeverity)
    assert not isinstance(result, Intent)


def test_severity_triggers_disjoint_from_intent_patterns() -> None:
    """No regex pattern is shared between severity triggers and intent patterns.

    The two classifiers operate on orthogonal axes. If a literal trigger
    word ever lands in both sets, it's a sign the consolidation is drifting.
    """
    from bridge.command_router import CommandRouter
    from bridge.operator_inbox import (
        _CONVERSATIONAL_OPENERS,
        _HALT_PREFIX_TRIGGERS,
        _HALT_WORD_TRIGGERS,
        _INFO_PREFIXES,
    )

    # Collect every literal token used by severity classification.
    severity_tokens: set[str] = set()
    severity_tokens.update(_HALT_WORD_TRIGGERS)
    severity_tokens.update(_HALT_PREFIX_TRIGGERS)
    severity_tokens.update(p.strip() for p in _INFO_PREFIXES)
    severity_tokens.update(_CONVERSATIONAL_OPENERS)

    # Collect every literal regex pattern source used by intent classification.
    intent_pattern_sources: set[str] = set()
    for patterns in CommandRouter.INTENT_PATTERNS.values():
        intent_pattern_sources.update(patterns)

    # No severity token should appear verbatim as an intent regex pattern.
    # (Intent regexes use \b word boundaries — e.g. r"\bfix\b" — so a bare
    # token like "halt" cannot collide unless the pattern literally is "halt".)
    overlap = severity_tokens & intent_pattern_sources
    assert not overlap, (
        f"Severity tokens leaked into intent patterns: {overlap}. "
        f"classify_severity must stay severity-only (#1537)."
    )


def test_operator_inbox_does_not_import_intent_classifier() -> None:
    """operator_inbox stays decoupled from intent classification.

    Severity classification must not depend on intent — they are orthogonal.
    If operator_inbox ever needs an Intent value, the dependency should be
    surfaced explicitly (and this test updated) rather than added silently.
    """
    import bridge.operator_inbox as oi

    source = inspect.getsource(oi)
    assert "from bridge.intent_classifier" not in source
    assert "from .intent_classifier" not in source
    assert "from bridge.command_router" not in source
    assert "from .command_router" not in source


# ---------------------------------------------------------------------------
# Invariant 3: RoutingCascade does not import or instantiate CommandRouter
# ---------------------------------------------------------------------------


def test_routing_cascade_does_not_import_command_router() -> None:
    """routing_cascade.py does department-keyword routing, not intent routing.

    Before #1537 the cascade carried an unused ``self._command_router =
    CommandRouter()`` instance — dead code that invited future scope creep.
    This test pins the cleanup: the cascade must not depend on the intent
    surface at all.
    """
    import bridge.routing_cascade as rc

    source = inspect.getsource(rc)
    # Forbid the actual import statements and instantiation — but allow the
    # name to appear in comments (e.g. the consolidation note that explains
    # WHY the dependency was removed).
    forbidden = (
        "from bridge.command_router import CommandRouter",
        "from .command_router import CommandRouter",
        "import bridge.command_router",
        "CommandRouter()",
    )
    for needle in forbidden:
        assert needle not in source, (
            f"routing_cascade must not contain {needle!r} (#1537)"
        )


def test_routing_cascade_has_no_command_router_attribute() -> None:
    """Instantiated RoutingCascade carries no _command_router attribute."""
    from bridge.routing_cascade import RoutingCascade

    cascade = RoutingCascade()
    assert not hasattr(cascade, "_command_router"), (
        "RoutingCascade._command_router was dead code; removed by #1537"
    )
