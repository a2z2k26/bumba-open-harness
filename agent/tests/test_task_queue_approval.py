"""Tests for operator gate primitive in TaskQueue (sprint F-W.4)."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from bridge.task_queue import TaskQueue, _approval_events


@pytest.fixture()
def mock_db() -> MagicMock:
    db = MagicMock()
    db.execute = AsyncMock()
    db.commit = AsyncMock()
    db.fetchone = AsyncMock(return_value=None)
    db.fetchall = AsyncMock(return_value=[])
    return db


@pytest.fixture()
def tq(mock_db: MagicMock) -> TaskQueue:
    return TaskQueue(mock_db)


def _make_task(task_id: int = 1, status: str = "awaiting_approval") -> tuple:
    """Return a raw DB row tuple for an AsyncTask."""
    return (
        task_id,        # id
        status,         # status
        "test prompt",  # prompt
        "sess-1",       # session_id
        "csess-1",      # claude_session_id
        "Approve?",     # pending_question
        None,           # pending_options
        None,           # user_response
        None,           # result
        "chat-1",       # chat_id
        "2026-04-18",   # created_at
        "2026-04-18",   # updated_at
    )


class TestSetAwaitingApproval:
    @pytest.mark.asyncio
    async def test_sets_status_in_db(self, tq: TaskQueue, mock_db: MagicMock) -> None:
        event = asyncio.Event()
        await tq.set_awaiting_approval(42, "Ready to publish?", event)

        mock_db.execute.assert_called_once()
        call_args = mock_db.execute.call_args[0]
        assert "awaiting_approval" in call_args[0]
        assert call_args[1][0] == "Ready to publish?"
        assert call_args[1][1] == 42

    @pytest.mark.asyncio
    async def test_registers_event_in_registry(
        self, tq: TaskQueue, mock_db: MagicMock
    ) -> None:
        event = asyncio.Event()
        # Clean registry
        _approval_events.clear()
        await tq.set_awaiting_approval(99, "OK?", event)
        assert 99 in _approval_events
        assert _approval_events[99] is event
        _approval_events.clear()


class TestApprove:
    @pytest.mark.asyncio
    async def test_approve_sets_pending_and_fires_event(
        self, tq: TaskQueue, mock_db: MagicMock
    ) -> None:
        event = asyncio.Event()
        _approval_events[1] = event
        mock_db.fetchone = AsyncMock(return_value=_make_task(1, "awaiting_approval"))

        result = await tq.approve(1)

        assert result is True
        event_fired = event.is_set()
        assert event_fired
        # Event should be removed from registry
        assert 1 not in _approval_events
        _approval_events.clear()

    @pytest.mark.asyncio
    async def test_approve_returns_false_if_not_awaiting(
        self, tq: TaskQueue, mock_db: MagicMock
    ) -> None:
        mock_db.fetchone = AsyncMock(return_value=_make_task(1, "completed"))
        result = await tq.approve(1)
        assert result is False

    @pytest.mark.asyncio
    async def test_approve_returns_false_if_not_found(
        self, tq: TaskQueue, mock_db: MagicMock
    ) -> None:
        mock_db.fetchone = AsyncMock(return_value=None)
        result = await tq.approve(999)
        assert result is False


class TestReject:
    @pytest.mark.asyncio
    async def test_reject_sets_failed_and_fires_event(
        self, tq: TaskQueue, mock_db: MagicMock
    ) -> None:
        event = asyncio.Event()
        _approval_events[2] = event
        mock_db.fetchone = AsyncMock(return_value=_make_task(2, "awaiting_approval"))

        result = await tq.reject(2, "Not ready yet")

        assert result is True
        assert event.is_set()
        assert 2 not in _approval_events
        _approval_events.clear()

        # Verify DB update includes 'failed'
        call_args = mock_db.execute.call_args[0]
        assert "failed" in call_args[0]
        assert "rejected: Not ready yet" in call_args[1][0]

    @pytest.mark.asyncio
    async def test_reject_without_reason(
        self, tq: TaskQueue, mock_db: MagicMock
    ) -> None:
        event = asyncio.Event()
        _approval_events[3] = event
        mock_db.fetchone = AsyncMock(return_value=_make_task(3, "awaiting_approval"))

        result = await tq.reject(3)
        assert result is True
        call_args = mock_db.execute.call_args[0]
        assert "rejected" in call_args[1][0]
        _approval_events.clear()

    @pytest.mark.asyncio
    async def test_reject_returns_false_if_not_awaiting(
        self, tq: TaskQueue, mock_db: MagicMock
    ) -> None:
        mock_db.fetchone = AsyncMock(return_value=_make_task(1, "pending"))
        result = await tq.reject(1, "nope")
        assert result is False


class TestGetAwaitingApproval:
    @pytest.mark.asyncio
    async def test_returns_awaiting_tasks(
        self, tq: TaskQueue, mock_db: MagicMock
    ) -> None:
        mock_db.fetchall = AsyncMock(
            return_value=[_make_task(1), _make_task(2)]
        )
        tasks = await tq.get_awaiting_approval()
        assert len(tasks) == 2
        assert all(t.status == "awaiting_approval" for t in tasks)

    @pytest.mark.asyncio
    async def test_returns_empty_when_none(
        self, tq: TaskQueue, mock_db: MagicMock
    ) -> None:
        mock_db.fetchall = AsyncMock(return_value=[])
        tasks = await tq.get_awaiting_approval()
        assert tasks == []


class TestApprovalEventRoundtrip:
    """Integration-style test: set gate, then approve, event fires."""

    @pytest.mark.asyncio
    async def test_gate_roundtrip(self, mock_db: MagicMock) -> None:
        tq = TaskQueue(mock_db)
        event = asyncio.Event()
        _approval_events.clear()

        # Set gate
        await tq.set_awaiting_approval(10, "Publish weekly CEO review?", event)
        assert not event.is_set()

        # Simulate operator approving
        mock_db.fetchone = AsyncMock(return_value=_make_task(10, "awaiting_approval"))
        approved = await tq.approve(10)
        assert approved is True
        assert event.is_set()
        _approval_events.clear()
