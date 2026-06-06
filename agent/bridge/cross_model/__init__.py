"""OpenRouter HTTP fallback client + adapter (used by `bridge.fallback.FallbackChain`).

Post-P2.4 (#1720) this package is OpenRouter-only. Five dead modules
(`pi_agent`, `agent_adapter`'s `ClaudeAdapter`/`PiAdapter` stubs, `agent_manifest`,
`litellm_config`, `quality_normalizer`) were deleted; only the live OpenRouter
HTTP client / adapter and the `AdapterResult` + `AgentAdapter` Protocol that
the adapter satisfies remain.
"""
from __future__ import annotations

from .agent_adapter import AdapterResult, AgentAdapter
from .openrouter_adapter import OpenRouterAdapter
from .openrouter_client import OPENROUTER_URL, OpenRouterClient

__all__ = [
    "AdapterResult",
    "AgentAdapter",
    "OpenRouterAdapter",
    "OpenRouterClient",
    "OPENROUTER_URL",
]
