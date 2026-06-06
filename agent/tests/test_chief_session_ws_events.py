"""Z4-S61 (#1405) — chief_session.* events on WebSocket /ws/events stream.

Exercises the ``?filter=<prefix>`` query param added to the existing
``/ws/events`` handler. Tests use a real :class:`bridge.event_bus.EventBus`
wired onto a mock bridge so callbacks fire end-to-end through the WS
handler — no fake EventBus, no fake subscribe loop.

Sprint deliverables tested:
1. Unfiltered subscription receives a published ``chief_session.created``
   event.
2. ``?filter=chief_session.`` filters out non-matching event families.
3. Three concurrent clients (filter=chief_session., filter=chief_dispatcher.,
   no filter) each see exactly the right subset.
4. ``?filter=chief_session.created`` (full type) receives only that exact
   type — prefix is exclusive.
5. Default behaviour (no filter) still forwards ALL known event types,
   not just chief_session.* ones — back-compat preserved.
"""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from bridge.api_server import (
    APIServer,
    cors_middleware,
    create_auth_middleware,
)
from bridge.event_bus import EventBus

pytestmark = pytest.mark.socket  # binds localhost sockets via aiohttp TestServer

API_TOKEN = "test-z4-s61-token"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_mock_bridge_with_real_event_bus() -> tuple[MagicMock, EventBus]:
    """Mock bridge wired with a real EventBus.

    The WS handler subscribes via ``bridge._autonomy.event_bus.subscribe``
    and unsubscribes via ``unsubscribe``. Using a real EventBus here means
    the per-event-type fan-out is exercised exactly the way it is in
    production — callbacks fire on ``bus.publish(...)`` and ``ws.send_str``
    schedules go through the running loop.
    """
    bridge = MagicMock()
    bridge._config = MagicMock()
    bridge._config.data_dir = "/tmp/test-z4-s61-data"
    bridge._config.operator_discord_id = "test-operator"
    bridge._db = AsyncMock()
    bridge._health_server = None
    bridge._tmux_agents = None
    bridge._session_mgr = None
    bridge._cost_tracker = None
    bridge._memory = None
    bridge._commands = None
    bridge._metrics = None
    bridge._tracer = None
    bridge._task_queue = None
    bridge._task_pipeline = None
    bridge._quality_gate = None
    bridge._webhook_receiver = None

    bus = EventBus(data_dir=None)  # no persistence, in-memory only
    autonomy = MagicMock()
    autonomy.event_bus = bus
    bridge._autonomy = autonomy
    return bridge, bus


async def _make_client(bridge: MagicMock) -> TestClient:
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
    return client


async def _drain(ws, *, timeout: float = 0.6) -> list[dict]:
    """Read all pending JSON frames from the WS until ``timeout`` of silence."""
    received: list[dict] = []
    while True:
        try:
            msg = await asyncio.wait_for(ws.receive(), timeout=timeout)
        except asyncio.TimeoutError:
            return received
        # ``receive()`` may return a TEXT/BINARY/CLOSE/CLOSED frame;
        # only TEXT frames carry our JSON payloads.
        if msg.type.name == "TEXT":
            try:
                received.append(json.loads(msg.data))
            except Exception:
                continue
        elif msg.type.name in ("CLOSE", "CLOSING", "CLOSED", "ERROR"):
            return received


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_unfiltered_client_receives_chief_session_created():
    """A client without a filter sees a ``chief_session.created`` publish.

    Verifies the event arrives at the WS — proves the new event type is
    in EVENT_TYPES and the existing fan-out picks it up.
    """
    bridge, bus = _make_mock_bridge_with_real_event_bus()
    client = await _make_client(bridge)
    try:
        async with client.ws_connect(
            f"/ws/events?token={API_TOKEN}"
        ) as ws:
            # Allow the handler to register its subscriptions before we
            # publish (the per-event-type subscribe loop is sync but we
            # are scheduled across the asyncio loop, so a brief yield
            # avoids a race).
            await asyncio.sleep(0.05)
            bus.publish(
                "chief_session.created",
                {"session_id": "sess-abc", "department": "engineering"},
            )
            received = await _drain(ws)
            await ws.close()
    finally:
        await client.close()

    types = [m["event_type"] for m in received]
    assert "chief_session.created" in types
    payload = next(m for m in received if m["event_type"] == "chief_session.created")
    assert payload["payload"]["session_id"] == "sess-abc"
    assert payload["payload"]["department"] == "engineering"


