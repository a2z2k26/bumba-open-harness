"""Tests for bridge.factory.validate — Dark Factory 4-reviewer holdout gate.

Sprint 14.07 — Plan 14 Phase 4.

All Claude subprocess + gh + git interactions are mocked. These tests must
NEVER hit the real Anthropic API or a live GitHub repo.
"""
from __future__ import annotations

import asyncio
import time
from unittest.mock import patch

import pytest

from bridge.factory import validate as v
from bridge.factory.validate import (
    COST_CAP_USD,
    REVIEWER_PROMPTS,
    ReviewerKind,
    ReviewerResult,
    ValidateResult,
    aggregate_verdicts,
    run_reviewer,
    validate_pr,
)
from bridge.factory.labels import FactoryState


# ── Helpers ─────────────────────────────────────────────────────────────


def _well_formed_output(verdict: str = "pass", summary: str = "looks fine") -> str:
    """Produce a textbook reviewer response for parsing tests."""
    return (
        f"VERDICT: {verdict}\n"
        f"SUMMARY: {summary}\n"
        "FINDINGS:\n"
        "- none\n"
    )


def _make_result(
    kind: ReviewerKind = ReviewerKind.BEHAVIORAL,
    verdict: str = "pass",
    summary: str = "ok",
    findings: tuple[str, ...] = (),
    cost_usd: float = 0.01,
    latency_ms: int = 100,
) -> ReviewerResult:
    return ReviewerResult(
        kind=kind,
        verdict=verdict,  # type: ignore[arg-type]
        summary=summary,
        findings=findings,
        cost_usd=cost_usd,
        latency_ms=latency_ms,
    )


# ── ReviewerResult / ValidateResult dataclasses ─────────────────────────


class TestDataclasses:
    def test_reviewer_result_round_trip(self):
        r = _make_result(
            kind=ReviewerKind.SECURITY,
            verdict="block",
            summary="hardcoded secret",
            findings=("token in source",),
            cost_usd=0.05,
            latency_ms=420,
        )
        assert r.kind is ReviewerKind.SECURITY
        assert r.verdict == "block"
        assert r.summary == "hardcoded secret"
        assert r.findings == ("token in source",)
        assert r.cost_usd == 0.05
        assert r.latency_ms == 420

    def test_reviewer_result_is_frozen(self):
        r = _make_result()
        with pytest.raises(Exception):
            r.verdict = "block"  # type: ignore[misc]

    def test_validate_result_is_frozen(self):
        vr = ValidateResult(
            reviewer_results=(),
            aggregate_verdict="pass",
            block_reasons=(),
            total_cost_usd=0.0,
        )
        with pytest.raises(Exception):
            vr.aggregate_verdict = "block"  # type: ignore[misc]


# ── aggregate_verdicts ───────────────────────────────────────────────────


class TestAggregateVerdicts:
    def test_all_pass_yields_pass_no_blockers(self):
        results = tuple(_make_result(kind=k, verdict="pass") for k in ReviewerKind)
        verdict, blockers = aggregate_verdicts(results)
        assert verdict == "pass"
        assert blockers == ()

    def test_one_block_yields_block_with_one_reason(self):
        results = (
            _make_result(kind=ReviewerKind.SECURITY, verdict="block", summary="leaked key"),
            _make_result(kind=ReviewerKind.BEHAVIORAL, verdict="pass"),
            _make_result(kind=ReviewerKind.CODE_QUALITY, verdict="pass"),
            _make_result(kind=ReviewerKind.TEST_QUALITY, verdict="pass"),
        )
        verdict, blockers = aggregate_verdicts(results)
        assert verdict == "block"
        assert len(blockers) == 1
        assert blockers[0] == "security: leaked key"

    def test_multiple_blocks_listed_in_input_order(self):
        results = (
            _make_result(kind=ReviewerKind.BEHAVIORAL, verdict="block", summary="off-spec"),
            _make_result(kind=ReviewerKind.SECURITY, verdict="block", summary="leaked key"),
            _make_result(kind=ReviewerKind.CODE_QUALITY, verdict="pass"),
            _make_result(kind=ReviewerKind.TEST_QUALITY, verdict="pass"),
        )
        verdict, blockers = aggregate_verdicts(results)
        assert verdict == "block"
        assert blockers == ("behavioral: off-spec", "security: leaked key")

    def test_one_advise_no_block_yields_advise(self):
        results = (
            _make_result(kind=ReviewerKind.BEHAVIORAL, verdict="advise"),
            _make_result(kind=ReviewerKind.SECURITY, verdict="pass"),
            _make_result(kind=ReviewerKind.CODE_QUALITY, verdict="pass"),
            _make_result(kind=ReviewerKind.TEST_QUALITY, verdict="pass"),
        )
        verdict, blockers = aggregate_verdicts(results)
        assert verdict == "advise"
        assert blockers == ()

    def test_block_takes_precedence_over_advise(self):
        results = (
            _make_result(kind=ReviewerKind.BEHAVIORAL, verdict="advise"),
            _make_result(kind=ReviewerKind.SECURITY, verdict="block", summary="bad"),
            _make_result(kind=ReviewerKind.CODE_QUALITY, verdict="advise"),
            _make_result(kind=ReviewerKind.TEST_QUALITY, verdict="pass"),
        )
        verdict, blockers = aggregate_verdicts(results)
        assert verdict == "block"
        assert blockers == ("security: bad",)

    def test_empty_results_yields_pass(self):
        verdict, blockers = aggregate_verdicts(())
        assert verdict == "pass"
        assert blockers == ()


