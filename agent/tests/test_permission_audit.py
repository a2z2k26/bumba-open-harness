"""Tests for permission decision audit trail."""
from __future__ import annotations

import pytest
from bridge.permission_audit import (
    PermissionDecision,
    PermissionAuditLog,
)


class TestPermissionDecision:
    def test_frozen_dataclass(self):
        decision = PermissionDecision(
            decision_id="test-123",
            tool_name="Bash",
            action="deny",
            reason_type="denylist_match",
            reason_detail="Matches denied pattern: rm -rf",
            rule_source="tool_isolation",
            matched_pattern=r"rm\s+-rf",
            context="autonomous",
            agent_id="engineering-backend-architect",
            session_id="session-abc",
        )
        assert decision.action == "deny"
        with pytest.raises(AttributeError):
            decision.action = "allow"  # type: ignore[misc]

    def test_all_reason_types_valid(self):
        from bridge.permission_audit import VALID_REASON_TYPES
        assert "allowlist_match" in VALID_REASON_TYPES
        assert "denylist_match" in VALID_REASON_TYPES
        assert "tier_gate" in VALID_REASON_TYPES
        assert "budget_exceeded" in VALID_REASON_TYPES
        assert "circuit_open" in VALID_REASON_TYPES
        assert "operator_approval" in VALID_REASON_TYPES
        assert "default_deny" in VALID_REASON_TYPES


class TestPermissionAuditLog:
    @pytest.mark.asyncio
    async def test_log_and_query_decision(self):
        from bridge.database import Database
        db = Database(":memory:")
        await db.connect()
        audit = PermissionAuditLog(db)
        await audit.initialize()

        decision = PermissionDecision(
            decision_id="test-001",
            tool_name="Bash",
            action="deny",
            reason_type="denylist_match",
            reason_detail="rm -rf blocked",
            context="autonomous",
            session_id="session-1",
        )
        await audit.log(decision)

        results = await audit.query(tool_name="Bash")
        assert len(results) == 1
        assert results[0].action == "deny"

    @pytest.mark.asyncio
    async def test_query_by_action(self):
        from bridge.database import Database
        db = Database(":memory:")
        await db.connect()
        audit = PermissionAuditLog(db)
        await audit.initialize()

        await audit.log(PermissionDecision(
            decision_id="d1", tool_name="Read", action="allow",
            reason_type="allowlist_match", context="interactive", session_id="s1",
        ))
        await audit.log(PermissionDecision(
            decision_id="d2", tool_name="Bash", action="deny",
            reason_type="denylist_match", context="autonomous", session_id="s1",
        ))

        denials = await audit.query(action="deny")
        assert len(denials) == 1
        assert denials[0].tool_name == "Bash"
