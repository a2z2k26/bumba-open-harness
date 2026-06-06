"""Drift test: all three OpenRouter constructors must default to the canonical
DEFAULT_OPENROUTER_MODEL (P0.04), not a private literal."""
import inspect
from pathlib import Path

from bridge import model_defaults
from bridge.cross_model import openrouter_adapter, openrouter_client
from bridge.cross_model.openrouter_adapter import OpenRouterAdapter
from bridge.cross_model.openrouter_client import OpenRouterClient
from bridge import fallback
from bridge.fallback import FallbackChain


def _default_model(fn) -> str:
    return inspect.signature(fn).parameters["model"].default


def _sources_constant_not_literal(module) -> bool:
    """The module must reference the canonical constant for its default and must
    not re-hardcode the bare literal as the constructor default."""
    src = Path(module.__file__).read_text()
    return (
        "model_defaults.DEFAULT_OPENROUTER_MODEL" in src
        and 'model: str = "anthropic/claude-3.5-sonnet"' not in src
    )


def test_client_default_matches_canonical():
    assert _default_model(OpenRouterClient.__init__) == model_defaults.DEFAULT_OPENROUTER_MODEL


def test_adapter_default_matches_canonical():
    assert _default_model(OpenRouterAdapter.__init__) == model_defaults.DEFAULT_OPENROUTER_MODEL


def test_fallback_default_matches_canonical():
    assert _default_model(FallbackChain.__init__) == model_defaults.DEFAULT_OPENROUTER_MODEL


def test_current_value_preserved():
    assert model_defaults.DEFAULT_OPENROUTER_MODEL == "anthropic/claude-3.5-sonnet"


def test_client_sources_constant_not_literal():
    assert _sources_constant_not_literal(openrouter_client)


def test_adapter_sources_constant_not_literal():
    assert _sources_constant_not_literal(openrouter_adapter)


def test_fallback_sources_constant_not_literal():
    assert _sources_constant_not_literal(fallback)


def test_fallback_threads_default_into_client():
    # Construct with no model arg; the wrapped client must carry the same model.
    chain = FallbackChain(api_key="")  # offline — no network, no model call
    assert chain._model == model_defaults.DEFAULT_OPENROUTER_MODEL
    assert chain._client.default_model == model_defaults.DEFAULT_OPENROUTER_MODEL
