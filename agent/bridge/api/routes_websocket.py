"""WebSocket events route (Sprint P6.2 split).

Pure reorg from ``bridge.api_server``. The /ws/events handler is the
only generic-event WebSocket route; per-WorkOrder WS lives in
``routes_workorders``.
"""
from __future__ import annotations

import asyncio
import json
import logging
import secrets

from aiohttp import web

logger = logging.getLogger(__name__)


async def _supervise_send(server, ws, data: str) -> None:
    """Send ``data`` on ``ws`` and supervise the result.

    Addresses audit finding M-5 (issue #2079, sprint audit-2026-05-16.F.06):
    the pre-fix path was ``asyncio.ensure_future(ws.send_str(data))`` —
    fire-and-forget. Closed-connection / ConnectionResetError /
    cancellation all surfaced as logged warnings on the event loop at
    best, and were silently dropped at worst, leaving stale clients in
    ``server._ws_clients``.

    Failure handling: increment ``websocket.event_push_failed`` on the
    MetricsCollector wired through ``server._bridge._metrics``, log one
    warning with the connection id + error type, and evict the dead ws
    from the registry. Cleanup is race-safe — the registry is mutated
    only if ``ws`` is still present.
    """
    try:
        await ws.send_str(data)
    except Exception as exc:  # noqa: BLE001 — broad on purpose: any send error evicts.
        metrics = getattr(getattr(server, "_bridge", None), "_metrics", None)
        if metrics is not None:
            try:
                metrics.increment("websocket.event_push_failed")
            except Exception:  # pragma: no cover — metrics must never propagate.
                pass
        logger.warning(
            "websocket event push failed",
            extra={
                "connection_id": id(ws),
                "error": type(exc).__name__,
            },
        )
        clients = getattr(server, "_ws_clients", None)
        if clients is not None and ws in clients:
            try:
                clients.remove(ws)
            except ValueError:  # pragma: no cover — race on concurrent eviction.
                pass


class _WebSocketRoutesMixin:
    """Provides the /ws/events WebSocket handler."""

    def _register_websocket_routes(self, app: web.Application) -> None:
        app.router.add_get("/ws/events", self._handle_ws_events)

    # ------------------------------------------------------------------
    # WebSocket (Phase 2)
    # ------------------------------------------------------------------

    async def _handle_ws_events(self, request: web.Request) -> web.Response:
        """WebSocket endpoint for real-time event streaming."""
        ws = web.WebSocketResponse(heartbeat=30.0)
        await ws.prepare(request)

        # Auth via query param for WebSocket (upgrade first, then reject)
        # Fail closed: if api_token is empty string, reject — no unauthenticated access
        token = request.query.get("token", "")
        if not self._api_token or not secrets.compare_digest(token, self._api_token):
            await ws.send_json({"error": "Unauthorized"})
            await ws.close()
            return ws
        self._ws_clients.append(ws)

        # Parse type filter (?types=a,b,c — exact-match list, pre-existing).
        type_filter = request.query.get("types", "")
        allowed_types = set(type_filter.split(",")) if type_filter else None

        # Z4-S61 (#1405) — opt-in prefix filter. Orthogonal to ?types=:
        # ?filter=chief_session. forwards every event whose type starts
        # with that string. Empty / missing = forward everything (the
        # back-compat default — same shape clients see today).
        prefix_filter = request.query.get("filter", "")

        # Subscribe to EventBus
        autonomy = self._bridge._autonomy
        sub_ids: list[str] = []
        if autonomy:
            loop = asyncio.get_running_loop()

            def _on_event(event):
                if allowed_types and event.event_type not in allowed_types:
                    return
                # Defense-in-depth: gate on prefix even though the
                # subscription set below is already prefix-narrowed.
                # Cheap to recheck and keeps the contract obvious if a
                # future refactor changes the subscription strategy.
                if prefix_filter and not event.event_type.startswith(
                    prefix_filter
                ):
                    return
                if ws.closed:
                    return
                try:
                    data = json.dumps({
                        "event_id": event.event_id,
                        "event_type": event.event_type,
                        "payload": event.payload,
                        "source": event.source,
                        "timestamp": event.timestamp,
                        "correlation_id": event.correlation_id,
                    })
                    # F.06 (#2079, M-5): supervise the send so failures
                    # are not silently swallowed. The supervisor logs,
                    # increments ``websocket.event_push_failed``, and
                    # evicts the dead ws from ``self._ws_clients``.
                    asyncio.ensure_future(
                        _supervise_send(self, ws, data), loop=loop
                    )
                except Exception:
                    pass

            from ..event_bus import EVENT_TYPES
            if allowed_types:
                # ?types= takes precedence — exact-match list.
                types_to_subscribe = allowed_types
            elif prefix_filter:
                # ?filter= — narrow to known event types matching the prefix.
                types_to_subscribe = tuple(
                    et for et in EVENT_TYPES if et.startswith(prefix_filter)
                )
            else:
                # Default — forward everything (unchanged behaviour).
                types_to_subscribe = EVENT_TYPES
            for et in types_to_subscribe:
                sub_ids.append(autonomy.event_bus.subscribe(et, _on_event))

        try:
            async for msg in ws:
                # Client messages are ignored (read-only stream)
                pass
        finally:
            if ws in self._ws_clients:
                self._ws_clients.remove(ws)
            if autonomy:
                for sid in sub_ids:
                    autonomy.event_bus.unsubscribe(sid)

        return ws
