"""Sprint 06.08 — Rubric evidence harness tests.

Spec: docs/specs/2026-04-25-reference-audit/spec-06-08-cost-telemetry-14-day-evidence-gate-savings-ats-yield.md
Issue: #1029

Coverage:
    * append_decision writes JSONL line with frozen-dataclass round-trip
    * append_decision idempotent (same listing_id + decided_at → no duplicate)
    * append_cover_letter_outcome + append_ats_yield round-trip
    * aggregate_day reads correctly; missing file → zero record
    * aggregate_day counts decisions by category correctly
    * aggregate_window 14-day window aggregates daily records
    * aggregate_window writes summary.json atomically (mtime + content)
    * aggregate_window with missing days → those days contribute zero
    * load_summary reads back correctly; absent → None
    * Estimated savings calculation (filtered=10, avg=$1.00, rubric=$0.50 → $9.50)
    * Pass rate calculation (8/10 = 0.8)
    * /rubric_evidence operator command formatting
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
import pytest_asyncio

from job_search.rubric_evidence import (
    DECISION_FILTERED,
    DECISION_NOT_APPLICABLE,
    DECISION_PASSED,
    SUMMARY_FILENAME,
    ATSYieldEvent,
    CoverLetterOutcome,
    GateDecision,
    aggregate_day,
    aggregate_window,
    append_ats_yield,
    append_cover_letter_outcome,
    append_decision,
    format_summary_for_discord,
    load_summary,
    read_last_notion_scan,
    write_last_notion_scan,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def evidence_dir(tmp_path: Path) -> Path:
    d = tmp_path / "rubric-evidence"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _iso(year: int, month: int, day: int, hour: int = 12) -> str:
    return datetime(year, month, day, hour, tzinfo=timezone.utc).isoformat()


def _decision(
    *,
    listing_id: str = "lst-1",
    decided_at_iso: str | None = None,
    grade: str = "B",
    score: float = 3.5,
    threshold: str = "B",
    decision: str = DECISION_PASSED,
    rubric_cost_usd: float = 0.05,
    estimated_cover_letter_cost_usd: float = 1.0,
) -> GateDecision:
    return GateDecision(
        listing_id=listing_id,
        decided_at_iso=decided_at_iso or _iso(2026, 5, 1),
        rubric_grade=grade,
        rubric_score=score,
        threshold=threshold,
        decision=decision,
        rubric_cost_usd=rubric_cost_usd,
        estimated_cover_letter_cost_usd=estimated_cover_letter_cost_usd,
    )


# ---------------------------------------------------------------------------
# append_decision
# ---------------------------------------------------------------------------


class TestAppendDecision:
    def test_writes_jsonl_round_trip(self, evidence_dir: Path) -> None:
        d = _decision(listing_id="lst-A", decided_at_iso=_iso(2026, 5, 1))
        wrote = append_decision(d, evidence_dir=evidence_dir)

        assert wrote is True
        path = evidence_dir / "2026-05-01.jsonl"
        assert path.exists()
        lines = [json.loads(l) for l in path.read_text().splitlines() if l.strip()]
        assert len(lines) == 1
        rec = lines[0]
        assert rec["_kind"] == "gate_decision"
        assert rec["listing_id"] == "lst-A"
        assert rec["rubric_grade"] == "B"
        assert rec["rubric_score"] == 3.5
        assert rec["threshold"] == "B"
        assert rec["decision"] == DECISION_PASSED
        assert rec["rubric_cost_usd"] == 0.05
        assert rec["estimated_cover_letter_cost_usd"] == 1.0

    def test_idempotent_on_listing_id_and_decided_at(self, evidence_dir: Path) -> None:
        d = _decision(listing_id="lst-A", decided_at_iso=_iso(2026, 5, 1))
        first = append_decision(d, evidence_dir=evidence_dir)
        second = append_decision(d, evidence_dir=evidence_dir)

        assert first is True
        assert second is False  # duplicate detected

        path = evidence_dir / "2026-05-01.jsonl"
        lines = [l for l in path.read_text().splitlines() if l.strip()]
        assert len(lines) == 1

    def test_different_decided_at_writes_separate_record(self, evidence_dir: Path) -> None:
        d1 = _decision(listing_id="lst-A", decided_at_iso=_iso(2026, 5, 1, 9))
        d2 = _decision(listing_id="lst-A", decided_at_iso=_iso(2026, 5, 1, 11))
        assert append_decision(d1, evidence_dir=evidence_dir) is True
        assert append_decision(d2, evidence_dir=evidence_dir) is True

        path = evidence_dir / "2026-05-01.jsonl"
        lines = [l for l in path.read_text().splitlines() if l.strip()]
        assert len(lines) == 2


# ---------------------------------------------------------------------------
# append_cover_letter_outcome + append_ats_yield round-trip
# ---------------------------------------------------------------------------


class TestAppendCoverLetterOutcome:
    def test_round_trip(self, evidence_dir: Path) -> None:
        outcome = CoverLetterOutcome(
            listing_id="lst-A",
            completed_at_iso=_iso(2026, 5, 1),
            actual_cost_usd=1.23,
            submitted=True,
        )
        assert append_cover_letter_outcome(outcome, evidence_dir=evidence_dir) is True

        path = evidence_dir / "2026-05-01.jsonl"
        rec = json.loads(path.read_text().splitlines()[0])
        assert rec["_kind"] == "cover_letter_outcome"
        assert rec["listing_id"] == "lst-A"
        assert rec["actual_cost_usd"] == 1.23
        assert rec["submitted"] is True

    def test_idempotent(self, evidence_dir: Path) -> None:
        outcome = CoverLetterOutcome(
            listing_id="lst-A",
            completed_at_iso=_iso(2026, 5, 1),
            actual_cost_usd=1.0,
            submitted=False,
        )
        assert append_cover_letter_outcome(outcome, evidence_dir=evidence_dir) is True
        assert append_cover_letter_outcome(outcome, evidence_dir=evidence_dir) is False


class TestAppendATSYield:
    def test_round_trip(self, evidence_dir: Path) -> None:
        event = ATSYieldEvent(
            listing_id="lst-A",
            event_at_iso=_iso(2026, 5, 1),
            event_kind="interview_scheduled",
        )
        assert append_ats_yield(event, evidence_dir=evidence_dir) is True

        path = evidence_dir / "2026-05-01.jsonl"
        rec = json.loads(path.read_text().splitlines()[0])
        assert rec["_kind"] == "ats_yield_event"
        assert rec["event_kind"] == "interview_scheduled"

    def test_idempotent_on_kind(self, evidence_dir: Path) -> None:
        event = ATSYieldEvent(
            listing_id="lst-A",
            event_at_iso=_iso(2026, 5, 1),
            event_kind="interview_scheduled",
        )
        assert append_ats_yield(event, evidence_dir=evidence_dir) is True
        assert append_ats_yield(event, evidence_dir=evidence_dir) is False
        # Different kind on same listing+ts should NOT collide
        other = ATSYieldEvent(
            listing_id="lst-A",
            event_at_iso=_iso(2026, 5, 1),
            event_kind="rejection",
        )
        assert append_ats_yield(other, evidence_dir=evidence_dir) is True


# ---------------------------------------------------------------------------
# aggregate_day
# ---------------------------------------------------------------------------


class TestAggregateDay:
    def test_missing_file_returns_zero_record(self, evidence_dir: Path) -> None:
        rec = aggregate_day("2026-05-01", evidence_dir=evidence_dir)
        assert rec.date == "2026-05-01"
        assert rec.decisions_count == 0
        assert rec.passed_count == 0
        assert rec.filtered_count == 0
        assert rec.rubric_total_cost_usd == 0.0
        assert rec.cover_letter_total_cost_usd == 0.0
        assert rec.estimated_savings_usd == 0.0
        assert rec.ats_yield_events_count == 0

    def test_counts_decisions_by_category(self, evidence_dir: Path) -> None:
        # 3 passed, 2 filtered, 1 not_applicable
        for i, decision in enumerate(
            [DECISION_PASSED] * 3 + [DECISION_FILTERED] * 2 + [DECISION_NOT_APPLICABLE]
        ):
            append_decision(
                _decision(
                    listing_id=f"lst-{i}",
                    decided_at_iso=_iso(2026, 5, 1, hour=8 + i),
                    decision=decision,
                ),
                evidence_dir=evidence_dir,
            )

        rec = aggregate_day("2026-05-01", evidence_dir=evidence_dir)
        assert rec.decisions_count == 6
        assert rec.passed_count == 3
        assert rec.filtered_count == 2
        assert rec.not_applicable_count == 1

    def test_estimated_savings_calculation(self, evidence_dir: Path) -> None:
        """filtered=10 @ $1.00 each, rubric_cost across 10 evals @ $0.05 each
        → estimated_savings = 10*1.00 - 10*0.05 = 9.50.
        """
        for i in range(10):
            append_decision(
                _decision(
                    listing_id=f"lst-{i}",
                    decided_at_iso=_iso(2026, 5, 1, hour=i),
                    decision=DECISION_FILTERED,
                    rubric_cost_usd=0.05,
                    estimated_cover_letter_cost_usd=1.00,
                ),
                evidence_dir=evidence_dir,
            )

        rec = aggregate_day("2026-05-01", evidence_dir=evidence_dir)
        assert rec.filtered_count == 10
        assert rec.rubric_total_cost_usd == pytest.approx(0.5)
        assert rec.estimated_savings_usd == pytest.approx(9.5)

    def test_aggregates_cover_letter_costs_and_yield_events(
        self, evidence_dir: Path
    ) -> None:
        # one passed + one cover letter outcome + one yield event
        append_decision(
            _decision(
                listing_id="lst-A",
                decided_at_iso=_iso(2026, 5, 1, 9),
                decision=DECISION_PASSED,
            ),
            evidence_dir=evidence_dir,
        )
        append_cover_letter_outcome(
            CoverLetterOutcome(
                listing_id="lst-A",
                completed_at_iso=_iso(2026, 5, 1, 10),
                actual_cost_usd=1.20,
                submitted=True,
            ),
            evidence_dir=evidence_dir,
        )
        append_ats_yield(
            ATSYieldEvent(
                listing_id="lst-A",
                event_at_iso=_iso(2026, 5, 1, 11),
                event_kind="interview_scheduled",
            ),
            evidence_dir=evidence_dir,
        )

        rec = aggregate_day("2026-05-01", evidence_dir=evidence_dir)
        assert rec.cover_letter_total_cost_usd == pytest.approx(1.20)
        assert rec.ats_yield_events_count == 1


# ---------------------------------------------------------------------------
# aggregate_window + summary persistence
# ---------------------------------------------------------------------------


class TestAggregateWindow:
    def test_pass_rate_calculation(self, evidence_dir: Path) -> None:
        # 8 passed + 2 filtered = 10 decisions, pass_rate = 0.8
        end = datetime(2026, 5, 14, tzinfo=timezone.utc).date()
        for i in range(8):
            append_decision(
                _decision(
                    listing_id=f"lst-p{i}",
                    decided_at_iso=_iso(2026, 5, 14, hour=i),
                    decision=DECISION_PASSED,
                ),
                evidence_dir=evidence_dir,
            )
        for i in range(2):
            append_decision(
                _decision(
                    listing_id=f"lst-f{i}",
                    decided_at_iso=_iso(2026, 5, 14, hour=10 + i),
                    decision=DECISION_FILTERED,
                ),
                evidence_dir=evidence_dir,
            )

        summary = aggregate_window(
            days=14, end_date_iso=end.isoformat(), evidence_dir=evidence_dir
        )
        assert summary.total_decisions == 10
        assert summary.total_passed == 8
        assert summary.total_filtered == 2
        assert summary.pass_rate == pytest.approx(0.8)

    def test_14_day_window_with_missing_days(self, evidence_dir: Path) -> None:
        """Days with no JSONL contribute zero — never raise."""
        # Only populate 2 days; the other 12 should be zero records
        append_decision(
            _decision(
                listing_id="lst-A",
                decided_at_iso=_iso(2026, 5, 1),
                decision=DECISION_PASSED,
            ),
            evidence_dir=evidence_dir,
        )
        append_decision(
            _decision(
                listing_id="lst-B",
                decided_at_iso=_iso(2026, 5, 14),
                decision=DECISION_FILTERED,
            ),
            evidence_dir=evidence_dir,
        )

        summary = aggregate_window(
            days=14, end_date_iso="2026-05-14", evidence_dir=evidence_dir
        )
        assert summary.window_days == 14
        assert summary.window_start == "2026-05-01"
        assert summary.window_end == "2026-05-14"
        assert len(summary.daily_records) == 14
        assert summary.total_decisions == 2

    def test_writes_summary_json_atomically(self, evidence_dir: Path) -> None:
        append_decision(
            _decision(
                listing_id="lst-A",
                decided_at_iso=_iso(2026, 5, 1),
                decision=DECISION_PASSED,
            ),
            evidence_dir=evidence_dir,
        )
        summary = aggregate_window(
            days=14, end_date_iso="2026-05-14", evidence_dir=evidence_dir
        )

        summary_path = evidence_dir / SUMMARY_FILENAME
        assert summary_path.exists()
        mtime_before = summary_path.stat().st_mtime
        # Verify JSON shape
        payload = json.loads(summary_path.read_text())
        assert payload["window_days"] == 14
        assert payload["total_decisions"] == 1
        assert payload["total_passed"] == 1
        assert isinstance(payload["daily_records"], list)
        assert len(payload["daily_records"]) == 14

        # Re-aggregate — should rewrite the file (mtime advances or stays equal,
        # but content is consistent).
        summary2 = aggregate_window(
            days=14, end_date_iso="2026-05-14", evidence_dir=evidence_dir
        )
        assert summary2.total_decisions == summary.total_decisions
        # Verify temp files have been cleaned up (no .tmp left over)
        leftover = list(evidence_dir.glob(SUMMARY_FILENAME + ".*"))
        assert leftover == [], f"orphan tempfiles: {leftover}"
        assert summary_path.stat().st_mtime >= mtime_before


# ---------------------------------------------------------------------------
# load_summary
# ---------------------------------------------------------------------------


class TestLoadSummary:
    def test_absent_returns_none(self, evidence_dir: Path) -> None:
        assert load_summary(evidence_dir=evidence_dir) is None

    def test_round_trip(self, evidence_dir: Path) -> None:
        append_decision(
            _decision(
                listing_id="lst-A",
                decided_at_iso=_iso(2026, 5, 14),
                decision=DECISION_PASSED,
            ),
            evidence_dir=evidence_dir,
        )
        original = aggregate_window(
            days=14, end_date_iso="2026-05-14", evidence_dir=evidence_dir
        )
        loaded = load_summary(evidence_dir=evidence_dir)

        assert loaded is not None
        assert loaded.window_days == original.window_days
        assert loaded.total_decisions == original.total_decisions
        assert loaded.total_passed == original.total_passed
        assert loaded.pass_rate == original.pass_rate
        assert len(loaded.daily_records) == 14


# ---------------------------------------------------------------------------
# Notion scan-cursor persistence
# ---------------------------------------------------------------------------


class TestScanCursor:
    def test_round_trip(self, evidence_dir: Path) -> None:
        assert read_last_notion_scan(evidence_dir=evidence_dir) is None
        ts = _iso(2026, 5, 14, 12)
        write_last_notion_scan(ts, evidence_dir=evidence_dir)
        assert read_last_notion_scan(evidence_dir=evidence_dir) == ts


# ---------------------------------------------------------------------------
# format_summary_for_discord
# ---------------------------------------------------------------------------


class TestFormatSummary:
    def test_none_summary_returns_no_evidence_message(self) -> None:
        text = format_summary_for_discord(None)
        assert "no rubric-gate evidence" in text.lower()

    def test_zero_decisions_message(self, evidence_dir: Path) -> None:
        summary = aggregate_window(
            days=14, end_date_iso="2026-05-14", evidence_dir=evidence_dir
        )
        text = format_summary_for_discord(summary)
        assert "no decisions" in text.lower()

    def test_populated_summary_renders_metrics(self, evidence_dir: Path) -> None:
        for i in range(8):
            append_decision(
                _decision(
                    listing_id=f"lst-p{i}",
                    decided_at_iso=_iso(2026, 5, 14, hour=i),
                    decision=DECISION_PASSED,
                ),
                evidence_dir=evidence_dir,
            )
        for i in range(2):
            append_decision(
                _decision(
                    listing_id=f"lst-f{i}",
                    decided_at_iso=_iso(2026, 5, 14, hour=10 + i),
                    decision=DECISION_FILTERED,
                    rubric_cost_usd=0.05,
                    estimated_cover_letter_cost_usd=1.0,
                ),
                evidence_dir=evidence_dir,
            )
        summary = aggregate_window(
            days=14, end_date_iso="2026-05-14", evidence_dir=evidence_dir
        )
        text = format_summary_for_discord(summary)

        assert "Rubric-gate evidence" in text
        assert "Decisions: 10" in text
        assert "passed 8" in text
        assert "filtered 2" in text
        assert "80.0%" in text
        assert "Estimated savings:" in text


# ---------------------------------------------------------------------------
# /rubric_evidence operator command
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def cmd_handler(migrated_db, message_queue, session_manager):
    from bridge.commands import CommandHandler as CmdHandler

    return CmdHandler(
        db=migrated_db,
        queue=message_queue,
        session_manager=session_manager,
        claude_runner=None,
    )


class TestRubricEvidenceCommand:
    @pytest.mark.asyncio
    async def test_returns_no_evidence_when_empty(self, cmd_handler) -> None:
        result = await cmd_handler.handle("chat-1", "rubric_evidence", "cached")
        # Either "no rubric-gate evidence" (no summary written) or "no decisions"
        # (summary aggregated to all-zero) is acceptable. The point is the
        # command does not crash and signals empty state.
        assert isinstance(result, str)
        assert (
            "no rubric-gate evidence" in result.lower()
            or "no decisions" in result.lower()
        )

    @pytest.mark.asyncio
    async def test_aggregates_and_renders(
        self, cmd_handler, migrated_db, evidence_dir: Path
    ) -> None:
        # Force the command's evidence_dir resolution to point at our tmp
        # location by writing decisions to the path it will scan.
        data_dir = Path(migrated_db.db_path).parent
        target = data_dir / "rubric-evidence"
        target.mkdir(parents=True, exist_ok=True)
        # 14-day window ending today, anchored to UTC.
        today = datetime.now(timezone.utc).date()
        ts = datetime(today.year, today.month, today.day, 12, tzinfo=timezone.utc).isoformat()
        append_decision(
            _decision(
                listing_id="lst-A",
                decided_at_iso=ts,
                decision=DECISION_PASSED,
            ),
            evidence_dir=target,
        )

        result = await cmd_handler.handle("chat-1", "rubric_evidence", "")
        assert "Rubric-gate evidence" in result
        assert "Decisions: 1" in result
