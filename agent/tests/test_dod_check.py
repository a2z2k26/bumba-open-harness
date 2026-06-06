"""Unit tests for scripts/dod_check.check_issue.

Sprint 08.12 — Issue #790.

The five named test cases per spec:
  - test_issue_with_linked_merged_green_pr_passes
  - test_issue_with_linked_unmerged_pr_fails
  - test_issue_with_no_linked_pr_fails
  - test_issue_with_dod_exempt_label_passes_without_pr
  - test_issue_with_linked_pr_but_red_ci_fails

These exercise the pure decision function only — no real `gh` API calls.
"""

from __future__ import annotations

import sys
from pathlib import Path

# scripts/ lives at repo root; agent/tests is one level deeper.
REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = REPO_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from dod_check import check_issue  # noqa: E402


def _make_pr_fetcher(prs: dict[int, dict]) -> callable:
    """Build a PR fetcher closure over a dict of {pr_number: pr_data}."""

    def _fetch(pr_number: int):
        return prs.get(pr_number)

    return _fetch


def test_issue_with_linked_merged_green_pr_passes() -> None:
    """Closed issue + linked PR with merged=True + empty rollup → valid."""
    issue = {
        "state": "CLOSED",
        "labels": [{"name": "type:feature"}],
        "closedByPullRequestsReferences": [{"number": 941}],
        "body": "Closes #999 (this should be ignored once a typed ref is present)",
        "comments": [],
    }
    prs = {
        941: {
            "state": "MERGED",
            "merged": True,
            "statusCheckRollup": [
                {"name": "tests", "conclusion": "SUCCESS"},
                {"name": "lint", "conclusion": "SUCCESS"},
            ],
        },
    }

    valid, reason = check_issue(issue, _make_pr_fetcher(prs))

    assert valid is True, reason
    assert "941" in reason


def test_issue_with_linked_unmerged_pr_fails() -> None:
    """Closed issue + linked PR with merged=False → invalid."""
    issue = {
        "state": "CLOSED",
        "labels": [],
        "closedByPullRequestsReferences": [{"number": 500}],
        "body": "",
        "comments": [],
    }
    prs = {
        500: {
            "state": "CLOSED",
            "merged": False,
            "statusCheckRollup": [],
        },
    }

    valid, reason = check_issue(issue, _make_pr_fetcher(prs))

    assert valid is False
    assert "not merged" in reason


def test_issue_with_no_linked_pr_fails() -> None:
    """Closed issue with no closedBy refs and no `closes #N` keywords → invalid."""
    issue = {
        "state": "CLOSED",
        "labels": [{"name": "type:bug"}],
        "closedByPullRequestsReferences": [],
        "body": "Closing this — operator decided it was duplicate.",
        "comments": [
            {"body": "agreed, closing"},
        ],
    }

    valid, reason = check_issue(issue, _make_pr_fetcher({}))

    assert valid is False
    assert "no linked PR" in reason or "no closedBy" in reason


def test_issue_with_dod_exempt_label_passes_without_pr() -> None:
    """`dod-exempt` label is the override — passes even with no linked PR."""
    issue = {
        "state": "CLOSED",
        "labels": [{"name": "dod-exempt"}, {"name": "planning-archived"}],
        "closedByPullRequestsReferences": [],
        "body": "Archived per planning sweep — no PR by design.",
        "comments": [],
    }

    valid, reason = check_issue(issue, _make_pr_fetcher({}))

    assert valid is True
    assert "dod-exempt" in reason


def test_issue_with_linked_pr_but_red_ci_fails() -> None:
    """Closed issue + linked merged PR but failing rollup → invalid."""
    issue = {
        "state": "CLOSED",
        "labels": [],
        "closedByPullRequestsReferences": [{"number": 700}],
        "body": "",
        "comments": [],
    }
    prs = {
        700: {
            "state": "MERGED",
            "merged": True,
            "statusCheckRollup": [
                {"name": "tests", "conclusion": "SUCCESS"},
                {"name": "lint", "conclusion": "FAILURE"},
            ],
        },
    }

    valid, reason = check_issue(issue, _make_pr_fetcher(prs))

    assert valid is False
    assert "CI not green" in reason or "red" in reason.lower() or "not green" in reason
