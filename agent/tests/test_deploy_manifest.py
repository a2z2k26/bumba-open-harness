"""Tests for bridge.deploy_manifest — tier classification, manifest CRUD, rollback."""

from __future__ import annotations

import json

import pytest

from bridge.deploy_manifest import (
    append_history,
    classify_manifest_tier,
    classify_tier,
    create_backup_manifest,
    create_manifest,
    purge_old_backups,
    read_history,
    read_manifest,
    restore_from_backup,
    update_manifest_status,
    validate_manifest,
    write_manifest,
)


# ── Tier Classification ──

class TestTierClassification:
    """File-path-based tier classification."""

    def test_kernel_security_py(self):
        assert classify_tier("bridge/security.py") == "C"

    def test_kernel_system_prompt(self):
        assert classify_tier("config/system-prompt.md") == "C"

    def test_kernel_hooks(self):
        assert classify_tier("config/hooks/memory-session-start.sh") == "C"

    def test_kernel_bootstrap(self):
        assert classify_tier("config/bootstrap/SOUL.md") == "C"

    def test_kernel_plist(self):
        assert classify_tier("com.bumba.agent-bridge.plist") == "C"

    def test_kernel_secrets(self):
        assert classify_tier(".secrets") == "C"

    def test_kernel_mcp_json(self):
        assert classify_tier(".mcp.json") == "C"

    def test_kernel_deploy_helper(self):
        assert classify_tier("scripts/deploy_helper.py") == "C"

    def test_bridge_py(self):
        assert classify_tier("bridge/app.py") == "B+"

    def test_bridge_services_py(self):
        assert classify_tier("bridge/services/email.py") == "B+"

    def test_job_search_py(self):
        assert classify_tier("job_search/pipeline.py") == "B+"

    def test_config_toml(self):
        assert classify_tier("config/bridge.toml") == "B"

    def test_config_yaml(self):
        assert classify_tier("config/zone2/rhythm-schema.yaml") == "B"

    def test_test_files(self):
        assert classify_tier("tests/test_app.py") == "A"

    def test_docs(self):
        assert classify_tier("docs/architecture.md") == "A"

    def test_templates(self):
        assert classify_tier("templates/project-template.yaml") == "A"

    def test_unknown_defaults_to_b(self):
        assert classify_tier("random/file.xyz") == "B"

    def test_manifest_tier_highest_wins(self):
        files = [
            {"source": "tests/test_foo.py"},  # A
            {"source": "bridge/app.py"},       # B+
        ]
        assert classify_manifest_tier(files) == "B+"

    def test_manifest_tier_kernel_wins(self):
        files = [
            {"source": "bridge/app.py"},       # B+
            {"source": "bridge/security.py"},  # C
        ]
        assert classify_manifest_tier(files) == "C"

    def test_manifest_tier_all_auto(self):
        files = [
            {"source": "tests/test_a.py"},
            {"source": "docs/readme.md"},
        ]
        assert classify_manifest_tier(files) == "A"


# ── Manifest CRUD ──

class TestManifestCRUD:
    def test_create_manifest(self):
        files = [{"source": "bridge/app.py", "target": "/deploy/bridge/app.py"}]
        m = create_manifest(files, reason="Fix bug", requested_by="agent")
        assert m["id"]
        assert m["tier"] == "B+"
        assert m["test_required"] is True
        assert m["status"] == "pending"
        assert m["reason"] == "Fix bug"

    def test_create_manifest_auto_tier(self):
        files = [{"source": "tests/test_foo.py"}]
        m = create_manifest(files, reason="Add test")
        assert m["tier"] == "A"
        assert m["test_required"] is False

    def test_validate_valid_manifest(self):
        m = create_manifest(
            [{"source": "bridge/app.py"}],
            reason="test",
        )
        assert validate_manifest(m) == []

    def test_validate_missing_id(self):
        errors = validate_manifest({"files": [{"source": "x"}], "tier": "A", "status": "pending", "reason": "x"})
        assert any("id" in e for e in errors)

    def test_validate_missing_files(self):
        errors = validate_manifest({"id": "x", "tier": "A", "status": "pending", "reason": "x"})
        assert any("files" in e for e in errors)

    def test_validate_empty_files(self):
        errors = validate_manifest({"id": "x", "files": [], "tier": "A", "status": "pending", "reason": "x"})
        assert any("files" in e for e in errors)

    def test_validate_invalid_tier(self):
        errors = validate_manifest({"id": "x", "files": [{"source": "x"}], "tier": "X", "status": "pending", "reason": "x"})
        assert any("tier" in e for e in errors)

    def test_validate_invalid_status(self):
        errors = validate_manifest({"id": "x", "files": [{"source": "x"}], "tier": "A", "status": "X", "reason": "x"})
        assert any("status" in e for e in errors)

    def test_validate_missing_reason(self):
        errors = validate_manifest({"id": "x", "files": [{"source": "x"}], "tier": "A", "status": "pending"})
        assert any("reason" in e for e in errors)

    def test_write_and_read(self, tmp_path):
        m = create_manifest([{"source": "bridge/app.py"}], reason="test")
        path = write_manifest(m, tmp_path / "requests")
        loaded = read_manifest(path)
        assert loaded["id"] == m["id"]
        assert loaded["reason"] == "test"

    def test_update_status(self, tmp_path):
        m = create_manifest([{"source": "x"}], reason="test")
        path = write_manifest(m, tmp_path / "requests")
        updated = update_manifest_status(path, "testing")
        assert updated["status"] == "testing"
        assert "testing_at" in updated

    def test_update_status_with_extra(self, tmp_path):
        m = create_manifest([{"source": "x"}], reason="test")
        path = write_manifest(m, tmp_path / "requests")
        updated = update_manifest_status(path, "failed", extra={"error": "tests failed"})
        assert updated["error"] == "tests failed"


