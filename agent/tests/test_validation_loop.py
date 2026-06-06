"""Tests for the pre-deploy validation integration in deploy-helper.py."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import deploy_helper  # noqa: E402


@pytest.fixture
def requests_dir(tmp_path):
    """Create a temporary deploy-requests directory."""
    d = tmp_path / "deploy-requests"
    d.mkdir()
    return d


@pytest.fixture
def messages_dir(tmp_path):
    """Create a temporary service_messages directory."""
    d = tmp_path / "service_messages"
    d.mkdir()
    return d


class TestPreDeployValidationIntegration:
    """Integration tests for pre-deploy test execution."""

    def test_py_deploy_runs_tests(self, tmp_path, requests_dir, messages_dir):
        """Deploying .py files should trigger test execution."""
        src = tmp_path / "module.py"
        src.write_text("print('hello')")

        manifest = {
            "id": "test-py-1",
            "description": "Deploy Python module",
            "files": [{
                "src": str(src),
                "dst": "/opt/bumba-harness/agent/config/claude-files/test.py",
                "owner": "bumba-agent:staff",
                "mode": "644",
            }],
            "status": "pending",
            "created_at": "2026-03-05T14:30:00Z",
        }

        path = requests_dir / "test-py-1.json"
        path.write_text(json.dumps(manifest))

        with patch.object(deploy_helper, "REQUESTS_DIR", requests_dir), \
             patch.object(deploy_helper, "MESSAGES_DIR", messages_dir), \
             patch.object(deploy_helper, "run_tests") as mock_tests, \
             patch.object(deploy_helper, "copy_files", return_value=(True, "")):
            mock_tests.return_value = (True, "all passed")
            deploy_helper.execute_deploy(path, manifest)

            assert mock_tests.call_count == 2  # pre-deploy + post-deploy
            updated = json.loads(path.read_text())
            assert updated["status"] == "completed"

    def test_py_deploy_blocked_on_test_failure(self, tmp_path, requests_dir, messages_dir):
        """Deploying .py files should block when tests fail."""
        src = tmp_path / "broken.py"
        src.write_text("raise Exception('broken')")

        manifest = {
            "id": "test-py-fail",
            "description": "Deploy broken Python module",
            "files": [{
                "src": str(src),
                "dst": "/opt/bumba-harness/agent/config/claude-files/broken.py",
                "owner": "bumba-agent:staff",
                "mode": "644",
            }],
            "status": "pending",
            "created_at": "2026-03-05T14:30:00Z",
        }

        path = requests_dir / "test-py-fail.json"
        path.write_text(json.dumps(manifest))

        with patch.object(deploy_helper, "REQUESTS_DIR", requests_dir), \
             patch.object(deploy_helper, "MESSAGES_DIR", messages_dir), \
             patch.object(deploy_helper, "run_tests") as mock_tests, \
             patch.object(deploy_helper, "copy_files") as mock_copy:
            mock_tests.return_value = (False, "FAILED: test_something\nAssertionError")
            deploy_helper.execute_deploy(path, manifest)

            mock_copy.assert_not_called()  # Files should NOT be copied
            updated = json.loads(path.read_text())
            assert updated["status"] == "failed"
            assert "Pre-deploy tests failed" in updated["error"]

    def test_md_deploy_skips_tests(self, tmp_path, requests_dir, messages_dir):
        """Deploying .md files should NOT trigger test execution."""
        src = tmp_path / "docs.md"
        src.write_text("# Documentation")

        manifest = {
            "id": "test-md-1",
            "description": "Deploy markdown docs",
            "files": [{
                "src": str(src),
                "dst": "/opt/bumba-harness/agent/config/claude-files/commands/test.md",
                "owner": "bumba-agent:staff",
                "mode": "644",
            }],
            "status": "pending",
            "created_at": "2026-03-05T14:30:00Z",
        }

        path = requests_dir / "test-md-1.json"
        path.write_text(json.dumps(manifest))

        with patch.object(deploy_helper, "REQUESTS_DIR", requests_dir), \
             patch.object(deploy_helper, "MESSAGES_DIR", messages_dir), \
             patch.object(deploy_helper, "run_tests") as mock_tests, \
             patch.object(deploy_helper, "copy_files", return_value=(True, "")):
            deploy_helper.execute_deploy(path, manifest)

            mock_tests.assert_not_called()  # Tests should NOT run for .md files
            updated = json.loads(path.read_text())
            assert updated["status"] == "completed"

    def test_mixed_deploy_runs_tests(self, tmp_path, requests_dir, messages_dir):
        """Deploy with both .py and .md files should trigger tests (due to .py)."""
        src_py = tmp_path / "module.py"
        src_py.write_text("pass")
        src_md = tmp_path / "docs.md"
        src_md.write_text("# docs")

        manifest = {
            "id": "test-mixed",
            "description": "Deploy mixed files",
            "files": [
                {"src": str(src_py), "dst": "/opt/bumba-harness/agent/config/claude-files/m.py", "owner": "bumba-agent:staff", "mode": "644"},
                {"src": str(src_md), "dst": "/opt/bumba-harness/agent/config/claude-files/d.md", "owner": "bumba-agent:staff", "mode": "644"},
            ],
            "status": "pending",
            "created_at": "2026-03-05T14:30:00Z",
        }

        path = requests_dir / "test-mixed.json"
        path.write_text(json.dumps(manifest))

        with patch.object(deploy_helper, "REQUESTS_DIR", requests_dir), \
             patch.object(deploy_helper, "MESSAGES_DIR", messages_dir), \
             patch.object(deploy_helper, "run_tests") as mock_tests, \
             patch.object(deploy_helper, "copy_files", return_value=(True, "")):
            mock_tests.return_value = (True, "passed")
            deploy_helper.execute_deploy(path, manifest)

            assert mock_tests.call_count == 2  # pre-deploy + post-deploy
