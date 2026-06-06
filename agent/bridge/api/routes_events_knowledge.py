"""Events + knowledge routes (Sprint P6.2 split).

Pure reorg from ``bridge.api_server``.
"""
from __future__ import annotations

from aiohttp import web

from ._helpers import _error, _ok


class _EventsKnowledgeRoutesMixin:
    """Provides /api/events, /api/knowledge, /api/knowledge/search."""

    def _register_events_knowledge_routes(self, app: web.Application) -> None:
        app.router.add_get("/api/events", self._handle_events)
        app.router.add_get(
            "/api/events/remote-status", self._handle_events_remote_status
        )
        app.router.add_get("/api/knowledge", self._handle_knowledge)
        app.router.add_get(
            "/api/knowledge/search", self._handle_knowledge_search
        )

    # ------------------------------------------------------------------
    # Events & Knowledge
    # ------------------------------------------------------------------

    async def _handle_events(self, request: web.Request) -> web.Response:
        """Return recent EventBus events."""
        limit = int(request.query.get("limit", "50"))
        autonomy = self._bridge._autonomy
        if autonomy is None:
            return _ok({"events": []})
        try:
            bus = autonomy.event_bus
            with bus._lock:
                events = list(bus._recent_events[-limit:])
            return _ok({
                "events": [
                    {
                        "event_id": e.event_id,
                        "event_type": e.event_type,
                        "payload": e.payload,
                        "source": e.source,
                        "timestamp": e.timestamp,
                        "correlation_id": e.correlation_id,
                    }
                    for e in reversed(events)
                ],
                "count": len(events),
                "total": bus.get_event_count(),
            })
        except Exception as e:
            return _error(str(e), 500)

    async def _handle_events_remote_status(
        self, request: web.Request
    ) -> web.Response:
        """Return the RemoteEventBridge transport mode + remote-delivery flag.

        Sprint S3.3 (backend-operability) — operators inspecting "remote
        events" must be able to tell whether the transport is the
        local-log default, the unimplemented MCP stub, or a real
        cross-machine transport. ``remote_delivery`` is True only when
        events actually leave this machine. When peer coordination is
        disabled (default), no bridge is constructed and the response
        reports ``transport_mode="none"`` with ``remote_delivery=False``.
        """
        bridge = getattr(self._bridge, "_remote_event_bridge", None)
        if bridge is None:
            return _ok({
                "transport_mode": "none",
                "remote_delivery": False,
                "bridge_wired": False,
            })
        try:
            payload = dict(bridge.status())
            payload["bridge_wired"] = True
            return _ok(payload)
        except Exception as e:
            return _error(str(e), 500)

    async def _handle_knowledge(self, request: web.Request) -> web.Response:
        """Return recent knowledge entries."""
        limit = int(request.query.get("limit", "20"))
        memory = self._bridge._memory
        if memory is None:
            return _ok({"entries": []})
        try:
            entries = await memory.get_recent_knowledge(limit=limit)
            return _ok({"entries": entries, "count": len(entries)})
        except Exception as e:
            return _error(str(e), 500)

    async def _handle_knowledge_search(
        self, request: web.Request
    ) -> web.Response:
        """Search knowledge using FTS5."""
        query = request.query.get("q", "")
        limit = int(request.query.get("limit", "10"))
        if not query:
            return _error("'q' query parameter is required")
        memory = self._bridge._memory
        if memory is None:
            return _error("Memory system not available", 503)
        try:
            results = await memory.search_knowledge(query, limit=limit)
            return _ok({"results": results, "query": query, "count": len(results)})
        except Exception as e:
            return _error(str(e), 500)
