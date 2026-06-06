"""Tests for bridge.routing_brain — RoutingBrain and RoutingDecision."""
from __future__ import annotations

import dataclasses
import pytest

from bridge.routing_brain import RoutingBrain, RoutingDecision
from bridge.intent_classifier import Intent


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _brain(selector=None) -> RoutingBrain:
    return RoutingBrain(selector=selector)


# ---------------------------------------------------------------------------
# 1. Low complexity (1-2) → "subagent"
# ---------------------------------------------------------------------------

class TestLowComplexityRoutesToSubagent:
    """Messages with complexity 1 or 2 should always route to subagent."""

    def test_trivial_fix_routes_subagent(self):
        brain = _brain()
        # Short, trivially simple messages score complexity 1
        decision = brain.decide("fix")
        assert decision.environment == "subagent", (
            f"Expected subagent for low-complexity 'fix', got {decision.environment!r}"
        )

    def test_complexity_2_routes_subagent(self, monkeypatch):
        """Patch classify to return complexity=2 and verify environment."""
        from bridge import routing_brain
        from bridge.intent_classifier import IntentClassification

        monkeypatch.setattr(
            routing_brain,
            "classify",
            lambda text: IntentClassification(
                intent=Intent.FIX, confidence=0.9, complexity=2
            ),
        )
        decision = _brain().decide("fix the typo")
        assert decision.environment == "subagent"

    def test_complexity_1_routes_subagent(self, monkeypatch):
        from bridge import routing_brain
        from bridge.intent_classifier import IntentClassification

        monkeypatch.setattr(
            routing_brain,
            "classify",
            lambda text: IntentClassification(
                intent=Intent.UNKNOWN, confidence=0.5, complexity=1
            ),
        )
        decision = _brain().decide("hi")
        assert decision.environment == "subagent"


# ---------------------------------------------------------------------------
# 2. High complexity (5) → "worktree"
# ---------------------------------------------------------------------------

class TestHighComplexityRoutesToWorktree:
    """Complexity 5 must always produce worktree regardless of selector."""

    def test_complexity_5_always_worktree(self, monkeypatch):
        from bridge import routing_brain
        from bridge.intent_classifier import IntentClassification

        monkeypatch.setattr(
            routing_brain,
            "classify",
            lambda text: IntentClassification(
                intent=Intent.BUILD, confidence=0.95, complexity=5
            ),
        )
        decision = _brain().decide("build a complex distributed system")
        assert decision.environment == "worktree"

    def test_complexity_5_worktree_beats_selector(self, monkeypatch):
        """Even when selector returns 'subagent', complexity>=5 forces worktree."""
        from bridge import routing_brain
        from bridge.intent_classifier import IntentClassification

        monkeypatch.setattr(
            routing_brain,
            "classify",
            lambda text: IntentClassification(
                intent=Intent.BUILD, confidence=0.95, complexity=5
            ),
        )

        class _FakeSelector:
            def suggest(self, *, intent: str, complexity: int) -> str:
                return "subagent"  # tries to override — must be ignored

        decision = _brain(selector=_FakeSelector()).decide("build it all")
        assert decision.environment == "worktree"

    def test_complexity_4_text_routes_worktree(self, monkeypatch):
        """complexity >= 4 AND modality == 'text' → worktree."""
        from bridge import routing_brain
        from bridge.intent_classifier import IntentClassification

        monkeypatch.setattr(
            routing_brain,
            "classify",
            lambda text: IntentClassification(
                intent=Intent.BUILD, confidence=0.9, complexity=4
            ),
        )
        decision = _brain().decide("refactor the whole auth module", modality="text")
        assert decision.environment == "worktree"

    def test_complexity_4_non_text_does_not_force_worktree(self, monkeypatch):
        """complexity == 4 with modality != 'text' does NOT force worktree."""
        from bridge import routing_brain
        from bridge.intent_classifier import IntentClassification

        monkeypatch.setattr(
            routing_brain,
            "classify",
            lambda text: IntentClassification(
                intent=Intent.BUILD, confidence=0.9, complexity=4
            ),
        )
        decision = _brain().decide("build this", modality="voice")
        # Should NOT be worktree — falls to moderate/subagent path
        assert decision.environment != "worktree"


