"""Dark Factory 7-rule synthesizer — deterministic decision table.

Sprint 14.08 — Plan 14 Phase 4.

Concept-only port of coleam00/dark-factory-experiment (no LICENSE — no
source copy). After Sprint 14.07's :mod:`bridge.factory.validate` runs the
4 holdout reviewers and aggregates their verdicts, this module classifies
the :class:`~bridge.factory.validate.ValidateResult` into one of seven
final outcomes that the factory loop (Sprint 14.10) then acts on.

The synthesizer is deterministic: given the same inputs, it always returns
the same outcome. No LLM calls. No I/O. Pure decision logic.

Outcomes
--------

============================  =============================================
``READY_FOR_OPERATOR``        All four reviewers passed. Proceed to operator
                              review.
``READY_WITH_NOTES``          Zero blocks, one or more advise. Proceed to
                              operator review with reviewer notes appended.
``NEEDS_FIX``                 One or more blocks but ALL on fixable kinds
                              (test/code quality). Bumba may attempt one
                              auto-fix iteration.
``NEEDS_HUMAN``               One or more blocks on a non-fixable kind
                              (security, behavioral). Operator must
                              intervene; auto-fix is not authorized.
``RETRY_REVIEWERS``           Two or more reviewers had parse errors and
                              this is the first attempt. Re-invoke the
                              holdouts before classifying.
``ABANDON``                   Same review run blocked twice (1 retry, then
                              the same blocks reproduced). Stop iterating
                              and escalate to operator.
``ESCALATE_COST``             Cumulative review cost exceeded the cap. Stop
                              and tag ``factory:cost-budget-exhausted``.
============================  =============================================

Rule order
----------

The seven rules fire top-to-bottom; first match wins. Rule 7 (the cost
kill switch) is checked FIRST so an over-budget loop can never escape via
a different outcome. Rule 6 (abandon-on-second-strike) is checked next so
a stuck PR doesn't loop forever. Then Rule 5 (retry on parse-error noise),
then the severity-ordered Rules 4 → 3 → 2 → 1.

Naming
------

The module is intentionally namespaced
:mod:`bridge.factory.seven_rule_synthesizer` to avoid colliding with the
unrelated Zone 3 :mod:`bridge.synthesizer` (WorkOrder result merging).
Renamed from ``bridge.factory.synthesizer`` in Sprint P8.3 / audit M-6
(#1749) so the leaf name no longer collides with the bridge-core
``synthesizer`` module. Public names use ``FactorySynthesis*`` /
``synthesize_validate_outcome`` to keep imports unambiguous in IDE
autocomplete and grep audits.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Final

from bridge.dispatch_metrics import increment_module_counter
from bridge.factory.labels import FactoryState

if TYPE_CHECKING:  # pragma: no cover — type-only imports
    from bridge.factory.validate import ReviewerResult


# ── Outcome enum + decision dataclass ────────────────────────────────────


class FactorySynthesisOutcome(str, Enum):
    """The seven outcomes of the synthesizer.

    Subclassing :class:`str` makes the values JSON-serializable and easy to
    compare against literal strings in tests/logs without losing enum
    semantics.
    """

    READY_FOR_OPERATOR = "ready_for_operator"
    READY_WITH_NOTES = "ready_with_notes"
    NEEDS_FIX = "needs_fix"
    NEEDS_HUMAN = "needs_human"
    RETRY_REVIEWERS = "retry_reviewers"
    ABANDON = "abandon"
    ESCALATE_COST = "escalate_cost"


@dataclass(frozen=True)
class SynthesisDecision:
    """Output of the synthesizer — final outcome plus reasoning chain.

    Frozen so a caller cannot accidentally mutate one decision while
    reasoning about another (e.g. between the label transition and the
    GitHub comment body in Sprint 14.10).
    """

    outcome: FactorySynthesisOutcome
    rule_fired: int  # 1-7, the rule that produced this decision
    explanation: str  # human-readable why this outcome was chosen
    block_reasons: tuple[str, ...] = ()  # reviewer block reasons that drove the call
    advise_reasons: tuple[str, ...] = ()  # reviewer advise notes (operator context)
    fixable_blocks: tuple[str, ...] = ()  # blocks NEEDS_FIX could attempt
    nonfixable_blocks: tuple[str, ...] = ()  # blocks requiring operator intervention


@dataclass(frozen=True)
class SynthesisInput:
    """Inputs needed to synthesize a decision.

    ``validate_result`` is typed :class:`object` rather than
    :class:`~bridge.factory.validate.ValidateResult` to keep this module
    importable in environments where the validate module's optional deps
    (``gh`` CLI for ``run_validate_for_pr``) aren't available. The
    synthesizer only reads attributes (``reviewer_results``,
    ``block_reasons``); it never calls validate functions.
    """

    validate_result: object  # ValidateResult from bridge.factory.validate
    total_cost_usd: float
    retry_count: int = 0  # 0 on first invocation, ≥1 on retries
    prior_block_signature: tuple[str, ...] = field(default_factory=tuple)


# ── Reviewer-kind classification ─────────────────────────────────────────


# Reviewer kinds whose blocks Bumba MAY attempt to auto-fix in a single
# additional iteration. Stylistic / coverage issues — the agent has the
# context and authority to address these without operator approval.
FIXABLE_REVIEWER_KINDS: Final[frozenset[str]] = frozenset(
    {"test_quality", "code_quality"}
)

# Reviewer kinds whose blocks REQUIRE operator intervention. Behavioral
# misalignment and security regressions are out of scope for auto-fix —
# both demand a human read on the issue body and threat model.
NONFIXABLE_REVIEWER_KINDS: Final[frozenset[str]] = frozenset(
    {"behavioral", "security"}
)


# ── Cost cap default ─────────────────────────────────────────────────────


# Default cumulative cost cap across all retries within a single factory
# loop. Sprint 14.07's per-validate cap is $0.50; this is the loop-wide
# ceiling assuming ~4 retries' worth of headroom. Callers may override via
# the ``cost_cap_usd`` keyword.
DEFAULT_COST_CAP_USD: Final[float] = 2.00


# ── Helpers ──────────────────────────────────────────────────────────────


def _normalize_block_signature(block_reasons: tuple[str, ...]) -> tuple[str, ...]:
    """Produce a stable signature for equality checks across retries.

    Lowercased + whitespace-stripped + sorted so the signature does not
    depend on reviewer dispatch order or surface formatting noise. The
    Rule 6 abandon check compares this signature against a stored prior
    one — without normalization, trivial whitespace drift would let the
    same block escape detection.
    """
    return tuple(sorted(reason.strip().lower() for reason in block_reasons))


def _classify_block_reason(reason: str) -> str | None:
    """Return the reviewer kind referenced by a block reason, or None.

    Block reasons follow ``"<kind>: <summary>"`` (see
    :func:`bridge.factory.validate.aggregate_verdicts`). The classifier
    parses the kind prefix, lowercases it, and returns it. Unknown or
    malformed reasons return ``None`` — those are treated as nonfixable
    by :func:`_partition_blocks` so we err on the side of operator review.
    """
    if not reason or ":" not in reason:
        return None
    kind, _, _summary = reason.partition(":")
    return kind.strip().lower() or None


def _partition_blocks(
    block_reasons: tuple[str, ...],
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Split block reasons into (fixable, nonfixable).

    Reasons whose kind is not in either set are treated as nonfixable —
    unknown territory escalates rather than auto-fixes.
    """
    fixable: list[str] = []
    nonfixable: list[str] = []
    for reason in block_reasons:
        kind = _classify_block_reason(reason)
        if kind in FIXABLE_REVIEWER_KINDS:
            fixable.append(reason)
        else:
            # Includes NONFIXABLE_REVIEWER_KINDS, unknown kinds, and None.
            nonfixable.append(reason)
    return tuple(fixable), tuple(nonfixable)


