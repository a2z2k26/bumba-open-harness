"""Tests for WorkOrder Public API + WebSocket streaming (#577)."""
from __future__ import annotations

import asyncio
import pytest
from unittest.mock import MagicMock, AsyncMock

from bridge.event_bus import EventBus
from bridge.workorder_stream import WorkOrderStreamManager


# ---------------------------------------------------------------------------
# WorkOrderStreamManager
# ---------------------------------------------------------------------------

def test_subscribe_returns_queue():
    mgr = WorkOrderStreamManager()
    q = mgr.subscribe("wo-123")
    assert q is not None
    assert mgr.active_subscriptions() == 1


def test_unsubscribe_removes_queue():
    mgr = WorkOrderStreamManager()
    q = mgr.subscribe("wo-123")
    mgr.unsubscribe("wo-123", q)
    assert mgr.active_subscriptions() == 0


def test_on_event_delivers_to_subscribers():
    mgr = WorkOrderStreamManager()
    q = mgr.subscribe("wo-abc")

    mgr._on_event("workorder.completed", {
        "workorder_id": "wo-abc",
        "status": "complete",
    })

    assert not q.empty()
    msg = q.get_nowait()
    assert msg["event"] == "workorder.completed"
    assert msg["data"]["workorder_id"] == "wo-abc"


def test_real_event_bus_publish_fans_out_completed_event():
    bus = EventBus()
    mgr = WorkOrderStreamManager(event_bus=bus)
    q = mgr.subscribe("wo-abc")
    mgr.wire_event_bus()

    bus.publish(
        "workorder.completed",
        {"workorder_id": "wo-abc", "status": "complete"},
        source="test",
    )

    assert not q.empty()
    msg = q.get_nowait()
    assert msg["event"] == "workorder.completed"
    assert msg["data"]["workorder_id"] == "wo-abc"


def test_on_event_no_workorder_id_ignored():
    mgr = WorkOrderStreamManager()
    q = mgr.subscribe("wo-abc")
    mgr._on_event("workorder.completed", {"no_id": "here"})
    assert q.empty()


def test_on_event_wrong_wo_ignored():
    mgr = WorkOrderStreamManager()
    q_a = mgr.subscribe("wo-aaa")
    mgr.subscribe("wo-bbb")

    mgr._on_event("workorder.completed", {"workorder_id": "wo-aaa"})
    assert not q_a.empty()


def test_wire_event_bus():
    mock_bus = MagicMock()
    mgr = WorkOrderStreamManager(event_bus=mock_bus)
    mgr.wire_event_bus()
    # Should subscribe to all WO event names
    assert mock_bus.subscribe.call_count >= 5


def test_wire_event_bus_idempotent():
    mock_bus = MagicMock()
    mgr = WorkOrderStreamManager(event_bus=mock_bus)
    mgr.wire_event_bus()
    mgr.wire_event_bus()  # second call should be a no-op
    call_count = mock_bus.subscribe.call_count
    # Count should not double
    mgr.wire_event_bus()
    assert mock_bus.subscribe.call_count == call_count


def test_broadcast_to_all():
    mgr = WorkOrderStreamManager()
    q1 = mgr.subscribe("wo-1")
    q2 = mgr.subscribe("wo-2")

    mgr.broadcast_to_all("system.alert", {"message": "hello"})

    assert not q1.empty()
    assert not q2.empty()


def test_queue_full_does_not_raise():
    mgr = WorkOrderStreamManager()
    # Subscribe with a tiny queue
    q: asyncio.Queue = asyncio.Queue(maxsize=1)
    mgr._subs["wo-full"].add(q)
    q.put_nowait({"event": "existing", "data": {}})  # fill queue

    # This should not raise
    mgr._on_event("workorder.completed", {"workorder_id": "wo-full"})
    # The new event must have been dropped — the queue still contains
    # only the original "existing" payload, not the "workorder.completed"
    # we just fanned out.
    assert q.qsize() == 1
    held = q.get_nowait()
    assert held["event"] == "existing"


# ---------------------------------------------------------------------------
# WorkOrderParkingManager (#569)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_park_and_resume():
    from bridge.workorder_parking import WorkOrderParkingManager, ParkedWorkOrder

    mgr = WorkOrderParkingManager()
    resume_called = []

    async def _resume(approved, reason):
        resume_called.append((approved, reason))

    pwo = ParkedWorkOrder(
        workorder_id="wo-001",
        review_id="rev-abc",
        gate_level_name="CODE_REVIEW",
        resume=_resume,
    )
    await mgr.park(pwo)
    result = await mgr.resume("rev-abc", approved=True, reason="LGTM")
    assert result is True
    assert resume_called == [(True, "LGTM")]


@pytest.mark.asyncio
async def test_resume_unknown_review():
    from bridge.workorder_parking import WorkOrderParkingManager

    mgr = WorkOrderParkingManager()
    result = await mgr.resume("nonexistent", approved=True)
    assert result is False


@pytest.mark.asyncio
async def test_list_parked():
    from bridge.workorder_parking import WorkOrderParkingManager, ParkedWorkOrder

    mgr = WorkOrderParkingManager()
    pwo = ParkedWorkOrder(
        workorder_id="wo-002",
        review_id="rev-xyz",
        gate_level_name="HUMAN_APPROVAL",
        resume=AsyncMock(),
    )
    await mgr.park(pwo)
    parked = await mgr.list_parked()
    assert len(parked) == 1
    assert parked[0]["review_id"] == "rev-xyz"
