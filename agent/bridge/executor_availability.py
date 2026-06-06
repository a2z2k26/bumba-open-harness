"""Executor availability provider — single source for the /status surface.

Sprint **audit-2026-05-16.F.02** (issue #2075, audit finding **SW-4**).

Pre-F.02 the codebase exposed two independent operator surfaces for
executor state:

* ``bridge.executors.availability_snapshot()`` — a static dict[str, str]
  reporting per-executor *runtime availability* ("can it run a WorkOrder
  right now?"). Consumed by ``/status`` and ``/status --full``.
* ``bridge.dispatcher.Dispatcher.get_executor_statuses()`` — a
  semi-static dict[str, str] reporting per-executor *activation state*
  ("is it wired into the dispatcher and how does it route?"). Consumed
  only by ``/status --full``.

Both surfaces answer "what is the state of the executor lane?", but
with different keys (uppercase vs lowercase), different sets (3 vs 4-5),
and orthogonal semantics. The audit (SW-4) called out the duplication
and the incomplete static snapshot — operator-facing output can drift
from actual ``WORKTREE`` / ``SUBAGENT`` / ``E2B`` availability without
either surface noticing.

This module introduces :class:`ExecutorAvailabilityProvider` — one
provider, one snapshot, one canonical set of known executor names. The
legacy ``availability_snapshot()`` becomes a thin facade over
:func:`default_provider`; the dispatcher's activation-status surface is
left intact (it answers a different question) but is cross-checked via
the drift test on :attr:`ExecutorAvailabilityProvider.known_executor_names`.

The canonical executor *availability* set today is
``{"WORKTREE", "SUBAGENT", "E2B"}`` — the three executors the existing
``availability_snapshot()`` reported. Adding or removing a name without
updating the drift test signals an intentional contract change.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass


@dataclass(frozen=True)
class ExecutorStatus:
    """Immutable per-executor availability record.

    ``name`` is the canonical uppercase executor identifier (e.g.
    ``"WORKTREE"``). ``available`` reports whether the executor can
    accept a WorkOrder right now. ``reason`` is a short human-readable
    note explaining a False ``available`` — empty string when the
    executor is available.
    """

    name: str
    available: bool
    reason: str = ""


class ExecutorAvailabilityProvider:
    """Single source of per-executor availability for ``/status``.

    Constructed with a mapping of executor-name → zero-argument check
    function. Each check returns the current :class:`ExecutorStatus`
    for that executor. The provider does not introspect the executor
    classes itself — the check functions hold the truth about what
    "available" means per executor.

    The provider is intentionally minimal: no caching, no rate
    limiting, no side effects. Callers that need throttling (e.g.
    Discord ``/status`` polling) wrap the provider themselves.
    """

    def __init__(self, checks: Mapping[str, Callable[[], ExecutorStatus]]) -> None:
        # Defensive copy so callers can't mutate the registry post-construction.
        self._checks: dict[str, Callable[[], ExecutorStatus]] = dict(checks)

    def snapshot(self) -> dict[str, ExecutorStatus]:
        """Return one :class:`ExecutorStatus` per registered executor.

        Order matches insertion order of the underlying check map; the
        rendering layer is responsible for any sort it wants.
        """
        return {name: check() for name, check in self._checks.items()}

    @property
    def known_executor_names(self) -> frozenset[str]:
        """Frozen set of registered executor names.

        Used by the drift test to detect intentional additions/removals
        to the canonical executor set without touching the test forcing
        the operator to acknowledge the change.
        """
        return frozenset(self._checks.keys())


# ---------------------------------------------------------------------------
# Default provider wiring
# ---------------------------------------------------------------------------

# Status strings preserved verbatim from the pre-F.02
# ``bridge.executors.availability_snapshot()`` constants so the wire
# format consumed by ``format_executor_section`` is unchanged.
_WORKTREE_AVAILABLE = "available"
_SUBAGENT_AVAILABLE = "available"
# E2B operability landed (#416): execute() drives a real sandbox run via the
# bumba-sandbox MCP when e2b_executor_enabled + e2b_api_key + claude_runner are
# present. This static surface can't see runtime config, so it reports the
# config-gated default; the live routable status is on /status --full
# (dispatcher.get_executor_statuses).
_E2B_BLOCKED_REASON = "config-gated: set e2b_executor_enabled + e2b_api_key (see /status --full)"


def _check_worktree() -> ExecutorStatus:
    """Worktree executor is always available (uses local git worktrees)."""
    return ExecutorStatus(name="WORKTREE", available=True, reason="")


def _check_subagent() -> ExecutorStatus:
    """Subagent executor is always available (uses ``claude -p`` subprocess)."""
    return ExecutorStatus(name="SUBAGENT", available=True, reason="")


def _check_e2b() -> ExecutorStatus:
    """E2B is config-gated. This static surface can't read runtime config;
    the live routable status is on ``/status --full``
    (``dispatcher.get_executor_statuses``)."""
    return ExecutorStatus(name="E2B", available=False, reason=_E2B_BLOCKED_REASON)


def default_provider() -> ExecutorAvailabilityProvider:
    """Build the canonical provider with the codebase's known check map.

    Concrete check functions live in this module (not imported from the
    executor classes) so the provider can be exercised in isolation —
    no executor subpackage import required, no async setup. The check
    functions encode exactly the constants the legacy
    ``availability_snapshot()`` returned.
    """
    return ExecutorAvailabilityProvider({
        "WORKTREE": _check_worktree,
        "SUBAGENT": _check_subagent,
        "E2B": _check_e2b,
    })


def snapshot_as_legacy_dict(
    provider: ExecutorAvailabilityProvider | None = None,
) -> dict[str, str]:
    """Render the provider's snapshot in the legacy dict[str, str] form.

    Preserves the pre-F.02 wire format ``format_executor_section``
    consumes: keys are executor names, values are either ``"available"``
    (when ``ExecutorStatus.available`` is True) or the ``reason`` string
    (when False). When ``provider`` is None, the default provider is used.
    """
    if provider is None:
        provider = default_provider()
    out: dict[str, str] = {}
    for name, status in provider.snapshot().items():
        if status.available:
            out[name] = "available"
        else:
            out[name] = status.reason or "unavailable"
    return out


__all__ = [
    "ExecutorStatus",
    "ExecutorAvailabilityProvider",
    "default_provider",
    "snapshot_as_legacy_dict",
]
