"""Tests for WebSocket event streaming endpoint (/ws/events)."""

import asyncio
import logging
from unittest.mock import MagicMock, AsyncMock

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from bridge.api_server import (
    APIServer,
    cors_middleware,
    create_auth_middleware,
)
from bridge.metrics import MetricsCollector

pytestmark = pytest.mark.socket  # binds localhost sockets via aiohttp TestServer

API_TOKEN = "test-ws-token-99"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_mock_bridge(with_event_bus: bool = False):
    bridge = MagicMock()
    bridge._config = MagicMock()
    bridge._config.data_dir = "/tmp/test-data"
    bridge._config.operator_discord_id = "test-operator"
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
    if with_event_bus:
        autonomy = MagicMock()
        autonomy.event_bus = MagicMock()
        call_counter = {"n": 0}

        def _subscribe(event_type, callback):
            call_counter["n"] += 1
            return f"sub-{call_counter['n']}"

        autonomy.event_bus.subscribe.side_effect = _subscribe
        autonomy.event_bus.unsubscribe.return_value = True
        bridge._autonomy = autonomy
    return bridge


async def _make_client(bridge, token: str = API_TOKEN) -> TestClient:
    server_obj = APIServer(bridge, api_token=token, port=0)
    app = web.Application(
        middlewares=[
            cors_middleware,
            create_auth_middleware(server_obj._api_token),
        ]
    )
    server_obj._register_routes(app)
    client = TestClient(TestServer(app))
    await client.start_server()
    return client


# ---------------------------------------------------------------------------
# Route registration
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_ws_events_route_registered():
    """The /ws/events route must be registered."""
    bridge = _make_mock_bridge()
    server_obj = APIServer(bridge, api_token=API_TOKEN, port=0)
    app = web.Application()
    server_obj._register_routes(app)
    route_paths = [r.resource.canonical for r in app.router.routes()]
    assert "/ws/events" in route_paths


# ---------------------------------------------------------------------------
# Token authentication
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_ws_rejects_missing_token():
    """WebSocket with no token is rejected when a token is configured."""
    bridge = _make_mock_bridge()
    client = await _make_client(bridge, token=API_TOKEN)
    try:
        async with client.ws_connect("/ws/events") as ws:
            msg = await ws.receive_json(timeout=2.0)
            assert "error" in msg
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_ws_rejects_wrong_token():
    """WebSocket with wrong token is rejected."""
    bridge = _make_mock_bridge()
    client = await _make_client(bridge, token=API_TOKEN)
    try:
        async with client.ws_connect("/ws/events?token=wrong-token") as ws:
            msg = await ws.receive_json(timeout=2.0)
            assert "error" in msg
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_ws_accepts_correct_token():
    """WebSocket with correct token connects without error."""
    bridge = _make_mock_bridge()
    client = await _make_client(bridge, token=API_TOKEN)
    try:
        async with client.ws_connect(f"/ws/events?token={API_TOKEN}") as ws:
            assert not ws.closed
            await ws.close()
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_ws_empty_token_rejected():
    """Empty token is always rejected — fail-closed per R5 security fix."""
    bridge = _make_mock_bridge()
    # Server is configured with a real token; client sends no token → must be rejected.
    server_obj = APIServer(bridge, api_token=API_TOKEN, port=0)
    app = web.Application(
        middlewares=[
            cors_middleware,
            create_auth_middleware(server_obj._api_token),
        ]
    )
    server_obj._register_routes(app)
    client = TestClient(TestServer(app))
    await client.start_server()
    try:
        async with client.ws_connect("/ws/events") as ws:
            msg = await ws.receive_json(timeout=2.0)
            assert "error" in msg
    finally:
        await client.close()


