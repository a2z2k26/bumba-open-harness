"""Tests for Devin-style knowledge auto-ingest (#578, S5.1 #2349)."""
from __future__ import annotations

import logging
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from bridge.event_bus import EventBus
from bridge.work_order import WorkOrder
from bridge.work_order_store import WorkOrderStore
from bridge.workorder_ingest import WorkOrderIngestor


# ---------------------------------------------------------------------------
# Temporal knowledge path (primary persistence)
# ---------------------------------------------------------------------------


def test_ingest_calls_temporal_knowledge():
    tk = MagicMock()
    ingestor = WorkOrderIngestor(temporal_knowledge=tk)

    ingestor.ingest_directly("wo-001", "fix-test", "myproject", "Fixed the failing test.")

    tk.append.assert_called_once()
    args = tk.append.call_args
    assert args.kwargs["key"] == "project:myproject:skill:fix-test"
    assert "Fixed the failing test" in args.kwargs["value"]


def test_ingest_skips_empty_output():
    tk = MagicMock()
    ingestor = WorkOrderIngestor(temporal_knowledge=tk)
    ingestor.ingest_directly("wo-003", "fix-test", "proj", "")
    tk.append.assert_not_called()


def test_ingest_handles_temporal_knowledge_exception():
    tk = MagicMock()
    tk.append.side_effect = Exception("DB error")
    ingestor = WorkOrderIngestor(temporal_knowledge=tk)
    # Should not raise even when tk fails
    ingestor.ingest_directly("wo-005", "fix-test", "proj", "output")


def test_temporal_knowledge_fallback_to_store_api():
    """If temporal_knowledge uses .store() instead of .append(), use that."""
    tk = MagicMock()
    tk.append.side_effect = AttributeError("no append")
    ingestor = WorkOrderIngestor(temporal_knowledge=tk)
    ingestor.ingest_directly("wo-008", "fix-test", "proj", "output")
    tk.store.assert_called_once()


# ---------------------------------------------------------------------------
# Event-bus subscription
# ---------------------------------------------------------------------------


def test_wire_subscribes_to_event_bus():
    bus = MagicMock()
    ingestor = WorkOrderIngestor(event_bus=bus)
    ingestor.wire()
    bus.subscribe.assert_called_once_with("workorder.completed", ingestor._on_completed)


def test_wire_is_idempotent():
    bus = MagicMock()
    ingestor = WorkOrderIngestor(event_bus=bus)
    ingestor.wire()
    ingestor.wire()  # Second call should not subscribe again
    assert bus.subscribe.call_count == 1


def test_wire_logs_secondary_persistence_status(caplog: pytest.LogCaptureFixture, tmp_path: Path):
    """S5.1: wire-time status log surfaces the secondary persistence wiring."""
    bus = MagicMock()
    store = WorkOrderStore(tmp_path / "wos.db")
    try:
        ingestor = WorkOrderIngestor(event_bus=bus, work_order_store=store)
        with caplog.at_level(logging.INFO, logger="bridge.workorder_ingest"):
            ingestor.wire()
        assert any(
            "secondary persistence: WorkOrderStore" in rec.message
            for rec in caplog.records
        ), caplog.text
    finally:
        store.close()


def test_wire_logs_secondary_persistence_not_configured(caplog: pytest.LogCaptureFixture):
    """S5.1: when work_order_store is None, status is surfaced as 'not configured'."""
    bus = MagicMock()
    ingestor = WorkOrderIngestor(event_bus=bus)
    with caplog.at_level(logging.INFO, logger="bridge.workorder_ingest"):
        ingestor.wire()
    assert any(
        "secondary persistence: not configured" in rec.message
        for rec in caplog.records
    ), caplog.text


def test_real_event_bus_publish_ingests_completed_event() -> None:
    """Live EventBus dispatch must reach the ingestor callback."""
    bus = EventBus()
    tk = MagicMock()
    ingestor = WorkOrderIngestor(event_bus=bus, temporal_knowledge=tk)
    ingestor.wire()

    bus.publish(
        "workorder.completed",
        {
            "workorder_id": "wo-009",
            "skill": "fix-test",
            "project": "myproj",
            "output_text": "Tests are fixed.",
        },
        source="test",
    )

    tk.append.assert_called_once()


# ---------------------------------------------------------------------------
# Event handler routing
# ---------------------------------------------------------------------------


def test_on_completed_event_handler():
    tk = MagicMock()
    ingestor = WorkOrderIngestor(temporal_knowledge=tk)
    ingestor._on_completed("workorder.completed", {
        "workorder_id": "wo-006",
        "skill": "fix-test",
        "project": "myproj",
        "output_text": "Tests are fixed.",
    })
    tk.append.assert_called_once()


