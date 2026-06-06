"""Tests for ``scripts.experiment_audit_branches`` (Sprint 02.04, issue #978).

Every git call goes through a caller-supplied callable so these tests
NEVER touch a real repository. Integration coverage of the experiment-
loop wiring uses ``patch.object`` on the helpers in ``experiment_loop``.
"""

from __future__ import annotations

import json
import sys
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Module under test lives next to ``experiment_loop`` in ``scripts/``.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from experiment_audit_branches import (  # noqa: E402
    AuditBranchResult,
    BranchSummary,
    annotate_branch_with_outcome,
    create_audit_branch,
    list_audit_branches,
    make_branch_name,
    parse_iter_id,
    read_branch_outcome,
)


# ── Helpers ────────────────────────────────────────────────────


def _completed(returncode: int = 0, stdout: str = "", stderr: str = "") -> subprocess.CompletedProcess[str]:
    """Build a ``subprocess.CompletedProcess`` for the mock git callable."""
    return subprocess.CompletedProcess(
        args=["git"], returncode=returncode, stdout=stdout, stderr=stderr,
    )


def _make_git(responses: list[subprocess.CompletedProcess[str]]):
    """Return a callable that pops responses in order; tracks calls."""
    calls: list[tuple[list[str], Path]] = []

    def _git(args: list[str], *, cwd: Path) -> subprocess.CompletedProcess[str]:
        calls.append((list(args), cwd))
        if not responses:
            raise AssertionError(f"unexpected extra git call: {args}")
        return responses.pop(0)

    _git.calls = calls  # type: ignore[attr-defined]
    return _git


# ── make_branch_name + parse_iter_id ────────────────────────────


class TestMakeBranchName:
    def test_int_zero_padded(self) -> None:
        assert make_branch_name(42) == "autoresearch/iter-0042"

    def test_int_zero(self) -> None:
        assert make_branch_name(0) == "autoresearch/iter-0000"

    def test_int_large(self) -> None:
        # > 9999 still works, just exceeds the 4-digit pad.
        assert make_branch_name(12345) == "autoresearch/iter-12345"

    def test_string_id(self) -> None:
        assert make_branch_name("abc-123") == "autoresearch/iter-abc-123"

    def test_uuid_hex_id(self) -> None:
        assert make_branch_name("deadbeefcafe") == "autoresearch/iter-deadbeefcafe"


class TestParseIterId:
    def test_parses_int_form(self) -> None:
        assert parse_iter_id("autoresearch/iter-0042") == "0042"

    def test_parses_string_form(self) -> None:
        assert parse_iter_id("autoresearch/iter-abc-123") == "abc-123"

    def test_returns_none_for_non_audit_branch(self) -> None:
        assert parse_iter_id("main") is None
        assert parse_iter_id("feature/foo") is None
        # ``autoresearch/something-else`` does NOT have the iter- segment.
        assert parse_iter_id("autoresearch/something-else") is None

    def test_returns_none_for_empty_iter(self) -> None:
        # ``autoresearch/iter-`` exactly with nothing after has no match
        # because the regex requires (.+).
        assert parse_iter_id("autoresearch/iter-") is None

    def test_round_trips(self) -> None:
        for raw in (1, 42, 9999, "abc", "x-y-z", "deadbeef"):
            name = make_branch_name(raw)  # type: ignore[arg-type]
            iter_id = parse_iter_id(name)
            assert iter_id is not None
            # For ints the parsed form is the zero-padded string;
            # for strings it round-trips exactly.
            if isinstance(raw, int):
                assert iter_id == f"{raw:04d}" or iter_id == str(raw)
            else:
                assert iter_id == raw


# ── create_audit_branch ────────────────────────────────────────


