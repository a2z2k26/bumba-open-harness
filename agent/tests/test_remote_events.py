"""Sprint 07.07 — RemoteEventBridge ↔ EventBus integration tests.

Covers the contract added by Sprint 07.07:
    1. EventBus.publish runs normally when no peer_target is in the
       payload (and no remote bridge has been wired).
    2. When the peer_coordination flag is on, a wired bridge, and a
       payload with peer_target — the bridge's publish_remote is
       invoked with the matching args.
    3. When the bridge's transport raises, RemoteEventBridge falls back
       to the local-log transport, the event is still persisted to
       events.jsonl, and the local subscribers still fire.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from bridge.event_bus import EventBus
from bridge.remote_events import (
    AGENT_WORK_ORDER,
    PEER_HEARTBEAT,
    MCPRemoteTransport,
    RemoteEventBridge,
    RemoteTransport,
    _LocalLogTransport,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def bus_persisted(tmp_path: Path) -> EventBus:
    """EventBus with persistence so we can verify events.jsonl writes."""
    return EventBus(data_dir=tmp_path)


# ---------------------------------------------------------------------------
# Spec test 1 — flag off, no peer_target → no remote dispatch
# ---------------------------------------------------------------------------


class TestLocalEventPublishedNormally:
    def test_no_peer_target_no_bridge_invocation(self) -> None:
        """When peer_coordination is OFF, publish() must not invoke the
        bridge even if a peer_target is present in the payload."""
        bus = EventBus()
        mock_bridge = MagicMock()
        # Wire the bridge but DO NOT enable the flag — peer_coordination
        # off must short-circuit the dispatch path.
        bus.set_remote_event_bridge(mock_bridge, peer_coordination_enabled=False)

        received: list[dict] = []
        bus.subscribe(AGENT_WORK_ORDER, lambda e: received.append(e.payload))

        # No peer_target — local publish only.
        bus.publish(AGENT_WORK_ORDER, payload={"task": "build-feature"})
        assert len(received) == 1
        assert mock_bridge.publish_remote.call_count == 0

        # Even WITH peer_target, flag-off must not route remotely.
        bus.publish(
            AGENT_WORK_ORDER,
            payload={"task": "deploy", "peer_target": "agent-b"},
        )
        assert len(received) == 2
        assert mock_bridge.publish_remote.call_count == 0

    def test_publish_without_bridge_unchanged(self) -> None:
        """No bridge wired at all — pre-07.07 behavior is preserved."""
        bus = EventBus()
        received: list[dict] = []
        bus.subscribe(PEER_HEARTBEAT, lambda e: received.append(e.payload))
        bus.publish(PEER_HEARTBEAT, payload={"peer_id": "agent-a"})
        assert received == [{"peer_id": "agent-a"}]


# ---------------------------------------------------------------------------
# Spec test 2 — peer_target with flag on routes through bridge
# ---------------------------------------------------------------------------


class TestPeerTargetEventRoutedThroughBridge:
    def test_bridge_called_with_correct_args(self) -> None:
        bus = EventBus()
        mock_bridge = MagicMock()
        bus.set_remote_event_bridge(mock_bridge, peer_coordination_enabled=True)

        payload = {"task": "deploy", "peer_target": "agent-b", "n": 7}
        bus.publish(AGENT_WORK_ORDER, payload=payload)

        # publish_remote(event_type, payload, target_peer)
        assert mock_bridge.publish_remote.call_count == 1
        args, kwargs = mock_bridge.publish_remote.call_args
        assert args[0] == AGENT_WORK_ORDER
        assert args[1]["task"] == "deploy"
        assert args[1]["peer_target"] == "agent-b"
        assert args[1]["n"] == 7
        assert args[2] == "agent-b"

    def test_local_publish_still_fires(self) -> None:
        """Remote routing does not replace the local publish — events.jsonl
        + subscribers fire regardless of bridge outcome."""
        bus = EventBus()
        mock_bridge = MagicMock()
        bus.set_remote_event_bridge(mock_bridge, peer_coordination_enabled=True)

        received: list[dict] = []
        bus.subscribe(AGENT_WORK_ORDER, lambda e: received.append(e.payload))

        bus.publish(
            AGENT_WORK_ORDER,
            payload={"task": "x", "peer_target": "agent-z"},
        )
        # Bridge fired AND local subscriber received the event.
        assert mock_bridge.publish_remote.call_count == 1
        assert len(received) == 1
        assert received[0]["peer_target"] == "agent-z"


# ---------------------------------------------------------------------------
# Spec test 3 — transport unavailable → fallback to local log + persist
# ---------------------------------------------------------------------------


class _RaisingTransport:
    """Test double — every send() raises a RuntimeError."""

    def __init__(self) -> None:
        self.attempts: int = 0

    def send(self, peer: str, event_type: str, payload: dict) -> None:
        self.attempts += 1
        raise RuntimeError("simulated transport failure")


class TestTransportUnavailableDegrades:
    def test_bridge_falls_back_to_local_log(self) -> None:
        """When the injected transport raises, publish_remote must not
        propagate — it falls back to _LocalLogTransport so the event is
        still observable."""
        local_bus = EventBus()
        local_received: list[dict] = []
        local_bus.subscribe(
            AGENT_WORK_ORDER, lambda e: local_received.append(e.payload)
        )
        raising = _RaisingTransport()
        bridge = RemoteEventBridge(event_bus=local_bus, transport=raising)

        # Should not raise — fallback handles it.
        bridge.publish_remote(AGENT_WORK_ORDER, {"task": "x"}, "agent-z")

        assert raising.attempts == 1
        # Fallback _LocalLogTransport(self._bus) re-publishes locally with
        # _target_peer enrichment, so local_received gets the event.
        assert len(local_received) == 1
        assert local_received[0]["task"] == "x"
        assert local_received[0]["_target_peer"] == "agent-z"

    def test_event_persisted_when_remote_publish_fails(
        self, bus_persisted: EventBus, tmp_path: Path
    ) -> None:
        """End-to-end: EventBus.publish + bridge.publish_remote raising +
        events.jsonl still gets the event (local publish always runs)."""

        class _DispatchRaising:
            def publish_remote(
                self, event_type: str, payload: dict, target_peer: str
            ) -> None:
                raise RuntimeError("bridge blew up")

        bus_persisted.set_remote_event_bridge(
            _DispatchRaising(), peer_coordination_enabled=True
        )

        bus_persisted.publish(
            AGENT_WORK_ORDER,
            payload={"task": "x", "peer_target": "agent-z"},
        )

        events_dir = tmp_path / "events"
        files = list(events_dir.glob("*.jsonl"))
        assert len(files) == 1, "events.jsonl must exist after publish"
        lines = [
            json.loads(line)
            for line in files[0].read_text().splitlines()
            if line.strip()
        ]
        assert len(lines) == 1
        assert lines[0]["event_type"] == AGENT_WORK_ORDER
        assert lines[0]["payload"]["peer_target"] == "agent-z"


# ---------------------------------------------------------------------------
# Transport plumbing — Protocol satisfaction + MCPRemoteTransport stub
# ---------------------------------------------------------------------------


class TestTransportProtocol:
    def test_local_log_transport_satisfies_protocol(self) -> None:
        # Structural typing: _LocalLogTransport.send signature matches
        # RemoteTransport. Construct one and call send to confirm.
        t: RemoteTransport = _LocalLogTransport()
        t.send("peer-1", AGENT_WORK_ORDER, {"x": 1})  # no event_bus → just logs

    def test_mcp_remote_transport_calls_peer_send_message_tool(self) -> None:
        """MCP transport uses bumba-memory's direct peer message tool."""

        class _FakeMCPClient:
            def __init__(self) -> None:
                self.calls: list[tuple[str, dict]] = []

            def call_tool(self, tool_name: str, arguments: dict) -> dict:
                self.calls.append((tool_name, arguments))
                return {"ok": True}

        client = _FakeMCPClient()
        transport = MCPRemoteTransport(client=client, source_agent_id="macbook")

        transport.send("macmini", AGENT_WORK_ORDER, {"task": "deploy"})

        assert client.calls == [
            (
                "peer_send_message",
                {
                    "source": "macbook",
                    "target": "macmini",
                    "message": {
                        "event_type": AGENT_WORK_ORDER,
                        "payload": {"task": "deploy"},
                    },
                    "messageType": "remote_event",
                },
            )
        ]

    def test_mcp_remote_transport_failure_falls_back_to_local_log(self) -> None:
        """A failing MCP client still leaves the event observable locally."""

        class _FailingMCPClient:
            def call_tool(self, tool_name: str, arguments: dict) -> dict:
                raise RuntimeError("mcp unavailable")

        local_bus = EventBus()
        local_received: list[dict] = []
        local_bus.subscribe(
            AGENT_WORK_ORDER, lambda e: local_received.append(e.payload)
        )
        bridge = RemoteEventBridge(
            event_bus=local_bus,
            transport=MCPRemoteTransport(
                client=_FailingMCPClient(),
                source_agent_id="macbook",
            ),
        )

        bridge.publish_remote(AGENT_WORK_ORDER, {"task": "deploy"}, "macmini")

        assert local_received == [{"task": "deploy", "_target_peer": "macmini"}]

    def test_bridge_default_transport_is_local_log(self) -> None:
        """Constructing RemoteEventBridge with no transport defaults to
        _LocalLogTransport — preserves the prior stub behavior."""
        bridge = RemoteEventBridge()
        assert isinstance(bridge._transport, _LocalLogTransport)


