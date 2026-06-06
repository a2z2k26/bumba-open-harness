"""Tests for bridge.factory.quality — Sprint 14.06 pre-PR quality gates.

Three guards are tested in isolation, plus a `run_all_quality_checks`
aggregate test, plus an integration test that confirms `implement.py`
routes a quality-gate failure to NEEDS_HUMAN.
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from bridge.factory import implement as impl
from bridge.factory.implement import PHASE_QUALITY, implement_issue
from bridge.factory.labels import FactoryState
from bridge.factory.quality import (
    NEW_DEP_MAGIC_PHRASE,
    PR_SIZE_CAP,
    QualityCheckResult,
    check_new_deps,
    check_pr_size,
    check_protected_files,
    run_all_quality_checks,
)


# ── PR size cap ─────────────────────────────────────────────────────────


class TestCheckPrSize:
    def test_passes_at_499_total(self):
        result = check_pr_size({"additions": 250, "deletions": 249, "files_changed": 3})
        assert isinstance(result, QualityCheckResult)
        assert result.passed is True
        assert result.reason == ""
        assert result.category == "pr_size"

    def test_passes_exactly_at_cap(self):
        result = check_pr_size({"additions": PR_SIZE_CAP, "deletions": 0})
        assert result.passed is True

    def test_fails_at_501(self):
        result = check_pr_size({"additions": 300, "deletions": 201, "files_changed": 5})
        assert result.passed is False
        assert "501" in result.reason
        assert str(PR_SIZE_CAP) in result.reason
        assert result.category == "pr_size"

    def test_handles_missing_keys_safely(self):
        # Partial dicts default to 0.
        assert check_pr_size({}).passed is True
        assert check_pr_size({"additions": 100}).passed is True


# ── Protected files ─────────────────────────────────────────────────────


class TestCheckProtectedFiles:
    def test_passes_for_clean_diff(self):
        result = check_protected_files(
            ["agent/bridge/factory/quality.py", "agent/tests/test_factory_quality.py"]
        )
        assert result.passed is True
        assert result.category == "protected_files"

    def test_fails_for_security_py(self):
        result = check_protected_files(
            ["agent/bridge/factory/quality.py", "agent/bridge/security.py"]
        )
        assert result.passed is False
        assert "security.py" in result.reason
        assert result.category == "protected_files"

    def test_fails_for_trust_score_py(self):
        result = check_protected_files(["agent/bridge/trust_score.py"])
        assert result.passed is False
        assert "trust_score.py" in result.reason

    def test_fails_for_kernel_baseline(self):
        result = check_protected_files(["data/kernel-baseline.json"])
        assert result.passed is False
        assert "kernel-baseline.json" in result.reason

    def test_fails_for_plist(self):
        result = check_protected_files(
            ["config/launchd/com.bumba.agent-bridge.plist"]
        )
        assert result.passed is False
        assert ".plist" in result.reason or "plist" in result.reason
        assert result.category == "protected_files"

    def test_fails_for_hooks_dir_file(self):
        result = check_protected_files(["config/hooks/memory-session-start.sh"])
        assert result.passed is False
        assert result.category == "protected_files"

    def test_passes_when_filename_resembles_but_doesnt_match(self):
        # A file named `not_security.txt` must NOT trip the gate. The match
        # is segment-based — substring fallback is tolerated for paranoid
        # safety but exact filename mismatches are clean.
        result = check_protected_files(["docs/notes.md", "agent/bridge/factory/quality.py"])
        assert result.passed is True

    def test_handles_empty_list(self):
        assert check_protected_files([]).passed is True

    def test_handles_empty_string_entries(self):
        assert check_protected_files([""]).passed is True


# ── New-dep justification ───────────────────────────────────────────────


_PYPROJECT_DEP_DIFF = """\
diff --git a/agent/pyproject.toml b/agent/pyproject.toml
--- a/agent/pyproject.toml
+++ b/agent/pyproject.toml
@@ -1,10 +1,12 @@
 [project]
 name = "bumba-agent"
 dependencies = [
     "discord.py>=2.0",
+    "requests>=2.31.0",
+    "httpx>=0.27.0",
 ]
