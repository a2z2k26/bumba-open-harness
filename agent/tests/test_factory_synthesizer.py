"""Tests for bridge.factory.seven_rule_synthesizer — Dark Factory 7-rule decision table.

Sprint 14.08 — Plan 14 Phase 4.

Pure-function tests; no I/O, no subprocess, no network. Each test
constructs a small ``ValidateResult`` fixture, hands it to
:func:`synthesize`, and asserts on the resulting :class:`SynthesisDecision`.
"""
from __future__ import annotations

import pytest

from bridge.factory.labels import FactoryState
from bridge.factory.seven_rule_synthesizer import (
    DEFAULT_COST_CAP_USD,
    FIXABLE_REVIEWER_KINDS,
    NONFIXABLE_REVIEWER_KINDS,
    FactorySynthesisOutcome,
    SynthesisDecision,
    SynthesisInput,
    _normalize_block_signature,
    outcome_to_factory_state,
    synthesize,
    synthesize_validate_outcome,
)
from bridge.factory.validate import ReviewerKind, ReviewerResult, ValidateResult


# ── Fixtures ────────────────────────────────────────────────────────────


def _result(
    kind: ReviewerKind,
    verdict: str,
    *,
    summary: str = "ok",
    findings: tuple[str, ...] = (),
    cost_usd: float = 0.01,
) -> ReviewerResult:
    return ReviewerResult(
        kind=kind,
        verdict=verdict,  # type: ignore[arg-type]
        summary=summary,
        findings=findings,
        cost_usd=cost_usd,
        latency_ms=100,
    )


def _vr(
    *reviewer_results: ReviewerResult,
    aggregate: str = "pass",
    block_reasons: tuple[str, ...] = (),
    total_cost_usd: float | None = None,
) -> ValidateResult:
    if total_cost_usd is None:
        total_cost_usd = sum(r.cost_usd for r in reviewer_results)
    return ValidateResult(
        reviewer_results=reviewer_results,
        aggregate_verdict=aggregate,  # type: ignore[arg-type]
        block_reasons=block_reasons,
        total_cost_usd=total_cost_usd,
    )


def _all_pass() -> ValidateResult:
    return _vr(
        _result(ReviewerKind.BEHAVIORAL, "pass"),
        _result(ReviewerKind.SECURITY, "pass"),
        _result(ReviewerKind.CODE_QUALITY, "pass"),
        _result(ReviewerKind.TEST_QUALITY, "pass"),
        aggregate="pass",
    )


# ── Rule 7: ESCALATE_COST ──────────────────────────────────────────────


class TestRule7CostKillSwitch:
    def test_over_cap_escalates(self):
        decision = synthesize(
            SynthesisInput(
                validate_result=_all_pass(),
                total_cost_usd=2.50,
            )
        )
        assert decision.outcome is FactorySynthesisOutcome.ESCALATE_COST
        assert decision.rule_fired == 7
        assert "2.5000" in decision.explanation
        assert "2.00" in decision.explanation

    def test_under_cap_falls_through(self):
        decision = synthesize(
            SynthesisInput(
                validate_result=_all_pass(),
                total_cost_usd=1.99,
            )
        )
        assert decision.outcome is FactorySynthesisOutcome.READY_FOR_OPERATOR

    def test_at_cap_does_not_trip(self):
        # Strict > comparison — exactly at the cap is allowed.
        decision = synthesize(
            SynthesisInput(
                validate_result=_all_pass(),
                total_cost_usd=2.00,
            )
        )
        assert decision.outcome is FactorySynthesisOutcome.READY_FOR_OPERATOR

    def test_custom_cap(self):
        decision = synthesize(
            SynthesisInput(validate_result=_all_pass(), total_cost_usd=0.51),
            cost_cap_usd=0.50,
        )
        assert decision.outcome is FactorySynthesisOutcome.ESCALATE_COST
        assert decision.rule_fired == 7

    def test_rule7_beats_rule6(self):
        """ESCALATE_COST + ABANDON conditions both true → rule 7 wins."""
        blocks = ("security: token leak",)
        vr = _vr(
            _result(
                ReviewerKind.SECURITY,
                "block",
                summary="token leak",
            ),
            aggregate="block",
            block_reasons=blocks,
        )
        decision = synthesize(
            SynthesisInput(
                validate_result=vr,
                total_cost_usd=10.00,  # very over cap
                retry_count=1,
                prior_block_signature=blocks,  # would also trip rule 6
            )
        )
        assert decision.outcome is FactorySynthesisOutcome.ESCALATE_COST
        assert decision.rule_fired == 7


