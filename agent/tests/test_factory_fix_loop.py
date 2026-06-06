"""Tests for bridge.factory.fix_loop — Sprint 14.09 fresh-context fix loop.

Concept-only port — no Dark Factory source copied. All tests are pure-
function or use injected async runners; no real Claude subprocess, no
``gh``, no network.
"""
from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bridge.factory.fix_loop import (
    DEFAULT_COST_CAP_PER_ATTEMPT_USD,
    DEFAULT_COST_CAP_TOTAL_USD,
    DEFAULT_MAX_ATTEMPTS,
    PROMPT_TEMPLATE,
    make_fix_runner,
    run_fix_loop,
)
from bridge.factory.labels import FactoryState
from bridge.factory.seven_rule_synthesizer import (
    FactorySynthesisOutcome,
    SynthesisDecision,
    SynthesisInput,
)
from bridge.factory.validate import ValidateResult


# ── Helpers ──────────────────────────────────────────────────────────────


def _decision(
    outcome: FactorySynthesisOutcome,
    *,
    block_reasons: tuple[str, ...] = (),
) -> SynthesisDecision:
    """Build a SynthesisDecision with sane defaults for fix-loop tests."""
    return SynthesisDecision(
        outcome=outcome,
        rule_fired=3,
        explanation="test",
        block_reasons=block_reasons,
        fixable_blocks=block_reasons,
    )


def _validate_result(
    *,
    aggregate: str = "pass",
    block_reasons: tuple[str, ...] = (),
    total_cost_usd: float = 0.05,
) -> ValidateResult:
    return ValidateResult(
        reviewer_results=(),
        aggregate_verdict=aggregate,  # type: ignore[arg-type]
        block_reasons=block_reasons,
        total_cost_usd=total_cost_usd,
    )


def _make_fix_runner_mock(
    *,
    new_diff: str = "@@ -1 +1 @@\n-old\n+new",
    cost_usd: float = 0.10,
    latency_ms: int = 1234,
) -> AsyncMock:
    """Build an AsyncMock returning a fix-runner triple."""
    return AsyncMock(return_value=(new_diff, cost_usd, latency_ms))


def _make_validate_runner_mock(
    *,
    result: ValidateResult | None = None,
    side_effect: list[ValidateResult] | None = None,
) -> AsyncMock:
    if side_effect is not None:
        return AsyncMock(side_effect=side_effect)
    return AsyncMock(return_value=result or _validate_result())


# ── Short-circuit: non-NEEDS_FIX initial decisions ───────────────────────


@pytest.mark.asyncio
class TestNonNeedsFixShortCircuit:
    @pytest.mark.parametrize(
        "outcome",
        [
            FactorySynthesisOutcome.READY_FOR_OPERATOR,
            FactorySynthesisOutcome.READY_WITH_NOTES,
            FactorySynthesisOutcome.NEEDS_HUMAN,
            FactorySynthesisOutcome.RETRY_REVIEWERS,
            FactorySynthesisOutcome.ABANDON,
            FactorySynthesisOutcome.ESCALATE_COST,
        ],
    )
    async def test_non_needs_fix_returns_immediately(
        self, outcome: FactorySynthesisOutcome
    ):
        fix_runner = _make_fix_runner_mock()
        validate_runner = _make_validate_runner_mock()
        result = await run_fix_loop(
            initial_decision=_decision(outcome),
            issue_body="body",
            pr_url="https://example/pr/1",
            initial_diff="diff",
            fix_runner=fix_runner,
            validate_runner=validate_runner,
        )
        # No attempts made.
        assert result.attempts == ()
        assert result.final_outcome is outcome
        assert result.escalated_to_human is False
        # No runner invoked.
        fix_runner.assert_not_called()
        validate_runner.assert_not_called()


# ── First attempt resolves ──────────────────────────────────────────────


