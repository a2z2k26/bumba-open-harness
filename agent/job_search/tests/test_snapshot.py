"""Tests for the approval snapshot store (Z2-S2.3 — highest stakes)."""
from __future__ import annotations


import pytest

from job_search.snapshot import (
    SnapshotMismatch,
    SnapshotStore,
    canonical_hash,
)


# ---------------------------------------------------------------------------
# canonical_hash — determinism
# ---------------------------------------------------------------------------

class TestCanonicalHash:
    def test_same_content_same_hash(self):
        p1 = {"subject": "Hello", "body": "Hi there", "to_email": "a@b.com"}
        p2 = {"to_email": "a@b.com", "body": "Hi there", "subject": "Hello"}
        assert canonical_hash(p1) == canonical_hash(p2)

    def test_different_value_different_hash(self):
        p1 = {"subject": "Hello", "body": "Hi there"}
        p2 = {"subject": "Hello", "body": "Hi there CHANGED"}
        assert canonical_hash(p1) != canonical_hash(p2)

    def test_extra_key_changes_hash(self):
        p1 = {"subject": "Hello"}
        p2 = {"subject": "Hello", "extra": "field"}
        assert canonical_hash(p1) != canonical_hash(p2)

    def test_nested_dict_order_independent(self):
        p1 = {"outer": {"b": 2, "a": 1}}
        p2 = {"outer": {"a": 1, "b": 2}}
        assert canonical_hash(p1) == canonical_hash(p2)

    def test_returns_hex_string(self):
        h = canonical_hash({"x": 1})
        assert isinstance(h, str)
        assert len(h) == 64  # SHA-256 hex = 64 chars
        int(h, 16)  # must be valid hex

    def test_empty_dict_is_stable(self):
        assert canonical_hash({}) == canonical_hash({})

    def test_whitespace_in_value_is_significant(self):
        assert canonical_hash({"v": "hello"}) != canonical_hash({"v": "hello "})


# ---------------------------------------------------------------------------
# SnapshotStore — record, verify, mark_sent
# ---------------------------------------------------------------------------

def _payload(slot: int = 1, body: str = "Hello there") -> dict:
    return {
        "slot": slot,
        "to_email": "alice@example.com",
        "subject": "Following up",
        "body": body,
        "contact_name": "Alice",
        "contact_title": "VP Engineering",
    }


class TestSnapshotStore:
    def test_record_then_verify_ok(self, tmp_path):
        store = SnapshotStore(tmp_path)
        p = _payload()
        store.record_approval("page1", p)
        # Identical payload should not raise
        store.verify_or_raise("page1", p)

    def test_verify_raises_on_body_change(self, tmp_path):
        store = SnapshotStore(tmp_path)
        store.record_approval("page1", _payload(body="original"))
        with pytest.raises(SnapshotMismatch) as exc_info:
            store.verify_or_raise("page1", _payload(body="EDITED"))
        assert exc_info.value.page_id == "page1"

    def test_verify_raises_when_no_snapshot(self, tmp_path):
        store = SnapshotStore(tmp_path)
        with pytest.raises(SnapshotMismatch):
            store.verify_or_raise("unknown_page", _payload())

    def test_mark_sent_updates_status(self, tmp_path):
        store = SnapshotStore(tmp_path)
        store.record_approval("page1", _payload())
        store.mark_sent("page1")
        record = store.get_record("page1")
        assert record is not None
        assert record["status"] == "sent"
        assert record["sent_at"] is not None

    def test_mark_drift_updates_status(self, tmp_path):
        store = SnapshotStore(tmp_path)
        store.record_approval("page1", _payload())
        store.mark_drift("page1")
        record = store.get_record("page1")
        assert record["status"] == "snapshot_drift"

    def test_drift_auto_marked_on_verify_failure(self, tmp_path):
        store = SnapshotStore(tmp_path)
        store.record_approval("page1", _payload(body="original"))
        with pytest.raises(SnapshotMismatch):
            store.verify_or_raise("page1", _payload(body="CHANGED"))
        record = store.get_record("page1")
        assert record["status"] == "snapshot_drift"

    def test_record_approval_is_idempotent(self, tmp_path):
        store = SnapshotStore(tmp_path)
        store.record_approval("page1", _payload())
        store.record_approval("page1", _payload())  # same page, same payload
        record = store.get_record("page1")
        assert record is not None

    def test_record_stores_full_payload(self, tmp_path):
        store = SnapshotStore(tmp_path)
        p = _payload()
        store.record_approval("page1", p)
        record = store.get_record("page1")
        assert record["payload"]["subject"] == p["subject"]
        assert record["payload"]["body"] == p["body"]

    def test_record_returns_hash_string(self, tmp_path):
        store = SnapshotStore(tmp_path)
        h = store.record_approval("page1", _payload())
        assert isinstance(h, str)
        assert len(h) == 64

    def test_multiple_pages_independent(self, tmp_path):
        store = SnapshotStore(tmp_path)
        store.record_approval("page1", _payload(body="A"))
        store.record_approval("page2", _payload(body="B"))
        store.verify_or_raise("page1", _payload(body="A"))
        store.verify_or_raise("page2", _payload(body="B"))

    def test_get_record_returns_none_for_unknown(self, tmp_path):
        store = SnapshotStore(tmp_path)
        assert store.get_record("nope") is None

    def test_corrupted_file_resets_gracefully(self, tmp_path):
        state_dir = tmp_path / "service_state"
        state_dir.mkdir()
        (state_dir / "send_snapshots.json").write_text("INVALID{{")
        store = SnapshotStore(tmp_path)
        # Should not raise — unknown page raises SnapshotMismatch, not IOError
        with pytest.raises(SnapshotMismatch):
            store.verify_or_raise("page1", _payload())

    def test_audit_query_groups_by_status(self, tmp_path):
        store = SnapshotStore(tmp_path)
        store.record_approval("p1", _payload())
        store.record_approval("p2", _payload())
        store.mark_sent("p1")
        store.mark_drift("p2")
        audit = store.audit_query()
        assert "p1" in audit["sent"]
        assert "p2" in audit["snapshot_drift"]

    def test_state_dir_created_automatically(self, tmp_path):
        nested = tmp_path / "a" / "b"
        store = SnapshotStore(nested)
        store.record_approval("p1", _payload())
        assert (nested / "service_state" / "send_snapshots.json").exists()


# ---------------------------------------------------------------------------
# SnapshotMismatch exception
# ---------------------------------------------------------------------------

class TestSnapshotMismatch:
    def test_attributes_set_correctly(self):
        exc = SnapshotMismatch("mypage", "abc123", "def456")
        assert exc.page_id == "mypage"
        assert exc.approved_hash == "abc123"
        assert exc.current_hash == "def456"

    def test_str_contains_page_id(self):
        exc = SnapshotMismatch("mypage", "abc123", "def456")
        assert "mypage" in str(exc)
