"""Tests for ``bridge.warm_policy.should_use_warm_path`` (Sprint P1.3, #1571).

Covers the audit-plan Option C decision tree:

1. opus models → one-shot (False)
2. is_workorder=True → one-shot (False)
3. has_tools=True → one-shot (False)
4. intent=None → one-shot (False) — operator-mandated fail-safe
5. intent in HIGH_RISK_INTENTS → one-shot (False)
6. otherwise (low-risk chat) → warm (True)
"""

from __future__ import annotations

import pytest

from bridge.warm_policy import (
    HIGH_RISK_INTENTS,
    should_use_warm_path,
)
from bridge.model_router import CAREFUL_OPUS_MODEL


# ---------------------------------------------------------------------------
# Rule 1 — opus models always one-shot
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("model", ["opus", CAREFUL_OPUS_MODEL])
def test_opus_models_force_one_shot(model: str) -> None:
    """opus / careful-opus always route to one-shot regardless of other args."""
    assert should_use_warm_path(
        model=model,
        intent="chat",
        has_tools=False,
        is_workorder=False,
    ) is False


def test_opus_force_one_shot_even_with_safe_intent() -> None:
    assert should_use_warm_path(
        model="opus",
        intent="analyze",
        has_tools=False,
        is_workorder=False,
    ) is False


# ---------------------------------------------------------------------------
# Rule 2 — workorders always one-shot
# ---------------------------------------------------------------------------


def test_workorder_forces_one_shot() -> None:
    """is_workorder=True must override everything else."""
    assert should_use_warm_path(
        model="haiku",
        intent="chat",
        has_tools=False,
        is_workorder=True,
    ) is False


def test_workorder_forces_one_shot_even_for_safe_intent() -> None:
    assert should_use_warm_path(
        model="sonnet",
        intent="analyze",
        has_tools=False,
        is_workorder=True,
    ) is False


# ---------------------------------------------------------------------------
# Rule 3 — tool-bearing messages always one-shot
# ---------------------------------------------------------------------------


def test_has_tools_forces_one_shot() -> None:
    """has_tools=True must override everything else (except workorder)."""
    assert should_use_warm_path(
        model="haiku",
        intent="chat",
        has_tools=True,
        is_workorder=False,
    ) is False


def test_has_tools_forces_one_shot_with_safe_intent() -> None:
    assert should_use_warm_path(
        model="sonnet",
        intent="document",
        has_tools=True,
        is_workorder=False,
    ) is False


# ---------------------------------------------------------------------------
# Rule 4 — intent=None FAIL-SAFE to one-shot (operator-mandated)
# ---------------------------------------------------------------------------


def test_intent_none_falls_through_to_one_shot() -> None:
    """When intent classification fails (returns None), we MUST fall through
    to one-shot, NOT warm.

    Operator-mandated fail-safe (Sprint P1.3): the dangerous default would
    be 'we couldn't classify so we defaulted to warm' — we explicitly
    reject that. This test is the durable guard against accidental
    inversion of the default.
    """
    assert should_use_warm_path(
        model="haiku",
        intent=None,
        has_tools=False,
        is_workorder=False,
    ) is False


def test_intent_none_fail_safe_holds_across_models() -> None:
    """intent=None forces one-shot regardless of model tier."""
    for model in ("haiku", "sonnet"):
        assert should_use_warm_path(
            model=model,
            intent=None,
            has_tools=False,
            is_workorder=False,
        ) is False, f"intent=None must fail-safe to one-shot for model={model}"


# ---------------------------------------------------------------------------
# Rule 5 — high-risk intents always one-shot
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("intent", [
    "code",
    "deploy",
    "security",
    "job_search_execute",
])
def test_audit_plan_literal_high_risk_intents_force_one_shot(intent: str) -> None:
    """The operator-mandated audit-plan literal set must never use warm."""
    assert should_use_warm_path(
        model="haiku",
        intent=intent,
        has_tools=False,
        is_workorder=False,
    ) is False


@pytest.mark.parametrize("intent", [
    "build",
    "fix",
    "optimize",
    "ops_diagnose",
])
def test_current_classifier_high_risk_intents_force_one_shot(intent: str) -> None:
    """Actual ``bridge.command_router.Intent`` values that map to high-risk
    concepts in today's classifier must also route to one-shot.
    """
    assert should_use_warm_path(
        model="haiku",
        intent=intent,
        has_tools=False,
        is_workorder=False,
    ) is False


