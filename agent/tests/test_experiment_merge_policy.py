"""Unit tests for the per-mode merge_policy seam.

Sprint audit-2026-05-15.B.02 (#1997). The two-protocol split is
load-bearing: ``PrePolicy.pre_outcome`` and ``PostPolicy.post_outcome``
MUST be distinct method names because ``@runtime_checkable`` Protocol
matches structurally by method name. The dry-run pass caught a
runtime-breaking bug in the original sketch where both methods were
called ``outcome``; ``test_proposal_only_is_not_postpolicy_instance``
and ``test_shadow_is_not_prepolicy_instance`` are the regression
guards.
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

# Import the seam via the same sys.path shim the loop tests use.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from _experiment.merge_policy import (  # noqa: E402 — sys.path tweak above
    IterationContext,
    IterationOutcome,
    PostPolicy,
    PrePolicy,
    ProductionPolicy,
    ProposalNotes,
    ProposalOnlyPolicy,
    ShadowNotes,
    ShadowPolicy,
    select_policy,
)


def _validation(status: str, summary: str | None = None) -> SimpleNamespace:
    """Build a minimal ValidationResult-shaped object."""
    return SimpleNamespace(status=status, summary=summary)


def _ctx(
    *,
    validation: SimpleNamespace,
    branch: str = "experiment/iter-x",
    audit_branch_sha: str | None = None,
) -> IterationContext:
    return IterationContext(
        worktree="/tmp/bumba-experiments/iter-x",
        branch=branch,
        description="tweak comment in bridge/x.py",
        validation=validation,
        exp={"id": "iter-x", "branch": branch, "worktree": "/tmp/bumba-experiments/iter-x"},
        audit_enabled=False,
        audit_branch_sha=audit_branch_sha,
    )


class TestProposalOnlyPolicy:
    def test_proposal_only_outcome_emits_proposal_skipped(self):
        policy = ProposalOnlyPolicy()
        outcome = policy.pre_outcome({"description": "swap log level"})
        assert isinstance(outcome, IterationOutcome)
        assert outcome.status == "proposal_skipped"
        assert outcome.commit_sha is None
        assert isinstance(outcome.notes, ProposalNotes)
        assert outcome.notes.description == "swap log level"
        assert outcome.notes.would_merge is False

    def test_proposal_only_is_prepolicy_instance(self):
        """ProposalOnlyPolicy structurally satisfies PrePolicy."""
        assert isinstance(ProposalOnlyPolicy(), PrePolicy)

    def test_proposal_only_is_not_postpolicy_instance(self):
        """Regression guard for the dry-run method-naming bug. If both
        protocols used the same method name ``outcome``, this would
        return True at runtime and the split would be meaningless.
        """
        assert not isinstance(ProposalOnlyPolicy(), PostPolicy)


class TestShadowPolicy:
    def test_shadow_keep_outcome_does_not_call_merge_fn(self):
        """ShadowPolicy has no merge_fn parameter — by construction it
        cannot merge. The strongest assertion is that the attribute
        simply does not exist on the instance.
        """
        policy = ShadowPolicy()
        outcome = policy.post_outcome(_ctx(validation=_validation("keep")))
        assert outcome.status == "shadow_keep"
        assert outcome.commit_sha is None
        assert not hasattr(policy, "_merge_fn")

    def test_shadow_discard_outcome_does_not_call_merge_fn(self):
        policy = ShadowPolicy()
        outcome = policy.post_outcome(_ctx(validation=_validation("discard")))
        assert outcome.status == "shadow_discard"
        assert outcome.commit_sha is None
        assert not hasattr(policy, "_merge_fn")

    def test_shadow_outcome_notes_include_would_merge_and_branch(self):
        policy = ShadowPolicy()
        outcome = policy.post_outcome(
            _ctx(
                validation=_validation("keep", summary="3 files changed"),
                branch="experiment/abc",
                audit_branch_sha="cafe1234",
            )
        )
        assert isinstance(outcome.notes, ShadowNotes)
        assert outcome.notes.would_merge is True
        assert outcome.notes.branch == "experiment/abc"
        assert outcome.notes.validator_summary == "3 files changed"
        assert outcome.notes.audit_branch_sha == "cafe1234"

    def test_shadow_is_postpolicy_instance(self):
        assert isinstance(ShadowPolicy(), PostPolicy)

    def test_shadow_is_not_prepolicy_instance(self):
        """Regression guard for the dry-run method-naming bug."""
        assert not isinstance(ShadowPolicy(), PrePolicy)


class TestProductionPolicy:
    def test_production_keep_calls_merge_fn_and_returns_keep_status(self):
        merge_fn = MagicMock(return_value="deadbeefcafe")
        policy = ProductionPolicy(merge_fn)
        outcome = policy.post_outcome(_ctx(validation=_validation("keep")))
        assert outcome.status == "keep"
        assert outcome.commit_sha == "deadbeefcafe"
        merge_fn.assert_called_once_with(
            "/tmp/bumba-experiments/iter-x",
            "experiment/iter-x",
            "tweak comment in bridge/x.py",
        )

    def test_production_discard_does_not_call_merge_fn(self):
        merge_fn = MagicMock()
        policy = ProductionPolicy(merge_fn)
        outcome = policy.post_outcome(_ctx(validation=_validation("discard")))
        assert outcome.status == "discard"
        assert outcome.commit_sha is None
        merge_fn.assert_not_called()

    def test_production_keep_with_failed_merge_returns_discard(self):
        """merge_fn returns None when fast-forward fails (e.g. main moved)
        — production policy degrades that into ``discard``.
        """
        merge_fn = MagicMock(return_value=None)
        policy = ProductionPolicy(merge_fn)
        outcome = policy.post_outcome(_ctx(validation=_validation("keep")))
        assert outcome.status == "discard"
        assert outcome.commit_sha is None
        merge_fn.assert_called_once()

    def test_production_keep_with_halt_returns_halted_pre_merge(self):
        merge_fn = MagicMock(return_value="deadbeefcafe")
        policy = ProductionPolicy(merge_fn)
        ctx = _ctx(validation=_validation("keep"))
        ctx = IterationContext(
            worktree=ctx.worktree,
            branch=ctx.branch,
            description=ctx.description,
            validation=ctx.validation,
            exp=ctx.exp,
            audit_enabled=ctx.audit_enabled,
            audit_branch_sha=ctx.audit_branch_sha,
            halted=True,
            halt_reason="operator stop",
        )

        outcome = policy.post_outcome(ctx)

        assert outcome.status == "halted_pre_merge"
        assert outcome.commit_sha is None
        merge_fn.assert_not_called()


class TestSelectPolicy:
    def test_select_policy_shadow_returns_postpolicy_without_merge_fn(self):
        """select_policy("shadow", merge_fn=...) MUST ignore merge_fn —
        ShadowPolicy by construction cannot merge.
        """
        policy = select_policy("shadow", merge_fn=MagicMock())
        assert isinstance(policy, ShadowPolicy)
        assert isinstance(policy, PostPolicy)
        assert not hasattr(policy, "_merge_fn")

    def test_select_policy_production_returns_postpolicy_with_merge_fn(self):
        merge_fn = MagicMock(return_value="abc123")
        policy = select_policy("production", merge_fn=merge_fn)
        assert isinstance(policy, ProductionPolicy)
        assert isinstance(policy, PostPolicy)
        # The merge_fn is captured and reachable when post_outcome fires.
        outcome = policy.post_outcome(_ctx(validation=_validation("keep")))
        assert outcome.commit_sha == "abc123"

    def test_select_policy_unknown_mode_raises_value_error(self):
        with pytest.raises(ValueError, match="Unknown experiment mode"):
            select_policy("bogus", merge_fn=MagicMock())
