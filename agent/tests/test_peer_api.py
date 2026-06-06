"""Unit tests for bridge.peer_api (Issue #81).

Uses aiohttp.test_utils directly (no pytest-aiohttp dependency).

Sprint 07.05 (#769): PeerRegistry now persists to SQLite. To keep these
tests isolated from each other (and from any leftover ``data/memory.db``
in the working tree), every PeerRegistry constructed here is given an
in-process ephemeral DB via ``:memory:``.
"""

from __future__ import annotations


import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from bridge.peer_api import register_peer_routes
from bridge.peer_registry import PeerRegistry, PeerStatus

pytestmark = pytest.mark.socket  # binds localhost sockets via aiohttp TestServer


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _ephemeral_registry() -> PeerRegistry:
    """A throwaway in-memory PeerRegistry for one test."""
    return PeerRegistry(db_path=":memory:")


def _make_app(
    registry: PeerRegistry | None = None,
) -> web.Application:
    app = web.Application()
    register_peer_routes(
        app,
        registry or _ephemeral_registry(),
    )
    return app


def _sample_peer_body(peer_id: str = "peer-1", name: str = "mac/main") -> dict:
    return {
        "peer_id": peer_id,
        "name": name,
        "metadata": {
            "machine": "mac-mini",
            "branch": "main",
            "model": "claude-opus-4-6",
            "version": "1.0.0",
            "capabilities": ["merge", "deploy"],
        },
        "tags": ["production"],
    }


# ------------------------------------------------------------------
# POST /api/peers
# ------------------------------------------------------------------

class TestRegisterPeer:
    @pytest.mark.asyncio
    async def test_register_success(self) -> None:
        async with TestClient(TestServer(_make_app())) as client:
            resp = await client.post("/api/peers", json=_sample_peer_body())
            assert resp.status == 201
            data = await resp.json()
            assert data["peer_id"] == "peer-1"
            assert data["status"] == "registered"

    @pytest.mark.asyncio
    async def test_register_missing_peer_id(self) -> None:
        async with TestClient(TestServer(_make_app())) as client:
            resp = await client.post("/api/peers", json={"name": "x"})
            assert resp.status == 400
            data = await resp.json()
            assert data["error"]["code"] == "VALIDATION_ERROR"

    @pytest.mark.asyncio
    async def test_register_missing_name(self) -> None:
        async with TestClient(TestServer(_make_app())) as client:
            resp = await client.post("/api/peers", json={"peer_id": "x"})
            assert resp.status == 400

    @pytest.mark.asyncio
    async def test_register_invalid_json(self) -> None:
        async with TestClient(TestServer(_make_app())) as client:
            resp = await client.post(
                "/api/peers",
                data=b"not-json",
                headers={"Content-Type": "application/json"},
            )
            assert resp.status == 400


# ------------------------------------------------------------------
# GET /api/peers
# ------------------------------------------------------------------

class TestListPeers:
    @pytest.mark.asyncio
    async def test_list_empty(self) -> None:
        async with TestClient(TestServer(_make_app())) as client:
            resp = await client.get("/api/peers")
            assert resp.status == 200
            data = await resp.json()
            assert data["data"] == []

    @pytest.mark.asyncio
    async def test_list_after_register(self) -> None:
        async with TestClient(TestServer(_make_app())) as client:
            await client.post("/api/peers", json=_sample_peer_body("a"))
            await client.post("/api/peers", json=_sample_peer_body("b"))
            resp = await client.get("/api/peers")
            data = await resp.json()
            assert len(data["data"]) == 2

    @pytest.mark.asyncio
    async def test_list_filter_by_status(self) -> None:
        registry = _ephemeral_registry()
        async with TestClient(TestServer(_make_app(registry))) as client:
            await client.post("/api/peers", json=_sample_peer_body("a"))
            await client.post("/api/peers", json=_sample_peer_body("b"))
            registry.update_status("b", PeerStatus.OFFLINE)
            resp = await client.get("/api/peers?status=online")
            data = await resp.json()
            assert len(data["data"]) == 1
            assert data["data"][0]["peer_id"] == "a"

    @pytest.mark.asyncio
    async def test_list_invalid_status(self) -> None:
        async with TestClient(TestServer(_make_app())) as client:
            resp = await client.get("/api/peers?status=bogus")
            assert resp.status == 400