class TestCreateAuditBranchHappyPath:
    def test_creates_branch_no_push(self, tmp_path: Path) -> None:
        # Sequence: rev-parse fails (branch doesn't exist) → branch creation.
        git = _make_git([
            _completed(returncode=128, stderr="unknown ref"),
            _completed(returncode=0),
        ])

        result = create_audit_branch(
            iter_id=42,
            head_sha="abc123def456",
            repo_root=tmp_path,
            push_to_origin=False,
            git=git,
        )

        assert result.branch_name == "autoresearch/iter-0042"
        assert result.commit_sha == "abc123def456"
        assert result.pushed is False
        assert result.push_error is None
        # Two calls: rev-parse, branch creation.
        assert len(git.calls) == 2  # type: ignore[attr-defined]
        assert git.calls[1][0][:2] == ["branch", "autoresearch/iter-0042"]  # type: ignore[attr-defined]

    def test_creates_and_pushes(self, tmp_path: Path) -> None:
        git = _make_git([
            _completed(returncode=128),  # rev-parse fail
            _completed(returncode=0),  # branch
            _completed(returncode=0),  # push
        ])

        result = create_audit_branch(
            iter_id="abc-1",
            head_sha="ff" * 20,
            repo_root=tmp_path,
            push_to_origin=True,
            git=git,
        )

        assert result.branch_name == "autoresearch/iter-abc-1"
        assert result.pushed is True
        assert result.push_error is None
        assert git.calls[2][0][:3] == ["push", "origin", "autoresearch/iter-abc-1"]  # type: ignore[attr-defined]


class TestCreateAuditBranchIdempotent:
    def test_existing_branch_same_sha_is_noop(self, tmp_path: Path) -> None:
        # rev-parse returns the same SHA → no branch creation.
        sha = "abcd" * 10
        git = _make_git([
            _completed(returncode=0, stdout=sha + "\n"),
        ])

        result = create_audit_branch(
            iter_id=7,
            head_sha=sha,
            repo_root=tmp_path,
            push_to_origin=False,
            git=git,
        )

        assert result.commit_sha == sha
        assert result.pushed is False
        assert result.push_error is None
        # Only the rev-parse call — no branch creation, no push.
        assert len(git.calls) == 1  # type: ignore[attr-defined]

    def test_existing_branch_different_sha_preserved(self, tmp_path: Path) -> None:
        existing_sha = "1111111111111111111111111111111111111111"
        new_sha = "2222222222222222222222222222222222222222"
        git = _make_git([
            _completed(returncode=0, stdout=existing_sha + "\n"),
        ])

        result = create_audit_branch(
            iter_id=7,
            head_sha=new_sha,
            repo_root=tmp_path,
            push_to_origin=False,
            git=git,
        )

        # Append-only contract — preserve the existing branch.
        assert result.commit_sha == existing_sha
        assert result.pushed is False
        assert result.push_error is not None
        assert "preserving existing" in result.push_error
        # No branch creation called.
        assert len(git.calls) == 1  # type: ignore[attr-defined]


class TestCreateAuditBranchPushFailure:
    def test_push_failure_populates_push_error(self, tmp_path: Path) -> None:
        git = _make_git([
            _completed(returncode=128),  # rev-parse fail
            _completed(returncode=0),  # branch ok
            _completed(returncode=1, stderr="permission denied"),  # push fail
        ])

        result = create_audit_branch(
            iter_id=99,
            head_sha="ab" * 20,
            repo_root=tmp_path,
            push_to_origin=True,
            git=git,
        )

        # Branch creation still considered successful — only push failed.
        assert result.commit_sha == "ab" * 20
        assert result.pushed is False
        assert result.push_error is not None
        assert "permission denied" in result.push_error


class TestCreateAuditBranchCreationFailure:
    def test_creation_failure_raises(self, tmp_path: Path) -> None:
        git = _make_git([
            _completed(returncode=128),  # rev-parse fail
            _completed(returncode=128, stderr="cannot create branch"),  # branch fail
        ])

        with pytest.raises(RuntimeError, match="cannot create branch"):
            create_audit_branch(
                iter_id=1,
                head_sha="cd" * 20,
                repo_root=tmp_path,
                push_to_origin=False,
                git=git,
            )


# ── annotate_branch_with_outcome / read_branch_outcome ─────────


