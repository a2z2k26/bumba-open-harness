"""HITL (human-in-the-loop) routes (Sprint P6.2 split).

Pure reorg from ``bridge.api_server``.
"""
from __future__ import annotations

import json

from aiohttp import web

from ._helpers import _error, _ok


class _HitlRoutesMixin:
    """Provides /api/hitl/* handlers (Phase 7)."""

    def _register_hitl_routes(self, app: web.Application) -> None:
        app.router.add_get("/api/hitl/pending", self._handle_hitl_pending)
        app.router.add_post(
            "/api/hitl/{task_id}/respond", self._handle_hitl_respond
        )

    # ------------------------------------------------------------------
    # HITL (Phase 7)
    # ------------------------------------------------------------------

    async def _handle_hitl_pending(
        self, request: web.Request
    ) -> web.Response:
        """List pending HITL tasks."""
        task_queue = self._bridge._task_queue
        if task_queue is None:
            return _ok({"pending": []})
        try:
            db = self._bridge._db
            if db is None:
                return _error("Database not available", 503)
            rows = await db.fetchall(
                "SELECT * FROM async_tasks WHERE status = 'needs_input' "
                "ORDER BY created_at DESC LIMIT 50"
            )
            pending = []
            for row in rows:
                options = None
                if row[6]:
                    try:
                        options = json.loads(row[6])
                    except json.JSONDecodeError:
                        pass
                pending.append({
                    "id": row[0],
                    "status": row[1],
                    "question": row[5],
                    "options": options,
                    "chat_id": row[9],
                    "created_at": row[10],
                })
            return _ok({"pending": pending, "count": len(pending)})
        except Exception as e:
            return _error(str(e), 500)

    async def _handle_hitl_respond(
        self, request: web.Request
    ) -> web.Response:
        """Submit a response to a HITL task."""
        task_id = int(request.match_info["task_id"])
        task_queue = self._bridge._task_queue
        if task_queue is None:
            return _error("Task queue not available", 503)
        try:
            body = await request.json()
        except (json.JSONDecodeError, Exception):
            return _error("Invalid JSON body")
        response = body.get("response", "")
        if not response:
            return _error("'response' field is required")
        try:
            task = await task_queue.get(task_id)
            if task is None:
                return _error(f"Task {task_id} not found", 404)
            if task.status != "needs_input":
                return _error(
                    f"Task {task_id} is not pending input (status: {task.status})",
                    409,
                )
            await task_queue.submit_response(task_id, response)
            return _ok({"id": task_id, "status": "responded"})
        except Exception as e:
            return _error(str(e), 500)