# ---------------------------------------------------------------------------
# 3. RoutingDecision is frozen (FrozenInstanceError on mutation)
# ---------------------------------------------------------------------------

class TestRoutingDecisionIsFrozen:
    def test_cannot_set_field(self):
        decision = _brain().decide("fix the bug")
        with pytest.raises(dataclasses.FrozenInstanceError):
            decision.environment = "tmux"  # type: ignore[misc]

    def test_cannot_set_intent(self):
        decision = _brain().decide("build a dashboard")
        with pytest.raises(dataclasses.FrozenInstanceError):
            decision.intent = Intent.UNKNOWN  # type: ignore[misc]

    def test_cannot_set_reason(self):
        decision = _brain().decide("deploy to prod")
        with pytest.raises(dataclasses.FrozenInstanceError):
            decision.reason = ""  # type: ignore[misc]


# ---------------------------------------------------------------------------
# 4. Works without EnvironmentSelector (None)
# ---------------------------------------------------------------------------

class TestWorksWithoutSelector:
    def test_none_selector_does_not_raise(self):
        brain = RoutingBrain(selector=None)
        decision = brain.decide("fix the login bug")
        assert isinstance(decision, RoutingDecision)

    def test_default_constructor_uses_none(self):
        brain = RoutingBrain()
        decision = brain.decide("analyze the logs")
        assert isinstance(decision, RoutingDecision)

    def test_moderate_complexity_without_selector_defaults_subagent(self, monkeypatch):
        from bridge import routing_brain
        from bridge.intent_classifier import IntentClassification

        # Use OPTIMIZE intent — not in the department mapping table, so it
        # falls through to the default moderate-range subagent path.
        monkeypatch.setattr(
            routing_brain,
            "classify",
            lambda text: IntentClassification(
                intent=Intent.OPTIMIZE, confidence=0.8, complexity=3
            ),
        )
        decision = RoutingBrain(selector=None).decide("optimize this")
        assert decision.environment == "subagent"


# ---------------------------------------------------------------------------
# 5. intent and confidence fields populated from intent_classifier
# ---------------------------------------------------------------------------

class TestFieldsPopulatedFromClassifier:
    def test_intent_field_is_intent_enum(self):
        decision = _brain().decide("fix the auth module")
        assert isinstance(decision.intent, Intent)

    def test_confidence_within_range(self):
        decision = _brain().decide("build a new API endpoint")
        assert 0.0 <= decision.confidence <= 1.0

    def test_complexity_within_range(self):
        decision = _brain().decide("test the payment flow")
        assert 1 <= decision.complexity <= 5

    def test_classifier_values_propagated(self, monkeypatch):
        from bridge import routing_brain
        from bridge.intent_classifier import IntentClassification

        monkeypatch.setattr(
            routing_brain,
            "classify",
            lambda text: IntentClassification(
                intent=Intent.DEPLOY, confidence=0.77, complexity=3
            ),
        )
        decision = _brain().decide("deploy the app")
        assert decision.intent == Intent.DEPLOY
        assert decision.confidence == pytest.approx(0.77)
        assert decision.complexity == 3


# ---------------------------------------------------------------------------
# 6. modality defaults to "text"
# ---------------------------------------------------------------------------

class TestModalityDefault:
    def test_default_modality_is_text(self):
        decision = _brain().decide("fix the issue")
        assert decision.modality == "text"

    def test_custom_modality_stored(self):
        decision = _brain().decide("fix the issue", modality="voice")
        assert decision.modality == "voice"

    def test_modality_file(self):
        decision = _brain().decide("analyze the file", modality="file")
        assert decision.modality == "file"


# ---------------------------------------------------------------------------
# 7. reason is a non-empty string
# ---------------------------------------------------------------------------

