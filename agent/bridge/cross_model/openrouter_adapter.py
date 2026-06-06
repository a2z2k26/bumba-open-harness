"""OpenRouter-backed AgentAdapter for the Board of Directors.

Sprint 04.03 — concept-only port of the llm-council cross-vendor pattern
(NO LICENSE on llm-council; no source code copied). Adapter satisfies
`AgentAdapter` Protocol from `bridge.cross_model.agent_adapter` and composes
the shared `OpenRouterClient` (Sprint 04.03a) for HTTP / auth / parsing.

The adapter contains NO new HTTP code, NO new retry logic, NO new auth
handling — every byte of network behavior comes from `OpenRouterClient`.
The only translation here is:
  prompt + context (Protocol input)
    -> OpenAI/OpenRouter chat-message list (client input)
  CompletionResult (client output)
    -> AdapterResult (Protocol output)

The class is registered as available in `bridge.cross_model.__init__` but is
not wired into `agent_router.py`; that wiring is Sprint 04.05's job (extending
`board.yaml` schema with an adapter field). Use of the adapter from the Board
is gated by `BridgeConfig.board_cross_vendor_enabled`, default OFF — Plan
04.07 flips after a shadow period.
"""
from __future__ import annotations

import asyncio
import logging

from bridge import model_defaults  # P0.04 canonical default-model constants

from .agent_adapter import AdapterResult
from .openrouter_client import CompletionResult, OpenRouterClient

logger = logging.getLogger(__name__)


class OpenRouterAdapter:
    """`AgentAdapter` implementation backed by OpenRouter.

    Construction mirrors `OpenRouterClient` — same `api_key`, `model`, and
    `timeout` knobs — so a Board YAML entry that names an adapter can pass
    its config straight through without translation.

    `invoke()` is async to satisfy the Protocol; internally it offloads the
    synchronous `OpenRouterClient.complete()` call to a worker thread via
    `asyncio.to_thread` so the event loop never blocks on the HTTP round
    trip.

    Errors raised by the client (network, parse, missing-keys) are caught
    and translated into a graceful `AdapterResult(success=False, ...)`
    envelope. The Board never sees an exception — a single failing member
    degrades cleanly while the rest of the council continues.
    """

    def __init__(
        self,
        api_key: str,
        model: str = model_defaults.DEFAULT_OPENROUTER_MODEL,
        timeout: int = 30,
    ) -> None:
        self._client = OpenRouterClient(
            api_key=api_key,
            model=model,
            timeout=timeout,
        )
        self._model = model

    @property
    def is_configured(self) -> bool:
        """Whether the adapter has a valid API key (delegated to client)."""
        return self._client.is_configured

    @property
    def model(self) -> str:
        """The default OpenRouter model identifier this adapter targets."""
        return self._model

    async def invoke(
        self,
        prompt: str,
        context: dict | None = None,
    ) -> AdapterResult:
        """Invoke the OpenRouter-backed model with the given prompt.

        `context` may carry a "system" key whose value becomes the system
        message; any other keys are ignored at this layer (cost-tracker
        feature tagging is Plan 04.04's job, see spec line 56).

        Returns `AdapterResult` — never raises. Network / parse failures
        produce `success=False` with `error` populated; the Board treats
        the call as a degraded member and continues.
        """
        messages: list[dict] = []
        if context and isinstance(context.get("system"), str):
            messages.append({"role": "system", "content": context["system"]})
        messages.append({"role": "user", "content": prompt})

        try:
            result: CompletionResult = await asyncio.to_thread(
                self._client.complete,
                messages,
            )
        except Exception as exc:  # noqa: BLE001 — Protocol promises envelope, not raise
            logger.warning(
                "OpenRouterAdapter.invoke failed (model=%s): %s",
                self._model,
                exc,
            )
            return AdapterResult(
                success=False,
                data={},
                model_used=self._model,
                tokens_used=0,
                error=f"{type(exc).__name__}: {exc}",
            )

        # CompletionResult.raw mirrors the full OpenRouter payload; usage
        # is optional per OpenRouter's docs, so default to 0 if absent.
        usage = result.raw.get("usage") if isinstance(result.raw, dict) else None
        tokens_used = 0
        if isinstance(usage, dict):
            total = usage.get("total_tokens")
            if isinstance(total, int):
                tokens_used = total

        logger.info(
            "OpenRouterAdapter.invoke ok (model=%s, tokens=%d)",
            result.model,
            tokens_used,
        )
        return AdapterResult(
            success=True,
            data={"response": result.content, "raw": result.raw},
            model_used=result.model,
            tokens_used=tokens_used,
        )