# ── run_reviewer parsing ─────────────────────────────────────────────────


class TestRunReviewerParsing:
    @pytest.mark.asyncio
    async def test_well_formed_pass(self):
        async def fake_runner(prompt: str, model: str = "haiku"):
            return _well_formed_output("pass", "all good"), 0.02, 250

        r = await run_reviewer(
            ReviewerKind.BEHAVIORAL,
            issue_body="add foo",
            pr_url="https://github.com/owner/repo/pull/1",
            diff_text="diff --git a/foo.py b/foo.py\n+def foo(): ...",
            runner=fake_runner,
        )
        assert r.kind is ReviewerKind.BEHAVIORAL
        assert r.verdict == "pass"
        assert r.summary == "all good"
        assert r.findings == ()
        assert r.cost_usd == 0.02
        assert r.latency_ms == 250

    @pytest.mark.asyncio
    async def test_well_formed_block_with_findings(self):
        raw = (
            "VERDICT: block\n"
            "SUMMARY: hardcoded secret\n"
            "FINDINGS:\n"
            "- token literal at foo.py:42\n"
            "- second issue here\n"
        )

        async def fake_runner(prompt: str, model: str = "haiku"):
            return raw, 0.04, 400

        r = await run_reviewer(
            ReviewerKind.SECURITY,
            issue_body="ship it",
            pr_url="https://x/pull/1",
            diff_text="+token = 'abc123'",
            runner=fake_runner,
        )
        assert r.verdict == "block"
        assert r.summary == "hardcoded secret"
        assert r.findings == (
            "token literal at foo.py:42",
            "second issue here",
        )

    @pytest.mark.asyncio
    async def test_malformed_output_falls_back_to_advise(self):
        async def fake_runner(prompt: str, model: str = "haiku"):
            return "the model rambled and forgot the format", 0.01, 100

        r = await run_reviewer(
            ReviewerKind.CODE_QUALITY,
            issue_body="x",
            pr_url="x",
            diff_text="x",
            runner=fake_runner,
        )
        assert r.verdict == "advise"
        assert "malformed" in r.summary
        assert any("parse error" in f for f in r.findings)

    @pytest.mark.asyncio
    async def test_empty_output_falls_back_to_advise(self):
        async def fake_runner(prompt: str, model: str = "haiku"):
            return "", 0.0, 50

        r = await run_reviewer(
            ReviewerKind.TEST_QUALITY,
            issue_body="x",
            pr_url="x",
            diff_text="x",
            runner=fake_runner,
        )
        assert r.verdict == "advise"
        assert "malformed" in r.summary

    @pytest.mark.asyncio
    async def test_runner_exception_yields_advise(self):
        async def boom_runner(prompt: str, model: str = "haiku"):
            raise RuntimeError("oauth expired")

        r = await run_reviewer(
            ReviewerKind.BEHAVIORAL,
            issue_body="x",
            pr_url="x",
            diff_text="x",
            runner=boom_runner,
        )
        assert r.verdict == "advise"
        assert "failed" in r.summary
        assert any("oauth expired" in f for f in r.findings)
        assert r.cost_usd == 0.0

    @pytest.mark.asyncio
    async def test_sync_runner_also_works(self):
        # A sync callable returning the tuple directly is supported because
        # asyncio.iscoroutine is False on the result.
        def sync_runner(prompt: str, model: str = "haiku"):
            return _well_formed_output("pass"), 0.01, 50

        r = await run_reviewer(
            ReviewerKind.BEHAVIORAL,
            issue_body="x",
            pr_url="x",
            diff_text="x",
            runner=sync_runner,
        )
        assert r.verdict == "pass"

    @pytest.mark.asyncio
    async def test_prompt_includes_lane_scoping(self):
        captured: dict[str, str] = {}

        async def capture_runner(prompt: str, model: str = "haiku"):
            captured["prompt"] = prompt
            return _well_formed_output("pass"), 0.0, 1

        await run_reviewer(
            ReviewerKind.BEHAVIORAL,
            issue_body="add foo",
            pr_url="https://x/pull/1",
            diff_text="+foo",
            runner=capture_runner,
        )
        # Lane-scoping language: "Do NOT comment on …" in every prompt.
        assert "Do NOT comment" in captured["prompt"]
        # Behavioral prompt names the issue body / diff alignment task.
        assert "BEHAVIORAL" in captured["prompt"]
        # The user message includes the diff.
        assert "+foo" in captured["prompt"]


