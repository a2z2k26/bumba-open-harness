"""Health + API index + heartbeat routes (Sprint P6.2 split).

Pure reorg of the corresponding handlers from ``bridge.api_server`` —
no behavioural change. The mixin class is mixed into ``APIServer`` so
``self`` resolves to the live bridge owner of ``_bridge``, ``_app_ref``,
``_start_time``, etc.
"""
from __future__ import annotations

import time

from aiohttp import web

from ._helpers import _ok, _redact_heartbeat_url


class _HealthRoutesMixin:
    """Provides health, API-index, and heartbeat-status handlers."""

    def _register_health_routes(self, app: web.Application) -> None:
        # Health (no auth required — handled by middleware skip)
        app.router.add_get("/healthz", self._handle_healthz)

        # API index
        app.router.add_get("/api", self._handle_api_index)

        # Heartbeat status (Sprint 07.09 — dead-man's switch observability)
        app.router.add_get(
            "/api/heartbeat/status", self._handle_heartbeat_status
        )

    # ------------------------------------------------------------------
    # Health
    # ------------------------------------------------------------------

    async def _handle_healthz(self, request: web.Request) -> web.Response:
        """Delegate to existing HealthServer logic."""
        health_server = self._bridge._health_server
        if health_server:
            health = await health_server.collect_health()
            status_code = 200 if health["status"] == "healthy" else 503
            return web.json_response(health, status=status_code)
        return _ok({
            "status": "healthy",
            "uptime_seconds": int(time.monotonic() - self._start_time),
        })

    async def _handle_heartbeat_status(
        self, request: web.Request
    ) -> web.Response:
        """Return the dead-man's switch heartbeat state (Sprint 07.09).

        Response shape:
            {
                "enabled": bool,        # url is configured
                "last_ping": float|None, # unix ts of last successful ping
                "target": str|null      # redacted to domain only — never
                                        # exposes the secret check ID
            }
        """
        pinger = getattr(self._bridge, "_heartbeat_pinger", None)
        url = getattr(pinger, "_check_url", None) if pinger else None
        last_ping = getattr(pinger, "last_ping_at", None) if pinger else None
        return _ok({
            "enabled": bool(url),
            "last_ping": last_ping,
            "target": _redact_heartbeat_url(url),
        })

    # ------------------------------------------------------------------
    # API Index
    # ------------------------------------------------------------------

    # NOTE: This handler is introspective — it enumerates all registered routes
    # at response time. CLAUDE.md is the authoritative operator-facing doc;
    # Plan 09 keeps it in sync with this introspection.
    async def _handle_api_index(self, request: web.Request) -> web.Response:
        """Return JSON listing of all registered endpoints.

        Walks ``self._app_ref.router.routes()`` so the response can never
        drift from the routes actually mounted by ``_register_routes``.

        Filter rules:
          - INCLUDE paths starting with ``/api/`` or ``/ws/`` and the
            literal ``/healthz``.
          - EXCLUDE paths starting with ``/internal/``.
          - EXCLUDE the auto-generated HEAD twin aiohttp adds for every
            GET route (HEAD is method-level duplication, not a distinct
            endpoint operators care about).
          - DEDUPE on (method, path) so any accidental double-registration
            renders once.
        """
        # Lazy import: avoids circular import at module load time since
        # ``_enumerate_public_routes`` lives in ``bridge.api_server``.
        from bridge.api_server import _enumerate_public_routes
        routes = _enumerate_public_routes(self._app_ref)
        return _ok({
            "routes": routes,
            "count": len(routes),
            "version": "1.0.0",
        })