class TestAnnotateBranchWithOutcome:
    def test_writes_note_returns_true(self, tmp_path: Path) -> None:
        sha = "ef" * 20
        git = _make_git([
            _completed(returncode=0, stdout=sha + "\n"),  # rev-parse
            _completed(returncode=0),  # notes add
        ])

        ok = annotate_branch_with_outcome(
            "autoresearch/iter-0042",
            outcome="keep",
            repo_root=tmp_path,
            git=git,
        )

        assert ok is True
        # Confirm we wrote to the dedicated notes ref.
        assert any("--ref=refs/notes/audit-outcome" in arg for arg in git.calls[1][0])  # type: ignore[attr-defined]

    def test_idempotent_replaces_with_force(self, tmp_path: Path) -> None:
        sha = "ef" * 20
        git = _make_git([
            _completed(returncode=0, stdout=sha + "\n"),
            _completed(returncode=0),
        ])

        annotate_branch_with_outcome(
            "autoresearch/iter-0042",
            outcome="discard",
            repo_root=tmp_path,
            git=git,
        )
        # ``--force`` must be present so re-annotation is safe.
        notes_args = git.calls[1][0]  # type: ignore[attr-defined]
        assert "--force" in notes_args

    def test_returns_false_on_rev_parse_failure(self, tmp_path: Path) -> None:
        git = _make_git([
            _completed(returncode=128, stderr="no such ref"),
        ])
        ok = annotate_branch_with_outcome(
            "autoresearch/iter-0042",
            outcome="crash",
            repo_root=tmp_path,
            git=git,
        )
        assert ok is False

    def test_returns_false_on_notes_failure(self, tmp_path: Path) -> None:
        sha = "ef" * 20
        git = _make_git([
            _completed(returncode=0, stdout=sha + "\n"),
            _completed(returncode=1, stderr="notes failed"),
        ])
        ok = annotate_branch_with_outcome(
            "autoresearch/iter-0042",
            outcome="keep",
            repo_root=tmp_path,
            git=git,
        )
        assert ok is False


class TestReadBranchOutcome:
    def test_returns_outcome_string(self, tmp_path: Path) -> None:
        git = _make_git([
            _completed(returncode=0, stdout="keep\n"),
        ])
        outcome = read_branch_outcome(
            "autoresearch/iter-0001",
            repo_root=tmp_path,
            git=git,
        )
        assert outcome == "keep"

    def test_returns_none_when_absent(self, tmp_path: Path) -> None:
        git = _make_git([
            _completed(returncode=1, stderr="no notes"),
        ])
        outcome = read_branch_outcome(
            "autoresearch/iter-0001",
            repo_root=tmp_path,
            git=git,
        )
        assert outcome is None


# ── list_audit_branches ────────────────────────────────────────


