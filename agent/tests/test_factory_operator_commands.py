"""Tests for bridge.factory.operator_commands — Sprint 14.11 (issue #1049).

Concept-only port — no Dark Factory source copied. Verifies:

  * pause/resume flag-file mechanics (existence, atomicity, idempotency),
  * ``collect_status`` happy + degraded paths,
  * ``escalate_issue`` calls transition + comment seams and surfaces metadata,
  * Discord rendering covers every status field,
  * orchestrator + soak-harness pause-flag short-circuit,
  * ``/factory`` operator subcommands route to the right helpers.

The factory orchestrator and soak-harness pause-flag tests live alongside
their respective sibling tests' style — collaborators are mocked, the
flag file is the only side effect we exercise.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio

from bridge.commands import CommandHandler
from bridge.factory import operator_commands as ops
from bridge.factory.labels import FactoryState
from bridge.factory.operator_commands import (
    FactoryStatus,
    collect_status,
    escalate_issue,
    format_status_for_discord,
    is_paused,
    pause,
    read_pause_meta,
    resume,
)


# ── Pause flag mechanics ────────────────────────────────────────────────


class TestPauseFlagMechanics:
    def test_is_paused_false_when_absent(self, tmp_path: Path):
        flag = tmp_path / "factory-paused.flag"
        assert is_paused(flag) is False

    def test_pause_creates_flag_with_metadata(self, tmp_path: Path):
        flag = tmp_path / "factory-paused.flag"
        pause(flag, by="operator", reason="lock held for 3h")
        assert flag.exists()
        meta = read_pause_meta(flag)
        assert meta["by"] == "operator"
        assert meta["reason"] == "lock held for 3h"
        assert "paused_at_iso" in meta
        # ISO timestamp parses cleanly.
        from datetime import datetime
        datetime.fromisoformat(meta["paused_at_iso"])

    def test_is_paused_true_after_pause(self, tmp_path: Path):
        flag = tmp_path / "factory-paused.flag"
        pause(flag)
        assert is_paused(flag) is True

    def test_pause_uses_tempfile_then_rename(self, tmp_path: Path):
        # Atomicity check — after pause, only the flag exists in tmp_path.
        flag = tmp_path / "factory-paused.flag"
        pause(flag, reason="atomic")
        siblings = sorted(p.name for p in tmp_path.iterdir())
        # No leftover .tmp files; just the flag.
        assert siblings == ["factory-paused.flag"]
        # Body parses as JSON cleanly — no half-written content.
        body = flag.read_text(encoding="utf-8")
        json.loads(body)

    def test_resume_returns_true_when_present(self, tmp_path: Path):
        flag = tmp_path / "factory-paused.flag"
        pause(flag)
        assert resume(flag) is True
        assert not flag.exists()

    def test_resume_returns_false_when_absent(self, tmp_path: Path):
        flag = tmp_path / "factory-paused.flag"
        assert resume(flag) is False

    def test_pause_overwrites_existing_metadata(self, tmp_path: Path):
        flag = tmp_path / "factory-paused.flag"
        pause(flag, by="op1", reason="r1")
        pause(flag, by="op2", reason="r2")
        meta = read_pause_meta(flag)
        assert meta["by"] == "op2"
        assert meta["reason"] == "r2"

    def test_read_pause_meta_returns_empty_when_absent(self, tmp_path: Path):
        assert read_pause_meta(tmp_path / "missing.flag") == {}

    def test_read_pause_meta_returns_empty_on_corrupt_body(self, tmp_path: Path):
        flag = tmp_path / "factory-paused.flag"
        flag.write_text("not json", encoding="utf-8")
        # is_paused still True (file existence is the signal).
        assert is_paused(flag) is True
        # But meta gracefully degrades.
        assert read_pause_meta(flag) == {}


# ── collect_status ──────────────────────────────────────────────────────


class _FakeCostTracker:
    """Duck-typed stand-in for bridge.cost_tracker.CostTracker."""

    def __init__(self, daily: float = 0.0, weekly: float = 0.0):
        self._daily = daily
        self._weekly = weekly

    def get_daily_summary(self) -> dict:
        return {"date": "2026-05-01", "total_cost": self._daily, "request_count": 3}

    def get_weekly_summary(self) -> dict:
        return {"total_cost": self._weekly, "request_count": 9}


class TestCollectStatus:
    def test_happy_path_assembles_all_fields(self, tmp_path: Path):
        # Arrange — populate every source.
        flag_path = tmp_path / "factory-paused.flag"  # absent
        soak_log_dir = tmp_path / "factory-soak"
        soak_log_dir.mkdir()
        # Synthetic soak entry for today so _count_processed_from_soak finds it.
        from datetime import datetime, timezone
        today = datetime.now(timezone.utc).date().isoformat()
        (soak_log_dir / f"soak-{today}.jsonl").write_text(
            json.dumps({"issue_number": 1}) + "\n", encoding="utf-8"
        )
        # last_run.json
        srvc_dir = tmp_path / "service_state"
        srvc_dir.mkdir()
        (srvc_dir / "last_run.json").write_text(
            json.dumps(
                {
                    "factory_orchestrator": {
                        "ts": "2026-05-01T12:00:00+00:00",
                        "cost_usd": 0.42,
                    }
                }
            ),
            encoding="utf-8",
        )

        # Stub the gh-count helpers.
        with patch(
            "bridge.factory.operator_commands._run_gh_count_accepted",
            return_value=7,
        ), patch(
            "bridge.factory.operator_commands._run_gh_count_in_flight",
            return_value=2,
        ), patch(
            "bridge.factory.operator_commands._read_soak_status",
            return_value=(True, "verified=5"),
        ):
            status = collect_status(
                orchestrator_enabled=True,
                log_dir=tmp_path,
                soak_log_dir=soak_log_dir,
                flag_path=flag_path,
                cost_tracker=_FakeCostTracker(daily=1.23, weekly=4.56),
            )

        assert isinstance(status, FactoryStatus)
        assert status.orchestrator_enabled is True
        assert status.paused is False
        assert status.last_tick_at_iso == "2026-05-01T12:00:00+00:00"
        assert status.last_tick_cost_usd == pytest.approx(0.42)
        assert status.issues_processed_today == 1
        assert status.issues_processed_this_week == 1
        assert status.total_cost_today_usd == pytest.approx(1.23)
        assert status.total_cost_this_week_usd == pytest.approx(4.56)
        assert status.pending_accepted_count == 7
        assert status.in_flight_count == 2
        assert status.soak_ready_to_enable is True
        assert status.soak_ready_reason == "verified=5"

    def test_defensive_zeros_when_everything_missing(self, tmp_path: Path):
        # No log_dir, no soak_log_dir, no cost_tracker, no gh — everything zero.
        with patch(
            "bridge.factory.operator_commands._run_gh_count_accepted",
            return_value=0,
        ), patch(
            "bridge.factory.operator_commands._run_gh_count_in_flight",
            return_value=0,
        ):
            status = collect_status(
                orchestrator_enabled=False,
                log_dir=None,
                soak_log_dir=None,
                flag_path=tmp_path / "missing.flag",
                cost_tracker=None,
            )
        assert status.orchestrator_enabled is False
        assert status.paused is False
        assert status.last_tick_at_iso is None
        assert status.last_tick_cost_usd == 0.0
        assert status.issues_processed_today == 0
        assert status.issues_processed_this_week == 0
        assert status.total_cost_today_usd == 0.0
        assert status.total_cost_this_week_usd == 0.0
        assert status.pending_accepted_count == 0
        assert status.in_flight_count == 0
        assert status.soak_ready_to_enable is False
        assert "soak directory not configured" in status.soak_ready_reason

    def test_paused_status_includes_metadata(self, tmp_path: Path):
        flag_path = tmp_path / "factory-paused.flag"
        pause(flag_path, by="operator", reason="freeze")
        with patch(
            "bridge.factory.operator_commands._run_gh_count_accepted",
            return_value=0,
        ), patch(
            "bridge.factory.operator_commands._run_gh_count_in_flight",
            return_value=0,
        ):
            status = collect_status(
                orchestrator_enabled=True,
                log_dir=None,
                soak_log_dir=None,
                flag_path=flag_path,
                cost_tracker=None,
            )
        assert status.paused is True
        assert status.paused_meta["by"] == "operator"
        assert status.paused_meta["reason"] == "freeze"

    def test_cost_tracker_failure_degrades_to_zero(self, tmp_path: Path):
        broken = MagicMock()
        broken.get_daily_summary.side_effect = RuntimeError("boom")
        broken.get_weekly_summary.side_effect = RuntimeError("boom")
        with patch(
            "bridge.factory.operator_commands._run_gh_count_accepted",
            return_value=0,
        ), patch(
            "bridge.factory.operator_commands._run_gh_count_in_flight",
            return_value=0,
        ):
            status = collect_status(
                orchestrator_enabled=False,
                log_dir=None,
                soak_log_dir=None,
                flag_path=tmp_path / "missing.flag",
                cost_tracker=broken,
            )
        assert status.total_cost_today_usd == 0.0
        assert status.total_cost_this_week_usd == 0.0


# ── escalate_issue ──────────────────────────────────────────────────────


class TestEscalateIssue:
    def test_calls_transition_and_comment(self, tmp_path: Path):
        transition = MagicMock(return_value=True)
        comment = MagicMock(return_value=True)
        with patch(
            "bridge.factory.operator_commands.get_state",
            return_value=FactoryState.IN_PROGRESS,
        ):
            outcome = escalate_issue(
                1234,
                reason="lock held 3h",
                actor="operator",
                transition_fn=transition,
                comment_fn=comment,
            )
        transition.assert_called_once_with(
            1234, FactoryState.IN_PROGRESS, FactoryState.NEEDS_HUMAN
        )
        comment.assert_called_once()
        body = comment.call_args.kwargs["body"]
        assert "operator" in body
        assert "lock held 3h" in body
        assert outcome["issue_number"] == 1234
        assert outcome["prior_state"] == FactoryState.IN_PROGRESS.value
        assert outcome["new_state"] == FactoryState.NEEDS_HUMAN.value
        assert outcome["transitioned"] is True
        assert outcome["comment_posted"] is True

    def test_handles_no_prior_state(self, tmp_path: Path):
        transition = MagicMock(return_value=True)
        comment = MagicMock(return_value=True)
        with patch(
            "bridge.factory.operator_commands.get_state", return_value=None
        ):
            outcome = escalate_issue(
                42,
                reason="manual",
                transition_fn=transition,
                comment_fn=comment,
            )
        transition.assert_called_once_with(
            42, None, FactoryState.NEEDS_HUMAN
        )
        assert outcome["prior_state"] is None
        assert outcome["transitioned"] is True

    def test_swallows_transition_failure(self, tmp_path: Path):
        transition = MagicMock(side_effect=RuntimeError("gh down"))
        comment = MagicMock(return_value=True)
        with patch(
            "bridge.factory.operator_commands.get_state", return_value=None
        ):
            outcome = escalate_issue(
                42,
                reason="manual",
                transition_fn=transition,
                comment_fn=comment,
            )
        # No raise — operator command must not crash on infra failure.
        assert outcome["transitioned"] is False
        assert outcome["comment_posted"] is True


# ── Discord rendering ───────────────────────────────────────────────────


class TestFormatStatusForDiscord:
    def _make_status(self, **overrides: Any) -> FactoryStatus:
        defaults = dict(
            orchestrator_enabled=True,
            paused=False,
            last_tick_at_iso="2026-05-01T12:00:00+00:00",
            last_tick_cost_usd=0.42,
            issues_processed_today=2,
            issues_processed_this_week=14,
            total_cost_today_usd=1.10,
            total_cost_this_week_usd=8.30,
            pending_accepted_count=5,
            in_flight_count=1,
            soak_ready_to_enable=True,
            soak_ready_reason="verified=5 over 14d",
        )
        defaults.update(overrides)
        return FactoryStatus(**defaults)

    def test_renders_all_fields(self):
        status = self._make_status()
        out = format_status_for_discord(status)
        assert "ENABLED" in out
        assert "running" in out  # not paused
        assert "2026-05-01T12:00:00+00:00" in out
        assert "$0.4200" in out  # last-tick cost rendered
        assert "Today: 2 issue(s)" in out
        assert "Last 7 days: 14 issue(s)" in out
        assert "$1.1000" in out  # today cost
        assert "$8.3000" in out  # week cost
        assert "Pending `factory:accepted`: 5" in out
        assert "In-flight: 1" in out
        assert "READY TO ENABLE" in out
        assert "verified=5 over 14d" in out

    def test_paused_renders_metadata_block(self):
        status = self._make_status(
            paused=True,
            paused_meta={
                "by": "operator",
                "reason": "freeze",
                "paused_at_iso": "2026-05-01T13:00:00+00:00",
            },
        )
        out = format_status_for_discord(status)
        assert "PAUSED" in out
        assert "Paused by `operator`" in out
        assert "freeze" in out

    def test_disabled_orchestrator_renders(self):
        status = self._make_status(orchestrator_enabled=False)
        out = format_status_for_discord(status)
        assert "DISABLED" in out

    def test_empty_last_tick_renders_never(self):
        status = self._make_status(last_tick_at_iso=None)
        out = format_status_for_discord(status)
        assert "never" in out


# ── Orchestrator pause-flag short-circuit ───────────────────────────────


@pytest.mark.asyncio
class TestOrchestratorRespectsPauseFlag:
    async def test_tick_returns_paused_error_when_flag_present(
        self, tmp_path: Path
    ):
        # Local import — orchestrator builder uses the same fixture style
        # as test_factory_orchestrator.py.
        from bridge.factory.seven_rule_synthesizer import (
            FactorySynthesisOutcome,
            SynthesisDecision,
        )
        from bridge.factory.validate import ValidateResult
        from bridge.services.factory_orchestrator import (
            GLOBAL_LOCK_FILENAME,
            FactoryOrchestrator,
        )

        # Drop the pause flag in the orchestrator's data_dir.
        pause(tmp_path / "factory-paused.flag", reason="t")

        impl_runner = MagicMock()
        validate_runner = AsyncMock(
            return_value=ValidateResult(
                reviewer_results=(),
                aggregate_verdict="pass",  # type: ignore[arg-type]
                block_reasons=(),
                total_cost_usd=0.0,
            )
        )
        synth = MagicMock(
            return_value=SynthesisDecision(
                outcome=FactorySynthesisOutcome.READY_FOR_OPERATOR,
                rule_fired=1,
                explanation="",
            )
        )

        orchestrator = FactoryOrchestrator(
            data_dir=tmp_path,
            chat_id="",
            config_enabled=True,
            implement_runner=impl_runner,
            validate_runner=validate_runner,
            synthesizer=synth,
            global_lock_path=tmp_path / GLOBAL_LOCK_FILENAME,
            per_target_lock_dir=tmp_path / "factory-locks",
        )

        # Even with `_gh_list_accepted` not stubbed, the tick should bail
        # before any GitHub call.
        with patch(
            "bridge.services.factory_orchestrator._gh_list_accepted",
        ) as mock_list:
            result = await orchestrator.tick()

        assert result.error == "paused"
        assert result.issues_processed == ()
        # Crucially, no GitHub calls fired.
        mock_list.assert_not_called()
        impl_runner.assert_not_called()
        validate_runner.assert_not_called()
        synth.assert_not_called()


# ── Soak-harness pause-flag short-circuit ───────────────────────────────


@pytest.mark.asyncio
class TestSoakHarnessRespectsPauseFlag:
    async def test_shadow_tick_returns_empty_when_paused(self, tmp_path: Path):
        from bridge.factory.soak_harness import SoakHarness

        # data_dir lookup on the orchestrator must resolve to tmp_path so
        # the pause-flag check finds our test flag.
        @dataclass
        class _Orch:
            data_dir: Path
            _repo: str = "your-org/bumba-open-harness"

        orch = _Orch(data_dir=tmp_path)
        pause(tmp_path / "factory-paused.flag", reason="t")

        harness = SoakHarness(orchestrator=orch, log_dir=tmp_path / "soak")
        with patch(
            "bridge.services.factory_orchestrator._gh_list_accepted"
        ) as mock_list:
            entries = await harness.shadow_tick()

        assert entries == ()
        mock_list.assert_not_called()


# ── /factory operator command — handler integration ────────────────────


@pytest_asyncio.fixture
async def cmd_handler(migrated_db, message_queue, session_manager):
    return CommandHandler(
        db=migrated_db,
        queue=message_queue,
        session_manager=session_manager,
        claude_runner=None,
    )


class TestCmdFactoryRegistration:
    def test_factory_in_bridge_commands(self, cmd_handler: CommandHandler):
        # Tier 3 — only registers when [commands] toml gates allow it.
        # We assert membership in the Tier 3 set.
        from bridge.commands import _TIER_3_POWER_USER
        assert "factory" in _TIER_3_POWER_USER

    def test_no_collision_with_existing_command(self):
        # No accidental rename of an existing top-level command.
        # (Spec acceptance criterion: BRIDGE_COMMANDS contains factory AND
        #  no existing entry renamed.)
        from bridge.commands import (
            _TIER_1_ESSENTIAL,
            _TIER_2_Z4,
        )
        # ``factory`` must not collide with a Tier 1 / Tier 2 surface.
        assert "factory" not in _TIER_1_ESSENTIAL
        assert "factory" not in _TIER_2_Z4


@pytest.mark.asyncio
class TestCmdFactoryDispatch:
    async def test_status_calls_collect_status(
        self, cmd_handler: CommandHandler
    ):
        # Patch collect_status + format_status_for_discord — we're testing
        # the dispatch wiring, not the rendering.
        fake_status = FactoryStatus(
            orchestrator_enabled=True,
            paused=False,
            last_tick_at_iso=None,
            last_tick_cost_usd=0.0,
            issues_processed_today=0,
            issues_processed_this_week=0,
            total_cost_today_usd=0.0,
            total_cost_this_week_usd=0.0,
            pending_accepted_count=0,
            in_flight_count=0,
            soak_ready_to_enable=False,
            soak_ready_reason="",
        )
        with patch.object(ops, "collect_status", return_value=fake_status):
            out = await cmd_handler._cmd_factory("chat-1", "status")
        assert "Factory status" in out

    async def test_pause_writes_flag(self, cmd_handler: CommandHandler):
        data_dir = Path(cmd_handler._db.db_path).parent
        flag = data_dir / "factory-paused.flag"
        # Cleanup any leftover from a prior run.
        if flag.exists():
            flag.unlink()
        out = await cmd_handler._cmd_factory("chat-1", "pause needs investigation")
        try:
            assert flag.exists()
            assert "paused" in out.lower()
            assert "needs investigation" in out
        finally:
            if flag.exists():
                flag.unlink()

    async def test_resume_clears_flag(self, cmd_handler: CommandHandler):
        data_dir = Path(cmd_handler._db.db_path).parent
        flag = data_dir / "factory-paused.flag"
        pause(flag, reason="t")
        try:
            out = await cmd_handler._cmd_factory("chat-1", "resume")
            assert "resumed" in out.lower()
            assert not flag.exists()
        finally:
            if flag.exists():
                flag.unlink()

    async def test_resume_when_not_paused_says_so(
        self, cmd_handler: CommandHandler
    ):
        data_dir = Path(cmd_handler._db.db_path).parent
        flag = data_dir / "factory-paused.flag"
        if flag.exists():
            flag.unlink()
        out = await cmd_handler._cmd_factory("chat-1", "resume")
        assert "not paused" in out.lower()

    async def test_pause_already_paused_warns(
        self, cmd_handler: CommandHandler
    ):
        data_dir = Path(cmd_handler._db.db_path).parent
        flag = data_dir / "factory-paused.flag"
        pause(flag, reason="first")
        try:
            out = await cmd_handler._cmd_factory("chat-1", "pause second")
            assert "already paused" in out.lower()
        finally:
            if flag.exists():
                flag.unlink()

    async def test_escalate_calls_helper(self, cmd_handler: CommandHandler):
        with patch.object(
            ops,
            "escalate_issue",
            return_value={
                "issue_number": 1234,
                "prior_state": "factory:in-progress",
                "new_state": "factory:needs-human",
                "transitioned": True,
                "comment_posted": True,
            },
        ) as mock_esc:
            out = await cmd_handler._cmd_factory(
                "chat-1", "escalate 1234 lock contended"
            )
        mock_esc.assert_called_once()
        assert mock_esc.call_args.args[0] == 1234
        assert mock_esc.call_args.kwargs["reason"] == "lock contended"
        assert "1234" in out
        assert "factory:needs-human" in out

    async def test_escalate_failure_surfaces(self, cmd_handler: CommandHandler):
        with patch.object(
            ops,
            "escalate_issue",
            return_value={
                "issue_number": 1234,
                "prior_state": None,
                "new_state": "factory:needs-human",
                "transitioned": False,
                "comment_posted": False,
            },
        ):
            out = await cmd_handler._cmd_factory(
                "chat-1", "escalate 1234 reason"
            )
        assert "did not change state" in out

    async def test_escalate_without_args_shows_usage(
        self, cmd_handler: CommandHandler
    ):
        out = await cmd_handler._cmd_factory("chat-1", "escalate")
        assert "Usage" in out
        assert "issue_number" in out

    async def test_escalate_non_integer_issue_rejected(
        self, cmd_handler: CommandHandler
    ):
        out = await cmd_handler._cmd_factory("chat-1", "escalate notanumber")
        assert "Invalid issue number" in out

    async def test_unknown_subcommand_lists_valid(
        self, cmd_handler: CommandHandler
    ):
        out = await cmd_handler._cmd_factory("chat-1", "wibble")
        assert "Unknown subcommand" in out
        assert "status" in out
        assert "pause" in out
        assert "resume" in out
        assert "escalate" in out

    async def test_no_args_defaults_to_status(self, cmd_handler: CommandHandler):
        # Bare ``/factory`` falls back to status view.
        with patch.object(
            ops,
            "collect_status",
            return_value=FactoryStatus(
                orchestrator_enabled=False,
                paused=False,
                last_tick_at_iso=None,
                last_tick_cost_usd=0.0,
                issues_processed_today=0,
                issues_processed_this_week=0,
                total_cost_today_usd=0.0,
                total_cost_this_week_usd=0.0,
                pending_accepted_count=0,
                in_flight_count=0,
                soak_ready_to_enable=False,
                soak_ready_reason="",
            ),
        ):
            out = await cmd_handler._cmd_factory("chat-1", "")
        assert "Factory status" in out
