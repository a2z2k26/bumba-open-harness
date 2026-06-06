"""Tests for API escalation endpoints (list, acknowledge, defer)."""

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

API_TOKEN = "test-token-escalation"


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


def _make_autonomy_with_alerts():
    """Create autonomy mock with one active alert."""
    alert = MagicMock()
    alert.level = 2  # numeric level
    alert.message = "Email service has 5 consecutive failures"
    alert.triggered_at = "2026-03-28T10:00:00Z"
    alert.deferred = False

    escalation = MagicMock()
    escalation._active_alerts = {"email": alert}
    escalation._deferred_queue = []

    autonomy = MagicMock()
    autonomy.escalation = escalation
    autonomy.trust = MagicMock()
    autonomy.trust._scores = {}
    autonomy.event_bus = MagicMock()
    autonomy.event_bus._recent_events = []
    autonomy.event_bus._lock = MagicMock()
    autonomy.event_bus._lock.__enter__ = MagicMock(return_value=None)
    autonomy.event_bus._lock.__exit__ = MagicMock(return_value=False)
    autonomy.event_bus.get_event_count.return_value = 0
    return autonomy


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
class TestEscalationList:
    async def test_no_autonomy(self):
        bridge = _make_bridge()
        bridge._autonomy = None
        client = await _create_client(bridge)
        try:
            resp = await client.get("/api/escalation", headers=_auth())
            assert resp.status == 200
            data = await resp.json()
            assert data["alerts"] == []
        finally:
            await client.close()

    async def test_with_alerts(self):
        bridge = _make_bridge()
        bridge._autonomy = _make_autonomy_with_alerts()
        client = await _create_client(bridge)
        try:
            resp = await client.get("/api/escalation", headers=_auth())
            assert resp.status == 200
            data = await resp.json()
            assert len(data["alerts"]) == 1
            assert data["alerts"][0]["source"] == "email"
        finally:
            await client.close()


@pytest.mark.asyncio
class TestEscalationAck:
    async def test_ack_missing_source(self):
        bridge = _make_bridge()
        bridge._autonomy = _make_autonomy_with_alerts()
        client = await _create_client(bridge)
        try:
            resp = await client.post(
                "/api/escalation/acknowledge",
                json={},
                headers=_auth(),
            )
            assert resp.status == 400
        finally:
            await client.close()

    async def test_ack_success(self):
        bridge = _make_bridge()
        bridge._autonomy = _make_autonomy_with_alerts()
        client = await _create_client(bridge)
        try:
            resp = await client.post(
                "/api/escalation/acknowledge",
                json={"source": "email"},
                headers=_auth(),
            )
            assert resp.status == 200
            data = await resp.json()
            assert data["acknowledged"] == "email"
            # Alert should be removed
            assert "email" not in bridge._autonomy.escalation._active_alerts
        finally:
            await client.close()

    async def test_ack_not_found(self):
        bridge = _make_bridge()
        bridge._autonomy = _make_autonomy_with_alerts()
        client = await _create_client(bridge)
        try:
            resp = await client.post(
                "/api/escalation/acknowledge",
                json={"source": "nonexistent"},
                headers=_auth(),
            )
            assert resp.status == 404
        finally:
            await client.close()


@pytest.mark.asyncio
class TestEscalationDefer:
    async def test_defer_success(self):
        bridge = _make_bridge()
        bridge._autonomy = _make_autonomy_with_alerts()
        client = await _create_client(bridge)
        try:
            resp = await client.post(
                "/api/escalation/defer",
                json={"source": "email"},
                headers=_auth(),
            )
            assert resp.status == 200
            data = await resp.json()
            assert data["deferred"] == "email"
            # Should move to deferred queue
            assert "email" not in bridge._autonomy.escalation._active_alerts
            assert len(bridge._autonomy.escalation._deferred_queue) == 1
        finally:
            await client.close()

    async def test_defer_not_found(self):
        bridge = _make_bridge()
        bridge._autonomy = _make_autonomy_with_alerts()
        client = await _create_client(bridge)
        try:
            resp = await client.post(
                "/api/escalation/defer",
                json={"source": "nonexistent"},
                headers=_auth(),
            )
            assert resp.status == 404
        finally:
            await client.close()
