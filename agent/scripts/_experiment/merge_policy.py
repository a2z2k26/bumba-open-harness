"""Per-mode merge policy for the experiment loop.

Two protocols separate the mutually-exclusive "before experiment runs"
and "after experiment validates" decision points. proposal_only mode
uses a PrePolicy and exits before any worktree work. shadow and
production modes use PostPolicy and decide based on validation.

The crash status for shadow iterations is NOT produced here — it is set
by main()'s exception wrapper when mode == "shadow" and a crash occurs
before post_outcome() is ever called.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Literal, Protocol, runtime_checkable


class ValidationResult(Protocol):
    status: Literal["keep", "discard"]
    summary: str | None


@dataclass(frozen=True)
class IterationContext:
    worktree: str
    branch: str
    description: str
    validation: ValidationResult
    exp: dict[str, Any]
    audit_enabled: bool
    audit_branch_sha: str | None = None
    halted: bool = False
    halt_reason: str | None = None


@dataclass(frozen=True)
class ProposalNotes:
    description: str
    would_merge: bool = False


@dataclass(frozen=True)
class ShadowNotes:
    would_merge: bool
    branch: str
    validator_summary: str | None
    audit_branch_sha: str | None


Notes = ProposalNotes | ShadowNotes | None


@dataclass(frozen=True)
class IterationOutcome:
    commit_sha: str | None
    # Note: the shadow-mode crash status is intentionally absent from this
    # Literal — main()'s exception wrapper builds the log_result dict
    # directly without going through IterationOutcome. The policy module
    # never produces a crash status.
    status: Literal[
        "keep", "discard", "crash",
        "shadow_keep", "shadow_discard",
        "proposal_skipped", "halted_pre_merge",
    ]
    notes: Notes = None


@runtime_checkable
class PrePolicy(Protocol):
    """Policies that decide BEFORE the experiment runs.

    Method name MUST differ from PostPolicy.post_outcome — runtime_checkable
    Protocol matches structurally by method name. Same-name methods would
    make isinstance(pre_policy, PostPolicy) return True. Live-verified.
    """
    def pre_outcome(self, exp_proposal: dict[str, Any]) -> IterationOutcome: ...


@runtime_checkable
class PostPolicy(Protocol):
    """Policies that decide AFTER validation."""
    def post_outcome(self, ctx: IterationContext) -> IterationOutcome: ...


MergePolicy = PrePolicy | PostPolicy


class ProposalOnlyPolicy:
    """proposal_only: emit a row marker, do not run experiment."""
    def pre_outcome(self, exp_proposal: dict[str, Any]) -> IterationOutcome:
        return IterationOutcome(
            commit_sha=None,
            status="proposal_skipped",
            notes=ProposalNotes(
                description=exp_proposal.get("description", ""),
                would_merge=False,
            ),
        )


class ShadowPolicy:
    """shadow: validate, record, notify, but never merge.

    The class intentionally accepts no parameters — by construction it
    cannot perform a merge. The crash status for shadow iterations is
    set by main()'s exception wrapper, not by this class.
    """
    def post_outcome(self, ctx: IterationContext) -> IterationOutcome:
        keep = ctx.validation.status == "keep"
        return IterationOutcome(
            commit_sha=None,
            status="shadow_keep" if keep else "shadow_discard",
            notes=ShadowNotes(
                would_merge=keep,
                branch=ctx.branch,
                validator_summary=getattr(ctx.validation, "summary", None),
                audit_branch_sha=ctx.audit_branch_sha,
            ),
        )


class ProductionPolicy:
    """production: merge on keep, drop on discard."""
    def __init__(self, merger: Callable[[str, str, str], str | None]) -> None:
        self._merge = merger

    def post_outcome(self, ctx: IterationContext) -> IterationOutcome:
        if ctx.halted:
            return IterationOutcome(
                commit_sha=None,
                status="halted_pre_merge",
                notes=None,
            )
        if ctx.validation.status != "keep":
            return IterationOutcome(commit_sha=None, status="discard", notes=None)
        commit = self._merge(ctx.worktree, ctx.branch, ctx.description)
        return IterationOutcome(
            commit_sha=commit,
            status="keep" if commit else "discard",
            notes=None,
        )


def select_policy(
    mode: str,
    *,
    merge_fn: Callable[[str, str, str], str | None],
) -> MergePolicy:
    if mode == "proposal_only":
        return ProposalOnlyPolicy()
    if mode == "shadow":
        # ShadowPolicy takes no constructor args — it cannot merge by
        # construction, so the injected fn is intentionally discarded.
        return ShadowPolicy()
    if mode == "production":
        return ProductionPolicy(merge_fn)
    raise ValueError(f"Unknown experiment mode: {mode!r}")