class TestReasonIsNonEmpty:
    @pytest.mark.parametrize("text,modality", [
        ("fix a typo", "text"),
        ("build a full microservices platform with ten services", "text"),
        ("hi", "text"),
        ("deploy everything now", "voice"),
    ])
    def test_reason_non_empty(self, text, modality):
        decision = _brain().decide(text, modality=modality)
        assert isinstance(decision.reason, str)
        assert len(decision.reason) > 0, "reason must not be empty"

    def test_reason_references_complexity(self, monkeypatch):
        from bridge import routing_brain
        from bridge.intent_classifier import IntentClassification

        monkeypatch.setattr(
            routing_brain,
            "classify",
            lambda text: IntentClassification(
                intent=Intent.FIX, confidence=0.9, complexity=5
            ),
        )
        decision = _brain().decide("fix everything")
        assert "5" in decision.reason or "worktree" in decision.reason.lower()


# ---------------------------------------------------------------------------
# 8. EnvironmentSelector hint is honoured in moderate range
# ---------------------------------------------------------------------------

class TestSelectorHintInModerateRange:
    def test_selector_suggest_called_for_moderate(self, monkeypatch):
        from bridge import routing_brain
        from bridge.intent_classifier import IntentClassification

        monkeypatch.setattr(
            routing_brain,
            "classify",
            lambda text: IntentClassification(
                intent=Intent.BUILD, confidence=0.8, complexity=3
            ),
        )

        called_with: list[dict] = []

        class _Selector:
            def suggest(self, *, intent: str, complexity: int) -> str:
                called_with.append({"intent": intent, "complexity": complexity})
                return "tmux"

        decision = _brain(selector=_Selector()).decide("build this module")
        assert decision.environment == "tmux"
        assert called_with == [{"intent": "build", "complexity": 3}]

    def test_invalid_selector_hint_ignored(self, monkeypatch):
        """Selector returning an unrecognised value → fall back to default."""
        from bridge import routing_brain
        from bridge.intent_classifier import IntentClassification

        # Use OPTIMIZE — not in department table, so selector path is exercised.
        monkeypatch.setattr(
            routing_brain,
            "classify",
            lambda text: IntentClassification(
                intent=Intent.OPTIMIZE, confidence=0.7, complexity=3
            ),
        )

        class _BadSelector:
            def suggest(self, *, intent: str, complexity: int) -> str:
                return "moon"  # not a valid environment

        decision = _brain(selector=_BadSelector()).decide("optimize logs")
        assert decision.environment == "subagent"

    def test_selector_without_suggest_method_ok(self, monkeypatch):
        """Selector without suggest() attribute → no crash, default used."""
        from bridge import routing_brain
        from bridge.intent_classifier import IntentClassification

        # Use OPTIMIZE — not in department table, so selector path is exercised.
        monkeypatch.setattr(
            routing_brain,
            "classify",
            lambda text: IntentClassification(
                intent=Intent.OPTIMIZE, confidence=0.7, complexity=3
            ),
        )

        class _NoSuggest:
            pass  # no suggest method

        decision = _brain(selector=_NoSuggest()).decide("optimize logs")
        assert decision.environment == "subagent"


# ---------------------------------------------------------------------------
# 9. Department routing via (Intent, Modality) table
# ---------------------------------------------------------------------------

