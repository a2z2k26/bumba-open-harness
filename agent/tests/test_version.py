"""Tests for bridge.version — version tracking and rollback flags."""

from __future__ import annotations

import json

import pytest

from bridge.version import (
    VersionInfo,
    check_rollback_flag,
    clear_rollback_flag,
    detect_version_change,
    get_current_version,
    get_running_version,
    init_version,
    set_rollback_flag,
    write_version,
)


@pytest.fixture
def data_dir(tmp_path):
    """Create a temp data directory."""
    d = tmp_path / "data"
    d.mkdir()
    return d


class TestVersionInfo:
    """Version reading and writing."""

    def test_default_version_info(self):
        info = VersionInfo()
        assert info.version == "0.0.0"
        assert info.git_commit == "unknown"

    def test_get_current_version_missing_file(self, data_dir):
        info = get_current_version(data_dir)
        assert info.version == "0.0.0"
        assert info.git_commit == "unknown"
        assert info.deployed_at == "unknown"
        assert info.deployed_by == "unknown"

    def test_get_current_version_reads_file(self, data_dir):
        (data_dir / "version.json").write_text(json.dumps({
            "version": "2.1.0",
            "git_commit": "abc1234",
            "deployed_at": "2026-03-13T15:30:00Z",
            "deployed_by": "deploy-helper",
        }))
        info = get_current_version(data_dir)
        assert info.version == "2.1.0"
        assert info.git_commit == "abc1234"
        assert info.deployed_by == "deploy-helper"

    def test_get_current_version_corrupt_json(self, data_dir):
        (data_dir / "version.json").write_text("not json")
        info = get_current_version(data_dir)
        assert info.version == "0.0.0"

    def test_write_version(self, data_dir):
        info = write_version(data_dir, "1.0.0", git_commit="def5678", deployed_by="test")
        assert info.version == "1.0.0"
        assert info.git_commit == "def5678"
        assert info.deployed_by == "test"
        assert info.deployed_at != "unknown"

        # Verify file on disk
        data = json.loads((data_dir / "version.json").read_text())
        assert data["version"] == "1.0.0"

    def test_write_then_read(self, data_dir):
        write_version(data_dir, "3.2.1", git_commit="xyz789")
        info = get_current_version(data_dir)
        assert info.version == "3.2.1"
        assert info.git_commit == "xyz789"

    def test_init_version_sets_running(self, data_dir):
        write_version(data_dir, "5.0.0")
        init_version(data_dir)
        assert get_running_version() == "5.0.0"

    def test_init_version_missing_file(self, data_dir):
        init_version(data_dir)
        assert get_running_version() == "0.0.0"

    def test_partial_version_json(self, data_dir):
        """File with only some fields still works."""
        (data_dir / "version.json").write_text(json.dumps({"version": "1.0.0"}))
        info = get_current_version(data_dir)
        assert info.version == "1.0.0"
        assert info.git_commit == "unknown"


class TestVersionChangeDetection:
    """Detecting version changes on startup."""

    def test_detects_version_change(self, data_dir):
        # Write version 1.0.0
        write_version(data_dir, "1.0.0")

        # State says last version was 0.5.0
        state_dir = data_dir / "service_state"
        state_dir.mkdir()
        (state_dir / "bridge-state.json").write_text(
            json.dumps({"last_version": "0.5.0"})
        )

        result = detect_version_change(data_dir)
        assert result == ("0.5.0", "1.0.0")

    def test_no_change_same_version(self, data_dir):
        write_version(data_dir, "1.0.0")
        state_dir = data_dir / "service_state"
        state_dir.mkdir()
        (state_dir / "bridge-state.json").write_text(
            json.dumps({"last_version": "1.0.0"})
        )

        result = detect_version_change(data_dir)
        assert result is None

    def test_first_run_no_state(self, data_dir):
        write_version(data_dir, "1.0.0")
        result = detect_version_change(data_dir)
        assert result == ("0.0.0", "1.0.0")

    def test_updates_state_after_detection(self, data_dir):
        write_version(data_dir, "2.0.0")
        detect_version_change(data_dir)

        state_dir = data_dir / "service_state"
        state = json.loads((state_dir / "bridge-state.json").read_text())
        assert state["last_version"] == "2.0.0"
        assert "last_version_change" in state

    def test_no_version_file_vs_no_state(self, data_dir):
        """Both missing — 0.0.0 == 0.0.0, no change."""
        result = detect_version_change(data_dir)
        assert result is None


class TestRollbackFlag:
    """Rollback flag operations."""

    def test_no_flag_returns_none(self, data_dir):
        assert check_rollback_flag(data_dir) is None

    def test_set_and_check_flag(self, data_dir):
        set_rollback_flag(data_dir, "broken deploy")
        flag = check_rollback_flag(data_dir)
        assert flag is not None
        assert flag["reason"] == "broken deploy"
        assert "requested_at" in flag

    def test_clear_flag(self, data_dir):
        set_rollback_flag(data_dir, "bad deploy")
        assert check_rollback_flag(data_dir) is not None
        clear_rollback_flag(data_dir)
        assert check_rollback_flag(data_dir) is None

    def test_clear_nonexistent_flag(self, data_dir):
        """No error when clearing a flag that doesn't exist."""
        clear_rollback_flag(data_dir)

    def test_corrupt_flag_file(self, data_dir):
        (data_dir / "rollback.flag").write_text("not json")
        flag = check_rollback_flag(data_dir)
        assert flag is not None
        assert flag["reason"] == "unknown"
