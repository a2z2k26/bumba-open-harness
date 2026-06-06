"""WorkOrder WebSocket subscription manager.

Sprint S12: Per-WO WebSocket subscription registry.
Fed by event_bus events; fans out to subscribed WebSocket queues.
"""
from __future__ import annotations

import asyncio
import logging
from collections import defaultdict

log = logging.getLogger(__name__)

# Events broadcast to WO subscribers
_WO_EVENT_NAMES = frozenset({
    "workorder.dispatched",
    "workorder.executing",
    "workorder.verifying",
    "workorder.completed",
    "workorder.failed",
    "workorder.resumed",
})


class WorkOrderStreamManager:
    """Per-WO WebSocket subscription registry. Fed by event_bus."""

    def __init__(self, event_bus: object | None = None) -> None:
        self._bus = event_bus
        self._subs: dict[str, set[asyncio.Queue]] = defaultdict(set)
        self._wired = False

    def subscribe(self, wo_id: str) -> asyncio.Queue:
        """Subscribe to state updates for a specific WO. Returns the event queue."""
        q: asyncio.Queue = asyncio.Queue(maxsize=100)
        self._subs[wo_id].add(q)
        return q

    def unsubscribe(self, wo_id: str, q: asyncio.Queue) -> None:
        """Unsubscribe a queue from WO updates."""
        if wo_id in self._subs:
            self._subs[wo_id].discard(q)
            if not self._subs[wo_id]:
                del self._subs[wo_id]

    def wire_event_bus(self) -> None:
        """Subscribe to all workorder.* events and fan out to WS queues."""
        if self._wired or self._bus is None:
            return
        for event_name in _WO_EVENT_NAMES:
            self._bus.subscribe(event_name, self._on_event)  # type: ignore[attr-defined]
        self._wired = True
        log.info("WorkOrderStreamManager wired to event bus")

    def _on_event(self, event_name: object, payload: dict | None = None) -> None:
        """Handle an event bus event and fan out to subscribed queues."""
        event_name, payload = self._event_name_and_payload(event_name, payload)
        wo_id = payload.get("workorder_id")
        if wo_id is None:
            return
        queues = list(self._subs.get(wo_id, ()))
        if not queues:
            return
        msg = {"event": event_name, "data": payload}
        for q in queues:
            try:
                q.put_nowait(msg)
            except asyncio.QueueFull:
                log.warning(
                    "WorkOrderStream: dropped event %s for WO %s (queue full)",
                    event_name, wo_id[:8],
                )

    def _event_name_and_payload(
        self,
        event_name: object,
        payload: dict | None,
    ) -> tuple[str, dict]:
        """Accept both legacy direct calls and live EventBus callbacks."""
        if isinstance(event_name, str) and payload is not None:
            return event_name, payload

        raw_event_type = getattr(event_name, "event_type", "")
        raw_payload = getattr(event_name, "payload", {})
        if isinstance(raw_event_type, str) and isinstance(raw_payload, dict):
            return raw_event_type, raw_payload

        return "", {}

    def broadcast_to_all(self, event_name: str, payload: dict) -> None:
        """Broadcast an event to all subscribed queues regardless of WO ID."""
        msg = {"event": event_name, "data": payload}
        for wo_id, queues in list(self._subs.items()):
            for q in list(queues):
                try:
                    q.put_nowait(msg)
                except asyncio.QueueFull:
                    pass

    def active_subscriptions(self) -> int:
        """Return total count of active subscriptions."""
        return sum(len(qs) for qs in self._subs.values())