@pytest.mark.asyncio
class TestFirstAttemptResolves:
    async def test_first_attempt_fixes_skips_second(self):
        # First attempt produces a diff that synthesizes to READY_FOR_OPERATOR.
        fix_runner = _make_fix_runner_mock(cost_usd=0.20)
        # First validate result has no blocks → synth Rule 1 → READY_FOR_OPERATOR.
        validate_runner = _make_validate_runner_mock(
            result=_validate_result(aggregate="pass", total_cost_usd=0.10),
        )
        result = await run_fix_loop(
            initial_decision=_decision(
                FactorySynthesisOutcome.NEEDS_FIX,
                block_reasons=("test_quality: thin",),
            ),
            issue_body="ib",
            pr_url="u",
            initial_diff="d0",
            fix_runner=fix_runner,
            validate_runner=validate_runner,
        )
        assert len(result.attempts) == 1
        assert result.attempts[0].attempt_number == 1
        assert (
            result.attempts[0].final_outcome
            == FactorySynthesisOutcome.READY_FOR_OPERATOR
        )
        assert result.final_outcome == FactorySynthesisOutcome.READY_FOR_OPERATOR
        assert result.escalated_to_human is False
        assert result.attempts[0].block_reasons_addressed == ("test_quality: thin",)
        assert result.attempts[0].block_reasons_remaining == ()
        # Cost = fix subprocess + validate.
        assert pytest.approx(result.total_cost_usd) == 0.30
        # Each runner called exactly once.
        assert fix_runner.await_count == 1
        assert validate_runner.await_count == 1

    async def test_fix_runner_receives_correct_kwargs(self):
        captured: dict[str, Any] = {}

        async def fix_runner(
            issue_body: str,
            current_diff: str,
            block_reasons: tuple[str, ...],
        ) -> tuple[str, float, int]:
            captured["issue_body"] = issue_body
            captured["current_diff"] = current_diff
            captured["block_reasons"] = block_reasons
            return ("new_diff", 0.10, 100)

        validate_runner = _make_validate_runner_mock(
            result=_validate_result(),
        )
        await run_fix_loop(
            initial_decision=_decision(
                FactorySynthesisOutcome.NEEDS_FIX,
                block_reasons=("code_quality: nesting",),
            ),
            issue_body="ISSUE BODY",
            pr_url="u",
            initial_diff="DIFF0",
            fix_runner=fix_runner,
            validate_runner=validate_runner,
        )
        assert captured["issue_body"] == "ISSUE BODY"
        assert captured["current_diff"] == "DIFF0"
        assert captured["block_reasons"] == ("code_quality: nesting",)


# ── Two attempts then resolves ──────────────────────────────────────────


