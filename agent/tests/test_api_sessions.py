"""Tests for API session endpoints (list, reset)."""

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

API_TOKEN = "test-token-sessions"


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
class TestSessionsList:
    async def test_no_session_mgr(self):
        bridge = _make_bridge()
        bridge._session_mgr = None
        client = await _create_client(bridge)
        try:
            resp = await client.get("/api/sessions", headers=_auth())
            assert resp.status == 200
            data = await resp.json()
            assert data["sessions"] == []
        finally:
            await client.close()

    async def test_with_sessions(self):
        bridge = _make_bridge()
        bridge._session_mgr = AsyncMock()
        bridge._session_mgr.list_active = AsyncMock(return_value=[
            {
                "chat_id": "123",
                "session_id": "sess-001",
                "created_at": "2026-03-28T10:00:00Z",
                "last_activity": "2026-03-28T10:05:00Z",
                "message_count": 5,
            }
        ])
        client = await _create_client(bridge)
        try:
            resp = await client.get("/api/sessions", headers=_auth())
            assert resp.status == 200
            data = await resp.json()
            assert len(data["sessions"]) == 1
            assert data["sessions"][0]["chat_id"] == "123"
        finally:
            await client.close()


@pytest.mark.asyncio
class TestSessionReset:
    async def test_missing_chat_id(self):
        bridge = _make_bridge()
        bridge._session_mgr = AsyncMock()
        client = await _create_client(bridge)
        try:
            resp = await client.post(
                "/api/sessions/reset",
                json={},
                headers=_auth(),
            )
            assert resp.status == 400
        finally:
            await client.close()

    async def test_reset_success(self):
        bridge = _make_bridge()
        bridge._session_mgr = AsyncMock()
        bridge._session_mgr.expire_session = AsyncMock()
        client = await _create_client(bridge)
        try:
            resp = await client.post(
                "/api/sessions/reset",
                json={"chat_id": "456"},
                headers=_auth(),
            )
            assert resp.status == 200
            data = await resp.json()
            assert data["reset"] is True
        finally:
            await client.close()
