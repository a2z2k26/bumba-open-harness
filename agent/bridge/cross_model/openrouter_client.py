"""Shared OpenRouter HTTP client.

Lifted verbatim from `bridge/fallback.py:32-100` so that both the legacy
`FallbackChain` (in `bridge.fallback`) and the upcoming `OpenRouterAdapter`
(Sprint 04.03) can share a single HTTP+auth surface.

Behavior is intentionally identical to the original `FallbackChain.invoke()`
implementation — no new options, no new error paths, no new defaults. This
module is a structural extraction; behavior changes belong in follow-up sprints.

Uses `urllib.request` (no extra dependencies) to match the existing fallback
style. Sync interface mirrors the synchronous call site in `fallback.py`.
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from dataclasses import dataclass

from bridge import model_defaults  # P0.04 canonical default-model constants

log = logging.getLogger(__name__)

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"


@dataclass(frozen=True)
class CompletionResult:
    """Parsed result of a successful OpenRouter completion call.

    Mirrors the fields `FallbackChain.invoke()` extracts from the response:
    `content` (the assistant message text) and `model` (the actual model the
    server selected, which may differ from the requested one). `raw` carries
    the full decoded JSON for callers that need usage/cost details.
    """

    content: str
    model: str
    raw: dict


class OpenRouterClient:
    """Sync OpenRouter chat-completions client.

    The constructor takes the same configuration that `FallbackChain` reads
    today: API key, default model, request timeout. `complete()` issues the
    POST and returns a `CompletionResult` on 200, or raises the underlying
    exception (`urllib.error.URLError`, `json.JSONDecodeError`, `KeyError`,
    `IndexError`) for the caller to translate into its preferred envelope.

    No retry policy is added in this extraction — the original `fallback.py`
    code does a single attempt, and Sprint 04.03a is a behavior-preserving
    refactor. Retries belong in 04.03 or a follow-up.
    """

    def __init__(
        self,
        api_key: str,
        model: str = model_defaults.DEFAULT_OPENROUTER_MODEL,
        timeout: int = 30,
        url: str = OPENROUTER_URL,
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._timeout = timeout
        self._url = url

    @property
    def is_configured(self) -> bool:
        """Whether the client has a valid API key."""
        return bool(self._api_key)

    @property
    def default_model(self) -> str:
        """Default model used when `complete()` is called without `model=`."""
        return self._model

    def complete(
        self,
        messages: list[dict],
        *,
        model: str | None = None,
        max_tokens: int = 1000,
    ) -> CompletionResult:
        """Issue a chat-completions POST and return the parsed result.

        `messages` follows the OpenAI/OpenRouter chat shape:
        `[{"role": "system"|"user"|"assistant", "content": "..."}]`.

        Raises whatever the underlying call raises — callers translate.
        """
        chosen_model = model or self._model
        payload = {
            "model": chosen_model,
            "messages": messages,
            "max_tokens": max_tokens,
        }

        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            self._url,
            data=data,
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://bumba-agent.local",
                "X-Title": "Bumba Agent Fallback",
            },
            method="POST",
        )

        with urllib.request.urlopen(req, timeout=self._timeout) as resp:
            result = json.loads(resp.read().decode("utf-8"))

        content = result["choices"][0]["message"]["content"]
        model_used = result.get("model", chosen_model)

        return CompletionResult(content=content, model=model_used, raw=result)
