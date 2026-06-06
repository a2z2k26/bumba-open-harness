"""Task pipeline routes (Sprint P6.2 split).

Pure reorg from ``bridge.api_server``.
"""
from __future__ import annotations

import json

from aiohttp import web

from ._helpers import _error, _ok


class _TasksRoutesMixin:
    """Provides /api/tasks/* handlers (Phase 3 Kanban pipeline)."""

    def _register_tasks_routes(self, app: web.Application) -> None:
        app.router.add_get("/api/tasks", self._handle_list_tasks)
        app.router.add_get("/api/tasks/{task_id}", self._handle_get_task)
        app.router.add_post("/api/tasks", self._handle_create_task)
        app.router.add_put(
            "/api/tasks/{task_id}/status", self._handle_move_task
        )
        app.router.add_put(
            "/api/tasks/{task_id}/move", self._handle_move_task
        )
        app.router.add_put(
            "/api/tasks/{task_id}/assign", self._handle_assign_task
        )

    # ------------------------------------------------------------------
    # Tasks (Phase 3 — stubs, replaced by task_pipeline module)
    # ------------------------------------------------------------------

    async def _handle_list_tasks(self, request: web.Request) -> web.Response:
        """List tasks from the pipeline."""
        pipeline = getattr(self._bridge, "_task_pipeline", None)
        if pipeline is None:
            return _error("Task pipeline not initialized", 503)
        try:
            status_filter = request.query.get("status")
            tasks = await pipeline.list_tasks(status=status_filter)
            summary = await pipeline.get_pipeline_summary()
            return _ok({"tasks": tasks, "summary": summary})
        except Exception as e:
            return _error(str(e), 500)

    async def _handle_get_task(self, request: web.Request) -> web.Response:
        """Get a task by ID."""
        task_id = int(request.match_info["task_id"])
        pipeline = getattr(self._bridge, "_task_pipeline", None)
        if pipeline is None:
            return _error("Task pipeline not initialized", 503)
        try:
            task = await pipeline.get_task(task_id)
            if task is None:
                return _error(f"Task {task_id} not found", 404)
            return _ok(task)
        except Exception as e:
            return _error(str(e), 500)

    async def _handle_create_task(self, request: web.Request) -> web.Response:
        """Create a new task."""
        pipeline = getattr(self._bridge, "_task_pipeline", None)
        if pipeline is None:
            return _error("Task pipeline not initialized", 503)
        try:
            body = await request.json()
        except (json.JSONDecodeError, Exception):
            return _error("Invalid JSON body")
        title = body.get("title", "")
        if not title:
            return _error("'title' field is required")
        try:
            task_id = await pipeline.create_task(
                title=title,
                description=body.get("description", ""),
                priority=body.get("priority", "medium"),
                assigned_to=body.get("assigned_to"),
                source=body.get("source", "api"),
            )
            return _ok({"id": task_id, "title": title}, status=201)
        except Exception as e:
            return _error(str(e), 500)

    async def _handle_move_task(self, request: web.Request) -> web.Response:
        """Move a task to a new status."""
        task_id = int(request.match_info["task_id"])
        pipeline = getattr(self._bridge, "_task_pipeline", None)
        if pipeline is None:
            return _error("Task pipeline not initialized", 503)
        try:
            body = await request.json()
        except (json.JSONDecodeError, Exception):
            return _error("Invalid JSON body")
        new_status = body.get("status", "")
        if not new_status:
            return _error("'status' field is required")
        try:
            moved = await pipeline.move_task(task_id, new_status)
            if not moved:
                return _error(f"Invalid transition for task {task_id}", 422)
            return _ok({"id": task_id, "status": new_status})
        except ValueError as e:
            return _error(str(e), 422)
        except Exception as e:
            return _error(str(e), 500)

    async def _handle_assign_task(self, request: web.Request) -> web.Response:
        """Assign a task to an agent."""
        task_id = int(request.match_info["task_id"])
        pipeline = getattr(self._bridge, "_task_pipeline", None)
        if pipeline is None:
            return _error("Task pipeline not initialized", 503)
        try:
            body = await request.json()
        except (json.JSONDecodeError, Exception):
            return _error("Invalid JSON body")
        assigned_to = body.get("assigned_to", "")
        if not assigned_to:
            return _error("'assigned_to' field is required")
        try:
            assigned = await pipeline.assign_task(task_id, assigned_to)
            if not assigned:
                return _error(f"Task {task_id} not found", 404)
            return _ok({"id": task_id, "assigned_to": assigned_to})
        except Exception as e:
            return _error(str(e), 500)
