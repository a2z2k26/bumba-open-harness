"""Tests for API trust endpoint (per-capability trust scores)."""

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

API_TOKEN = "test-token-trust"


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
class TestTrustEndpoint:
    async def test_no_autonomy(self):
        bridge = _make_bridge()
        bridge._autonomy = None
        client = await _create_client(bridge)
        try:
            resp = await client.get("/api/trust", headers=_auth())
            assert resp.status == 200
            data = await resp.json()
            assert data["domains"] == {}
        finally:
            await client.close()

    async def test_with_trust_scores(self):
        bridge = _make_bridge()

        # Build mock trust engine
        cap_score = MagicMock()
        cap_score.score = 75.0
        cap_score.total_actions = 100
        cap_score.successes = 90
        cap_score.failures = 10
        cap_score.override_tier = None

        trust = MagicMock()
        trust._scores = {"routing": cap_score, "deploy": cap_score}
        trust.get_tier.return_value = "autonomous"

        autonomy = MagicMock()
        autonomy.trust = trust
        autonomy.escalation = MagicMock()
        autonomy.escalation._active_alerts = {}
        autonomy.event_bus = MagicMock()
        autonomy.event_bus._recent_events = []
        autonomy.event_bus._lock = MagicMock()
        autonomy.event_bus._lock.__enter__ = MagicMock(return_value=None)
        autonomy.event_bus._lock.__exit__ = MagicMock(return_value=False)
        autonomy.event_bus.get_event_count.return_value = 0

        bridge._autonomy = autonomy

        client = await _create_client(bridge)
        try:
            resp = await client.get("/api/trust", headers=_auth())
            assert resp.status == 200
            data = await resp.json()
            assert "routing" in data["domains"]
            assert data["domains"]["routing"]["score"] == 75.0
            assert data["domains"]["routing"]["tier"] == "autonomous"
        finally:
            await client.close()
