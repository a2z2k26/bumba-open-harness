"""Zone 4 operator report route (Z4-23 #2449).

Exposes ``GET /api/zone4/report`` — a read surface over the run manifests
the Zone 4 pipeline persists under ``zone4_artifact_root`` (config.py
default ``/opt/bumba-harness/zone4-runs``). The aggregation logic lives in
:mod:`bridge.zone4_report`; this mixin is the thin HTTP seam.

Why a read-only route over manifests rather than a new datastore: the
Z4-05 run-relay already finalizes one ``manifest.json`` per run with the
full telemetry block embedded (primary/fallback model, in/out tokens,
request count, duration, failure class) plus the artifact entries. That is
the queryable source the report needs — no log-ingest adapter required (the
premise the issue asked us to confirm). The report reads metadata only and
links back to manifest paths rather than embedding specialist output.

Query params:
    window: "24h" (default) or "7d".
    since / until: ISO-8601 bounds; when both present they override
        ``window``. Useful for an explicit date range.

Auth: bearer-token via the global middleware (no per-route auth code).
Always registered — when ``zone4_artifact_root`` is unset or empty the
handler returns a well-formed empty report rather than 503, so the operator
sees "no runs yet" instead of a wiring error.
"""
from __future__ import annotations

import logging

from aiohttp import web

from ._helpers import _error, _ok

logger = logging.getLogger(__name__)


class _Zone4ReportsRoutesMixin:
    """Provides GET /api/zone4/report (always registered)."""

    def _register_zone4_reports_routes(self, app: web.Application) -> None:
        app.router.add_get("/api/zone4/report", self._handle_zone4_report)

    async def _handle_zone4_report(
        self, request: web.Request
    ) -> web.Response:
        """GET /api/zone4/report — cost / provider / reliability aggregate."""
        from bridge.zone4_report import build_report

        config = getattr(self._bridge, "_config", None)
        artifact_root = getattr(config, "zone4_artifact_root", None)

        query = request.rel_url.query
        window = query.get("window")
        since = query.get("since")
        until = query.get("until")

        if not artifact_root:
            # No artifact root configured — return an empty, well-formed
            # report so the operator distinguishes "no runs" from a 5xx.
            try:
                from bridge.zone4_report import Zone4Report, parse_window

                start, end, label = parse_window(
                    window, since=since, until=until
                )
            except ValueError as exc:
                return _error(str(exc), 400)
            empty = Zone4Report(
                window=label,
                window_start_utc=_iso(start),
                window_end_utc=_iso(end),
                total_runs=0,
                skipped_count=0,
                departments=(),
            )
            return _ok(empty.to_dict())

        try:
            report = build_report(
                artifact_root, window=window, since=since, until=until
            )
        except ValueError as exc:
            # Bad window/timestamp spec — operator error, not a server fault.
            return _error(str(exc), 400)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Zone 4 report build failed")
            return _error(str(exc), 500)

        return _ok(report.to_dict())


def _iso(dt) -> str:
    from datetime import timezone

    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
