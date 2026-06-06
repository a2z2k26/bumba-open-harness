"""Extended tests for bridge/api_server.py — pushing coverage toward 80%.

Targets the gaps left after PR #282:
- RateLimiter: refill, denial, cleanup, IP isolation
- Rate-limit 429 via middleware
- APIServer lifecycle: port property, stop() without runner, stop() closing WS
- Healthz: degraded (503) path
- Handler exception paths across agents, sessions, cost, trust, escalation,
  events, knowledge, commands, metrics, traces, tasks, reviews, webhooks, HITL
- Services: config exists but no state dir
- Metrics: counter, histogram, unknown name
- Traces: no file, with JSON data
- Tasks: list with data, get found, create success, move (invalid/ValueError),
  assign found/not-found
- Reviews: list with data, create success, decide (found/not-found)
- Webhooks: receiver success + exception
- HITL: pending with db rows, respond (bad JSON, no queue)
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from bridge.api_server import (
    APIServer,
    RateLimiter,
    cors_middleware,
    create_auth_middleware,
)

pytestmark = pytest.mark.socket  # binds localhost sockets via aiohttp TestServer

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

API_TOKEN = "ext-test-token-42"


@pytest.fixture(autouse=True)
def reset_rate_limiter():
    """Replace the module-level rate limiter with a fresh, large-bucket
    instance before every test so cross-test state cannot cause spurious 429s.
    """
    import bridge.api_server as _mod
    fresh = RateLimiter(rate=2.0, bucket_size=10_000)
    with patch.object(_mod, "_rate_limiter", fresh):
        yield


def _make_bridge() -> MagicMock:
    bridge = MagicMock()
    bridge._config = MagicMock()
    bridge._config.data_dir = "/tmp/test-ext-data"
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


async def _create_client(bridge: MagicMock) -> TestClient:
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


def _auth() -> dict[str, str]:
    return {"Authorization": f"Bearer {API_TOKEN}"}


# ---------------------------------------------------------------------------
# RateLimiter — unit tests
# ---------------------------------------------------------------------------

class TestRateLimiterExtended:
    def test_initial_request_allowed(self) -> None:
        rl = RateLimiter(rate=2.0, bucket_size=5)
        assert rl.check("1.2.3.4") is True

    def test_bucket_empty_denies(self) -> None:
        rl = RateLimiter(rate=2.0, bucket_size=3)
        for _ in range(3):
            rl.check("1.2.3.4")
        assert rl.check("1.2.3.4") is False

    def test_refill_allows_after_wait(self) -> None:
        rl = RateLimiter(rate=100.0, bucket_size=2)
        rl.check("1.2.3.4")
        rl.check("1.2.3.4")
        assert rl.check("1.2.3.4") is False
        # Manually simulate time passing by patching the entry
        rl._clients["1.2.3.4"]["last_refill"] -= 0.1  # 0.1s → 10 tokens at rate=100
        assert rl.check("1.2.3.4") is True

    def test_ip_isolation(self) -> None:
        rl = RateLimiter(rate=2.0, bucket_size=1)
        # Exhaust IP-A
        rl.check("10.0.0.1")
        assert rl.check("10.0.0.1") is False
        # IP-B still has a full bucket
        assert rl.check("10.0.0.2") is True

    def test_cleanup_removes_stale_entries(self) -> None:
        rl = RateLimiter(rate=2.0, bucket_size=5, stale_seconds=10.0)
        rl.check("stale-ip")
        # Backdating last_refill and last_cleanup to force cleanup
        rl._clients["stale-ip"]["last_refill"] = time.monotonic() - 20.0
        rl._last_cleanup = time.monotonic() - 61.0  # older than 60s threshold
        rl.check("trigger-cleanup-ip")  # triggers _cleanup
        assert "stale-ip" not in rl._clients

    def test_cleanup_keeps_fresh_entries(self) -> None:
        rl = RateLimiter(rate=2.0, bucket_size=5, stale_seconds=300.0)
        rl.check("fresh-ip")
        rl._last_cleanup = time.monotonic() - 61.0
        rl.check("another-ip")
        # fresh-ip should still be present (accessed recently)
        assert "fresh-ip" in rl._clients


# ---------------------------------------------------------------------------
# Rate-limit 429 via middleware
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestRateLimitMiddleware:
    async def test_rate_limit_429_when_bucket_exhausted(self) -> None:
        """Exhaust the module-level _rate_limiter for a specific IP, then
        observe a 429 on a subsequent request from the same IP."""
        bridge = _make_bridge()
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

        try:
            from bridge import api_server as _mod
            # Patch the module-level rate limiter with a tiny bucket
            tiny_rl = RateLimiter(rate=0.0, bucket_size=0)
            # Pre-exhaust: put an entry with 0 tokens
            tiny_rl._clients["127.0.0.1"] = {
                "tokens": 0.0,
                "last_refill": time.monotonic(),
            }
            with patch.object(_mod, "_rate_limiter", tiny_rl):
                resp = await client.get("/api", headers=_auth())
                assert resp.status == 429
        finally:
            await client.close()


# ---------------------------------------------------------------------------
# APIServer lifecycle
# ---------------------------------------------------------------------------

class TestAPIServerLifecycle:
    def test_port_property_returns_configured_port(self) -> None:
        bridge = _make_bridge()
        server = APIServer(bridge, api_token=API_TOKEN, port=9999)
        assert server.port == 9999

    @pytest.mark.asyncio
    async def test_stop_with_no_runner_is_safe(self) -> None:
        bridge = _make_bridge()
        server = APIServer(bridge, api_token=API_TOKEN)
        # _runner is None by default — stop() must not raise
        await server.stop()

    @pytest.mark.asyncio
    async def test_stop_closes_ws_clients(self) -> None:
        bridge = _make_bridge()
        server = APIServer(bridge, api_token=API_TOKEN)
        # Inject a fake WebSocket client
        fake_ws = AsyncMock()
        server._ws_clients.append(fake_ws)
        await server.stop()
        fake_ws.close.assert_awaited_once()
        assert len(server._ws_clients) == 0


# ---------------------------------------------------------------------------
# P2.2 — CORS allowlist startup-warning wiring (audit C9)
# ---------------------------------------------------------------------------


class TestCorsStartupWarning:
    """Sprint P2.2 — when the bridge binds to a non-local host without any
    CORS origins configured, ``APIServer.start`` must emit a single warning.
    That signals to the operator that the API is LAN-reachable but no
    browser can use it cross-origin."""

    @pytest.mark.asyncio
    async def test_warns_when_lan_bind_with_empty_allowlist(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        import logging

        bridge = _make_bridge()
        # Pick port 0 so the OS allocates a free port; we shut down before
        # any real traffic. host=0.0.0.0 + empty allowlist = warn.
        # ``allow_remote_bind=True`` opts in past the P2.1 follow-up
        # (#1626) fail-closed validator so the CORS warning path is the
        # only thing under test here.
        server = APIServer(
            bridge,
            api_token=API_TOKEN,
            host="0.0.0.0",
            port=0,
            cors_allowed_origins=(),
            allow_remote_bind=True,
            # B.04 (#2053) — github_webhook_secret required when start()
            # runs; supply to reach the CORS warning path under test.
            github_webhook_secret="t",
        )
        with caplog.at_level(logging.WARNING, logger="bridge.api_server"):
            try:
                await server.start()
                msgs = [r.getMessage() for r in caplog.records]
                assert any(
                    "empty CORS allowlist" in m for m in msgs
                ), f"expected CORS warning, got: {msgs}"
            finally:
                await server.stop()

    @pytest.mark.asyncio
    async def test_no_warning_when_localhost_bind(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        import logging

        bridge = _make_bridge()
        server = APIServer(
            bridge,
            api_token=API_TOKEN,
            host="127.0.0.1",
            port=0,
            cors_allowed_origins=(),
            # B.04 (#2053) — github_webhook_secret required when start() runs.
            github_webhook_secret="t",
        )
        with caplog.at_level(logging.WARNING, logger="bridge.api_server"):
            try:
                await server.start()
                msgs = [r.getMessage() for r in caplog.records]
                assert not any(
                    "empty CORS allowlist" in m for m in msgs
                ), f"localhost bind must not warn; got: {msgs}"
            finally:
                await server.stop()

    @pytest.mark.asyncio
    async def test_no_warning_when_lan_bind_with_allowlist(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        import logging

        bridge = _make_bridge()
        # ``allow_remote_bind=True`` opts in past the P2.1 follow-up
        # (#1626) fail-closed validator so the CORS path is the only
        # surface this test exercises.
        server = APIServer(
            bridge,
            api_token=API_TOKEN,
            host="0.0.0.0",
            port=0,
            cors_allowed_origins=("https://dash.example.com",),
            allow_remote_bind=True,
            # B.04 (#2053) — github_webhook_secret required when start() runs.
            github_webhook_secret="t",
        )
        with caplog.at_level(logging.WARNING, logger="bridge.api_server"):
            try:
                await server.start()
                msgs = [r.getMessage() for r in caplog.records]
                assert not any(
                    "empty CORS allowlist" in m for m in msgs
                ), f"LAN bind with allowlist must not warn; got: {msgs}"
            finally:
                await server.stop()


# ---------------------------------------------------------------------------
# Healthz — degraded path
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestHealthzDegraded:
    async def test_healthz_503_when_degraded(self) -> None:
        bridge = _make_bridge()
        health_mock = AsyncMock()
        health_mock.collect_health = AsyncMock(return_value={
            "status": "degraded",
            "uptime_seconds": 10,
        })
        bridge._health_server = health_mock

        client = await _create_client(bridge)
        try:
            resp = await client.get("/healthz")
            assert resp.status == 503
            data = await resp.json()
            assert data["status"] == "degraded"
        finally:
            await client.close()

    async def test_healthz_200_when_healthy(self) -> None:
        bridge = _make_bridge()
        health_mock = AsyncMock()
        health_mock.collect_health = AsyncMock(return_value={
            "status": "healthy",
            "uptime_seconds": 100,
        })
        bridge._health_server = health_mock

        client = await _create_client(bridge)
        try:
            resp = await client.get("/healthz")
            assert resp.status == 200
        finally:
            await client.close()


# ---------------------------------------------------------------------------
# Agents — additional paths
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestAgentsExtended:
    async def test_list_agents_exception(self) -> None:
        bridge = _make_bridge()
        bridge._tmux_agents = AsyncMock()
        bridge._tmux_agents.list_agents = AsyncMock(side_effect=RuntimeError("tmux died"))

        client = await _create_client(bridge)
        try:
            resp = await client.get("/api/agents", headers=_auth())
            assert resp.status == 500
        finally:
            await client.close()

    async def test_get_agent_no_tmux(self) -> None:
        bridge = _make_bridge()
        bridge._tmux_agents = None

        client = await _create_client(bridge)
        try:
            resp = await client.get("/api/agents/any-id", headers=_auth())
            assert resp.status == 503
        finally:
            await client.close()

    async def test_get_agent_found(self) -> None:
        bridge = _make_bridge()
        agent_mock = MagicMock()
        agent_mock.agent_id = "found-agent"
        agent_mock.name = "finder"
        agent_mock.status = "running"
        agent_mock.created_at = "2026-01-01T00:00:00Z"
        agent_mock.task = "Investigate"

        bridge._tmux_agents = AsyncMock()
        bridge._tmux_agents.get_agent = AsyncMock(return_value=agent_mock)

        client = await _create_client(bridge)
        try:
            resp = await client.get("/api/agents/found-agent", headers=_auth())
            assert resp.status == 200
            data = await resp.json()
            assert data["id"] == "found-agent"
        finally:
            await client.close()

    async def test_get_agent_exception(self) -> None:
        bridge = _make_bridge()
        bridge._tmux_agents = AsyncMock()
        bridge._tmux_agents.get_agent = AsyncMock(side_effect=RuntimeError("boom"))

        client = await _create_client(bridge)
        try:
            resp = await client.get("/api/agents/any-id", headers=_auth())
            assert resp.status == 500
        finally:
            await client.close()

    async def test_spawn_agent_bad_json(self) -> None:
        bridge = _make_bridge()
        bridge._tmux_agents = AsyncMock()

        client = await _create_client(bridge)
        try:
            resp = await client.post(
                "/api/agents/spawn",
                data="not-json",
                headers={**_auth(), "Content-Type": "application/json"},
            )
            assert resp.status == 400
        finally:
            await client.close()

    async def test_spawn_agent_exception(self) -> None:
        bridge = _make_bridge()
        bridge._tmux_agents = AsyncMock()
        bridge._tmux_agents.spawn_agent = AsyncMock(side_effect=RuntimeError("spawn failed"))

        client = await _create_client(bridge)
        try:
            resp = await client.post(
                "/api/agents/spawn",
                json={"task": "do thing"},
                headers=_auth(),
            )
            assert resp.status == 500
        finally:
            await client.close()

    async def test_kill_agent_no_tmux(self) -> None:
        bridge = _make_bridge()
        bridge._tmux_agents = None

        client = await _create_client(bridge)
        try:
            resp = await client.post("/api/agents/abc/kill", headers=_auth())
            assert resp.status == 503
        finally:
            await client.close()

    async def test_kill_agent_exception(self) -> None:
        bridge = _make_bridge()
        bridge._tmux_agents = AsyncMock()
        bridge._tmux_agents.kill_agent = AsyncMock(side_effect=RuntimeError("kill failed"))

        client = await _create_client(bridge)
        try:
            resp = await client.post("/api/agents/abc/kill", headers=_auth())
            assert resp.status == 500
        finally:
            await client.close()


# ---------------------------------------------------------------------------
# Sessions — additional paths
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestSessionsExtended:
    async def test_list_sessions_exception(self) -> None:
        bridge = _make_bridge()
        bridge._session_mgr = AsyncMock()
        bridge._session_mgr.list_active = AsyncMock(side_effect=RuntimeError("db gone"))

        client = await _create_client(bridge)
        try:
            resp = await client.get("/api/sessions", headers=_auth())
            assert resp.status == 500
        finally:
            await client.close()

    async def test_reset_session_bad_json(self) -> None:
        bridge = _make_bridge()
        bridge._session_mgr = AsyncMock()

        client = await _create_client(bridge)
        try:
            resp = await client.post(
                "/api/sessions/reset",
                data="bad-json",
                headers={**_auth(), "Content-Type": "application/json"},
            )
            assert resp.status == 400
        finally:
            await client.close()

    async def test_reset_session_no_manager(self) -> None:
        bridge = _make_bridge()
        bridge._session_mgr = None

        client = await _create_client(bridge)
        try:
            resp = await client.post(
                "/api/sessions/reset",
                json={"chat_id": "123"},
                headers=_auth(),
            )
            assert resp.status == 503
        finally:
            await client.close()

    async def test_reset_session_exception(self) -> None:
        bridge = _make_bridge()
        bridge._session_mgr = AsyncMock()
        bridge._session_mgr.expire_session = AsyncMock(side_effect=RuntimeError("fail"))

        client = await _create_client(bridge)
        try:
            resp = await client.post(
                "/api/sessions/reset",
                json={"chat_id": "123"},
                headers=_auth(),
            )
            assert resp.status == 500
        finally:
            await client.close()


# ---------------------------------------------------------------------------
# Cost — exception path
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestCostExtended:
    async def test_cost_exception(self) -> None:
        bridge = _make_bridge()
        bridge._cost_tracker = MagicMock()
        bridge._cost_tracker.get_daily_summary.side_effect = RuntimeError("tracker error")

        client = await _create_client(bridge)
        try:
            resp = await client.get("/api/cost", headers=_auth())
            assert resp.status == 500
        finally:
            await client.close()


# ---------------------------------------------------------------------------
# Trust — exception path
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestTrustExtended:
    async def test_trust_exception(self) -> None:
        bridge = _make_bridge()
        autonomy = MagicMock()
        autonomy.trust = MagicMock()
        # Accessing ._scores raises
        type(autonomy.trust)._scores = property(lambda self: (_ for _ in ()).throw(RuntimeError("trust broken")))
        bridge._autonomy = autonomy

        client = await _create_client(bridge)
        try:
            resp = await client.get("/api/trust", headers=_auth())
            assert resp.status == 500
        finally:
            await client.close()


# ---------------------------------------------------------------------------
# Escalation — exception paths
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestEscalationExtended:
    async def test_list_escalation_exception(self) -> None:
        bridge = _make_bridge()
        autonomy = MagicMock()
        autonomy.escalation = MagicMock()
        type(autonomy.escalation)._active_alerts = property(
            lambda self: (_ for _ in ()).throw(RuntimeError("escalation db fail"))
        )
        bridge._autonomy = autonomy

        client = await _create_client(bridge)
        try:
            resp = await client.get("/api/escalation", headers=_auth())
            assert resp.status == 500
        finally:
            await client.close()

    async def test_acknowledge_bad_json(self) -> None:
        bridge = _make_bridge()
        autonomy = MagicMock()
        autonomy.escalation = MagicMock()
        autonomy.escalation._active_alerts = {}
        bridge._autonomy = autonomy

        client = await _create_client(bridge)
        try:
            resp = await client.post(
                "/api/escalation/acknowledge",
                data="not-json",
                headers={**_auth(), "Content-Type": "application/json"},
            )
            assert resp.status == 400
        finally:
            await client.close()

    async def test_defer_bad_json(self) -> None:
        bridge = _make_bridge()
        autonomy = MagicMock()
        autonomy.escalation = MagicMock()
        autonomy.escalation._active_alerts = {}
        bridge._autonomy = autonomy

        client = await _create_client(bridge)
        try:
            resp = await client.post(
                "/api/escalation/defer",
                data="not-json",
                headers={**_auth(), "Content-Type": "application/json"},
            )
            assert resp.status == 400
        finally:
            await client.close()

    async def test_defer_missing_source(self) -> None:
        bridge = _make_bridge()
        autonomy = MagicMock()
        autonomy.escalation = MagicMock()
        autonomy.escalation._active_alerts = {}
        bridge._autonomy = autonomy

        client = await _create_client(bridge)
        try:
            resp = await client.post(
                "/api/escalation/defer",
                json={},
                headers=_auth(),
            )
            assert resp.status == 400
        finally:
            await client.close()


# ---------------------------------------------------------------------------
# Events — exception path + with data
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestEventsExtended:
    async def test_events_exception(self) -> None:
        bridge = _make_bridge()
        autonomy = MagicMock()
        # Make _recent_events property raise to trigger the except branch
        autonomy.event_bus = MagicMock()
        autonomy.event_bus._lock = MagicMock()
        autonomy.event_bus._lock.__enter__ = MagicMock(return_value=None)
        autonomy.event_bus._lock.__exit__ = MagicMock(return_value=False)
        # Accessing _recent_events inside the lock context will raise
        type(autonomy.event_bus)._recent_events = property(
            lambda self: (_ for _ in ()).throw(RuntimeError("event bus boom"))
        )
        bridge._autonomy = autonomy

        client = await _create_client(bridge)
        try:
            resp = await client.get("/api/events", headers=_auth())
            assert resp.status == 500
        finally:
            await client.close()

    async def test_events_with_data(self) -> None:
        bridge = _make_bridge()
        autonomy = MagicMock()
        event = MagicMock()
        event.event_id = "e1"
        event.event_type = "message.processed"
        event.payload = {}
        event.source = "bridge"
        event.timestamp = "2026-01-01T00:00:00Z"
        event.correlation_id = "corr-1"

        autonomy.event_bus = MagicMock()
        autonomy.event_bus._recent_events = [event]
        autonomy.event_bus._lock = MagicMock()
        autonomy.event_bus._lock.__enter__ = MagicMock(return_value=None)
        autonomy.event_bus._lock.__exit__ = MagicMock(return_value=False)
        autonomy.event_bus.get_event_count.return_value = 1
        bridge._autonomy = autonomy

        client = await _create_client(bridge)
        try:
            resp = await client.get("/api/events", headers=_auth())
            assert resp.status == 200
            data = await resp.json()
            assert data["count"] == 1
            assert data["events"][0]["event_id"] == "e1"
        finally:
            await client.close()


# ---------------------------------------------------------------------------
# Knowledge — with data, search success, search no memory
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestKnowledgeExtended:
    async def test_knowledge_with_data(self) -> None:
        bridge = _make_bridge()
        bridge._memory = AsyncMock()
        bridge._memory.get_recent_knowledge = AsyncMock(
            return_value=[{"id": 1, "content": "hello"}]
        )

        client = await _create_client(bridge)
        try:
            resp = await client.get("/api/knowledge", headers=_auth())
            assert resp.status == 200
            data = await resp.json()
            assert data["count"] == 1
        finally:
            await client.close()

    async def test_knowledge_exception(self) -> None:
        bridge = _make_bridge()
        bridge._memory = AsyncMock()
        bridge._memory.get_recent_knowledge = AsyncMock(side_effect=RuntimeError("mem fail"))

        client = await _create_client(bridge)
        try:
            resp = await client.get("/api/knowledge", headers=_auth())
            assert resp.status == 500
        finally:
            await client.close()

    async def test_knowledge_search_success(self) -> None:
        bridge = _make_bridge()
        bridge._memory = AsyncMock()
        bridge._memory.search_knowledge = AsyncMock(return_value=[{"id": 2, "content": "result"}])

        client = await _create_client(bridge)
        try:
            resp = await client.get("/api/knowledge/search?q=hello", headers=_auth())
            assert resp.status == 200
            data = await resp.json()
            assert data["query"] == "hello"
            assert data["count"] == 1
        finally:
            await client.close()

    async def test_knowledge_search_no_memory(self) -> None:
        bridge = _make_bridge()
        bridge._memory = None

        client = await _create_client(bridge)
        try:
            resp = await client.get("/api/knowledge/search?q=test", headers=_auth())
            assert resp.status == 503
        finally:
            await client.close()

    async def test_knowledge_search_exception(self) -> None:
        bridge = _make_bridge()
        bridge._memory = AsyncMock()
        bridge._memory.search_knowledge = AsyncMock(side_effect=RuntimeError("search fail"))

        client = await _create_client(bridge)
        try:
            resp = await client.get("/api/knowledge/search?q=test", headers=_auth())
            assert resp.status == 500
        finally:
            await client.close()


# ---------------------------------------------------------------------------
# Services — config exists but no state dir
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestServicesExtended:
    async def test_services_config_no_state_dir(self, tmp_path: Path) -> None:
        bridge = _make_bridge()
        bridge._config.data_dir = str(tmp_path)
        # service_state dir does not exist inside tmp_path — endpoint returns early

        client = await _create_client(bridge)
        try:
            resp = await client.get("/api/services", headers=_auth())
            assert resp.status == 200
            data = await resp.json()
            # Early return: no service_state dir means empty services, no launchd block
            assert data["services"] == {}
        finally:
            await client.close()

    async def test_services_filters_unknown_state_files(self, tmp_path: Path) -> None:
        bridge = _make_bridge()
        bridge._config.data_dir = str(tmp_path)
        state_dir = tmp_path / "service_state"
        state_dir.mkdir()
        (state_dir / "briefing-state.json").write_text(json.dumps({
            "last_status": "success",
        }))
        (state_dir / "nonexistent-state.json").write_text(json.dumps({
            "last_status": "failure",
            "last_error": "ValueError: Unknown service: nonexistent",
        }))

        client = await _create_client(bridge)
        try:
            resp = await client.get("/api/services", headers=_auth())
            assert resp.status == 200
            data = await resp.json()
            assert "briefing" in data["services"]
            assert "nonexistent" not in data["services"]
        finally:
            await client.close()


# ---------------------------------------------------------------------------
# Commands — additional paths
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestCommandsExtended:
    async def test_dispatch_missing_command_field(self) -> None:
        bridge = _make_bridge()
        bridge._commands = AsyncMock()

        client = await _create_client(bridge)
        try:
            resp = await client.post(
                "/api/commands",
                json={},
                headers=_auth(),
            )
            assert resp.status == 400
        finally:
            await client.close()

    async def test_dispatch_no_handler(self) -> None:
        bridge = _make_bridge()
        bridge._commands = None

        client = await _create_client(bridge)
        try:
            resp = await client.post(
                "/api/commands",
                json={"command": "status"},
                headers=_auth(),
            )
            assert resp.status == 503
        finally:
            await client.close()

    async def test_dispatch_bad_json(self) -> None:
        bridge = _make_bridge()
        bridge._commands = AsyncMock()

        client = await _create_client(bridge)
        try:
            resp = await client.post(
                "/api/commands",
                data="not-json",
                headers={**_auth(), "Content-Type": "application/json"},
            )
            assert resp.status == 400
        finally:
            await client.close()

    async def test_dispatch_exception(self) -> None:
        bridge = _make_bridge()
        bridge._commands = AsyncMock()
        bridge._commands.handle = AsyncMock(side_effect=RuntimeError("cmd failed"))

        client = await _create_client(bridge)
        try:
            resp = await client.post(
                "/api/commands",
                json={"command": "status"},
                headers=_auth(),
            )
            assert resp.status == 500
        finally:
            await client.close()


# ---------------------------------------------------------------------------
# Metrics — counter, histogram, unknown, exception
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestMetricsExtended:
    async def test_metrics_counter(self) -> None:
        bridge = _make_bridge()
        bridge._metrics = MagicMock()
        bridge._metrics.snapshot.return_value = {
            "counters": {"messages_processed": 42},
            "histograms": {},
        }

        client = await _create_client(bridge)
        try:
            resp = await client.get("/api/metrics/messages_processed", headers=_auth())
            assert resp.status == 200
            data = await resp.json()
            assert data["type"] == "counter"
            assert data["value"] == 42
        finally:
            await client.close()

    async def test_metrics_histogram(self) -> None:
        bridge = _make_bridge()
        bridge._metrics = MagicMock()
        bridge._metrics.snapshot.return_value = {
            "counters": {},
            "histograms": {"response_time": {"p50": 120, "p99": 500}},
        }

        client = await _create_client(bridge)
        try:
            resp = await client.get("/api/metrics/response_time", headers=_auth())
            assert resp.status == 200
            data = await resp.json()
            assert data["type"] == "histogram"
            assert data["data"]["p50"] == 120
        finally:
            await client.close()

    async def test_metrics_unknown_name(self) -> None:
        bridge = _make_bridge()
        bridge._metrics = MagicMock()
        bridge._metrics.snapshot.return_value = {
            "counters": {},
            "histograms": {},
        }

        client = await _create_client(bridge)
        try:
            resp = await client.get("/api/metrics/nonexistent", headers=_auth())
            assert resp.status == 200
            data = await resp.json()
            assert data["type"] == "unknown"
        finally:
            await client.close()

    async def test_metrics_exception(self) -> None:
        bridge = _make_bridge()
        bridge._metrics = MagicMock()
        bridge._metrics.snapshot.side_effect = RuntimeError("metrics boom")

        client = await _create_client(bridge)
        try:
            resp = await client.get("/api/metrics/any", headers=_auth())
            assert resp.status == 500
        finally:
            await client.close()


# ---------------------------------------------------------------------------
# Traces — with tracer (no file, with data)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestTracesExtended:
    async def test_traces_with_tracer_no_file(self) -> None:
        bridge = _make_bridge()
        tracer = MagicMock()
        tracer._output_path = Path("/nonexistent/path/traces.jsonl")
        bridge._tracer = tracer

        client = await _create_client(bridge)
        try:
            resp = await client.get("/api/traces", headers=_auth())
            assert resp.status == 200
            data = await resp.json()
            assert data["traces"] == []
        finally:
            await client.close()

    async def test_traces_with_data(self, tmp_path: Path) -> None:
        bridge = _make_bridge()
        trace_file = tmp_path / "traces.jsonl"
        span1 = {"span_id": "s1", "duration_ms": 50}
        span2 = {"span_id": "s2", "duration_ms": 100}
        trace_file.write_text(
            json.dumps(span1) + "\n" + json.dumps(span2) + "\n"
        )

        tracer = MagicMock()
        tracer._output_path = trace_file
        bridge._tracer = tracer

        client = await _create_client(bridge)
        try:
            resp = await client.get("/api/traces", headers=_auth())
            assert resp.status == 200
            data = await resp.json()
            assert data["count"] == 2
            # Reversed, so latest span first
            assert data["traces"][0]["span_id"] == "s2"
        finally:
            await client.close()

    async def test_traces_exception(self) -> None:
        bridge = _make_bridge()
        tracer = MagicMock()
        tracer._output_path = MagicMock()
        tracer._output_path.exists.return_value = True
        tracer._output_path.read_text.side_effect = OSError("read fail")
        bridge._tracer = tracer

        client = await _create_client(bridge)
        try:
            resp = await client.get("/api/traces", headers=_auth())
            assert resp.status == 500
        finally:
            await client.close()


# ---------------------------------------------------------------------------
# Tasks — list, get, create, move, assign
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestTasksExtended:
    async def test_list_tasks_with_data(self) -> None:
        bridge = _make_bridge()
        pipeline = AsyncMock()
        pipeline.list_tasks = AsyncMock(return_value=[{"id": 1, "title": "t"}])
        pipeline.get_pipeline_summary = AsyncMock(return_value={})
        bridge._task_pipeline = pipeline

        client = await _create_client(bridge)
        try:
            resp = await client.get("/api/tasks", headers=_auth())
            assert resp.status == 200
            data = await resp.json()
            assert len(data["tasks"]) == 1
        finally:
            await client.close()

    async def test_list_tasks_exception(self) -> None:
        bridge = _make_bridge()
        pipeline = AsyncMock()
        pipeline.list_tasks = AsyncMock(side_effect=RuntimeError("pipeline fail"))
        bridge._task_pipeline = pipeline

        client = await _create_client(bridge)
        try:
            resp = await client.get("/api/tasks", headers=_auth())
            assert resp.status == 500
        finally:
            await client.close()

    async def test_get_task_found(self) -> None:
        bridge = _make_bridge()
        pipeline = AsyncMock()
        pipeline.get_task = AsyncMock(return_value={"id": 5, "title": "found"})
        bridge._task_pipeline = pipeline

        client = await _create_client(bridge)
        try:
            resp = await client.get("/api/tasks/5", headers=_auth())
            assert resp.status == 200
            data = await resp.json()
            assert data["id"] == 5
        finally:
            await client.close()

    async def test_get_task_not_found(self) -> None:
        bridge = _make_bridge()
        pipeline = AsyncMock()
        pipeline.get_task = AsyncMock(return_value=None)
        bridge._task_pipeline = pipeline

        client = await _create_client(bridge)
        try:
            resp = await client.get("/api/tasks/999", headers=_auth())
            assert resp.status == 404
        finally:
            await client.close()

    async def test_get_task_exception(self) -> None:
        bridge = _make_bridge()
        pipeline = AsyncMock()
        pipeline.get_task = AsyncMock(side_effect=RuntimeError("task boom"))
        bridge._task_pipeline = pipeline

        client = await _create_client(bridge)
        try:
            resp = await client.get("/api/tasks/1", headers=_auth())
            assert resp.status == 500
        finally:
            await client.close()

    async def test_create_task_success(self) -> None:
        bridge = _make_bridge()
        pipeline = AsyncMock()
        pipeline.create_task = AsyncMock(return_value=7)
        bridge._task_pipeline = pipeline

        client = await _create_client(bridge)
        try:
            resp = await client.post(
                "/api/tasks",
                json={"title": "New task", "priority": "high"},
                headers=_auth(),
            )
            assert resp.status == 201
            data = await resp.json()
            assert data["id"] == 7
        finally:
            await client.close()

    async def test_create_task_bad_json(self) -> None:
        bridge = _make_bridge()
        pipeline = AsyncMock()
        bridge._task_pipeline = pipeline

        client = await _create_client(bridge)
        try:
            resp = await client.post(
                "/api/tasks",
                data="bad",
                headers={**_auth(), "Content-Type": "application/json"},
            )
            assert resp.status == 400
        finally:
            await client.close()

    async def test_create_task_exception(self) -> None:
        bridge = _make_bridge()
        pipeline = AsyncMock()
        pipeline.create_task = AsyncMock(side_effect=RuntimeError("create fail"))
        bridge._task_pipeline = pipeline

        client = await _create_client(bridge)
        try:
            resp = await client.post(
                "/api/tasks",
                json={"title": "X"},
                headers=_auth(),
            )
            assert resp.status == 500
        finally:
            await client.close()

    async def test_move_task_success(self) -> None:
        bridge = _make_bridge()
        pipeline = AsyncMock()
        pipeline.move_task = AsyncMock(return_value=True)
        bridge._task_pipeline = pipeline

        client = await _create_client(bridge)
        try:
            resp = await client.put(
                "/api/tasks/1/move",
                json={"status": "in_progress"},
                headers=_auth(),
            )
            assert resp.status == 200
            data = await resp.json()
            assert data["status"] == "in_progress"
        finally:
            await client.close()

    async def test_move_task_invalid_transition(self) -> None:
        bridge = _make_bridge()
        pipeline = AsyncMock()
        pipeline.move_task = AsyncMock(return_value=False)
        bridge._task_pipeline = pipeline

        client = await _create_client(bridge)
        try:
            resp = await client.put(
                "/api/tasks/1/move",
                json={"status": "done"},
                headers=_auth(),
            )
            assert resp.status == 422
        finally:
            await client.close()

    async def test_move_task_value_error(self) -> None:
        bridge = _make_bridge()
        pipeline = AsyncMock()
        pipeline.move_task = AsyncMock(side_effect=ValueError("bad status"))
        bridge._task_pipeline = pipeline

        client = await _create_client(bridge)
        try:
            resp = await client.put(
                "/api/tasks/1/move",
                json={"status": "invalid_state"},
                headers=_auth(),
            )
            assert resp.status == 422
        finally:
            await client.close()

    async def test_move_task_bad_json(self) -> None:
        bridge = _make_bridge()
        pipeline = AsyncMock()
        bridge._task_pipeline = pipeline

        client = await _create_client(bridge)
        try:
            resp = await client.put(
                "/api/tasks/1/move",
                data="bad",
                headers={**_auth(), "Content-Type": "application/json"},
            )
            assert resp.status == 400
        finally:
            await client.close()

    async def test_assign_task_success(self) -> None:
        bridge = _make_bridge()
        pipeline = AsyncMock()
        pipeline.assign_task = AsyncMock(return_value=True)
        bridge._task_pipeline = pipeline

        client = await _create_client(bridge)
        try:
            resp = await client.put(
                "/api/tasks/1/assign",
                json={"assigned_to": "agent-x"},
                headers=_auth(),
            )
            assert resp.status == 200
            data = await resp.json()
            assert data["assigned_to"] == "agent-x"
        finally:
            await client.close()

    async def test_assign_task_not_found(self) -> None:
        bridge = _make_bridge()
        pipeline = AsyncMock()
        pipeline.assign_task = AsyncMock(return_value=False)
        bridge._task_pipeline = pipeline

        client = await _create_client(bridge)
        try:
            resp = await client.put(
                "/api/tasks/99/assign",
                json={"assigned_to": "agent-x"},
                headers=_auth(),
            )
            assert resp.status == 404
        finally:
            await client.close()

    async def test_assign_task_exception(self) -> None:
        bridge = _make_bridge()
        pipeline = AsyncMock()
        pipeline.assign_task = AsyncMock(side_effect=RuntimeError("assign fail"))
        bridge._task_pipeline = pipeline

        client = await _create_client(bridge)
        try:
            resp = await client.put(
                "/api/tasks/1/assign",
                json={"assigned_to": "agent-x"},
                headers=_auth(),
            )
            assert resp.status == 500
        finally:
            await client.close()

    async def test_assign_task_missing_field(self) -> None:
        bridge = _make_bridge()
        pipeline = AsyncMock()
        bridge._task_pipeline = pipeline

        client = await _create_client(bridge)
        try:
            resp = await client.put(
                "/api/tasks/1/assign",
                json={},
                headers=_auth(),
            )
            assert resp.status == 400
        finally:
            await client.close()


# ---------------------------------------------------------------------------
# Reviews — list, create, decide
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestReviewsExtended:
    async def test_list_reviews_with_data(self) -> None:
        bridge = _make_bridge()
        gate = AsyncMock()
        gate.get_pending_reviews = AsyncMock(return_value=[{"id": 1}])
        bridge._quality_gate = gate

        client = await _create_client(bridge)
        try:
            resp = await client.get("/api/reviews", headers=_auth())
            assert resp.status == 200
            data = await resp.json()
            assert data["count"] == 1
        finally:
            await client.close()

    async def test_list_reviews_exception(self) -> None:
        bridge = _make_bridge()
        gate = AsyncMock()
        gate.get_pending_reviews = AsyncMock(side_effect=RuntimeError("gate fail"))
        bridge._quality_gate = gate

        client = await _create_client(bridge)
        try:
            resp = await client.get("/api/reviews", headers=_auth())
            assert resp.status == 500
        finally:
            await client.close()

    async def test_create_review_success(self) -> None:
        bridge = _make_bridge()
        gate = AsyncMock()
        gate.request_review = AsyncMock(return_value=3)
        bridge._quality_gate = gate

        client = await _create_client(bridge)
        try:
            resp = await client.post(
                "/api/reviews",
                json={"task_id": 1, "reviewer": "operator"},
                headers=_auth(),
            )
            assert resp.status == 201
            data = await resp.json()
            assert data["id"] == 3
        finally:
            await client.close()

    async def test_create_review_missing_task_id(self) -> None:
        bridge = _make_bridge()
        gate = AsyncMock()
        bridge._quality_gate = gate

        client = await _create_client(bridge)
        try:
            resp = await client.post(
                "/api/reviews",
                json={"reviewer": "operator"},
                headers=_auth(),
            )
            assert resp.status == 400
        finally:
            await client.close()

    async def test_create_review_exception(self) -> None:
        bridge = _make_bridge()
        gate = AsyncMock()
        gate.request_review = AsyncMock(side_effect=RuntimeError("gate fail"))
        bridge._quality_gate = gate

        client = await _create_client(bridge)
        try:
            resp = await client.post(
                "/api/reviews",
                json={"task_id": 1},
                headers=_auth(),
            )
            assert resp.status == 500
        finally:
            await client.close()

    async def test_decide_review_approved(self) -> None:
        bridge = _make_bridge()
        gate = AsyncMock()
        gate.submit_decision = AsyncMock(return_value=True)
        bridge._quality_gate = gate

        client = await _create_client(bridge)
        try:
            resp = await client.post(
                "/api/reviews/1/decide",
                json={"decision": "approved"},
                headers=_auth(),
            )
            assert resp.status == 200
            data = await resp.json()
            assert data["decision"] == "approved"
        finally:
            await client.close()

    async def test_decide_review_not_found(self) -> None:
        bridge = _make_bridge()
        gate = AsyncMock()
        gate.submit_decision = AsyncMock(return_value=False)
        bridge._quality_gate = gate

        client = await _create_client(bridge)
        try:
            resp = await client.post(
                "/api/reviews/999/decide",
                json={"decision": "approved"},
                headers=_auth(),
            )
            assert resp.status == 404
        finally:
            await client.close()

    async def test_decide_review_exception(self) -> None:
        bridge = _make_bridge()
        gate = AsyncMock()
        gate.submit_decision = AsyncMock(side_effect=RuntimeError("decide fail"))
        bridge._quality_gate = gate

        client = await _create_client(bridge)
        try:
            resp = await client.post(
                "/api/reviews/1/decide",
                json={"decision": "approved"},
                headers=_auth(),
            )
            assert resp.status == 500
        finally:
            await client.close()


# ---------------------------------------------------------------------------
# Webhooks — with receiver (success + exception)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestWebhooksExtended:
    async def test_webhook_receiver_success(self) -> None:
        bridge = _make_bridge()
        receiver = AsyncMock()
        receiver.handle_webhook = AsyncMock(return_value={"received": True, "action": "opened"})
        bridge._webhook_receiver = receiver

        client = await _create_client(bridge)
        try:
            resp = await client.post(
                "/api/webhooks/github",
                json={"action": "opened"},
                headers={**_auth(), "X-GitHub-Event": "pull_request"},
            )
            assert resp.status == 200
            data = await resp.json()
            assert data["received"] is True
        finally:
            await client.close()

    async def test_webhook_receiver_exception(self) -> None:
        bridge = _make_bridge()
        receiver = AsyncMock()
        receiver.handle_webhook = AsyncMock(side_effect=RuntimeError("hmac fail"))
        bridge._webhook_receiver = receiver

        client = await _create_client(bridge)
        try:
            resp = await client.post(
                "/api/webhooks/github",
                json={"action": "opened"},
                headers=_auth(),
            )
            assert resp.status == 500
        finally:
            await client.close()


# ---------------------------------------------------------------------------
# HITL — pending with db rows, respond paths
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestHITLExtended:
    async def test_hitl_pending_with_db_rows(self) -> None:
        bridge = _make_bridge()
        bridge._task_queue = AsyncMock()
        # Row: (id, status, _, _, _, question, options_json, _, _, chat_id, created_at)
        row = [
            1,              # id
            "needs_input",  # status
            None, None, None,
            "Approve deploy?",  # question
            '["yes", "no"]',    # options
            None, None,
            "discord-123",  # chat_id
            "2026-01-01T00:00:00Z",  # created_at
        ]
        bridge._db.fetchall = AsyncMock(return_value=[row])

        client = await _create_client(bridge)
        try:
            resp = await client.get("/api/hitl/pending", headers=_auth())
            assert resp.status == 200
            data = await resp.json()
            assert data["count"] == 1
            assert data["pending"][0]["question"] == "Approve deploy?"
            assert data["pending"][0]["options"] == ["yes", "no"]
        finally:
            await client.close()

    async def test_hitl_pending_db_exception(self) -> None:
        bridge = _make_bridge()
        bridge._task_queue = AsyncMock()
        bridge._db.fetchall = AsyncMock(side_effect=RuntimeError("db fail"))

        client = await _create_client(bridge)
        try:
            resp = await client.get("/api/hitl/pending", headers=_auth())
            assert resp.status == 500
        finally:
            await client.close()

    async def test_hitl_respond_no_queue(self) -> None:
        bridge = _make_bridge()
        bridge._task_queue = None

        client = await _create_client(bridge)
        try:
            resp = await client.post(
                "/api/hitl/1/respond",
                json={"response": "yes"},
                headers=_auth(),
            )
            assert resp.status == 503
        finally:
            await client.close()

    async def test_hitl_respond_bad_json(self) -> None:
        bridge = _make_bridge()
        bridge._task_queue = AsyncMock()

        client = await _create_client(bridge)
        try:
            resp = await client.post(
                "/api/hitl/1/respond",
                data="bad",
                headers={**_auth(), "Content-Type": "application/json"},
            )
            assert resp.status == 400
        finally:
            await client.close()

    async def test_hitl_respond_success(self) -> None:
        bridge = _make_bridge()
        bridge._task_queue = AsyncMock()
        task_mock = MagicMock()
        task_mock.status = "needs_input"
        bridge._task_queue.get = AsyncMock(return_value=task_mock)
        bridge._task_queue.submit_response = AsyncMock()

        client = await _create_client(bridge)
        try:
            resp = await client.post(
                "/api/hitl/1/respond",
                json={"response": "yes"},
                headers=_auth(),
            )
            assert resp.status == 200
            data = await resp.json()
            assert data["status"] == "responded"
        finally:
            await client.close()

    async def test_hitl_respond_exception(self) -> None:
        bridge = _make_bridge()
        bridge._task_queue = AsyncMock()
        task_mock = MagicMock()
        task_mock.status = "needs_input"
        bridge._task_queue.get = AsyncMock(return_value=task_mock)
        bridge._task_queue.submit_response = AsyncMock(side_effect=RuntimeError("respond fail"))

        client = await _create_client(bridge)
        try:
            resp = await client.post(
                "/api/hitl/1/respond",
                json={"response": "yes"},
                headers=_auth(),
            )
            assert resp.status == 500
        finally:
            await client.close()
