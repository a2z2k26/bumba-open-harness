"""Tests for WorkOrder correlation + cost primitives (#570)."""
from __future__ import annotations

from bridge.work_order import WorkOrder


def test_workorder_has_idempotency_key_field():
    wo = WorkOrder.create(intent="test", skill="fix-test", project="proj")
    assert wo.idempotency_key is None
    assert wo.trigger_source == "dispatcher"
    assert wo.cost_cap_usd is None
    assert wo.retry_of is None
    assert wo.attempt_number == 1


def test_workorder_with_idempotency_key():
    from dataclasses import replace
    wo = WorkOrder.create(intent="test", skill="fix-test", project="proj")
    wo2 = replace(wo, idempotency_key="msg-abc123", trigger_source="discord")
    assert wo2.idempotency_key == "msg-abc123"
    assert wo2.trigger_source == "discord"


def test_workorder_to_dict_includes_s07_fields():
    from dataclasses import replace
    wo = WorkOrder.create(intent="test", skill="fix-test", project="proj")
    wo = replace(wo, idempotency_key="key-1", trigger_source="webhook", cost_cap_usd=0.5)
    d = wo.to_dict()
    assert d["idempotency_key"] == "key-1"
    assert d["trigger_source"] == "webhook"
    assert d["cost_cap_usd"] == 0.5
    assert d["attempt_number"] == 1


def test_workorder_from_dict_roundtrip():
    from dataclasses import replace
    wo = WorkOrder.create(intent="test", skill="fix-test", project="proj")
    wo = replace(wo, idempotency_key="key-2", trigger_source="cron", retry_of="old-id", attempt_number=2)
    restored = WorkOrder.from_dict(wo.to_dict())
    assert restored.idempotency_key == "key-2"
    assert restored.trigger_source == "cron"
    assert restored.retry_of == "old-id"
    assert restored.attempt_number == 2


def test_workorder_store_idempotency_lookup(tmp_path):
    from bridge.work_order_store import WorkOrderStore
    from dataclasses import replace

    store = WorkOrderStore(tmp_path / "test.db")
    wo = WorkOrder.create(intent="test", skill="fix-test", project="proj")
    wo = replace(wo, idempotency_key="msg-xyz")
    store.save(wo)

    found = store.find_by_idempotency_key("msg-xyz")
    assert found is not None
    assert found.id == wo.id


def test_workorder_store_idempotency_key_not_found(tmp_path):
    from bridge.work_order_store import WorkOrderStore
    store = WorkOrderStore(tmp_path / "test.db")
    assert store.find_by_idempotency_key("does-not-exist") is None


def test_workorder_store_s07_migration(tmp_path):
    """Migration adds idempotency_key column idempotently."""
    import sqlite3
    from bridge.work_order_store import WorkOrderStore

    # Create store (runs migration)
    store = WorkOrderStore(tmp_path / "test.db")

    # Check column exists
    conn = sqlite3.connect(str(tmp_path / "test.db"))
    cols = {row[1] for row in conn.execute("PRAGMA table_info(work_orders)").fetchall()}
    conn.close()
    assert "idempotency_key" in cols

    # Second open should not fail
    store2 = WorkOrderStore(tmp_path / "test.db")
    store2.close()


def test_workorder_from_dict_defaults_for_old_rows():
    """Old WO dicts without S07 fields get default values."""
    data = {
        "id": "abc",
        "intent": "test",
        "skill": "fix-test",
        "project": "proj",
        "status": "pending",
    }
    wo = WorkOrder.from_dict(data)
    assert wo.idempotency_key is None
    assert wo.trigger_source == "dispatcher"
    assert wo.attempt_number == 1
