"""Zone 4 VAPI department routes (Sprint P6.2 split).

Pure reorg from ``bridge.api_server``. Includes the VAPI webhook
endpoint at /api/v1/voice/webhook (route registered here, handler also
referenced from routes_webhooks via mixin inheritance).
"""
from __future__ import annotations

from aiohttp import web


class _VapiDepartmentsRoutesMixin:
    """Provides /api/v1/departments/* + /api/v1/voice/webhook handlers."""

    def _register_vapi_departments_routes(self, app: web.Application) -> None:
        app.router.add_get("/api/v1/departments", self._list_departments)
        app.router.add_get("/api/v1/departments/{dept}", self._get_department)
        app.router.add_post(
            "/api/v1/departments/{dept}/chat/completions",
            self._department_chat_completions,
        )

        # D1.7b — VAPI inbound webhook (handler defined in routes_webhooks
        # mixin; route registered here because it's part of the VAPI surface).
        app.router.add_post("/api/v1/voice/webhook", self._handle_vapi_webhook)

    # ------------------------------------------------------------------
    # Zone 4 VAPI department routes
    # ------------------------------------------------------------------

    async def _list_departments(self, request: web.Request) -> web.Response:
        """List all departments registered in the DepartmentRegistry."""
        if self._departments is None:
            return web.json_response({"departments": []})
        return web.json_response({"departments": self._departments.department_names()})

    async def _get_department(self, request: web.Request) -> web.Response:
        """Return metadata for a single department."""
        dept = request.match_info["dept"]
        if self._departments is None:
            return web.json_response({"error": "departments not wired"}, status=503)
        try:
            cfg = self._departments.get_config(dept)
        except KeyError:
            return web.json_response({"error": f"unknown department: {dept}"}, status=404)
        return web.json_response({
            "name": cfg.name,
            "zone": cfg.zone,
            "description": str(cfg.description),
            "vapi_enabled": bool(cfg.vapi and cfg.vapi.enabled),
            "employees": [e.name for e in cfg.employees],
        })

    async def _department_chat_completions(self, request: web.Request) -> web.StreamResponse:
        """OpenAI-compatible SSE chat completion endpoint for a department.

        VAPI sends standard OpenAI-format chat requests here.
        Route is gated by cfg.vapi.enabled.
        """
        import uuid as _uuid
        from teams._vapi import parse_openai_request, stream_department_as_sse
        from teams._types import BridgeDeps

        dept = request.match_info["dept"]
        if self._departments is None:
            return web.json_response({"error": "departments not wired"}, status=503)

        try:
            body = await request.json()
            user_msg = parse_openai_request(body)
        except Exception as e:
            return web.json_response({"error": str(e)}, status=400)

        try:
            cfg = self._departments.get_config(dept)
        except KeyError:
            return web.json_response({"error": f"unknown department: {dept}"}, status=404)

        if not (cfg.vapi and cfg.vapi.enabled):
            return web.json_response(
                {"error": f"VAPI not enabled for {dept}"}, status=403,
            )

        # Sprint 04.12: site 4-of-4 BridgeDeps direct-construction migration.
        # Use BridgeDeps.from_app so future field additions on BridgeDeps
        # don't silently leave VAPI voice calls with unset attributes.
        # Closes #610 once 04.09/10/11 also land.
        deps = BridgeDeps.from_app(
            self._bridge,
            session_id=f"vapi-{_uuid.uuid4().hex[:12]}",
            department=dept,
        )

        resp = web.StreamResponse(
            status=200,
            headers={
                "Content-Type": "text/event-stream",
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
            },
        )
        await resp.prepare(request)

        async for chunk in stream_department_as_sse(self._departments, dept, user_msg, deps):
            await resp.write(chunk.encode("utf-8"))

        await resp.write_eof()
        return resp