# ------------------------------------------------------------------
# GET /api/peers/{peer_id}
# ------------------------------------------------------------------

class TestGetPeer:
    @pytest.mark.asyncio
    async def test_get_existing(self) -> None:
        async with TestClient(TestServer(_make_app())) as client:
            await client.post("/api/peers", json=_sample_peer_body("p1"))
            resp = await client.get("/api/peers/p1")
            assert resp.status == 200
            data = await resp.json()
            assert data["peer_id"] == "p1"
            assert data["status"] == "online"
            assert data["metadata"]["machine"] == "mac-mini"

    @pytest.mark.asyncio
    async def test_get_missing(self) -> None:
        async with TestClient(TestServer(_make_app())) as client:
            resp = await client.get("/api/peers/nope")
            assert resp.status == 404


# ------------------------------------------------------------------
# DELETE /api/peers/{peer_id}
# ------------------------------------------------------------------

class TestDeregisterPeer:
    @pytest.mark.asyncio
    async def test_deregister_existing(self) -> None:
        async with TestClient(TestServer(_make_app())) as client:
            await client.post("/api/peers", json=_sample_peer_body("p1"))
            resp = await client.delete("/api/peers/p1")
            assert resp.status == 200
            data = await resp.json()
            assert data["status"] == "deregistered"
            # Verify gone
            resp2 = await client.get("/api/peers/p1")
            assert resp2.status == 404

    @pytest.mark.asyncio
    async def test_deregister_missing(self) -> None:
        async with TestClient(TestServer(_make_app())) as client:
            resp = await client.delete("/api/peers/nope")
            assert resp.status == 404


# ------------------------------------------------------------------
# POST /api/peers/{peer_id}/heartbeat
# ------------------------------------------------------------------

class TestHeartbeat:
    @pytest.mark.asyncio
    async def test_heartbeat_success(self) -> None:
        async with TestClient(TestServer(_make_app())) as client:
            await client.post("/api/peers", json=_sample_peer_body("p1"))
            resp = await client.post("/api/peers/p1/heartbeat")
            assert resp.status == 200
            data = await resp.json()
            assert data["heartbeat"] == "ok"

    @pytest.mark.asyncio
    async def test_heartbeat_missing_peer(self) -> None:
        async with TestClient(TestServer(_make_app())) as client:
            resp = await client.post("/api/peers/nope/heartbeat")
            assert resp.status == 404


# ------------------------------------------------------------------
# POST /api/peers/{peer_id}/message
# ------------------------------------------------------------------

class TestSendMessage:
    @pytest.mark.asyncio
    async def test_message_success(self) -> None:
        async with TestClient(TestServer(_make_app())) as client:
            await client.post("/api/peers", json=_sample_peer_body("p1"))
            resp = await client.post(
                "/api/peers/p1/message",
                json={"type": "work_order", "data": {"task": "build"}},
            )
            assert resp.status == 200
            data = await resp.json()
            assert data["status"] == "delivered"

    @pytest.mark.asyncio
    async def test_message_missing_peer(self) -> None:
        async with TestClient(TestServer(_make_app())) as client:
            resp = await client.post(
                "/api/peers/nope/message",
                json={"type": "ping"},
            )
            assert resp.status == 404

    @pytest.mark.asyncio
    async def test_message_invalid_json(self) -> None:
        async with TestClient(TestServer(_make_app())) as client:
            await client.post("/api/peers", json=_sample_peer_body("p1"))
            resp = await client.post(
                "/api/peers/p1/message",
                data=b"not-json",
                headers={"Content-Type": "application/json"},
            )
            assert resp.status == 400


