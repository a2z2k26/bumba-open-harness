"""Channel-agnostic message bus for routing inbound and outbound messages.

Provides typed message envelopes (InboundMessage, OutboundMessage) and an
asyncio.Queue-backed MessageBus that decouples message producers (channels)
from consumers (bridge processing pipeline).
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class InboundMessage:
    """A message received from an external channel.

    Attributes:
        channel: Name of the originating channel (e.g. "discord", "vapi").
        chat_id: Channel-specific chat/conversation identifier.
        text: Message body text.
        platform_message_id: Platform-specific message ID for reply threading.
        timestamp: Unix timestamp when the message was received.
    """

    channel: str
    chat_id: str
    text: str
    platform_message_id: int
    timestamp: float = field(default_factory=time.time)


@dataclass(frozen=True)
class OutboundMessage:
    """A message to be sent to an external channel.

    Attributes:
        channel: Target channel name.
        chat_id: Target chat/conversation identifier.
        text: Message body text.
        reply_to: Optional platform message ID to thread as a reply.
    """

    channel: str
    chat_id: str
    text: str
    reply_to: int | None = None


class MessageBus:
    """Async queue pair for decoupled inbound/outbound message routing.

    Channels publish inbound messages; the bridge pipeline consumes them.
    The pipeline publishes outbound messages; channels consume and deliver them.
    """

    def __init__(self, maxsize: int = 0) -> None:
        """Initialize the message bus.

        Args:
            maxsize: Maximum queue size (0 = unbounded).
        """
        self._inbound: asyncio.Queue[InboundMessage] = asyncio.Queue(maxsize=maxsize)
        self._outbound: asyncio.Queue[OutboundMessage] = asyncio.Queue(maxsize=maxsize)

    async def publish_inbound(self, msg: InboundMessage) -> None:
        """Enqueue an inbound message from a channel.

        Args:
            msg: The inbound message to enqueue.
        """
        await self._inbound.put(msg)
        logger.debug(
            "Inbound message queued: channel=%s chat_id=%s len=%d",
            msg.channel, msg.chat_id, len(msg.text),
        )

    async def publish_outbound(self, msg: OutboundMessage) -> None:
        """Enqueue an outbound message for delivery to a channel.

        Args:
            msg: The outbound message to enqueue.
        """
        await self._outbound.put(msg)
        logger.debug(
            "Outbound message queued: channel=%s chat_id=%s len=%d",
            msg.channel, msg.chat_id, len(msg.text),
        )

    async def get_inbound(self) -> InboundMessage:
        """Block until an inbound message is available, then return it."""
        return await self._inbound.get()

    async def get_outbound(self) -> OutboundMessage:
        """Block until an outbound message is available, then return it."""
        return await self._outbound.get()

    async def drain(self) -> None:
        """Flush both queues, discarding all pending messages.

        Useful during shutdown to prevent blocked coroutines.
        """
        drained_in = 0
        while not self._inbound.empty():
            try:
                self._inbound.get_nowait()
                drained_in += 1
            except asyncio.QueueEmpty:
                break

        drained_out = 0
        while not self._outbound.empty():
            try:
                self._outbound.get_nowait()
                drained_out += 1
            except asyncio.QueueEmpty:
                break

        if drained_in or drained_out:
            logger.info(
                "MessageBus drained: %d inbound, %d outbound discarded",
                drained_in, drained_out,
            )

    @property
    def inbound_qsize(self) -> int:
        """Number of messages waiting in the inbound queue."""
        return self._inbound.qsize()

    @property
    def outbound_qsize(self) -> int:
        """Number of messages waiting in the outbound queue."""
        return self._outbound.qsize()
