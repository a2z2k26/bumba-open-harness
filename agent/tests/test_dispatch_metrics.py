"""Tests for ``bridge.dispatch_metrics`` (Sprint #1115).

The module wraps an in-memory determinism counter store. Tests assert:

  - ``increment_module_counter`` increments invocation + the
    deterministic / judged counter selected by tier
  - cost / parse_error / trust_score / escalation kwargs are recorded
  - ``record_invocation`` decorator works on sync + async callables
  - ``record_invocation`` extracts ``cost_usd`` from result objects on
    Tier 2/3/4
  - ``record_invocation`` increments parse_error and re-raises on
    ``TypeError`` / ``ValueError``
  - ``snapshot()`` returns the right totals + ratio (zero when empty)
  - ``format_snapshot_for_discord`` produces all sections
  - Concurrent increments are atomic (1000 expected after 100 × 10)
  - The annotated host modules increment the counter on call
  - ``/determinism`` operator command happy path
"""
from __future__ import annotations

import asyncio
import threading
from dataclasses import dataclass

import pytest

from bridge import dispatch_metrics as dm


# ── Per-test isolation ──────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _reset_dispatch_store():
    """Each test gets an empty counter store."""
    dm.reset_for_tests()
    yield
    dm.reset_for_tests()


# ── increment_module_counter ────────────────────────────────────────────


class TestIncrementModuleCounter:

    def test_tier_zero_increments_invocation_and_deterministic(self):
        dm.increment_module_counter("foo.pure", tier=0)
        snap = dm.snapshot()
        assert snap.deterministic_total == 1
        assert snap.judged_total == 0
        mod = snap.by_module["foo.pure"]
        assert mod["tier"] == 0
        assert mod["invocations"] == 1
        assert mod["cost_usd"] == 0.0
        assert mod["parse_errors"] == 0
        assert mod["escalations"] == 0
        assert mod["trust_score"] is None

    def test_tier_one_increments_deterministic(self):
        dm.increment_module_counter("foo.table", tier=1)
        snap = dm.snapshot()
        assert snap.deterministic_total == 1
        assert snap.judged_total == 0

    def test_tier_two_increments_judged_with_cost(self):
        dm.increment_module_counter("foo.haiku", tier=2, cost_usd=0.05)
        snap = dm.snapshot()
        assert snap.deterministic_total == 0
        assert snap.judged_total == 1
        assert snap.by_module["foo.haiku"]["cost_usd"] == 0.05

    def test_tier_two_parse_error_increments_errors(self):
        dm.increment_module_counter(
            "foo.haiku", tier=2, cost_usd=0.05, parse_error=True,
        )
        snap = dm.snapshot()
        assert snap.by_module["foo.haiku"]["parse_errors"] == 1

    def test_tier_three_escalation_increments(self):
        dm.increment_module_counter("foo.fix_loop", tier=3, escalation=True)
        snap = dm.snapshot()
        assert snap.judged_total == 1
        assert snap.by_module["foo.fix_loop"]["escalations"] == 1

    def test_tier_three_trust_score_recorded(self):
        dm.increment_module_counter("foo.judged", tier=3, trust_score=87.5)
        snap = dm.snapshot()
        assert snap.by_module["foo.judged"]["trust_score"] == 87.5

    def test_invalid_tier_raises_value_error(self):
        with pytest.raises(ValueError):
            dm.increment_module_counter("foo.bad", tier=5)  # type: ignore[arg-type]

    def test_repeat_invocations_accumulate(self):
        for _ in range(7):
            dm.increment_module_counter("foo.t0", tier=0)
        snap = dm.snapshot()
        assert snap.by_module["foo.t0"]["invocations"] == 7
        assert snap.deterministic_total == 7


# ── record_invocation decorator ─────────────────────────────────────────