@pytest.mark.asyncio
class TestSecondAttemptResolves:
    async def test_first_fails_second_succeeds(self):
        fix_runner = AsyncMock(
            side_effect=[
                ("d1", 0.30, 100),
                ("d2", 0.40, 100),
            ]
        )
        # First validate still blocks; second passes. Use *different* block
        # reasons on the first re-validate so synth Rule 6 (abandon on
        # second-strike) does not fire — we want the loop to actually try
        # a second attempt.
        validate_runner = AsyncMock(
            side_effect=[
                _validate_result(
                    aggregate="block",
                    block_reasons=("code_quality: still nested",),
                    total_cost_usd=0.05,
                ),
                _validate_result(aggregate="pass", total_cost_usd=0.05),
            ]
        )
        result = await run_fix_loop(
            initial_decision=_decision(
                FactorySynthesisOutcome.NEEDS_FIX,
                block_reasons=("code_quality: deeply nested",),
            ),
            issue_body="ib",
            pr_url="u",
            initial_diff="d0",
            fix_runner=fix_runner,
            validate_runner=validate_runner,
        )
        assert len(result.attempts) == 2
        assert result.attempts[0].attempt_number == 1
        assert (
            result.attempts[0].final_outcome
            == FactorySynthesisOutcome.NEEDS_FIX
        )
        assert result.attempts[1].attempt_number == 2
        assert (
            result.attempts[1].final_outcome
            == FactorySynthesisOutcome.READY_FOR_OPERATOR
        )
        assert result.final_outcome == FactorySynthesisOutcome.READY_FOR_OPERATOR
        assert result.escalated_to_human is False

    async def test_validate_runner_receives_new_diff(self):
        # First fix produces a recognizable diff; assert validate sees it.
        fix_runner = AsyncMock(
            side_effect=[
                ("FIXED_DIFF_1", 0.10, 100),
                ("FIXED_DIFF_2", 0.10, 100),
            ]
        )
        captured_diffs: list[str] = []

        async def validate_runner(
            issue_body: str, pr_url: str, diff_text: str,
        ) -> ValidateResult:
            captured_diffs.append(diff_text)
            return _validate_result(
                aggregate="block",
                block_reasons=(f"code_quality: round {len(captured_diffs)}",),
                total_cost_usd=0.05,
            )

        await run_fix_loop(
            initial_decision=_decision(
                FactorySynthesisOutcome.NEEDS_FIX,
                block_reasons=("code_quality: deeply nested",),
            ),
            issue_body="ib",
            pr_url="u",
            initial_diff="ORIGINAL_DIFF",
            fix_runner=fix_runner,
            validate_runner=validate_runner,
        )
        # validate sees FIXED_DIFF_1 then FIXED_DIFF_2 — never ORIGINAL_DIFF.
        assert captured_diffs == ["FIXED_DIFF_1", "FIXED_DIFF_2"]


# ── Both attempts fail → escalate ────────────────────────────────────────


@pytest.mark.asyncio
class TestBothAttemptsFailEscalate:
    async def test_both_fail_escalates_to_human(self):
        fix_runner = AsyncMock(
            side_effect=[("d1", 0.30, 100), ("d2", 0.40, 100)]
        )
        # Two different block sets so synth Rule 6 (abandon) doesn't fire.
        validate_runner = AsyncMock(
            side_effect=[
                _validate_result(
                    aggregate="block",
                    block_reasons=("code_quality: foo",),
                    total_cost_usd=0.05,
                ),
                _validate_result(
                    aggregate="block",
                    block_reasons=("test_quality: bar",),
                    total_cost_usd=0.05,
                ),
            ]
        )
        result = await run_fix_loop(
            initial_decision=_decision(
                FactorySynthesisOutcome.NEEDS_FIX,
                block_reasons=("code_quality: orig",),
            ),
            issue_body="ib",
            pr_url="u",
            initial_diff="d0",
            fix_runner=fix_runner,
            validate_runner=validate_runner,
        )
        assert len(result.attempts) == 2
        assert result.final_outcome == FactorySynthesisOutcome.NEEDS_HUMAN
        assert result.final_state == FactoryState.NEEDS_HUMAN
        assert result.escalated_to_human is True


# ── Per-attempt cost cap ─────────────────────────────────────────────────


@pytest.mark.asyncio
class TestPerAttemptCostCap:
    async def test_breach_fails_attempt_next_runs(self):
        # First attempt costs $5.00 — way over the cap. It should fail
        # with error set; the second attempt still runs.
        fix_runner = AsyncMock(
            side_effect=[
                ("d1", 5.00, 100),  # over cap
                ("d2", 0.40, 100),
            ]
        )
        validate_runner = AsyncMock(
            return_value=_validate_result(aggregate="pass"),
        )
        result = await run_fix_loop(
            initial_decision=_decision(
                FactorySynthesisOutcome.NEEDS_FIX,
                block_reasons=("code_quality: orig",),
            ),
            issue_body="ib",
            pr_url="u",
            initial_diff="d0",
            fix_runner=fix_runner,
            validate_runner=validate_runner,
            cost_cap_per_attempt_usd=1.50,
            cost_cap_total_usd=10.00,  # high, so the cap-breach is per-attempt
        )
        # First attempt has error.
        assert result.attempts[0].error is not None
        assert "cost cap" in result.attempts[0].error
        # Second attempt ran AND resolved.
        assert len(result.attempts) == 2
        # validate only runs after a successful fix subprocess. First attempt
        # failed before validate, so validate ran exactly once (for attempt 2).
        assert validate_runner.await_count == 1


