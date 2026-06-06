"""Rubric-gate evidence harness — 14-day cost & ATS-yield observation.

Sprint 06.08 of the 2026-04-25 reference-audit bundle.

Sprint 06.03 (PR #1130) shipped the rubric gate that filters low-fit
listings before paying for a cover letter. This module is the evidence
harness that proves (or refutes) the savings claim across a 14-day soak.

Two observable streams:

1. **Gate decisions** — one record per ``_apply_rubric_gate`` classification
   ("passed" / "filtered" / "not_applicable") with the rubric grade,
   score, threshold-at-decision, eval cost, and the *estimated* cost we
   would have paid for the cover letter if we had proceeded.

2. **Cover-letter outcomes** — recorded after a cover letter is generated
   (post-gate) with the *actual* cost we paid and whether the listing was
   submitted.

3. **ATS yield** — operator-tracker signals (interview / response /
   rejection) recorded by scanning Notion for status changes since the
   last scan cursor.

All three streams are persisted as append-only JSONL under
``data/rubric-evidence/YYYY-MM-DD.jsonl`` with a record-kind tag. A
rolling 14-day :class:`RollingSummary` is materialized on demand and
written atomically to ``data/rubric-evidence/summary.json`` so the
``/rubric_evidence`` operator command + Sprint 06.08 Discord report can
render fast without re-aggregating raw lines.

Idempotency: every append is keyed by ``(listing_id, decided_at_iso)``
(or analogous primary key). Replays — eg. a cron retry — never
double-count.

Failure mode: every public ``append_*`` swallows IO errors after
logging. Evidence collection must NEVER block the cron.

Concept-only port (career-ops, MIT). Subprocess and dataclass shapes
follow the surrounding module style — no code copied verbatim.
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable, Optional

log = logging.getLogger(__name__)

# Default location relative to the resolved data_dir (eg.
# ``bridge.paths.data_root() / "rubric-evidence"``). Tests pass an explicit
# ``evidence_dir`` so production defaults never leak.
EVIDENCE_DIR = Path("data/rubric-evidence")
SUMMARY_FILENAME = "summary.json"
LAST_SCAN_FILENAME = ".last_notion_scan"

WINDOW_DAYS_DEFAULT = 14

# Record-kind discriminators (one JSONL file holds all three streams).
_KIND_DECISION = "gate_decision"
_KIND_COVER_LETTER = "cover_letter_outcome"
_KIND_ATS_YIELD = "ats_yield_event"

# Decision tags emitted by ``_apply_rubric_gate``. Kept loose (str) on the
# dataclass so the Notion override flow can extend without breaking the
# schema.
DECISION_PASSED = "passed"
DECISION_FILTERED = "filtered"
DECISION_NOT_APPLICABLE = "not_applicable"
# P8.6 / MD-19: distinguish a Haiku-eval crash (grade is None because the
# eval call raised) from a true low-grade reject. Without this tag, both
# look like ``DECISION_FILTERED`` to the daily roll-up and the operator
# can't tell whether the rubric is doing real work or silently failing.
DECISION_FAILED_EVAL = "failed_eval"


# ---------------------------------------------------------------------------
# Frozen dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class GateDecision:
    """One rubric gate decision — emitted at gate time.

    ``rubric_grade`` is the empty string when the gate is disabled and the
    listing flowed through unevaluated. ``rubric_score`` is 0.0 in that
    case. ``threshold`` is the operator-tunable threshold *at decision
    time* so a later threshold change does not retroactively rewrite the
    record.
    """

    listing_id: str
    decided_at_iso: str
    rubric_grade: str
    rubric_score: float
    threshold: str
    decision: str
    rubric_cost_usd: float
    estimated_cover_letter_cost_usd: float


@dataclass(frozen=True)
class CoverLetterOutcome:
    """Recorded after cover-letter generation completes."""

    listing_id: str
    completed_at_iso: str
    actual_cost_usd: float
    submitted: bool


@dataclass(frozen=True)
class ATSYieldEvent:
    """Recorded when the operator marks an interview / response / rejection."""

    listing_id: str
    event_at_iso: str
    event_kind: str  # "interview_scheduled" / "response_received" / "rejection"


@dataclass(frozen=True)
class DailyEvidenceRecord:
    """One day's aggregate."""

    date: str  # YYYY-MM-DD
    decisions_count: int
    passed_count: int
    filtered_count: int
    not_applicable_count: int
    rubric_total_cost_usd: float
    cover_letter_total_cost_usd: float
    estimated_savings_usd: float
    ats_yield_events_count: int
    # P8.6 / MD-19: count of decisions where the Haiku eval call raised
    # (grade is None at gate time). Distinguishes silent-eval-failure
    # from a true low-grade reject. Defaults to 0 for back-compat with
    # records persisted before this field existed.
    failed_eval_count: int = 0


