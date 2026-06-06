"""Tests for bridge.factory.holdout — Dark Factory holdout primitive.

Sprint 14.03 — Plan 14 Phase 4. Concept-only port, no source copy.

These tests must NEVER hit the real Anthropic API or any live
subprocess. The holdout primitive delegates all subprocess work to a
caller-supplied runner; here every runner is a mock that records what
it was called with.
"""
from __future__ import annotations

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock

import pytest

from bridge.factory.holdout import (
    HoldoutInput,
    HoldoutRunner,
    HoldoutVerdict,
    make_empty_tools_runner,
    parse_verdict,
    run_holdout,
    run_holdout_batch,
)


# ── Helpers ─────────────────────────────────────────────────────────────


def _well_formed(verdict: str = "pass", summary: str = "looks fine") -> str:
    return (
        f"VERDICT: {verdict}\n"
        f"SUMMARY: {summary}\n"
        "FINDINGS:\n"
        "- none\n"
    )


def _input(
    kind: str = "behavioral",
    prompt: str = "judge this",
    cost_cap_usd: float = 0.20,
    timeout_s: int = 60,
) -> HoldoutInput:
    return HoldoutInput(
        kind=kind,
        prompt=prompt,
        cost_cap_usd=cost_cap_usd,
        timeout_s=timeout_s,
    )


def _make_runner(
    response: str | None = None,
    cost_usd: float = 0.01,
    latency_ms: int = 100,
    delay_s: float = 0.0,
) -> tuple[HoldoutRunner, list[str]]:
    """Build a recording runner. Returns (runner, captured_prompts)."""
    captured: list[str] = []
    body = response if response is not None else _well_formed()

    async def _runner(prompt: str) -> tuple[str, float, int]:
        captured.append(prompt)
        if delay_s:
            await asyncio.sleep(delay_s)
        return body, cost_usd, latency_ms

    return _runner, captured


# ── parse_verdict ───────────────────────────────────────────────────────


class TestParseVerdict:
    def test_pass_with_findings_bullets(self):
        raw = (
            "VERDICT: pass\n"
            "Summary line\n"
            "FINDINGS:\n"
            "- finding 1\n"
            "- finding 2\n"
        )
        verdict, summary, findings, err = parse_verdict(raw)
        assert verdict is HoldoutVerdict.PASS
        assert summary == "Summary line"
        assert findings == ("finding 1", "finding 2")
        assert err is None

    def test_block_no_findings_section(self):
        raw = "VERDICT: block\nReason\n"
        verdict, summary, findings, err = parse_verdict(raw)
        assert verdict is HoldoutVerdict.BLOCK
        assert summary == "Reason"
        assert findings == ()
        assert err is None

    def test_advise_with_findings_dropped_none_placeholder(self):
        raw = (
            "VERDICT: advise\n"
            "soft signal\n"
            "FINDINGS:\n"
            "- none\n"
        )
        verdict, summary, findings, err = parse_verdict(raw)
        assert verdict is HoldoutVerdict.ADVISE
        assert summary == "soft signal"
        assert findings == ()
        assert err is None

    def test_garbage_returns_advise_with_parse_error(self):
        verdict, summary, findings, err = parse_verdict("garbage")
        assert verdict is HoldoutVerdict.ADVISE
        assert summary == "reviewer output malformed"
        assert findings == ()
        assert err is not None
        assert "VERDICT" in err  # error names the missing field

    def test_empty_string_returns_advise(self):
        verdict, summary, findings, err = parse_verdict("")
        assert verdict is HoldoutVerdict.ADVISE
        assert err is not None
        assert "empty" in err.lower()

    def test_whitespace_only_returns_advise(self):
        verdict, summary, findings, err = parse_verdict("   \n  \n")
        assert verdict is HoldoutVerdict.ADVISE
        assert err is not None

    def test_summary_line_is_first_non_empty_after_verdict(self):
        raw = (
            "VERDICT: pass\n"
            "\n"
            "this is the summary\n"
            "and another line\n"
            "FINDINGS:\n"
            "- x\n"
        )
        verdict, summary, findings, err = parse_verdict(raw)
        assert summary == "this is the summary"
        assert findings == ("x",)


# ── run_holdout ──────────────────────────────────────────────────────────