# ── validate_pr ─────────────────────────────────────────────────────────


class TestValidatePr:
    @pytest.mark.asyncio
    async def test_runs_all_4_reviewers(self):
        call_count = {"n": 0}

        async def fake_runner(prompt: str, model: str = "haiku"):
            call_count["n"] += 1
            return _well_formed_output("pass"), 0.01, 100

        result = await validate_pr(
            issue_body="x",
            pr_url="https://x/pull/1",
            diff_text="small diff",
            runner=fake_runner,
        )
        assert call_count["n"] == 4
        assert len(result.reviewer_results) == 4
        kinds = {r.kind for r in result.reviewer_results}
        assert kinds == set(ReviewerKind)

    @pytest.mark.asyncio
    async def test_aggregate_pass_when_all_pass(self):
        async def fake_runner(prompt: str, model: str = "haiku"):
            return _well_formed_output("pass"), 0.01, 100

        result = await validate_pr(
            issue_body="x",
            pr_url="x",
            diff_text="x",
            runner=fake_runner,
        )
        assert result.aggregate_verdict == "pass"
        assert result.block_reasons == ()
        assert result.total_cost_usd == pytest.approx(0.04)

    @pytest.mark.asyncio
    async def test_aggregate_block_when_any_blocks(self):
        # Each kind gets a distinct verdict via the prompt-scanning trick.
        async def fake_runner(prompt: str, model: str = "haiku"):
            if "SECURITY" in prompt:
                return _well_formed_output("block", "hardcoded key"), 0.02, 100
            return _well_formed_output("pass"), 0.01, 100

        result = await validate_pr(
            issue_body="x",
            pr_url="x",
            diff_text="x",
            runner=fake_runner,
        )
        assert result.aggregate_verdict == "block"
        assert len(result.block_reasons) == 1
        assert "security" in result.block_reasons[0]

    @pytest.mark.asyncio
    async def test_runs_reviewers_concurrently(self):
        # Each fake call sleeps for 100ms. If sequential, total ≥400ms; if
        # concurrent, total ≈100ms. We allow generous slack to account for
        # asyncio overhead on slow CI runners.
        async def slow_runner(prompt: str, model: str = "haiku"):
            await asyncio.sleep(0.1)
            return _well_formed_output("pass"), 0.01, 100

        started = time.monotonic()
        await validate_pr(
            issue_body="x",
            pr_url="x",
            diff_text="x",
            runner=slow_runner,
        )
        elapsed = time.monotonic() - started
        # Sequential would be ≥0.4s; concurrent should be well under 0.3s.
        assert elapsed < 0.3, f"reviewers ran sequentially? elapsed={elapsed:.3f}s"

    @pytest.mark.asyncio
    async def test_cost_cap_estimate_degrades_to_two_reviewers(self):
        # Build a diff large enough to push the estimate above $0.50.
        # _HAIKU_USD_PER_CHAR = 2.5e-7; n_reviewers=4; cap=0.50.
        # → diff_text length must exceed 0.50 / (4 * 2.5e-7) = 500_000 chars.
        big_diff = "x" * 600_000

        call_count = {"n": 0}
        seen_kinds: list[ReviewerKind] = []

        async def fake_runner(prompt: str, model: str = "haiku"):
            call_count["n"] += 1
            # Identify which reviewer is calling by prompt header.
            for kind in ReviewerKind:
                if kind.value.upper().replace("_", "-") in prompt or kind.name in prompt:
                    seen_kinds.append(kind)
                    break
            return _well_formed_output("pass"), 0.01, 100

        result = await validate_pr(
            issue_body="x",
            pr_url="x",
            diff_text=big_diff,
            runner=fake_runner,
        )
        # Two reviewers ran (behavioral + security degraded mode).
        assert call_count["n"] == 2
        assert len(result.reviewer_results) == 2
        ran_kinds = {r.kind for r in result.reviewer_results}
        assert ran_kinds == {ReviewerKind.BEHAVIORAL, ReviewerKind.SECURITY}

    @pytest.mark.asyncio
    async def test_total_cost_summed_from_results(self):
        async def fake_runner(prompt: str, model: str = "haiku"):
            return _well_formed_output("pass"), 0.07, 100

        result = await validate_pr(
            issue_body="x",
            pr_url="x",
            diff_text="x",
            runner=fake_runner,
        )
        # 4 reviewers x $0.07 = $0.28.
        assert result.total_cost_usd == pytest.approx(0.28)


