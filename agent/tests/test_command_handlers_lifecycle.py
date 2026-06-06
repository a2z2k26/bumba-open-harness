"""Tests for ``bridge.command_handlers.lifecycle`` helpers.

Sprint S1.1 (#2277) — route the ``/health`` Discord command through the
canonical API health configuration instead of the legacy hardcoded
``127.0.0.1:8199``. Covers:

  * ``_healthz_url`` derives host/port from config defaults
  * ``_healthz_url`` honours explicit config overrides
  * ``_healthz_url`` falls back when config is None / missing fields
  * Regression guard: the legacy ``127.0.0.1:8199`` is not embedded in
    the lifecycle command-handler source.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from bridge.command_handlers.lifecycle import _healthz_url


def test_healthz_url_uses_configured_api_port() -> None:
    """A config carrying canonical 8200 produces the canonical URL."""
    config = SimpleNamespace(api_host="127.0.0.1", api_port=8200)
    assert _healthz_url(config) == "http://127.0.0.1:8200/healthz"


def test_healthz_url_respects_overrides() -> None:
    """Non-default host/port should be honoured verbatim."""
    config = SimpleNamespace(api_host="0.0.0.0", api_port=9000)
    assert _healthz_url(config) == "http://0.0.0.0:9000/healthz"


def test_healthz_url_falls_back_when_config_none() -> None:
    """Missing config defaults to the canonical 127.0.0.1:8200 endpoint."""
    assert _healthz_url(None) == "http://127.0.0.1:8200/healthz"


def test_healthz_url_falls_back_on_missing_attrs() -> None:
    """A config object without api_host/api_port should still resolve."""
    config = SimpleNamespace()
    assert _healthz_url(config) == "http://127.0.0.1:8200/healthz"


def test_healthz_url_coerces_none_fields_to_defaults() -> None:
    """Falsy attribute values (None / 0) should fall back to canonical."""
    config = SimpleNamespace(api_host=None, api_port=None)
    assert _healthz_url(config) == "http://127.0.0.1:8200/healthz"


def test_lifecycle_health_does_not_hardcode_legacy_8199() -> None:
    """Regression guard: the legacy port must not reappear in the source."""
    source_path = (
        Path(__file__).resolve().parent.parent
        / "bridge"
        / "command_handlers"
        / "lifecycle.py"
    )
    source = source_path.read_text(encoding="utf-8")
    assert "127.0.0.1:8199" not in source
    assert ":8199/healthz" not in source