class TestRunHoldout:
    @pytest.mark.asyncio
    async def test_calls_runner_exactly_once(self):
        runner, captured = _make_runner()
        await run_holdout(_input(), runner=runner)
        assert len(captured) == 1

    @pytest.mark.asyncio
    async def test_propagates_verdict_summary_findings(self):
        runner, _ = _make_runner(
            response=(
                "VERDICT: block\n"
                "hardcoded secret\n"
                "FINDINGS:\n"
                "- token at foo.py:42\n"
                "- second finding\n"
            ),
        )
        result = await run_holdout(_input(kind="security"), runner=runner)
        assert result.kind == "security"
        assert result.verdict is HoldoutVerdict.BLOCK
        assert result.summary == "hardcoded secret"
        assert result.findings == (
            "token at foo.py:42",
            "second finding",
        )
        assert result.parse_error is None

    @pytest.mark.asyncio
    async def test_propagates_cost_and_latency_from_runner(self):
        runner, _ = _make_runner(cost_usd=0.07, latency_ms=420)
        result = await run_holdout(_input(), runner=runner)
        assert result.cost_usd == pytest.approx(0.07)
        assert result.latency_ms == 420

    @pytest.mark.asyncio
    async def test_malformed_response_yields_advise_with_parse_error(self):
        runner, _ = _make_runner(response="model rambled")
        result = await run_holdout(_input(), runner=runner)
        assert result.verdict is HoldoutVerdict.ADVISE
        assert result.parse_error is not None
        assert "VERDICT" in result.parse_error

    @pytest.mark.asyncio
    async def test_runtime_error_yields_advise(self):
        async def boom_runner(prompt: str) -> tuple[str, float, int]:
            raise RuntimeError("oauth expired")

        result = await run_holdout(_input(), runner=boom_runner)
        assert result.verdict is HoldoutVerdict.ADVISE
        assert "failed" in result.summary
        assert result.parse_error is not None
        assert "RuntimeError" in result.parse_error
        assert "oauth expired" in result.parse_error
        assert result.cost_usd == 0.0
        assert any("oauth expired" in f for f in result.findings)

    @pytest.mark.asyncio
    async def test_timeout_error_yields_advise_naming_timeout(self):
        async def slow_runner(prompt: str) -> tuple[str, float, int]:
            raise asyncio.TimeoutError("60s")

        result = await run_holdout(_input(), runner=slow_runner)
        assert result.verdict is HoldoutVerdict.ADVISE
        assert "timed out" in result.summary
        assert result.parse_error is not None
        assert "TimeoutError" in result.parse_error
        assert result.cost_usd == 0.0

    @pytest.mark.asyncio
    async def test_cost_cap_breach_yields_advise_with_cost_cap_exceeded(self):
        # Runner reports $0.50 spend against a $0.10 cap.
        runner, _ = _make_runner(cost_usd=0.50, latency_ms=100)
        result = await run_holdout(
            _input(cost_cap_usd=0.10),
            runner=runner,
        )
        assert result.verdict is HoldoutVerdict.ADVISE
        assert result.parse_error == "cost_cap_exceeded"
        assert result.cost_usd == pytest.approx(0.50)
        # raw_response is preserved so the audit trail survives.
        assert result.raw_response  # non-empty

    @pytest.mark.asyncio
    async def test_cost_cap_exact_boundary_does_not_trip(self):
        # Cost exactly equal to cap is allowed; only `>` trips the cap.
        runner, _ = _make_runner(cost_usd=0.10, latency_ms=100)
        result = await run_holdout(
            _input(cost_cap_usd=0.10),
            runner=runner,
        )
        assert result.parse_error is None
        assert result.verdict is HoldoutVerdict.PASS

    @pytest.mark.asyncio
    async def test_runner_receives_input_prompt_verbatim(self):
        runner, captured = _make_runner()
        await run_holdout(
            _input(prompt="exact prompt body"),
            runner=runner,
        )
        assert captured == ["exact prompt body"]


# ── run_holdout_batch ────────────────────────────────────────────────────


class TestRunHoldoutBatch:
    @pytest.mark.asyncio
    async def test_three_inputs_yield_three_results(self):
        runner, captured = _make_runner()
        results = await run_holdout_batch(
            (_input(kind="a"), _input(kind="b"), _input(kind="c")),
            runner=runner,
        )
        assert len(results) == 3
        assert len(captured) == 3

    @pytest.mark.asyncio
    async def test_results_preserve_input_order_by_kind(self):
        runner, _ = _make_runner()
        results = await run_holdout_batch(
            (
                _input(kind="behavioral"),
                _input(kind="security"),
                _input(kind="code_quality"),
                _input(kind="test_quality"),
            ),
            runner=runner,
        )
        kinds = [r.kind for r in results]
        assert kinds == ["behavioral", "security", "code_quality", "test_quality"]

    @pytest.mark.asyncio
    async def test_empty_batch_returns_empty_tuple(self):
        runner, captured = _make_runner()
        results = await run_holdout_batch((), runner=runner)
        assert results == ()
        assert captured == []

    @pytest.mark.asyncio
    async def test_runs_concurrently_not_sequentially(self):
        # Each invocation sleeps 100ms. Sequential ≥ 0.3s for three;
        # concurrent should finish well under 0.25s. Generous slack
        # leaves room for slow CI runners.
        runner, _ = _make_runner(delay_s=0.1)
        started = time.monotonic()
        results = await run_holdout_batch(
            (_input(kind="a"), _input(kind="b"), _input(kind="c")),
            runner=runner,
        )
        elapsed = time.monotonic() - started
        assert len(results) == 3
        assert elapsed < 0.25, f"batch ran sequentially? elapsed={elapsed:.3f}s"

    @pytest.mark.asyncio
    async def test_one_breach_does_not_abort_siblings(self):
        # The first input gets a cost-cap breach; the others should
        # still produce normal PASS verdicts.
        call_idx = {"n": 0}

        async def variable_cost_runner(prompt: str) -> tuple[str, float, int]:
            call_idx["n"] += 1
            cost = 1.00 if call_idx["n"] == 1 else 0.01
            return _well_formed(), cost, 100

        results = await run_holdout_batch(
            (
                _input(kind="a", cost_cap_usd=0.10),  # will breach
                _input(kind="b", cost_cap_usd=0.10),
                _input(kind="c", cost_cap_usd=0.10),
            ),
            runner=variable_cost_runner,
        )
        assert len(results) == 3
        # First breached → ADVISE + parse_error.
        assert results[0].parse_error == "cost_cap_exceeded"
        # Others are clean.
        assert results[1].parse_error is None
        assert results[1].verdict is HoldoutVerdict.PASS
        assert results[2].parse_error is None
        assert results[2].verdict is HoldoutVerdict.PASS