# ---------------------------------------------------------------------------
# EventBus subscription lifecycle
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_ws_subscribes_to_event_bus():
    """Connecting a client subscribes to EventBus event types."""
    bridge = _make_mock_bridge(with_event_bus=True)
    client = await _make_client(bridge, token=API_TOKEN)
    try:
        async with client.ws_connect(f"/ws/events?token={API_TOKEN}") as ws:
            await asyncio.sleep(0.05)
            assert bridge._autonomy.event_bus.subscribe.call_count > 0
            await ws.close()
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_ws_unsubscribes_all_on_disconnect():
    """All EventBus subscriptions are cleaned up when the client disconnects."""
    bridge = _make_mock_bridge(with_event_bus=True)
    client = await _make_client(bridge, token=API_TOKEN)
    event_bus = bridge._autonomy.event_bus
    try:
        async with client.ws_connect(f"/ws/events?token={API_TOKEN}") as ws:
            await asyncio.sleep(0.05)
            sub_count = event_bus.subscribe.call_count
            await ws.close()
        await asyncio.sleep(0.05)
    finally:
        await client.close()

    # Every subscribe call must have a corresponding unsubscribe
    assert event_bus.unsubscribe.call_count == sub_count


# ---------------------------------------------------------------------------
# Type filtering
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_ws_type_filter_limits_subscriptions():
    """?types= query param limits which event types are subscribed."""
    bridge = _make_mock_bridge(with_event_bus=True)
    event_bus = bridge._autonomy.event_bus
    subscribed_types = []

    def _subscribe(event_type, callback):
        subscribed_types.append(event_type)
        return f"sub-{event_type}"

    event_bus.subscribe.side_effect = _subscribe

    client = await _make_client(bridge, token=API_TOKEN)
    try:
        async with client.ws_connect(
            f"/ws/events?token={API_TOKEN}&types=message.processed,health.changed"
        ) as ws:
            await asyncio.sleep(0.05)
            await ws.close()
        await asyncio.sleep(0.05)
    finally:
        await client.close()

    assert "message.processed" in subscribed_types
    assert "health.changed" in subscribed_types
    # Types not in the filter must not be subscribed
    assert "deploy.started" not in subscribed_types
    assert "failure.detected" not in subscribed_types


# ---------------------------------------------------------------------------
# Event push supervision (audit-2026-05-16.F.06, M-5 / #2079)
# ---------------------------------------------------------------------------
#
# The /ws/events subscriber path used to fire-and-forget ``ws.send_str(data)``
# via ``asyncio.ensure_future``, so send failures (closed connection,
# ConnectionResetError, etc.) were silently dropped. The fix wraps the send
# in a supervisor coroutine that:
#   * awaits the send
#   * on failure: increments ``websocket.event_push_failed``, logs a
#     warning with the connection id + error type, removes the dead ws
#     from ``self._ws_clients``
#   * on success: leaves the registry alone (regression guard)
#
# These tests drive the supervisor directly via the captured ``_on_event``
# callback so we don't have to round-trip through aiohttp's test server.


def _make_event(event_type: str = "message.processed"):
    """Construct a minimal event object that matches the subscriber's
    attribute access pattern in routes_websocket._on_event."""
    ev = MagicMock()
    ev.event_id = "evt-001"
    ev.event_type = event_type
    ev.payload = {"k": "v"}
    ev.source = "test"
    ev.timestamp = 0
    ev.correlation_id = "corr-001"
    return ev


@pytest.mark.asyncio
async def test_ws_event_push_success_preserves_client():
    """Successful broadcast does not drop the client and does not increment
    the failure metric — regression guard for the supervision change."""
    bridge = _make_mock_bridge(with_event_bus=True)
    metrics = MetricsCollector(data_dir="/tmp/test-ws-metrics")
    bridge._metrics = metrics

    server_obj = APIServer(bridge, api_token=API_TOKEN, port=0)
    healthy = MagicMock()
    healthy.closed = False
    healthy.send_str = AsyncMock(return_value=None)
    server_obj._ws_clients.append(healthy)

    callback = _build_on_event_for(server_obj, healthy)
    callback(_make_event())
    await asyncio.sleep(0.05)

    assert healthy.send_str.await_count == 1
    assert metrics.get_counter("websocket.event_push_failed") == 0
    assert healthy in server_obj._ws_clients


