"""Tests for bridge/plist_manager.py — LaunchDaemon plist management."""

from __future__ import annotations

import json
import plistlib
import time
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from bridge.plist_manager import (
    PlistManager,
    KNOWN_SERVICES,
    SERVICE_LABELS,
    MAX_DISABLED,
    COOLDOWN_SECONDS,
)


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    """Provide a temporary data directory."""
    d = tmp_path / "data"
    d.mkdir()
    return d


@pytest.fixture
def mgr(data_dir: Path) -> PlistManager:
    """Provide a PlistManager with mocked command execution."""
    m = PlistManager(data_dir)
    # Default: all commands succeed
    m._execute_command = MagicMock(return_value=(0, "", ""))
    return m


# ------------------------------------------------------------------
# Service name validation
# ------------------------------------------------------------------


class TestServiceNameValidation:
    """Reject unknown service names."""

    def test_reject_unknown_service(self, mgr: PlistManager):
        result = mgr.restart_service("nonexistent")
        assert result["success"] is False
        assert "Unknown service" in result["message"]

    def test_reject_empty_service_name(self, mgr: PlistManager):
        result = mgr.disable_service("")
        assert result["success"] is False
        assert "Unknown service" in result["message"]

    def test_accept_known_service(self, mgr: PlistManager):
        result = mgr.restart_service("email")
        assert result["success"] is True

    def test_all_known_services_have_labels(self):
        for name in KNOWN_SERVICES:
            assert name in SERVICE_LABELS


# ------------------------------------------------------------------
# Protected service enforcement
# ------------------------------------------------------------------


class TestProtectedServices:
    """Operations on bridge and monitor must be rejected."""

    def test_restart_bridge_rejected(self, mgr: PlistManager):
        result = mgr.restart_service("bridge")
        assert result["success"] is False
        assert "protected" in result["message"].lower()

    def test_restart_monitor_rejected(self, mgr: PlistManager):
        result = mgr.restart_service("monitor")
        assert result["success"] is False
        assert "protected" in result["message"].lower()

    def test_disable_bridge_rejected(self, mgr: PlistManager):
        result = mgr.disable_service("bridge")
        assert result["success"] is False
        assert "protected" in result["message"].lower()

    def test_disable_monitor_rejected(self, mgr: PlistManager):
        result = mgr.disable_service("monitor")
        assert result["success"] is False
        assert "protected" in result["message"].lower()

    def test_enable_bridge_rejected(self, mgr: PlistManager):
        result = mgr.enable_service("bridge")
        assert result["success"] is False
        assert "protected" in result["message"].lower()

    def test_update_interval_bridge_rejected(self, mgr: PlistManager):
        result = mgr.update_interval("bridge", 600)
        assert result["success"] is False
        assert "protected" in result["message"].lower()

    def test_is_protected_true(self, mgr: PlistManager):
        assert mgr.is_protected("bridge") is True
        assert mgr.is_protected("monitor") is True

    def test_is_protected_false_for_regular(self, mgr: PlistManager):
        assert mgr.is_protected("email") is False
        assert mgr.is_protected("briefing") is False

    def test_get_status_allowed_for_protected(self, mgr: PlistManager):
        """get_service_status is read-only, should work for protected services."""
        result = mgr.get_service_status("bridge")
        assert result["success"] is True


# ------------------------------------------------------------------
# Cooldown enforcement
# ------------------------------------------------------------------


class TestCooldown:
    """Reject operations within 5 min cooldown window."""

    def test_cooldown_blocks_second_operation(self, mgr: PlistManager):
        result1 = mgr.restart_service("email")
        assert result1["success"] is True

        result2 = mgr.restart_service("email")
        assert result2["success"] is False
        assert "cooldown" in result2["message"].lower()

    def test_cooldown_per_service(self, mgr: PlistManager):
        """Cooldown on email should not block calendar."""
        result1 = mgr.restart_service("email")
        assert result1["success"] is True

        result2 = mgr.restart_service("calendar")
        assert result2["success"] is True

    def test_cooldown_expires(self, mgr: PlistManager):
        """After cooldown period, operations should succeed."""
        mgr.restart_service("email")

        # Simulate time passing
        mgr._state["last_operation"]["email"] = time.time() - COOLDOWN_SECONDS - 1
        mgr._save_state()

        result = mgr.restart_service("email")
        assert result["success"] is True

    def test_cooldown_shows_remaining_time(self, mgr: PlistManager):
        mgr.restart_service("checkin")
        result = mgr.restart_service("checkin")
        assert result["success"] is False
        assert "remaining" in result["message"].lower()