@dataclass(frozen=True)
class RollingSummary:
    """14-day rolling summary."""

    window_days: int
    window_start: str
    window_end: str
    total_decisions: int
    total_passed: int
    total_filtered: int
    total_rubric_cost_usd: float
    total_cover_letter_cost_usd: float
    total_estimated_savings_usd: float
    total_ats_yield_events: int
    pass_rate: float
    daily_records: tuple[DailyEvidenceRecord, ...] = field(default_factory=tuple)
    # P8.6 / MD-19: surfaces the rolling count of Haiku-eval failures so
    # the operator notices when the rubric's silently degrading. Default
    # 0 keeps back-compat with summary.json files written pre-P8.6.
    total_failed_eval: int = 0


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------


def _resolve_dir(evidence_dir: Path | str) -> Path:
    p = Path(evidence_dir)
    p.mkdir(parents=True, exist_ok=True)
    return p


def _date_path(evidence_dir: Path, date_iso: str) -> Path:
    return evidence_dir / f"{date_iso}.jsonl"


def _date_from_iso_ts(ts_iso: str) -> str:
    """Pull a YYYY-MM-DD prefix from an ISO8601 timestamp.

    Tolerates trailing 'Z', timezone offsets, and degenerate inputs by
    falling back to UTC today rather than raising — evidence emission
    must never crash the cron.
    """
    try:
        # ``fromisoformat`` accepts +00:00 but not 'Z' before 3.11.
        cleaned = ts_iso.replace("Z", "+00:00")
        return datetime.fromisoformat(cleaned).date().isoformat()
    except (TypeError, ValueError):
        return datetime.now(timezone.utc).date().isoformat()


# ---------------------------------------------------------------------------
# Atomic JSONL append (idempotent on listing_id + primary timestamp)
# ---------------------------------------------------------------------------


def _read_jsonl_lines(path: Path) -> list[dict]:
    if not path.exists():
        return []
    out: list[dict] = []
    try:
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                # Defensive: a corrupt line should not poison the rest.
                log.warning("rubric-evidence: skipping malformed line in %s", path.name)
                continue
    except OSError as e:
        log.error("rubric-evidence: failed to read %s: %s", path, e)
    return out