# ── make_empty_tools_runner ─────────────────────────────────────────────


class TestMakeEmptyToolsRunner:
    @pytest.mark.asyncio
    async def test_invokes_underlying_with_allowed_tools_empty_kwarg(self):
        # Mock claude_runner that records the kwargs it was called with
        # and returns a tuple shape.
        fake_invoke = AsyncMock(return_value=("VERDICT: pass\nok\n", 0.01, 50))
        fake_claude = MagicMock()
        fake_claude.invoke = fake_invoke

        runner = make_empty_tools_runner(fake_claude, timeout_s=5)
        response, cost_usd, latency_ms = await runner("the prompt")

        fake_invoke.assert_awaited_once()
        # Inspect the kwargs that were passed.
        _args, kwargs = fake_invoke.await_args
        assert kwargs.get("allowed_tools") == ""
        assert response == "VERDICT: pass\nok\n"
        assert cost_usd == pytest.approx(0.01)
        assert latency_ms == 50

    @pytest.mark.asyncio
    async def test_object_return_shape_is_tolerated(self):
        # Underlying invoke returns an object with attributes.
        class _R:
            text = "VERDICT: pass\nok\n"
            cost_usd = 0.02
            latency_ms = 99

        fake_claude = MagicMock()
        fake_claude.invoke = AsyncMock(return_value=_R())
        runner = make_empty_tools_runner(fake_claude, timeout_s=5)
        response, cost_usd, latency_ms = await runner("p")
        assert response == "VERDICT: pass\nok\n"
        assert cost_usd == pytest.approx(0.02)
        assert latency_ms == 99

    @pytest.mark.asyncio
    async def test_timeout_propagates_as_asyncio_timeout(self):
        # Underlying invoke hangs; wait_for fires.
        async def hang(*a, **kw):
            await asyncio.sleep(10)

        fake_claude = MagicMock()
        fake_claude.invoke = hang
        runner = make_empty_tools_runner(fake_claude, timeout_s=0.05)
        with pytest.raises(asyncio.TimeoutError):
            await runner("p")

    @pytest.mark.asyncio
    async def test_missing_invoke_attr_raises_runtime_error(self):
        # claude_runner without an .invoke attribute → loud failure.
        class _Bare:
            pass

        runner = make_empty_tools_runner(_Bare(), timeout_s=5)
        with pytest.raises(RuntimeError, match="missing invoke"):
            await runner("p")


# ── Integration: validate.py still works on top of the primitive ────────


class TestValidateIntegration:
    """Smoke test: validate.py's validate_pr should still dispatch four
    reviewers after the refactor onto run_holdout_batch.
    """

    @pytest.mark.asyncio
    async def test_validate_pr_still_dispatches_four_reviewers(self):
        from bridge.factory.validate import ReviewerKind, validate_pr

        call_count = {"n": 0}
        seen_kinds: set[str] = set()

        async def fake_runner(prompt: str, model: str = "haiku"):
            call_count["n"] += 1
            # Reviewer prompts contain kind name with either underscore
            # ("CODE_QUALITY" → "CODE-QUALITY" in the system prompt) or
            # bare ("BEHAVIORAL", "SECURITY"); accept either form.
            for kind in ReviewerKind:
                hyphenated = kind.name.replace("_", "-")
                if kind.name in prompt or hyphenated in prompt:
                    seen_kinds.add(kind.value)
                    break
            return _well_formed("pass"), 0.01, 50

        result = await validate_pr(
            issue_body="x",
            pr_url="https://x/pull/1",
            diff_text="small",
            runner=fake_runner,
        )
        assert call_count["n"] == 4
        assert len(result.reviewer_results) == 4
        assert seen_kinds == {k.value for k in ReviewerKind}
