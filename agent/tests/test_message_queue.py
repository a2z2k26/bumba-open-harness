"""Tests for bridge.message_queue (S53)."""

from __future__ import annotations

import asyncio

import pytest


class TestEnqueueDequeue:
    """Basic queue operations."""

    @pytest.mark.asyncio
    async def test_enqueue_and_dequeue(self, message_queue):
        msg_id = await message_queue.enqueue(100, "chat-1", "Hello")
        assert msg_id > 0

        msg = await message_queue.dequeue()
        assert msg is not None
        assert msg.text == "Hello"
        assert msg.chat_id == "chat-1"
        assert msg.status == "processing"
        assert msg.attempt_count == 1

    @pytest.mark.asyncio
    async def test_fifo_order(self, message_queue):
        await message_queue.enqueue(1, "chat-1", "First")
        await message_queue.enqueue(2, "chat-1", "Second")
        await message_queue.enqueue(3, "chat-1", "Third")

        m1 = await message_queue.dequeue()
        m2 = await message_queue.dequeue()
        m3 = await message_queue.dequeue()

        assert m1.text == "First"
        assert m2.text == "Second"
        assert m3.text == "Third"

    @pytest.mark.asyncio
    async def test_empty_dequeue(self, message_queue):
        msg = await message_queue.dequeue()
        assert msg is None


class TestStatusTransitions:
    """Status transitions: complete, fail, retry."""

    @pytest.mark.asyncio
    async def test_complete(self, message_queue, migrated_db):
        await message_queue.enqueue(1, "chat-1", "Test")
        msg = await message_queue.dequeue()
        await message_queue.complete(msg.id)

        row = await migrated_db.fetchone(
            "SELECT status, completed_at FROM message_queue WHERE id = ?", (msg.id,)
        )
        assert row[0] == "completed"
        assert row[1] is not None

    @pytest.mark.asyncio
    async def test_fail(self, message_queue, migrated_db):
        await message_queue.enqueue(1, "chat-1", "Test")
        msg = await message_queue.dequeue()
        await message_queue.fail(msg.id, "timeout")

        row = await migrated_db.fetchone(
            "SELECT status, error_details FROM message_queue WHERE id = ?", (msg.id,)
        )
        assert row[0] == "failed"
        assert "timeout" in row[1]

    @pytest.mark.asyncio
    async def test_retry(self, message_queue):
        await message_queue.enqueue(1, "chat-1", "Test")
        msg = await message_queue.dequeue()
        await message_queue.retry(msg.id)

        msg2 = await message_queue.dequeue()
        assert msg2 is not None
        assert msg2.id == msg.id
        assert msg2.attempt_count == 2

    @pytest.mark.asyncio
    async def test_attempt_count_increments(self, message_queue):
        await message_queue.enqueue(1, "chat-1", "Test")

        msg = await message_queue.dequeue()
        assert msg.attempt_count == 1
        await message_queue.retry(msg.id)

        msg = await message_queue.dequeue()
        assert msg.attempt_count == 2
        await message_queue.retry(msg.id)

        msg = await message_queue.dequeue()
        assert msg.attempt_count == 3


class TestRateLimitAndSendFailed:
    """Rate limiting and send_failed flows."""

    @pytest.mark.asyncio
    async def test_rate_limit_all(self, message_queue, migrated_db):
        await message_queue.enqueue(1, "chat-1", "A")
        await message_queue.enqueue(2, "chat-1", "B")
        await message_queue.enqueue(3, "chat-1", "C")

        count = await message_queue.rate_limit_all()
        assert count == 3

        rows = await migrated_db.fetchall(
            "SELECT status FROM message_queue WHERE status = 'rate_limited'"
        )
        assert len(rows) == 3

    @pytest.mark.asyncio
    async def test_mark_send_failed_and_get_unsent(self, message_queue):
        await message_queue.enqueue(1, "chat-1", "Test")
        msg = await message_queue.dequeue()

        await message_queue.mark_send_failed(msg.id, "Response text here")
        unsent = await message_queue.get_unsent_responses()
        assert len(unsent) == 1
        assert unsent[0][0] == msg.id
        assert unsent[0][1] == "chat-1"
        assert unsent[0][2] == "Response text here"

    @pytest.mark.asyncio
    async def test_send_failed_retry_flow(self, message_queue):
        """Full flow: enqueue → dequeue → send_failed → get_unsent → complete."""
        await message_queue.enqueue(1, "chat-1", "Original")
        msg = await message_queue.dequeue()

        # Claude succeeds but Discord fails
        await message_queue.mark_send_failed(msg.id, "Claude response")

        # Later, Discord recovers
        unsent = await message_queue.get_unsent_responses()
        assert len(unsent) == 1

        # Resend succeeds
        await message_queue.complete(unsent[0][0])
        unsent2 = await message_queue.get_unsent_responses()
        assert len(unsent2) == 0


class TestOrphanedAndStatus:
    """Crash recovery and status."""

    @pytest.mark.asyncio
    async def test_reset_orphaned(self, message_queue):
        await message_queue.enqueue(1, "chat-1", "A")
        await message_queue.enqueue(2, "chat-1", "B")
        await message_queue.dequeue()  # A → processing

        count = await message_queue.reset_orphaned()
        assert count == 1

        msg = await message_queue.dequeue()
        assert msg.text == "A"

    @pytest.mark.asyncio
    async def test_queue_status(self, message_queue):
        await message_queue.enqueue(1, "chat-1", "Pending 1")
        await message_queue.enqueue(2, "chat-1", "Pending 2")

        status = await message_queue.get_queue_status()
        assert status["counts"]["pending"] == 2
        assert len(status["pending"]) == 2

    @pytest.mark.asyncio
    async def test_concurrent_dequeue_lock(self, message_queue):
        """Only one dequeue should succeed at a time."""
        await message_queue.enqueue(1, "chat-1", "Single")

        results = await asyncio.gather(
            message_queue.dequeue(),
            message_queue.dequeue(),
        )

        non_none = [r for r in results if r is not None]
        assert len(non_none) == 1