def _atomic_write_jsonl(path: Path, records: Iterable[dict]) -> None:
    """Rewrite ``path`` atomically from ``records`` via a sibling tempfile."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            for rec in records:
                f.write(json.dumps(rec, sort_keys=True))
                f.write("\n")
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _append_idempotent(
    path: Path,
    new_record: dict,
    *,
    dedup_keys: tuple[str, ...],
) -> bool:
    """Append ``new_record`` to ``path`` unless an existing line matches on
    every value in ``dedup_keys``. Returns True when written, False when a
    duplicate was detected.
    """
    existing = _read_jsonl_lines(path)
    target_signature = tuple(new_record.get(k) for k in dedup_keys)
    for rec in existing:
        if tuple(rec.get(k) for k in dedup_keys) == target_signature:
            return False

    existing.append(new_record)
    _atomic_write_jsonl(path, existing)
    return True


# ---------------------------------------------------------------------------
# Public append API
# ---------------------------------------------------------------------------


def append_decision(
    decision: GateDecision,
    *,
    evidence_dir: Path | str = EVIDENCE_DIR,
) -> bool:
    """Atomic append for a :class:`GateDecision`.

    Returns True if the record was written, False if a record with the
    same ``listing_id`` and ``decided_at_iso`` already exists. Never
    raises — IO errors are logged and surfaced as False so the caller can
    keep going.
    """
    try:
        directory = _resolve_dir(evidence_dir)
        date_iso = _date_from_iso_ts(decision.decided_at_iso)
        path = _date_path(directory, date_iso)
        record = {"_kind": _KIND_DECISION, **asdict(decision)}
        return _append_idempotent(
            path,
            record,
            dedup_keys=("_kind", "listing_id", "decided_at_iso"),
        )
    except Exception as e:  # pragma: no cover — defensive net
        log.error("rubric-evidence: append_decision failed: %s", e)
        return False


def append_cover_letter_outcome(
    outcome: CoverLetterOutcome,
    *,
    evidence_dir: Path | str = EVIDENCE_DIR,
) -> bool:
    """Atomic append for a :class:`CoverLetterOutcome`.

    Returns True on write, False on duplicate. Never raises.
    """
    try:
        directory = _resolve_dir(evidence_dir)
        date_iso = _date_from_iso_ts(outcome.completed_at_iso)
        path = _date_path(directory, date_iso)
        record = {"_kind": _KIND_COVER_LETTER, **asdict(outcome)}
        return _append_idempotent(
            path,
            record,
            dedup_keys=("_kind", "listing_id", "completed_at_iso"),
        )
    except Exception as e:  # pragma: no cover — defensive net
        log.error("rubric-evidence: append_cover_letter_outcome failed: %s", e)
        return False


def append_ats_yield(
    event: ATSYieldEvent,
    *,
    evidence_dir: Path | str = EVIDENCE_DIR,
) -> bool:
    """Atomic append for an :class:`ATSYieldEvent`.

    Returns True on write, False on duplicate. Never raises.
    """
    try:
        directory = _resolve_dir(evidence_dir)
        date_iso = _date_from_iso_ts(event.event_at_iso)
        path = _date_path(directory, date_iso)
        record = {"_kind": _KIND_ATS_YIELD, **asdict(event)}
        return _append_idempotent(
            path,
            record,
            dedup_keys=("_kind", "listing_id", "event_at_iso", "event_kind"),
        )
    except Exception as e:  # pragma: no cover — defensive net
        log.error("rubric-evidence: append_ats_yield failed: %s", e)
        return False


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------


def _empty_day(date_iso: str) -> DailyEvidenceRecord:
    return DailyEvidenceRecord(
        date=date_iso,
        decisions_count=0,
        passed_count=0,
        filtered_count=0,
        not_applicable_count=0,
        rubric_total_cost_usd=0.0,
        cover_letter_total_cost_usd=0.0,
        estimated_savings_usd=0.0,
        ats_yield_events_count=0,
        failed_eval_count=0,
    )


def aggregate_day(
    date_iso: str,
    *,
    evidence_dir: Path | str = EVIDENCE_DIR,
) -> DailyEvidenceRecord:
    """Aggregate a single day's JSONL file into a :class:`DailyEvidenceRecord`.

    Missing file → zero record. Malformed lines are skipped (logged).

    Estimated savings = (sum of estimated_cover_letter_cost over filtered
    decisions) - (sum of rubric_cost across all decisions). The rubric
    eval cost is netted across *all* decisions because we paid that even
    for the listings we ultimately let through.
    """
    directory = _resolve_dir(evidence_dir)
    path = _date_path(directory, date_iso)
    records = _read_jsonl_lines(path)
    if not records:
        return _empty_day(date_iso)

    decisions = 0
    passed = 0
    filtered = 0
    not_applicable = 0
    failed_eval = 0
    rubric_cost = 0.0
    cover_letter_cost = 0.0
    filtered_estimated = 0.0
    ats_count = 0

    for rec in records:
        kind = rec.get("_kind")
        if kind == _KIND_DECISION:
            decisions += 1
            decision = str(rec.get("decision", ""))
            if decision == DECISION_PASSED:
                passed += 1
            elif decision == DECISION_FILTERED:
                filtered += 1
                filtered_estimated += float(
                    rec.get("estimated_cover_letter_cost_usd", 0.0) or 0.0
                )
            elif decision == DECISION_NOT_APPLICABLE:
                not_applicable += 1
            elif decision == DECISION_FAILED_EVAL:
                # P8.6 / MD-19: silent rubric eval failure. No cost
                # attribution (we never paid the eval — it raised), so
                # rubric_cost is not incremented for this record.
                failed_eval += 1
            rubric_cost += float(rec.get("rubric_cost_usd", 0.0) or 0.0)
        elif kind == _KIND_COVER_LETTER:
            cover_letter_cost += float(rec.get("actual_cost_usd", 0.0) or 0.0)
        elif kind == _KIND_ATS_YIELD:
            ats_count += 1

    estimated_savings = filtered_estimated - rubric_cost

    return DailyEvidenceRecord(
        date=date_iso,
        decisions_count=decisions,
        passed_count=passed,
        filtered_count=filtered,
        not_applicable_count=not_applicable,
        rubric_total_cost_usd=round(rubric_cost, 6),
        cover_letter_total_cost_usd=round(cover_letter_cost, 6),
        estimated_savings_usd=round(estimated_savings, 6),
        ats_yield_events_count=ats_count,
        failed_eval_count=failed_eval,
    )


def aggregate_window(
    *,
    days: int = WINDOW_DAYS_DEFAULT,
    end_date_iso: Optional[str] = None,
    evidence_dir: Path | str = EVIDENCE_DIR,
) -> RollingSummary:
    """Aggregate ``days`` days ending at ``end_date_iso`` (default: today UTC).

    Writes the result atomically to ``<evidence_dir>/summary.json``.
    Missing daily files contribute a zero record (no exception).
    """
    if days <= 0:
        days = WINDOW_DAYS_DEFAULT
    directory = _resolve_dir(evidence_dir)

    end_date = (
        datetime.fromisoformat(end_date_iso).date()
        if end_date_iso
        else datetime.now(timezone.utc).date()
    )
    start_date = end_date - timedelta(days=days - 1)

    daily: list[DailyEvidenceRecord] = []
    for offset in range(days):
        d = start_date + timedelta(days=offset)
        daily.append(aggregate_day(d.isoformat(), evidence_dir=directory))

    total_decisions = sum(r.decisions_count for r in daily)
    total_passed = sum(r.passed_count for r in daily)
    total_filtered = sum(r.filtered_count for r in daily)
    total_rubric_cost = sum(r.rubric_total_cost_usd for r in daily)
    total_cover_letter_cost = sum(r.cover_letter_total_cost_usd for r in daily)
    total_estimated_savings = sum(r.estimated_savings_usd for r in daily)
    total_ats = sum(r.ats_yield_events_count for r in daily)
    total_failed_eval = sum(r.failed_eval_count for r in daily)

    pass_rate = (total_passed / total_decisions) if total_decisions else 0.0

    summary = RollingSummary(
        window_days=days,
        window_start=start_date.isoformat(),
        window_end=end_date.isoformat(),
        total_decisions=total_decisions,
        total_passed=total_passed,
        total_filtered=total_filtered,
        total_rubric_cost_usd=round(total_rubric_cost, 6),
        total_cover_letter_cost_usd=round(total_cover_letter_cost, 6),
        total_estimated_savings_usd=round(total_estimated_savings, 6),
        total_ats_yield_events=total_ats,
        pass_rate=round(pass_rate, 6),
        daily_records=tuple(daily),
        total_failed_eval=total_failed_eval,
    )

    _write_summary(directory, summary)
    return summary


def _write_summary(evidence_dir: Path, summary: RollingSummary) -> None:
    """Atomic write to ``<evidence_dir>/summary.json``."""
    path = evidence_dir / SUMMARY_FILENAME
    payload = {
        "window_days": summary.window_days,
        "window_start": summary.window_start,
        "window_end": summary.window_end,
        "total_decisions": summary.total_decisions,
        "total_passed": summary.total_passed,
        "total_filtered": summary.total_filtered,
        "total_rubric_cost_usd": summary.total_rubric_cost_usd,
        "total_cover_letter_cost_usd": summary.total_cover_letter_cost_usd,
        "total_estimated_savings_usd": summary.total_estimated_savings_usd,
        "total_ats_yield_events": summary.total_ats_yield_events,
        "pass_rate": summary.pass_rate,
        "total_failed_eval": summary.total_failed_eval,
        "daily_records": [asdict(r) for r in summary.daily_records],
    }
    fd, tmp = tempfile.mkstemp(dir=evidence_dir, prefix=SUMMARY_FILENAME + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(payload, f, sort_keys=True, indent=2)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def load_summary(
    *,
    evidence_dir: Path | str = EVIDENCE_DIR,
) -> Optional[RollingSummary]:
    """Read ``<evidence_dir>/summary.json`` back into a :class:`RollingSummary`.

    Returns None when absent or malformed (logged).
    """
    directory = Path(evidence_dir)
    path = directory / SUMMARY_FILENAME
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        log.error("rubric-evidence: failed to read %s: %s", path, e)
        return None

    daily_raw = data.get("daily_records", []) or []
    daily: list[DailyEvidenceRecord] = []
    for entry in daily_raw:
        if not isinstance(entry, dict):
            continue
        try:
            daily.append(
                DailyEvidenceRecord(
                    date=str(entry.get("date", "")),
                    decisions_count=int(entry.get("decisions_count", 0) or 0),
                    passed_count=int(entry.get("passed_count", 0) or 0),
                    filtered_count=int(entry.get("filtered_count", 0) or 0),
                    not_applicable_count=int(entry.get("not_applicable_count", 0) or 0),
                    rubric_total_cost_usd=float(entry.get("rubric_total_cost_usd", 0.0) or 0.0),
                    cover_letter_total_cost_usd=float(
                        entry.get("cover_letter_total_cost_usd", 0.0) or 0.0
                    ),
                    estimated_savings_usd=float(entry.get("estimated_savings_usd", 0.0) or 0.0),
                    ats_yield_events_count=int(entry.get("ats_yield_events_count", 0) or 0),
                    failed_eval_count=int(entry.get("failed_eval_count", 0) or 0),
                )
            )
        except (TypeError, ValueError):
            continue

    try:
        return RollingSummary(
            window_days=int(data.get("window_days", WINDOW_DAYS_DEFAULT)),
            window_start=str(data.get("window_start", "")),
            window_end=str(data.get("window_end", "")),
            total_decisions=int(data.get("total_decisions", 0) or 0),
            total_passed=int(data.get("total_passed", 0) or 0),
            total_filtered=int(data.get("total_filtered", 0) or 0),
            total_rubric_cost_usd=float(data.get("total_rubric_cost_usd", 0.0) or 0.0),
            total_cover_letter_cost_usd=float(
                data.get("total_cover_letter_cost_usd", 0.0) or 0.0
            ),
            total_estimated_savings_usd=float(
                data.get("total_estimated_savings_usd", 0.0) or 0.0
            ),
            total_ats_yield_events=int(data.get("total_ats_yield_events", 0) or 0),
            pass_rate=float(data.get("pass_rate", 0.0) or 0.0),
            daily_records=tuple(daily),
            total_failed_eval=int(data.get("total_failed_eval", 0) or 0),
        )
    except (TypeError, ValueError) as e:
        log.error("rubric-evidence: malformed summary.json: %s", e)
        return None


# ---------------------------------------------------------------------------
# Notion scan-cursor persistence (used by JobSearchAgent._scan_notion_for_yield_events)
# ---------------------------------------------------------------------------


def read_last_notion_scan(*, evidence_dir: Path | str = EVIDENCE_DIR) -> Optional[str]:
    """Return the ISO8601 timestamp of the last Notion yield-scan, or None."""
    directory = Path(evidence_dir)
    path = directory / LAST_SCAN_FILENAME
    if not path.exists():
        return None
    try:
        text = path.read_text(encoding="utf-8").strip()
        return text or None
    except OSError as e:
        log.error("rubric-evidence: failed to read scan cursor %s: %s", path, e)
        return None


def write_last_notion_scan(
    iso_ts: str,
    *,
    evidence_dir: Path | str = EVIDENCE_DIR,
) -> None:
    """Persist the latest Notion yield-scan cursor atomically."""
    directory = _resolve_dir(evidence_dir)
    path = directory / LAST_SCAN_FILENAME
    fd, tmp = tempfile.mkstemp(dir=directory, prefix=LAST_SCAN_FILENAME + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(iso_ts)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


# ---------------------------------------------------------------------------
# Operator-facing formatter (consumed by /rubric_evidence + Sprint 06.08 report)
# ---------------------------------------------------------------------------


def format_summary_for_discord(summary: Optional[RollingSummary]) -> str:
    """Render a compact Discord-friendly summary string.

    Returns a one-line "no evidence yet" stub when ``summary`` is None or
    has zero decisions — the harness's first day will look like this.
    """
    if summary is None:
        return (
            "No rubric-gate evidence yet — harness has not aggregated a "
            "window. Wait for the next prepare cron + aggregation pass."
        )
    if summary.total_decisions == 0:
        return (
            f"Rubric-gate evidence ({summary.window_days}-day window "
            f"{summary.window_start} → {summary.window_end}): no decisions "
            "recorded yet."
        )

    pass_pct = summary.pass_rate * 100.0
    return (
        f"**Rubric-gate evidence — {summary.window_days}-day window**\n"
        f"Window: {summary.window_start} → {summary.window_end}\n"
        f"Decisions: {summary.total_decisions} "
        f"(passed {summary.total_passed}, filtered {summary.total_filtered}, "
        f"pass rate {pass_pct:.1f}%)\n"
        f"Rubric eval spend: ${summary.total_rubric_cost_usd:.2f}\n"
        f"Cover-letter spend: ${summary.total_cover_letter_cost_usd:.2f}\n"
        f"Estimated savings: ${summary.total_estimated_savings_usd:.2f}\n"
        f"ATS yield events: {summary.total_ats_yield_events}"
    )
