"""WorkOrder routes (Sprint P6.2 split).

Pure reorg from ``bridge.api_server``. The S12 WorkOrder public API
endpoints — create + get + WS stream — plus the Z4-S23 ChiefDispatcher
dispatch block. Behavioral guarantee: byte-for-byte identical to the
pre-split implementation.
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from aiohttp import web

from ._helpers import _error

logger = logging.getLogger(__name__)


class _WorkordersRoutesMixin:
    """Provides /api/workorders/* + /ws/workorders/{wo_id} handlers."""

    def _register_workorders_routes(self, app: web.Application) -> None:
        # S12 — WorkOrder Public API
        app.router.add_post("/api/workorders", self._handle_create_workorder)
        app.router.add_get("/api/workorders/{wo_id}", self._handle_get_workorder)
        app.router.add_get("/ws/workorders/{wo_id}", self._handle_ws_workorder)
        # Sprint S3.2 (Backend Operability, #2283) — executor routability
        # surface. Lives next to the WO routes because it answers "which
        # executor lanes will accept the WorkOrder I'm about to POST?"
        app.router.add_get(
            "/api/executors/status", self._handle_get_executor_status
        )

    # ------------------------------------------------------------------
    # S12 — WorkOrder Public API
    # ------------------------------------------------------------------

    async def _handle_create_workorder(self, request: web.Request) -> web.Response:
        """POST /api/workorders — create a WorkOrder from external spec.

        Required fields: intent, skill, project.
        Optional: output_schema, constraints, idempotency_key, trigger_source,
        department_target, department (Z4-S23 #1396 — alias accepted as
        ``department_hint`` for spec compatibility).

        Z4-S23 (#1396) extension: when ``department`` (or its alias
        ``department_hint``) is supplied OR when the bridge is configured
        with ``chief_dispatcher_enabled=true`` AND a ``ChiefDispatcher`` is
        wired on the BridgeApp, the freshly-created WorkOrder is routed
        through the chief-session dispatcher. The response then includes
        ``chief_session_id`` (and ``chief_session_state``, ``department``)
        alongside the existing fields. When neither condition holds, the
        endpoint preserves its pre-Z4-S23 behaviour exactly.

        Returns: { workorder_id, ws_url, status, workorder,
        [chief_session_id], [chief_session_state], [department] }
        """
        try:
            body = await request.json()
        except Exception:
            return _error("Invalid JSON body", 400)

        required = ["intent", "skill", "project"]
        missing = [k for k in required if not body.get(k)]
        if missing:
            return _error(f"Missing required fields: {missing}", 400)

        # Z4-S23 (#1396) — optional dispatch hint. Accept both "department"
        # (task brief) and "department_hint" (issue spec text); the brief
        # wins if both are present so callers can stage migrations without
        # breaking.
        department_hint_raw = body.get("department")
        if department_hint_raw is None:
            department_hint_raw = body.get("department_hint")
        department_hint = (
            str(department_hint_raw).strip() if department_hint_raw else None
        ) or None

        try:
            from bridge.work_order import WorkOrder
            from dataclasses import replace as dc_replace

            wo = WorkOrder.create(
                intent=body["intent"],
                skill=body["skill"],
                project=body["project"],
            )
            # Apply optional fields
            idempotency_key = body.get("idempotency_key")
            trigger_source = body.get("trigger_source", "webhook")
            wo = dc_replace(
                wo,
                idempotency_key=idempotency_key,
                trigger_source=trigger_source,
            )
            if body.get("output_schema"):
                wo = dc_replace(wo, output_schema=body["output_schema"])

            # Sprint 03.04 — plumb department_target. Precedence: an
            # explicit body field beats automatic derivation. Falls back
            # to environment_selector._derive_department(skill) when the
            # caller didn't supply a value, so external WorkOrders for
            # department-class skills can reach DepartmentExecutor with a
            # resolvable target. No-op for filesystem/readonly skills.
            #
            # Z4-S23 — the new ``department`` (alias ``department_hint``)
            # field outranks the legacy ``department_target`` so
            # dispatch-driven calls don't have to also send the legacy
            # name. Skill-derived fallback still applies last.
            from bridge.environment_selector import _derive_department
            explicit_dept = department_hint or body.get("department_target")
            if explicit_dept:
                wo = wo.with_department(str(explicit_dept))
            else:
                derived_dept = _derive_department(body["skill"])
                if derived_dept is not None:
                    wo = wo.with_department(derived_dept)

        except Exception as exc:
            logger.exception("Failed to create WorkOrder from API request")
            return _error(f"WorkOrder creation failed: {exc}", 500)

        # Persist if store is available
        wo_store = getattr(self._bridge, "_workorder_store", None)
        if wo_store is not None:
            try:
                wo_store.save(wo)
            except Exception:
                logger.warning("Failed to persist WorkOrder %s", wo.id[:8])

        ws_url = f"/ws/workorders/{wo.id}"
        response_body: dict[str, Any] = {
            "workorder_id": wo.id,
            "ws_url": ws_url,
            "status": wo.status.value,
            "workorder": wo.to_dict(),
        }

        # ------------------------------------------------------------------
        # Z4-S23 (#1396) — optional ChiefDispatcher dispatch.
        # ------------------------------------------------------------------
        # Trigger conditions:
        #   1. ``department`` was supplied AND a dispatcher is wired
        #      (best path — operator-driven explicit routing).
        #   2. ``department`` was absent AND
        #      ``chief_dispatcher_enabled=true`` AND a dispatcher is wired
        #      (the dispatcher fires for every WO once the flag is on, so
        #      the rule-based router gets to use Tier 2/3/4).
        #
        # Pre-Z4-S23 behaviour is preserved when neither condition holds
        # (returns ``workorder_id`` + ``ws_url`` only — no chief fields).
        # When ``department`` is supplied but the dispatcher is unwired
        # or disabled, return 503 — callers explicitly asked for dispatch
        # and the bridge can't honour it.
        bridge_cfg = getattr(self._bridge, "_config", None)
        chief_flag_on = bool(
            getattr(bridge_cfg, "chief_dispatcher_enabled", False)
        )
        dispatcher = getattr(self._bridge, "_chief_dispatcher", None)

        should_dispatch = dispatcher is not None and (
            department_hint is not None or chief_flag_on
        )

        if department_hint is not None and (
            dispatcher is None or not chief_flag_on
        ):
            return web.json_response(
                {
                    "error": "chief_dispatcher_unavailable",
                    "hint": (
                        "department was specified but chief_dispatcher_enabled "
                        "is false or no ChiefDispatcher is wired; either "
                        "remove the department field or enable the dispatcher"
                    ),
                    "workorder_id": wo.id,
                },
                status=503,
            )

        if should_dispatch:
            try:
                from bridge.work_order_router import RoutingError
                from teams._types import BridgeDeps
                import uuid as _uuid

                deps = BridgeDeps.from_app(
                    self._bridge,
                    session_id=f"dispatch-{_uuid.uuid4().hex[:12]}",
                    department=department_hint or "",
                )
                session = await dispatcher.dispatch(wo, deps)
            except RoutingError as exc:
                return web.json_response(
                    {
                        "error": "routing_error",
                        "reason": exc.reason,
                        "workorder_id": wo.id,
                    },
                    status=422,
                )
            except Exception as exc:
                logger.exception(
                    "ChiefDispatcher.dispatch raised for WO %s", wo.id[:8]
                )
                return _error(f"Dispatch failed: {exc}", 500)

            response_body["chief_session_id"] = session.session_id
            # ``state`` is a ChiefSessionState enum; surface its string value.
            response_body["chief_session_state"] = (
                session.state.value
                if hasattr(session.state, "value")
                else str(session.state)
            )
            response_body["department"] = session.department

        return web.json_response(response_body, status=201)

    # NOTE: requires Plan 03 sprint to set self._bridge._workorder_store before
    # this route resolves. Sprint 03.06 (PR #890) shipped the setters; if you
    # see 503 here, check _initialize() didn't error.
    async def _handle_get_workorder(self, request: web.Request) -> web.Response:
        """GET /api/workorders/{wo_id} — retrieve WorkOrder state."""
        wo_id = request.match_info.get("wo_id", "")
        if not wo_id:
            return _error("Missing wo_id", 400)

        wo_store = getattr(self._bridge, "_workorder_store", None)
        if wo_store is None:
            return web.json_response(
                {
                    "error": "workorder_store_not_initialized",
                    "hint": (
                        "Plan 03 dispatcher wiring is required; verify "
                        "_initialize() ran successfully"
                    ),
                },
                status=503,
            )

        try:
            wo = wo_store.get(wo_id)
            if wo is None:
                wo = wo_store.find_by_idempotency_key(wo_id)
        except Exception as exc:
            return _error(f"Store error: {exc}", 500)

        if wo is None:
            return _error(f"WorkOrder {wo_id!r} not found", 404)

        return web.json_response(wo.to_dict())

    async def _handle_ws_workorder(self, request: web.Request) -> web.WebSocketResponse:
        """GET /ws/workorders/{wo_id} — WebSocket stream for WO state transitions."""
        wo_id = request.match_info.get("wo_id", "")
        if not wo_id:
            return web.Response(status=400, text="Missing wo_id")  # type: ignore[return-value]

        ws = web.WebSocketResponse(heartbeat=30.0)
        await ws.prepare(request)

        stream_mgr = getattr(self._bridge, "_workorder_stream", None)
        if stream_mgr is None:
            await ws.send_str(json.dumps({
                "event": "error",
                "data": {
                    "error": "workorder_stream_not_initialized",
                    "hint": (
                        "Plan 03 dispatcher wiring is required; verify "
                        "_initialize() ran successfully"
                    ),
                },
            }))
            await ws.close()
            return ws

        q = stream_mgr.subscribe(wo_id)
        try:
            # Send current state immediately if available
            wo_store = getattr(self._bridge, "_workorder_store", None)
            if wo_store is not None:
                try:
                    wo = wo_store.get(wo_id)
                    if wo:
                        await ws.send_str(json.dumps({
                            "event": "workorder.current",
                            "data": wo.to_dict(),
                        }))
                except Exception:
                    pass

            # Forward stream events to the WS until the client closes.
            # Sprint 07.03: previously the handler only iterated `async for
            # msg in ws` (draining incoming client frames) and never read
            # from `q`, so subscribers received nothing. Fan events from
            # the queue out to the socket explicitly, and let either
            # client-close or socket-error tear the connection down.
            async def _drain_queue() -> None:
                while not ws.closed:
                    msg = await q.get()
                    if ws.closed:
                        return
                    await ws.send_str(json.dumps(msg))

            async def _read_client() -> None:
                async for _msg in ws:
                    # Read-only stream — discard inbound frames.
                    pass

            drain_task = asyncio.create_task(_drain_queue())
            read_task = asyncio.create_task(_read_client())
            try:
                done, pending = await asyncio.wait(
                    {drain_task, read_task},
                    return_when=asyncio.FIRST_COMPLETED,
                )
                for t in pending:
                    t.cancel()
                # Surface any exception raised by the completed task.
                for t in done:
                    exc = t.exception()
                    if exc is not None:
                        raise exc
            finally:
                for t in (drain_task, read_task):
                    if not t.done():
                        t.cancel()

        except Exception:
            logger.exception("WorkOrder WS error for WO %s", wo_id[:8])
        finally:
            stream_mgr.unsubscribe(wo_id, q)

        return ws

    # ------------------------------------------------------------------
    # S3.2 (Backend Operability, #2283) — executor status surface
    # ------------------------------------------------------------------

    async def _handle_get_executor_status(
        self, request: web.Request
    ) -> web.Response:
        """GET /api/executors/status — per-executor activation + routability.

        Returns ``{"executors": {<name>: {"status": str, "routable": bool}}}``
        with one entry per executor known to the dispatcher (subagent,
        department, worktree, e2b, tmux). The ``routable`` flag is the
        single predicate the dispatcher uses to admit explicit assignments
        — so operators can see at a glance which lanes will accept a
        WorkOrder right now and which (``stub``, ``conditional_unwired``)
        will be rejected at validate-time.

        Returns 503 when the dispatcher is not wired (zone-3 disabled).
        """
        dispatcher = getattr(self._bridge, "_dispatcher", None)
        if dispatcher is None:
            return web.json_response(
                {
                    "error": "dispatcher_not_wired",
                    "hint": (
                        "dispatcher_enabled is false or _initialize() has "
                        "not constructed the Dispatcher; executor status "
                        "is unavailable"
                    ),
                },
                status=503,
            )

        try:
            payload = dispatcher.get_executor_status_payload()
        except Exception as exc:  # noqa: BLE001
            logger.exception("Failed to render executor status payload")
            return _error(f"Executor status error: {exc}", 500)

        return web.json_response({"executors": payload})