def test_high_risk_intents_constant_includes_audit_plan_literals() -> None:
    """Regression guard: the operator-mandated audit-plan labels MUST appear
    in ``HIGH_RISK_INTENTS``. Removing them silently inverts the policy.
    """
    for label in ("code", "deploy", "security", "job_search_execute"):
        assert label in HIGH_RISK_INTENTS, (
            f"audit-plan literal {label!r} missing from HIGH_RISK_INTENTS"
        )


def test_high_risk_intents_frozen() -> None:
    """HIGH_RISK_INTENTS must be frozen so callers can't mutate it."""
    assert isinstance(HIGH_RISK_INTENTS, frozenset)


# ---------------------------------------------------------------------------
# Rule 6 — low-risk chat permits warm
# ---------------------------------------------------------------------------


def test_low_risk_chat_haiku_uses_warm() -> None:
    """Canonical happy-path: short conversational message on haiku."""
    assert should_use_warm_path(
        model="haiku",
        intent="unknown",
        has_tools=False,
        is_workorder=False,
    ) is True


def test_low_risk_chat_sonnet_uses_warm() -> None:
    """Sonnet on a low-risk intent — also warm."""
    assert should_use_warm_path(
        model="sonnet",
        intent="unknown",
        has_tools=False,
        is_workorder=False,
    ) is True


@pytest.mark.parametrize("intent", [
    "analyze",
    "test",
    "document",
    "qa_review",
    "strategy_analyze",
    "design_review",
    "board_query",
    "unknown",
])
def test_low_risk_intents_permit_warm(intent: str) -> None:
    """Read-only / advisory intents on a non-opus model are warm-safe."""
    assert should_use_warm_path(
        model="haiku",
        intent=intent,
        has_tools=False,
        is_workorder=False,
    ) is True


# ---------------------------------------------------------------------------
# Full decision tree walk
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "model,intent,has_tools,is_workorder,expected",
    [
        # opus always one-shot
        ("opus", "unknown", False, False, False),
        (CAREFUL_OPUS_MODEL, "unknown", False, False, False),
        # workorder always one-shot
        ("haiku", "unknown", False, True, False),
        ("sonnet", "analyze", False, True, False),
        # has_tools always one-shot
        ("haiku", "unknown", True, False, False),
        ("sonnet", "document", True, False, False),
        # intent=None fail-safe to one-shot
        ("haiku", None, False, False, False),
        ("sonnet", None, False, False, False),
        # high-risk intents one-shot
        ("haiku", "code", False, False, False),
        ("haiku", "deploy", False, False, False),
        ("haiku", "security", False, False, False),
        ("haiku", "job_search_execute", False, False, False),
        ("haiku", "build", False, False, False),
        ("haiku", "fix", False, False, False),
        ("haiku", "optimize", False, False, False),
        ("haiku", "ops_diagnose", False, False, False),
        # low-risk → warm
        ("haiku", "unknown", False, False, True),
        ("haiku", "analyze", False, False, True),
        ("haiku", "test", False, False, True),
        ("haiku", "document", False, False, True),
        ("sonnet", "unknown", False, False, True),
        ("sonnet", "analyze", False, False, True),
        # precedence: opus beats safe intent
        ("opus", "unknown", False, False, False),
        # precedence: workorder beats safe model+intent
        ("haiku", "unknown", False, True, False),
        # precedence: has_tools beats safe model+intent
        ("haiku", "unknown", True, False, False),
    ],
)
def test_full_decision_tree(
    model: str,
    intent: str | None,
    has_tools: bool,
    is_workorder: bool,
    expected: bool,
) -> None:
    """Parametrized walk of the full Option C decision tree."""
    assert should_use_warm_path(
        model=model,
        intent=intent,
        has_tools=has_tools,
        is_workorder=is_workorder,
    ) is expected


# ---------------------------------------------------------------------------
# API hygiene
# ---------------------------------------------------------------------------


def test_keyword_only_signature() -> None:
    """should_use_warm_path is keyword-only — calling positionally must fail.

    This protects against accidental argument reordering at call sites.
    """
    with pytest.raises(TypeError):
        # Positional call — must raise.
        should_use_warm_path("haiku", "chat", False, False)  # type: ignore[misc]


def test_pure_function_no_side_effects() -> None:
    """Calling the function repeatedly with same inputs yields same output."""
    args = dict(model="haiku", intent="unknown", has_tools=False, is_workorder=False)
    first = should_use_warm_path(**args)
    second = should_use_warm_path(**args)
    third = should_use_warm_path(**args)
    assert first == second == third is True
