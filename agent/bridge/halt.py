"""Shared HaltPolicy contract for autonomous surfaces (audit-2026-05-16.C.01).

Autonomous surfaces (job-search, factory, proactive, warm-chief,
experiment-loop, workflow_engine, ...) historically each rolled their own
pause concept: halt flag reads, per-service enabled flags, direct CLI
behavior, in-flight cancellation state. This module introduces ONE small
contract every surface can converge on.

The contract answers two questions:

    1. "May new autonomous work START on this surface?"  → check_start
    2. "Should in-flight work on this surface CANCEL?"   → check_continue

Both return a frozen HaltDecision carrying a boolean and a human-readable
reason. Reasons must be populated when blocked so operator logs are useful.

The policy is intentionally pure — no I/O, no SecurityManager dependency,
no filesystem reads. The halt state is injected as two callables so tests
can construct policies without fixtures and so the same policy class works
against any halt source (local file flag, remote kill switch, in-memory
test double).

This sprint introduces the contract only. Call-site migration to the
deeper autonomous surfaces is deferred to:

    - C.02 (#2057) warm-chief
    - C.03 (#2058) experiment-loop
    - C.04 (#2059) job-search
    - C.05 (#2060) factory
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class HaltDecision:
    """Result of consulting a HaltPolicy.

    Attributes:
        blocked: True when the surface must not start (or must cancel) work.
        reason: Human-readable explanation. None only when ``blocked`` is False.
    """

    blocked: bool
    reason: str | None = None


class HaltPolicy:
    """Decides whether autonomous work may start or continue.

    The policy holds two zero-argument callables that report the current
    halt state. It does not cache results — every ``check_*`` consults the
    callables, so policy instances can be long-lived (built once at boot
    and shared across surfaces).

    Args:
        is_halted: Returns True when the global halt flag is set.
        halt_reason: Returns the raw halt reason string, or None.
        cancel_in_flight: When True (default), a global halt blocks
            ``check_continue`` for in-flight work. When False, in-flight
            work is allowed to finish even when halt is set — useful for
            surfaces that must drain cleanly (e.g. flush a write buffer)
            rather than abort mid-operation.
    """

    def __init__(
        self,
        *,
        is_halted: Callable[[], bool],
        halt_reason: Callable[[], str | None],
        cancel_in_flight: bool = True,
    ) -> None:
        self._is_halted = is_halted
        self._halt_reason = halt_reason
        self._cancel_in_flight = cancel_in_flight

    def check_start(self, surface: str) -> HaltDecision:
        """Should new autonomous work be allowed to START on ``surface``?

        Returns a blocked decision when the global halt flag is set. The
        ``surface`` argument is propagated into the reason string for
        operator-log clarity.
        """
        if self._is_halted():
            return HaltDecision(
                blocked=True,
                reason=_format_reason(surface, self._halt_reason()),
            )
        return HaltDecision(blocked=False, reason=None)

    def check_continue(self, surface: str) -> HaltDecision:
        """Should in-flight autonomous work on ``surface`` be allowed to CONTINUE?

        Returns a blocked decision when the global halt flag is set AND the
        policy was constructed with ``cancel_in_flight=True`` (the default).
        Surfaces that opt out of cancellation (``cancel_in_flight=False``)
        always receive a non-blocked decision from this method — they are
        responsible for their own drain semantics.
        """
        if self._is_halted() and self._cancel_in_flight:
            return HaltDecision(
                blocked=True,
                reason=_format_reason(surface, self._halt_reason()),
            )
        return HaltDecision(blocked=False, reason=None)


def _format_reason(surface: str, raw_reason: str | None) -> str:
    """Build the operator-facing reason string.

    The surface argument is included so a grep of the log answers
    "which surface was blocked?" without needing to correlate timestamps.
    """
    raw = raw_reason or "halt flag set"
    return f"halt flag set (surface={surface}): {raw}"
