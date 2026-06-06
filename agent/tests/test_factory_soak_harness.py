"""Tests for bridge.factory.soak_harness — Sprint 14.11.

Concept-only port — no Dark Factory source copied.

Pure-function tests for the JSONL append / verification / aggregation
primitives. End-to-end tests for the SoakHarness wrapper use mocked
orchestrators that surface the seam where production-action would
normally fire — the harness must NEVER call those seams.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bridge.factory.soak_harness import (
    SOAK_LOG_NAME_FMT,
    SoakEntry,
    SoakHarness,
    aggregate_soak_window,
    append_soak_entry,
    format_report_for_discord,
    update_verification,
)


# ── Helpers ──────────────────────────────────────────────────────────────


def _make_entry(
    *,
    issue_number: int = 1234,
    issue_title: str = "Demo issue",
    processed_at_iso: str | None = None,
    synthesis_outcome: str = "ready_for_operator",
    rule_fired: int = 1,
    block_reasons: tuple[str, ...] = (),
    advise_reasons: tuple[str, ...] = (),
    would_action: str = "would_proceed",
    cost_usd: float = 0.50,
    duration_seconds: float = 12.5,
    operator_verification: str = "pending",
    operator_notes: str = "",
) -> SoakEntry:
    """Convenience builder so each test only specifies the fields it cares about."""
    if processed_at_iso is None:
        processed_at_iso = datetime.now(timezone.utc).isoformat(timespec="seconds")
    return SoakEntry(
        issue_number=issue_number,
        issue_title=issue_title,
        processed_at_iso=processed_at_iso,
        synthesis_outcome=synthesis_outcome,
        rule_fired=rule_fired,
        block_reasons=block_reasons,
        advise_reasons=advise_reasons,
        would_action=would_action,  # type: ignore[arg-type]
        cost_usd=cost_usd,
        duration_seconds=duration_seconds,
        operator_verification=operator_verification,  # type: ignore[arg-type]
        operator_notes=operator_notes,
    )


def _today_iso() -> str:
    return datetime.now(timezone.utc).date().isoformat()


@dataclass
class _FakeImplementResult:
    """Subset of ImplementResult attributes the soak harness reads."""
    issue_number: int
    pr_number: int | None
    pr_url: str | None
    final_state: Any
    failed_phase: str | None
    cost_usd: float


def _make_validate_result(
    *,
    aggregate: str = "pass",
    block_reasons: tuple[str, ...] = (),
    total_cost_usd: float = 0.05,
):
    from bridge.factory.validate import ValidateResult
    return ValidateResult(
        reviewer_results=(),
        aggregate_verdict=aggregate,  # type: ignore[arg-type]
        block_reasons=block_reasons,
        total_cost_usd=total_cost_usd,
    )


def _make_orchestrator_mock(
    *,
    impl_result=None,
    validate_result=None,
    decision=None,
    repo: str = "your-org/bumba-open-harness",
    cost_cap_per_issue: float = 2.00,
) -> Any:
    """Build a duck-typed orchestrator stand-in for the SoakHarness.

    We don't construct a real FactoryOrchestrator because the soak
    harness only reads private attributes via getattr — a SimpleNamespace
    plus mocks is enough and keeps the test free of implement_issue
    / validate_pr import chains.
    """
    from types import SimpleNamespace
    from bridge.factory.labels import FactoryState
    from bridge.factory.seven_rule_synthesizer import (
        FactorySynthesisOutcome,
        SynthesisDecision,
    )

    if impl_result is None:
        impl_result = _FakeImplementResult(
            issue_number=1,
            pr_number=99,
            pr_url="https://example/pr/99",
            final_state=FactoryState.NEEDS_REVIEW,
            failed_phase=None,
            cost_usd=0.50,
        )
    impl_runner = MagicMock(return_value=impl_result)

    if validate_result is None:
        validate_result = _make_validate_result()
    validate_runner = AsyncMock(return_value=validate_result)

    if decision is None:
        decision = SynthesisDecision(
            outcome=FactorySynthesisOutcome.READY_FOR_OPERATOR,
            rule_fired=1,
            explanation="all reviewers passed",
        )
    synth = MagicMock(return_value=decision)

    return SimpleNamespace(
        _implement=impl_runner,
        _validate=validate_runner,
        _synthesize=synth,
        _repo=repo,
        _cost_cap_per_issue=cost_cap_per_issue,
    )


# ── append_soak_entry ────────────────────────────────────────────────────


class TestAppendSoakEntry:
    def test_writes_record_to_dated_jsonl(self, tmp_path: Path):
        entry = _make_entry(processed_at_iso="2026-05-01T12:00:00+00:00")
        append_soak_entry(entry, log_dir=tmp_path)
        path = tmp_path / SOAK_LOG_NAME_FMT.format(date="2026-05-01")
        assert path.exists()
        lines = path.read_text(encoding="utf-8").splitlines()
        assert len(lines) == 1
        rec = json.loads(lines[0])
        assert rec["issue_number"] == entry.issue_number
        assert rec["synthesis_outcome"] == entry.synthesis_outcome
        assert rec["operator_verification"] == "pending"

    def test_idempotent_on_signature(self, tmp_path: Path):
        # Two entries with same (issue_number, processed_at_iso) → second is no-op.
        ts = "2026-05-01T12:00:00+00:00"
        e1 = _make_entry(issue_number=42, processed_at_iso=ts, cost_usd=0.10)
        e2 = _make_entry(issue_number=42, processed_at_iso=ts, cost_usd=999.00)
        append_soak_entry(e1, log_dir=tmp_path)
        append_soak_entry(e2, log_dir=tmp_path)

        path = tmp_path / SOAK_LOG_NAME_FMT.format(date="2026-05-01")
        lines = path.read_text(encoding="utf-8").splitlines()
        assert len(lines) == 1
        rec = json.loads(lines[0])
        # First write wins — operator verifications survive replays.
        assert rec["cost_usd"] == 0.10

    def test_distinct_processed_at_appends(self, tmp_path: Path):
        e1 = _make_entry(
            issue_number=42, processed_at_iso="2026-05-01T12:00:00+00:00"
        )
        e2 = _make_entry(
            issue_number=42, processed_at_iso="2026-05-01T16:00:00+00:00"
        )
        append_soak_entry(e1, log_dir=tmp_path)
        append_soak_entry(e2, log_dir=tmp_path)
        path = tmp_path / SOAK_LOG_NAME_FMT.format(date="2026-05-01")
        lines = path.read_text(encoding="utf-8").splitlines()
        assert len(lines) == 2

    def test_io_errors_swallowed(self, tmp_path: Path, monkeypatch):
        # Patch _atomic_write_jsonl to raise — append should NOT propagate.
        from bridge.factory import soak_harness

        def boom(*_args, **_kwargs):
            raise OSError("disk full")

        monkeypatch.setattr(soak_harness, "_atomic_write_jsonl", boom)
        # Should not raise.
        append_soak_entry(_make_entry(), log_dir=tmp_path)


# ── update_verification ──────────────────────────────────────────────────


class TestUpdateVerification:
    def test_updates_existing_entry(self, tmp_path: Path):
        ts = "2026-05-01T12:00:00+00:00"
        append_soak_entry(
            _make_entry(issue_number=42, processed_at_iso=ts),
            log_dir=tmp_path,
        )
        ok = update_verification(
            42, verification="correct", notes="matched", log_dir=tmp_path
        )
        assert ok is True

        path = tmp_path / SOAK_LOG_NAME_FMT.format(date="2026-05-01")
        rec = json.loads(path.read_text(encoding="utf-8").splitlines()[0])
        assert rec["operator_verification"] == "correct"
        assert rec["operator_notes"] == "matched"
        assert rec["operator_verification_at_iso"] is not None

    def test_returns_false_when_missing(self, tmp_path: Path):
        ok = update_verification(
            999, verification="correct", log_dir=tmp_path
        )
        assert ok is False

    def test_picks_most_recent_record_when_duplicates(self, tmp_path: Path):
        # Two entries for #42 across different days. update should hit the
        # most-recent (later processed_at_iso).
        e_old = _make_entry(
            issue_number=42, processed_at_iso="2026-05-01T08:00:00+00:00"
        )
        e_new = _make_entry(
            issue_number=42, processed_at_iso="2026-05-02T08:00:00+00:00"
        )
        append_soak_entry(e_old, log_dir=tmp_path)
        append_soak_entry(e_new, log_dir=tmp_path)

        ok = update_verification(
            42, verification="incorrect", notes="diverged", log_dir=tmp_path
        )
        assert ok is True

        # Old still pending, new is incorrect.
        old_path = tmp_path / SOAK_LOG_NAME_FMT.format(date="2026-05-01")
        new_path = tmp_path / SOAK_LOG_NAME_FMT.format(date="2026-05-02")
        old_rec = json.loads(old_path.read_text().splitlines()[0])
        new_rec = json.loads(new_path.read_text().splitlines()[0])
        assert old_rec["operator_verification"] == "pending"
        assert new_rec["operator_verification"] == "incorrect"

    def test_rejects_unknown_verdict(self, tmp_path: Path):
        ok = update_verification(
            42, verification="bogus", log_dir=tmp_path  # type: ignore[arg-type]
        )
        assert ok is False


# ── aggregate_soak_window ────────────────────────────────────────────────


class TestAggregateSoakWindow:
    def test_zero_entries_returns_zero_report(self, tmp_path: Path):
        report = aggregate_soak_window(days=14, log_dir=tmp_path)
        assert report.total_issues_processed == 0
        assert report.pending_verification == 0
        assert report.verified_correct == 0
        assert report.correctness_rate == 0.0
        assert report.ready_to_enable is False
        assert "no soak entries" in report.ready_reason.lower()

    def test_mixed_verifications_compute_correctness(self, tmp_path: Path):
        # 5 correct + 2 incorrect → rate = 5/7 ≈ 0.714
        end_date = datetime.now(timezone.utc).date()
        for i in range(5):
            ts = (
                datetime.combine(end_date - timedelta(days=i), datetime.min.time())
                .replace(tzinfo=timezone.utc)
                .isoformat(timespec="seconds")
            )
            append_soak_entry(
                _make_entry(
                    issue_number=1000 + i,
                    processed_at_iso=ts,
                    operator_verification="correct",
                ),
                log_dir=tmp_path,
            )
        for i in range(2):
            ts = (
                datetime.combine(end_date - timedelta(days=i + 5), datetime.min.time())
                .replace(tzinfo=timezone.utc)
                .isoformat(timespec="seconds")
            )
            append_soak_entry(
                _make_entry(
                    issue_number=2000 + i,
                    processed_at_iso=ts,
                    operator_verification="incorrect",
                ),
                log_dir=tmp_path,
            )

        report = aggregate_soak_window(days=14, log_dir=tmp_path)
        assert report.total_issues_processed == 7
        assert report.verified_correct == 5
        assert report.verified_incorrect == 2
        assert report.pending_verification == 0
        # 5/7 = 0.714285...
        assert abs(report.correctness_rate - 5 / 7) < 1e-6
        # Below 0.80 floor → not ready.
        assert report.ready_to_enable is False
        assert "correctness_rate" in report.ready_reason

    def test_5_correct_zero_incorrect_14d_is_ready(self, tmp_path: Path):
        # 5 correct, 0 incorrect, 14d window → ready=True.
        end_date = datetime.now(timezone.utc).date()
        for i in range(5):
            ts = (
                datetime.combine(end_date - timedelta(days=i), datetime.min.time())
                .replace(tzinfo=timezone.utc)
                .isoformat(timespec="seconds")
            )
            append_soak_entry(
                _make_entry(
                    issue_number=1000 + i,
                    processed_at_iso=ts,
                    operator_verification="correct",
                ),
                log_dir=tmp_path,
            )

        report = aggregate_soak_window(days=14, log_dir=tmp_path)
        assert report.verified_correct == 5
        assert report.verified_incorrect == 0
        assert report.correctness_rate == 1.0
        assert report.ready_to_enable is True
        assert "ready" in report.ready_reason.lower()

    def test_4_correct_below_min_count_not_ready(self, tmp_path: Path):
        end_date = datetime.now(timezone.utc).date()
        for i in range(4):
            ts = (
                datetime.combine(end_date - timedelta(days=i), datetime.min.time())
                .replace(tzinfo=timezone.utc)
                .isoformat(timespec="seconds")
            )
            append_soak_entry(
                _make_entry(
                    issue_number=1000 + i,
                    processed_at_iso=ts,
                    operator_verification="correct",
                ),
                log_dir=tmp_path,
            )

        report = aggregate_soak_window(days=14, log_dir=tmp_path)
        assert report.verified_correct == 4
        assert report.correctness_rate == 1.0
        # 4 < min_verified_count=5 → not ready.
        assert report.ready_to_enable is False
        assert "verified_correct" in report.ready_reason

    def test_window_below_14d_not_ready(self, tmp_path: Path):
        # Even with 5 correct + 100% rate, window<14 → not ready.
        end_date = datetime.now(timezone.utc).date()
        for i in range(5):
            ts = (
                datetime.combine(end_date - timedelta(days=i), datetime.min.time())
                .replace(tzinfo=timezone.utc)
                .isoformat(timespec="seconds")
            )
            append_soak_entry(
                _make_entry(
                    issue_number=1000 + i,
                    processed_at_iso=ts,
                    operator_verification="correct",
                ),
                log_dir=tmp_path,
            )

        report = aggregate_soak_window(days=7, log_dir=tmp_path)
        assert report.ready_to_enable is False
        assert "window" in report.ready_reason.lower()

    def test_sample_pending_caps_at_five(self, tmp_path: Path):
        # 8 pending entries → sample_pending should be 5 most-recent.
        end_date = datetime.now(timezone.utc).date()
        for i in range(8):
            ts = (
                datetime.combine(end_date - timedelta(days=i), datetime.min.time())
                .replace(tzinfo=timezone.utc)
                .isoformat(timespec="seconds")
            )
            append_soak_entry(
                _make_entry(
                    issue_number=1000 + i,
                    processed_at_iso=ts,
                    # default pending
                ),
                log_dir=tmp_path,
            )

        report = aggregate_soak_window(days=14, log_dir=tmp_path)
        assert len(report.sample_pending) == 5
        # Sorted most-recent first.
        assert report.sample_pending[0].issue_number == 1000  # offset 0 → end_date
        # Last in sample is offset 4 → end_date - 4d
        assert report.sample_pending[-1].issue_number == 1004

    def test_by_outcome_counts(self, tmp_path: Path):
        end_date = datetime.now(timezone.utc).date()
        outcomes = ["ready_for_operator", "needs_fix", "needs_human", "ready_for_operator"]
        for i, out in enumerate(outcomes):
            ts = (
                datetime.combine(end_date - timedelta(days=i), datetime.min.time())
                .replace(tzinfo=timezone.utc)
                .isoformat(timespec="seconds")
            )
            append_soak_entry(
                _make_entry(
                    issue_number=1000 + i,
                    processed_at_iso=ts,
                    synthesis_outcome=out,
                ),
                log_dir=tmp_path,
            )
        report = aggregate_soak_window(days=14, log_dir=tmp_path)
        assert report.by_outcome.get("ready_for_operator") == 2
        assert report.by_outcome.get("needs_fix") == 1
        assert report.by_outcome.get("needs_human") == 1


# ── format_report_for_discord ────────────────────────────────────────────


class TestFormatReportForDiscord:
    def test_renders_compact_block(self, tmp_path: Path):
        # Single entry in window — rendered output mentions the issue.
        ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
        append_soak_entry(
            _make_entry(
                issue_number=42,
                issue_title="Sample title",
                processed_at_iso=ts,
            ),
            log_dir=tmp_path,
        )
        report = aggregate_soak_window(days=14, log_dir=tmp_path)
        text = format_report_for_discord(report)
        assert "Factory Soak Harness" in text
        assert "Total issues processed" in text
        # Pending list surfaces our entry.
        assert "#42" in text
        # Status ribbon at bottom.
        assert "[NOT READY]" in text or "[READY]" in text


# ── SoakHarness.shadow_tick ──────────────────────────────────────────────


@pytest.mark.asyncio
class TestSoakHarness:
    async def test_empty_queue_writes_nothing(self, tmp_path: Path):
        orch = _make_orchestrator_mock()
        harness = SoakHarness(orchestrator=orch, log_dir=tmp_path)
        with patch(
            "bridge.services.factory_orchestrator._gh_list_accepted",
            return_value=[],
        ):
            entries = await harness.shadow_tick()
        assert entries == ()

    async def test_happy_path_writes_entry_and_does_not_act(
        self, tmp_path: Path
    ):
        orch = _make_orchestrator_mock()
        harness = SoakHarness(orchestrator=orch, log_dir=tmp_path)

        with patch(
            "bridge.services.factory_orchestrator._gh_list_accepted",
            return_value=[
                {"number": 7, "title": "Demo", "body": "do the thing"},
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
            return_value=True,
        ) as mock_transition:
            entries = await harness.shadow_tick()

        assert len(entries) == 1
        e = entries[0]
        assert e.issue_number == 7
        assert e.synthesis_outcome == "ready_for_operator"
        assert e.would_action == "would_proceed"
        # The harness MUST NEVER fire the production-action seams.
        mock_comment.assert_not_called()
        mock_ready.assert_not_called()
        mock_transition.assert_not_called()

        # Entry persisted in soak log.
        date_iso = e.processed_at_iso[:10]
        path = tmp_path / SOAK_LOG_NAME_FMT.format(date=date_iso)
        assert path.exists()

    async def test_implement_failure_records_escalate(self, tmp_path: Path):
        impl = _FakeImplementResult(
            issue_number=1,
            pr_number=None,
            pr_url=None,
            final_state=None,
            failed_phase="implement",
            cost_usd=0.05,
        )
        orch = _make_orchestrator_mock(impl_result=impl)
        harness = SoakHarness(orchestrator=orch, log_dir=tmp_path)
        with patch(
            "bridge.services.factory_orchestrator._gh_list_accepted",
            return_value=[{"number": 7, "title": "x", "body": "y"}],
        ), patch(
            "bridge.services.factory_orchestrator._gh_pr_diff",
            return_value="",
        ):
            entries = await harness.shadow_tick()
        assert len(entries) == 1
        assert entries[0].synthesis_outcome == "implement_incomplete"
        assert entries[0].would_action == "would_escalate"

    async def test_outcome_mapped_to_action(self, tmp_path: Path):
        from bridge.factory.seven_rule_synthesizer import (
            FactorySynthesisOutcome,
            SynthesisDecision,
        )

        decision = SynthesisDecision(
            outcome=FactorySynthesisOutcome.NEEDS_HUMAN,
            rule_fired=4,
            explanation="security regression",
            block_reasons=("security: token leak",),
        )
        orch = _make_orchestrator_mock(decision=decision)
        harness = SoakHarness(orchestrator=orch, log_dir=tmp_path)

        with patch(
            "bridge.services.factory_orchestrator._gh_list_accepted",
            return_value=[{"number": 7, "title": "x", "body": "y"}],
        ), patch(
            "bridge.services.factory_orchestrator._gh_pr_diff",
            return_value="diff",
        ):
            entries = await harness.shadow_tick()

        assert len(entries) == 1
        assert entries[0].synthesis_outcome == "needs_human"
        assert entries[0].would_action == "would_escalate"
        assert "security: token leak" in entries[0].block_reasons


# ── Integration with /soak_status, /soak_verify commands ─────────────────


@pytest.mark.asyncio
class TestSoakCommands:
    async def test_soak_status_formats_for_discord(self, tmp_path: Path):
        # Seed one entry so the report has something to render.
        ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
        soak_dir = tmp_path / "factory-soak"
        append_soak_entry(
            _make_entry(issue_number=4242, processed_at_iso=ts),
            log_dir=soak_dir,
        )

        from bridge.commands import CommandHandler

        # Build a tiny stand-in handler — only _db.db_path matters here.
        from types import SimpleNamespace
        handler = CommandHandler.__new__(CommandHandler)
        handler._db = SimpleNamespace(db_path=str(tmp_path / "memory.db"))

        result = await handler._cmd_soak_status("chat-1", "")
        assert "Factory Soak Harness" in result
        assert "#4242" in result

    async def test_soak_status_invalid_days(self, tmp_path: Path):
        from bridge.commands import CommandHandler
        from types import SimpleNamespace

        handler = CommandHandler.__new__(CommandHandler)
        handler._db = SimpleNamespace(db_path=str(tmp_path / "memory.db"))

        result = await handler._cmd_soak_status("chat-1", "bogus")
        assert "Invalid argument" in result

    async def test_soak_verify_records_correct(self, tmp_path: Path):
        ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
        soak_dir = tmp_path / "factory-soak"
        append_soak_entry(
            _make_entry(issue_number=4242, processed_at_iso=ts),
            log_dir=soak_dir,
        )

        from bridge.commands import CommandHandler
        from types import SimpleNamespace
        handler = CommandHandler.__new__(CommandHandler)
        handler._db = SimpleNamespace(db_path=str(tmp_path / "memory.db"))

        result = await handler._cmd_soak_verify(
            "chat-1", "4242 correct factory matched"
        )
        assert "Recorded `correct`" in result

    async def test_soak_verify_missing_args(self, tmp_path: Path):
        from bridge.commands import CommandHandler
        from types import SimpleNamespace
        handler = CommandHandler.__new__(CommandHandler)
        handler._db = SimpleNamespace(db_path=str(tmp_path / "memory.db"))

        # No args at all.
        result = await handler._cmd_soak_verify("chat-1", "")
        assert "Usage:" in result
        # One arg only.
        result = await handler._cmd_soak_verify("chat-1", "1234")
        assert "Usage:" in result

    async def test_soak_verify_unknown_verdict(self, tmp_path: Path):
        from bridge.commands import CommandHandler
        from types import SimpleNamespace
        handler = CommandHandler.__new__(CommandHandler)
        handler._db = SimpleNamespace(db_path=str(tmp_path / "memory.db"))

        result = await handler._cmd_soak_verify("chat-1", "1234 banana")
        assert "Invalid verdict" in result

    async def test_soak_verify_unknown_issue(self, tmp_path: Path):
        from bridge.commands import CommandHandler
        from types import SimpleNamespace
        handler = CommandHandler.__new__(CommandHandler)
        handler._db = SimpleNamespace(db_path=str(tmp_path / "memory.db"))

        # No soak entries exist — verify should report not-found.
        result = await handler._cmd_soak_verify("chat-1", "9999 correct")
        assert "No soak entry" in result

    async def test_soak_verify_bad_issue_number(self, tmp_path: Path):
        from bridge.commands import CommandHandler
        from types import SimpleNamespace
        handler = CommandHandler.__new__(CommandHandler)
        handler._db = SimpleNamespace(db_path=str(tmp_path / "memory.db"))

        result = await handler._cmd_soak_verify("chat-1", "not-a-number correct")
        assert "Invalid issue number" in result


# ── Config wiring ────────────────────────────────────────────────────────


class TestConfigFields:
    def test_factory_soak_fields_default_to_safe_values(self):
        from bridge.config import BridgeConfig

        cfg = BridgeConfig()
        assert cfg.factory_soak_harness_enabled is False
        assert cfg.factory_soak_min_verified_count == 5
        assert cfg.factory_soak_min_correctness_rate == 0.80


# ── Tier 3 registration ──────────────────────────────────────────────────


class TestCommandRegistration:
    def test_soak_commands_in_tier3(self):
        from bridge.commands import _TIER_3_POWER_USER

        assert "soak_status" in _TIER_3_POWER_USER
        assert "soak_verify" in _TIER_3_POWER_USER


# ── Service runner registration ──────────────────────────────────────────


class TestServiceRunnerRegistration:
    def test_factory_soak_in_service_map(self):
        from bridge.services.runner import SERVICE_MAP, SERVICE_TIMEOUTS

        assert "factory_soak" in SERVICE_MAP
        assert SERVICE_MAP["factory_soak"] == (
            "bridge.services.factory_soak",
            "FactorySoakService",
        )
        # Timeout configured.
        assert SERVICE_TIMEOUTS.get("factory_soak", 0) >= 600
