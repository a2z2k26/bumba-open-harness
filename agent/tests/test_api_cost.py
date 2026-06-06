"""Tests for API cost endpoint (daily/weekly summaries)."""

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

API_TOKEN = "test-token-cost"


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


@pytest.mark.asyncio
class TestCostEndpoint:
    async def test_no_tracker(self):
        bridge = _make_bridge()
        bridge._cost_tracker = None
        client = await _create_client(bridge)
        try:
            resp = await client.get("/api/cost", headers=_auth())
            assert resp.status == 200
            data = await resp.json()
            assert data["daily"] == {}
            assert data["weekly"] == {}
        finally:
            await client.close()

    async def test_cost_endpoint_null_tracker_shape(self):
        bridge = _make_bridge()
        bridge._cost_tracker = None
        client = await _create_client(bridge)
        try:
            resp = await client.get("/api/cost", headers=_auth())
            assert resp.status == 200
            data = await resp.json()
            assert data["by_workflow"] == {}
        finally:
            await client.close()

    async def test_cost_endpoint_includes_by_workflow(self):
        bridge = _make_bridge()
        bridge._cost_tracker = MagicMock()
        bridge._cost_tracker.get_daily_summary.return_value = {}
        bridge._cost_tracker.get_weekly_summary.return_value = {}
        bridge._cost_tracker.get_cost_by_agent.return_value = {}
        bridge._cost_tracker.get_cost_by_workflow.return_value = {
            "nightly-digest": {"cost": 1.25, "count": 4},
        }
        client = await _create_client(bridge)
        try:
            resp = await client.get("/api/cost", headers=_auth())
            assert resp.status == 200
            data = await resp.json()
            assert isinstance(data["by_workflow"], dict)
            assert data["by_workflow"]["nightly-digest"]["cost"] == 1.25
        finally:
            await client.close()

    async def test_with_tracker(self):
        bridge = _make_bridge()
        bridge._cost_tracker = MagicMock()
        bridge._cost_tracker.get_daily_summary.return_value = {
            "date": "2026-03-28",
            "total_cost": 2.50,
            "request_count": 15,
            "by_model": {
                "sonnet": {"cost": 2.00, "count": 12},
                "haiku": {"cost": 0.50, "count": 3},
            },
        }
        bridge._cost_tracker.get_weekly_summary.return_value = {
            "total_cost": 12.75,
            "request_count": 80,
            "by_model": {
                "sonnet": {"cost": 10.00, "count": 60},
                "haiku": {"cost": 2.75, "count": 20},
            },
        }
        bridge._cost_tracker.get_cost_by_agent.return_value = {}
        bridge._cost_tracker.get_cost_by_workflow.return_value = {}

        client = await _create_client(bridge)
        try:
            resp = await client.get("/api/cost", headers=_auth())
            assert resp.status == 200
            data = await resp.json()
            assert data["daily"]["total_cost"] == 2.50
            assert data["daily"]["request_count"] == 15
            assert data["weekly"]["total_cost"] == 12.75
        finally:
            await client.close()
