"""In-memory ring buffer of recent routing decisions for /status observability.

Issue #1540 — surface the last N routing decisions so the operator can answer
"why did that message go to Haiku vs Sonnet?" or "which department picked it
up?" at runtime, via ``/status``.

This module deliberately keeps the surface minimal:

- A ``RoutingDecisionRecord`` frozen dataclass capturing the fields the issue
  calls out (``message_id``, ``router_used``, ``intent``, ``severity``,
  ``model_selected``, ``department_routed_to``) plus a ``timestamp_ms`` for
  display ordering.
- A ``RoutingHistory`` singleton with ``record(record)`` and ``recent(n=5)``
  methods backed by ``collections.deque(maxlen=5)``.
- A module-level ``record_routing_decision`` convenience that the call site
  uses directly so the routers themselves don't have to construct
  ``RoutingDecisionRecord`` instances.

Design notes (per the task brief):

- Default to a plain ``deque``. The router call site (``app.py::_invoke_claude``)
  is not async-locked around the routing call; this is observability, not
  source of truth, so a theoretical lost-record race is acceptable.
- No persistence; ring buffer is in-process only. If the bridge restarts, the
  buffer is empty until the next message arrives. That's intentional — the
  operator can ``/log`` for the durable trail.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from threading import Lock
from typing import Optional

__all__ = [
    "RoutingDecisionRecord",
    "RoutingHistory",
    "record_routing_decision",
    "get_history",
]


@dataclass(frozen=True)
class RoutingDecisionRecord:
    """A single routing decision snapshot.

    Fields mirror issue #1540 acceptance criteria. Any field that wasn't
    available at the decision point is stored as ``None`` rather than
    fabricated.
    """

    message_id: Optional[str]
    router_used: str
    intent: Optional[str]
    severity: Optional[str]
    model_selected: Optional[str]
    department_routed_to: Optional[str]
    timestamp_ms: int


class RoutingHistory:
    """Bounded ring buffer of recent routing decisions.

    Backed by ``collections.deque(maxlen=maxlen)``. A ``threading.Lock`` guards
    the deque so that record() from sync paths and recent() from a /status
    handler running on the asyncio event loop don't race — the lock is cheap
    and uncontended in practice.
    """

    def __init__(self, maxlen: int = 5) -> None:
        self._buf: deque[RoutingDecisionRecord] = deque(maxlen=maxlen)
        self._lock = Lock()

    def record(self, decision: RoutingDecisionRecord) -> None:
        """Append a decision to the ring buffer (oldest dropped at capacity)."""
        with self._lock:
            self._buf.append(decision)

    def recent(self, n: int = 5) -> list[RoutingDecisionRecord]:
        """Return the most-recent ``n`` decisions in insertion order.

        When ``n`` exceeds the buffer size, returns everything currently held.
        """
        if n <= 0:
            return []
        with self._lock:
            # deque is iterable in insertion order; slice from the right.
            items = list(self._buf)
        return items[-n:]

    def clear(self) -> None:
        """Drop all recorded decisions. Test-only convenience."""
        with self._lock:
            self._buf.clear()


# Process-wide singleton. The bridge is a single-process daemon, so a module
# global is the simplest surface. Tests can either ``clear()`` between cases
# or construct their own ``RoutingHistory`` instance.
_HISTORY = RoutingHistory(maxlen=5)


def get_history() -> RoutingHistory:
    """Return the process-wide RoutingHistory singleton."""
    return _HISTORY


def record_routing_decision(
    *,
    message_id: Optional[str],
    router_used: str,
    intent: Optional[str] = None,
    severity: Optional[str] = None,
    model_selected: Optional[str] = None,
    department_routed_to: Optional[str] = None,
    timestamp_ms: Optional[int] = None,
) -> None:
    """Record a routing decision on the process-wide history.

    All fields except ``router_used`` are optional; pass ``None`` when the
    field genuinely isn't available at the call site rather than fabricating.

    ``timestamp_ms`` defaults to ``time.time() * 1000`` if not supplied.
    """
    if timestamp_ms is None:
        import time
        timestamp_ms = int(time.time() * 1000)

    _HISTORY.record(
        RoutingDecisionRecord(
            message_id=str(message_id) if message_id is not None else None,
            router_used=router_used,
            intent=intent,
            severity=severity,
            model_selected=model_selected,
            department_routed_to=department_routed_to,
            timestamp_ms=timestamp_ms,
        )
    )