# ------------------------------------------------------------------
# Max disabled limit
# ------------------------------------------------------------------


class TestMaxDisabled:
    """Cannot have more than MAX_DISABLED services disabled at once."""

    def test_max_disabled_enforced(self, mgr: PlistManager):
        mgr.disable_service("email")
        # Bypass cooldown
        mgr._state["last_operation"]["email"] = 0.0

        mgr.disable_service("calendar")
        mgr._state["last_operation"]["calendar"] = 0.0

        result = mgr.disable_service("checkin")
        assert result["success"] is False
        assert "max" in result["message"].lower() or str(MAX_DISABLED) in result["message"]

    def test_reenable_allows_new_disable(self, mgr: PlistManager):
        mgr.disable_service("email")
        mgr._state["last_operation"]["email"] = 0.0

        mgr.disable_service("calendar")
        mgr._state["last_operation"]["calendar"] = 0.0

        # Re-enable email
        mgr.enable_service("email")
        mgr._state["last_operation"]["email"] = 0.0

        # Now disabling checkin should work
        result = mgr.disable_service("checkin")
        assert result["success"] is True

    def test_disable_already_disabled_does_not_count_twice(self, mgr: PlistManager):
        """Re-disabling an already-disabled service should not increase count."""
        mgr.disable_service("email")
        mgr._state["last_operation"]["email"] = 0.0

        mgr.disable_service("calendar")
        mgr._state["last_operation"]["calendar"] = 0.0

        # Try disabling email again (already disabled)
        result = mgr.disable_service("email")
        assert result["success"] is True  # should succeed since it's already disabled


# ------------------------------------------------------------------
# Dependency warnings
# ------------------------------------------------------------------


class TestDependencies:
    """Warn when disabling services that others depend on."""

    def test_get_dependents_email(self, mgr: PlistManager):
        deps = mgr.get_dependents("email")
        assert "briefing" in deps

    def test_get_dependents_calendar(self, mgr: PlistManager):
        deps = mgr.get_dependents("calendar")
        assert "briefing" in deps

    def test_get_dependents_job_search(self, mgr: PlistManager):
        deps = mgr.get_dependents("job-search")
        assert "job-execute" in deps

    def test_get_dependents_no_deps(self, mgr: PlistManager):
        deps = mgr.get_dependents("checkin")
        assert deps == []

    def test_disable_with_dependents_warns(self, mgr: PlistManager):
        result = mgr.disable_service("email")
        assert result["success"] is True
        assert "warnings" in result
        assert any("briefing" in w for w in result["warnings"])

    def test_disable_without_dependents_no_warning(self, mgr: PlistManager):
        result = mgr.disable_service("checkin")
        assert result["success"] is True
        assert "warnings" not in result


# ------------------------------------------------------------------
# Interval bounds validation
# ------------------------------------------------------------------


