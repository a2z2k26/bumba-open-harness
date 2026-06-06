"""Tests for the _WorkflowRoutesMixin REST surface (WS3.5).

Covers the five workflow-run routes:
  - GET  /api/workflows                      list defs
  - POST /api/workflows/{name}/start         trigger -> {run_id}
  - GET  /api/workflows/runs                 list_all_runs
  - GET  /api/workflows/runs/{run_id}        live engine state + store fallback
  - POST /api/workflows/runs/{run_id}/cancel cancel run

Mirrors the aiohttp TestServer pattern used in test_api_cost.py.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from bridge.api_server import (
    APIServer,
    cors_middleware,
    create_auth_middleware,
)

pytestmark = pytest.mark.socket  # binds localhost sockets via aiohttp TestServer

API_TOKEN = "test-token-workflows"


def _make_bridge():
    bridge = MagicMock()
    bridge._config = MagicMock()
    bridge._config.data_dir = "/tmp/test-data"
    bridge._config.operator_discord_id = "test-op"
    bridge._db = AsyncMock()
    bridge._health_server = None
    bridge._tmux_agents = None
    bridge._session_mgr = None
    bridge._cost_tracker = None
    bridge._autonomy = None
    bridge._memory = None
    bridge._commands = None
    bridge._metrics = None
    bridge._tracer = None
    bridge._task_queue = None
    bridge._task_pipeline = None
    bridge._quality_gate = None
    bridge._webhook_receiver = None
    bridge._workflow_registry = None
    bridge._workflow_engine = None
    bridge._workorder_store = None
    return bridge


async def _create_client(bridge):
    server = APIServer(bridge, api_token=API_TOKEN)
    app = web.Application(
        middlewares=[
            cors_middleware,
            create_auth_middleware(server._api_token),
        ]
    )
    server._register_routes(app)
    ts = TestServer(app)
    client = TestClient(ts)
    await client.start_server()
    return client


def _auth():
    return {"Authorization": f"Bearer {API_TOKEN}"}


# ---------------------------------------------------------------------------
# POST /api/workflows/{name}/start
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_start_returns_run_id():
    bridge = _make_bridge()
    registry = MagicMock()
    registry.trigger.return_value = "wfrun-abc123"
    engine = MagicMock()
    bridge._workflow_registry = registry
    bridge._workflow_engine = engine

    client = await _create_client(bridge)
    try:
        resp = await client.post(
            "/api/workflows/design.audit/start",
            json={"inputs": {"target": "x"}},
            headers=_auth(),
        )
        assert resp.status == 200
        body = await resp.json()
        assert body["run_id"] == "wfrun-abc123"
        registry.trigger.assert_called_once()
        # name is the path param; engine is passed through
        _args, kwargs = registry.trigger.call_args
        assert kwargs.get("engine") is engine
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_start_no_engine_returns_503():
    bridge = _make_bridge()
    registry = MagicMock()
    registry.trigger.return_value = None  # no engine attached -> None
    bridge._workflow_registry = registry
    bridge._workflow_engine = None

    client = await _create_client(bridge)
    try:
        resp = await client.post(
            "/api/workflows/design.audit/start",
            json={},
            headers=_auth(),
        )
        assert resp.status == 503
        body = await resp.json()
        assert "error" in body
        assert "run_id" not in body
    finally:
        await client.close()


# ---------------------------------------------------------------------------
# GET /api/workflows/runs/{run_id}
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_run_status_live():
    bridge = _make_bridge()
    engine = MagicMock()
    state = MagicMock()
    state.run_id = "wfrun-live"
    state.workflow_name = "design.audit"
    state.status = "running"
    state.current_step = "step1"
    state.context = {"k": "v"}
    state.cost_usd = 1.25
    state.created_at = "2026-06-02T00:00:00+00:00"
    state.completed_at = None
    engine.get_run_state.return_value = state
    bridge._workflow_engine = engine

    client = await _create_client(bridge)
    try:
        resp = await client.get(
            "/api/workflows/runs/wfrun-live", headers=_auth()
        )
        assert resp.status == 200
        body = await resp.json()
        assert body["id"] == "wfrun-live"
        assert body["status"] == "running"
        assert body["source"] == "engine"
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_get_run_status_falls_back_to_store():
    bridge = _make_bridge()
    engine = MagicMock()
    engine.get_run_state.return_value = None  # not in memory (post-restart)
    bridge._workflow_engine = engine

    store = MagicMock()
    persisted = MagicMock()
    persisted.id = "wfrun-old"
    persisted.workflow_name = "design.audit"
    persisted.status = "completed"
    persisted.current_step = None
    persisted.context = {}
    persisted.cost_usd = 0.5
    persisted.created_at = "2026-06-01T00:00:00+00:00"
    persisted.completed_at = "2026-06-01T00:05:00+00:00"
    store.get_workflow_run.return_value = persisted
    bridge._workorder_store = store

    client = await _create_client(bridge)
    try:
        resp = await client.get(
            "/api/workflows/runs/wfrun-old", headers=_auth()
        )
        assert resp.status == 200
        body = await resp.json()
        assert body["id"] == "wfrun-old"
        assert body["status"] == "completed"
        assert body["source"] == "store"
        store.get_workflow_run.assert_called_once_with("wfrun-old")
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_get_run_status_404_when_both_miss():
    bridge = _make_bridge()
    engine = MagicMock()
    engine.get_run_state.return_value = None
    bridge._workflow_engine = engine
    store = MagicMock()
    store.get_workflow_run.return_value = None
    bridge._workorder_store = store

    client = await _create_client(bridge)
    try:
        resp = await client.get(
            "/api/workflows/runs/nope", headers=_auth()
        )
        assert resp.status == 404
    finally:
        await client.close()


# ---------------------------------------------------------------------------
# POST /api/workflows/runs/{run_id}/cancel
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cancel_run():
    bridge = _make_bridge()
    engine = MagicMock()
    engine.cancel = AsyncMock(return_value=True)
    bridge._workflow_engine = engine

    client = await _create_client(bridge)
    try:
        resp = await client.post(
            "/api/workflows/runs/wfrun-x/cancel", headers=_auth()
        )
        assert resp.status == 200
        body = await resp.json()
        assert body["cancelled"] is True
        engine.cancel.assert_awaited_once_with("wfrun-x")
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_cancel_run_no_engine_503():
    bridge = _make_bridge()
    bridge._workflow_engine = None

    client = await _create_client(bridge)
    try:
        resp = await client.post(
            "/api/workflows/runs/wfrun-x/cancel", headers=_auth()
        )
        assert resp.status == 503
    finally:
        await client.close()


# ---------------------------------------------------------------------------
# GET /api/workflows  +  GET /api/workflows/runs
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_workflow_defs():
    bridge = _make_bridge()
    registry = MagicMock()
    registry.list.return_value = [{"name": "design.audit", "trigger": "explicit"}]
    bridge._workflow_registry = registry

    client = await _create_client(bridge)
    try:
        resp = await client.get("/api/workflows", headers=_auth())
        assert resp.status == 200
        body = await resp.json()
        assert body["workflows"][0]["name"] == "design.audit"
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_list_all_runs():
    bridge = _make_bridge()
    store = MagicMock()
    run = MagicMock()
    run.id = "wfrun-1"
    run.workflow_name = "design.audit"
    run.status = "completed"
    run.current_step = None
    run.context = {}
    run.cost_usd = 0.1
    run.created_at = "2026-06-01T00:00:00+00:00"
    run.completed_at = "2026-06-01T00:01:00+00:00"
    store.list_all_runs.return_value = [run]
    bridge._workorder_store = store

    client = await _create_client(bridge)
    try:
        resp = await client.get("/api/workflows/runs", headers=_auth())
        assert resp.status == 200
        body = await resp.json()
        assert body["runs"][0]["id"] == "wfrun-1"
    finally:
        await client.close()


# ---------------------------------------------------------------------------
# API index parity
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_routes_in_api_index():
    bridge = _make_bridge()
    client = await _create_client(bridge)
    try:
        resp = await client.get("/api", headers=_auth())
        assert resp.status == 200
        body = await resp.json()
        paths = {r["path"] for r in body["routes"]}
        assert "/api/workflows" in paths
        assert "/api/workflows/{name}/start" in paths
        assert "/api/workflows/runs" in paths
        assert "/api/workflows/runs/{run_id}" in paths
        assert "/api/workflows/runs/{run_id}/cancel" in paths
    finally:
        await client.close()