class TestDepartmentRouting:
    """Messages matching the (Intent, Modality) table route to DEPARTMENT."""

    def test_analyze_solo_routes_strategy(self, monkeypatch):
        """'analyze our competitive position' → DEPARTMENT + strategy."""
        from bridge import routing_brain
        from bridge.intent_classifier import IntentClassification

        monkeypatch.setattr(
            routing_brain,
            "classify",
            lambda text: IntentClassification(
                intent=Intent.ANALYZE, confidence=0.8, complexity=3
            ),
        )
        decision = _brain().decide("analyze our competitive position")
        assert decision.environment == "department"
        assert decision.department_hint == "strategy"

    def test_analyze_orchestrated_routes_board(self, monkeypatch):
        """'review our Q1 priorities as a team' → DEPARTMENT + board.

        The word 'team' triggers ORCHESTRATED modality, and
        Intent.ANALYZE + Modality.ORCHESTRATED maps to 'board'.
        """
        from bridge import routing_brain
        from bridge.intent_classifier import IntentClassification

        monkeypatch.setattr(
            routing_brain,
            "classify",
            lambda text: IntentClassification(
                intent=Intent.ANALYZE, confidence=0.8, complexity=3
            ),
        )
        # "team" triggers ORCHESTRATED in ModalityDetector
        decision = _brain().decide("review our Q1 priorities as a team")
        assert decision.environment == "department"
        assert decision.department_hint == "board"

    def test_test_parallel_routes_qa(self, monkeypatch):
        """'run the test suite in parallel' → DEPARTMENT + qa."""
        from bridge import routing_brain
        from bridge.intent_classifier import IntentClassification

        monkeypatch.setattr(
            routing_brain,
            "classify",
            lambda text: IntentClassification(
                intent=Intent.TEST, confidence=0.85, complexity=2
            ),
        )
        decision = _brain().decide("run the test suite in parallel")
        assert decision.environment == "department"
        assert decision.department_hint == "qa"

    def test_deploy_solo_routes_ops(self, monkeypatch):
        """'deploy to production' → DEPARTMENT + ops."""
        from bridge import routing_brain
        from bridge.intent_classifier import IntentClassification

        monkeypatch.setattr(
            routing_brain,
            "classify",
            lambda text: IntentClassification(
                intent=Intent.DEPLOY, confidence=0.9, complexity=2
            ),
        )
        decision = _brain().decide("deploy to production")
        assert decision.environment == "department"
        assert decision.department_hint == "ops"

    def test_document_solo_routes_design(self, monkeypatch):
        """'document the API' → DEPARTMENT + design."""
        from bridge import routing_brain
        from bridge.intent_classifier import IntentClassification

        monkeypatch.setattr(
            routing_brain,
            "classify",
            lambda text: IntentClassification(
                intent=Intent.DOCUMENT, confidence=0.85, complexity=2
            ),
        )
        decision = _brain().decide("document the API")
        assert decision.environment == "department"
        assert decision.department_hint == "design"


# ---------------------------------------------------------------------------
# 10. Backward compatibility — non-department intents unchanged
# ---------------------------------------------------------------------------

class TestDepartmentBackwardCompat:
    """Existing routing for FIX, BUILD, etc. must not change."""

    def test_fix_routes_subagent(self):
        """'fix the auth bug' → subagent (unchanged)."""
        decision = _brain().decide("fix the auth bug")
        assert decision.environment == "subagent"
        assert decision.department_hint is None

    def test_build_routes_unchanged(self, monkeypatch):
        """'build a new feature' at moderate complexity → subagent or worktree."""
        from bridge import routing_brain
        from bridge.intent_classifier import IntentClassification

        monkeypatch.setattr(
            routing_brain,
            "classify",
            lambda text: IntentClassification(
                intent=Intent.BUILD, confidence=0.85, complexity=3
            ),
        )
        decision = _brain().decide("build a new feature")
        # BUILD is not in the department table — should NOT route to department
        assert decision.environment != "department"
        assert decision.department_hint is None

    def test_department_hint_none_for_non_department(self):
        """Non-department decisions must have department_hint=None."""
        decision = _brain().decide("fix a typo")
        assert decision.department_hint is None

    def test_extreme_complexity_overrides_department(self, monkeypatch):
        """Complexity 5 forces worktree even if intent matches department table."""
        from bridge import routing_brain
        from bridge.intent_classifier import IntentClassification

        monkeypatch.setattr(
            routing_brain,
            "classify",
            lambda text: IntentClassification(
                intent=Intent.ANALYZE, confidence=0.9, complexity=5
            ),
        )
        decision = _brain().decide("analyze the entire system architecture")
        assert decision.environment == "worktree"
        assert decision.department_hint is None
