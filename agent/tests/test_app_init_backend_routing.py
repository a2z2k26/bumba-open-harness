"""Startup routing guards for model-agnostic backend modes."""

from __future__ import annotations

from types import SimpleNamespace

from bridge.app_init import _warm_claude_enabled_for_config


def test_warm_claude_enabled_for_legacy_boot() -> None:
    """Legacy mode keeps the persistent Claude process enabled."""
    config = SimpleNamespace(backends_enabled=False, backends_main="openrouter")

    assert _warm_claude_enabled_for_config(config) is True


def test_warm_claude_enabled_when_main_backend_is_claude() -> None:
    """Model-agnostic mode can still opt the main route into Claude."""
    config = SimpleNamespace(backends_enabled=True, backends_main="claude")

    assert _warm_claude_enabled_for_config(config) is True


def test_warm_claude_disabled_when_main_backend_is_http() -> None:
    """OpenRouter main routing must not construct or spawn warm Claude."""
    config = SimpleNamespace(backends_enabled=True, backends_main="openrouter")

    assert _warm_claude_enabled_for_config(config) is False