def test_on_completed_no_output_skipped():
    tk = MagicMock()
    ingestor = WorkOrderIngestor(temporal_knowledge=tk)
    ingestor._on_completed("workorder.completed", {
        "workorder_id": "wo-007",
        "skill": "fix-test",
        "project": "myproj",
        "output_text": "",
    })
    tk.append.assert_not_called()


# ---------------------------------------------------------------------------
# S5.1: secondary persistence path (WorkOrderStore)
# ---------------------------------------------------------------------------


@pytest.fixture
def store(tmp_path: Path) -> WorkOrderStore:
    s = WorkOrderStore(tmp_path / "wos.db")
    yield s
    s.close()


def test_secondary_write_success(store: WorkOrderStore) -> None:
    """S5.1 AC: Completed WorkOrder output reaches WorkOrderStore when configured."""
    wo = WorkOrder.create(intent="Build auth", skill="backend-architect", project="proj-x")
    store.save(wo)

    ingestor = WorkOrderIngestor(work_order_store=store)
    ingestor.ingest_directly(wo.id, "backend-architect", "proj-x", "auth shipped.")

    retrieved = store.get(wo.id)
    assert retrieved is not None
    assert retrieved.output.result == "auth shipped."


def test_secondary_write_no_store_is_silent(caplog: pytest.LogCaptureFixture) -> None:
    """work_order_store=None is the deliberate "secondary target optional" path."""
    ingestor = WorkOrderIngestor()  # no targets at all
    with caplog.at_level(logging.WARNING, logger="bridge.workorder_ingest"):
        ingestor.ingest_directly("wo-noop", "x", "y", "some output")
    # No warning fires when the target is simply absent.
    assert not any(
        rec.levelno == logging.WARNING for rec in caplog.records
    ), caplog.text


def test_secondary_write_orphan_event_warns(
    store: WorkOrderStore, caplog: pytest.LogCaptureFixture
) -> None:
    """S5.1: an event referencing a WO id absent from the store surfaces a WARNING."""
    ingestor = WorkOrderIngestor(work_order_store=store)
    with caplog.at_level(logging.WARNING, logger="bridge.workorder_ingest"):
        ingestor.ingest_directly("orphan-wo-id", "x", "y", "stranded output")
    assert any(
        "orphan workorder.completed" in rec.message and "orphan-wo-id"[:8] in rec.message
        for rec in caplog.records
    ), caplog.text


def test_secondary_write_incompatible_target_warns(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """S5.1: a configured-but-incompatible target (no .get / .save) is visible."""
    class Sketch:
        """Looks like a store, isn't one — no .get / .save surface."""

    ingestor = WorkOrderIngestor(work_order_store=Sketch())  # type: ignore[arg-type]
    with caplog.at_level(logging.WARNING, logger="bridge.workorder_ingest"):
        ingestor.ingest_directly("wo-incompat", "x", "y", "output")
    assert any(
        "incompatible" in rec.message and "Sketch" in rec.message
        for rec in caplog.records
    ), caplog.text


def test_secondary_write_get_failure_logs_exception(
    store: WorkOrderStore, caplog: pytest.LogCaptureFixture
) -> None:
    """A raised .get is logged with exception detail, not silently swallowed."""

    class BrokenStore:
        def get(self, wo_id):  # noqa: D401
            raise RuntimeError("db unreachable")

        def save(self, wo):
            raise AssertionError("save should not be called when get raises")

    ingestor = WorkOrderIngestor(work_order_store=BrokenStore())  # type: ignore[arg-type]
    with caplog.at_level(logging.ERROR, logger="bridge.workorder_ingest"):
        ingestor.ingest_directly("wo-x", "x", "y", "output")
    assert any(
        "WorkOrderStore.get failed" in rec.message for rec in caplog.records
    ), caplog.text


def test_temporal_and_secondary_both_succeed(store: WorkOrderStore) -> None:
    """Both targets fire on a single event when both are configured."""
    tk = MagicMock()
    wo = WorkOrder.create(intent="dual-write", skill="fix", project="proj-y")
    store.save(wo)

    ingestor = WorkOrderIngestor(temporal_knowledge=tk, work_order_store=store)
    ingestor.ingest_directly(wo.id, "fix", "proj-y", "done")

    tk.append.assert_called_once()
    retrieved = store.get(wo.id)
    assert retrieved is not None
    assert retrieved.output.result == "done"
