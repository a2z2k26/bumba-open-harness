"""Fallback LLM chain: Claude → OpenRouter → graceful failure.

Uses urllib.request (no extra dependencies) to call OpenRouter API
when the primary Claude subprocess fails after all retries.

Sprint 04.03a — the OpenRouter HTTP+auth client now lives in
`bridge.cross_model.openrouter_client`. `FallbackChain` composes it; the
external API of this module is unchanged.
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request  # kept so monkeypatches against `bridge.fallback.urllib.request.urlopen` still resolve
from dataclasses import dataclass

from bridge import model_defaults  # P0.04 canonical default-model constants

from .cross_model.openrouter_client import OPENROUTER_URL, OpenRouterClient

log = logging.getLogger(__name__)

FALLBACK_INDICATOR = "[Fallback Mode] "

# Re-exported for any callers that imported the URL constant directly.
__all__ = ["FALLBACK_INDICATOR", "OPENROUTER_URL", "FallbackChain", "FallbackResult"]


@dataclass
class FallbackResult:
    """Result from a fallback LLM invocation."""

    response_text: str
    model_used: str
    is_fallback: bool = True
    error: str | None = None


class FallbackChain:
    """Fallback LLM chain using OpenRouter API."""

    def __init__(
        self,
        api_key: str,
        model: str = model_defaults.DEFAULT_OPENROUTER_MODEL,
        timeout: int = 30,
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._timeout = timeout
        self._client = OpenRouterClient(
            api_key=api_key,
            model=model,
            timeout=timeout,
        )

    @property
    def is_configured(self) -> bool:
        """Whether the fallback chain has a valid API key."""
        return bool(self._api_key)

    def invoke(self, message: str, context: str = "") -> FallbackResult:
        """Invoke the fallback LLM.

        Returns FallbackResult with the response or error details.
        """
        if not self._api_key:
            return FallbackResult(
                response_text="I'm currently experiencing issues and my backup system isn't configured. Please try again later.",
                model_used="none",
                error="No OpenRouter API key configured",
            )

        messages = []
        if context:
            messages.append({"role": "system", "content": context})
        messages.append({"role": "user", "content": message})

        try:
            result = self._client.complete(messages)
            log.info(
                "Fallback LLM responded (%s, %d chars)",
                result.model,
                len(result.content),
            )
            return FallbackResult(
                response_text=FALLBACK_INDICATOR + result.content,
                model_used=result.model,
            )

        except urllib.error.URLError as e:
            log.error("Fallback LLM network error: %s", e)
            return FallbackResult(
                response_text="I'm currently experiencing connection issues. Please try again in a moment.",
                model_used="none",
                error=f"Network error: {e}",
            )
        except (json.JSONDecodeError, KeyError, IndexError) as e:
            log.error("Fallback LLM response parse error: %s", e)
            return FallbackResult(
                response_text="I received an unexpected response from my backup system. Please try again.",
                model_used="none",
                error=f"Parse error: {e}",
            )
        except Exception as e:
            log.error("Fallback LLM unexpected error: %s", e)
            return FallbackResult(
                response_text="I'm experiencing technical difficulties. Please try again later.",
                model_used="none",
                error=f"Unexpected: {e}",
            )
