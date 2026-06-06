"""Workflow-run REST surface (WS3.5, Refs #2570).

Exposes the operator-facing view + control plane for Zone 4 Layer 2
workflow runs. Handlers read three subsystems off ``self._bridge``:

- ``_workflow_registry`` — ``WorkflowRegistry`` (list defs, trigger by name)
- ``_workflow_engine``   — ``WorkflowEngine`` (live run state, cancel)
- ``_workorder_store``   — ``WorkOrderStore`` (durable run rows)

Live run state lives in-memory on the engine and is lost across a bridge
restart; ``GET /api/workflows/runs/{run_id}`` therefore falls back to the
persisted row when the engine has no in-memory state.
"""
from __future__ import annotations

import json
from typing import Any

from aiohttp import web

from ._helpers import _error, _ok


def _serialize_engine_state(state: Any) -> dict[str, Any]:
    """Render a ``WorkflowRunState`` into the canonical run dict."""
    return {
        "id": state.run_id,
        "workflow_name": state.workflow_name,
        "status": state.status,
        "current_step": state.current_step,
        "context": state.context,
        "cost_usd": state.cost_usd,
        "created_at": state.created_at,
        "completed_at": state.completed_at,
        "source": "engine",
    }


def _serialize_store_run(run: Any) -> dict[str, Any]:
    """Render a persisted ``WorkflowRun`` into the canonical run dict."""
    return {
        "id": run.id,
        "workflow_name": run.workflow_name,
        "status": run.status,
        "current_step": run.current_step,
        "context": run.context,
        "cost_usd": run.cost_usd,
        "created_at": run.created_at,
        "completed_at": run.completed_at,
        "source": "store",
    }


class _WorkflowRoutesMixin:
    """Provides /api/workflows and /api/workflows/runs/* handlers."""

    def _register_workflows_routes(self, app: web.Application) -> None:
        app.router.add_get("/api/workflows", self._handle_list_workflows)
        app.router.add_post(
            "/api/workflows/{name}/start", self._handle_start_workflow
        )
        app.router.add_get(
            "/api/workflows/runs", self._handle_list_workflow_runs
        )
        app.router.add_get(
            "/api/workflows/runs/{run_id}", self._handle_get_workflow_run
        )
        app.router.add_post(
            "/api/workflows/runs/{run_id}/cancel",
            self._handle_cancel_workflow_run,
        )

    # ------------------------------------------------------------------
    # Definitions
    # ------------------------------------------------------------------

    async def _handle_list_workflows(
        self, request: web.Request
    ) -> web.Response:
        """List all loaded workflow definitions."""
        registry = self._bridge._workflow_registry
        if registry is None:
            return _ok({"workflows": []})
        try:
            return _ok({"workflows": registry.list()})
        except Exception as e:  # noqa: BLE001
            return _error(str(e), 500)

    async def _handle_start_workflow(
        self, request: web.Request
    ) -> web.Response:
        """Trigger a workflow by name. Returns ``{run_id}`` on success.

        Returns 503 when no engine is attached (``trigger`` returns None) —
        the run never started, so a null run_id must not be reported as a
        success.
        """
        name = request.match_info["name"]
        registry = self._bridge._workflow_registry
        if registry is None:
            return _error("Workflow registry not available", 503)

        try:
            body = await request.json()
        except (json.JSONDecodeError, Exception):  # noqa: BLE001
            body = {}
        inputs = body.get("inputs", {}) if isinstance(body, dict) else {}

        engine = self._bridge._workflow_engine
        try:
            run_id = registry.trigger(name, inputs, engine=engine)
        except KeyError:
            return _error(f"Workflow {name!r} not found", 404)
        except Exception as e:  # noqa: BLE001
            return _error(str(e), 500)

        if run_id is None:
            return _error(
                "Workflow engine not available — run was not started", 503
            )
        return _ok({"run_id": run_id})

    # ------------------------------------------------------------------
    # Runs
    # ------------------------------------------------------------------

    async def _handle_list_workflow_runs(
        self, request: web.Request
    ) -> web.Response:
        """List the most recent runs across all workflows (durable)."""
        store = getattr(self._bridge, "_workorder_store", None)
        if store is None:
            return _ok({"runs": []})
        try:
            status = request.query.get("status")
            runs = store.list_all_runs(status=status)
            return _ok({"runs": [_serialize_store_run(r) for r in runs]})
        except Exception as e:  # noqa: BLE001
            return _error(str(e), 500)

    async def _handle_get_workflow_run(
        self, request: web.Request
    ) -> web.Response:
        """Return a single run — live engine state, else persisted row.

        Engine state is in-memory and lost across restart, so a miss there
        falls back to the durable store. 404 only when both miss.
        """
        run_id = request.match_info["run_id"]

        engine = self._bridge._workflow_engine
        if engine is not None:
            try:
                state = engine.get_run_state(run_id)
            except Exception as e:  # noqa: BLE001
                return _error(str(e), 500)
            if state is not None:
                return _ok(_serialize_engine_state(state))

        store = getattr(self._bridge, "_workorder_store", None)
        if store is not None:
            try:
                run = store.get_workflow_run(run_id)
            except Exception as e:  # noqa: BLE001
                return _error(str(e), 500)
            if run is not None:
                return _ok(_serialize_store_run(run))

        return _error(f"Workflow run {run_id!r} not found", 404)

    async def _handle_cancel_workflow_run(
        self, request: web.Request
    ) -> web.Response:
        """Cancel an active workflow run via the engine."""
        run_id = request.match_info["run_id"]
        engine = self._bridge._workflow_engine
        if engine is None:
            return _error("Workflow engine not available", 503)
        try:
            cancelled = await engine.cancel(run_id)
        except Exception as e:  # noqa: BLE001
            return _error(str(e), 500)
        return _ok({"cancelled": cancelled, "run_id": run_id})