def _count_parse_errors(reviewer_results: tuple["ReviewerResult", ...]) -> int:
    """Count reviewer results whose findings indicate a parse error.

    :func:`bridge.factory.validate._parse_reviewer_output` injects a
    finding starting with ``"parse error:"`` whenever the reviewer's raw
    output couldn't be structured. We detect those rather than relying on
    a sentinel field — the dataclass has none.
    """
    count = 0
    for r in reviewer_results:
        for finding in getattr(r, "findings", ()) or ():
            if isinstance(finding, str) and finding.lower().startswith("parse error"):
                count += 1
                break
    return count


def _collect_advise_reasons(
    reviewer_results: tuple["ReviewerResult", ...],
) -> tuple[str, ...]:
    """Collect ``"<kind>: <summary>"`` lines for every advise reviewer.

    Mirrors the format of ``ValidateResult.block_reasons`` so the
    operator-facing GitHub comment in Sprint 14.10 can render them with
    the same template.
    """
    return tuple(
        f"{r.kind.value}: {r.summary}"
        for r in reviewer_results
        if getattr(r, "verdict", None) == "advise"
    )


# ── The 7 rules ──────────────────────────────────────────────────────────


def synthesize(
    inputs: SynthesisInput,
    *,
    cost_cap_usd: float = DEFAULT_COST_CAP_USD,
) -> SynthesisDecision:
    """Apply the seven rules in order; return the first-match decision.

    Rules (top-to-bottom, first match wins):

    Rule 7 (KILL SWITCH)
        ``total_cost_usd > cost_cap_usd`` → ``ESCALATE_COST``. Checked
        first so a runaway loop cannot escape via another outcome.

    Rule 6 (ABANDON)
        ``retry_count >= 1`` AND the normalized block signature equals
        the prior one → ``ABANDON``. The same review run blocked twice;
        further iteration is unproductive. All blocks classified as
        nonfixable so the operator sees the full set.

    Rule 5 (RETRY_REVIEWERS)
        Two or more reviewers had parse errors AND this is the first
        attempt → ``RETRY_REVIEWERS``. Likely transient; re-invoke the
        holdouts before classifying.

    Rule 4 (NEEDS_HUMAN)
        Any block on a non-fixable kind (behavioral, security) →
        ``NEEDS_HUMAN``. If fixable blocks coexist, operator still
        handles all — nonfixable wins.

    Rule 3 (NEEDS_FIX)
        Blocks exist and are ALL on fixable kinds (test/code quality) →
        ``NEEDS_FIX``. Bumba may attempt one auto-fix iteration.

    Rule 2 (READY_WITH_NOTES)
        No blocks, one or more advise → ``READY_WITH_NOTES``. Reviewer
        notes preserved on the decision for the operator-facing comment.

    Rule 1 (READY_FOR_OPERATOR)
        All reviewers passed (or there were no reviewer results — empty
        input is treated as vacuously passing per the validate module's
        aggregator contract) → ``READY_FOR_OPERATOR``.
    """
    # Determinism Spectrum (Sprint #1115): pure decision table, Tier 0.
    increment_module_counter("factory.seven_rule_synthesizer.synthesize", tier=0)
    vr = inputs.validate_result
    reviewer_results: tuple["ReviewerResult", ...] = tuple(
        getattr(vr, "reviewer_results", ()) or ()
    )
    block_reasons: tuple[str, ...] = tuple(getattr(vr, "block_reasons", ()) or ())
    fixable_blocks, nonfixable_blocks = _partition_blocks(block_reasons)
    advise_reasons = _collect_advise_reasons(reviewer_results)

    # Rule 7 — KILL SWITCH (run first)
    if inputs.total_cost_usd > cost_cap_usd:
        return SynthesisDecision(
            outcome=FactorySynthesisOutcome.ESCALATE_COST,
            rule_fired=7,
            explanation=(
                f"Cumulative review cost ${inputs.total_cost_usd:.4f} exceeded "
                f"cap ${cost_cap_usd:.2f}; halting iteration."
            ),
            block_reasons=block_reasons,
            advise_reasons=advise_reasons,
            fixable_blocks=fixable_blocks,
            nonfixable_blocks=nonfixable_blocks,
        )

    # Rule 6 — ABANDON on second-strike same blocks
    current_signature = _normalize_block_signature(block_reasons)
    if (
        inputs.retry_count >= 1
        and block_reasons
        and current_signature == _normalize_block_signature(inputs.prior_block_signature)
    ):
        return SynthesisDecision(
            outcome=FactorySynthesisOutcome.ABANDON,
            rule_fired=6,
            explanation=(
                "Same blocks reproduced after retry; iteration is unproductive. "
                "Escalating to operator."
            ),
            block_reasons=block_reasons,
            advise_reasons=advise_reasons,
            fixable_blocks=(),
            # When we abandon, treat every block as operator-handled.
            nonfixable_blocks=block_reasons,
        )

    # Rule 5 — RETRY when ≥2 reviewers parse-errored on the first attempt
    parse_error_count = _count_parse_errors(reviewer_results)
    if parse_error_count >= 2 and inputs.retry_count == 0:
        return SynthesisDecision(
            outcome=FactorySynthesisOutcome.RETRY_REVIEWERS,
            rule_fired=5,
            explanation=(
                f"{parse_error_count} reviewers had parse errors on the first "
                "attempt; likely transient — retrying before classifying."
            ),
            block_reasons=(),
            advise_reasons=advise_reasons,
            fixable_blocks=(),
            nonfixable_blocks=(),
        )

    # Rule 4 — NEEDS_HUMAN on any non-fixable block
    if nonfixable_blocks:
        return SynthesisDecision(
            outcome=FactorySynthesisOutcome.NEEDS_HUMAN,
            rule_fired=4,
            explanation=(
                f"{len(nonfixable_blocks)} non-fixable block(s) present "
                "(behavioral / security / unknown); operator must intervene."
            ),
            block_reasons=block_reasons,
            advise_reasons=advise_reasons,
            fixable_blocks=fixable_blocks,
            nonfixable_blocks=nonfixable_blocks,
        )

    # Rule 3 — NEEDS_FIX when blocks exist but are ALL fixable
    if fixable_blocks:
        return SynthesisDecision(
            outcome=FactorySynthesisOutcome.NEEDS_FIX,
            rule_fired=3,
            explanation=(
                f"{len(fixable_blocks)} block(s) on fixable kinds "
                "(test/code quality); attempting one auto-fix iteration."
            ),
            block_reasons=block_reasons,
            advise_reasons=advise_reasons,
            fixable_blocks=fixable_blocks,
            nonfixable_blocks=(),
        )

    # Rule 2 — READY_WITH_NOTES when zero blocks but advise present
    if advise_reasons:
        return SynthesisDecision(
            outcome=FactorySynthesisOutcome.READY_WITH_NOTES,
            rule_fired=2,
            explanation=(
                f"No blocks; {len(advise_reasons)} advisory note(s) for "
                "operator context."
            ),
            block_reasons=(),
            advise_reasons=advise_reasons,
            fixable_blocks=(),
            nonfixable_blocks=(),
        )

    # Rule 1 — READY_FOR_OPERATOR (default; covers empty results too)
    return SynthesisDecision(
        outcome=FactorySynthesisOutcome.READY_FOR_OPERATOR,
        rule_fired=1,
        explanation="All reviewers passed; PR ready for operator review.",
        block_reasons=(),
        advise_reasons=(),
        fixable_blocks=(),
        nonfixable_blocks=(),
    )


