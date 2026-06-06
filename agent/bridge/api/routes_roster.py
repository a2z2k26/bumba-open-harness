"""Roster registry routes — RR.3 (issue #2593).

Operator-only REST surface over the ``RosterRegistryStore`` (RR.1): list the
runtime specialist overlay, register a specialist (validated), and unregister
one — all without a YAML edit or redeploy. The store handles validation +
cache invalidation; these handlers are a thin HTTP shell that maps a
``RegisterResult(ok=False)`` to a clean 400 (the seam audited in the spec:
surface the validation error, never a 500 or a silent null success).

The store lives on the bridge as ``_roster_registry`` (wired in a later
sprint / app boot). When it is absent, reads degrade to an empty list and
writes return 503 — never a 500.

Mirrors ``_CostTrustRoutesMixin`` structure.
"""
from __future__ import annotations

import json

from aiohttp import web

from ._helpers import _error, _ok

# Best-effort event emitted on a successful registration. The registry entry
# lives at ``config/registry/events/roster-registry.yaml`` (registry gate).
ROSTER_REGISTERED_EVENT = "z4.roster.specialist_registered"


class _RosterRoutesMixin:
    """Provides /api/roster (+ /{department}), /register, /unregister."""

    def _register_roster_routes(self, app: web.Application) -> None:
        app.router.add_get("/api/roster", self._handle_roster_list)
        app.router.add_get(
            "/api/roster/{department}", self._handle_roster_list_dept
        )
        app.router.add_post(
            "/api/roster/register", self._handle_roster_register
        )
        app.router.add_post(
            "/api/roster/unregister", self._handle_roster_unregister
        )

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------

    def _roster_store(self):
        """Return the wired ``RosterRegistryStore`` or None."""
        return getattr(self._bridge, "_roster_registry", None)

    @staticmethod
    def _specialist_dict(spec) -> dict:
        return {
            "department": spec.department,
            "name": spec.name,
            "agent_ref": spec.agent_ref,
            "registered_at": spec.registered_at,
            "registered_by": spec.registered_by,
        }

    def _resolve_event_bus(self):
        """Return the live ``EventBus`` (or None) via the autonomy layer.

        Same resolution the chief-sessions routes use — the bus hangs off
        ``BridgeApp._autonomy.event_bus``; degrade gracefully when unwired.
        """
        autonomy = getattr(self._bridge, "_autonomy", None)
        if autonomy is None:
            return None
        return getattr(autonomy, "event_bus", None)

    # ------------------------------------------------------------------
    # reads
    # ------------------------------------------------------------------

    async def _handle_roster_list(self, request: web.Request) -> web.Response:
        """List all registered specialists across departments."""
        store = self._roster_store()
        if store is None:
            return _ok({"specialists": [], "count": 0})
        try:
            specialists = store.list_all()
            return _ok({
                "specialists": [
                    self._specialist_dict(s) for s in specialists
                ],
                "count": len(specialists),
            })
        except Exception as e:  # noqa: BLE001
            return _error(str(e), 500)

    async def _handle_roster_list_dept(
        self, request: web.Request
    ) -> web.Response:
        """List the registered overlay for one department."""
        department = request.match_info.get("department", "")
        store = self._roster_store()
        if store is None:
            return _ok(
                {"department": department, "specialists": [], "count": 0}
            )
        try:
            specialists = store.list_for_department(department)
            return _ok({
                "department": department,
                "specialists": [
                    self._specialist_dict(s) for s in specialists
                ],
                "count": len(specialists),
            })
        except Exception as e:  # noqa: BLE001
            return _error(str(e), 500)

    # ------------------------------------------------------------------
    # writes
    # ------------------------------------------------------------------

    async def _handle_roster_register(
        self, request: web.Request
    ) -> web.Response:
        """Validate + register a specialist.

        Validation failures (unknown dept, unresolvable agent_ref, duplicate,
        shadowed built-in) surface as 400 carrying the store's error — never a
        500. Missing JSON fields are rejected before the store is consulted.
        """
        try:
            body = await request.json()
        except (json.JSONDecodeError, Exception):
            return _error("Invalid JSON body")
        department = body.get("department", "")
        name = body.get("name", "")
        agent_ref = body.get("agent_ref", "")
        if not department or not name or not agent_ref:
            return _error(
                "'department', 'name', and 'agent_ref' are required"
            )

        store = self._roster_store()
        if store is None:
            return _error("Roster registry not available", 503)

        result = store.register(department, name, agent_ref)
        if not result.ok:
            return _error(result.error or "registration rejected", 400)

        spec = result.specialist
        self._emit_registered_event(spec)
        return _ok({"registered": True, "specialist": self._specialist_dict(spec)})

    async def _handle_roster_unregister(
        self, request: web.Request
    ) -> web.Response:
        """Remove a registered specialist (404 if absent)."""
        try:
            body = await request.json()
        except (json.JSONDecodeError, Exception):
            return _error("Invalid JSON body")
        department = body.get("department", "")
        name = body.get("name", "")
        if not department or not name:
            return _error("'department' and 'name' are required")

        store = self._roster_store()
        if store is None:
            return _error("Roster registry not available", 503)

        removed = store.unregister(department, name)
        if not removed:
            return _error(
                f"specialist {name!r} not registered in department "
                f"{department!r}",
                404,
            )
        return _ok({"unregistered": name, "department": department})

    # ------------------------------------------------------------------
    # event
    # ------------------------------------------------------------------

    def _emit_registered_event(self, spec) -> None:
        """Publish ``z4.roster.specialist_registered`` best-effort."""
        bus = self._resolve_event_bus()
        if bus is None:
            return
        try:
            bus.publish(
                ROSTER_REGISTERED_EVENT,
                {
                    "department": spec.department,
                    "name": spec.name,
                    "agent_ref": spec.agent_ref,
                    "registered_by": spec.registered_by,
                },
                source="api.routes_roster",
            )
        except Exception:  # noqa: BLE001 — never let event publish break the write
            pass
