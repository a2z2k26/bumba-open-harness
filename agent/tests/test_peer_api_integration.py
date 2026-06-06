"""Integration tests for Sprint 07.06 — peer routes wired into APIServer.

Sprint 07.04 wired ``PeerRegistrationManager`` into ``BridgeApp``'s
lifecycle so a ``PeerRegistry`` instance exists once the bridge starts
with ``peer_coordination_enabled = True``. Sprint 07.05 backed the
registry with SQLite.

The peer routes were defined in ``bridge.peer_api`` since 07.04 but
never bound to the running aiohttp app — operators hitting
``GET /api/peers`` got aiohttp's default 404. Sprint 07.06 calls
``register_peer_routes(app, registry)`` from
``APIServer._register_routes`` whenever the flag is on AND the
backing registry exists.

These tests pin the flag-on / flag-off contract:

  1. Flag on + register a peer through the registry → GET /api/peers
     returns the self-record.
  2. Flag off → GET /api/peers returns 404 (aiohttp default), proving
     the routes were never mounted.

Note (#1613, 2026-05-11): the MergeQueue stub + its three
``/api/merge-queue*`` routes were removed.  The merge-queue endpoint
integration test was retired alongside the stub.
"""

from __future__ import annotations

import time
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
from bridge.peer_registry import (
    PeerMetadata,
    PeerRecord,
    PeerRegistry,
    PeerStatus,
)

pytestmark = pytest.mark.socket  # binds localhost sockets via aiohttp TestServer

API_TOKEN = "peer-integration-test-token-0706"


# ---------------------------------------------------------------------------
# Fixtures (mirror the patterns in test_api_index.py / test_peer_api.py)
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_rate_limiter() -> None:
    """Replace module-level rate limiter with a generous bucket per test."""
    import bridge.api_server as _mod

    fresh = RateLimiter(rate=2.0, bucket_size=10_000)
    with patch.object(_mod, "_rate_limiter", fresh):
        yield


def _make_bridge(
    *,
    peer_flag_on: bool,
    peer_registry: PeerRegistry | None = None,
) -> MagicMock:
    """Construct a MagicMock BridgeApp with just enough wiring for APIServer.

    APIServer reads ``self._bridge._config.peer_coordination_enabled`` and
    ``self._bridge._peer_registry`` from inside ``_register_routes``;
    nothing else in the peer wiring path touches the bridge mock.

    Note (#1613): ``_merge_queue`` is still read from the bridge by
    ``api_server.py`` (locked file) as part of its gating conditional
    for ``register_peer_routes``.  ``MagicMock()`` returns a truthy
    sentinel for any attribute access by default, which keeps the
    flag-on path mounting the peer routes during these tests.  The
    real ``BridgeApp`` no longer sets ``_merge_queue`` at all — see the
    follow-up note in the PR body.
    """
    bridge = MagicMock()
    config = MagicMock()
    config.peer_coordination_enabled = peer_flag_on
    bridge._config = config

    bridge._peer_registry = peer_registry

    # Components other handlers touch — kept None so introspective routes
    # like /api/cost / /api/agents stay quiet during the response-shape
    # tests below (we never hit them, but APIServer.__init__ doesn't).
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
    bridge._db = AsyncMock()
    return bridge


def _make_app(server: APIServer) -> web.Application:
    app = web.Application(
        middlewares=[
            cors_middleware,
            create_auth_middleware(server._api_token),
        ]
    )
    server._register_routes(app)
    return app


async def _make_client(app: web.Application) -> TestClient:
    ts = TestServer(app)
    client = TestClient(ts)
    await client.start_server()
    return client


def _auth() -> dict[str, str]:
    return {"Authorization": f"Bearer {API_TOKEN}"}


def _seed_self_record(registry: PeerRegistry, peer_id: str = "self-mac") -> None:
    """Insert a self-style PeerRecord directly into the registry.

    Mirrors what ``PeerRegistrationManager.start()`` would do once the
    bridge boots with the flag on; we skip the manager here because this
    test exercises only the API surface, not the registration lifecycle.
    """
    now = time.time()
    record = PeerRecord(
        peer_id=peer_id,
        name="bridge-self",
        status=PeerStatus.ONLINE,
        metadata=PeerMetadata(
            machine="mac-mini",
            branch="main",
            model="claude-opus-4-7",
            version="1.0.0",
            capabilities=["merge", "deploy"],
        ),
        last_heartbeat=now,
        registered_at=now,
        tags=["self"],
    )
    registry.register(record)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_peers_endpoint_returns_self_record_when_flag_on() -> None:
    """Flag-on + a registered self-record → GET /api/peers exposes it.

    Proves register_peer_routes() ran and the handler reads the live
    PeerRegistry instance the bridge constructs at startup.
    """
    registry = PeerRegistry(db_path=":memory:")
    _seed_self_record(registry, peer_id="self-mac")

    bridge = _make_bridge(
        peer_flag_on=True,
        peer_registry=registry,
    )
    server = APIServer(bridge, api_token=API_TOKEN)
    app = _make_app(server)

    client = await _make_client(app)
    try:
        resp = await client.get("/api/peers", headers=_auth())
        assert resp.status == 200
        body = await resp.json()
    finally:
        await client.close()

    # peer_api.handle_list_peers wraps results in {"data": [...]}.
    assert isinstance(body.get("data"), list)
    peer_ids = [peer["peer_id"] for peer in body["data"]]
    assert "self-mac" in peer_ids, body


@pytest.mark.asyncio
async def test_peers_endpoint_404_when_flag_off() -> None:
    """Flag-off → register_peer_routes() never runs; route resolves to 404.

    Pins the contract that this sprint is purely additive: existing
    deployments without `peer_coordination_enabled = true` see no new
    routes and no behavior change.
    """
    bridge = _make_bridge(
        peer_flag_on=False,
        peer_registry=None,
    )
    # The locked ``api_server.py`` gates ``register_peer_routes`` on
    # ``_merge_queue is not None`` (#1613 follow-up).  Force the mock
    # attribute to ``None`` so the conditional fails and the routes
    # stay unmounted, matching production behaviour with the flag off.
    bridge._merge_queue = None
    server = APIServer(bridge, api_token=API_TOKEN)
    app = _make_app(server)

    client = await _make_client(app)
    try:
        resp = await client.get("/api/peers", headers=_auth())
        assert resp.status == 404
    finally:
        await client.close()
