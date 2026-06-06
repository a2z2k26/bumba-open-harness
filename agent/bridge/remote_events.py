"""Issue #82 -- Remote event types and bridge for cross-machine coordination.

Defines 10 agent/peer event type constants and a ``RemoteEventBridge``
that wraps the existing ``EventBus`` to publish events destined for
remote peers.

Sprint 07.07 — RemoteEventBridge gains an injectable ``RemoteTransport``.
The default ``_LocalLogTransport`` preserves the prior stub behavior
(logs the target peer; optionally publishes to a local ``EventBus`` so
existing callers keep dispatching to local subscribers). A real
``MCPRemoteTransport`` stub is declared but not implemented — the bridge
half is in place pending bumba-memory-mcp shipping its event-broadcast
tool. ``EventBus.publish`` (Sprint 07.07) detects ``peer_target`` in
event payloads and forwards through this bridge when the
``peer_coordination_enabled`` flag is on.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Protocol

from .event_bus import Event, EventBus

log = logging.getLogger(__name__)


# ------------------------------------------------------------------
# Remote event type constants
# ------------------------------------------------------------------

AGENT_WORK_ORDER = "agent.work_order"
AGENT_STATUS_UPDATE = "agent.status_update"
AGENT_ESCALATION = "agent.escalation"
AGENT_RESULT = "agent.result"
AGENT_QUERY = "agent.query"
AGENT_QUERY_RESPONSE = "agent.query_response"

PEER_REGISTERED = "peer.registered"
PEER_DEREGISTERED = "peer.deregistered"
PEER_HEARTBEAT = "peer.heartbeat"

CONSOLIDATION_COMPLETED = "consolidation.completed"

REMOTE_EVENT_TYPES = (
    AGENT_WORK_ORDER,
    AGENT_STATUS_UPDATE,
    AGENT_ESCALATION,
    AGENT_RESULT,
    AGENT_QUERY,
    AGENT_QUERY_RESPONSE,
    PEER_REGISTERED,
    PEER_DEREGISTERED,
    PEER_HEARTBEAT,
    CONSOLIDATION_COMPLETED,
)


# ------------------------------------------------------------------
# Transport Protocol (Sprint 07.07)
# ------------------------------------------------------------------


class RemoteTransport(Protocol):
    """Abstract transport for delivering events to remote peers.

    Implementations are responsible for actually getting the event off
    this machine. The bridge contract: ``send`` must not raise for
    transient delivery failures handled internally; if it does raise,
    ``RemoteEventBridge.publish_remote`` falls back to the local-log
    transport so the event is at least observable.
    """

    def send(self, peer: str, event_type: str, payload: dict) -> None:
        ...


class MCPToolClient(Protocol):
    """Minimal sync client seam for invoking bumba-memory MCP tools."""

    def call_tool(
        self,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> dict[str, Any] | None:
        ...


class _LocalLogTransport:
    """Default transport — logs the target peer and (optionally) publishes
    to a local ``EventBus``.

    Preserves the prior stub behavior of ``RemoteEventBridge`` from
    before Sprint 07.07: when constructed with an ``event_bus`` it
    re-dispatches the event locally with a ``_target_peer`` annotation,
    matching the contract that existing callers (and
    ``test_cross_machine_integration``) depend on. When constructed
    without an event_bus it merely logs.
    """

    def __init__(self, event_bus: EventBus | None = None) -> None:
        self._event_bus = event_bus

    def send(self, peer: str, event_type: str, payload: dict) -> None:
        if self._event_bus is not None:
            enriched = dict(payload)
            enriched["_target_peer"] = peer
            self._event_bus.publish(event_type, enriched, source="remote_bridge")
        log.info(
            "Remote event published (local-log): type=%s target=%s",
            event_type,
            peer,
        )


class MCPRemoteTransport:
    """MCP-mediated peer event delivery via bumba-memory peer messaging.

    The transport intentionally depends on a small ``MCPToolClient`` protocol
    rather than a concrete runtime client. That lets tests prove the exact MCP
    tool contract now, while production wiring can inject the bridge's chosen
    MCP client once peer coordination is ready to leave local-log mode.
    """

    def __init__(
        self,
        *,
        client: MCPToolClient,
        source_agent_id: str,
        tool_name: str = "peer_send_message",
    ) -> None:
        self._client = client
        self._source_agent_id = source_agent_id
        self._tool_name = tool_name

    def send(self, peer: str, event_type: str, payload: dict) -> None:
        self._client.call_tool(
            self._tool_name,
            {
                "source": self._source_agent_id,
                "target": peer,
                "message": {
                    "event_type": event_type,
                    "payload": dict(payload),
                },
                "messageType": "remote_event",
            },
        )


# ------------------------------------------------------------------
# Remote event bridge
# ------------------------------------------------------------------


class RemoteEventBridge:
    """Wraps an injectable ``RemoteTransport`` for peer-targeted events.

    Sprint 07.07 made ``RemoteEventBridge`` transport-injectable.
    ``__init__`` accepts an optional ``event_bus`` (legacy positional —
    used by the default ``_LocalLogTransport`` to mirror the pre-07.07
    behavior of dispatching to local subscribers) and an optional
    ``transport`` (the Sprint 07.07 extension point — when provided,
    overrides the default and is the actual delivery mechanism).
    ``publish_remote`` calls ``transport.send`` and, on any exception,
    falls back to ``_LocalLogTransport`` so the event is still
    observable.
    """

    def __init__(
        self,
        event_bus: EventBus | None = None,
        transport: RemoteTransport | None = None,
    ) -> None:
        self._bus = event_bus
        self._transport: RemoteTransport = transport or _LocalLogTransport(event_bus)

    def publish_remote(
        self,
        event_type: str,
        payload: dict,
        target_peer: str,
    ) -> None:
        """Publish an event intended for a remote peer.

        Calls ``self._transport.send(target_peer, event_type, payload)``.
        If the transport raises, falls back to ``_LocalLogTransport`` so
        the event is at minimum observable in logs (and, when the bridge
        was constructed with an event_bus, in the local event stream).
        """
        try:
            self._transport.send(target_peer, event_type, payload)
        except Exception:
            log.exception(
                "remote event delivery failed; falling back to local log"
            )
            _LocalLogTransport(self._bus).send(target_peer, event_type, payload)

    # ------------------------------------------------------------------
    # Sprint S3.3 — operator-visible transport mode/status.
    #
    # The default transport is ``_LocalLogTransport`` and the MCP
    # transport is an unimplemented stub. Without this surface, operators
    # inspecting a "remote events" status cannot tell whether events are
    # actually crossing machines or merely landing in the local log.
    # ``transport_mode`` returns a stable string id; ``status`` packages
    # it with an explicit ``remote_delivery`` boolean so callers don't
    # have to encode the local-log/MCP-stub knowledge themselves.
    # ------------------------------------------------------------------

    def transport_mode(self) -> str:
        """Return the active transport mode id.

        ``"local_log"`` — default ``_LocalLogTransport``; events stay on
        this machine. ``"mcp"`` — MCP peer-message transport with an
        injected client. Any other class name is returned verbatim for
        forward-compatibility with real transports added later.
        """
        if isinstance(self._transport, _LocalLogTransport):
            return "local_log"
        if isinstance(self._transport, MCPRemoteTransport):
            return "mcp"
        return self._transport.__class__.__name__

    def status(self) -> dict[str, object]:
        """Return an operator-facing status dict.

        ``remote_delivery`` is True when the active transport is not the
        local-log default — i.e. events are expected to leave this machine.
        """
        mode = self.transport_mode()
        return {
            "transport_mode": mode,
            "remote_delivery": mode != "local_log",
        }

    @staticmethod
    def is_remote_event(event_type: str) -> bool:
        """Return True if *event_type* is a known remote event."""
        return event_type in REMOTE_EVENT_TYPES

    @staticmethod
    def format_remote_event(event: Event) -> dict:
        """Serialize an ``Event`` for HTTP transport."""
        return {
            "event_id": event.event_id,
            "event_type": event.event_type,
            "payload": event.payload,
            "source": event.source,
            "timestamp": event.timestamp,
            "correlation_id": event.correlation_id,
            "serialized_at": datetime.now(timezone.utc).isoformat(),
        }