# ── Total cost cap ───────────────────────────────────────────────────────


@pytest.mark.asyncio
class TestTotalCostCap:
    async def test_total_cap_mid_loop_escalates(self):
        # First attempt costs $1.00 (within per-attempt). Validate adds
        # $0.02. Cumulative = $1.02. Total cap = $1.00. The cap engages
        # *before* the second attempt's pre-attempt gate, so the loop
        # stops + escalates.
        fix_runner = AsyncMock(
            side_effect=[
                ("d1", 1.00, 100),
                ("d2", 0.40, 100),  # never invoked
            ]
        )
        validate_runner = AsyncMock(
            return_value=_validate_result(
                aggregate="block",
                block_reasons=("code_quality: still bad",),
                total_cost_usd=0.02,
            ),
        )
        result = await run_fix_loop(
            initial_decision=_decision(
                FactorySynthesisOutcome.NEEDS_FIX,
                block_reasons=("code_quality: orig",),
            ),
            issue_body="ib",
            pr_url="u",
            initial_diff="d0",
            fix_runner=fix_runner,
            validate_runner=validate_runner,
            cost_cap_per_attempt_usd=2.00,
            cost_cap_total_usd=1.00,
        )
        # First attempt ran; second never invoked.
        assert fix_runner.await_count == 1
        # Final outcome is ESCALATE_COST per cost-kill-switch path.
        assert result.final_outcome == FactorySynthesisOutcome.ESCALATE_COST
        assert result.escalated_to_human is True


# ── prior_block_signature normalization flow ────────────────────────────


@pytest.mark.asyncio
class TestPriorBlockSignatureFlow:
    async def test_signature_normalized_before_synth(self):
        # First attempt's block_reasons have funky case + whitespace.
        # The synthesizer call after attempt 1 must receive a normalized
        # signature (sorted, lowercased, stripped).
        captured_inputs: list[SynthesisInput] = []
        original_synthesize = None  # capture via patch

        def spy_synth(
            inputs: SynthesisInput, *, cost_cap_usd: float = 999.0,
        ) -> SynthesisDecision:
            captured_inputs.append(inputs)
            # Always return READY so the loop terminates after attempt 1.
            return SynthesisDecision(
                outcome=FactorySynthesisOutcome.READY_FOR_OPERATOR,
                rule_fired=1,
                explanation="ok",
            )

        fix_runner = _make_fix_runner_mock()
        validate_runner = _make_validate_runner_mock(
            result=_validate_result(aggregate="pass"),
        )
        with patch(
            "bridge.factory.fix_loop.synthesize", side_effect=spy_synth,
        ):
            await run_fix_loop(
                initial_decision=_decision(
                    FactorySynthesisOutcome.NEEDS_FIX,
                    # Funky surface — should be normalized before synth.
                    block_reasons=(
                        "  Test_Quality: THIN  ",
                        "code_quality: NESTED",
                    ),
                ),
                issue_body="ib",
                pr_url="u",
                initial_diff="d0",
                fix_runner=fix_runner,
                validate_runner=validate_runner,
            )
        # Synth was called once (attempt 1's re-synth).
        assert len(captured_inputs) == 1
        sig = captured_inputs[0].prior_block_signature
        # Lowercased, stripped, sorted.
        assert sig == ("code_quality: nested", "test_quality: thin")
        assert captured_inputs[0].retry_count == 1


# ── make_fix_runner — fresh-context invariant ───────────────────────────