# ── Rule 6: ABANDON ────────────────────────────────────────────────────


class TestRule6Abandon:
    def test_same_signature_abandons(self):
        blocks = ("security: token leak",)
        vr = _vr(
            _result(ReviewerKind.SECURITY, "block", summary="token leak"),
            aggregate="block",
            block_reasons=blocks,
        )
        decision = synthesize(
            SynthesisInput(
                validate_result=vr,
                total_cost_usd=0.10,
                retry_count=1,
                prior_block_signature=blocks,
            )
        )
        assert decision.outcome is FactorySynthesisOutcome.ABANDON
        assert decision.rule_fired == 6
        assert decision.nonfixable_blocks == blocks

    def test_new_signature_falls_through(self):
        prior = ("security: token leak",)
        new_blocks = ("security: different issue",)
        vr = _vr(
            _result(ReviewerKind.SECURITY, "block", summary="different issue"),
            aggregate="block",
            block_reasons=new_blocks,
        )
        decision = synthesize(
            SynthesisInput(
                validate_result=vr,
                total_cost_usd=0.10,
                retry_count=1,
                prior_block_signature=prior,
            )
        )
        assert decision.outcome is FactorySynthesisOutcome.NEEDS_HUMAN
        assert decision.rule_fired == 4

    def test_retry_count_zero_never_fires(self):
        blocks = ("security: token leak",)
        vr = _vr(
            _result(ReviewerKind.SECURITY, "block", summary="token leak"),
            aggregate="block",
            block_reasons=blocks,
        )
        decision = synthesize(
            SynthesisInput(
                validate_result=vr,
                total_cost_usd=0.10,
                retry_count=0,
                prior_block_signature=blocks,  # ignored on retry_count=0
            )
        )
        assert decision.outcome is FactorySynthesisOutcome.NEEDS_HUMAN
        assert decision.rule_fired == 4

    def test_no_blocks_does_not_abandon(self):
        # If we somehow retry with no current blocks, rule 6 should NOT
        # fire — it requires blocks to compare.
        vr = _all_pass()
        decision = synthesize(
            SynthesisInput(
                validate_result=vr,
                total_cost_usd=0.10,
                retry_count=1,
                prior_block_signature=("security: prior",),
            )
        )
        assert decision.outcome is FactorySynthesisOutcome.READY_FOR_OPERATOR


# ── Rule 5: RETRY_REVIEWERS ────────────────────────────────────────────