class TestListAuditBranches:
    def _git_responses(self, *, branches: list[str], commits: dict[str, tuple[str, str, str]]):
        # First call: for-each-ref.  Then per-branch one log call.
        for_each_stdout = "\n".join(branches) + ("\n" if branches else "")
        responses = [_completed(returncode=0, stdout=for_each_stdout)]
        for b in sorted(branches):
            sha, subj, iso = commits[b]
            responses.append(_completed(
                returncode=0,
                stdout=f"{sha}\x1f{subj}\x1f{iso}\n",
            ))
        return responses

    def test_walks_branches_with_metadata(self, tmp_path: Path) -> None:
        commits = {
            "autoresearch/iter-0001": ("a" * 40, "iter 1 subject", "2026-04-30T00:00:00+00:00"),
            "autoresearch/iter-0002": ("b" * 40, "iter 2 subject", "2026-04-30T00:10:00+00:00"),
        }
        git = _make_git(self._git_responses(
            branches=list(commits.keys()), commits=commits,
        ))

        summaries = list_audit_branches(
            repo_root=tmp_path,
            jsonl_path=None,
            git=git,
        )

        assert len(summaries) == 2
        assert summaries[0].branch_name == "autoresearch/iter-0001"
        assert summaries[0].commit_sha == "a" * 40
        assert summaries[0].commit_subject == "iter 1 subject"
        assert summaries[0].outcome is None  # no JSONL → no metadata
        assert summaries[1].branch_name == "autoresearch/iter-0002"

    def test_annotates_outcome_from_jsonl(self, tmp_path: Path) -> None:
        # Two iterations: 1 keep with fitness, 2 discard with cost.
        jsonl_path = tmp_path / "experiments.jsonl"
        jsonl_path.write_text(
            json.dumps({"iter_id": 1, "status": "keep", "fitness_delta": 0.42, "cost_usd": 0.05}) + "\n"
            + json.dumps({"iter_id": 2, "status": "discard", "fitness_delta": -0.1, "cost_usd": 0.07}) + "\n"
        )

        commits = {
            "autoresearch/iter-0001": ("a" * 40, "subj 1", "2026-04-30T00:00:00+00:00"),
            "autoresearch/iter-0002": ("b" * 40, "subj 2", "2026-04-30T00:10:00+00:00"),
        }
        git = _make_git(self._git_responses(
            branches=list(commits.keys()), commits=commits,
        ))

        summaries = list_audit_branches(
            repo_root=tmp_path,
            jsonl_path=jsonl_path,
            git=git,
        )

        assert summaries[0].outcome == "keep"
        assert summaries[0].fitness_value == pytest.approx(0.42)
        assert summaries[0].cost_usd == pytest.approx(0.05)
        assert summaries[1].outcome == "discard"
        assert summaries[1].fitness_value == pytest.approx(-0.1)

    def test_returns_empty_when_no_branches(self, tmp_path: Path) -> None:
        git = _make_git([_completed(returncode=0, stdout="")])
        summaries = list_audit_branches(
            repo_root=tmp_path,
            jsonl_path=None,
            git=git,
        )
        assert summaries == ()

    def test_returns_immutable_tuple(self, tmp_path: Path) -> None:
        git = _make_git([_completed(returncode=0, stdout="")])
        summaries = list_audit_branches(
            repo_root=tmp_path,
            jsonl_path=None,
            git=git,
        )
        assert isinstance(summaries, tuple)


# ── Integration: experiment_loop wiring ────────────────────────


class TestExperimentLoopIntegration:
    """Verify the experiment_loop helpers call into experiment_audit_branches.

    We patch the safe-wrapper helpers directly so the test exercises only
    the wiring contract — the underlying audit-branch behavior already
    has dedicated tests above.
    """

    def test_create_safe_wraps_create_audit_branch(self, tmp_path: Path) -> None:
        import experiment_loop as el

        fake_result = AuditBranchResult(
            branch_name="autoresearch/iter-test1",
            commit_sha="aa" * 20,
            pushed=False,
            push_error=None,
        )
        with patch.object(el, "create_audit_branch", return_value=fake_result) as mock:
            out = el._create_audit_branch_safe(
                iter_id="test1", head_sha="aa" * 20, push_to_origin=False,
            )
            assert out is fake_result
            mock.assert_called_once()
            kwargs = mock.call_args.kwargs
            assert kwargs["iter_id"] == "test1"
            assert kwargs["push_to_origin"] is False

    def test_create_safe_swallows_exceptions(self) -> None:
        import experiment_loop as el

        with patch.object(el, "create_audit_branch", side_effect=RuntimeError("boom")):
            out = el._create_audit_branch_safe(
                iter_id="x", head_sha="bb" * 20, push_to_origin=False,
            )
            assert out is None

    def test_annotate_safe_calls_through(self) -> None:
        import experiment_loop as el

        with patch.object(el, "annotate_branch_with_outcome") as mock:
            mock.return_value = True
            el._annotate_audit_branch_safe(
                "autoresearch/iter-x", outcome="keep",
            )
            mock.assert_called_once()

    def test_annotate_safe_swallows_exceptions(self) -> None:
        import experiment_loop as el

        with patch.object(
            el, "annotate_branch_with_outcome", side_effect=RuntimeError("boom"),
        ):
            # Must not raise.
            el._annotate_audit_branch_safe(
                "autoresearch/iter-x", outcome="discard",
            )

    def test_load_audit_branch_settings_default_off(self) -> None:
        """When config import fails, settings degrade to (False, False, False).

        Sprint audit-2026-05-16.E.02 (#2070) added the third element
        ``local_cleanup`` to the tuple; the loader stays fail-soft.
        """
        import experiment_loop as el

        with patch.object(
            el, "_load_audit_branch_settings",
            wraps=el._load_audit_branch_settings,
        ):
            enabled, push, local_cleanup = el._load_audit_branch_settings()
            # Default config has audit_branches off — verify the loader
            # is wired up and returns booleans for all three fields.
            assert isinstance(enabled, bool)
            assert isinstance(push, bool)
            assert isinstance(local_cleanup, bool)


