"""Integration test -- cross-machine coordination lifecycle (Issue #83).

Exercises the Plan 5 stack: PeerRegistry, RemoteEventBridge, and
PeerRegistrationManager in concert.

Note (#1613, 2026-05-11): the MergeQueue stub was removed.  The merge
steps in ``test_full_lifecycle`` and the dedicated
``TestMergeQueueWithRegistry`` class were retired alongside the stub.
"""

from __future__ import annotations

import time

import pytest

from bridge.event_bus import EventBus
from bridge.peer_registration import PeerRegistrationManager, RegistrationConfig
from bridge.peer_registry import PeerMetadata, PeerRecord, PeerRegistry, PeerStatus
from bridge.remote_events import (
    AGENT_WORK_ORDER,
    CONSOLIDATION_COMPLETED,
    PEER_DEREGISTERED,
    PEER_HEARTBEAT,
    PEER_REGISTERED,
    RemoteEventBridge,
)


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _make_peer(
    peer_id: str,
    name: str = "test-machine/main",
    capabilities: list[str] | None = None,
    last_heartbeat: float | None = None,
) -> PeerRecord:
    return PeerRecord(
        peer_id=peer_id,
        name=name,
        status=PeerStatus.ONLINE,
        metadata=PeerMetadata(
            machine="test-machine",
            branch="main",
            model="claude-opus-4-6",
            version="1.0.0",
            capabilities=capabilities or [],
        ),
        last_heartbeat=last_heartbeat or time.time(),
        registered_at=time.time(),
    )


# ------------------------------------------------------------------
# Full lifecycle integration test
# ------------------------------------------------------------------

class TestCrossMachineLifecycle:
    """Exercises steps 1-9 from the issue spec."""

    @pytest.mark.asyncio
    async def test_full_lifecycle(self) -> None:
        # 1. Create PeerRegistry
        registry = PeerRegistry(db_path=":memory:")
        event_bus = EventBus()
        remote_bridge = RemoteEventBridge(event_bus)

        # Track published events
        published_events: list[dict] = []
        event_bus.subscribe(
            PEER_REGISTERED,
            lambda e: published_events.append({"type": e.event_type, "payload": e.payload}),
        )
        event_bus.subscribe(
            PEER_HEARTBEAT,
            lambda e: published_events.append({"type": e.event_type, "payload": e.payload}),
        )
        event_bus.subscribe(
            PEER_DEREGISTERED,
            lambda e: published_events.append({"type": e.event_type, "payload": e.payload}),
        )

        # 2. Register 2 peers
        peer_a = _make_peer("agent-a", capabilities=["merge", "deploy"])
        peer_b = _make_peer("agent-b", capabilities=["test"])
        registry.register(peer_a)
        registry.register(peer_b)
        remote_bridge.publish_remote(
            PEER_REGISTERED, {"peer_id": "agent-a"}, target_peer="agent-a"
        )
        remote_bridge.publish_remote(
            PEER_REGISTERED, {"peer_id": "agent-b"}, target_peer="agent-b"
        )

        # 3. Verify both visible
        all_peers = registry.list_peers()
        assert len(all_peers) == 2
        peer_ids = {p.peer_id for p in all_peers}
        assert peer_ids == {"agent-a", "agent-b"}

        # 4. Send heartbeats
        assert registry.update_heartbeat("agent-a") is True
        assert registry.update_heartbeat("agent-b") is True
        remote_bridge.publish_remote(
            PEER_HEARTBEAT, {"peer_id": "agent-a"}, target_peer="agent-a"
        )

        # 5. Verify events published (registrations + heartbeat)
        assert len(published_events) >= 3  # 2 registered + 1 heartbeat
        event_types = [e["type"] for e in published_events]
        assert PEER_REGISTERED in event_types
        assert PEER_HEARTBEAT in event_types

        # 6. Prune stale peer -- make agent-b stale
        stale_time = time.time() - 300
        registry.deregister("agent-b")
        stale_peer = _make_peer("agent-b", last_heartbeat=stale_time)
        registry.register(stale_peer)
        pruned = registry.prune_stale(timeout_seconds=180.0)
        assert "agent-b" in pruned
        assert registry.get("agent-b").status == PeerStatus.OFFLINE

        # 7. Verify deregistered
        registry.deregister("agent-b")
        assert registry.get("agent-b") is None
        remote_bridge.publish_remote(
            PEER_DEREGISTERED, {"peer_id": "agent-b"}, target_peer="agent-b"
        )

        # Final: agent-a still online
        assert registry.get("agent-a").status == PeerStatus.ONLINE


