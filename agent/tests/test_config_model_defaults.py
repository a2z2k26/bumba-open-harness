"""Drift test: BridgeConfig model-ish defaults must reference the canonical
default-model constants from bridge.model_defaults (P0.01), not bare literals."""
from bridge import config as config_mod
from bridge.config import BridgeConfig
from bridge import model_defaults


def test_fallback_default_sources_from_canonical():
    cfg = BridgeConfig()
    assert cfg.fallback_openrouter_model == model_defaults.DEFAULT_OPENROUTER_MODEL


def test_backend_name_defaults_source_from_canonical():
    cfg = BridgeConfig()
    assert cfg.backends_main == model_defaults.DEFAULT_BACKEND_NAME
    assert cfg.backends_chiefs_default == model_defaults.DEFAULT_BACKEND_NAME
    assert cfg.backends_specialists_default == model_defaults.DEFAULT_BACKEND_NAME


def test_canonical_values_preserve_current_behavior():
    # Documented defaults must not silently change under the indirection.
    assert model_defaults.DEFAULT_OPENROUTER_MODEL == "anthropic/claude-3.5-sonnet"
    assert model_defaults.DEFAULT_BACKEND_NAME == "claude"


def test_toml_override_still_wins(tmp_path):
    toml = tmp_path / "bridge.toml"
    toml.write_text(
        '[fallback]\nopenrouter_model = "anthropic/claude-opus-4-7"\n'
        '[backends]\nmain = "codex"\n'
    )
    cfg = config_mod.load_config(toml, skip_secrets=True, skip_validation=True)
    assert cfg.fallback_openrouter_model == "anthropic/claude-opus-4-7"
    assert cfg.backends_main == "codex"
