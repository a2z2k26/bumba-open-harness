"""Tests for bridge.factory.implement — Dark Factory implement workflow.

Sprint 14.05 — Plan 14 Phase 3.

All `gh`, `git`, `pytest`, `ruff`, and `claude` subprocess calls are mocked.
These tests must NEVER touch a live GitHub repo, run a real Claude
subprocess, or shell out to git on the host filesystem.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from bridge.factory import implement as impl
from bridge.factory.implement import (
    COST_CAP_USD,
    PHASE_COST_CAP,
    PHASE_DRAFT_PR,
    PHASE_LINT,
    PHASE_TEST,
    ImplementResult,
    _branch_name,
    _slugify,
    implement_issue,
    implement_workflow,
)
from bridge.factory.labels import FactoryState


# ── gh stub helpers ─────────────────────────────────────────────────────


def _gh_issue_view_payload(
    title: str = "Add foo",
    body: str = "We should add foo because bar.",
    labels: list[str] | None = None,
) -> tuple[int, str, str]:
    """Build a fake (rc, stdout, stderr) for `gh issue view --json …`."""
    labels = labels or [FactoryState.ACCEPTED.value]
    payload = {
        "title": title,
        "body": body,
        "labels": [{"name": n} for n in labels],
        "comments": [],
    }
    return (0, json.dumps(payload), "")


def _gh_issue_list_payload(numbers: list[int]) -> tuple[int, str, str]:
    """Build a fake (rc, stdout, stderr) for `gh issue list --json number`."""
    return (0, json.dumps([{"number": n} for n in numbers]), "")


def _gh_pr_create_stdout(pr_number: int = 4242) -> tuple[int, str, str]:
    """Build a fake (rc, stdout, stderr) for `gh pr create --draft`."""
    url = f"https://github.com/owner/repo/pull/{pr_number}"
    return (0, url + "\n", "")


# ── _slugify / _branch_name ─────────────────────────────────────────────


class TestSlugAndBranchName:
    def test_slugify_lowercases_and_hyphenates(self):
        assert _slugify("Add foo bar") == "add-foo-bar"

    def test_slugify_strips_specials(self):
        assert _slugify("Fix: bug! (#42)") == "fix-bug-42"

    def test_slugify_truncates_long_titles(self):
        long = "x" * 100
        assert len(_slugify(long, max_len=40)) <= 40

    def test_slugify_empty_falls_back(self):
        assert _slugify("") == "issue"
        assert _slugify("!!!") == "issue"

    def test_branch_name_format(self):
        assert _branch_name(7, "Add foo") == "factory/7-add-foo"


# ── implement_issue happy path ──────────────────────────────────────────


class TestImplementIssueHappyPath:
    """All 10 phases succeed → ImplementResult with pr_number set."""

    def test_happy_path_returns_pr_number_and_needs_review_state(self, tmp_path: Path):
        repo_root = tmp_path / "repo"
        repo_root.mkdir()
        workspace = tmp_path / "workspace"

        view = _gh_issue_view_payload(title="Add foo", body="Body.")
        pr_create = _gh_pr_create_stdout(pr_number=4242)
        comment_resp = (0, "", "")

        # Sequence the subprocess calls expected during a full happy-path run.
        # We use a side-effect dispatcher that returns based on argv signature
        # rather than positional ordering — the order varies because some
        # phases share helpers and refactors must not break the test.
        def fake_run(args, **kwargs):
            head = args[:3]
            if head == ["gh", "issue", "view"]:
                return view
            if head == ["gh", "pr", "create"]:
                return pr_create
            if head == ["gh", "issue", "comment"]:
                return comment_resp
            if head[:2] == ["git", "worktree"] and args[2] == "add":
                return (0, "", "")
            if head[:2] == ["git", "add"]:
                return (0, "", "")
            if head[:2] == ["git", "commit"]:
                return (0, "", "")
            if head[:2] == ["git", "push"]:
                return (0, "", "")
            # Sprint 14.06: quality gate inspects the diff via 3 `git diff` calls.
            if head[:2] == ["git", "diff"]:
                return (0, "", "")
            if head[0] == "pytest":
                return (0, "1 passed", "")
            if head[0] == "ruff":
                return (0, "All checks passed!", "")
            raise AssertionError(f"unexpected subprocess call: {args}")

        # Mock the Claude subprocess (plan + implement phases) to return cleanly.
        def fake_claude(prompt, *, cwd=None, timeout=180):
            if "planner stage" in prompt:
                return (0, "1. Inspect file. 2. Add foo.", "")
            return (0, "Added foo.", "")

        with (
            patch("bridge.factory.implement._run_subprocess", side_effect=fake_run),
            patch("bridge.factory.implement._invoke_claude", side_effect=fake_claude),
            patch(
                "bridge.factory.implement.transition_state",
                return_value=True,
            ) as mock_tx,
        ):
            result = implement_issue(
                42,
                repo="owner/repo",
                workspace_root=workspace,
                repo_root=repo_root,
            )

        assert isinstance(result, ImplementResult)
        assert result.issue_number == 42
        assert result.pr_number == 4242
        assert result.pr_url == "https://github.com/owner/repo/pull/4242"
        assert result.failed_phase is None
        assert result.final_state is FactoryState.NEEDS_REVIEW
        # Two state transitions expected: ACCEPTED→IN_PROGRESS and IN_PROGRESS→NEEDS_REVIEW
        assert mock_tx.call_count == 2


# ── Failure routing ─────────────────────────────────────────────────────


class TestImplementFailureRouting:
    """Phase failures route to the right state and surface failed_phase."""

    def _baseline_run(self, view, pr_create=None, pytest_rc=0, ruff_rc=0):
        """Build a fake_run that takes happy-path defaults but accepts overrides."""
        comment_resp = (0, "", "")
        pr_create = pr_create or _gh_pr_create_stdout()

        def fake_run(args, **kwargs):
            head = args[:3]
            if head == ["gh", "issue", "view"]:
                return view
            if head == ["gh", "pr", "create"]:
                return pr_create
            if head == ["gh", "issue", "comment"]:
                return comment_resp
            if head == ["gh", "issue", "edit"]:
                return (0, "", "")
            if head[:2] == ["git", "worktree"] and args[2] == "add":
                return (0, "", "")
            if head[:2] == ["git", "add"]:
                return (0, "", "")
            if head[:2] == ["git", "commit"]:
                return (0, "", "")
            if head[:2] == ["git", "push"]:
                return (0, "", "")
            # Sprint 14.06: quality gate inspects the diff via 3 `git diff` calls.
            if head[:2] == ["git", "diff"]:
                return (0, "", "")
            if head[0] == "pytest":
                return (pytest_rc, "1 failed" if pytest_rc else "1 passed", "")
            if head[0] == "ruff":
                return (
                    ruff_rc,
                    "x.py:1:1 E501" if ruff_rc else "All checks passed!",
                    "",
                )
            raise AssertionError(f"unexpected subprocess call: {args}")

        return fake_run

    def test_phase6_test_failure_routes_to_fix_attempt_1(self, tmp_path: Path):
        repo_root = tmp_path / "repo"
        repo_root.mkdir()
        workspace = tmp_path / "workspace"
        view = _gh_issue_view_payload()

        fake_run = self._baseline_run(view, pytest_rc=1)

        def fake_claude(prompt, **kwargs):
            return (0, "plan or impl ok", "")

        with (
            patch("bridge.factory.implement._run_subprocess", side_effect=fake_run),
            patch("bridge.factory.implement._invoke_claude", side_effect=fake_claude),
            patch("bridge.factory.implement.transition_state", return_value=True),
        ):
            result = implement_issue(
                42, repo="owner/repo",
                workspace_root=workspace, repo_root=repo_root,
            )

        assert result.failed_phase == PHASE_TEST
        assert result.final_state is FactoryState.FIX_ATTEMPT_1
        assert result.pr_number is None

    def test_phase7_lint_failure_routes_to_fix_attempt_1(self, tmp_path: Path):
        repo_root = tmp_path / "repo"
        repo_root.mkdir()
        workspace = tmp_path / "workspace"
        view = _gh_issue_view_payload()

        fake_run = self._baseline_run(view, ruff_rc=1)

        with (
            patch("bridge.factory.implement._run_subprocess", side_effect=fake_run),
            patch(
                "bridge.factory.implement._invoke_claude",
                return_value=(0, "ok", ""),
            ),
            patch("bridge.factory.implement.transition_state", return_value=True),
        ):
            result = implement_issue(
                42, repo="owner/repo",
                workspace_root=workspace, repo_root=repo_root,
            )

        assert result.failed_phase == PHASE_LINT
        assert result.final_state is FactoryState.FIX_ATTEMPT_1
        assert result.pr_number is None

    def test_phase8_draft_pr_failure_routes_to_needs_human(self, tmp_path: Path):
        repo_root = tmp_path / "repo"
        repo_root.mkdir()
        workspace = tmp_path / "workspace"
        view = _gh_issue_view_payload()

        # gh pr create exits non-zero
        fake_run = self._baseline_run(view, pr_create=(1, "", "PR creation failed"))

        with (
            patch("bridge.factory.implement._run_subprocess", side_effect=fake_run),
            patch(
                "bridge.factory.implement._invoke_claude",
                return_value=(0, "ok", ""),
            ),
            patch("bridge.factory.implement.transition_state", return_value=True),
        ):
            result = implement_issue(
                42, repo="owner/repo",
                workspace_root=workspace, repo_root=repo_root,
            )

        assert result.failed_phase == PHASE_DRAFT_PR
        assert result.final_state is FactoryState.NEEDS_HUMAN
        assert result.pr_number is None

    def test_subprocess_timeout_routes_to_needs_human(self, tmp_path: Path):
        """A TimeoutExpired raised by claude (e.g. plan phase) → NEEDS_HUMAN."""
        repo_root = tmp_path / "repo"
        repo_root.mkdir()
        workspace = tmp_path / "workspace"
        view = _gh_issue_view_payload()

        def fake_run(args, **kwargs):
            head = args[:3]
            if head == ["gh", "issue", "view"]:
                return view
            if head == ["gh", "issue", "comment"]:
                return (0, "", "")
            if head == ["gh", "issue", "edit"]:
                return (0, "", "")
            raise AssertionError(f"unexpected subprocess: {args}")

        def claude_timeout(prompt, **kwargs):
            raise subprocess.TimeoutExpired(cmd="claude", timeout=180)

        with (
            patch("bridge.factory.implement._run_subprocess", side_effect=fake_run),
            patch("bridge.factory.implement._invoke_claude", side_effect=claude_timeout),
            patch("bridge.factory.implement.transition_state", return_value=True),
        ):
            result = implement_issue(
                42, repo="owner/repo",
                workspace_root=workspace, repo_root=repo_root,
            )

        # Plan phase raises → routes to NEEDS_HUMAN
        assert result.final_state is FactoryState.NEEDS_HUMAN
        assert result.pr_number is None


# ── Cost cap ────────────────────────────────────────────────────────────


class TestCostCap:
    """Cost cap halts the workflow with cost_cap_exceeded."""

    def test_cost_cap_constant_is_one_dollar(self):
        # Sprint 14.05 contract: $1.00/issue cap.
        assert COST_CAP_USD == pytest.approx(1.0)

    def test_cost_cap_exceeded_after_plan_halts_workflow(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        """If plan phase reports cost > cap, workflow halts before branching."""
        repo_root = tmp_path / "repo"
        repo_root.mkdir()
        workspace = tmp_path / "workspace"
        view = _gh_issue_view_payload()

        def fake_run(args, **kwargs):
            head = args[:3]
            if head == ["gh", "issue", "view"]:
                return view
            if head == ["gh", "issue", "comment"]:
                return (0, "", "")
            if head == ["gh", "issue", "edit"]:
                return (0, "", "")
            raise AssertionError(f"unexpected subprocess: {args}")

        def fake_claude(prompt, **kwargs):
            return (0, "plan body", "")

        # Override the plan phase to report > cap cost. Implement phase MUST
        # not be reached, so we leave _invoke_claude side-effect general.
        def expensive_plan(issue_number, classification):
            return ("plan", COST_CAP_USD + 0.5)

        monkeypatch.setattr(impl, "_plan_phase", expensive_plan)

        with (
            patch("bridge.factory.implement._run_subprocess", side_effect=fake_run),
            patch("bridge.factory.implement._invoke_claude", side_effect=fake_claude),
            patch("bridge.factory.implement.transition_state", return_value=True),
        ):
            result = implement_issue(
                42, repo="owner/repo",
                workspace_root=workspace, repo_root=repo_root,
            )

        assert result.failed_phase == PHASE_COST_CAP
        assert result.final_state is FactoryState.NEEDS_HUMAN
        assert result.cost_usd > COST_CAP_USD
        assert result.pr_number is None


# ── implement_workflow rate limiting + flag gating ──────────────────────


class TestImplementWorkflow:
    def test_feature_flag_off_returns_empty_no_subprocess(self):
        # Any subprocess call when the flag is OFF is a contract violation.
        with patch(
            "bridge.factory.implement._run_subprocess",
            side_effect=AssertionError("no subprocess when flag OFF"),
        ):
            results = implement_workflow(config_enabled=False)
        assert results == []

    def test_workflow_rate_limits_at_max_issues(self, tmp_path: Path):
        """If 5 issues are accepted but max_issues=2, only 2 implements run."""
        repo_root = tmp_path / "repo"
        repo_root.mkdir()
        workspace = tmp_path / "workspace"

        # The list call returns 5 issues; only 2 should be implemented.
        list_resp = _gh_issue_list_payload([101, 102, 103, 104, 105])

        called_with: list[int] = []

        def fake_implement_issue(issue_number, **kwargs):
            called_with.append(issue_number)
            return ImplementResult(
                issue_number=issue_number,
                pr_number=9000 + issue_number,
                pr_url=f"https://example.com/pull/{9000 + issue_number}",
                final_state=FactoryState.NEEDS_REVIEW,
                failed_phase=None,
                cost_usd=0.10,
                evaluated_at=__import__("datetime").datetime.now(
                    __import__("datetime").timezone.utc
                ),
            )

        def fake_run(args, **kwargs):
            if args[:3] == ["gh", "issue", "list"]:
                return list_resp
            raise AssertionError(f"unexpected subprocess: {args}")

        with (
            patch("bridge.factory.implement._run_subprocess", side_effect=fake_run),
            patch(
                "bridge.factory.implement.implement_issue",
                side_effect=fake_implement_issue,
            ),
        ):
            results = implement_workflow(
                repo="owner/repo",
                max_issues=2,
                workspace_root=workspace,
                repo_root=repo_root,
            )

        assert len(results) == 2
        assert called_with == [101, 102]
        assert {r.pr_number for r in results} == {9101, 9102}

    def test_workflow_returns_empty_when_no_accepted_issues(self):
        with patch(
            "bridge.factory.implement._run_subprocess",
            return_value=_gh_issue_list_payload([]),
        ):
            results = implement_workflow(repo="owner/repo")
        assert results == []
