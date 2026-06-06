"""Tests for MS4.8: Self-Editing Core Memory."""

from __future__ import annotations

import pytest

from bridge.self_edit_memory import (
    EditRequest,
    SelfEditMemory,
    classify_tier,
)


@pytest.fixture
def mem(tmp_path):
    return SelfEditMemory(tmp_path / "edit.db")


# ── Tier Classification ──

class TestTierClassification:
    def test_tier_a_learning(self):
        assert classify_tier("learning") == "A"

    def test_tier_a_tools(self):
        assert classify_tier("tools") == "A"

    def test_tier_a_general(self):
        assert classify_tier("general") == "A"

    def test_tier_b_preference(self):
        assert classify_tier("preference") == "B"

    def test_tier_b_decision(self):
        assert classify_tier("decision") == "B"

    def test_tier_c_identity(self):
        assert classify_tier("identity") == "C"

    def test_tier_c_security(self):
        assert classify_tier("security") == "C"

    def test_unknown_defaults_to_a(self):
        assert classify_tier("random_category") == "A"


# ── Tier A: Auto-Approved ──

class TestTierAEdits:
    def test_create_auto_approved(self, mem):
        req = EditRequest(
            key="tool:brave-search",
            action="create",
            new_value="Brave search works well for web queries",
            category="learning",
        )
        result = mem.process_edit(req)
        assert result.success is True
        assert result.auto_approved is True
        assert result.tier == "A"
        assert result.audit_id > 0

    def test_update_auto_approved(self, mem):
        req = EditRequest(
            key="tool:brave-search",
            action="update",
            new_value="Updated info",
            category="tools",
            reason="Better description",
        )
        result = mem.process_edit(req, old_value="Old info")
        assert result.success is True
        assert result.auto_approved is True

    def test_delete_auto_approved(self, mem):
        req = EditRequest(
            key="example:old",
            action="delete",
            category="examples",
            reason="No longer useful",
        )
        result = mem.process_edit(req, old_value="some value")
        assert result.success is True

    def test_audit_recorded(self, mem):
        req = EditRequest(
            key="test-key",
            action="create",
            new_value="value",
            category="learning",
            reason="test",
        )
        result = mem.process_edit(req)
        entries = mem.get_audit_log(key="test-key")
        assert len(entries) == 1
        assert entries[0].action == "create"
        assert entries[0].auto_approved is True


# ── Tier B: Requires Approval ──

class TestTierBEdits:
    def test_preference_needs_approval(self, mem):
        req = EditRequest(
            key="pref:coding-style",
            action="update",
            new_value="Prefer functional style",
            category="preference",
        )
        result = mem.process_edit(req)
        assert result.success is False
        assert result.needs_approval is True
        assert result.tier == "B"

    def test_pending_edit_created(self, mem):
        req = EditRequest(
            key="dec:arch",
            action="create",
            new_value="Use microservices",
            category="decision",
        )
        mem.process_edit(req)
        pending = mem.get_pending_edits()
        assert len(pending) == 1
        assert pending[0]["key"] == "dec:arch"

    def test_approve_pending(self, mem):
        req = EditRequest(
            key="pref:x", action="update", new_value="v",
            category="preference",
        )
        mem.process_edit(req)
        pending = mem.get_pending_edits()
        assert mem.approve_pending(pending[0]["id"]) is True
        # Pending list should be empty now
        remaining = mem.get_pending_edits()
        assert len(remaining) == 0

    def test_reject_pending(self, mem):
        req = EditRequest(
            key="pref:y", action="update", new_value="v",
            category="preference",
        )
        mem.process_edit(req)
        pending = mem.get_pending_edits()
        assert mem.reject_pending(pending[0]["id"], reason="Not useful") is True


# ── Tier C: Rejected ──

class TestTierCEdits:
    def test_identity_rejected(self, mem):
        req = EditRequest(
            key="identity:name",
            action="update",
            new_value="New Name",
            category="identity",
        )
        result = mem.process_edit(req)
        assert result.rejected is True
        assert "protected" in result.reject_reason

    def test_security_rejected(self, mem):
        req = EditRequest(
            key="sec:token",
            action="update",
            new_value="new-token",
            category="security",
        )
        result = mem.process_edit(req)
        assert result.rejected is True

    def test_kernel_rejected(self, mem):
        req = EditRequest(
            key="kernel:config",
            action="update",
            new_value="modified",
            category="kernel",
        )
        result = mem.process_edit(req)
        assert result.rejected is True


# ── Audit Log ──

class TestAuditLog:
    def test_audit_log_records_old_value(self, mem):
        req = EditRequest(
            key="k", action="update", new_value="new",
            category="learning", reason="test",
        )
        mem.process_edit(req, old_value="old")
        entries = mem.get_audit_log(key="k")
        assert entries[0].old_value == "old"
        assert entries[0].new_value == "new"

    def test_audit_log_with_trace_id(self, mem):
        req = EditRequest(
            key="k", action="create", new_value="v",
            category="learning", trace_id="trace-abc-123",
        )
        mem.process_edit(req)
        entries = mem.get_audit_log(key="k")
        assert entries[0].trace_id == "trace-abc-123"

    def test_audit_count(self, mem):
        assert mem.audit_count() == 0
        for i in range(5):
            mem.process_edit(EditRequest(
                key=f"k{i}", action="create", new_value="v",
                category="learning",
            ))
        assert mem.audit_count() == 5
        assert mem.audit_count("k0") == 1

    def test_get_audit_entry_by_id(self, mem):
        req = EditRequest(
            key="test", action="create", new_value="val",
            category="learning",
        )
        result = mem.process_edit(req)
        entry = mem.get_audit_entry(result.audit_id)
        assert entry is not None
        assert entry.key == "test"

    def test_get_nonexistent_audit_entry(self, mem):
        assert mem.get_audit_entry(999) is None

    def test_audit_all_keys(self, mem):
        for i in range(3):
            mem.process_edit(EditRequest(
                key=f"k{i}", action="create", new_value="v",
                category="learning",
            ))
        all_entries = mem.get_audit_log()
        assert len(all_entries) == 3


# ── Formatting ──

class TestAuditFormatting:
    def test_format_empty(self, mem):
        result = mem.format_audit_log([])
        assert "No audit" in result

    def test_format_entries(self, mem):
        mem.process_edit(EditRequest(
            key="k", action="create", new_value="v",
            category="learning", reason="test reason",
        ))
        entries = mem.get_audit_log()
        result = mem.format_audit_log(entries)
        assert "Key" in result
        assert "Action" in result
        assert "test reason" in result