# ---------------------------------------------------------------------------
# Sprint S3.3 — transport mode + status surface
# ---------------------------------------------------------------------------


class TestTransportModeStatus:
    """Operators must be able to distinguish local-log delivery from a
    real cross-machine MCP transport. ``transport_mode``/``status``
    encode that knowledge so callers don't have to isinstance the
    private ``_transport`` attribute themselves.
    """

    def test_remote_event_bridge_reports_local_log_transport(self) -> None:
        bridge = RemoteEventBridge()
        assert bridge.status() == {
            "transport_mode": "local_log",
            "remote_delivery": False,
        }

    def test_remote_event_bridge_reports_mcp_transport(self) -> None:
        """MCP transport is a real remote-delivery mode once a client is injected."""

        class _FakeMCPClient:
            def call_tool(self, tool_name: str, arguments: dict) -> dict:
                return {"ok": True}

        bridge = RemoteEventBridge(
            transport=MCPRemoteTransport(
                client=_FakeMCPClient(),
                source_agent_id="macbook",
            )
        )
        assert bridge.transport_mode() == "mcp"
        assert bridge.status() == {
            "transport_mode": "mcp",
            "remote_delivery": True,
        }

    def test_remote_event_bridge_reports_real_transport(self) -> None:
        """A non-stub transport — ``remote_delivery`` is True and the
        class name is surfaced verbatim for forward-compatibility."""

        class _RealRemoteTransport:
            def send(self, peer: str, event_type: str, payload: dict) -> None:
                # Pretend to ship the event over the wire.
                return None

        bridge = RemoteEventBridge(transport=_RealRemoteTransport())
        assert bridge.transport_mode() == "_RealRemoteTransport"
        assert bridge.status() == {
            "transport_mode": "_RealRemoteTransport",
            "remote_delivery": True,
        }