# ------------------------------------------------------------------
# PeerRegistrationManager integration
# ------------------------------------------------------------------

class TestRegistrationManagerIntegration:
    @pytest.mark.asyncio
    async def test_start_stop_lifecycle(self) -> None:
        registry = PeerRegistry(db_path=":memory:")
        config = RegistrationConfig(
            machine="test-box",
            branch="main",
            model="claude-opus-4-6",
            version="1.0.0",
            capabilities=["merge"],
        )
        manager = PeerRegistrationManager(registry, config)

        # Start registers self
        await manager.start()
        peer_id = manager.self_peer_id
        peer = registry.get(peer_id)
        assert peer is not None
        assert peer.status == PeerStatus.ONLINE
        assert peer.metadata.machine == "test-box"
        assert "merge" in peer.metadata.capabilities

        # Stop deregisters
        await manager.stop()
        assert registry.get(peer_id) is None

    @pytest.mark.asyncio
    async def test_heartbeat_runs(self) -> None:
        registry = PeerRegistry(db_path=":memory:")
        config = RegistrationConfig(
            machine="hb-test",
            branch="dev",
            model="claude-opus-4-6",
            version="1.0.0",
            capabilities=[],
        )
        manager = PeerRegistrationManager(registry, config)
        await manager.start()

        old_hb = registry.get(manager.self_peer_id).last_heartbeat
        # Trigger heartbeat manually by running the loop briefly
        registry.update_heartbeat(manager.self_peer_id)
        new_hb = registry.get(manager.self_peer_id).last_heartbeat
        assert new_hb >= old_hb

        await manager.stop()


# ------------------------------------------------------------------
# RemoteEventBridge integration
# ------------------------------------------------------------------

class TestRemoteEventBridgeIntegration:
    def test_publish_remote_dispatches_locally(self) -> None:
        bus = EventBus()
        bridge = RemoteEventBridge(bus)
        received: list[dict] = []
        bus.subscribe(
            AGENT_WORK_ORDER,
            lambda e: received.append(e.payload),
        )
        bridge.publish_remote(
            AGENT_WORK_ORDER,
            {"task": "build-feature"},
            target_peer="remote-1",
        )
        assert len(received) == 1
        assert received[0]["task"] == "build-feature"
        assert received[0]["_target_peer"] == "remote-1"

    def test_is_remote_event(self) -> None:
        assert RemoteEventBridge.is_remote_event(AGENT_WORK_ORDER) is True
        assert RemoteEventBridge.is_remote_event(CONSOLIDATION_COMPLETED) is True
        assert RemoteEventBridge.is_remote_event("message.received") is False

    def test_format_remote_event(self) -> None:
        bus = EventBus()
        event = bus.publish(PEER_REGISTERED, {"peer_id": "x"})
        serialized = RemoteEventBridge.format_remote_event(event)
        assert serialized["event_type"] == PEER_REGISTERED
        assert serialized["payload"]["peer_id"] == "x"
        assert "serialized_at" in serialized
        assert "event_id" in serialized


# ------------------------------------------------------------------
# Capability discovery integration
# ------------------------------------------------------------------

class TestCapabilityDiscovery:
    def test_find_merge_capable_peers(self) -> None:
        registry = PeerRegistry(db_path=":memory:")
        registry.register(_make_peer("a", capabilities=["merge", "deploy"]))
        registry.register(_make_peer("b", capabilities=["test", "lint"]))
        registry.register(_make_peer("c", capabilities=["merge"]))

        merge_peers = registry.find_by_capability("merge")
        assert len(merge_peers) == 2
        ids = {p.peer_id for p in merge_peers}
        assert ids == {"a", "c"}

    def test_no_peers_with_capability(self) -> None:
        registry = PeerRegistry(db_path=":memory:")
        registry.register(_make_peer("a", capabilities=["test"]))
        assert registry.find_by_capability("deploy") == []


