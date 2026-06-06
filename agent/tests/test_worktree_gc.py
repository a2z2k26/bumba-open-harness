"""Tests for worktree GC service (#572 sub-bet 3)."""
from __future__ import annotations

import os
import tempfile
import time

from unittest.mock import MagicMock, patch

_TMPDIR = tempfile.gettempdir()

from bridge.services.worktree_gc import run_worktree_gc, _is_safe_to_prune


# ---------------------------------------------------------------------------
# Unit tests for _is_safe_to_prune
# ---------------------------------------------------------------------------

def test_safe_prefix_private_tmp():
    assert _is_safe_to_prune("/private/tmp/bumba-abc") is True


def test_safe_prefix_tmpdir():
    assert _is_safe_to_prune(_TMPDIR.rstrip("/") + "/bumba-abc") is True


def test_safe_prefix_tmp():
    assert _is_safe_to_prune("/tmp/bumba-xyz") is True


def test_unsafe_prefix_home():
    assert _is_safe_to_prune("/opt/bumba-harness/agent") is False


def test_unsafe_prefix_documents():
    assert _is_safe_to_prune("/home/operator/bumba-open-harness/agent") is False


# ---------------------------------------------------------------------------
# Basic functionality
# ---------------------------------------------------------------------------

def test_run_worktree_gc_returns_dict():
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        result = run_worktree_gc("/fake/repo")
    assert isinstance(result, dict)
    assert "pruned" in result
    assert "skipped" in result
    assert "errors" in result


def test_empty_worktree_list():
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        result = run_worktree_gc("/fake/repo")
    assert result["pruned"] == []
    assert result["skipped"] == []
    assert result["errors"] == []


def test_git_list_failure_returns_empty():
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="fatal: not a git repo")
        result = run_worktree_gc("/fake/repo")
    assert result == {"pruned": [], "skipped": [], "errors": []}


# ---------------------------------------------------------------------------
# Prune logic with /private/tmp paths
# ---------------------------------------------------------------------------

def test_prunes_old_tmp_worktrees():
    """Worktrees in /private/tmp that are old should be pruned."""
    # Create a real directory in /private/tmp with old mtime
    with tempfile.TemporaryDirectory(prefix="bumba-wt-test-old-", dir=_TMPDIR) as old_wt:
        old_time = time.time() - (2 * 86400)
        os.utime(old_wt, (old_time, old_time))

        with tempfile.TemporaryDirectory(prefix="bumba-wt-test-new-", dir=_TMPDIR) as new_wt:
            porcelain = (
                "worktree /opt/bumba-harness/agent\n"
                "HEAD 999999\n"
                "branch refs/heads/main\n\n"
                f"worktree {old_wt}\n"
                "HEAD abc123\n"
                "branch refs/heads/feat/old\n\n"
                f"worktree {new_wt}\n"
                "HEAD def456\n"
                "branch refs/heads/feat/new\n\n"
            )

            def _side_effect(cmd, **kwargs):
                m = MagicMock()
                if "list" in cmd:
                    m.returncode = 0
                    m.stdout = porcelain
                    m.stderr = ""
                else:
                    m.returncode = 0
                    m.stdout = ""
                    m.stderr = ""
                return m

            with patch("subprocess.run", side_effect=_side_effect):
                result = run_worktree_gc("/fake/repo", age_threshold_s=86400)

    assert old_wt in result["pruned"]
    skipped_paths = [s["path"] if isinstance(s, dict) else s for s in result["skipped"]]
    assert new_wt in skipped_paths


def test_skips_non_tmp_worktrees():
    """Worktrees NOT in /private/tmp or /tmp must never be pruned."""
    porcelain = (
        "worktree /opt/bumba-harness/agent\n"
        "HEAD 111111\n"
        "branch refs/heads/main\n\n"
        "worktree /home/operator/bumba-open-harness/agent\n"
        "HEAD 222222\n"
        "branch refs/heads/develop\n\n"
    )

    def _side_effect(cmd, **kwargs):
        m = MagicMock()
        if "list" in cmd:
            m.returncode = 0
            m.stdout = porcelain
            m.stderr = ""
        else:
            m.returncode = 0
            m.stdout = ""
            m.stderr = ""
        return m

    with patch("subprocess.run", side_effect=_side_effect) as mock_run:
        result = run_worktree_gc("/fake/repo", age_threshold_s=0)

    # remove should never have been called for non-/tmp paths
    for c in mock_run.call_args_list:
        args = c.args[0] if c.args else []
        assert "remove" not in args, "Must not prune non-/tmp worktrees"
    assert len(result["pruned"]) == 0


