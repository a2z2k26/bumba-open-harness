"""Tests for API agent endpoints (list, detail, spawn, kill)."""

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

API_TOKEN = "test-token-agents"


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
class TestAgentsList:
    async def test_no_tmux_returns_empty(self):
        bridge = _make_bridge()
        bridge._tmux_agents = None
        client = await _create_client(bridge)
        try:
            resp = await client.get("/api/agents", headers=_auth())
            assert resp.status == 200
            data = await resp.json()
            assert data["agents"] == []
        finally:
            await client.close()

    async def test_with_agents(self):
        bridge = _make_bridge()
        agent = MagicMock()
        agent.agent_id = "abc12345"
        agent.name = "worker"
        agent.status = "running"
        agent.created_at = "2026-03-28T10:00:00Z"
        agent.task = "Build feature X"

        bridge._tmux_agents = AsyncMock()
        bridge._tmux_agents.list_agents = AsyncMock(return_value=[agent])

        client = await _create_client(bridge)
        try:
            resp = await client.get("/api/agents", headers=_auth())
            assert resp.status == 200
            data = await resp.json()
            assert len(data["agents"]) == 1
            assert data["agents"][0]["id"] == "abc12345"
            assert data["agents"][0]["status"] == "running"
        finally:
            await client.close()


@pytest.mark.asyncio
class TestAgentSpawn:
    async def test_spawn_no_tmux(self):
        bridge = _make_bridge()
        bridge._tmux_agents = None
        client = await _create_client(bridge)
        try:
            resp = await client.post(
                "/api/agents/spawn",
                json={"task": "do something"},
                headers=_auth(),
            )
            assert resp.status == 503
        finally:
            await client.close()

    async def test_spawn_missing_task(self):
        bridge = _make_bridge()
        bridge._tmux_agents = AsyncMock()
        client = await _create_client(bridge)
        try:
            resp = await client.post(
                "/api/agents/spawn",
                json={"name": "test"},
                headers=_auth(),
            )
            assert resp.status == 400
        finally:
            await client.close()

    async def test_spawn_success(self):
        bridge = _make_bridge()
        agent = MagicMock()
        agent.agent_id = "new123"
        agent.name = "spawned"
        agent.status = "running"

        bridge._tmux_agents = AsyncMock()
        bridge._tmux_agents.spawn_agent = AsyncMock(return_value=agent)

        client = await _create_client(bridge)
        try:
            resp = await client.post(
                "/api/agents/spawn",
                json={"task": "Analyze codebase"},
                headers=_auth(),
            )
            assert resp.status == 201
            data = await resp.json()
            assert data["id"] == "new123"
        finally:
            await client.close()


@pytest.mark.asyncio
class TestAgentKill:
    async def test_kill_agent(self):
        bridge = _make_bridge()
        bridge._tmux_agents = AsyncMock()
        bridge._tmux_agents.kill_agent = AsyncMock(return_value=True)

        client = await _create_client(bridge)
        try:
            resp = await client.post(
                "/api/agents/abc123/kill",
                headers=_auth(),
            )
            assert resp.status == 200
            data = await resp.json()
            assert data["killed"] == "abc123"
        finally:
            await client.close()

    async def test_kill_agent_not_found(self):
        bridge = _make_bridge()
        bridge._tmux_agents = AsyncMock()
        bridge._tmux_agents.kill_agent = AsyncMock(return_value=False)

        client = await _create_client(bridge)
        try:
            resp = await client.post(
                "/api/agents/nonexistent/kill",
                headers=_auth(),
            )
            assert resp.status == 404
        finally:
            await client.close()