class TestRule5RetryReviewers:
    def test_two_parse_errors_retries(self):
        vr = _vr(
            _result(
                ReviewerKind.BEHAVIORAL,
                "advise",
                findings=("parse error: missing VERDICT",),
            ),
            _result(
                ReviewerKind.SECURITY,
                "advise",
                findings=("parse error: empty reviewer output",),
            ),
            _result(ReviewerKind.CODE_QUALITY, "pass"),
            _result(ReviewerKind.TEST_QUALITY, "pass"),
            aggregate="advise",
        )
        decision = synthesize(
            SynthesisInput(
                validate_result=vr,
                total_cost_usd=0.10,
                retry_count=0,
            )
        )
        assert decision.outcome is FactorySynthesisOutcome.RETRY_REVIEWERS
        assert decision.rule_fired == 5
        assert "2 reviewers" in decision.explanation

    def test_one_parse_error_falls_through(self):
        vr = _vr(
            _result(
                ReviewerKind.BEHAVIORAL,
                "advise",
                findings=("parse error: missing VERDICT",),
            ),
            _result(ReviewerKind.SECURITY, "pass"),
            _result(ReviewerKind.CODE_QUALITY, "pass"),
            _result(ReviewerKind.TEST_QUALITY, "pass"),
            aggregate="advise",
        )
        decision = synthesize(
            SynthesisInput(
                validate_result=vr,
                total_cost_usd=0.10,
                retry_count=0,
            )
        )
        assert decision.outcome is FactorySynthesisOutcome.READY_WITH_NOTES

    def test_two_parse_errors_after_retry_falls_through(self):
        vr = _vr(
            _result(
                ReviewerKind.BEHAVIORAL,
                "advise",
                findings=("parse error: missing VERDICT",),
            ),
            _result(
                ReviewerKind.SECURITY,
                "advise",
                findings=("parse error: empty reviewer output",),
            ),
            aggregate="advise",
        )
        decision = synthesize(
            SynthesisInput(
                validate_result=vr,
                total_cost_usd=0.10,
                retry_count=1,
            )
        )
        # Falls through past rule 5 to rule 2 (advise notes only).
        assert decision.outcome is FactorySynthesisOutcome.READY_WITH_NOTES


# ── Rule 4: NEEDS_HUMAN ────────────────────────────────────────────────


class TestRule4NeedsHuman:
    def test_security_block(self):
        blocks = ("security: hardcoded API key",)
        vr = _vr(
            _result(ReviewerKind.SECURITY, "block", summary="hardcoded API key"),
            aggregate="block",
            block_reasons=blocks,
        )
        decision = synthesize(
            SynthesisInput(validate_result=vr, total_cost_usd=0.10)
        )
        assert decision.outcome is FactorySynthesisOutcome.NEEDS_HUMAN
        assert decision.rule_fired == 4
        assert decision.nonfixable_blocks == blocks

    def test_behavioral_block(self):
        blocks = ("behavioral: diff doesn't address issue",)
        vr = _vr(
            _result(
                ReviewerKind.BEHAVIORAL,
                "block",
                summary="diff doesn't address issue",
            ),
            aggregate="block",
            block_reasons=blocks,
        )
        decision = synthesize(
            SynthesisInput(validate_result=vr, total_cost_usd=0.10)
        )
        assert decision.outcome is FactorySynthesisOutcome.NEEDS_HUMAN

    def test_mixed_fixable_and_nonfixable(self):
        blocks = (
            "security: open redirect",
            "test_quality: missing test for new branch",
        )
        vr = _vr(
            _result(ReviewerKind.SECURITY, "block", summary="open redirect"),
            _result(
                ReviewerKind.TEST_QUALITY,
                "block",
                summary="missing test for new branch",
            ),
            aggregate="block",
            block_reasons=blocks,
        )
        decision = synthesize(
            SynthesisInput(validate_result=vr, total_cost_usd=0.10)
        )
        # nonfixable wins even when fixable also present
        assert decision.outcome is FactorySynthesisOutcome.NEEDS_HUMAN
        assert decision.rule_fired == 4
        assert "security: open redirect" in decision.nonfixable_blocks
        assert "test_quality: missing test for new branch" in decision.fixable_blocks

    def test_unknown_kind_treated_as_nonfixable(self):
        # An unrecognized kind escalates rather than auto-fixes.
        blocks = ("mystery: who knows what",)
        vr = _vr(
            aggregate="block",
            block_reasons=blocks,
        )
        decision = synthesize(
            SynthesisInput(validate_result=vr, total_cost_usd=0.10)
        )
        assert decision.outcome is FactorySynthesisOutcome.NEEDS_HUMAN


# ── Rule 3: NEEDS_FIX ──────────────────────────────────────────────────


