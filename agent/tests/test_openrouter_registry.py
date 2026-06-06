"""P5.02 — OpenRouter registration + config wiring. No network, no live calls.

Test-helper correction: BridgeConfig is @dataclass(frozen=True), so the issue's
`setattr(cfg, ...)` would raise FrozenInstanceError. Overrides use
dataclasses.replace (the established pattern, config.py:1921/1979).
"""
from __future__ import annotations

from dataclasses import replace

import pytest

from bridge.backends.factory import build_backend_instances
from bridge.backends.openrouter import OpenRouterBackend
from bridge.backends.registry import BackendRegistry
from bridge.config import load_config


def _config(**overrides):
    cfg = load_config(skip_secrets=True, skip_validation=True)
    return replace(cfg, **overrides) if overrides else cfg


def test_default_model_field_exists():
    cfg = load_config(skip_secrets=True, skip_validation=True)
    assert hasattr(cfg, "openrouter_default_model")


def test_factory_includes_openrouter_instance():
    cfg = _config(openrouter_api_key="sk-or-test")
    instances = build_backend_instances(cfg)
    assert isinstance(instances["openrouter"], OpenRouterBackend)
    assert "claude" in instances
    assert "codex" in instances


def test_registry_resolves_main_to_openrouter():
    cfg = _config(openrouter_api_key="sk-or-test", backends_main="openrouter")
    registry = BackendRegistry(cfg, build_backend_instances(cfg))
    backend = registry.resolve("main")
    assert isinstance(backend, OpenRouterBackend)


def test_registry_resolves_specialist_override_to_openrouter():
    cfg = _config(
        openrouter_api_key="sk-or-test",
        backends_specialists_overrides={"code-reviewer": "openrouter"},
    )
    registry = BackendRegistry(cfg, build_backend_instances(cfg))
    backend = registry.resolve("specialist", specialist="code-reviewer")
    assert isinstance(backend, OpenRouterBackend)


def test_unknown_backend_name_raises_keyerror():
    cfg = _config(backends_main="nonsuch")
    registry = BackendRegistry(cfg, build_backend_instances(cfg))
    with pytest.raises(KeyError, match="nonsuch"):
        registry.resolve("main")


def test_openrouter_backend_uses_default_model_field():
    """The new openrouter_default_model field flows into the backend's model."""
    cfg = _config(
        openrouter_api_key="sk-or-test",
        openrouter_default_model="z-ai/glm-4.6",
    )
    instances = build_backend_instances(cfg)
    backend = instances["openrouter"]
    assert isinstance(backend, OpenRouterBackend)
    # The backend's resolved model reflects the configured default.
    assert backend._model == "z-ai/glm-4.6"