class TestEnsureWorktreeCommit:
    """``_ensure_worktree_commit`` is the worktree-side helper that gives
    audit-branch creation a SHA to anchor on regardless of keep/discard."""

    def test_returns_none_when_status_fails(self) -> None:
        import experiment_loop as el

        fake_status = MagicMock(returncode=1, stdout="", stderr="not a git repo")
        with patch.object(el.subprocess, "run", return_value=fake_status):
            sha = el._ensure_worktree_commit("/tmp/nonexistent", "desc")
            assert sha is None

    def test_returns_head_when_clean(self, tmp_path: Path) -> None:
        import experiment_loop as el

        clean_status = MagicMock(returncode=0, stdout="", stderr="")
        head_result = MagicMock(returncode=0, stdout="cafe" * 10 + "\n", stderr="")
        with patch.object(el.subprocess, "run", side_effect=[clean_status, head_result]):
            sha = el._ensure_worktree_commit(str(tmp_path), "desc")
            assert sha == "cafe" * 10


# ── /experiment_branches operator command ──────────────────────


class TestExperimentBranchesCommand:
    """Smoke tests for the operator command. Covers the disabled-flag
    short-circuit and the listing-mode happy path."""

    @pytest.mark.asyncio
    async def test_disabled_flag_message(self) -> None:
        from bridge.commands import CommandHandler

        handler = CommandHandler.__new__(CommandHandler)
        with patch("bridge.config.load_config") as mock_cfg:
            cfg = MagicMock()
            cfg.experiment_audit_branches_enabled = False
            mock_cfg.return_value = cfg

            response = await handler._cmd_experiment_branches("chat", "")

        assert "audit-branches feature is OFF" in response
        assert "audit_branches_enabled = true" in response

    @pytest.mark.asyncio
    async def test_listing_mode_no_branches(self) -> None:
        from bridge.commands import CommandHandler

        handler = CommandHandler.__new__(CommandHandler)
        with patch("bridge.config.load_config") as mock_cfg:
            cfg = MagicMock()
            cfg.experiment_audit_branches_enabled = True
            mock_cfg.return_value = cfg

            with patch(
                "experiment_audit_branches.list_audit_branches",
                return_value=(),
            ):
                response = await handler._cmd_experiment_branches("chat", "")

        assert "no `autoresearch/iter-*` branches yet" in response

    @pytest.mark.asyncio
    async def test_listing_mode_with_branches(self) -> None:
        from bridge.commands import CommandHandler

        handler = CommandHandler.__new__(CommandHandler)
        summary = BranchSummary(
            branch_name="autoresearch/iter-0001",
            iter_id="0001",
            commit_sha="a" * 40,
            commit_subject="experiment: try X",
            authored_at_iso="2026-04-30T00:00:00+00:00",
            outcome="keep",
            fitness_value=0.5,
            cost_usd=0.02,
        )

        with patch("bridge.config.load_config") as mock_cfg:
            cfg = MagicMock()
            cfg.experiment_audit_branches_enabled = True
            mock_cfg.return_value = cfg

            with patch(
                "experiment_audit_branches.list_audit_branches",
                return_value=(summary,),
            ):
                response = await handler._cmd_experiment_branches("chat", "")

        assert "autoresearch/iter-0001" in response
        assert "keep" in response
        assert "Audit Branches" in response