class TestRule3NeedsFix:
    def test_test_quality_block_only(self):
        blocks = ("test_quality: missing assertion",)
        vr = _vr(
            _result(
                ReviewerKind.TEST_QUALITY,
                "block",
                summary="missing assertion",
            ),
            aggregate="block",
            block_reasons=blocks,
        )
        decision = synthesize(
            SynthesisInput(validate_result=vr, total_cost_usd=0.10)
        )
        assert decision.outcome is FactorySynthesisOutcome.NEEDS_FIX
        assert decision.rule_fired == 3
        assert decision.fixable_blocks == blocks
        assert decision.nonfixable_blocks == ()

    def test_code_and_test_quality_both_fixable(self):
        blocks = (
            "code_quality: deeply nested logic",
            "test_quality: gameable assertion",
        )
        vr = _vr(
            aggregate="block",
            block_reasons=blocks,
        )
        decision = synthesize(
            SynthesisInput(validate_result=vr, total_cost_usd=0.10)
        )
        assert decision.outcome is FactorySynthesisOutcome.NEEDS_FIX
        assert decision.rule_fired == 3
        assert set(decision.fixable_blocks) == set(blocks)


# ── Rule 2: READY_WITH_NOTES ───────────────────────────────────────────


class TestRule2ReadyWithNotes:
    def test_zero_blocks_one_advise(self):
        vr = _vr(
            _result(
                ReviewerKind.CODE_QUALITY,
                "advise",
                summary="long function but readable",
            ),
            _result(ReviewerKind.BEHAVIORAL, "pass"),
            _result(ReviewerKind.SECURITY, "pass"),
            _result(ReviewerKind.TEST_QUALITY, "pass"),
            aggregate="advise",
        )
        decision = synthesize(
            SynthesisInput(validate_result=vr, total_cost_usd=0.10)
        )
        assert decision.outcome is FactorySynthesisOutcome.READY_WITH_NOTES
        assert decision.rule_fired == 2
        assert decision.advise_reasons == (
            "code_quality: long function but readable",
        )

    def test_zero_blocks_two_advise(self):
        vr = _vr(
            _result(ReviewerKind.CODE_QUALITY, "advise", summary="naming"),
            _result(ReviewerKind.TEST_QUALITY, "advise", summary="thin coverage"),
            _result(ReviewerKind.BEHAVIORAL, "pass"),
            _result(ReviewerKind.SECURITY, "pass"),
            aggregate="advise",
        )
        decision = synthesize(
            SynthesisInput(validate_result=vr, total_cost_usd=0.10)
        )
        assert decision.outcome is FactorySynthesisOutcome.READY_WITH_NOTES
        assert len(decision.advise_reasons) == 2
        assert "code_quality: naming" in decision.advise_reasons
        assert "test_quality: thin coverage" in decision.advise_reasons


# ── Rule 1: READY_FOR_OPERATOR ─────────────────────────────────────────


class TestRule1ReadyForOperator:
    def test_all_pass(self):
        decision = synthesize(
            SynthesisInput(validate_result=_all_pass(), total_cost_usd=0.10)
        )
        assert decision.outcome is FactorySynthesisOutcome.READY_FOR_OPERATOR
        assert decision.rule_fired == 1
        assert decision.block_reasons == ()
        assert decision.advise_reasons == ()

    def test_empty_results_falls_to_rule_1(self):
        # Documented choice: empty reviewer_results is vacuously passing
        # (mirrors validate.aggregate_verdicts which returns "pass" on
        # empty input).
        vr = _vr(aggregate="pass", block_reasons=())
        decision = synthesize(
            SynthesisInput(validate_result=vr, total_cost_usd=0.0)
        )
        assert decision.outcome is FactorySynthesisOutcome.READY_FOR_OPERATOR
        assert decision.rule_fired == 1


# ── _normalize_block_signature ─────────────────────────────────────────


class TestNormalizeBlockSignature:
    def test_order_independent(self):
        a = _normalize_block_signature(("security: a", "test_quality: b"))
        b = _normalize_block_signature(("test_quality: b", "security: a"))
        assert a == b

    def test_case_insensitive(self):
        a = _normalize_block_signature(("Security: TOKEN leak",))
        b = _normalize_block_signature(("security: token leak",))
        assert a == b

    def test_whitespace_stripped(self):
        a = _normalize_block_signature(("  security: leak  ",))
        b = _normalize_block_signature(("security: leak",))
        assert a == b

    def test_empty_tuple(self):
        assert _normalize_block_signature(()) == ()


