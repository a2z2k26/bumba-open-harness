"""Sprint 23 (Phase 5D) — REST routes for the directive lifecycle dashboard.

Adds four endpoints to the existing Mission Control API:

- GET  /api/directives                — list directives (filterable by status)
- GET  /api/directives/{id}/tree      — directive + child tasks + correlated surfaces
- GET  /api/surfaces                  — surfaces (filterable by unread / to_agent / kind)
- POST /api/surfaces/{id}/ack         — acknowledge a surface

All four sit behind the existing Bearer-token middleware and per-IP rate
limiter. The WebSocket live-update path is the existing ``/ws/events``
stream — Sprint 23 added five new event types (``directive.issued``,
``directive.status_changed``, ``task.status_changed``, ``surface.written``,
``surface.acknowledged``) that the stores publish on every state change,
so dashboard subscribers get real-time updates without any new WebSocket
topic.

Registration model mirrors ``Zone4Routes`` in
``bridge/observability/api_routes.py``: a ``register(app)`` method that
tolerates a frozen router (graceful degradation if the caller wires
this in post-start). The recommended call order is **before**
``api_server.start()`` — same router-ordering lesson as Epic #620
Sprint 7.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from aiohttp import web

if TYPE_CHECKING:
    from bridge.database import Database

log = logging.getLogger(__name__)


def _serialise_directive(d: Any) -> dict[str, Any]:
    """Convert a Directive dataclass into a JSON-friendly dict."""
    return {
        "directive_id": d.directive_id,
        "from_agent": d.from_agent,
        "to_chief": d.to_chief,
        "intent": d.intent,
        "constraints": list(d.constraints),
        "deadline_utc": d.deadline_utc.isoformat() if d.deadline_utc else None,
        "priority": d.priority,
        "issued_at_utc": d.issued_at_utc.isoformat(),
        "context": dict(d.context),
        "operator_id": d.operator_id,
    }


def _serialise_task(t: Any) -> dict[str, Any]:
    return {
        "task_id": t.task_id,
        "directive_id": t.directive_id,
        "from_chief": t.from_chief,
        "to_specialist": t.to_specialist,
        "description": t.description,
        "constraints": list(t.constraints),
        "deadline_utc": t.deadline_utc.isoformat() if t.deadline_utc else None,
        "issued_at_utc": t.issued_at_utc.isoformat(),
    }


def _serialise_surface(s: Any) -> dict[str, Any]:
    kind = s.kind.value if hasattr(s.kind, "value") else s.kind
    urgency = s.urgency.value if hasattr(s.urgency, "value") else s.urgency
    return {
        "surface_id": s.surface_id,
        "from_agent": s.from_agent,
        "to_agent": s.to_agent,
        "kind": kind,
        "urgency": urgency,
        "correlation_id": s.correlation_id,
        "payload": dict(s.payload),
        "created_at_utc": s.created_at_utc.isoformat(),
    }


class DirectiveRoutes:
    """REST routes for the Phase 5 directive lifecycle dashboard.

    Holds a reference to the live Database so handlers don't have to
    re-resolve it from the request context every call.
    """

    def __init__(self, *, db: "Database") -> None:
        self._db = db

    # -- registration ------------------------------------------------------

    def register(self, app: web.Application) -> None:
        """Register all directive routes on an aiohttp application.

        Tolerates a frozen router so a misordered caller can't break
        bridge startup — the dashboard endpoints simply remain absent
        until the order is fixed. (Same graceful-degradation pattern
        as Zone4Routes.)
        """
        try:
            self._register_routes(app)
        except RuntimeError as exc:
            if "frozen router" in str(exc).lower():
                log.warning(
                    "DirectiveRoutes: router is frozen; skipping registration. "
                    "Fix: call register() before api_server.start()."
                )
                return
            raise

    def _register_routes(self, app: web.Application) -> None:
        app.router.add_get("/api/directives", self._handle_list_directives)
        app.router.add_get(
            "/api/directives/{directive_id}/tree", self._handle_directive_tree
        )
        app.router.add_get("/api/surfaces", self._handle_list_surfaces)
        app.router.add_post(
            "/api/surfaces/{surface_id}/ack", self._handle_ack_surface
        )

    # -- handlers ----------------------------------------------------------

    async def _handle_list_directives(
        self, request: web.Request
    ) -> web.Response:
        """GET /api/directives?status=active|all&limit=50

        Returns: {"directives": [...]}.
        Defaults to status=active (non-terminal). limit clamps to [1, 200].
        """
        from bridge import directive_store

        status = request.query.get("status", "active").lower()
        try:
            limit = int(request.query.get("limit", "50"))
        except ValueError:
            limit = 50
        limit = max(1, min(limit, 200))

        try:
            if status == "all":
                directives = await directive_store.list_all(self._db, limit=limit)
            elif status == "active":
                directives = await directive_store.list_active(self._db)
                directives = directives[:limit]
            else:
                return web.json_response(
                    {"error": f"unknown status filter: {status}"},
                    status=400,
                )
        except Exception as exc:  # noqa: BLE001
            log.exception("list_directives failed")
            return web.json_response({"error": str(exc)}, status=500)

        return web.json_response(
            {"directives": [_serialise_directive(d) for d in directives]}
        )

    async def _handle_directive_tree(
        self, request: web.Request
    ) -> web.Response:
        """GET /api/directives/{directive_id}/tree

        Returns: {"directive": {...}, "tasks": [...], "surfaces": [...]}.
        404 if directive_id is unknown. Surfaces include both
        chief-correlated (correlation_id == directive_id) and
        task-correlated (correlation_id == task_id for each child task).
        """
        from bridge import directive_store, surface_store, task_store

        directive_id = request.match_info["directive_id"]

        try:
            directive = await directive_store.get_directive(self._db, directive_id)
            if directive is None:
                return web.json_response(
                    {"error": "not found"}, status=404
                )

            tasks = await task_store.list_by_directive(self._db, directive_id)
            chief_surfaces = await surface_store.list_by_correlation(
                self._db, directive_id
            )
            # Aggregate surfaces from each child task too — the spec asks
            # for "list of surfaces grouped by correlation, chronological"
            all_surfaces = list(chief_surfaces)
            for t in tasks:
                task_surfaces = await surface_store.list_by_correlation(
                    self._db, t.task_id
                )
                all_surfaces.extend(task_surfaces)
            # Sort merged surfaces chronologically
            all_surfaces.sort(key=lambda s: s.created_at_utc)
        except Exception as exc:  # noqa: BLE001
            log.exception("directive_tree failed id=%s", directive_id)
            return web.json_response({"error": str(exc)}, status=500)

        return web.json_response({
            "directive": _serialise_directive(directive),
            "tasks": [_serialise_task(t) for t in tasks],
            "surfaces": [_serialise_surface(s) for s in all_surfaces],
        })

    async def _handle_list_surfaces(
        self, request: web.Request
    ) -> web.Response:
        """GET /api/surfaces?unread=true&to_agent=main&kind=blocker&limit=50

        All filters optional. Defaults: most recent 50 unread.
        """
        from bridge import surface_store

        unread = request.query.get("unread", "true").lower() in ("1", "true", "yes")
        to_agent = request.query.get("to_agent")
        kind = request.query.get("kind")
        try:
            limit = int(request.query.get("limit", "50"))
        except ValueError:
            limit = 50
        limit = max(1, min(limit, 200))

        try:
            if to_agent and unread:
                surfaces = await surface_store.list_unread_for_agent(
                    self._db, to_agent
                )
            elif kind:
                try:
                    surfaces = await surface_store.list_by_kind(
                        self._db, kind, limit=limit
                    )
                except ValueError as e:
                    return web.json_response(
                        {"error": str(e)}, status=400
                    )
            elif unread:
                surfaces = await surface_store.list_active(self._db, limit=limit)
            else:
                surfaces = await surface_store.list_all(self._db, limit=limit)
            surfaces = surfaces[:limit]
        except Exception as exc:  # noqa: BLE001
            log.exception("list_surfaces failed")
            return web.json_response({"error": str(exc)}, status=500)

        return web.json_response(
            {"surfaces": [_serialise_surface(s) for s in surfaces]}
        )

    async def _handle_ack_surface(
        self, request: web.Request
    ) -> web.Response:
        """POST /api/surfaces/{surface_id}/ack

        Returns 200 with {"updated": bool}. Idempotent — re-acking the
        same surface returns updated=false rather than churning the
        timestamp. 404 if surface_id is unknown.
        """
        from bridge import surface_store

        surface_id = request.match_info["surface_id"]
        try:
            updated = await surface_store.mark_read(self._db, surface_id)
        except ValueError as exc:
            return web.json_response({"error": str(exc)}, status=404)
        except Exception as exc:  # noqa: BLE001
            log.exception("ack_surface failed id=%s", surface_id)
            return web.json_response({"error": str(exc)}, status=500)
        return web.json_response({"updated": updated})
