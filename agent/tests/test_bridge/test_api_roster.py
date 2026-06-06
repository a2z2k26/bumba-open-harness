"""Tests for the roster registry REST surface — RR.3 (issue #2593).

The ``_RosterRoutesMixin`` exposes operator-only routes over the
``RosterRegistryStore`` (RR.1) so the dashboard / operator can add/remove
runtime specialists without a YAML edit. These tests pin the seam audited in
the spec: a validation failure must surface as a clean 400 (not a 500 or a
silent null success), and an absent unregister must surface as a 404.

Mirrors the aiohttp ``TestServer`` harness in ``tests/test_api_cost.py``.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from bridge.api_server import (
    APIServer,
    _enumerate_public_routes,
    cors_middleware,
    create_auth_middleware,
)
from bridge.roster_registry_store import (
    RegisteredSpecialist,
    RegisterResult,
)

pytestmark = pytest.mark.socket  # binds localhost sockets via aiohttp TestServer

API_TOKEN = "test-token-roster"


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
    bridge._roster_registry = None
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


def _specialist(department="engineering", name="perf-2"):
    return RegisteredSpecialist(
        department=department,
        name=name,
        agent_ref="performance-engineer",
        registered_at="2026-06-03T00:00:00+00:00",
        registered_by="operator",
    )


@pytest.mark.asyncio
class TestRosterRoutes:
    async def test_register_route_validates(self):
        """A valid registration returns 200 + the persisted specialist."""
        bridge = _make_bridge()
        store = MagicMock()
        store.register.return_value = RegisterResult(
            ok=True, specialist=_specialist()
        )
        bridge._roster_registry = store
        client = await _create_client(bridge)
        try:
            resp = await client.post(
                "/api/roster/register",
                headers=_auth(),
                json={
                    "department": "engineering",
                    "name": "perf-2",
                    "agent_ref": "performance-engineer",
                },
            )
            assert resp.status == 200
            data = await resp.json()
            assert data["specialist"]["name"] == "perf-2"
            store.register.assert_called_once_with(
                "engineering", "perf-2", "performance-engineer"
            )
        finally:
            await client.close()

    async def test_register_route_400_on_bad_dept(self):
        """A validation failure surfaces as 400 carrying the error — not 500."""
        bridge = _make_bridge()
        store = MagicMock()
        store.register.return_value = RegisterResult(
            ok=False, error="unknown department: 'nope'"
        )
        bridge._roster_registry = store
        client = await _create_client(bridge)
        try:
            resp = await client.post(
                "/api/roster/register",
                headers=_auth(),
                json={
                    "department": "nope",
                    "name": "x",
                    "agent_ref": "y",
                },
            )
            assert resp.status == 400
            data = await resp.json()
            assert "unknown department" in data["error"]
        finally:
            await client.close()

    async def test_register_route_400_on_missing_field(self):
        """Missing required field returns 400 before touching the store."""
        bridge = _make_bridge()
        store = MagicMock()
        bridge._roster_registry = store
        client = await _create_client(bridge)
        try:
            resp = await client.post(
                "/api/roster/register",
                headers=_auth(),
                json={"department": "engineering"},
            )
            assert resp.status == 400
            store.register.assert_not_called()
        finally:
            await client.close()

    async def test_list_roster_route(self):
        """GET /api/roster lists all registered specialists across depts."""
        bridge = _make_bridge()
        store = MagicMock()
        store.list_all.return_value = (_specialist(),)
        bridge._roster_registry = store
        client = await _create_client(bridge)
        try:
            resp = await client.get("/api/roster", headers=_auth())
            assert resp.status == 200
            data = await resp.json()
            assert data["count"] == 1
            assert data["specialists"][0]["name"] == "perf-2"
        finally:
            await client.close()

    async def test_list_roster_for_department_route(self):
        """GET /api/roster/{dept} lists the overlay for one department."""
        bridge = _make_bridge()
        store = MagicMock()
        store.list_for_department.return_value = (_specialist(),)
        bridge._roster_registry = store
        client = await _create_client(bridge)
        try:
            resp = await client.get(
                "/api/roster/engineering", headers=_auth()
            )
            assert resp.status == 200
            data = await resp.json()
            assert data["department"] == "engineering"
            assert data["count"] == 1
            store.list_for_department.assert_called_once_with("engineering")
        finally:
            await client.close()

    async def test_list_roster_no_store_empty(self):
        """No store wired → GET returns an empty list (not a 500)."""
        bridge = _make_bridge()
        bridge._roster_registry = None
        client = await _create_client(bridge)
        try:
            resp = await client.get("/api/roster", headers=_auth())
            assert resp.status == 200
            data = await resp.json()
            assert data["specialists"] == []
            assert data["count"] == 0
        finally:
            await client.close()

    async def test_unregister_route(self):
        """POST /api/roster/unregister removes a present specialist (200)."""
        bridge = _make_bridge()
        store = MagicMock()
        store.unregister.return_value = True
        bridge._roster_registry = store
        client = await _create_client(bridge)
        try:
            resp = await client.post(
                "/api/roster/unregister",
                headers=_auth(),
                json={"department": "engineering", "name": "perf-2"},
            )
            assert resp.status == 200
            data = await resp.json()
            assert data["unregistered"] == "perf-2"
            store.unregister.assert_called_once_with("engineering", "perf-2")
        finally:
            await client.close()

    async def test_unregister_route_404_when_absent(self):
        """Unregistering an absent specialist returns 404."""
        bridge = _make_bridge()
        store = MagicMock()
        store.unregister.return_value = False
        bridge._roster_registry = store
        client = await _create_client(bridge)
        try:
            resp = await client.post(
                "/api/roster/unregister",
                headers=_auth(),
                json={"department": "engineering", "name": "ghost"},
            )
            assert resp.status == 404
        finally:
            await client.close()

    async def test_register_no_store_503(self):
        """No store wired → register returns 503, not a 500."""
        bridge = _make_bridge()
        bridge._roster_registry = None
        client = await _create_client(bridge)
        try:
            resp = await client.post(
                "/api/roster/register",
                headers=_auth(),
                json={
                    "department": "engineering",
                    "name": "perf-2",
                    "agent_ref": "performance-engineer",
                },
            )
            assert resp.status == 503
        finally:
            await client.close()

    async def test_routes_in_api_index(self):
        """All four roster routes surface in the introspective /api index."""
        bridge = _make_bridge()
        server = APIServer(bridge, api_token=API_TOKEN)
        app = web.Application(
            middlewares=[
                cors_middleware,
                create_auth_middleware(server._api_token),
            ]
        )
        server._register_routes(app)
        paths = {r["path"] for r in _enumerate_public_routes(app)}
        assert "/api/roster" in paths
        assert "/api/roster/{department}" in paths
        assert "/api/roster/register" in paths
        assert "/api/roster/unregister" in paths