# ── route_validate_outcome ──────────────────────────────────────────────


class TestRouteValidateOutcome:
    def test_block_routes_to_needs_human(self):
        result = ValidateResult(
            reviewer_results=(
                _make_result(kind=ReviewerKind.SECURITY, verdict="block", summary="bad"),
            ),
            aggregate_verdict="block",
            block_reasons=("security: bad",),
            total_cost_usd=0.05,
        )
        with patch.object(v, "_gh_issue_comment") as mock_comment, \
             patch.object(v, "transition_state", return_value=True) as mock_trans:
            target = v.route_validate_outcome(
                issue_number=42,
                result=result,
                repo="owner/repo",
            )
        assert target is FactoryState.NEEDS_HUMAN
        # Comment posted with the block reason.
        mock_comment.assert_called_once()
        comment_body = mock_comment.call_args[0][1]
        assert "block" in comment_body
        assert "security: bad" in comment_body
        mock_trans.assert_called()

    def test_pass_routes_to_needs_review(self):
        result = ValidateResult(
            reviewer_results=tuple(
                _make_result(kind=k, verdict="pass") for k in ReviewerKind
            ),
            aggregate_verdict="pass",
            block_reasons=(),
            total_cost_usd=0.04,
        )
        with patch.object(v, "_gh_issue_comment") as mock_comment, \
             patch.object(v, "transition_state", return_value=True):
            target = v.route_validate_outcome(
                issue_number=7,
                result=result,
                repo="owner/repo",
            )
        assert target is FactoryState.NEEDS_REVIEW
        comment_body = mock_comment.call_args[0][1]
        assert "pass" in comment_body

    def test_advise_routes_to_needs_review(self):
        result = ValidateResult(
            reviewer_results=(
                _make_result(kind=ReviewerKind.BEHAVIORAL, verdict="advise"),
            ),
            aggregate_verdict="advise",
            block_reasons=(),
            total_cost_usd=0.02,
        )
        with patch.object(v, "_gh_issue_comment"), \
             patch.object(v, "transition_state", return_value=True):
            target = v.route_validate_outcome(
                issue_number=7,
                result=result,
                repo="owner/repo",
            )
        assert target is FactoryState.NEEDS_REVIEW


# ── run_validate_for_pr feature flag ────────────────────────────────────


class TestRunValidateForPrFlag:
    @pytest.mark.asyncio
    async def test_flag_off_returns_none_and_skips_reviewers(self):
        called = {"runner": False, "transition": False}

        async def fake_runner(prompt: str, model: str = "haiku"):
            called["runner"] = True
            return _well_formed_output("pass"), 0.01, 100

        with patch.object(v, "transition_state") as mock_trans:
            result = await v.run_validate_for_pr(
                issue_number=1,
                issue_body="x",
                pr_url="x",
                diff_text="x",
                runner=fake_runner,
                repo="owner/repo",
                config_enabled=False,
            )
        assert result is None
        assert called["runner"] is False
        mock_trans.assert_not_called()

    @pytest.mark.asyncio
    async def test_flag_on_runs_full_pipeline(self):
        async def fake_runner(prompt: str, model: str = "haiku"):
            return _well_formed_output("pass"), 0.01, 100

        with patch.object(v, "_gh_issue_comment"), \
             patch.object(v, "transition_state", return_value=True):
            result = await v.run_validate_for_pr(
                issue_number=1,
                issue_body="x",
                pr_url="x",
                diff_text="x",
                runner=fake_runner,
                repo="owner/repo",
                config_enabled=True,
            )
        assert result is not None
        assert result.aggregate_verdict == "pass"


# ── Reviewer prompt sanity ──────────────────────────────────────────────


class TestReviewerPromptsCoverAllKinds:
    def test_every_kind_has_a_prompt(self):
        for kind in ReviewerKind:
            assert kind in REVIEWER_PROMPTS
            assert "VERDICT" in REVIEWER_PROMPTS[kind]
            assert "Do NOT comment" in REVIEWER_PROMPTS[kind]

    def test_cost_cap_sanity(self):
        # The cap is the documented $0.50 ceiling.
        assert COST_CAP_USD == 0.50