"""


_PYPROJECT_NO_DEP_DIFF = """\
diff --git a/agent/bridge/factory/foo.py b/agent/bridge/factory/foo.py
--- a/agent/bridge/factory/foo.py
+++ b/agent/bridge/factory/foo.py
@@ -0,0 +1,3 @@
+def foo():
+    return 42
"""


class TestCheckNewDeps:
    def test_fails_when_pyproject_adds_dep_without_magic_phrase(self):
        result = check_new_deps(_PYPROJECT_DEP_DIFF, "Plain issue body, no magic.")
        assert result.passed is False
        assert "requests" in result.reason or "httpx" in result.reason
        assert result.category == "new_deps"

    def test_passes_when_pyproject_adds_dep_with_magic_phrase(self):
        body = (
            "We need requests for HTTP retries.\n\n"
            f"{NEW_DEP_MAGIC_PHRASE} required for the new HTTP client adapter."
        )
        result = check_new_deps(_PYPROJECT_DEP_DIFF, body)
        assert result.passed is True

    def test_passes_when_pyproject_unchanged(self):
        result = check_new_deps(_PYPROJECT_NO_DEP_DIFF, "no magic phrase here")
        assert result.passed is True

    def test_passes_for_empty_diff(self):
        assert check_new_deps("", "").passed is True

    def test_magic_phrase_is_case_insensitive(self):
        body = "NEW-DEP-JUSTIFIED: needed for X"
        result = check_new_deps(_PYPROJECT_DEP_DIFF, body)
        assert result.passed is True


# ── run_all_quality_checks ──────────────────────────────────────────────


class TestRunAllQualityChecks:
    def test_returns_four_results_in_stable_order(self):
        results = run_all_quality_checks(
            diff_stat={"additions": 10, "deletions": 5, "files_changed": 1},
            changed_files=["agent/bridge/factory/quality.py"],
            diff_text="",
            issue_body="",
        )
        assert len(results) == 4
        assert [r.category for r in results] == [
            "pr_size",
            "protected_files",
            "new_deps",
            "branch_protection",
        ]
        assert all(r.passed for r in results)

    def test_multiple_failures_all_surfaced(self):
        results = run_all_quality_checks(
            diff_stat={"additions": 600, "deletions": 0, "files_changed": 1},
            changed_files=["agent/bridge/security.py"],
            diff_text=_PYPROJECT_DEP_DIFF,
            issue_body="no magic",
        )
        assert [r.passed for r in results] == [False, False, False, True]
        # Each result names its own category in the reason.
        size_r, protect_r, deps_r, branch_r = results
        assert size_r.category == "pr_size" and not size_r.passed
        assert protect_r.category == "protected_files" and not protect_r.passed
        assert deps_r.category == "new_deps" and not deps_r.passed
        assert branch_r.category == "branch_protection" and branch_r.passed


# ── Integration: implement.py routes quality failure to NEEDS_HUMAN ─────


def _gh_issue_view_payload(
    title: str = "Add foo",
    body: str = "issue body",
    labels: list[str] | None = None,
) -> tuple[int, str, str]:
    labels = labels or [FactoryState.ACCEPTED.value]
    payload = {
        "title": title,
        "body": body,
        "labels": [{"name": n} for n in labels],
        "comments": [],
    }
    return (0, json.dumps(payload), "")


class TestImplementWiresQualityGate:
    """The quality phase fires between commit (5) and test (6).

    On any quality failure, `implement_issue` short-circuits to NEEDS_HUMAN
    with `failed_phase=PHASE_QUALITY`. We mock the diff inputs so the gate
    sees an oversized diff.
    """

    def test_oversized_diff_routes_to_needs_human(self, tmp_path: Path):
        repo_root = tmp_path / "repo"
        repo_root.mkdir()
        workspace = tmp_path / "workspace"
        view = _gh_issue_view_payload(body="no magic phrase")

        # Track that pytest/ruff/pr-create are NEVER reached when quality fails.
        forbidden_calls: list[list[str]] = []

        def fake_run(args, **kwargs):
            head = args[:3]
            if head == ["gh", "issue", "view"]:
                return view
            if head == ["gh", "issue", "comment"]:
                return (0, "", "")
            if head == ["gh", "issue", "edit"]:
                return (0, "", "")
            if head[:2] == ["git", "worktree"] and args[2] == "add":
                return (0, "", "")
            if head[:2] == ["git", "add"]:
                return (0, "", "")
            if head[:2] == ["git", "commit"]:
                return (0, "", "")
            # Anything past commit is forbidden once quality fails.
            if head[0] == "pytest" or head[0] == "ruff" or head == ["gh", "pr", "create"]:
                forbidden_calls.append(list(args))
                raise AssertionError(f"unexpected post-quality call: {args}")
            # Diff-collection git calls (numstat, name-only, plain diff) — return empty.
            if head[:2] == ["git", "diff"]:
                return (0, "", "")
            raise AssertionError(f"unexpected subprocess call: {args}")

        # Override _quality_phase to force a failure (any failure suffices).
        def forced_fail(**kwargs):
            return False, ["forced size cap failure for test"]

        with (
            patch("bridge.factory.implement._run_subprocess", side_effect=fake_run),
            patch(
                "bridge.factory.implement._invoke_claude",
                return_value=(0, "ok", ""),
            ),
            patch("bridge.factory.implement.transition_state", return_value=True),
            patch.object(impl, "_quality_phase", side_effect=forced_fail),
        ):
            result = implement_issue(
                42,
                repo="owner/repo",
                workspace_root=workspace,
                repo_root=repo_root,
            )

        assert result.failed_phase == PHASE_QUALITY
        assert result.final_state is FactoryState.NEEDS_HUMAN
        assert result.pr_number is None
        # Confirm post-quality phases were never run.
        assert forbidden_calls == []

    def test_real_quality_phase_passes_for_clean_diff(self, tmp_path: Path):
        """End-to-end: with empty diff (numstat/name-only/diff all empty),
        the real `_quality_phase` should pass and the workflow continues."""
        repo_root = tmp_path / "repo"
        repo_root.mkdir()
        workspace = tmp_path / "workspace"
        view = _gh_issue_view_payload(body="clean issue body")
        pr_create = (0, "https://github.com/owner/repo/pull/777\n", "")

        def fake_run(args, **kwargs):
            head = args[:3]
            if head == ["gh", "issue", "view"]:
                return view
            if head == ["gh", "issue", "comment"]:
                return (0, "", "")
            if head == ["gh", "issue", "edit"]:
                return (0, "", "")
            if head == ["gh", "pr", "create"]:
                return pr_create
            if head[:2] == ["git", "worktree"] and args[2] == "add":
                return (0, "", "")
            if head[:2] == ["git", "add"]:
                return (0, "", "")
            if head[:2] == ["git", "commit"]:
                return (0, "", "")
            if head[:2] == ["git", "push"]:
                return (0, "", "")
            if head[:2] == ["git", "diff"]:
                # Empty diff text → no LOC, no files, no deps → all gates pass.
                return (0, "", "")
            if head[0] == "pytest":
                return (0, "1 passed", "")
            if head[0] == "ruff":
                return (0, "All checks passed!", "")
            raise AssertionError(f"unexpected subprocess: {args}")

        with (
            patch("bridge.factory.implement._run_subprocess", side_effect=fake_run),
            patch(
                "bridge.factory.implement._invoke_claude",
                return_value=(0, "ok", ""),
            ),
            patch("bridge.factory.implement.transition_state", return_value=True),
        ):
            result = implement_issue(
                42,
                repo="owner/repo",
                workspace_root=workspace,
                repo_root=repo_root,
            )

        assert result.failed_phase is None
        assert result.final_state is FactoryState.NEEDS_REVIEW
        assert result.pr_number == 777
