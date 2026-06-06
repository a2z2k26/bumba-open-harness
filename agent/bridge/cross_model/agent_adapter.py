"""Agent adapter Protocol — live API surface used by OpenRouterAdapter.

Post-P2.4 (#1720) the cross-model package is OpenRouter-only. This module
retains exactly the two symbols that `openrouter_adapter.py` and its tests
import:

  * `AdapterResult` — standardised response envelope returned by `invoke()`
  * `AgentAdapter`  — runtime-checkable Protocol satisfied by `OpenRouterAdapter`

The pre-P2.4 `ClaudeAdapter` and `PiAdapter` stubs (with `TODO: Implement`
markers) were deleted in #1720 along with the rest of the dead cross_model
shape (pi_agent, agent_manifest, litellm_config, quality_normalizer). Any
future cross-vendor work will design a new backend-registry data model
distinct from the deleted capability-registry shape.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class AdapterResult:
    """Standardised result envelope returned by every adapter."""

    success: bool
    data: dict
    model_used: str
    tokens_used: int = 0
    error: str = ""


@runtime_checkable
class AgentAdapter(Protocol):
    """Protocol that every model adapter must implement."""

    async def invoke(self, prompt: str, context: dict | None = None) -> AdapterResult:
        """Invoke the model with the given prompt and optional context."""
        ...