# ── outcome_to_factory_state mapping ───────────────────────────────────


class TestOutcomeToFactoryState:
    def test_ready_for_operator_maps_to_needs_review(self):
        assert outcome_to_factory_state(
            FactorySynthesisOutcome.READY_FOR_OPERATOR
        ) is FactoryState.NEEDS_REVIEW

    def test_ready_with_notes_maps_to_needs_review(self):
        assert outcome_to_factory_state(
            FactorySynthesisOutcome.READY_WITH_NOTES
        ) is FactoryState.NEEDS_REVIEW

    def test_needs_fix_maps_to_fix_attempt_1(self):
        assert outcome_to_factory_state(
            FactorySynthesisOutcome.NEEDS_FIX
        ) is FactoryState.FIX_ATTEMPT_1

    def test_needs_human_maps_to_needs_human(self):
        assert outcome_to_factory_state(
            FactorySynthesisOutcome.NEEDS_HUMAN
        ) is FactoryState.NEEDS_HUMAN

    def test_retry_reviewers_maps_to_in_progress(self):
        assert outcome_to_factory_state(
            FactorySynthesisOutcome.RETRY_REVIEWERS
        ) is FactoryState.IN_PROGRESS

    def test_abandon_maps_to_needs_human(self):
        assert outcome_to_factory_state(
            FactorySynthesisOutcome.ABANDON
        ) is FactoryState.NEEDS_HUMAN

    def test_escalate_cost_maps_to_needs_human(self):
        assert outcome_to_factory_state(
            FactorySynthesisOutcome.ESCALATE_COST
        ) is FactoryState.NEEDS_HUMAN

    def test_every_outcome_has_a_mapping(self):
        # Defensive — if a new outcome lands without a state mapping, the
        # call raises rather than silently routing wrong.
        for outcome in FactorySynthesisOutcome:
            state = outcome_to_factory_state(outcome)
            assert isinstance(state, FactoryState)


# ── Purity / determinism ───────────────────────────────────────────────


class TestPurity:
    def test_same_input_same_output(self):
        inp = SynthesisInput(
            validate_result=_all_pass(),
            total_cost_usd=0.10,
        )
        d1 = synthesize(inp)
        d2 = synthesize(inp)
        assert d1 == d2

    def test_input_not_mutated(self):
        # Frozen dataclasses can't be mutated, but the principle still
        # bears asserting: the function does not reach into its inputs.
        original_blocks = ("test_quality: missing assertion",)
        vr = _vr(
            aggregate="block",
            block_reasons=original_blocks,
        )
        inp = SynthesisInput(
            validate_result=vr,
            total_cost_usd=0.10,
            retry_count=0,
        )
        synthesize(inp)
        assert vr.block_reasons == original_blocks
        assert inp.retry_count == 0

    def test_alias_matches_main(self):
        inp = SynthesisInput(
            validate_result=_all_pass(),
            total_cost_usd=0.10,
        )
        assert synthesize_validate_outcome(inp) == synthesize(inp)


# ── Module-level invariants ────────────────────────────────────────────


class TestModuleInvariants:
    def test_default_cap_is_two_dollars(self):
        assert DEFAULT_COST_CAP_USD == 2.00

    def test_fixable_kinds_disjoint_from_nonfixable(self):
        assert FIXABLE_REVIEWER_KINDS.isdisjoint(NONFIXABLE_REVIEWER_KINDS)

    def test_decision_is_frozen(self):
        d = SynthesisDecision(
            outcome=FactorySynthesisOutcome.READY_FOR_OPERATOR,
            rule_fired=1,
            explanation="x",
        )
        with pytest.raises(Exception):  # FrozenInstanceError
            d.rule_fired = 2  # type: ignore[misc]
