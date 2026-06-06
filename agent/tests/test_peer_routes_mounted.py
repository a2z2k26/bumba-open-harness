"""Sprint E1.5 (#1715) -- peer routes mount when flag is on, post-#1613.

Background: PR #1613 (2026-05-11) removed the MergeQueue stub and the
``BridgeApp._merge_queue`` attribute.  ``api_server.py`` still gated
``register_peer_routes`` on ``getattr(self._bridge, "_merge_queue", None)
is not None`` -- so on a real, post-#1613 BridgeApp the gate always
failed and the 6 peer routes silently never mounted, even when the
operator set ``peer_coordination_enabled = true``.

This test pins the post-fix contract using a bridge mock that does NOT
carry a ``_merge_queue`` attribute (the production shape since #1613).

Note on layering: ``test_peer_api_integration.py`` already exercises
flag-on (with a MagicMock that returned a truthy default for any attr
access, which masked the bug) and flag-off.  This file is intentionally
narrower -- it verifies the exact failure mode E1.5 fixes.
"""

from __future__ import annotations

import time
from unittest.mock import AsyncMock, patch

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

pytestmark = pytest.mark.socket

API_TOKEN = "peer-mount-test-token-e1-5"


class _BridgeWithoutMergeQueue:
    """Minimal BridgeApp stand-in that does NOT expose ``_merge_queue``.

    Mirrors the production shape post-#1613: the attribute simply does
    not exist on the bridge instance.  Using a plain class rather than
    ``MagicMock`` so attribute access raises ``AttributeError`` (which
    ``getattr(..., None)`` handles) instead of returning a truthy mock.
    """

    def __init__(self, *, peer_flag_on: bool, peer_registry: PeerRegistry | None) -> None:
        # APIServer reads ``self._bridge._config.peer_coordination_enabled``.
        class _Config:
            pass

        cfg = _Config()
        cfg.peer_coordination_enabled = peer_flag_on
        self._config = cfg

        self._peer_registry = peer_registry

        # Components other handlers may probe via getattr-with-None.
        self._health_server = None
        self._tmux_agents = None
        self._session_mgr = None
        self._cost_tracker = None
        self._autonomy = None
        self._memory = None
        self._commands = None
        self._metrics = None
        self._tracer = None
        self._task_queue = None
        self._task_pipeline = None
        self._quality_gate = None
        self._webhook_receiver = None
        self._db = AsyncMock()
        # Deliberately NO ``self._merge_queue`` -- matches post-#1613 reality.


@pytest.fixture(autouse=True)
def _reset_rate_limiter() -> None:
    import bridge.api_server as _mod

    fresh = RateLimiter(rate=2.0, bucket_size=10_000)
    with patch.object(_mod, "_rate_limiter", fresh):
        yield


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


@pytest.mark.asyncio
async def test_peer_routes_mount_when_flag_on_and_no_merge_queue_attr() -> None:
    """E1.5 keystone: flag on + registry + NO merge-queue attr -> routes mount.

    Pre-fix, the dropped clause in api_server.py caused this assertion
    to fail (route returned 404 because register_peer_routes was never
    called).  Post-fix, the gate is ``peer_flag_on and peer_registry is
    not None`` and the routes mount.
    """
    registry = PeerRegistry(db_path=":memory:")
    _seed_self_record(registry, peer_id="self-mac")

    bridge = _BridgeWithoutMergeQueue(peer_flag_on=True, peer_registry=registry)
    assert not hasattr(bridge, "_merge_queue"), (
        "Test pre-condition: bridge must NOT carry the removed attribute (post-#1613)."
    )
    server = APIServer(bridge, api_token=API_TOKEN)
    app = _make_app(server)

    client = await _make_client(app)
    try:
        resp = await client.get("/api/peers", headers=_auth())
        assert resp.status == 200, (
            f"Expected /api/peers to mount and return 200; got {resp.status}. "
            "If 404, register_peer_routes was never called -- E1.5 regression."
        )
        body = await resp.json()
    finally:
        await client.close()

    peer_ids = [peer["peer_id"] for peer in body.get("data", [])]
    assert "self-mac" in peer_ids, body


@pytest.mark.asyncio
async def test_peer_routes_absent_when_flag_off() -> None:
    """Flag-off still keeps routes unmounted (additive change only)."""
    bridge = _BridgeWithoutMergeQueue(peer_flag_on=False, peer_registry=None)
    server = APIServer(bridge, api_token=API_TOKEN)
    app = _make_app(server)

    client = await _make_client(app)
    try:
        resp = await client.get("/api/peers", headers=_auth())
        assert resp.status == 404
    finally:
        await client.close()
