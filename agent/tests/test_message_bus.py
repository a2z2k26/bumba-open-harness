"""Tests for MessageBus and message envelope dataclasses."""

from __future__ import annotations

import asyncio
import time

import pytest

from bridge.message_bus import InboundMessage, MessageBus, OutboundMessage


# ---------------------------------------------------------------------------
# InboundMessage
# ---------------------------------------------------------------------------


class TestInboundMessage:
    def test_create(self):
        msg = InboundMessage(
            channel="discord",
            chat_id="123",
            text="hello",
            platform_message_id=456,
        )
        assert msg.channel == "discord"
        assert msg.chat_id == "123"
        assert msg.text == "hello"
        assert msg.platform_message_id == 456
        assert msg.timestamp > 0

    def test_frozen(self):
        msg = InboundMessage(
            channel="discord", chat_id="1", text="x", platform_message_id=1
        )
        with pytest.raises(AttributeError):
            msg.text = "changed"  # type: ignore[misc]

    def test_custom_timestamp(self):
        ts = 1234567890.0
        msg = InboundMessage(
            channel="vapi", chat_id="1", text="x", platform_message_id=1, timestamp=ts
        )
        assert msg.timestamp == ts

    def test_default_timestamp_is_recent(self):
        before = time.time()
        msg = InboundMessage(channel="x", chat_id="1", text="x", platform_message_id=1)
        after = time.time()
        assert before <= msg.timestamp <= after


# ---------------------------------------------------------------------------
# OutboundMessage
# ---------------------------------------------------------------------------


class TestOutboundMessage:
    def test_create(self):
        msg = OutboundMessage(
            channel="discord", chat_id="123", text="response"
        )
        assert msg.channel == "discord"
        assert msg.chat_id == "123"
        assert msg.text == "response"
        assert msg.reply_to is None

    def test_create_with_reply(self):
        msg = OutboundMessage(
            channel="vapi", chat_id="1", text="ok", reply_to=42
        )
        assert msg.reply_to == 42

    def test_frozen(self):
        msg = OutboundMessage(channel="x", chat_id="1", text="x")
        with pytest.raises(AttributeError):
            msg.text = "changed"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# MessageBus
# ---------------------------------------------------------------------------


class TestMessageBus:
    @pytest.fixture
    def bus(self) -> MessageBus:
        return MessageBus()

    # -- Basic publish/get --

    @pytest.mark.asyncio
    async def test_publish_and_get_inbound(self, bus: MessageBus):
        msg = InboundMessage(
            channel="discord", chat_id="1", text="hello", platform_message_id=1
        )
        await bus.publish_inbound(msg)
        assert bus.inbound_qsize == 1
        got = await bus.get_inbound()
        assert got is msg
        assert bus.inbound_qsize == 0

    @pytest.mark.asyncio
    async def test_publish_and_get_outbound(self, bus: MessageBus):
        msg = OutboundMessage(channel="discord", chat_id="1", text="reply")
        await bus.publish_outbound(msg)
        assert bus.outbound_qsize == 1
        got = await bus.get_outbound()
        assert got is msg
        assert bus.outbound_qsize == 0

    # -- FIFO ordering --

    @pytest.mark.asyncio
    async def test_fifo_order_inbound(self, bus: MessageBus):
        msgs = [
            InboundMessage(channel="d", chat_id="1", text=f"msg{i}", platform_message_id=i)
            for i in range(5)
        ]
        for m in msgs:
            await bus.publish_inbound(m)

        for i in range(5):
            got = await bus.get_inbound()
            assert got.text == f"msg{i}"

    @pytest.mark.asyncio
    async def test_fifo_order_outbound(self, bus: MessageBus):
        msgs = [
            OutboundMessage(channel="d", chat_id="1", text=f"reply{i}")
            for i in range(5)
        ]
        for m in msgs:
            await bus.publish_outbound(m)

        for i in range(5):
            got = await bus.get_outbound()
            assert got.text == f"reply{i}"

    # -- Blocking behavior --

    @pytest.mark.asyncio
    async def test_get_inbound_blocks_until_published(self, bus: MessageBus):
        """get_inbound should block until a message is published."""
        msg = InboundMessage(channel="d", chat_id="1", text="delayed", platform_message_id=1)

        async def publish_later():
            await asyncio.sleep(0.05)
            await bus.publish_inbound(msg)

        task = asyncio.create_task(publish_later())
        got = await asyncio.wait_for(bus.get_inbound(), timeout=2.0)
        assert got is msg
        await task

    @pytest.mark.asyncio
    async def test_get_outbound_blocks_until_published(self, bus: MessageBus):
        msg = OutboundMessage(channel="d", chat_id="1", text="delayed")

        async def publish_later():
            await asyncio.sleep(0.05)
            await bus.publish_outbound(msg)

        task = asyncio.create_task(publish_later())
        got = await asyncio.wait_for(bus.get_outbound(), timeout=2.0)
        assert got is msg
        await task

    # -- Drain --

    @pytest.mark.asyncio
    async def test_drain_empties_both_queues(self, bus: MessageBus):
        for i in range(3):
            await bus.publish_inbound(
                InboundMessage(channel="d", chat_id="1", text=f"in{i}", platform_message_id=i)
            )
        for i in range(2):
            await bus.publish_outbound(
                OutboundMessage(channel="d", chat_id="1", text=f"out{i}")
            )
        assert bus.inbound_qsize == 3
        assert bus.outbound_qsize == 2

        await bus.drain()

        assert bus.inbound_qsize == 0
        assert bus.outbound_qsize == 0

    @pytest.mark.asyncio
    async def test_drain_on_empty_is_noop(self, bus: MessageBus):
        await bus.drain()
        assert bus.inbound_qsize == 0
        assert bus.outbound_qsize == 0

    # -- Queue size --

    @pytest.mark.asyncio
    async def test_qsize_tracking(self, bus: MessageBus):
        assert bus.inbound_qsize == 0
        assert bus.outbound_qsize == 0

        await bus.publish_inbound(
            InboundMessage(channel="d", chat_id="1", text="x", platform_message_id=1)
        )
        assert bus.inbound_qsize == 1

        await bus.publish_outbound(
            OutboundMessage(channel="d", chat_id="1", text="y")
        )
        assert bus.outbound_qsize == 1

    # -- Bounded queue --

    @pytest.mark.asyncio
    async def test_bounded_queue_blocks(self):
        """With maxsize=1, second publish should block until first is consumed."""
        bus = MessageBus(maxsize=1)
        msg1 = InboundMessage(channel="d", chat_id="1", text="first", platform_message_id=1)
        msg2 = InboundMessage(channel="d", chat_id="1", text="second", platform_message_id=2)

        await bus.publish_inbound(msg1)
        assert bus.inbound_qsize == 1

        # Second publish should block — verify with timeout
        async def publish_second():
            await bus.publish_inbound(msg2)

        task = asyncio.create_task(publish_second())
        await asyncio.sleep(0.05)
        # Queue should still have 1 item (second is blocked)
        assert bus.inbound_qsize == 1

        # Consume first, second should now complete
        got = await bus.get_inbound()
        assert got is msg1
        await asyncio.wait_for(task, timeout=1.0)
        assert bus.inbound_qsize == 1  # second is now in queue