class TestUpdateInterval:
    """Validate interval bounds and plist modification."""

    def test_interval_too_small(self, mgr: PlistManager):
        result = mgr.update_interval("email", 30)
        assert result["success"] is False
        assert "min 60s" in result["message"].lower()

    def test_interval_too_large(self, mgr: PlistManager):
        result = mgr.update_interval("email", 100_000)
        assert result["success"] is False
        assert "max 86400s" in result["message"].lower()

    def test_interval_boundary_min(self, data_dir: Path, tmp_path: Path):
        """60s should be accepted."""
        mgr = PlistManager(data_dir)
        mgr._execute_command = MagicMock(return_value=(0, "", ""))

        plist_file = tmp_path / "com.bumba.agent-email.plist"
        plist_data = {"Label": "com.bumba.agent-email", "StartInterval": 7200}
        with plist_file.open("wb") as f:
            plistlib.dump(plist_data, f)

        with patch.object(mgr, "_plist_path", return_value=plist_file):
            result = mgr.update_interval("email", 60)
        assert result["success"] is True

    def test_interval_boundary_max(self, data_dir: Path, tmp_path: Path):
        """86400s should be accepted."""
        mgr = PlistManager(data_dir)
        mgr._execute_command = MagicMock(return_value=(0, "", ""))

        plist_file = tmp_path / "com.bumba.agent-email.plist"
        plist_data = {"Label": "com.bumba.agent-email", "StartInterval": 7200}
        with plist_file.open("wb") as f:
            plistlib.dump(plist_data, f)

        with patch.object(mgr, "_plist_path", return_value=plist_file):
            result = mgr.update_interval("email", 86400)
        assert result["success"] is True

    def test_interval_updates_plist(self, data_dir: Path, tmp_path: Path):
        """Verify the plist file is actually modified."""
        mgr = PlistManager(data_dir)
        mgr._execute_command = MagicMock(return_value=(0, "", ""))

        plist_file = tmp_path / "com.bumba.agent-email.plist"
        plist_data = {"Label": "com.bumba.agent-email", "StartInterval": 7200}
        with plist_file.open("wb") as f:
            plistlib.dump(plist_data, f)

        with patch.object(mgr, "_plist_path", return_value=plist_file):
            result = mgr.update_interval("email", 3600)

        assert result["success"] is True
        with plist_file.open("rb") as f:
            updated = plistlib.load(f)
        assert updated["StartInterval"] == 3600

    def test_interval_no_start_interval_key(self, data_dir: Path, tmp_path: Path):
        """Services using StartCalendarInterval should be rejected."""
        mgr = PlistManager(data_dir)
        mgr._execute_command = MagicMock(return_value=(0, "", ""))

        plist_file = tmp_path / "com.bumba.agent-briefing.plist"
        plist_data = {"Label": "com.bumba.agent-briefing", "StartCalendarInterval": {"Hour": 7}}
        with plist_file.open("wb") as f:
            plistlib.dump(plist_data, f)

        with patch.object(mgr, "_plist_path", return_value=plist_file):
            result = mgr.update_interval("briefing", 3600)

        assert result["success"] is False
        assert "StartCalendarInterval" in result["message"]

    def test_interval_plist_not_found(self, data_dir: Path, tmp_path: Path):
        """Missing plist file."""
        mgr = PlistManager(data_dir)
        mgr._execute_command = MagicMock(return_value=(0, "", ""))

        missing = tmp_path / "does-not-exist.plist"
        with patch.object(mgr, "_plist_path", return_value=missing):
            result = mgr.update_interval("email", 3600)

        assert result["success"] is False
        assert "not found" in result["message"].lower()


# ------------------------------------------------------------------
# Operation logging
# ------------------------------------------------------------------


class TestOperationLogging:
    """All operations are logged to JSONL."""

    def test_restart_logged(self, mgr: PlistManager, data_dir: Path):
        mgr.restart_service("email")
        log_path = data_dir / "plist_operations.jsonl"
        assert log_path.exists()
        entries = [json.loads(line) for line in log_path.read_text().splitlines()]
        assert len(entries) == 1
        assert entries[0]["operation"] == "restart"
        assert entries[0]["service"] == "email"
        assert entries[0]["success"] is True

    def test_failed_operation_logged(self, mgr: PlistManager, data_dir: Path):
        result = mgr.restart_service("bridge")
        assert result["success"] is False
        # Protected service rejections happen before execution, no log entry
        # (logged operations are those that attempt execution)

    def test_multiple_operations_logged(self, mgr: PlistManager, data_dir: Path):
        mgr.restart_service("email")
        # Bypass cooldown
        mgr._state["last_operation"]["email"] = 0.0
        mgr.disable_service("email")

        log_path = data_dir / "plist_operations.jsonl"
        entries = [json.loads(line) for line in log_path.read_text().splitlines()]
        assert len(entries) == 2
        assert entries[0]["operation"] == "restart"
        assert entries[1]["operation"] == "disable"

    def test_log_has_timestamp(self, mgr: PlistManager, data_dir: Path):
        mgr.restart_service("calendar")
        log_path = data_dir / "plist_operations.jsonl"
        entries = [json.loads(line) for line in log_path.read_text().splitlines()]
        assert "timestamp" in entries[0]
        assert "T" in entries[0]["timestamp"]  # ISO format


