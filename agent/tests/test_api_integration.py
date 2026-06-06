"""Phase 9: Integration tests for the full Mission Control API surface.

Verifies all routes are registered, endpoints return expected shapes,
and the full stack works end-to-end with mocked bridge components.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from bridge.api_server import (
    APIServer,
    RateLimiter,
    cors_middleware,
    create_auth_middleware,
    create_cors_middleware,
)

pytestmark = pytest.mark.socket  # binds localhost sockets via aiohttp TestServer


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

API_TOKEN = "integration-test-token"

EXPECTED_ROUTES = [
    ("GET", "/healthz"),
    ("GET", "/api"),
    ("GET", "/api/agents"),
    ("GET", "/api/agents/{agent_id}"),
    ("POST", "/api/agents/spawn"),
    ("POST", "/api/agents/{agent_id}/kill"),
    ("GET", "/api/sessions"),
    ("POST", "/api/sessions/reset"),
    ("GET", "/api/cost"),
    ("GET", "/api/trust"),
    ("GET", "/api/escalation"),
    ("POST", "/api/escalation/acknowledge"),
    ("POST", "/api/escalation/defer"),
    ("GET", "/api/events"),
    ("GET", "/api/knowledge"),
    ("GET", "/api/knowledge/search"),
    ("GET", "/api/services"),
    ("GET", "/api/commands"),
    ("POST", "/api/commands"),
    ("GET", "/api/metrics/{name}"),
    ("GET", "/api/traces"),
    ("GET", "/api/tasks"),
    ("GET", "/api/tasks/{task_id}"),
    ("POST", "/api/tasks"),
    ("PUT", "/api/tasks/{task_id}/move"),
    ("PUT", "/api/tasks/{task_id}/assign"),
    ("GET", "/api/reviews"),
    ("POST", "/api/reviews"),
    ("POST", "/api/reviews/{review_id}/decide"),
    ("POST", "/api/webhooks/github"),
    ("GET", "/api/hitl/pending"),
    ("POST", "/api/hitl/{task_id}/respond"),
    ("GET", "/ws/events"),
]


def _make_full_mock_bridge():
    """Create a comprehensive mock BridgeApp with all components wired."""
    bridge = MagicMock()
    bridge._config = MagicMock()
    bridge._config.data_dir = "/tmp/test-data"
    bridge._config.operator_discord_id = "test-operator"

    # Database
    bridge._db = AsyncMock()
    bridge._db.fetchall = AsyncMock(return_value=[])
    bridge._db.fetchone = AsyncMock(return_value=None)

    # Health
    health = AsyncMock()
    health.collect_health = AsyncMock(return_value={
        "status": "healthy",
        "uptime_seconds": 42,
        "components": {},
        "timestamp": "2026-03-28T00:00:00Z",
    })
    bridge._health_server = health

    # Agents
    bridge._tmux_agents = None

    # Sessions
    session_mgr = AsyncMock()
    session_mgr.list_active = AsyncMock(return_value=[])
    bridge._session_mgr = session_mgr

    # Cost
    cost_tracker = MagicMock()
    cost_tracker.get_daily_summary.return_value = {
        "date": "2026-03-28", "total_cost": 1.23, "request_count": 10
    }
    cost_tracker.get_weekly_summary.return_value = {
        "total_cost": 5.67, "request_count": 50
    }
    cost_tracker.get_cost_by_agent.return_value = {}
    bridge._cost_tracker = cost_tracker

    # Autonomy (trust + escalation + event_bus)
    autonomy = MagicMock()

    trust = MagicMock()
    trust._scores = {}
    autonomy.trust = trust

    escalation = MagicMock()
    escalation._active_alerts = {}
    autonomy.escalation = escalation

    event_bus = MagicMock()
    event_bus._recent_events = []
    event_bus._lock = MagicMock()
    event_bus._lock.__enter__ = MagicMock(return_value=None)
    event_bus._lock.__exit__ = MagicMock(return_value=False)
    event_bus.get_event_count.return_value = 0
    autonomy.event_bus = event_bus

    bridge._autonomy = autonomy

    # Memory
    memory = AsyncMock()
    memory.get_recent_knowledge = AsyncMock(return_value=[])
    memory.search_knowledge = AsyncMock(return_value=[])
    bridge._memory = memory

    # Commands
    commands = AsyncMock()
    commands.handle = AsyncMock(return_value="OK")
    bridge._commands = commands

    # Metrics
    metrics = MagicMock()
    metrics.snapshot.return_value = {"counters": {}, "histograms": {}}
    bridge._metrics = metrics

    # Tracer
    bridge._tracer = None

    # Task queue (HITL)
    bridge._task_queue = AsyncMock()
    bridge._task_queue.get = AsyncMock(return_value=None)

    # Task pipeline
    pipeline = AsyncMock()
    pipeline.list_tasks = AsyncMock(return_value=[])
    pipeline.get_pipeline_summary = AsyncMock(return_value={
        "inbox": 0, "assigned": 0, "in_progress": 0,
        "review": 0, "quality_review": 0, "done": 0, "failed": 0,
    })
    pipeline.get_task = AsyncMock(return_value=None)
    pipeline.create_task = AsyncMock(return_value=1)
    pipeline.move_task = AsyncMock(return_value=True)
    pipeline.assign_task = AsyncMock(return_value=True)
    bridge._task_pipeline = pipeline

    # Quality gate
    gate = AsyncMock()
    gate.get_pending_reviews = AsyncMock(return_value=[])
    gate.request_review = AsyncMock(return_value=1)
    gate.submit_decision = AsyncMock(return_value=True)
    bridge._quality_gate = gate

    # Webhook receiver
    receiver = AsyncMock()
    receiver.handle_webhook = AsyncMock(return_value={"received": True})
    bridge._webhook_receiver = receiver

    return bridge


@pytest.fixture
def full_bridge():
    return _make_full_mock_bridge()


async def _create_test_client(bridge):
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
# Route registration
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestRouteRegistration:
    async def test_all_expected_routes_registered(self, full_bridge):
        server = APIServer(full_bridge, api_token=API_TOKEN)
        app = web.Application()
        server._register_routes(app)

        registered = set()
        for resource in app.router.resources():
            info = resource.get_info()
            path = info.get("path") or info.get("formatter", "")
            for route in resource:
                registered.add((route.method, path))

        for method, path in EXPECTED_ROUTES:
            assert (method, path) in registered, \
                f"Route {method} {path} not registered"

    async def test_route_count_matches(self, full_bridge):
        server = APIServer(full_bridge, api_token=API_TOKEN)
        app = web.Application()
        server._register_routes(app)

        route_count = sum(1 for r in app.router.routes())
        # Should have at least as many routes as expected
        assert route_count >= len(EXPECTED_ROUTES)


# ---------------------------------------------------------------------------
# Health endpoint (smoke test)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestHealthSmoke:
    async def test_healthz_returns_200(self, full_bridge):
        client = await _create_test_client(full_bridge)
        try:
            resp = await client.get("/healthz")
            assert resp.status == 200
            data = await resp.json()
            assert data["status"] == "healthy"
        finally:
            await client.close()


# ---------------------------------------------------------------------------
# API Index
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestAPIIndexIntegration:
    async def test_api_index_lists_all_endpoints(self, full_bridge):
        client = await _create_test_client(full_bridge)
        try:
            resp = await client.get("/api", headers=_auth())
            assert resp.status == 200
            data = await resp.json()
            # Sprint 07.02: handler is now introspective; payload key is
            # "routes" (with a top-level "count") rather than "endpoints".
            paths = {e["path"] for e in data["routes"]}
            assert "/healthz" in paths
            assert "/api/agents" in paths
            assert "/api/tasks" in paths
            assert "/api/reviews" in paths
            assert "/ws/events" in paths
        finally:
            await client.close()


# ---------------------------------------------------------------------------
# End-to-end flows
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestEndToEndFlows:
    async def test_cost_endpoint_returns_daily_and_weekly(self, full_bridge):
        client = await _create_test_client(full_bridge)
        try:
            resp = await client.get("/api/cost", headers=_auth())
            assert resp.status == 200
            data = await resp.json()
            assert "daily" in data
            assert "weekly" in data
            assert data["daily"]["total_cost"] == 1.23
        finally:
            await client.close()

    async def test_task_pipeline_create_and_list(self, full_bridge):
        client = await _create_test_client(full_bridge)
        try:
            # Create task
            resp = await client.post(
                "/api/tasks",
                json={"title": "Test task", "priority": "high"},
                headers=_auth(),
            )
            assert resp.status == 201
            data = await resp.json()
            assert data["id"] == 1

            # List tasks
            resp = await client.get("/api/tasks", headers=_auth())
            assert resp.status == 200
        finally:
            await client.close()

    async def test_quality_review_flow(self, full_bridge):
        client = await _create_test_client(full_bridge)
        try:
            # Request review
            resp = await client.post(
                "/api/reviews",
                json={"task_id": 1, "reviewer": "operator"},
                headers=_auth(),
            )
            assert resp.status == 201

            # Decide review
            resp = await client.post(
                "/api/reviews/1/decide",
                json={"decision": "approved", "comment": "LGTM"},
                headers=_auth(),
            )
            assert resp.status == 200
        finally:
            await client.close()

    async def test_services_endpoint(self, full_bridge):
        client = await _create_test_client(full_bridge)
        try:
            resp = await client.get("/api/services", headers=_auth())
            assert resp.status == 200
        finally:
            await client.close()

    async def test_events_endpoint(self, full_bridge):
        client = await _create_test_client(full_bridge)
        try:
            resp = await client.get("/api/events", headers=_auth())
            assert resp.status == 200
            data = await resp.json()
            assert "events" in data
        finally:
            await client.close()

    async def test_hitl_pending(self, full_bridge):
        client = await _create_test_client(full_bridge)
        try:
            resp = await client.get("/api/hitl/pending", headers=_auth())
            assert resp.status == 200
            data = await resp.json()
            assert "pending" in data
        finally:
            await client.close()


# ---------------------------------------------------------------------------
# Rate limiter unit tests
# ---------------------------------------------------------------------------

class TestRateLimiter:
    def test_allows_initial_request(self):
        rl = RateLimiter(rate=2.0, bucket_size=120)
        assert rl.check("127.0.0.1") is True

    def test_allows_burst_up_to_bucket_size(self):
        rl = RateLimiter(rate=2.0, bucket_size=5)
        for _ in range(5):
            assert rl.check("10.0.0.1") is True
        assert rl.check("10.0.0.1") is False

    def test_different_ips_independent(self):
        rl = RateLimiter(rate=2.0, bucket_size=2)
        assert rl.check("10.0.0.1") is True
        assert rl.check("10.0.0.1") is True
        assert rl.check("10.0.0.1") is False
        # Different IP should still work
        assert rl.check("10.0.0.2") is True


# ---------------------------------------------------------------------------
# Auth flow integration
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestAuthIntegration:
    async def test_no_token_returns_401(self, full_bridge):
        client = await _create_test_client(full_bridge)
        try:
            resp = await client.get("/api/agents")
            assert resp.status == 401
        finally:
            await client.close()

    async def test_wrong_token_returns_401(self, full_bridge):
        client = await _create_test_client(full_bridge)
        try:
            resp = await client.get(
                "/api/agents",
                headers={"Authorization": "Bearer wrong-token"},
            )
            assert resp.status == 401
        finally:
            await client.close()

    async def test_valid_token_returns_200(self, full_bridge):
        client = await _create_test_client(full_bridge)
        try:
            resp = await client.get("/api/agents", headers=_auth())
            assert resp.status == 200
        finally:
            await client.close()

    async def test_healthz_skips_auth(self, full_bridge):
        client = await _create_test_client(full_bridge)
        try:
            resp = await client.get("/healthz")
            assert resp.status == 200
        finally:
            await client.close()

    async def test_cors_preflight_skips_auth(self, full_bridge):
        server = APIServer(full_bridge, api_token=API_TOKEN)
        app = web.Application(
            middlewares=[
                create_cors_middleware(("https://mission-control.test",)),
                create_auth_middleware(server._api_token),
            ]
        )
        server._register_routes(app)
        ts = TestServer(app)
        client = TestClient(ts)
        await client.start_server()
        try:
            resp = await client.options(
                "/api/agents",
                headers={"Origin": "https://mission-control.test"},
            )
            assert resp.status == 204
            assert (
                resp.headers["Access-Control-Allow-Origin"]
                == "https://mission-control.test"
            )
        finally:
            await client.close()