@pytest.mark.asyncio
class TestMakeFixRunnerFreshContext:
    async def test_no_resume_no_session_id(self):
        """The fix runner must NEVER pass --resume / a session_id."""
        captured_kwargs: dict[str, Any] = {}

        class _FakeResult:
            response_text = "patched diff"
            cost_usd = 0.42

        async def fake_invoke(prompt: str, **kwargs: Any) -> _FakeResult:
            captured_kwargs.update(kwargs)
            return _FakeResult()

        claude_runner = MagicMock()
        claude_runner.invoke = fake_invoke

        runner = make_fix_runner(claude_runner, model="sonnet")
        new_diff, cost_usd, latency_ms = await runner(
            "ib", "current diff", ("test_quality: thin",),
        )
        # Verify fresh-context kwargs.
        assert captured_kwargs.get("session_id") is None
        # Resume must not be passed.
        assert "resume" not in captured_kwargs
        assert captured_kwargs.get("model") == "sonnet"
        # Outputs propagate.
        assert new_diff == "patched diff"
        assert cost_usd == pytest.approx(0.42)
        assert latency_ms >= 0

    async def test_default_model_is_sonnet(self):
        """Default model is sonnet — fix loop needs reasoning, not haiku."""
        captured_kwargs: dict[str, Any] = {}

        class _FakeResult:
            response_text = ""
            cost_usd = 0.0

        async def fake_invoke(prompt: str, **kwargs: Any) -> _FakeResult:
            captured_kwargs.update(kwargs)
            return _FakeResult()

        cr = MagicMock()
        cr.invoke = fake_invoke
        runner = make_fix_runner(cr)  # model not overridden
        await runner("ib", "d", ())
        assert captured_kwargs.get("model") == "sonnet"

    async def test_returns_callable(self):
        cr = MagicMock()
        runner = make_fix_runner(cr)
        assert callable(runner)


# ── Fix-runner exception handling ────────────────────────────────────────


@pytest.mark.asyncio
class TestFixRunnerErrorHandling:
    async def test_exception_recorded_next_attempt_runs(self):
        # First attempt raises; second attempt succeeds.
        async def flaky_fix(*_a: Any, **_kw: Any) -> tuple[str, float, int]:
            raise RuntimeError("fix subprocess crashed")

        fix_runner = AsyncMock(
            side_effect=[
                RuntimeError("fix subprocess crashed"),
                ("d2", 0.40, 100),
            ]
        )
        validate_runner = AsyncMock(
            return_value=_validate_result(aggregate="pass"),
        )
        result = await run_fix_loop(
            initial_decision=_decision(
                FactorySynthesisOutcome.NEEDS_FIX,
                block_reasons=("code_quality: orig",),
            ),
            issue_body="ib",
            pr_url="u",
            initial_diff="d0",
            fix_runner=fix_runner,
            validate_runner=validate_runner,
        )
        assert len(result.attempts) == 2
        assert result.attempts[0].error is not None
        assert "fix subprocess crashed" in result.attempts[0].error
        # Second attempt resolved.
        assert (
            result.attempts[1].final_outcome
            == FactorySynthesisOutcome.READY_FOR_OPERATOR
        )


# ── Defensive cap on max_attempts ───────────────────────────────────────


@pytest.mark.asyncio
class TestMaxAttemptsCap:
    async def test_max_attempts_capped_at_default(self):
        # Caller asks for 99 attempts; defensive cap pulls it back to 2.
        # We feed 99 distinct block sets so each synth pass returns NEEDS_FIX
        # (Rule 6 abandon would otherwise fire).
        fix_runner = AsyncMock(
            return_value=("dN", 0.10, 100),
        )
        validate_runner = AsyncMock(
            side_effect=[
                _validate_result(
                    aggregate="block",
                    block_reasons=(f"code_quality: round-{i}",),
                    total_cost_usd=0.01,
                )
                for i in range(99)
            ]
        )
        result = await run_fix_loop(
            initial_decision=_decision(
                FactorySynthesisOutcome.NEEDS_FIX,
                block_reasons=("code_quality: orig",),
            ),
            issue_body="ib",
            pr_url="u",
            initial_diff="d0",
            fix_runner=fix_runner,
            validate_runner=validate_runner,
            max_attempts=99,
        )
        # Capped at DEFAULT_MAX_ATTEMPTS (= 2).
        assert len(result.attempts) == DEFAULT_MAX_ATTEMPTS
        assert fix_runner.await_count == DEFAULT_MAX_ATTEMPTS
        assert result.escalated_to_human is True