class TestRecordInvocationDecorator:

    def test_sync_function_records_each_call(self):
        @dm.record_invocation("syncmod", tier=0)
        def f(x: int) -> int:
            return x + 1

        assert f(1) == 2
        assert f(2) == 3
        snap = dm.snapshot()
        assert snap.by_module["syncmod"]["invocations"] == 2
        assert snap.deterministic_total == 2

    def test_async_function_records_each_call(self):
        @dm.record_invocation("asyncmod", tier=1)
        async def f(x: int) -> int:
            await asyncio.sleep(0)
            return x * 2

        async def _run():
            return await f(3) + await f(4)

        assert asyncio.run(_run()) == 14
        snap = dm.snapshot()
        assert snap.by_module["asyncmod"]["invocations"] == 2

    def test_tier_two_extracts_cost_from_result(self):
        @dataclass
        class R:
            cost_usd: float

        @dm.record_invocation("haiku.fn", tier=2)
        def f() -> R:
            return R(cost_usd=0.07)

        f()
        f()
        snap = dm.snapshot()
        assert snap.by_module["haiku.fn"]["invocations"] == 2
        assert snap.by_module["haiku.fn"]["cost_usd"] == pytest.approx(0.14)

    def test_tier_three_extracts_total_cost_usd_from_result(self):
        @dataclass
        class R:
            total_cost_usd: float

        @dm.record_invocation("judged.fn", tier=3)
        def f() -> R:
            return R(total_cost_usd=0.25)

        f()
        snap = dm.snapshot()
        assert snap.by_module["judged.fn"]["cost_usd"] == pytest.approx(0.25)

    def test_type_error_increments_parse_error_and_reraises(self):
        @dm.record_invocation("parser", tier=2)
        def f():
            raise TypeError("bad shape")

        with pytest.raises(TypeError, match="bad shape"):
            f()
        snap = dm.snapshot()
        assert snap.by_module["parser"]["parse_errors"] == 1
        # The wrapper records the invocation alongside the parse error so
        # /determinism shows the failed call in the per-module breakdown.
        assert snap.by_module["parser"]["invocations"] == 1
        assert snap.judged_total == 1

    def test_value_error_increments_parse_error_and_reraises(self):
        @dm.record_invocation("parser2", tier=2)
        def f():
            raise ValueError("nope")

        with pytest.raises(ValueError, match="nope"):
            f()
        snap = dm.snapshot()
        assert snap.by_module["parser2"]["parse_errors"] == 1
        assert snap.by_module["parser2"]["invocations"] == 1

    def test_other_exceptions_do_not_count_as_parse_error(self):
        @dm.record_invocation("other", tier=2)
        def f():
            raise RuntimeError("boom")

        with pytest.raises(RuntimeError):
            f()
        snap = dm.snapshot()
        # RuntimeError isn't a parse error → nothing recorded at all
        assert "other" not in snap.by_module


# ── snapshot ratio + totals ──────────────────────────────────────────────


class TestSnapshot:

    def test_empty_snapshot(self):
        snap = dm.snapshot()
        assert snap.deterministic_total == 0
        assert snap.judged_total == 0
        assert snap.deterministic_ratio == 0.0
        assert snap.by_module == {}

    def test_ratio_is_deterministic_over_total(self):
        for _ in range(3):
            dm.increment_module_counter("a", tier=0)
        for _ in range(7):
            dm.increment_module_counter("b", tier=2)
        snap = dm.snapshot()
        assert snap.deterministic_total == 3
        assert snap.judged_total == 7
        assert snap.deterministic_ratio == pytest.approx(0.3)

    def test_ratio_one_when_only_deterministic(self):
        dm.increment_module_counter("a", tier=0)
        dm.increment_module_counter("a", tier=0)
        snap = dm.snapshot()
        assert snap.deterministic_ratio == 1.0


# ── format_snapshot_for_discord ──────────────────────────────────────────