# ── Deploy History ──

class TestDeployHistory:
    def test_append_and_read(self, tmp_path):
        history_file = tmp_path / "history.jsonl"
        m = create_manifest([{"source": "bridge/app.py"}], reason="test")
        append_history(history_file, m, {"test_result": "passed", "duration_ms": 500})
        records = read_history(history_file)
        assert len(records) == 1
        assert records[0]["deploy_id"] == m["id"]
        assert records[0]["test_result"] == "passed"

    def test_read_empty(self, tmp_path):
        assert read_history(tmp_path / "nonexistent.jsonl") == []

    def test_limit(self, tmp_path):
        history_file = tmp_path / "history.jsonl"
        for i in range(10):
            m = create_manifest([{"source": f"f{i}.py"}], reason=f"r{i}")
            append_history(history_file, m)
        records = read_history(history_file, limit=5)
        assert len(records) == 5


# ── Backup & Rollback ──

class TestBackupRollback:
    def test_create_backup(self, tmp_path):
        # Create a fake deployed file
        target_dir = tmp_path / "deploy"
        target_dir.mkdir()
        target_file = target_dir / "app.py"
        target_file.write_text("print('hello')")

        backup_dir = tmp_path / "backups"
        files = [{"target": str(target_file)}]
        backup = create_backup_manifest("deploy-001", files, backup_dir)

        assert backup["deploy_id"] == "deploy-001"
        assert len(backup["files"]) == 1
        assert backup["files"][0]["sha256"]

    def test_restore_from_backup(self, tmp_path):
        # Create file and backup
        target_dir = tmp_path / "deploy"
        target_dir.mkdir()
        target_file = target_dir / "app.py"
        original_content = "print('original')"
        target_file.write_text(original_content)

        backup_dir = tmp_path / "backups"
        files = [{"target": str(target_file)}]
        create_backup_manifest("deploy-002", files, backup_dir)

        # Overwrite the file (simulating deploy)
        target_file.write_text("print('broken')")
        assert target_file.read_text() == "print('broken')"

        # Restore
        restored = restore_from_backup(backup_dir, "deploy-002")
        assert len(restored) == 1
        assert target_file.read_text() == original_content

    def test_restore_nonexistent_backup(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            restore_from_backup(tmp_path / "backups", "nonexistent")

    def test_purge_old_backups(self, tmp_path):
        backup_dir = tmp_path / "backups"

        # Create an old backup
        old_dir = backup_dir / "old-deploy"
        old_dir.mkdir(parents=True)
        old_manifest = {
            "deploy_id": "old-deploy",
            "created_at": "2020-01-01T00:00:00+00:00",
            "files": [],
        }
        (old_dir / "backup-manifest.json").write_text(json.dumps(old_manifest))

        # Create a recent backup
        new_dir = backup_dir / "new-deploy"
        new_dir.mkdir(parents=True)
        from datetime import datetime, timezone
        new_manifest = {
            "deploy_id": "new-deploy",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "files": [],
        }
        (new_dir / "backup-manifest.json").write_text(json.dumps(new_manifest))

        removed = purge_old_backups(backup_dir, max_age_days=7)
        assert removed == 1
        assert not old_dir.exists()
        assert new_dir.exists()

    def test_backup_nonexistent_file(self, tmp_path):
        """Backup skips files that don't exist on disk."""
        backup_dir = tmp_path / "backups"
        files = [{"target": str(tmp_path / "nonexistent.py")}]
        backup = create_backup_manifest("deploy-003", files, backup_dir)
        assert len(backup["files"]) == 0

    def test_purge_empty_dir(self, tmp_path):
        assert purge_old_backups(tmp_path / "nonexistent") == 0