@pytest.mark.asyncio
async def test_ws_event_push_failure_increments_metric_and_evicts(caplog):
    """When a client's send raises, the supervisor increments the metric,
    logs a warning, and evicts the dead ws from ``_ws_clients``."""
    bridge = _make_mock_bridge(with_event_bus=True)
    metrics = MetricsCollector(data_dir="/tmp/test-ws-metrics")
    bridge._metrics = metrics

    # We don't go through aiohttp — drive the route handler directly with
    # mocks so we can force ``send_str`` to raise.
    server_obj = APIServer(bridge, api_token=API_TOKEN, port=0)
    fail_ws = MagicMock()
    fail_ws.closed = False
    fail_ws.send_str = AsyncMock(side_effect=ConnectionResetError("broken"))
    server_obj._ws_clients.append(fail_ws)

    # Build the subscriber callback directly by reusing the route mixin's
    # closure construction via a tiny shim.
    callback = _build_on_event_for(server_obj, fail_ws)

    with caplog.at_level(logging.WARNING, logger="bridge.api.routes_websocket"):
        callback(_make_event())
        # Allow the supervisor coroutine to run.
        await asyncio.sleep(0.05)

    assert metrics.get_counter("websocket.event_push_failed") == 1
    assert fail_ws not in server_obj._ws_clients
    # A warning was emitted with the error type in the record.
    failure_records = [
        r for r in caplog.records
        if r.levelno == logging.WARNING and "event push" in r.getMessage().lower()
    ]
    assert failure_records, "expected a warning log for the push failure"


@pytest.mark.asyncio
async def test_ws_event_push_partial_failure_keeps_healthy_clients():
    """With 3 clients where 2 raise on send, the healthy one survives and
    the registry ends with exactly that one."""
    bridge = _make_mock_bridge(with_event_bus=True)
    metrics = MetricsCollector(data_dir="/tmp/test-ws-metrics")
    bridge._metrics = metrics

    server_obj = APIServer(bridge, api_token=API_TOKEN, port=0)
    fail_a = MagicMock()
    fail_a.closed = False
    fail_a.send_str = AsyncMock(side_effect=ConnectionResetError("a"))
    fail_b = MagicMock()
    fail_b.closed = False
    fail_b.send_str = AsyncMock(side_effect=RuntimeError("b"))
    healthy = MagicMock()
    healthy.closed = False
    healthy.send_str = AsyncMock(return_value=None)

    for ws in (fail_a, fail_b, healthy):
        server_obj._ws_clients.append(ws)

    # Each ws has its own _on_event callback in the production path.
    for ws in (fail_a, fail_b, healthy):
        cb = _build_on_event_for(server_obj, ws)
        cb(_make_event())

    await asyncio.sleep(0.05)

    assert metrics.get_counter("websocket.event_push_failed") == 2
    assert healthy.send_str.await_count == 1
    assert fail_a not in server_obj._ws_clients
    assert fail_b not in server_obj._ws_clients
    assert healthy in server_obj._ws_clients
    assert server_obj._ws_clients == [healthy]


# ---------------------------------------------------------------------------
# Helpers for the supervision tests
# ---------------------------------------------------------------------------

def _build_on_event_for(server_obj: APIServer, ws):
    """Reproduce the subscriber-side ``_on_event`` closure used by the
    /ws/events handler, scoped to a single ``ws`` object.

    This mirrors the production path in ``routes_websocket._handle_ws_events``
    after the F.06 supervision change. Test-side only — the production
    closure is constructed inline in the handler.
    """
    import json

    from bridge.api import routes_websocket

    loop = asyncio.get_event_loop()

    def _on_event(event):
        if ws.closed:
            return
        data = json.dumps({
            "event_id": event.event_id,
            "event_type": event.event_type,
            "payload": event.payload,
            "source": event.source,
            "timestamp": event.timestamp,
            "correlation_id": event.correlation_id,
        })
        asyncio.ensure_future(
            routes_websocket._supervise_send(server_obj, ws, data),
            loop=loop,
        )

    return _on_event