# ------------------------------------------------------------------
# State persistence
# ------------------------------------------------------------------


class TestStatePersistence:
    """State survives PlistManager recreation."""

    def test_disabled_list_persisted(self, data_dir: Path):
        mgr = PlistManager(data_dir)
        mgr._execute_command = MagicMock(return_value=(0, "", ""))

        mgr.disable_service("email")

        # Create new instance — state should be loaded from disk
        mgr2 = PlistManager(data_dir)
        mgr2._execute_command = MagicMock(return_value=(0, "", ""))

        assert "email" in mgr2._state["disabled_services"]

    def test_cooldown_persisted(self, data_dir: Path):
        mgr = PlistManager(data_dir)
        mgr._execute_command = MagicMock(return_value=(0, "", ""))

        mgr.restart_service("email")

        # New instance should still enforce cooldown
        mgr2 = PlistManager(data_dir)
        mgr2._execute_command = MagicMock(return_value=(0, "", ""))

        result = mgr2.restart_service("email")
        assert result["success"] is False
        assert "cooldown" in result["message"].lower()

    def test_state_file_created_in_data_dir(self, data_dir: Path):
        mgr = PlistManager(data_dir)
        mgr._execute_command = MagicMock(return_value=(0, "", ""))
        mgr.restart_service("email")

        state_file = data_dir / "plist-management-state.json"
        assert state_file.exists()


# ------------------------------------------------------------------
# Restart service
# ------------------------------------------------------------------


class TestRestartService:
    """restart_service bootout + bootstrap flow."""

    def test_restart_calls_bootout_then_bootstrap(self, mgr: PlistManager):
        calls = []
        def track_cmd(cmd):
            calls.append(cmd)
            return (0, "", "")
        mgr._execute_command = track_cmd

        result = mgr.restart_service("email")
        assert result["success"] is True
        assert len(calls) == 2
        assert "bootout" in calls[0]
        assert "bootstrap" in calls[1]

    def test_restart_tolerates_not_loaded(self, mgr: PlistManager):
        """If service wasn't loaded, bootout failure is OK."""
        call_count = [0]
        def mock_cmd(cmd):
            call_count[0] += 1
            if "bootout" in cmd:
                return (1, "", "Could not find specified service")
            return (0, "", "")
        mgr._execute_command = mock_cmd

        result = mgr.restart_service("email")
        assert result["success"] is True


# ------------------------------------------------------------------
# Service status (read-only)
# ------------------------------------------------------------------


class TestGetServiceStatus:
    """get_service_status is read-only — no cooldown, works for protected."""

    def test_status_loaded(self, mgr: PlistManager):
        mgr._execute_command = MagicMock(return_value=(0, "service info...", ""))
        result = mgr.get_service_status("email")
        assert result["success"] is True
        assert result["loaded"] is True

    def test_status_not_loaded(self, mgr: PlistManager):
        mgr._execute_command = MagicMock(return_value=(1, "", "not found"))
        result = mgr.get_service_status("email")
        assert result["success"] is True
        assert result["loaded"] is False

    def test_status_unknown_service(self, mgr: PlistManager):
        result = mgr.get_service_status("fake")
        assert result["success"] is False

    def test_status_shows_disabled_by_manager(self, mgr: PlistManager):
        mgr._state["disabled_services"] = ["email"]
        result = mgr.get_service_status("email")
        assert result["disabled_by_manager"] is True


# ------------------------------------------------------------------
# Enable service
# ------------------------------------------------------------------


class TestEnableService:
    """enable_service removes from disabled list."""

    def test_enable_removes_from_disabled(self, mgr: PlistManager):
        mgr._state["disabled_services"] = ["email"]
        result = mgr.enable_service("email")
        assert result["success"] is True
        assert "email" not in mgr._state["disabled_services"]