def test_git_remove_failure_captured_in_errors():
    with tempfile.TemporaryDirectory(prefix="bumba-wt-stale-", dir=_TMPDIR) as old_wt:
        old_time = time.time() - (2 * 86400)
        os.utime(old_wt, (old_time, old_time))

        porcelain = (
            "worktree /opt/bumba-harness/agent\n"
            "HEAD main123\n"
            "branch refs/heads/main\n\n"
            f"worktree {old_wt}\n"
            "HEAD abc123\n"
            "branch refs/heads/feat/stale\n\n"
        )

        def _side_effect(cmd, **kwargs):
            m = MagicMock()
            if "list" in cmd:
                m.returncode = 0
                m.stdout = porcelain
                m.stderr = ""
            else:
                # git worktree remove fails
                m.returncode = 1
                m.stdout = ""
                m.stderr = "error: cannot remove"
            return m

        with patch("subprocess.run", side_effect=_side_effect):
            result = run_worktree_gc("/fake/repo", age_threshold_s=3600)

    # Should be captured in errors, not pruned
    error_strs = [str(e) for e in result["errors"]]
    assert any(old_wt in e for e in error_strs)
    assert old_wt not in result["pruned"]


def test_age_threshold_respected():
    """Only prune worktrees older than age_threshold_s."""
    with tempfile.TemporaryDirectory(prefix="bumba-wt-recent-", dir=_TMPDIR) as slightly_old:
        # 30 minutes old
        old_time = time.time() - 1800
        os.utime(slightly_old, (old_time, old_time))

        porcelain = (
            "worktree /opt/bumba-harness/agent\n"
            "HEAD main123\n"
            "branch refs/heads/main\n\n"
            f"worktree {slightly_old}\n"
            "HEAD abc123\n"
            "branch refs/heads/feat/x\n\n"
        )

        def _side_effect(cmd, **kwargs):
            m = MagicMock()
            if "list" in cmd:
                m.returncode = 0
                m.stdout = porcelain
                m.stderr = ""
            else:
                m.returncode = 0
                m.stdout = ""
                m.stderr = ""
            return m

        with patch("subprocess.run", side_effect=_side_effect):
            # Threshold = 2 hours → 30min old should NOT be pruned
            result = run_worktree_gc("/fake/repo", age_threshold_s=7200)

    skipped_paths = [s["path"] if isinstance(s, dict) else s for s in result["skipped"]]
    assert slightly_old in skipped_paths
    assert slightly_old not in result["pruned"]


def test_detached_head_worktree_handled():
    """Worktrees with detached HEAD (no branch) should still be evaluated."""
    with tempfile.TemporaryDirectory(prefix="bumba-wt-detached-", dir=_TMPDIR) as old_wt:
        old_time = time.time() - (2 * 86400)
        os.utime(old_wt, (old_time, old_time))

        porcelain = (
            "worktree /opt/bumba-harness/agent\n"
            "HEAD main123\n"
            "branch refs/heads/main\n\n"
            f"worktree {old_wt}\n"
            "HEAD abc123\n"
            "detached\n\n"
        )

        def _side_effect(cmd, **kwargs):
            m = MagicMock()
            if "list" in cmd:
                m.returncode = 0
                m.stdout = porcelain
                m.stderr = ""
            else:
                m.returncode = 0
                m.stdout = ""
                m.stderr = ""
            return m

        with patch("subprocess.run", side_effect=_side_effect):
            result = run_worktree_gc("/fake/repo", age_threshold_s=86400)

    # Should attempt to prune detached head worktrees in /tmp
    assert old_wt in result["pruned"]


def test_pruned_count_matches():
    """All pruned entries should count correctly."""
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        result = run_worktree_gc("/fake/repo")
    total = len(result["pruned"]) + len(result["skipped"]) + len(result["errors"])
    # With empty list, total = 0
    assert total == 0
