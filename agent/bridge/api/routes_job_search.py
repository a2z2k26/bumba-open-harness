"""Job search funnel route (Sprint P6.2 split).

Pure reorg from ``bridge.api_server``. Single endpoint (D5.8) returning
funnel-failure aggregation across boards/ATS/steps.
"""
from __future__ import annotations

import logging

from aiohttp import web

from ._helpers import _error

logger = logging.getLogger(__name__)


class _JobSearchRoutesMixin:
    """Provides /api/job_search/funnel handler."""

    def _register_job_search_routes(self, app: web.Application) -> None:
        app.router.add_get("/api/job_search/funnel", self._handle_job_search_funnel)

    # ------------------------------------------------------------------
    # D5.8 — Job search funnel-failure aggregator
    # ------------------------------------------------------------------

    async def _handle_job_search_funnel(self, request: web.Request) -> web.Response:
        """Return per-board/ATS/step funnel-failure report.

        GET /api/job_search/funnel?window=7d

        Query params:
            window: "7d" (default) | "30d" | "all"

        Returns a JSON-serialised FunnelReport (via dataclasses.asdict).
        """
        window = request.rel_url.query.get("window", "7d")
        try:
            import dataclasses
            from job_search.funnel import aggregate_funnel
            report = aggregate_funnel(window=window)
            return web.json_response(dataclasses.asdict(report))
        except Exception as exc:
            logger.exception("D5.8 funnel endpoint error")
            return _error(str(exc), status=500)