class TestFormatSnapshot:

    def test_empty_snapshot_renders_placeholder(self):
        snap = dm.snapshot()
        text = dm.format_snapshot_for_discord(snap)
        assert "Determinism Spectrum" in text
        assert "No module invocations" in text

    def test_populated_snapshot_renders_all_sections(self):
        for _ in range(5):
            dm.increment_module_counter("alpha", tier=0)
        dm.increment_module_counter("beta", tier=2, cost_usd=0.10)
        dm.increment_module_counter(
            "gamma", tier=3, cost_usd=0.50, escalation=True,
        )
        snap = dm.snapshot()
        text = dm.format_snapshot_for_discord(snap)
        assert "Deterministic ratio" in text
        assert "alpha" in text
        assert "beta" in text
        assert "gamma" in text
        assert "Top" in text
        assert "Escalations recorded: **1**" in text


# ── Concurrency ──────────────────────────────────────────────────────────


class TestConcurrency:

    def test_thread_safe_increments(self):
        n_threads = 100
        per_thread = 10

        def worker():
            for _ in range(per_thread):
                dm.increment_module_counter("hot", tier=0)

        threads = [threading.Thread(target=worker) for _ in range(n_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        snap = dm.snapshot()
        assert snap.by_module["hot"]["invocations"] == n_threads * per_thread
        assert snap.deterministic_total == n_threads * per_thread


# ── Annotated host modules ───────────────────────────────────────────────


class TestAnnotatedModules:

    def test_synthesizer_increments_tier_zero(self):
        from bridge.factory.seven_rule_synthesizer import (
            SynthesisInput,
            synthesize,
        )

        # Build a vacuous validate_result via a duck-typed object.
        class _VR:
            reviewer_results = ()
            block_reasons = ()

        synthesize(SynthesisInput(validate_result=_VR(), total_cost_usd=0.0))
        snap = dm.snapshot()
        mod = snap.by_module["factory.seven_rule_synthesizer.synthesize"]
        assert mod["tier"] == 0
        assert mod["invocations"] == 1
        assert snap.deterministic_total == 1

    def test_mad_result_increments_tier_zero(self):
        from bridge.mad_confidence import mad_result

        mad_result([1.0, 2.0, 3.0])
        snap = dm.snapshot()
        mod = snap.by_module["mad_confidence.mad_result"]
        assert mod["tier"] == 0
        assert mod["invocations"] == 1

    def test_quality_run_all_increments_tier_one(self):
        from bridge.factory.quality import run_all_quality_checks

        run_all_quality_checks(
            diff_stat={"additions": 10, "deletions": 5},
            changed_files=["bridge/factory/labels.py"],
            diff_text="",
            issue_body="",
        )
        snap = dm.snapshot()
        mod = snap.by_module["factory.quality.run_all_quality_checks"]
        assert mod["tier"] == 1
        assert mod["invocations"] == 1
        assert snap.deterministic_total == 1


# ── /determinism operator command ────────────────────────────────────────


class TestDeterminismCommand:

    @pytest.mark.asyncio
    async def test_determinism_command_renders_snapshot(self):
        # Populate the store BEFORE the command runs so the output is
        # non-empty. The handler reads the live snapshot; the test fixture
        # already reset the store at setup.
        dm.increment_module_counter("alpha", tier=0)
        dm.increment_module_counter("beta", tier=2, cost_usd=0.05)

        # Build a minimal CommandHandler. We mock everything irrelevant
        # to /determinism; the handler only touches dispatch_metrics.
        from unittest.mock import MagicMock

        from bridge.commands import CommandHandler

        handler = CommandHandler(
            db=MagicMock(),
            queue=MagicMock(),
            session_manager=MagicMock(),
            claude_runner=None,
        )
        # Tier 3 gating: we call _cmd_determinism directly (the dispatch
        # path goes through BRIDGE_COMMANDS which is gated by the toml).
        text = await handler._cmd_determinism("chat-1", "")
        assert "Determinism Spectrum" in text
        assert "Deterministic ratio" in text
        assert "alpha" in text
        assert "beta" in text
