"""HttpBackend — OpenAI-compatible HTTP implementation of ``BackendProtocol``.

P3.02 (model-agnostic runtime). The subprocess-CLI surface
(``resolve_binary`` / ``build_command``) of ``BackendProtocol`` does not apply
to an HTTP backend, so those methods raise ``NotImplementedError`` and the
real work lives in ``request`` (issue the POST) + ``parse_event`` (map the
OpenAI-compatible chat response to a ``StreamEvent``).

The request/parse shape is lifted from
``cross_model/openrouter_client.py`` (POST to ``…/chat/completions`` with
``{"model","messages","max_tokens"}``, ``Authorization: Bearer``, response at
``choices[0].message.content``) but built on ``httpx`` per the phase brief so
tests can mock the client. ``parse_cost`` is a not_applicable placeholder until
P3.03 wires usage-based cost.
"""
from __future__ import annotations

import json
import logging
import os
from decimal import Decimal
from typing import TYPE_CHECKING, Any

import httpx

from ._protocol import StreamEvent

if TYPE_CHECKING:
    from ..cost_tracker import CostMeasurement

logger = logging.getLogger(__name__)


class HttpBackend:
    """OpenAI-compatible chat-completions backend over HTTP.

    Constructed with an endpoint base URL, API key, model id, and timeout.
    Satisfies ``BackendProtocol`` structurally; ``transport`` returns
    ``"http"`` so callers branch onto the HTTP surface.
    """

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        timeout: int = 30,
        price_per_1m: tuple[float, float] | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._model = model
        self._timeout = timeout
        # (input, output) USD per 1M tokens. None → cost cannot be measured
        # (operator has not configured pricing for this model) → parse_cost
        # returns source="unknown" rather than a misleading measured zero.
        self._price_per_1m = price_per_1m

    @property
    def transport(self) -> str:
        """OpenAI-compatible HTTP backend."""
        return "http"

    @property
    def capabilities(self) -> dict[str, Any]:
        """Static capability map for this HTTP model.

        Capabilities depend on the model/endpoint. The HTTP base issues a
        single non-streaming completion, so ``streaming`` is False until a
        streaming subclass lands; ``model`` and ``transport`` let the
        registry/router branch on what this backend can do.
        """
        return {"model": self._model, "transport": "http", "streaming": False}

    def request(self, *, message: str, system_prompt: str | None = None) -> dict[str, Any]:
        """Issue one chat-completions POST and return the decoded JSON dict.

        Mirrors the OpenAI/OpenRouter chat shape used by
        ``OpenRouterClient.complete`` — system message first (when present),
        then the user message. Raises ``httpx.HTTPStatusError`` on non-2xx
        for the caller to translate.
        """
        if os.environ.get("BUMBA_ALLOW_LIVE") != "1":
            raise RuntimeError(
                "HTTP backend live calls require BUMBA_ALLOW_LIVE=1. "
                "Set it only for an operator-approved live-model validation."
            )

        messages: list[dict[str, str]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": message})

        payload = {"model": self._model, "messages": messages, "max_tokens": 4096}
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        with httpx.Client(timeout=self._timeout) as client:
            resp = client.post(
                f"{self._base_url}/chat/completions",
                headers=headers,
                json=payload,
            )
            resp.raise_for_status()
            return resp.json()

    def resolve_binary(self) -> str | list[str]:
        """No binary — HTTP backends do not spawn a subprocess."""
        raise NotImplementedError("HttpBackend has no subprocess binary (transport='http')")

    def build_command(self, **_kwargs: Any) -> list[str]:
        """No argv — HTTP backends issue requests via ``request``."""
        raise NotImplementedError("HttpBackend has no argv (transport='http')")

    def parse_event(self, line: str) -> StreamEvent | None:
        """Map one OpenAI-compatible chat-response JSON dict to a StreamEvent.

        The HTTP path returns a single completion (no NDJSON streaming yet),
        so the whole response decodes to one ``result`` event carrying the
        assistant text. Blank lines and malformed JSON return ``None``.
        """
        line = line.strip()
        if not line:
            return None
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            logger.warning("Invalid JSON from HTTP backend response: %s", line[:200])
            return None

        event = StreamEvent()
        event.type = "result"
        try:
            event.text = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            event.is_error = True
            return event
        event.session_id = data.get("id", "")
        return event

    def parse_cost(self, event: dict[str, Any]) -> "CostMeasurement":
        """Estimate cost from the OpenAI-compatible ``usage`` block.

        OpenAI-compatible responses carry token counts in
        ``usage.prompt_tokens`` / ``usage.completion_tokens``. With operator
        pricing (``price_per_1m``) configured, cost is
        ``input_tokens/1e6 * input_price + output_tokens/1e6 * output_price``
        → ``source="estimated"``. Missing usage OR missing pricing returns
        ``source="unknown"`` with ``amount_usd=None`` — never a measured zero
        (HI-2 contract, mirrors ``ClaudeBackend.parse_cost``).
        """
        from ..cost_tracker import CostMeasurement

        usage_id = event.get("id") or None
        usage = event.get("usage")
        if not isinstance(usage, dict) or self._price_per_1m is None:
            return CostMeasurement(
                amount_usd=None,
                source="unknown",
                backend="http",
                raw_usage_id=usage_id,
            )

        prompt_tokens = usage.get("prompt_tokens", 0)
        completion_tokens = usage.get("completion_tokens", 0)
        if not isinstance(prompt_tokens, int) or not isinstance(completion_tokens, int):
            return CostMeasurement(
                amount_usd=None,
                source="unknown",
                backend="http",
                raw_usage_id=usage_id,
            )

        in_price, out_price = self._price_per_1m
        amount = (
            Decimal(prompt_tokens) / Decimal(1_000_000) * Decimal(str(in_price))
            + Decimal(completion_tokens) / Decimal(1_000_000) * Decimal(str(out_price))
        )
        return CostMeasurement(
            amount_usd=amount,
            source="estimated",
            backend="http",
            raw_usage_id=usage_id,
        )

    def auth_env(self) -> dict[str, str]:
        """HTTP auth rides the Authorization header, not subprocess env."""
        return {}

    def shutdown(self) -> None:
        """No persistent connection held; httpx.Client is per-request."""
        return None

    # -- Capability honesty (P1.01 surface) ---------------------------------
    # The base OpenAI-compatible chat backend issues a single text completion;
    # it does not wire the Claude-CLI tool surfaces. Report all four False so
    # the capability guard (P1.02/P1.03) keeps tool-requiring work off it.
    # Subclasses (e.g. a function-calling OpenRouter model) may override.
    def supports_tool_calling(self) -> bool:
        """False — the base HTTP backend runs no tools."""
        return False

    def supports_system_prompt(self) -> bool:
        """False — system prompt rides the messages array, not a CLI flag;
        the dispatch contract is the CLI ``system_prompt_file`` surface."""
        return False

    def supports_mcp_config(self) -> bool:
        """False — no MCP surface over the chat-completions endpoint."""
        return False

    def supports_tool_preauth(self) -> bool:
        """False — no allow-list pre-authorization surface."""
        return False
