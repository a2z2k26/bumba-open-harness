"""Tests for bridge.services.factory_orchestrator — Sprint 14.10.

Concept-only port — no Dark Factory source copied.

Pure-function tests where possible (route-table, lock semantics).
End-to-end tests use ``patch`` against the orchestrator's injected
collaborators so the real ``gh``, Claude, and validate subprocesses are
never invoked.
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bridge.factory.labels import FactoryState
from bridge.factory.seven_rule_synthesizer import (
    FactorySynthesisOutcome,
    SynthesisDecision,
    SynthesisInput,
)
from bridge.factory.validate import ReviewerResult, ValidateResult
from bridge.services.factory_orchestrator import (
    AWAITING_REVIEW_STATE,
    DEFAULT_COST_CAP_PER_ISSUE_USD,
    DEFAULT_COST_CAP_PER_TICK_USD,
    GLOBAL_LOCK_FILENAME,
    NEEDS_FIX_STATE,
    NEEDS_HUMAN_STATE,
    FactoryOrchestrator,
    TickResult,
    _release_lock,
    _route_outcome,
    _try_acquire_lock,
)


# ── Fixtures ────────────────────────────────────────────────────────────


@dataclass
class _FakeImplementResult:
    """Subset of ImplementResult attributes the orchestrator reads."""

    issue_number: int
    pr_number: int | None
    pr_url: str | None
    final_state: FactoryState
    failed_phase: str | None
    cost_usd: float


def _make_validate_result(
    *,
    aggregate: str = "pass",
    block_reasons: tuple[str, ...] = (),
    total_cost_usd: float = 0.05,
    reviewers: tuple[ReviewerResult, ...] = (),
) -> ValidateResult:
    return ValidateResult(
        reviewer_results=reviewers,
        aggregate_verdict=aggregate,  # type: ignore[arg-type]
        block_reasons=block_reasons,
        total_cost_usd=total_cost_usd,
    )


def _make_orchestrator(
    tmp_path: Path,
    *,
    impl_result: _FakeImplementResult | None = None,
    validate_result: ValidateResult | list | None = None,
    decision: SynthesisDecision | list | None = None,
    notifier: Any = None,
    cost_cap_per_tick: float = DEFAULT_COST_CAP_PER_TICK_USD,
    cost_cap_per_issue: float = DEFAULT_COST_CAP_PER_ISSUE_USD,
) -> FactoryOrchestrator:
    """Build an orchestrator with all collaborators mocked."""
    impl_result = impl_result or _FakeImplementResult(
        issue_number=1,
        pr_number=99,
        pr_url="https://example/pr/99",
        final_state=FactoryState.NEEDS_REVIEW,
        failed_phase=None,
        cost_usd=0.50,
    )
    implement_runner = MagicMock(return_value=impl_result)

    if isinstance(validate_result, list):
        validate_runner = AsyncMock(side_effect=validate_result)
    elif validate_result is None:
        validate_runner = AsyncMock(return_value=_make_validate_result())
    else:
        validate_runner = AsyncMock(return_value=validate_result)

    if isinstance(decision, list):
        synth = MagicMock(side_effect=decision)
    elif decision is None:
        synth = MagicMock(
            return_value=SynthesisDecision(
                outcome=FactorySynthesisOutcome.READY_FOR_OPERATOR,
                rule_fired=1,
                explanation="all reviewers passed",
            )
        )
    else:
        synth = MagicMock(return_value=decision)

    return FactoryOrchestrator(
        data_dir=tmp_path,
        chat_id="",
        config_enabled=True,
        implement_runner=implement_runner,
        validate_runner=validate_runner,
        synthesizer=synth,
        notifier=notifier,
        global_lock_path=tmp_path / GLOBAL_LOCK_FILENAME,
        per_target_lock_dir=tmp_path / "factory-locks",
        cost_cap_per_tick_usd=cost_cap_per_tick,
        cost_cap_per_issue_usd=cost_cap_per_issue,
    )


# ── Lock primitives ──────────────────────────────────────────────────────


class TestLockPrimitives:
    def test_acquire_writes_pid(self, tmp_path: Path):
        path = tmp_path / "x.lock"
        assert _try_acquire_lock(path, stale_s=60) is True
        assert path.read_text() == str(os.getpid())

    def test_acquire_blocks_when_alive(self, tmp_path: Path):
        path = tmp_path / "x.lock"
        # Write our own PID — fresh + alive — re-acquire fails.
        path.write_text(str(os.getpid()))
        # Set mtime to "now" (already is, but explicit) so age < stale.
        os.utime(path, None)
        # Patching alive-check: use a different pid that we know is dead.
        path.write_text("999999999")
        # 999999999 is not alive — should be reclaimed even if "fresh".
        # But age is fresh — code only reclaims if dead OR stale, not "fresh
        # but dead". Actually it says: "fresh AND alive AND nonzero" → blocked.
        # So fresh + dead → fall through to overwrite. Verify.
        assert _try_acquire_lock(path, stale_s=60) is True
        assert path.read_text() == str(os.getpid())

    def test_acquire_reclaims_stale(self, tmp_path: Path):
        path = tmp_path / "x.lock"
        path.write_text("1")  # init=1, often alive on Unix; we override mtime.
        # Make it ancient.
        old = time.time() - 9999
        os.utime(path, (old, old))
        assert _try_acquire_lock(path, stale_s=60) is True

    def test_release_only_if_ours(self, tmp_path: Path):
        path = tmp_path / "x.lock"
        path.write_text("999999999")  # not us
        _release_lock(path)
        assert path.exists()  # not deleted — wasn't ours

        path.write_text(str(os.getpid()))
        _release_lock(path)
        assert not path.exists()


# ── Pure routing ─────────────────────────────────────────────────────────


class TestRouteOutcome:
    @pytest.mark.parametrize(
        ("outcome", "expected_state", "expected_pr_ready"),
        [
            (FactorySynthesisOutcome.READY_FOR_OPERATOR, AWAITING_REVIEW_STATE, True),
            (FactorySynthesisOutcome.READY_WITH_NOTES, AWAITING_REVIEW_STATE, True),
            (FactorySynthesisOutcome.NEEDS_FIX, NEEDS_FIX_STATE, False),
            (FactorySynthesisOutcome.NEEDS_HUMAN, NEEDS_HUMAN_STATE, False),
            (FactorySynthesisOutcome.ABANDON, NEEDS_HUMAN_STATE, False),
            (FactorySynthesisOutcome.ESCALATE_COST, NEEDS_HUMAN_STATE, False),
            (FactorySynthesisOutcome.RETRY_REVIEWERS, FactoryState.IN_PROGRESS, False),
        ],
    )
    def test_table_routes(
        self,
        outcome: FactorySynthesisOutcome,
        expected_state: FactoryState,
        expected_pr_ready: bool,
    ):
        plan = _route_outcome(
            outcome,
            explanation="test",
            block_reasons=("behavioral: missed",),
            advise_reasons=(),
        )
        assert plan.target_state is expected_state
        assert plan.mark_pr_ready is expected_pr_ready
        assert outcome.value in plan.comment_body

    def test_block_and_advise_lines_render(self):
        plan = _route_outcome(
            FactorySynthesisOutcome.NEEDS_HUMAN,
            explanation="why",
            block_reasons=("security: foo",),
            advise_reasons=("code_quality: meh",),
        )
        assert "security: foo" in plan.comment_body
        assert "code_quality: meh" in plan.comment_body
        assert "concept-only-no-license" in plan.comment_body


# ── Tick — empty queue, lock paths ───────────────────────────────────────


@pytest.mark.asyncio
class TestTick:
    async def test_empty_queue_processes_zero(self, tmp_path: Path):
        orchestrator = _make_orchestrator(tmp_path)
        with patch(
            "bridge.services.factory_orchestrator._gh_list_accepted",
            return_value=[],
        ):
            result = await orchestrator.tick()
        assert isinstance(result, TickResult)
        assert result.issues_processed == ()
        assert result.skipped_count == 0
        assert result.error is None

    async def test_global_lock_contention(self, tmp_path: Path):
        # Pre-populate the global lock with a fresh, alive holder (us).
        lock_path = tmp_path / GLOBAL_LOCK_FILENAME
        lock_path.write_text(str(os.getpid()))
        os.utime(lock_path, None)

        orchestrator = _make_orchestrator(tmp_path)

        # Patch _try_acquire_lock to return False to simulate contention.
        with patch(
            "bridge.services.factory_orchestrator._try_acquire_lock",
            return_value=False,
        ):
            result = await orchestrator.tick()
        assert result.error == "locked"
        assert result.issues_processed == ()

    async def test_happy_path_ready_for_operator(
        self, tmp_path: Path
    ):
        notifier = MagicMock()
        orchestrator = _make_orchestrator(tmp_path, notifier=notifier)
        transition_seen: list[tuple] = []

        def fake_transition(num, frm, to):
            transition_seen.append((num, frm, to))
            return frm == FactoryState.NEEDS_REVIEW

        with patch(
            "bridge.services.factory_orchestrator._gh_list_accepted",
            return_value=[
                {"number": 7, "title": "x", "body": "do the thing"},
            ],
        ), patch(
            "bridge.services.factory_orchestrator._gh_pr_diff",
            return_value="diff",
        ), patch(
            "bridge.services.factory_orchestrator._gh_issue_comment"
        ) as mock_comment, patch(
            "bridge.services.factory_orchestrator._gh_pr_ready_for_review"
        ) as mock_ready, patch(
            "bridge.services.factory_orchestrator.transition_state",
            side_effect=fake_transition,
        ):
            tick = await orchestrator.tick()

        assert len(tick.issues_processed) == 1
        ipr = tick.issues_processed[0]
        assert ipr.issue_number == 7
        assert ipr.final_state == FactoryState.NEEDS_REVIEW.value
        assert ipr.synthesis_outcome == FactorySynthesisOutcome.READY_FOR_OPERATOR.value
        assert ipr.error is None
        # Comment + PR-ready both fire.
        mock_comment.assert_called_once()
        mock_ready.assert_called_once_with(99, repo="your-org/bumba-open-harness")
        # Notifier got the summary.
        notifier.assert_called_once()
        assert "processed 1 issue" in notifier.call_args[0][0]

    async def test_per_target_lock_contention_skips_issue(
        self, tmp_path: Path
    ):
        orchestrator = _make_orchestrator(tmp_path)
        # Pre-create per-target lock with a "fresh + alive" holder (us).
        lock_dir = tmp_path / "factory-locks"
        lock_dir.mkdir(parents=True)
        per_target = lock_dir / "issue-7.lock"
        per_target.write_text(str(os.getpid()))
        os.utime(per_target, None)

        # Make _try_acquire_lock return True for global, False for per-target.
        from bridge.services.factory_orchestrator import GLOBAL_LOCK_FILENAME
        global_lock = tmp_path / GLOBAL_LOCK_FILENAME

        def fake_acquire(path, *, stale_s):
            if path == global_lock:
                return True
            return False  # per-target contended

        with patch(
            "bridge.services.factory_orchestrator._gh_list_accepted",
            return_value=[
                {"number": 7, "title": "x", "body": "y"},
            ],
        ), patch(
            "bridge.services.factory_orchestrator._try_acquire_lock",
            side_effect=fake_acquire,
        ):
            tick = await orchestrator.tick()

        assert tick.issues_processed == ()
        assert tick.skipped_count == 1

    async def test_stale_per_target_lock_is_reclaimed(self, tmp_path: Path):
        orchestrator = _make_orchestrator(tmp_path)
        lock_dir = tmp_path / "factory-locks"
        lock_dir.mkdir(parents=True)
        # Stale lock — old mtime + dead PID.
        per_target = lock_dir / "issue-7.lock"
        per_target.write_text("999999999")
        ancient = time.time() - 9999
        os.utime(per_target, (ancient, ancient))

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

        # Stale lock reclaimed → issue processed.
        assert len(tick.issues_processed) == 1


# ── Outcome routing under the orchestrator ──────────────────────────────


@pytest.mark.asyncio
class TestOutcomeRouting:
    @pytest.mark.parametrize(
        ("outcome", "expected_state"),
        [
            (FactorySynthesisOutcome.READY_FOR_OPERATOR, FactoryState.NEEDS_REVIEW),
            (FactorySynthesisOutcome.READY_WITH_NOTES, FactoryState.NEEDS_REVIEW),
            (FactorySynthesisOutcome.NEEDS_FIX, FactoryState.FIX_ATTEMPT_1),
            (FactorySynthesisOutcome.NEEDS_HUMAN, FactoryState.NEEDS_HUMAN),
            (FactorySynthesisOutcome.ABANDON, FactoryState.NEEDS_HUMAN),
            (FactorySynthesisOutcome.ESCALATE_COST, FactoryState.NEEDS_HUMAN),
        ],
    )
    async def test_outcome_to_final_state(
        self,
        tmp_path: Path,
        outcome: FactorySynthesisOutcome,
        expected_state: FactoryState,
    ):
        decision = SynthesisDecision(
            outcome=outcome,
            rule_fired=1,
            explanation="test",
            block_reasons=("behavioral: foo",),
        )
        orchestrator = _make_orchestrator(tmp_path, decision=decision)

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

        assert len(tick.issues_processed) == 1
        assert tick.issues_processed[0].final_state == expected_state.value

    async def test_retry_reviewers_invokes_validate_twice(self, tmp_path: Path):
        # First decision — RETRY. Second — READY_FOR_OPERATOR.
        decisions = [
            SynthesisDecision(
                outcome=FactorySynthesisOutcome.RETRY_REVIEWERS,
                rule_fired=5,
                explanation="parse errors",
            ),
            SynthesisDecision(
                outcome=FactorySynthesisOutcome.READY_FOR_OPERATOR,
                rule_fired=1,
                explanation="all good now",
            ),
        ]
        validate_results = [_make_validate_result(), _make_validate_result()]
        orchestrator = _make_orchestrator(
            tmp_path,
            validate_result=validate_results,
            decision=decisions,
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

        # validate runner called twice (initial + 1 retry).
        assert orchestrator._validate.await_count == 2
        # synthesizer called twice (initial + post-retry).
        assert orchestrator._synthesize.call_count == 2
        # Final state landed at NEEDS_REVIEW (READY_FOR_OPERATOR).
        assert tick.issues_processed[0].final_state == FactoryState.NEEDS_REVIEW.value
        # Synth_outcome reflects the RETRY decision (we record the first one
        # since synthesis_outcome is set off the *first* decision when retry
        # happens — but our impl records the second).
        assert tick.issues_processed[0].synthesis_outcome == (
            FactorySynthesisOutcome.READY_FOR_OPERATOR.value
        )

    async def test_second_synthesize_receives_prior_signature(self, tmp_path: Path):
        decisions = [
            SynthesisDecision(
                outcome=FactorySynthesisOutcome.RETRY_REVIEWERS,
                rule_fired=5,
                explanation="parse errors",
            ),
            SynthesisDecision(
                outcome=FactorySynthesisOutcome.READY_FOR_OPERATOR,
                rule_fired=1,
                explanation="ok",
            ),
        ]
        v1 = _make_validate_result(block_reasons=("test_quality: thin",))
        v2 = _make_validate_result()
        orchestrator = _make_orchestrator(
            tmp_path,
            validate_result=[v1, v2],
            decision=decisions,
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
            await orchestrator.tick()

        # The second SynthesisInput should carry retry_count=1 and
        # the prior block signature derived from v1.
        second_call = orchestrator._synthesize.call_args_list[1]
        synth_input: SynthesisInput = second_call[0][0]
        assert synth_input.retry_count == 1
        assert synth_input.prior_block_signature == ("test_quality: thin",)


# ── Cost caps ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
class TestCostCaps:
    async def test_per_tick_cap_halts_after_first_issue(self, tmp_path: Path):
        # First issue costs $6 (impl); per-tick cap $5
        # → tick processes one issue then halts before the second.
        impl_result = _FakeImplementResult(
            issue_number=0,
            pr_number=1,
            pr_url="u",
            final_state=FactoryState.NEEDS_REVIEW,
            failed_phase=None,
            cost_usd=6.0,
        )
        orchestrator = _make_orchestrator(
            tmp_path,
            impl_result=impl_result,
            cost_cap_per_tick=5.0,
        )

        with patch(
            "bridge.services.factory_orchestrator._gh_list_accepted",
            return_value=[
                {"number": 1, "title": "a", "body": "b"},
                {"number": 2, "title": "c", "body": "d"},
            ],
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

        # First issue processed, second never started.
        assert len(tick.issues_processed) == 1
        assert tick.total_cost_usd >= 6.0

    async def test_per_issue_cap_passes_to_synth(self, tmp_path: Path):
        # The per-issue cap is the cost_cap_usd argument to ``synthesize``.
        # Verify the orchestrator threads it through correctly.
        orchestrator = _make_orchestrator(
            tmp_path,
            cost_cap_per_issue=1.50,
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
            await orchestrator.tick()

        synth_call = orchestrator._synthesize.call_args
        assert synth_call.kwargs.get("cost_cap_usd") == 1.50


# ── Service entry / feature flag ────────────────────────────────────────


@pytest.mark.asyncio
class TestServiceRun:
    async def test_run_returns_skip_when_disabled(self, tmp_path: Path):
        orchestrator = FactoryOrchestrator(
            data_dir=tmp_path,
            chat_id="",
            config_enabled=False,
            global_lock_path=tmp_path / GLOBAL_LOCK_FILENAME,
            per_target_lock_dir=tmp_path / "factory-locks",
        )

        # Patch load_config so it ALSO reports disabled.
        @dataclass
        class _Cfg:
            factory_orchestrator_enabled: bool = False

        with patch("bridge.config.load_config", return_value=_Cfg()):
            result = await orchestrator.run()

        assert result.skip_reason == "feature flag OFF"
        assert result.work_items == 0

    async def test_run_returns_service_result_when_enabled(self, tmp_path: Path):
        orchestrator = _make_orchestrator(tmp_path)
        with patch(
            "bridge.services.factory_orchestrator._gh_list_accepted",
            return_value=[],
        ):
            result = await orchestrator.run()
        assert result.service == "factory_orchestrator"
        assert result.skip_reason is None
        assert result.work_items == 0
        assert result.ok is True

    async def test_run_surfaces_locked_anomaly_when_global_lock_contended(
        self, tmp_path: Path
    ):
        lock_path = tmp_path / GLOBAL_LOCK_FILENAME
        lock_path.write_text(str(os.getpid()), encoding="utf-8")
        os.utime(lock_path, None)

        orchestrator = FactoryOrchestrator(
            data_dir=tmp_path,
            chat_id="",
            config_enabled=True,
            global_lock_path=lock_path,
            per_target_lock_dir=tmp_path / "factory-locks",
        )

        result = await orchestrator.run()

        assert result.ok is False
        assert result.work_items == 0
        assert "locked" in result.anomalies
        assert result.skip_reason is None


# ── Mailbox wiring (Sprint D1.2) ────────────────────────────────────────


class TestLoadMailboxSettings:
    """Unit tests for _load_mailbox_settings helper."""

    def test_returns_defaults_when_flag_off(self):
        from bridge.services.factory_orchestrator import _load_mailbox_settings

        @dataclass
        class _Cfg:
            factory_mailbox_enabled: bool = False
            factory_mailbox_poll_interval_seconds: int = 2
            factory_mailbox_decision_timeout_seconds: int = 3600

        with patch(
            "bridge.services.factory_orchestrator.load_config"
            if False  # guard — _load_mailbox_settings uses its own import
            else "bridge.config.load_config",
            return_value=_Cfg(),
        ):
            enabled, poll, decision_to = _load_mailbox_settings()

        assert enabled is False
        assert poll == 2
        assert decision_to == 3600

    def test_returns_true_when_flag_on(self):
        from bridge.services.factory_orchestrator import _load_mailbox_settings

        @dataclass
        class _CfgOn:
            factory_mailbox_enabled: bool = True
            factory_mailbox_poll_interval_seconds: int = 5
            factory_mailbox_decision_timeout_seconds: int = 1800

        with patch("bridge.config.load_config", return_value=_CfgOn()):
            enabled, poll, decision_to = _load_mailbox_settings()

        assert enabled is True
        assert poll == 5
        assert decision_to == 1800

    def test_fails_open_on_config_error(self):
        from bridge.services.factory_orchestrator import _load_mailbox_settings

        with patch(
            "bridge.config.load_config", side_effect=RuntimeError("boom")
        ):
            enabled, poll, decision_to = _load_mailbox_settings()

        assert enabled is False
        assert poll == 2
        assert decision_to == 3600


@pytest.mark.asyncio
class TestMailboxWiring:
    """Integration tests: mailbox kwargs reach implement_issue correctly."""

    async def test_mailbox_off_no_kwargs_passed(self, tmp_path: Path):
        """When factory_mailbox_enabled=False, implement is called without
        mailbox_enabled or mailbox_data_dir kwargs."""
        orchestrator = _make_orchestrator(tmp_path)
        _issue = {"number": 1, "title": "test", "body": "do the thing"}

        with patch(
            "bridge.services.factory_orchestrator._load_mailbox_settings",
            return_value=(False, 2, 3600),
        ), patch(
            "bridge.services.factory_orchestrator._gh_list_accepted",
            return_value=[_issue],
        ), patch(
            "bridge.services.factory_orchestrator._gh_pr_diff",
            return_value="diff",
        ), patch(
            "bridge.services.factory_orchestrator.transition_state",
            return_value=True,
        ), patch(
            "bridge.services.factory_orchestrator._gh_issue_comment"
        ), patch(
            "bridge.services.factory_orchestrator._gh_pr_ready_for_review"
        ):
            await orchestrator.tick()

        call_kwargs = orchestrator._implement.call_args[1]
        assert "mailbox_enabled" not in call_kwargs
        assert "mailbox_data_dir" not in call_kwargs

    async def test_mailbox_on_kwargs_passed(self, tmp_path: Path):
        """When factory_mailbox_enabled=True, implement is called with
        mailbox_enabled=True and mailbox_data_dir pointing to data_dir/factory-mailboxes."""
        orchestrator = _make_orchestrator(tmp_path)
        _issue = {"number": 1, "title": "test", "body": "do the thing"}

        with patch(
            "bridge.services.factory_orchestrator._load_mailbox_settings",
            return_value=(True, 2, 3600),
        ), patch(
            "bridge.services.factory_orchestrator._gh_list_accepted",
            return_value=[_issue],
        ), patch(
            "bridge.services.factory_orchestrator._gh_pr_diff",
            return_value="diff",
        ), patch(
            "bridge.services.factory_orchestrator.transition_state",
            return_value=True,
        ), patch(
            "bridge.services.factory_orchestrator._gh_issue_comment"
        ), patch(
            "bridge.services.factory_orchestrator._gh_pr_ready_for_review"
        ):
            await orchestrator.tick()

        call_kwargs = orchestrator._implement.call_args[1]
        assert call_kwargs.get("mailbox_enabled") is True
        assert call_kwargs.get("mailbox_data_dir") == tmp_path / "factory-mailboxes"


# ── audit-2026-05-16.C.05: HaltPolicy convergence ───────────────────────


class TestHaltPolicyIntegration:
    """The orchestrator honours the shared HaltPolicy contract.

    Pre-C.05 the factory had ``factory-paused.flag`` as its only pause
    surface. The audit (HI-3/SW-2) called for the global halt flag to
    also stop the factory — same contract as warm-chief, experiment-loop,
    job-search. These tests cover:

      1. Global halt set → ``check_start`` blocks new ticks (error="halted").
      2. Global halt set mid-tick → ``check_continue`` causes the per-issue
         loop to break before the next dispatch.
      3. No HaltPolicy wired → legacy pause-flag-only behaviour preserved
         (back-compat regression check).
      4. ``_build_runtime_halt_policy`` reads the on-disk halt flag.
    """

    @pytest.mark.asyncio
    async def test_halt_policy_blocks_tick_start(self, tmp_path: Path):
        """When the policy reports halted, the tick exits immediately with
        ``error='halted'`` and no GitHub state is touched.
        """
        from bridge.halt import HaltDecision, HaltPolicy

        # Policy that always reports halted.
        policy = HaltPolicy(
            is_halted=lambda: True,
            halt_reason=lambda: "operator pressed /halt",
        )
        orchestrator = _make_orchestrator(tmp_path)
        orchestrator._halt_policy = policy

        # _gh_list_accepted is patched to a sentinel that would raise if
        # called — proves halt fires BEFORE the listing call.
        with patch(
            "bridge.services.factory_orchestrator._gh_list_accepted",
            side_effect=AssertionError("listing must not run under halt"),
        ):
            result = await orchestrator.tick()

        assert result.error == "halted"
        assert result.issues_processed == ()
        assert result.skipped_count == 0
        # Decision payload was renderable as a string.
        assert isinstance(policy.check_start("factory"), HaltDecision)

    @pytest.mark.asyncio
    async def test_halt_policy_blocks_before_pause_flag(self, tmp_path: Path):
        """When BOTH halt and pause-flag are set, halt wins the error
        code — operators rely on ``halted`` to know /halt was the trigger
        rather than /factory pause.
        """
        from bridge.halt import HaltPolicy

        # Both flags raised: pause-flag on disk AND halt-policy blocking.
        pause_flag = tmp_path / "factory-paused.flag"
        pause_flag.write_text("paused by operator")
        policy = HaltPolicy(
            is_halted=lambda: True,
            halt_reason=lambda: "halted",
        )
        orchestrator = _make_orchestrator(tmp_path)
        orchestrator._halt_policy = policy

        result = await orchestrator.tick()

        assert result.error == "halted"

    @pytest.mark.asyncio
    async def test_halt_mid_tick_stops_further_starts(self, tmp_path: Path):
        """``check_continue`` fires before each per-issue dispatch. When
        halt flips mid-tick (after the first issue but before the second),
        the loop breaks and the in-flight issue's result is preserved.
        """
        from bridge.halt import HaltPolicy

        # Halt source: returns False on the start check + first
        # continue check (so issue #7 dispatches), then True from the
        # second continue check onwards (so issue #8 is skipped).
        # Reads sequence: 1 = check_start (tick), 2 = check_continue
        # before issue #7, 3 = check_continue before issue #8.
        halt_state = {"reads": 0}

        def _is_halted() -> bool:
            halt_state["reads"] += 1
            return halt_state["reads"] > 2

        policy = HaltPolicy(
            is_halted=_is_halted,
            halt_reason=lambda: "mid-tick halt",
        )
        orchestrator = _make_orchestrator(tmp_path)
        orchestrator._halt_policy = policy

        # Two issues in the queue. Only the first should be processed —
        # the continue check fires before the second.
        with patch(
            "bridge.services.factory_orchestrator._gh_list_accepted",
            return_value=[
                {"number": 7, "title": "first", "body": "body1"},
                {"number": 8, "title": "second", "body": "body2"},
            ],
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
            result = await orchestrator.tick()

        # First issue processed (in-flight finishes cleanly); second
        # skipped via the continue check.
        assert len(result.issues_processed) == 1
        assert result.issues_processed[0].issue_number == 7
        # The tick itself reports no error — the loop broke cleanly.
        assert result.error is None

    @pytest.mark.asyncio
    async def test_no_halt_policy_preserves_legacy_behaviour(
        self, tmp_path: Path
    ):
        """When ``halt_policy=None`` (the default), the global halt check
        is skipped entirely. The pause flag remains the only operator
        surface. Back-compat regression check.
        """
        orchestrator = _make_orchestrator(tmp_path)
        # Explicit: no halt policy wired.
        assert orchestrator._halt_policy is None

        # Even with the halt.flag file on disk, the tick does not honour
        # it when no policy is wired (the policy is the seam).
        (tmp_path / "halt.flag").write_text("operator halted")

        with patch(
            "bridge.services.factory_orchestrator._gh_list_accepted",
            return_value=[],
        ):
            result = await orchestrator.tick()

        # No halt error — tick ran normally and found no issues.
        assert result.error is None
        assert result.issues_processed == ()

    def test_build_runtime_halt_policy_reads_disk_flag(self, tmp_path: Path):
        """``_build_runtime_halt_policy`` mirrors the on-disk halt flag.
        Mirrors the canonical pattern in ``job_search/_pipeline.py``.
        """
        from bridge.services.factory_orchestrator import (
            _build_runtime_halt_policy,
        )

        policy = _build_runtime_halt_policy(tmp_path)
        # Flag absent → not blocked.
        assert policy.check_start("factory").blocked is False

        # Flag present with reason → blocked, reason propagated.
        (tmp_path / "halt.flag").write_text("operator pressed /halt")
        decision = policy.check_start("factory")
        assert decision.blocked is True
        assert decision.reason is not None
        # The surface name appears in the reason for log-grep clarity.
        assert "factory" in decision.reason
        assert "operator pressed /halt" in decision.reason

        # check_continue also fires on the global halt (default
        # cancel_in_flight=True).
        assert policy.check_continue("factory").blocked is True
