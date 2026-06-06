"""Tests for ``bridge.second_brain.shadow_router`` — Sprint 05.11 (#1021).

Covers the 14-day shadow + auto-routing decision harness for
consolidation outputs. Per ADR Decision 4 (signed 2026-05-01,
``agent/docs/architecture/second-brain.md``), the harness only
records what the auto-router would have done — it never modifies
vault files. Tests assert that contract.

Concept-only port — no source copied (Karpathy gist informs the
markdown-wiki shape only; ``concept-only-no-license``).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from bridge.second_brain.shadow_router import (
    SHADOW_LOG_NAME_FMT,
    ShadowEntry,
    ShadowReport,
    ShadowRouter,
    aggregate_shadow_window,
    append_shadow_entry,
    evaluate_contribution,
    format_shadow_report,
    update_actual_outcome,
)


# ---------------- helpers ---------------- #


@dataclass
class _StubLintFinding:
    """Minimal duck-typed stand-in for ``LintFinding``."""

    severity: str
    message: str = ""


@dataclass
class _StubContribution:
    """Minimal duck-typed stand-in for ``Contribution``."""

    relpath: str
    body: str
    authored_at: str = "2026-05-01T12:00:00Z"
    source: str = "consolidation"
    destination: str = "curated"
    session_id: str = "test-session"
    provenance: str = "test"


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _seed_entry(
    log_dir: Path,
    *,
    relpath: str,
    decided_at: str,
    decision: str = "promote",
    actual: str = "pending",
    actual_at: object = None,
) -> ShadowEntry:
    """Materialize a shadow entry on disk for aggregation tests."""
    entry = ShadowEntry(
        contribution_relpath=relpath,
        contribution_authored_at_iso=decided_at,
        shadow_decision=decision,  # type: ignore[arg-type]
        shadow_decision_at_iso=decided_at,
        shadow_reason="seeded for test",
        actual_outcome=actual,  # type: ignore[arg-type]
        actual_outcome_at_iso=actual_at,  # type: ignore[arg-type]
    )
    append_shadow_entry(entry, log_dir=log_dir)
    return entry


# ---------------- evaluate_contribution ---------------- #


class TestEvaluateContribution:
    def test_lint_error_blocks_with_reject(self):
        body = "x " * 200  # well over the word floor
        decision, reason = evaluate_contribution(
            body,
            contribution_relpath=(
                "bumba-contributions/curated/consolidation/2026-05-01-digest.md"
            ),
            lint_findings=[
                _StubLintFinding(severity="error", message="missing frontmatter"),
            ],
        )
        assert decision == "reject"
        assert "missing frontmatter" in reason

    def test_lint_warning_does_not_block(self):
        body = " ".join(["word"] * 200)
        decision, _ = evaluate_contribution(
            body,
            contribution_relpath=(
                "bumba-contributions/curated/consolidation/2026-05-01-digest.md"
            ),
            lint_findings=[_StubLintFinding(severity="warning", message="orphan")],
        )
        assert decision == "promote"

    def test_too_short_leaves_curated(self):
        decision, reason = evaluate_contribution(
            "short body",
            contribution_relpath=(
                "bumba-contributions/curated/consolidation/2026-05-01-digest.md"
            ),
        )
        assert decision == "leave_curated"
        assert "too short" in reason

    def test_consolidation_path_with_length_promotes(self):
        body = " ".join(["w"] * 150)
        decision, reason = evaluate_contribution(
            body,
            contribution_relpath=(
                "bumba-contributions/curated/consolidation/2026-05-01-digest.md"
            ),
        )
        assert decision == "promote"
        assert "consolidation" in reason

    def test_non_consolidation_falls_to_leave_curated(self):
        body = " ".join(["w"] * 150)
        decision, _ = evaluate_contribution(
            body,
            contribution_relpath=(
                "bumba-contributions/staging/daily-logs/2026-05-01.md"
            ),
        )
        assert decision == "leave_curated"

    def test_explicit_word_count_overrides_body_count(self):
        decision, _ = evaluate_contribution(
            "x x x",  # only 3 tokens by split, but we override
            contribution_relpath=(
                "bumba-contributions/curated/consolidation/2026-05-01-digest.md"
            ),
            word_count=200,
        )
        assert decision == "promote"


# ---------------- append + idempotency ---------------- #


class TestAppendShadowEntry:
    def test_append_creates_jsonl(self, tmp_path):
        entry = ShadowEntry(
            contribution_relpath=(
                "bumba-contributions/curated/consolidation/2026-05-01-digest.md"
            ),
            contribution_authored_at_iso="2026-05-01T12:00:00Z",
            shadow_decision="promote",
            shadow_decision_at_iso="2026-05-01T12:30:00Z",
            shadow_reason="t",
            actual_outcome="pending",
            actual_outcome_at_iso=None,
        )
        append_shadow_entry(entry, log_dir=tmp_path)
        log_file = tmp_path / SHADOW_LOG_NAME_FMT.format(date="2026-05-01")
        assert log_file.is_file()
        line = log_file.read_text(encoding="utf-8").splitlines()[0]
        record = json.loads(line)
        assert record["shadow_decision"] == "promote"

    def test_append_is_idempotent_on_relpath_and_decided_at(self, tmp_path):
        entry = ShadowEntry(
            contribution_relpath="bumba-contributions/curated/consolidation/x.md",
            contribution_authored_at_iso="2026-05-01T12:00:00Z",
            shadow_decision="promote",
            shadow_decision_at_iso="2026-05-01T12:30:00Z",
            shadow_reason="t",
            actual_outcome="pending",
            actual_outcome_at_iso=None,
        )
        append_shadow_entry(entry, log_dir=tmp_path)
        # Repeat → still one line.
        append_shadow_entry(entry, log_dir=tmp_path)
        log_file = tmp_path / SHADOW_LOG_NAME_FMT.format(date="2026-05-01")
        lines = [
            line for line in log_file.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        assert len(lines) == 1


# ---------------- update_actual_outcome ---------------- #


class TestUpdateActualOutcome:
    def test_updates_matching_entry(self, tmp_path):
        _seed_entry(
            tmp_path,
            relpath="bumba-contributions/curated/consolidation/x.md",
            decided_at="2026-05-01T12:00:00Z",
        )
        ok = update_actual_outcome(
            "bumba-contributions/curated/consolidation/x.md",
            actual_outcome="promoted",
            decided_at_iso="2026-05-01T13:00:00Z",
            log_dir=tmp_path,
        )
        assert ok is True
        log_file = tmp_path / SHADOW_LOG_NAME_FMT.format(date="2026-05-01")
        record = json.loads(log_file.read_text().splitlines()[0])
        assert record["actual_outcome"] == "promoted"
        assert record["actual_outcome_at_iso"] == "2026-05-01T13:00:00Z"

    def test_returns_false_when_missing(self, tmp_path):
        ok = update_actual_outcome(
            "bumba-contributions/curated/consolidation/missing.md",
            actual_outcome="rejected",
            decided_at_iso="2026-05-01T13:00:00Z",
            log_dir=tmp_path,
        )
        assert ok is False

    def test_no_double_stamp(self, tmp_path):
        _seed_entry(
            tmp_path,
            relpath="bumba-contributions/curated/consolidation/x.md",
            decided_at="2026-05-01T12:00:00Z",
        )
        update_actual_outcome(
            "bumba-contributions/curated/consolidation/x.md",
            actual_outcome="promoted",
            decided_at_iso="2026-05-01T13:00:00Z",
            log_dir=tmp_path,
        )
        # Second update — already not pending → returns False.
        ok = update_actual_outcome(
            "bumba-contributions/curated/consolidation/x.md",
            actual_outcome="rejected",
            decided_at_iso="2026-05-01T14:00:00Z",
            log_dir=tmp_path,
        )
        assert ok is False


# ---------------- aggregate_shadow_window ---------------- #


class TestAggregateShadowWindow:
    def test_zero_entries_returns_zeros(self, tmp_path):
        report = aggregate_shadow_window(days=14, log_dir=tmp_path)
        assert isinstance(report, ShadowReport)
        assert report.total_contributions == 0
        assert report.pending_count == 0
        assert report.decided_count == 0
        assert report.agreement_rate == 0.0

    def test_5_days_of_entries_aggregate(self, tmp_path):
        # Seed 5 entries across 5 days inside a 14-day window ending today.
        end = datetime.now(timezone.utc).date()
        for i in range(5):
            day = end - timedelta(days=i)
            iso = f"{day.strftime('%Y-%m-%d')}T12:00:00Z"
            _seed_entry(
                tmp_path,
                relpath=f"bumba-contributions/curated/consolidation/{i}.md",
                decided_at=iso,
                decision="promote",
                # 4 of 5 the operator promoted; 1 rejected → agreement 4/5.
                actual="promoted" if i < 4 else "rejected",
                actual_at=iso,
            )
        report = aggregate_shadow_window(
            days=14,
            end_date_iso=end.strftime("%Y-%m-%d"),
            log_dir=tmp_path,
        )
        assert report.total_contributions == 5
        assert report.decided_count == 5
        assert report.pending_count == 0
        assert report.agreement_count == 4
        assert report.disagreement_count == 1
        assert report.agreement_rate == pytest.approx(4 / 5)

    def test_pending_excluded_from_agreement_rate(self, tmp_path):
        end = datetime.now(timezone.utc).date()
        iso = f"{end.strftime('%Y-%m-%d')}T12:00:00Z"
        _seed_entry(
            tmp_path,
            relpath="bumba-contributions/curated/consolidation/x.md",
            decided_at=iso,
            decision="promote",
            actual="pending",
        )
        _seed_entry(
            tmp_path,
            relpath="bumba-contributions/curated/consolidation/y.md",
            decided_at=iso,
            decision="promote",
            actual="promoted",
            actual_at=iso,
        )
        report = aggregate_shadow_window(
            days=14,
            end_date_iso=end.strftime("%Y-%m-%d"),
            log_dir=tmp_path,
        )
        assert report.total_contributions == 2
        assert report.pending_count == 1
        assert report.decided_count == 1
        assert report.agreement_rate == 1.0

    def test_sample_disagreements_capped_at_10(self, tmp_path):
        end = datetime.now(timezone.utc).date()
        # Seed 15 disagreements all on the same day.
        for i in range(15):
            iso = f"{end.strftime('%Y-%m-%d')}T12:{i:02d}:00Z"
            _seed_entry(
                tmp_path,
                relpath=f"bumba-contributions/curated/consolidation/d{i}.md",
                decided_at=iso,
                decision="promote",
                actual="rejected",
                actual_at=iso,
            )
        report = aggregate_shadow_window(
            days=14,
            end_date_iso=end.strftime("%Y-%m-%d"),
            log_dir=tmp_path,
        )
        assert report.disagreement_count == 15
        assert len(report.sample_disagreements) == 10


# ---------------- ShadowRouter ---------------- #


class _FakeWikiRepo:
    """Minimal stand-in — ShadowRouter only holds the reference."""

    def __init__(self, vault_root: Path) -> None:
        self.vault_root = vault_root


class TestShadowRouter:
    def test_observe_writes_entry_and_does_not_mutate_vault(self, tmp_path):
        vault = tmp_path / "vault"
        vault.mkdir()
        log_dir = tmp_path / "shadow"
        router = ShadowRouter(
            wiki_repo=_FakeWikiRepo(vault),
            log_dir=log_dir,
        )
        before = sorted(vault.rglob("*"))
        contribution = _StubContribution(
            relpath=(
                "bumba-contributions/curated/consolidation/2026-05-01-digest.md"
            ),
            body=" ".join(["word"] * 150),
        )
        entry = router.observe(contribution)
        assert entry.shadow_decision == "promote"
        assert entry.actual_outcome == "pending"
        # Log file present.
        assert any(log_dir.rglob("shadow-*.jsonl"))
        # Vault untouched.
        after = sorted(vault.rglob("*"))
        assert before == after

    def test_correlate_promotion_updates_entry(self, tmp_path):
        vault = tmp_path / "vault"
        vault.mkdir()
        log_dir = tmp_path / "shadow"
        router = ShadowRouter(
            wiki_repo=_FakeWikiRepo(vault),
            log_dir=log_dir,
        )
        contribution = _StubContribution(
            relpath=(
                "bumba-contributions/curated/consolidation/2026-05-01-digest.md"
            ),
            body=" ".join(["word"] * 150),
        )
        router.observe(contribution)
        ok = router.correlate_promotion(
            contribution.relpath,
            decided_at_iso=_utc_now(),
        )
        assert ok is True
        # Re-running correlate is idempotent — second call returns False
        # because the entry is no longer "pending".
        ok2 = router.correlate_promotion(
            contribution.relpath,
            decided_at_iso=_utc_now(),
        )
        assert ok2 is False

    def test_observe_all_records_each(self, tmp_path):
        vault = tmp_path / "vault"
        vault.mkdir()
        log_dir = tmp_path / "shadow"
        router = ShadowRouter(
            wiki_repo=_FakeWikiRepo(vault),
            log_dir=log_dir,
        )
        contributions = [
            _StubContribution(
                relpath=(
                    f"bumba-contributions/curated/consolidation/{i}.md"
                ),
                body=" ".join(["word"] * 150),
            )
            for i in range(3)
        ]
        entries = router.observe_all(contributions)
        assert len(entries) == 3


# ---------------- format_shadow_report (recommendation gate) ---------------- #


class TestFormatShadowReport:
    def _report(self, *, decided: int, agreement: int, threshold: float = 0.90):
        rate = (agreement / decided) if decided else 0.0
        return ShadowReport(
            window_days=14,
            window_start_iso="2026-04-18",
            window_end_iso="2026-05-01",
            total_contributions=decided,
            pending_count=0,
            decided_count=decided,
            agreement_count=agreement,
            disagreement_count=decided - agreement,
            agreement_rate=rate,
            by_decision={
                "promote": {
                    "total": decided,
                    "agreement": agreement,
                    "disagreement": decided - agreement,
                    "pending": 0,
                },
                "leave_curated": {
                    "total": 0,
                    "agreement": 0,
                    "disagreement": 0,
                    "pending": 0,
                },
                "reject": {
                    "total": 0,
                    "agreement": 0,
                    "disagreement": 0,
                    "pending": 0,
                },
            },
            sample_disagreements=tuple(),
        )

    def test_recommendation_ready_to_flip_at_threshold(self):
        report = self._report(decided=60, agreement=55)
        out = format_shadow_report(report, promote_threshold=0.90, decided_floor=50)
        assert "ready to flip" in out

    def test_recommendation_keep_observing_below_threshold(self):
        report = self._report(decided=60, agreement=40)
        out = format_shadow_report(report, promote_threshold=0.90, decided_floor=50)
        assert "keep observing" in out

    def test_recommendation_keep_observing_below_decided_floor(self):
        report = self._report(decided=10, agreement=10)
        out = format_shadow_report(report, promote_threshold=0.90, decided_floor=50)
        assert "keep observing" in out


# ---------------- /shadow_report command integration ---------------- #


class TestShadowReportCommand:
    """Lightweight integration: the command renders the threshold gate
    correctly when given a wired router + a report with seeded entries."""

    @pytest.mark.asyncio
    async def test_shadow_report_when_router_unwired(self, tmp_path):
        from unittest.mock import MagicMock

        # Local import keeps the test independent of fixture order.
        from bridge.commands import CommandHandler

        ch = CommandHandler(
            db=MagicMock(),
            queue=MagicMock(),
            session_manager=MagicMock(),
        )
        # Simulate gating: cfg present, but shadow_router unwired.
        cfg = MagicMock()
        cfg.second_brain_shadow_router_enabled = True
        cfg.second_brain_shadow_router_window_days = 14
        cfg.second_brain_shadow_router_promote_threshold = 0.90
        app = MagicMock()
        app.config = cfg
        ch.set_app(app)

        result = await ch._cmd_shadow_report("chat-1", "")
        assert "not enabled" in result.lower()

    @pytest.mark.asyncio
    async def test_shadow_report_renders_when_wired(self, tmp_path):
        from unittest.mock import MagicMock

        from bridge.commands import CommandHandler

        # Wire a router with seeded entries.
        log_dir = tmp_path / "shadow"
        end = datetime.now(timezone.utc).date()
        for i in range(60):
            iso = f"{end.strftime('%Y-%m-%d')}T12:{i // 60:02d}:{i % 60:02d}Z"
            _seed_entry(
                log_dir,
                relpath=(
                    f"bumba-contributions/curated/consolidation/n{i}.md"
                ),
                decided_at=iso,
                decision="promote",
                actual="promoted",
                actual_at=iso,
            )

        router = ShadowRouter(
            wiki_repo=_FakeWikiRepo(tmp_path),
            log_dir=log_dir,
        )

        ch = CommandHandler(
            db=MagicMock(),
            queue=MagicMock(),
            session_manager=MagicMock(),
        )
        cfg = MagicMock()
        cfg.second_brain_shadow_router_enabled = True
        cfg.second_brain_shadow_router_window_days = 14
        cfg.second_brain_shadow_router_promote_threshold = 0.90
        app = MagicMock()
        app.config = cfg
        ch.set_app(app)
        ch.set_shadow_router(router)

        result = await ch._cmd_shadow_report("chat-1", "")
        assert "Shadow Router Report" in result
        assert "ready to flip" in result
