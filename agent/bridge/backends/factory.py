"""Backend-instances factory for ``BackendRegistry``.

Phase 5 (model-agnostic runtime): assembles the ``{name: BackendProtocol}``
dict that ``BackendRegistry`` (``backends/registry.py``) resolves against.
Centralizing construction keeps ``BridgeApp`` boot wiring thin and gives
tests one seam to build the full backend set from a ``BridgeConfig``.

The factory constructs every known backend unconditionally — the registry
only ever hands out the ones named by ``config.backends_*`` policy, and the
whole registry stays dormant until ``backends_enabled`` flips (default
false, see ``config.py``). Constructing an unused backend is cheap (no I/O,
no network) and keeps the dict's key set stable for the resolver's
``KeyError`` contract.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ._protocol import BackendProtocol
from .claude import ClaudeBackend
from .codex import CodexBackend
from .openrouter import OpenRouterBackend

if TYPE_CHECKING:
    from ..config import BridgeConfig


def build_backend_instances(config: BridgeConfig) -> dict[str, BackendProtocol]:
    """Return the canonical ``{name: BackendProtocol}`` dict.

    Keys are the stable backend names operators use in ``[backends]`` policy
    (``backends_main`` etc.): ``"claude"``, ``"codex"``, ``"openrouter"``. The
    dict is freshly constructed each call so callers own the lifecycle;
    ``BackendRegistry`` takes a defensive copy.
    """
    return {
        "claude": ClaudeBackend(config),
        "codex": CodexBackend(config),
        "openrouter": OpenRouterBackend(config),
    }
