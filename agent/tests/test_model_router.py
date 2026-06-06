"""Tests for bridge.model_router."""

from __future__ import annotations

import time

from bridge.model_router import ModelRouter, RoutingDecision, classify_complexity, classify


class TestClassifyComplexity:
    """Message complexity classification."""

    def test_simple_greeting(self):
        assert classify_complexity("hi") == "simple"
        assert classify_complexity("hello") == "simple"
        assert classify_complexity("thanks") == "simple"

    def test_simple_short_message(self):
        assert classify_complexity("ok") == "simple"
        assert classify_complexity("yes") == "simple"

    def test_complex_code_request(self):
        assert classify_complexity("refactor the authentication module to use JWT") == "complex"

    def test_complex_analysis(self):
        assert classify_complexity("analyze and debug the database connection issue") == "complex"

    def test_medium_single_pattern(self):
        # "explain" + "function" match 2 patterns → complex
        assert classify_complexity("explain what this function does") == "complex"

    def test_complex_long_message(self):
        long_msg = "Please help me with " + "a" * 600
        assert classify_complexity(long_msg) == "complex"

    def test_medium_moderate_length(self):
        mod_msg = "I need some help with understanding " + "a" * 100
        assert classify_complexity(mod_msg) == "medium"


class TestModelRouter:
    """Budget-aware model routing."""

    def test_route_simple(self):
        router = ModelRouter(daily_budget=0.0)
        decision = router.route("hi there")
        assert decision.tier == "simple"
        assert decision.downgraded is False

    def test_route_complex(self):
        router = ModelRouter(daily_budget=0.0)
        decision = router.route("refactor and analyze and debug the authentication module")
        assert decision.tier == "complex"

    def test_route_unlimited_budget(self):
        router = ModelRouter(daily_budget=0.0)
        decision = router.route("analyze this code")
        assert decision.budget_remaining == 0.0  # 0 means unlimited

    def test_route_within_budget(self):
        router = ModelRouter(daily_budget=1.0)
        decision = router.route("analyze this code")
        assert decision.budget_remaining > 0

    def test_route_downgrade_over_budget(self):
        router = ModelRouter(daily_budget=0.01)
        # Log enough cost to exhaust budget
        router.log_cost(0.009)
        decision = router.route("refactor and redesign the authentication module")
        # Should downgrade from complex to something cheaper
        assert decision.downgraded is True
        assert decision.tier in ("medium", "simple")

    def test_log_cost_and_spend(self):
        router = ModelRouter(daily_budget=1.0)
        router.log_cost(0.05)
        router.log_cost(0.10)
        assert abs(router.get_daily_spend() - 0.15) < 1e-6

    def test_rolling_cost_prunes_old(self):
        router = ModelRouter(daily_budget=1.0)
        # Add an old entry (simulate 25 hours ago)
        router._cost_log.append((time.time() - 90000, 0.50))
        router.log_cost(0.10)
        # Old entry should be pruned
        assert abs(router.get_daily_spend() - 0.10) < 1e-6

    def test_budget_status_unlimited(self):
        router = ModelRouter(daily_budget=0.0)
        status = router.get_budget_status()
        assert status["is_unlimited"] is True

    def test_budget_status_with_budget(self):
        router = ModelRouter(daily_budget=5.0)
        router.log_cost(1.0)
        status = router.get_budget_status()
        assert status["is_unlimited"] is False
        assert abs(status["remaining"] - 4.0) < 1e-6

    def test_routing_decision_dataclass(self):
        d = RoutingDecision(
            tier="medium",
            model="claude-sonnet",
            reason="test",
        )
        assert d.downgraded is False
        assert d.budget_remaining == 0.0


# ---------------------------------------------------------------------------
# Sprint 06.12 — Trust gate for model routing
# ---------------------------------------------------------------------------

from unittest.mock import MagicMock
from bridge.model_router import DEFAULT_MODEL


class TestTrustGate:
    """classify() respects trust.check_access('routing') when trust is provided."""

    def _make_trust(self, allowed: bool) -> MagicMock:
        trust = MagicMock()
        access = MagicMock()
        access.allowed = allowed
        access.tier = "disabled" if not allowed else "auto"
        trust.check_access.return_value = access
        return trust

    def test_trust_denied_returns_default_model(self):
        """When trust.check_access('routing') returns allowed=False, classify returns DEFAULT_MODEL."""
        trust = self._make_trust(allowed=False)
        result = classify("refactor the entire authentication system", trust=trust)
        trust.check_access.assert_called_once_with("routing")
        assert result == DEFAULT_MODEL

    def test_trust_allowed_proceeds_to_classify(self):
        """When trust.check_access('routing') returns allowed=True, classify proceeds normally."""
        trust = self._make_trust(allowed=True)
        # This complex message should route to opus without trust gate interference
        result = classify("architect a new microservices system from scratch", trust=trust)
        trust.check_access.assert_called_once_with("routing")
        assert result == "opus"

    def test_no_trust_proceeds_normally(self):
        """Without trust argument, classify works as before (no gate)."""
        result = classify("hi")
        assert result == "haiku"

    def test_trust_error_does_not_crash(self):
        """If trust.check_access raises, classify falls through to normal routing."""
        trust = MagicMock()
        trust.check_access.side_effect = RuntimeError("trust db unavailable")
        # Should not raise; falls through to normal classification
        result = classify("hi", trust=trust)
        assert isinstance(result, str)

    def test_default_model_is_haiku(self):
        """DEFAULT_MODEL is 'haiku' — the safest fallback."""
        assert DEFAULT_MODEL == "haiku"
