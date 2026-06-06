"""Issue #81 -- Peer coordination REST endpoints.

Standalone route handlers for cross-machine peer management.  Kept
separate from ``api_server.py`` to avoid merge conflicts.  Call
``register_peer_routes(app, registry)`` to wire everything into an
``aiohttp.web.Application``.

Note (#1613, 2026-05-11): the MergeQueue stub and its three associated
routes were removed.  The stub returned mock data and had no real
consumer; cross-machine merging was never wired live.  The follow-up
cleanup (Sprint E1.5, #1715) removed the now-unused third parameter
from ``register_peer_routes`` and dropped the matching gate in
``api_server.py`` that was silently keeping the peer routes unmounted
on a post-#1613 bridge.
"""

from __future__ import annotations

import json
import logging
import time

from aiohttp import web

from .peer_registry import PeerMetadata, PeerRecord, PeerRegistry, PeerStatus

log = logging.getLogger(__name__)


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _json(data: dict | list, status: int = 200) -> web.Response:
    return web.json_response(data, status=status)


def _error(code: str, message: str, status: int = 400) -> web.Response:
    return _json({"error": {"code": code, "message": message}}, status=status)


def _peer_to_dict(peer: PeerRecord) -> dict:
    return {
        "peer_id": peer.peer_id,
        "name": peer.name,
        "status": peer.status.value,
        "metadata": {
            "machine": peer.metadata.machine,
            "branch": peer.metadata.branch,
            "model": peer.metadata.model,
            "version": peer.metadata.version,
            "capabilities": list(peer.metadata.capabilities),
        },
        "last_heartbeat": peer.last_heartbeat,
        "registered_at": peer.registered_at,
        "tags": list(peer.tags),
    }


# ------------------------------------------------------------------
# Peer routes
# ------------------------------------------------------------------

async def handle_register_peer(request: web.Request) -> web.Response:
    """POST /api/peers -- register a new peer."""
    registry: PeerRegistry = request.app["peer_registry"]
    try:
        body = await request.json()
    except json.JSONDecodeError:
        return _error("INVALID_JSON", "Request body must be valid JSON")

    peer_id = body.get("peer_id", "")
    name = body.get("name", "")
    if not peer_id or not name:
        return _error("VALIDATION_ERROR", "peer_id and name are required")

    meta_raw = body.get("metadata", {})
    now = time.time()
    record = PeerRecord(
        peer_id=peer_id,
        name=name,
        status=PeerStatus.ONLINE,
        metadata=PeerMetadata(
            machine=meta_raw.get("machine", ""),
            branch=meta_raw.get("branch", ""),
            model=meta_raw.get("model", ""),
            version=meta_raw.get("version", ""),
            capabilities=meta_raw.get("capabilities", []),
        ),
        last_heartbeat=now,
        registered_at=now,
        tags=body.get("tags", []),
    )
    registry.register(record)
    return _json({"peer_id": peer_id, "status": "registered"}, status=201)


async def handle_list_peers(request: web.Request) -> web.Response:
    """GET /api/peers -- list all peers (optional ?status= filter)."""
    registry: PeerRegistry = request.app["peer_registry"]
    status_filter = request.query.get("status")
    ps = None
    if status_filter:
        try:
            ps = PeerStatus(status_filter)
        except ValueError:
            return _error("INVALID_STATUS", f"Unknown status: {status_filter}")
    peers = registry.list_peers(status=ps)
    return _json({"data": [_peer_to_dict(p) for p in peers]})


async def handle_get_peer(request: web.Request) -> web.Response:
    """GET /api/peers/{peer_id}"""
    registry: PeerRegistry = request.app["peer_registry"]
    peer_id = request.match_info["peer_id"]
    peer = registry.get(peer_id)
    if peer is None:
        return _error("NOT_FOUND", f"Peer {peer_id} not found", status=404)
    return _json(_peer_to_dict(peer))


async def handle_deregister_peer(request: web.Request) -> web.Response:
    """DELETE /api/peers/{peer_id}"""
    registry: PeerRegistry = request.app["peer_registry"]
    peer_id = request.match_info["peer_id"]
    removed = registry.deregister(peer_id)
    if not removed:
        return _error("NOT_FOUND", f"Peer {peer_id} not found", status=404)
    return _json({"peer_id": peer_id, "status": "deregistered"})


async def handle_heartbeat(request: web.Request) -> web.Response:
    """POST /api/peers/{peer_id}/heartbeat"""
    registry: PeerRegistry = request.app["peer_registry"]
    peer_id = request.match_info["peer_id"]
    updated = registry.update_heartbeat(peer_id)
    if not updated:
        return _error("NOT_FOUND", f"Peer {peer_id} not found", status=404)
    return _json({"peer_id": peer_id, "heartbeat": "ok"})


async def handle_send_message(request: web.Request) -> web.Response:
    """POST /api/peers/{peer_id}/message -- stub for inter-peer messaging."""
    registry: PeerRegistry = request.app["peer_registry"]
    peer_id = request.match_info["peer_id"]
    peer = registry.get(peer_id)
    if peer is None:
        return _error("NOT_FOUND", f"Peer {peer_id} not found", status=404)
    try:
        body = await request.json()
    except json.JSONDecodeError:
        return _error("INVALID_JSON", "Request body must be valid JSON")
    # Stub -- log and acknowledge
    log.info("Message to peer %s: %s", peer_id, body.get("type", "unknown"))
    return _json({"peer_id": peer_id, "status": "delivered"})


# ------------------------------------------------------------------
# Route registration
# ------------------------------------------------------------------

def register_peer_routes(
    app: web.Application,
    registry: PeerRegistry,
) -> None:
    """Attach all peer routes to *app*."""
    app["peer_registry"] = registry

    app.router.add_post("/api/peers", handle_register_peer)
    app.router.add_get("/api/peers", handle_list_peers)
    app.router.add_get("/api/peers/{peer_id}", handle_get_peer)
    app.router.add_delete("/api/peers/{peer_id}", handle_deregister_peer)
    app.router.add_post("/api/peers/{peer_id}/heartbeat", handle_heartbeat)
    app.router.add_post("/api/peers/{peer_id}/message", handle_send_message)
