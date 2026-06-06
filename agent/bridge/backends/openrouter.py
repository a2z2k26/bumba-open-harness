"""OpenRouterBackend — concrete HTTP backend for OpenRouter cheap-frontier models.

Phase 5 (model-agnostic runtime): the third concrete backend behind
``BackendProtocol``, after ``ClaudeBackend`` and ``CodexBackend``. It extends
the P3.02 ``HttpBackend`` rather than re-implementing the OpenAI-compatible HTTP
surface, inheriting ``transport='http'``, ``request()``, ``parse_event()``, the
capability methods, and the usage×price cost machinery. Only OpenRouter
specifics are overridden:

    - ``auth_env()`` injects ``OPENROUTER_API_KEY`` (the base returns ``{}``)
      so a subprocess-free dispatch picks up the key.
    - the model defaults from ``config.fallback_openrouter_model`` (the
      canonical default from ``model_defaults`` / P0.04).
    - ``parse_cost()`` prefers OpenRouter's *reported* ``usage.cost`` (USD,
      → ``source='measured'``) when present, falling back to the base's
      token×price computation. A usage block with neither a reported cost nor
      configured pricing is ``source='unknown'`` — never a fabricated zero
      (SW-3 / HI-2 contract).

Design note: the original P5.01 spec wrote this as a standalone implementation
(it predated P3.02). Operator-approved reconciliation subclasses HttpBackend so
the HTTP logic lives in one place and the transport/capability surface stays
consistent.
"""

from __future__ import annotations

import logging
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from .http_base import HttpBackend

if TYPE_CHECKING:
    from ..config import BridgeConfig
    from ..cost_tracker import CostMeasurement

logger = logging.getLogger(__name__)

#: OpenRouter's OpenAI-compatible endpoint base (matches
#: ``cross_model.openrouter_client.OPENROUTER_URL`` without the path suffix).
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"


class OpenRouterBackend(HttpBackend):
    """OpenRouter (DeepSeek / GLM / cheap-frontier) HTTP backend.

    Constructed with a ``BridgeConfig``; reads ``openrouter_api_key`` (auth)
    and ``fallback_openrouter_model`` (default model). Optional per-1M pricing
    can be supplied so token-based cost is estimated when OpenRouter does not
    report ``usage.cost`` directly.
    """

    def __init__(
        self,
        config: BridgeConfig,
        *,
        price_per_1m: tuple[float, float] | None = None,
    ) -> None:
        self.config = config
        # Prefer the dedicated openrouter_default_model (P5.02); fall back to
        # fallback_openrouter_model for configs predating that field.
        default_model = getattr(
            config, "openrouter_default_model", None
        ) or config.fallback_openrouter_model
        super().__init__(
            base_url=OPENROUTER_BASE_URL,
            api_key=config.openrouter_api_key,
            model=default_model,
            price_per_1m=price_per_1m,
        )

    def auth_env(self) -> dict[str, str]:
        """Inject ``OPENROUTER_API_KEY`` so a subprocess-free dispatch authenticates.

        Empty dict when no key is configured (mirrors the graceful-degradation
        pattern — the call fails loud at request time, not at construction).
        """
        key = self.config.openrouter_api_key
        return {"OPENROUTER_API_KEY": key} if key else {}

    def parse_cost(self, event: dict[str, Any]) -> "CostMeasurement":
        """Prefer OpenRouter's reported ``usage.cost`` (USD) over token×price.

        OpenRouter credit accounts return a dollar cost directly in
        ``usage.cost`` → ``source='measured'``. When that field is absent, fall
        back to the base ``HttpBackend.parse_cost`` (token×configured price, or
        ``source='unknown'`` if no pricing). The backend tag is ``"openrouter"``
        rather than the base ``"http"`` so cost rows attribute correctly.
        """
        from ..cost_tracker import CostMeasurement

        usage = event.get("usage")
        usage_id = event.get("id") or None
        if isinstance(usage, dict) and "cost" in usage:
            reported = usage["cost"]
            if isinstance(reported, (int, float)):
                return CostMeasurement(
                    amount_usd=Decimal(str(reported)),
                    source="measured",
                    backend="openrouter",
                    raw_usage_id=usage_id,
                )

        # No reported dollar cost — defer to the base token×price path, then
        # re-tag the backend as openrouter.
        base = super().parse_cost(event)
        return CostMeasurement(
            amount_usd=base.amount_usd,
            source=base.source,
            backend="openrouter",
            raw_usage_id=base.raw_usage_id,
        )