# ── Constants exposed for orchestrator wiring ────────────────────────────


class TestConstants:
    def test_defaults_match_spec(self):
        assert DEFAULT_MAX_ATTEMPTS == 2
        assert DEFAULT_COST_CAP_PER_ATTEMPT_USD == pytest.approx(1.50)
        assert DEFAULT_COST_CAP_TOTAL_USD == pytest.approx(3.00)

    def test_prompt_template_includes_required_sections(self):
        # The fix prompt must expose all three input slots.
        assert "{issue_body}" in PROMPT_TEMPLATE
        assert "{current_diff}" in PROMPT_TEMPLATE
        assert "{block_reasons_formatted}" in PROMPT_TEMPLATE


# ── Orchestrator integration ────────────────────────────────────────────


@pytest.mark.asyncio
class TestOrchestratorIntegration:
    async def test_orchestrator_routes_needs_fix_through_loop(self, tmp_path):
        """When fix_loop_enabled, NEEDS_FIX outcomes invoke the fix loop
        and use its final outcome for routing."""
        from bridge.services.factory_orchestrator import (
            FactoryOrchestrator,
            GLOBAL_LOCK_FILENAME,
        )

        # Implement always succeeds with a draft PR.
        from dataclasses import dataclass

        @dataclass
        class _Impl:
            issue_number: int = 7
            pr_number: int = 99
            pr_url: str = "https://example/pr/99"
            final_state: FactoryState = FactoryState.NEEDS_REVIEW
            failed_phase: str | None = None
            cost_usd: float = 0.30

        # Synthesizer returns NEEDS_FIX once (initial), nothing else
        # (the fix-loop's internal synth uses the real one).
        synth = MagicMock(
            return_value=SynthesisDecision(
                outcome=FactorySynthesisOutcome.NEEDS_FIX,
                rule_fired=3,
                explanation="needs fix",
                block_reasons=("code_quality: nested",),
                fixable_blocks=("code_quality: nested",),
            )
        )

        # Fix runner produces a clean diff. Validate (called by fix loop's
        # internal validate adapter — which is the orchestrator's validate
        # runner) returns "pass" so the loop's internal synth lands on
        # READY_FOR_OPERATOR.
        fix_runner = _make_fix_runner_mock(cost_usd=0.20)

        validate_runner = AsyncMock(
            side_effect=[
                # First call: orchestrator's Phase 2 validate.
                _validate_result(
                    aggregate="block",
                    block_reasons=("code_quality: nested",),
                    total_cost_usd=0.05,
                ),
                # Second call: fix loop's internal re-validate after the
                # fix subprocess. Pass → fix loop's synth → READY_FOR_OPERATOR.
                _validate_result(aggregate="pass", total_cost_usd=0.05),
            ]
        )

        orchestrator = FactoryOrchestrator(
            data_dir=tmp_path,
            chat_id="",
            config_enabled=True,
            implement_runner=MagicMock(return_value=_Impl()),
            validate_runner=validate_runner,
            synthesizer=synth,
            global_lock_path=tmp_path / GLOBAL_LOCK_FILENAME,
            per_target_lock_dir=tmp_path / "factory-locks",
            fix_loop_enabled=True,
            fix_runner=fix_runner,
            fix_loop_max_attempts=2,
            fix_loop_cost_cap_per_attempt_usd=1.50,
            fix_loop_cost_cap_total_usd=3.00,
        )

        with patch(
            "bridge.services.factory_orchestrator._gh_list_accepted",
            return_value=[{"number": 7, "title": "x", "body": "do thing"}],
        ), patch(
            "bridge.services.factory_orchestrator._gh_pr_diff",
            return_value="diff",
        ), patch(
            "bridge.services.factory_orchestrator._gh_issue_comment"
        ), patch(
            "bridge.services.factory_orchestrator._gh_pr_ready_for_review"
        ) as mock_ready, patch(
            "bridge.services.factory_orchestrator.transition_state",
            return_value=True,
        ):
            tick = await orchestrator.tick()

        # Fix loop ran: fix_runner invoked once (first attempt resolved).
        assert fix_runner.await_count == 1
        # Validate ran twice: Phase 2 + fix-loop's internal re-validate.
        assert validate_runner.await_count == 2
        # Issue routed to NEEDS_REVIEW (READY_FOR_OPERATOR target).
        assert len(tick.issues_processed) == 1
        ipr = tick.issues_processed[0]
        assert ipr.final_state == FactoryState.NEEDS_REVIEW.value
        # Synthesis_outcome reflects the fix-loop's verdict (READY_FOR_OPERATOR),
        # not the original NEEDS_FIX.
        assert (
            ipr.synthesis_outcome
            == FactorySynthesisOutcome.READY_FOR_OPERATOR.value
        )
        # PR moved to ready (READY_FOR_OPERATOR triggers mark_pr_ready=True).
        mock_ready.assert_called_once()

    async def test_orchestrator_skips_loop_when_flag_off(self, tmp_path):
        """When fix_loop_enabled=False (default), NEEDS_FIX routes
        straight to factory:fix-attempt-1 as before."""
        from bridge.services.factory_orchestrator import (
            FactoryOrchestrator,
            GLOBAL_LOCK_FILENAME,
        )
        from dataclasses import dataclass

        @dataclass
        class _Impl:
            issue_number: int = 7
            pr_number: int = 99
            pr_url: str = "u"
            final_state: FactoryState = FactoryState.NEEDS_REVIEW
            failed_phase: str | None = None
            cost_usd: float = 0.30

        synth = MagicMock(
            return_value=SynthesisDecision(
                outcome=FactorySynthesisOutcome.NEEDS_FIX,
                rule_fired=3,
                explanation="needs fix",
                block_reasons=("code_quality: x",),
                fixable_blocks=("code_quality: x",),
            )
        )
        fix_runner = _make_fix_runner_mock()
        validate_runner = AsyncMock(
            return_value=_validate_result(
                aggregate="block",
                block_reasons=("code_quality: x",),
            ),
        )
        orchestrator = FactoryOrchestrator(
            data_dir=tmp_path,
            chat_id="",
            config_enabled=True,
            implement_runner=MagicMock(return_value=_Impl()),
            validate_runner=validate_runner,
            synthesizer=synth,
            global_lock_path=tmp_path / GLOBAL_LOCK_FILENAME,
            per_target_lock_dir=tmp_path / "factory-locks",
            fix_loop_enabled=False,  # OFF
            fix_runner=fix_runner,
        )
        with patch(
            "bridge.services.factory_orchestrator._gh_list_accepted",
            return_value=[{"number": 7, "title": "x", "body": "y"}],
        ), patch(
            "bridge.services.factory_orchestrator._gh_pr_diff",
            return_value="diff",
        ), patch(
            "bridge.services.factory_orchestrator._gh_issue_comment"
        ), patch(
            "bridge.services.factory_orchestrator._gh_pr_ready_for_review"
        ), patch(
            "bridge.services.factory_orchestrator.transition_state",
            return_value=True,
        ):
            tick = await orchestrator.tick()

        # Fix runner never called when flag is off.
        fix_runner.assert_not_called()
        # Final state lands at FIX_ATTEMPT_1 (the legacy behaviour).
        assert (
            tick.issues_processed[0].final_state
            == FactoryState.FIX_ATTEMPT_1.value
        )
