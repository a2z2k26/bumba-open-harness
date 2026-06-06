"""P0.04 — canonical default-model constants module.

Foundation sprint surfaced by Phase 2: every magnostic-p2 sprint imports
``bridge.model_defaults`` for its default-model constants, but the plan never
created the module (it mis-attributed the module to P0.01, whose real scope was
stream-parsing delegation). This module centralises the model/backend default
literals so the de-hardcode sprints have a single source of truth to redirect to.

All values are the CURRENT hardcoded literals — this is pure centralisation,
no behaviour change. Each value is asserted here so a future model bump is a
one-line edit with a test that documents intent.
"""

from bridge import model_defaults


def test_backend_name_default():
    assert model_defaults.DEFAULT_BACKEND_NAME == "claude"


def test_openrouter_model_default():
    assert model_defaults.DEFAULT_OPENROUTER_MODEL == "anthropic/claude-3.5-sonnet"


def test_paid_model_default():
    assert model_defaults.DEFAULT_PAID_MODEL == "claude-sonnet-4-6"


def test_pricing_model_default():
    assert model_defaults.DEFAULT_PRICING_MODEL == "claude-opus-4-6"


def test_voice_model_default():
    assert model_defaults.DEFAULT_VOICE_MODEL == "claude-sonnet-4-5"


def test_careful_model_default():
    assert model_defaults.DEFAULT_CAREFUL_MODEL == "claude-opus-4-5-20251001"


def test_registration_model_default():
    assert model_defaults.DEFAULT_REGISTRATION_MODEL == "claude-opus-4-6"


def test_tier_defaults():
    assert model_defaults.DEFAULT_TIER_SIMPLE == "claude-haiku"
    assert model_defaults.DEFAULT_TIER_MEDIUM == "claude-sonnet"
    assert model_defaults.DEFAULT_TIER_COMPLEX == "claude-opus"


def test_all_constants_are_nonempty_strings():
    """Every public constant is a non-empty str — guards against a future
    edit accidentally setting one to None/empty."""
    names = [n for n in dir(model_defaults) if n.startswith("DEFAULT_")]
    assert names, "module must export DEFAULT_* constants"
    for name in names:
        value = getattr(model_defaults, name)
        assert isinstance(value, str) and value, f"{name} must be a non-empty str"
