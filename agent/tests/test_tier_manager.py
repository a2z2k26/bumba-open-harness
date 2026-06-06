"""Tests for MS5.4: Graduated Kernel Access."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from bridge.tier_manager import (
    BPLUS_TO_B_DAYS_IN_TIER,
    BPLUS_TO_B_DEPLOY_MIN,
    BPLUS_TO_B_TRUST_MIN,
    C_TO_BPLUS_DEPLOY_MIN,
    C_TO_BPLUS_FILE_DEPLOY_MIN,
    C_TO_BPLUS_TRUST_MIN,
    TIER_A,
    TIER_B,
    TIER_B_PLUS,
    TIER_C,
    TierManager,
)


@pytest.fixture
def mgr(tmp_path):
    return TierManager(data_path=tmp_path / "tiers.json")


@pytest.fixture
def mem_mgr():
    return TierManager()


# ── File Registration ──


class TestFileRegistration:
    def test_register_file(self, mem_mgr):
        ft = mem_mgr.register_file("bridge/app.py")
        assert ft.path == "bridge/app.py"
        assert ft.current_tier == TIER_C

    def test_register_with_tier(self, mem_mgr):
        ft = mem_mgr.register_file("bridge/security.py", tier=TIER_A, locked=True)
        assert ft.current_tier == TIER_A
        assert ft.locked is True

    def test_register_duplicate_returns_existing(self, mem_mgr):
        ft1 = mem_mgr.register_file("bridge/app.py")
        ft2 = mem_mgr.register_file("bridge/app.py")
        assert ft1 is ft2

    def test_list_files(self, mem_mgr):
        mem_mgr.register_file("a.py")
        mem_mgr.register_file("b.py")
        assert len(mem_mgr.list_files()) == 2

    def test_list_files_by_tier(self, mem_mgr):
        mem_mgr.register_file("a.py", tier=TIER_C)
        mem_mgr.register_file("b.py", tier=TIER_A, locked=True)
        assert len(mem_mgr.list_files(tier=TIER_C)) == 1
        assert len(mem_mgr.list_files(tier=TIER_A)) == 1


# ── Immutability ──


class TestImmutability:
    def test_security_py_is_immutable(self, mem_mgr):
        assert mem_mgr.is_immutable("bridge/security.py") is True

    def test_trust_score_py_is_immutable(self, mem_mgr):
        assert mem_mgr.is_immutable("bridge/trust_score.py") is True

    def test_regular_file_not_immutable(self, mem_mgr):
        assert mem_mgr.is_immutable("bridge/app.py") is False

    def test_immutable_file_cannot_promote(self, mem_mgr):
        mem_mgr.register_file("bridge/security.py", tier=TIER_C)
        assert mem_mgr.promote("bridge/security.py", TIER_B_PLUS) is False

    def test_immutable_check_c_to_bplus(self, mem_mgr):
        mem_mgr.register_file("bridge/security.py", tier=TIER_C)
        ok, reason = mem_mgr.check_c_to_bplus("bridge/security.py", 95.0, 100)
        assert ok is False
        assert "Immutable" in reason


# ── Deploy Tracking ──


class TestDeployTracking:
    def test_record_success(self, mem_mgr):
        mem_mgr.register_file("app.py")
        mem_mgr.record_deploy("app.py", success=True)
        ft = mem_mgr.get_file("app.py")
        assert ft.deploy_count == 1
        assert ft.last_deploy != ""

    def test_record_failure(self, mem_mgr):
        mem_mgr.register_file("app.py")
        mem_mgr.record_deploy("app.py", success=False)
        ft = mem_mgr.get_file("app.py")
        assert ft.rollback_count == 1
        assert ft.last_rollback != ""

    def test_auto_register_on_deploy(self, mem_mgr):
        mem_mgr.record_deploy("new.py", success=True)
        ft = mem_mgr.get_file("new.py")
        assert ft is not None


# ── C → B+ Promotion ──


class TestCToBPlus:
    def _setup_eligible(self, mgr):
        mgr.register_file("widget.py", tier=TIER_C)
        ft = mgr.get_file("widget.py")
        ft.deploy_count = C_TO_BPLUS_FILE_DEPLOY_MIN + 1
        # Ensure no recent rollback
        ft.last_rollback = ""
        return ft

    def test_eligible(self, mem_mgr):
        self._setup_eligible(mem_mgr)
        ok, _ = mem_mgr.check_c_to_bplus(
            "widget.py", C_TO_BPLUS_TRUST_MIN + 5, C_TO_BPLUS_DEPLOY_MIN + 5
        )
        assert ok is True

    def test_trust_too_low(self, mem_mgr):
        self._setup_eligible(mem_mgr)
        ok, reason = mem_mgr.check_c_to_bplus(
            "widget.py", C_TO_BPLUS_TRUST_MIN - 5, C_TO_BPLUS_DEPLOY_MIN + 5
        )
        assert ok is False
        assert "Trust" in reason

    def test_not_enough_total_deploys(self, mem_mgr):
        self._setup_eligible(mem_mgr)
        ok, reason = mem_mgr.check_c_to_bplus(
            "widget.py", C_TO_BPLUS_TRUST_MIN + 5, C_TO_BPLUS_DEPLOY_MIN - 5
        )
        assert ok is False

    def test_not_enough_file_deploys(self, mem_mgr):
        mem_mgr.register_file("widget.py", tier=TIER_C)
        ft = mem_mgr.get_file("widget.py")
        ft.deploy_count = 1
        ok, reason = mem_mgr.check_c_to_bplus(
            "widget.py", C_TO_BPLUS_TRUST_MIN + 5, C_TO_BPLUS_DEPLOY_MIN + 5
        )
        assert ok is False

    def test_recent_rollback_blocks(self, mem_mgr):
        self._setup_eligible(mem_mgr)
        ft = mem_mgr.get_file("widget.py")
        ft.last_rollback = datetime.now(timezone.utc).isoformat()
        ok, reason = mem_mgr.check_c_to_bplus(
            "widget.py", C_TO_BPLUS_TRUST_MIN + 5, C_TO_BPLUS_DEPLOY_MIN + 5
        )
        assert ok is False
        assert "Rollback" in reason

    def test_wrong_tier(self, mem_mgr):
        mem_mgr.register_file("widget.py", tier=TIER_B_PLUS)
        ok, reason = mem_mgr.check_c_to_bplus(
            "widget.py", 95, 100
        )
        assert ok is False
        assert "Not at Tier C" in reason


# ── B+ → B Promotion ──


class TestBPlusToB:
    def test_eligible(self, mem_mgr):
        mem_mgr.register_file("widget.py", tier=TIER_B_PLUS)
        ft = mem_mgr.get_file("widget.py")
        ft.promoted_at = (
            datetime.now(timezone.utc) - timedelta(days=BPLUS_TO_B_DAYS_IN_TIER + 1)
        ).isoformat()
        ok, _ = mem_mgr.check_bplus_to_b(
            "widget.py", BPLUS_TO_B_TRUST_MIN + 1, BPLUS_TO_B_DEPLOY_MIN + 1
        )
        assert ok is True

    def test_trust_too_low(self, mem_mgr):
        mem_mgr.register_file("widget.py", tier=TIER_B_PLUS)
        ok, reason = mem_mgr.check_bplus_to_b(
            "widget.py", BPLUS_TO_B_TRUST_MIN - 5, BPLUS_TO_B_DEPLOY_MIN + 1
        )
        assert ok is False

    def test_not_enough_time(self, mem_mgr):
        mem_mgr.register_file("widget.py", tier=TIER_B_PLUS)
        ft = mem_mgr.get_file("widget.py")
        ft.promoted_at = datetime.now(timezone.utc).isoformat()
        ok, reason = mem_mgr.check_bplus_to_b(
            "widget.py", BPLUS_TO_B_TRUST_MIN + 1, BPLUS_TO_B_DEPLOY_MIN + 1
        )
        assert ok is False
        assert "days" in reason


# ── Promote / Demote ──


class TestPromoteDemote:
    def test_promote(self, mem_mgr):
        mem_mgr.register_file("x.py", tier=TIER_C)
        assert mem_mgr.promote("x.py", TIER_B_PLUS, reason="earned") is True
        ft = mem_mgr.get_file("x.py")
        assert ft.current_tier == TIER_B_PLUS
        assert ft.promoted_at != ""
        assert len(ft.tier_history) == 2  # initial + promotion

    def test_promote_locked_fails(self, mem_mgr):
        mem_mgr.register_file("x.py", tier=TIER_C, locked=True, lock_reason="test")
        assert mem_mgr.promote("x.py", TIER_B_PLUS) is False

    def test_demote_resets_counters(self, mem_mgr):
        mem_mgr.register_file("x.py", tier=TIER_B_PLUS)
        ft = mem_mgr.get_file("x.py")
        ft.deploy_count = 50
        mem_mgr.demote("x.py", TIER_C, reason="rollback")
        ft = mem_mgr.get_file("x.py")
        assert ft.current_tier == TIER_C
        assert ft.deploy_count == 0
        assert ft.rollback_count == 0

    def test_demote_nonexistent(self, mem_mgr):
        assert mem_mgr.demote("nope.py", TIER_C) is False


# ── Audit ──


class TestAudit:
    def test_no_issues_when_consistent(self, mem_mgr):
        mem_mgr.register_file("x.py", tier=TIER_C)
        issues = mem_mgr.audit({"deploy": 90.0})
        assert len(issues) == 0

    def test_detects_bplus_trust_mismatch(self, mem_mgr):
        mem_mgr.register_file("x.py", tier=TIER_B_PLUS)
        issues = mem_mgr.audit({"deploy": 50.0})
        assert len(issues) == 1
        assert issues[0]["issue"] == "trust_below_tier"

    def test_detects_b_trust_mismatch(self, mem_mgr):
        mem_mgr.register_file("x.py", tier=TIER_B)
        issues = mem_mgr.audit({"deploy": 80.0})
        assert len(issues) == 1

    def test_skips_locked_files(self, mem_mgr):
        mem_mgr.register_file("x.py", tier=TIER_B_PLUS, locked=True)
        issues = mem_mgr.audit({"deploy": 30.0})
        assert len(issues) == 0


# ── Persistence ──


class TestPersistence:
    def test_save_and_load(self, tmp_path):
        path = tmp_path / "tiers.json"
        mgr1 = TierManager(data_path=path)
        mgr1.register_file("app.py", tier=TIER_C)
        mgr1.record_deploy("app.py", success=True)

        mgr2 = TierManager(data_path=path)
        ft = mgr2.get_file("app.py")
        assert ft is not None
        assert ft.deploy_count == 1

    def test_promotion_persisted(self, tmp_path):
        path = tmp_path / "tiers.json"
        mgr1 = TierManager(data_path=path)
        mgr1.register_file("app.py", tier=TIER_C)
        mgr1.promote("app.py", TIER_B_PLUS)

        mgr2 = TierManager(data_path=path)
        ft = mgr2.get_file("app.py")
        assert ft.current_tier == TIER_B_PLUS


# ── Formatting ──


class TestFormatting:
    def test_tier_table(self, mem_mgr):
        mem_mgr.register_file("a.py", tier=TIER_C)
        mem_mgr.register_file("b.py", tier=TIER_A, locked=True)
        table = mem_mgr.format_tier_table()
        assert "a.py" in table
        assert "b.py" in table
        assert "Tier" in table

    def test_empty_table(self, mem_mgr):
        table = mem_mgr.format_tier_table()
        assert "No files" in table

    def test_count(self, mem_mgr):
        mem_mgr.register_file("a.py", tier=TIER_C)
        mem_mgr.register_file("b.py", tier=TIER_A)
        assert mem_mgr.count() == 2
        assert mem_mgr.count(tier=TIER_C) == 1
