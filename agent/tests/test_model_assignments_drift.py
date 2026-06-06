"""Drift test: DOMAIN_ASSIGNMENTS defaults + ModelRouter fallback must source
the canonical default model from bridge.model_defaults (P0.01)."""
from bridge.model_assignments import (
    DOMAIN_ASSIGNMENTS,
    Domain,
    ModelRouter,
    ModelTier,
    MODELS,
)
from bridge import model_defaults


def test_general_domain_uses_canonical_default():
    assert DOMAIN_ASSIGNMENTS[Domain.GENERAL] == model_defaults.DEFAULT_PAID_MODEL


def test_router_fallback_uses_canonical_default(monkeypatch):
    # An unmapped domain falls back to the canonical default, not a literal.
    # Repoint the canonical constant to a real catalogue entry and confirm the
    # get_model fallback tracks it live (proving it reads the constant, not a
    # baked-in literal). claude-opus-4-6 is a valid PAID catalogue entry.
    router = ModelRouter()
    monkeypatch.setattr(model_defaults, "DEFAULT_PAID_MODEL", "claude-opus-4-6")
    # Simulate a domain with no assignment by clearing it.
    monkeypatch.delitem(DOMAIN_ASSIGNMENTS, Domain.GENERAL, raising=False)
    spec = router.get_model(Domain.GENERAL, tier_preference=ModelTier.PAID)
    assert spec.model_id == model_defaults.DEFAULT_PAID_MODEL


def test_canonical_default_present_in_catalogue():
    # The canonical default must be a real catalogue entry or routing breaks.
    assert model_defaults.DEFAULT_PAID_MODEL in MODELS


def test_current_default_value_preserved():
    assert model_defaults.DEFAULT_PAID_MODEL == "claude-sonnet-4-6"
