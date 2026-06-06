"""Bridge backends — subprocess-CLI abstraction over agent runtimes.

Codex-1 (issue #1835) introduced ``BackendProtocol`` to extract Claude-specific
subprocess concerns from ``ClaudeRunner``. Codex-2 (issue #1836) adds
``CodexBackend``; Codex-3 (issue #1837) will land the registry-driven
selection layer on top.

Public surface:
    - ``BackendProtocol``: the 5-method interface (resolve_binary,
      build_command, parse_event, auth_env, shutdown).
    - ``ClaudeBackend``: the in-place default, lifted from ``claude_runner``.
    - ``CodexBackend``: OpenAI Codex CLI implementation (Codex-2, #1836).
    - ``StreamEvent``: the shared event dataclass each backend's
      ``parse_event`` returns.
    - ``codex_cost_computable``: fail-loud readiness flag consulted at
      ``backends_enabled`` flip time (E.04 #2011).
    - ``readiness_for_flip``: minimal pre-flip guard that refuses to flip
      ``backends_enabled`` when Codex is in the active set and
      ``codex_cost_computable()`` is False (E.04 #2011).
"""

from __future__ import annotations

from collections.abc import Iterable

from ._errors import CapabilityError
from ._protocol import BackendProtocol, StreamEvent
from .claude import ClaudeBackend
from .codex import CodexBackend
from .dispatch_guard import resolve_backend_for_dispatch
from .http_base import HttpBackend
from .one_shot import OneShotResult, spawn_one_shot
from .openrouter import OpenRouterBackend


def codex_cost_computable() -> bool:
    """Return True once Codex can emit a real ``cost_usd`` on ``turn.completed``.

    E.04 (#2011) — fail-loud guard. The Codex backend currently emits
    ``cost_usd=None`` + ``cost_unknown=True`` on every successful turn
    because OpenAI per-token pricing constants are not yet wired
    (TODO: Codex-6, #1840 — see ``codex.py:_parse_stream_line``).

    Until that lands, any deployment that flips ``backends_enabled = true``
    with ``codex`` in the active role set would silently corrupt cost
    aggregations. This function returns ``False`` so
    ``readiness_for_flip()`` (and any operator-tooling that consults the
    flag) refuses the flip.

    When Codex-6 ships the pricing model, flip this to ``True`` (or wire
    it to a real predicate against the pricing table) in the SAME PR that
    updates ``codex._parse_stream_line`` to emit real ``cost_usd`` floats.
    """
    # TODO: real pricing model — see #SW-4 / Codex-6 (#1840).
    return False


def readiness_for_flip(
    *,
    backends_enabled: bool,
    active_backends: Iterable[str],
) -> tuple[bool, str]:
    """Return ``(ready, reason)`` for a ``backends_enabled`` flip-on attempt.

    E.04 (#2011) — fail-loud guard wired in front of any operator action
    that flips ``backends_enabled`` from False to True. The guard refuses
    when ``codex`` is in ``active_backends`` and ``codex_cost_computable()``
    returns ``False`` — i.e. Codex would silently report unknown cost as
    ``$0.00`` in production. Other backends are not gated by this helper.

    Args:
        backends_enabled: the target value of the flag (must be ``True``
            for any check to fire).
        active_backends: iterable of backend names that would be active
            after the flip (typically the union of ``backends_main``,
            ``backends_chiefs_default``, ``backends_specialists_default``
            and the values of ``backends_specialists_overrides``).

    Returns:
        Tuple ``(ready, reason)``. ``ready`` is True when the flip is
        safe. ``reason`` is empty on the green path and names the missing
        precondition (and the issue it tracks) on the red path so
        operator-tooling can surface a one-line block message.
    """
    if not backends_enabled:
        # No flip being attempted — nothing to gate.
        return True, ""
    active_set = {str(b) for b in active_backends}
    if "codex" in active_set and not codex_cost_computable():
        return False, (
            "Refusing to flip backends_enabled=True with codex in the active "
            "backend set: codex_cost_computable() is False — Codex still "
            "reports cost_unknown=True on every turn.completed (audit E.04, "
            "issue #2011). Wire the OpenAI per-token pricing model "
            "(Codex-6, #1840) and flip codex_cost_computable() to True "
            "before re-attempting the flip."
        )
    return True, ""


__all__ = [
    "BackendProtocol",
    "CapabilityError",
    "ClaudeBackend",
    "CodexBackend",
    "HttpBackend",
    "OneShotResult",
    "OpenRouterBackend",
    "StreamEvent",
    "codex_cost_computable",
    "readiness_for_flip",
    "resolve_backend_for_dispatch",
    "spawn_one_shot",
]