# Spec-friendly alias. ``synthesize`` is the short name for in-module use;
# ``synthesize_validate_outcome`` is the unambiguous public name spelled
# out in the spec for callers grepping across the codebase.
synthesize_validate_outcome = synthesize


# ── Outcome → FactoryState mapping ───────────────────────────────────────


# Map each synthesizer outcome to the GitHub label state that the factory
# loop (Sprint 14.10) should transition the issue/PR into. ``ABANDON`` and
# ``ESCALATE_COST`` both terminate at ``NEEDS_HUMAN`` because the operator
# is the only authority that can clear either condition. ``NEEDS_FIX``
# rotates through the ``FIX_ATTEMPT_*`` lanes — Sprint 14.10 owns picking
# attempt-1 vs attempt-2 based on prior fix-attempt labels.
_OUTCOME_TO_STATE: Final[dict[FactorySynthesisOutcome, FactoryState]] = {
    FactorySynthesisOutcome.READY_FOR_OPERATOR: FactoryState.NEEDS_REVIEW,
    FactorySynthesisOutcome.READY_WITH_NOTES: FactoryState.NEEDS_REVIEW,
    FactorySynthesisOutcome.NEEDS_FIX: FactoryState.FIX_ATTEMPT_1,
    FactorySynthesisOutcome.NEEDS_HUMAN: FactoryState.NEEDS_HUMAN,
    FactorySynthesisOutcome.RETRY_REVIEWERS: FactoryState.IN_PROGRESS,
    FactorySynthesisOutcome.ABANDON: FactoryState.NEEDS_HUMAN,
    FactorySynthesisOutcome.ESCALATE_COST: FactoryState.NEEDS_HUMAN,
}


def outcome_to_factory_state(outcome: FactorySynthesisOutcome) -> FactoryState:
    """Map a synthesis outcome to its target factory label state.

    Sprint 14.10 (factory loop orchestrator) is the canonical caller. Out
    of an abundance of caution we hardcode every enum member rather than
    fall through to a default — a new outcome added without a mapping
    should fail loudly at import time, not silently route to a wrong
    state at runtime.
    """
    try:
        return _OUTCOME_TO_STATE[outcome]
    except KeyError as e:  # pragma: no cover — guarded by enum membership
        raise ValueError(f"No FactoryState mapping for outcome {outcome!r}") from e


__all__ = [
    "DEFAULT_COST_CAP_USD",
    "FIXABLE_REVIEWER_KINDS",
    "NONFIXABLE_REVIEWER_KINDS",
    "FactorySynthesisOutcome",
    "SynthesisDecision",
    "SynthesisInput",
    "outcome_to_factory_state",
    "synthesize",
    "synthesize_validate_outcome",
]
