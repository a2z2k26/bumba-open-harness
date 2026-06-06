"""Cost + trust + escalation routes (Sprint P6.2 split).

Pure reorg from ``bridge.api_server``. Grouped because all three handlers
read from the ``self._bridge._autonomy`` / ``self._bridge._cost_tracker``
subsystems and share their lifecycle (PoOL phase 5 autonomy stack).
"""
from __future__ import annotations

import json

from aiohttp import web

from ._helpers import _error, _ok


class _CostTrustRoutesMixin:
    """Provides /api/cost, /api/trust, /api/escalation/* handlers."""

    def _register_cost_trust_routes(self, app: web.Application) -> None:
        # Cost
        app.router.add_get("/api/cost", self._handle_cost)

        # Trust
        app.router.add_get("/api/trust", self._handle_trust)

        # Escalation
        app.router.add_get("/api/escalation", self._handle_list_escalation)
        app.router.add_post(
            "/api/escalation/acknowledge", self._handle_acknowledge
        )
        app.router.add_post(
            "/api/escalation/defer", self._handle_defer
        )

    # ------------------------------------------------------------------
    # Cost
    # ------------------------------------------------------------------

    async def _handle_cost(self, request: web.Request) -> web.Response:
        """Return daily + weekly cost summary with per-agent breakdown."""
        tracker = self._bridge._cost_tracker
        if tracker is None:
            return _ok(
                {"daily": {}, "weekly": {}, "by_agent": {}, "by_workflow": {}}
            )
        try:
            daily = tracker.get_daily_summary()
            weekly = tracker.get_weekly_summary()
            by_agent = tracker.get_cost_by_agent()
            by_workflow = tracker.get_cost_by_workflow()
            return _ok({
                "daily": daily,
                "weekly": weekly,
                "by_agent": by_agent,
                "by_workflow": by_workflow,
            })
        except Exception as e:
            return _error(str(e), 500)

    # ------------------------------------------------------------------
    # Trust
    # ------------------------------------------------------------------

    async def _handle_trust(self, request: web.Request) -> web.Response:
        """Return trust scores for all capability domains."""
        autonomy = self._bridge._autonomy
        if autonomy is None:
            return _ok({"domains": {}})
        try:
            trust = autonomy.trust
            domains = {}
            for cap in trust._scores:
                cs = trust._scores[cap]
                domains[cap] = {
                    "score": cs.score,
                    "tier": trust.get_tier(cap),
                    "total_actions": cs.total_actions,
                    "successes": cs.successes,
                    "failures": cs.failures,
                    "override": cs.override_tier,
                }
            return _ok({"domains": domains})
        except Exception as e:
            return _error(str(e), 500)

    # ------------------------------------------------------------------
    # Escalation
    # ------------------------------------------------------------------

    async def _handle_list_escalation(
        self, request: web.Request
    ) -> web.Response:
        """List active escalation alerts."""
        autonomy = self._bridge._autonomy
        if autonomy is None:
            return _ok({"alerts": []})
        try:
            engine = autonomy.escalation
            alerts = []
            for source, alert in engine._active_alerts.items():
                alerts.append({
                    "source": source,
                    "level": int(alert.level),
                    "message": alert.message,
                    "triggered_at": alert.triggered_at,
                    "deferred": alert.deferred,
                })
            return _ok({"alerts": alerts, "count": len(alerts)})
        except Exception as e:
            return _error(str(e), 500)

    async def _handle_acknowledge(
        self, request: web.Request
    ) -> web.Response:
        """Acknowledge an alert (remove it from active)."""
        try:
            body = await request.json()
        except (json.JSONDecodeError, Exception):
            return _error("Invalid JSON body")
        source = body.get("source", "")
        if not source:
            return _error("'source' field is required")
        autonomy = self._bridge._autonomy
        if autonomy is None:
            return _error("Escalation engine not available", 503)
        engine = autonomy.escalation
        if source in engine._active_alerts:
            del engine._active_alerts[source]
            return _ok({"acknowledged": source})
        return _error(f"Alert '{source}' not found", 404)

    async def _handle_defer(self, request: web.Request) -> web.Response:
        """Defer an alert."""
        try:
            body = await request.json()
        except (json.JSONDecodeError, Exception):
            return _error("Invalid JSON body")
        source = body.get("source", "")
        if not source:
            return _error("'source' field is required")
        autonomy = self._bridge._autonomy
        if autonomy is None:
            return _error("Escalation engine not available", 503)
        engine = autonomy.escalation
        if source in engine._active_alerts:
            alert = engine._active_alerts[source]
            alert.deferred = True
            engine._deferred_queue.append(alert)
            del engine._active_alerts[source]
            return _ok({"deferred": source})
        return _error(f"Alert '{source}' not found", 404)