@pytest.mark.asyncio
async def test_prefix_filter_excludes_non_matching_families():
    """``?filter=chief_session.`` only forwards chief_session events."""
    bridge, bus = _make_mock_bridge_with_real_event_bus()
    client = await _make_client(bridge)
    try:
        async with client.ws_connect(
            f"/ws/events?token={API_TOKEN}&filter=chief_session."
        ) as ws:
            await asyncio.sleep(0.05)
            bus.publish("chief_session.created", {"session_id": "s1"})
            bus.publish("chief_dispatcher.routed", {"session_id": "s1"})
            bus.publish("health.changed", {"component": "bridge"})
            received = await _drain(ws)
            await ws.close()
    finally:
        await client.close()

    types = [m["event_type"] for m in received]
    assert "chief_session.created" in types
    assert "chief_dispatcher.routed" not in types
    assert "health.changed" not in types


@pytest.mark.asyncio
async def test_concurrent_clients_with_different_filters():
    """Three clients with different filters see disjoint subsets.

    Client A: ``filter=chief_session.`` -> only chief_session events.
    Client B: ``filter=chief_dispatcher.`` -> only chief_dispatcher events.
    Client C: no filter -> all events.
    """
    bridge, bus = _make_mock_bridge_with_real_event_bus()
    client = await _make_client(bridge)
    try:
        async with client.ws_connect(
            f"/ws/events?token={API_TOKEN}&filter=chief_session."
        ) as ws_a, client.ws_connect(
            f"/ws/events?token={API_TOKEN}&filter=chief_dispatcher."
        ) as ws_b, client.ws_connect(
            f"/ws/events?token={API_TOKEN}"
        ) as ws_c:
            await asyncio.sleep(0.05)
            bus.publish("chief_session.created", {"session_id": "s1"})
            bus.publish("chief_dispatcher.routed", {"session_id": "s1"})
            bus.publish("health.changed", {"component": "bridge"})

            received_a = await _drain(ws_a)
            received_b = await _drain(ws_b)
            received_c = await _drain(ws_c)
            await ws_a.close()
            await ws_b.close()
            await ws_c.close()
    finally:
        await client.close()

    types_a = [m["event_type"] for m in received_a]
    types_b = [m["event_type"] for m in received_b]
    types_c = [m["event_type"] for m in received_c]

    assert types_a == ["chief_session.created"]
    assert types_b == ["chief_dispatcher.routed"]
    # Client C sees all three (order is publish order).
    assert "chief_session.created" in types_c
    assert "chief_dispatcher.routed" in types_c
    assert "health.changed" in types_c


@pytest.mark.asyncio
async def test_filter_with_full_event_type_is_exact_match():
    """``filter=chief_session.created`` does NOT match ``chief_session.state_changed``.

    Documents the prefix-match contract: the filter is treated literally
    as a prefix. ``chief_session.created`` is not a prefix of
    ``chief_session.state_changed`` (the next char after the filter is
    ``_`` for state_changed but the filter ends in ``d``), so only the
    exact event type is delivered.
    """
    bridge, bus = _make_mock_bridge_with_real_event_bus()
    client = await _make_client(bridge)
    try:
        async with client.ws_connect(
            f"/ws/events?token={API_TOKEN}&filter=chief_session.created"
        ) as ws:
            await asyncio.sleep(0.05)
            bus.publish("chief_session.created", {"session_id": "s1"})
            bus.publish("chief_session.state_changed", {"session_id": "s1"})
            received = await _drain(ws)
            await ws.close()
    finally:
        await client.close()

    types = [m["event_type"] for m in received]
    assert "chief_session.created" in types
    assert "chief_session.state_changed" not in types


@pytest.mark.asyncio
async def test_no_filter_preserves_pre_z4_s61_behaviour():
    """A client with no filter still sees the full pre-existing event surface.

    Publishes one event from the existing surface (``health.changed``)
    plus one from the new surface (``chief_session.created``). Both
    must arrive — back-compat for connected dashboards is the load-bearing
    constraint of this sprint.
    """
    bridge, bus = _make_mock_bridge_with_real_event_bus()
    client = await _make_client(bridge)
    try:
        async with client.ws_connect(
            f"/ws/events?token={API_TOKEN}"
        ) as ws:
            await asyncio.sleep(0.05)
            bus.publish("health.changed", {"component": "bridge"})
            bus.publish("chief_session.created", {"session_id": "s1"})
            received = await _drain(ws)
            await ws.close()
    finally:
        await client.close()

    types = [m["event_type"] for m in received]
    assert "health.changed" in types
    assert "chief_session.created" in types
