"""Tests for the introspective API index handler (Sprint 07.02).

`_handle_api_index` previously hand-listed 34 endpoints while
`_register_routes` had grown to 41. This sprint rewires the handler to
walk `self._app_ref.router.routes()` so the response can never drift
from the routes actually mounted.

The tests below pin three guarantees:

  1. The response advertises every public route registered by
     `_register_routes` (count parity).
  2. `/internal/...` paths are filtered out, even if registered.
  3. Adding a new public route via the same router automatically
     surfaces in the index — no human edit required.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from bridge.api_server import (
    APIServer,
    RateLimiter,
    _enumerate_public_routes,
    cors_middleware,
    create_auth_middleware,
)

pytestmark = pytest.mark.socket  # binds localhost sockets via aiohttp TestServer

API_TOKEN = "idx-test-token-7-02"


# ---------------------------------------------------------------------------
# Fixtures (mirrors the pattern in test_api_server_extended.py)
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _reset_rate_limiter():
    """Replace module-level rate limiter with a generous bucket per test."""
    import bridge.api_server as _mod

    fresh = RateLimiter(rate=2.0, bucket_size=10_000)
    with patch.object(_mod, "_rate_limiter", fresh):
        yield


def _make_bridge() -> MagicMock:
    bridge = MagicMock()
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


def _public_route_keys(app: web.Application) -> set[tuple[str, str]]:
    """Return the (method, path) pairs we expect the index to surface.

    Mirrors the filter rules in `_enumerate_public_routes`:
      - exclude HEAD twins
      - exclude /internal/...
      - include /healthz, /api/..., /ws/...
    """
    keys: set[tuple[str, str]] = set()
    for route in app.router.routes():
        resource = getattr(route, "resource", None)
        if resource is None:
            continue
        path = getattr(resource, "canonical", None)
        if not isinstance(path, str):
            continue
        method = (route.method or "").upper()
        if method == "HEAD":
            continue
        if path.startswith("/internal/"):
            continue
        if (
            path == "/healthz"
            or path == "/api"
            or path.startswith("/api/")
            or path.startswith("/ws/")
        ):
            keys.add((method, path))
    return keys


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_api_index_lists_every_registered_route() -> None:
    """The /api response.count must equal the number of public routes."""
    server = APIServer(_make_bridge(), api_token=API_TOKEN)
    app = _make_app(server)
    expected = _public_route_keys(app)

    # Sanity-check: the introspection helper agrees with the test's filter.
    introspected = _enumerate_public_routes(app)
    introspected_keys = {(r["method"], r["path"]) for r in introspected}
    assert introspected_keys == expected, (
        "Helper output diverges from the locally re-derived filter — "
        "test or implementation is wrong."
    )

    client = await _make_client(app)
    try:
        resp = await client.get("/api", headers=_auth())
        assert resp.status == 200
        body = await resp.json()
    finally:
        await client.close()

    assert body["count"] == len(expected)
    response_keys = {(r["method"], r["path"]) for r in body["routes"]}
    assert response_keys == expected


@pytest.mark.asyncio
async def test_api_index_excludes_internal_routes() -> None:
    """Routes under /internal/ must never appear in the public index."""
    server = APIServer(_make_bridge(), api_token=API_TOKEN)
    app = _make_app(server)

    async def _internal_handler(request: web.Request) -> web.Response:
        return web.json_response({"ok": True})

    app.router.add_get("/internal/probe", _internal_handler)
    app.router.add_post("/internal/secret/{id}", _internal_handler)

    client = await _make_client(app)
    try:
        resp = await client.get("/api", headers=_auth())
        body = await resp.json()
    finally:
        await client.close()

    paths = [r["path"] for r in body["routes"]]
    assert not any(p.startswith("/internal/") for p in paths), paths


@pytest.mark.asyncio
async def test_api_index_uses_introspection_for_new_routes() -> None:
    """Adding a route after _register_routes runs must surface in the index.

    This proves the handler reads the live router, not a baked-in list.
    """
    server = APIServer(_make_bridge(), api_token=API_TOKEN)
    app = _make_app(server)
    baseline_count = len(_enumerate_public_routes(app))

    async def _new_handler(request: web.Request) -> web.Response:
        return web.json_response({"ok": True})

    app.router.add_get("/api/sprint0702/probe", _new_handler)

    client = await _make_client(app)
    try:
        resp = await client.get("/api", headers=_auth())
        body = await resp.json()
    finally:
        await client.close()

    paths = [r["path"] for r in body["routes"]]
    assert "/api/sprint0702/probe" in paths
    assert body["count"] == baseline_count + 1


@pytest.mark.asyncio
async def test_api_index_suppresses_head_twins() -> None:
    """aiohttp auto-mirrors GET as HEAD; the index must surface GET only."""
    server = APIServer(_make_bridge(), api_token=API_TOKEN)
    app = _make_app(server)

    client = await _make_client(app)
    try:
        resp = await client.get("/api", headers=_auth())
        body = await resp.json()
    finally:
        await client.close()

    methods = {r["method"] for r in body["routes"]}
    assert "HEAD" not in methods, methods


@pytest.mark.asyncio
async def test_api_index_includes_self_and_healthz() -> None:
    """/api should list itself and /healthz so operators see the full surface."""
    server = APIServer(_make_bridge(), api_token=API_TOKEN)
    app = _make_app(server)

    client = await _make_client(app)
    try:
        resp = await client.get("/api", headers=_auth())
        body = await resp.json()
    finally:
        await client.close()

    pairs = {(r["method"], r["path"]) for r in body["routes"]}
    assert ("GET", "/api") in pairs
    assert ("GET", "/healthz") in pairs


def test_enumerate_public_routes_handles_none_app() -> None:
    """Defensive: helper returns [] when called before start()."""
    assert _enumerate_public_routes(None) == []


def test_enumerate_public_routes_dedupes_synthetic() -> None:
    """Belt-and-suspenders: dedup logic works if routes() ever yields dups.

    aiohttp's `add_get` itself rejects duplicate (method, path) pairs at
    registration time, so this can't happen organically — but the helper
    still de-dupes defensively. Verified by feeding a synthesized
    routes-iterable through a stub object that mirrors the aiohttp shape.
    """
    class _StubResource:
        def __init__(self, path: str) -> None:
            self.canonical = path

    class _StubRoute:
        def __init__(self, method: str, path: str) -> None:
            self.method = method
            self.resource = _StubResource(path)

    class _StubRouter:
        def routes(self) -> list[_StubRoute]:  # type: ignore[override]
            return [
                _StubRoute("GET", "/api/dup"),
                _StubRoute("GET", "/api/dup"),
            ]

    class _StubApp:
        router = _StubRouter()

    routes = _enumerate_public_routes(_StubApp())  # type: ignore[arg-type]
    paths = [r["path"] for r in routes]
    assert paths.count("/api/dup") == 1
