"""Drift test: can_afford's default pricing model must source the canonical
DEFAULT_PRICING_MODEL (P0.01), and that model must exist in PRICES."""
import inspect
from bridge.token_cost import TokenCostManager, PricingModel
from bridge import model_defaults


def test_can_afford_default_matches_canonical():
    # Identity (`is`), not just equality: the default must be SOURCED from the
    # canonical constant, not a coincidental bare literal. A literal would pass
    # `==` today yet silently diverge if DEFAULT_PRICING_MODEL changes — exactly
    # the drift this guard exists to catch.
    sig = inspect.signature(TokenCostManager.can_afford)
    assert sig.parameters["model"].default is model_defaults.DEFAULT_PRICING_MODEL


def test_canonical_pricing_model_present_in_table():
    # If absent, PricingModel silently uses $0 pricing — must never happen.
    assert model_defaults.DEFAULT_PRICING_MODEL in PricingModel.PRICES


def test_current_pricing_default_preserved():
    assert model_defaults.DEFAULT_PRICING_MODEL == "claude-opus-4-6"


def test_can_afford_uses_default_without_explicit_model():
    mgr = TokenCostManager(daily_budget=1000.0)
    # Should evaluate against the canonical default model's real prices.
    assert mgr.can_afford(1000) is True
