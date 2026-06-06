"""Metrics + traces routes (Sprint P6.2 split).

Pure reorg from ``bridge.api_server``.
"""
from __future__ import annotations

import json

from aiohttp import web

from ._helpers import _error, _ok


class _MetricsRoutesMixin:
    """Provides /api/metrics/{name} and /api/traces handlers."""

    def _register_metrics_routes(self, app: web.Application) -> None:
        app.router.add_get("/api/metrics/{name}", self._handle_metrics)
        app.router.add_get("/api/traces", self._handle_traces)

    # ------------------------------------------------------------------
    # Metrics & Traces
    # ------------------------------------------------------------------

    async def _handle_metrics(self, request: web.Request) -> web.Response:
        """Get metric data by name."""
        name = request.match_info["name"]
        metrics = self._bridge._metrics
        if metrics is None:
            return _ok({"name": name, "data": {}})
        try:
            snapshot = metrics.snapshot()
            # Check counters first, then histograms
            if name in snapshot.get("counters", {}):
                return _ok({
                    "name": name,
                    "type": "counter",
                    "value": snapshot["counters"][name],
                })
            if name in snapshot.get("histograms", {}):
                return _ok({
                    "name": name,
                    "type": "histogram",
                    "data": snapshot["histograms"][name],
                })
            return _ok({"name": name, "type": "unknown", "data": {}})
        except Exception as e:
            return _error(str(e), 500)

    async def _handle_traces(self, request: web.Request) -> web.Response:
        """Get recent trace spans."""
        limit = int(request.query.get("limit", "50"))
        tracer = self._bridge._tracer
        if tracer is None:
            return _ok({"traces": []})
        try:
            # Read recent spans from the tracer's output file
            spans = []
            output_path = tracer._output_path
            if output_path and output_path.exists():
                lines = output_path.read_text().strip().split("\n")
                for line in lines[-limit:]:
                    if line.strip():
                        try:
                            spans.append(json.loads(line))
                        except json.JSONDecodeError:
                            continue
            return _ok({"traces": list(reversed(spans)), "count": len(spans)})
        except Exception as e:
            return _error(str(e), 500)
