"""Tests for ``scripts.experiment_loop_push_guard`` (Sprint ref-audit-02-11, issue #986).

The guard is a defense-in-depth check: it refuses to push branch names
outside ``ALLOWED_PUSH_NAMESPACES`` *before* the network call so the
GitHub PAT's deny rules are never tested in production. These tests
cover the policy contract — both happy paths and the negative cases
that the guard must reject.

Integration test: ``create_audit_branch`` invokes ``assert_pushable_branch``
on its constructed branch name before pushing.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

# Modules under test live next to ``experiment_loop`` in ``scripts/``.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from experiment_loop_push_guard import (  # noqa: E402
    ALLOWED_PUSH_NAMESPACES,
    assert_pushable_branch,
)


# ── Helpers ────────────────────────────────────────────────────


def _completed(
    returncode: int = 0, stdout: str = "", stderr: str = ""
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(
        args=["git"], returncode=returncode, stdout=stdout, stderr=stderr,
    )


def _make_git(responses: list[subprocess.CompletedProcess[str]]):
    calls: list[tuple[list[str], Path]] = []

    def _git(args: list[str], *, cwd: Path) -> subprocess.CompletedProcess[str]:
        calls.append((list(args), cwd))
        if not responses:
            raise AssertionError(f"unexpected extra git call: {args}")
        return responses.pop(0)

    _git.calls = calls  # type: ignore[attr-defined]
    return _git


# ── Policy constants ───────────────────────────────────────────


class TestAllowedPushNamespaces:
    def test_is_a_tuple(self) -> None:
        # Tuple, not list — frozen-by-construction so callers cannot mutate
        # the policy at runtime.
        assert isinstance(ALLOWED_PUSH_NAMESPACES, tuple)

    def test_has_three_namespaces(self) -> None:
        # Spec named exactly three: autoresearch/iter-, experiment-finalize/,
        # experiment/. If this number changes, the design doc should be
        # updated in the same PR.
        assert len(ALLOWED_PUSH_NAMESPACES) == 3

    def test_contains_autoresearch_iter(self) -> None:
        assert "autoresearch/iter-" in ALLOWED_PUSH_NAMESPACES

    def test_contains_experiment_finalize(self) -> None:
        assert "experiment-finalize/" in ALLOWED_PUSH_NAMESPACES

    def test_contains_experiment(self) -> None:
        assert "experiment/" in ALLOWED_PUSH_NAMESPACES


# ── Happy paths ────────────────────────────────────────────────


class TestAssertPushableBranchAllowed:
    def test_autoresearch_iter_with_int_id(self) -> None:
        # No exception → pass
        assert_pushable_branch("autoresearch/iter-0042")

    def test_autoresearch_iter_with_string_id(self) -> None:
        assert_pushable_branch("autoresearch/iter-abc-123")

    def test_experiment_finalize(self) -> None:
        assert_pushable_branch("experiment-finalize/perf-cluster")

    def test_experiment_per_iteration(self) -> None:
        assert_pushable_branch("experiment/abc-123")

    def test_experiment_with_uuid_hex(self) -> None:
        assert_pushable_branch("experiment/deadbeefcafe")


# ── Forbidden cases ────────────────────────────────────────────


class TestAssertPushableBranchForbidden:
    def test_main_is_rejected(self) -> None:
        with pytest.raises(PermissionError) as exc_info:
            assert_pushable_branch("main")
        # Message must name the allowed prefixes so the operator can
        # diagnose without grepping source.
        assert "autoresearch/iter-" in str(exc_info.value)
        assert "experiment-finalize/" in str(exc_info.value)
        assert "experiment/" in str(exc_info.value)

    def test_feat_branch_is_rejected(self) -> None:
        with pytest.raises(PermissionError):
            assert_pushable_branch("feat/something")

    def test_release_branch_is_rejected(self) -> None:
        with pytest.raises(PermissionError):
            assert_pushable_branch("release/v1.0")

    def test_chore_branch_is_rejected(self) -> None:
        with pytest.raises(PermissionError):
            assert_pushable_branch("chore/cleanup")

    def test_autoresearch_iter_without_dash_is_rejected(self) -> None:
        # "autoresearch/iter" (no trailing dash) does NOT match the prefix
        # ``autoresearch/iter-``. Must include the trailing dash so we can't
        # accidentally push a parent ref.
        with pytest.raises(PermissionError):
            assert_pushable_branch("autoresearch/iter")

    def test_experiment_finalize_without_slash_is_rejected(self) -> None:
        # ``experiment-finalize`` without trailing slash is not a finalize
        # group — reject.
        with pytest.raises(PermissionError):
            assert_pushable_branch("experiment-finalize")

    def test_empty_string_is_rejected(self) -> None:
        with pytest.raises(PermissionError) as exc_info:
            assert_pushable_branch("")
        assert "empty branch name" in str(exc_info.value).lower()

    def test_whitespace_only_is_rejected(self) -> None:
        with pytest.raises(PermissionError):
            assert_pushable_branch("   ")

    def test_arbitrary_user_branch_is_rejected(self) -> None:
        # An operator-style branch that looks plausible but is not in scope.
        with pytest.raises(PermissionError):
            assert_pushable_branch("operator/wip-feature")


# ── Integration with create_audit_branch ───────────────────────


class TestCreateAuditBranchInvokesGuard:
    """When ``push_to_origin=True``, ``create_audit_branch`` must consult
    the guard before issuing the push subprocess call. The guard normally
    succeeds (because branch names are constructed via ``make_branch_name``
    which always prepends the allowed ``autoresearch/iter-`` prefix), so
    we verify it by patching the imported reference and asserting it was
    called exactly once with the correct branch name.
    """

    def test_guard_called_before_push_when_push_to_origin_true(
        self, tmp_path: Path
    ) -> None:
        from unittest.mock import patch

        import experiment_audit_branches as eab

        git = _make_git([
            _completed(returncode=128),  # rev-parse fail → branch doesn't exist
            _completed(returncode=0),    # branch creation
            _completed(returncode=0),    # push
        ])

        with patch.object(eab, "assert_pushable_branch") as mock_guard:
            result = eab.create_audit_branch(
                iter_id=42,
                head_sha="ff" * 20,
                repo_root=tmp_path,
                push_to_origin=True,
                git=git,
            )

        # Guard called exactly once with the constructed branch name.
        mock_guard.assert_called_once_with("autoresearch/iter-0042")
        # Push went through after the guard passed.
        assert result.pushed is True

    def test_guard_not_called_when_push_to_origin_false(
        self, tmp_path: Path
    ) -> None:
        from unittest.mock import patch

        import experiment_audit_branches as eab

        git = _make_git([
            _completed(returncode=128),  # rev-parse fail
            _completed(returncode=0),    # branch creation
        ])

        with patch.object(eab, "assert_pushable_branch") as mock_guard:
            eab.create_audit_branch(
                iter_id=42,
                head_sha="ff" * 20,
                repo_root=tmp_path,
                push_to_origin=False,
                git=git,
            )

        # No push attempted → no guard invocation. The guard is only for
        # the push code path.
        mock_guard.assert_not_called()
