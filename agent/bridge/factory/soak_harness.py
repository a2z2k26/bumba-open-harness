"""Dark Factory soak harness — 14-day shadow + 5-issue manual verification.

Sprint 14.11 — Plan 14 Phase 6 (production-enable gate).

Concept-only port of coleam00/dark-factory-experiment (no LICENSE — no
source copy). Sprints 14.04 → 14.10 built the loop; this sprint is the
gate that decides whether the operator flips the loop from observe-only
to act-on-issues.

The soak harness wraps :class:`bridge.services.factory_orchestrator.FactoryOrchestrator`'s
pipeline (implement → quality → validate → synthesize) but **never acts**.
Each shadow tick:

  1. Picks ``factory:accepted`` issues but does NOT transition them.
  2. Runs the full pipeline through the orchestrator's machinery.
  3. Persists the synthesizer's would-be outcome to a soak log.
  4. Surfaces the entries that were written this tick.

The soak log is JSONL at ``data/factory-soak/soak-YYYY-MM-DD.jsonl``,
keyed by ``(issue_number, processed_at_iso)`` for idempotent re-runs.

After 5 representative issues have been processed and verified (the
operator confirms the factory's would-have-done call against the
operator's eventual decision), :func:`aggregate_soak_window` reports
``ready_to_enable=True`` once the correctness rate clears the floor and
14 days have elapsed.

This module is observe-only. It does not call the GitHub state machine,
does not comment on PRs, and does not mark draft PRs ready. Distinct
module, distinct flag (``factory_soak_harness_enabled``) from the
orchestrator's production-action flag (``factory_orchestrator_enabled``).
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import tempfile
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal, Optional

logger = logging.getLogger(__name__)


# ── Type aliases + constants ─────────────────────────────────────────────


ActionTaken = Literal["none", "would_proceed", "would_escalate"]
OperatorVerification = Literal["pending", "correct", "incorrect", "skipped"]

SOAK_LOG_DIR = Path("data/factory-soak")
SOAK_LOG_NAME_FMT = "soak-{date}.jsonl"  # YYYY-MM-DD


# ── Frozen dataclasses ───────────────────────────────────────────────────


@dataclass(frozen=True)
class SoakEntry:
    """One issue's soak record.

    Frozen so the verification-update path cannot accidentally mutate the
    in-memory copy while rewriting the day's JSONL.

    ``processed_at_iso`` is the second half of the dedup signature so the
    same issue can appear in the log twice if reprocessed on a later tick
    (intentional — we track each shadow run separately, not just the
    most-recent verdict).
    """

    issue_number: int
    issue_title: str
    processed_at_iso: str
    synthesis_outcome: str  # FactorySynthesisOutcome string ("ready_for_operator", etc.)
    rule_fired: int
    block_reasons: tuple[str, ...]
    advise_reasons: tuple[str, ...]
    would_action: ActionTaken
    cost_usd: float
    duration_seconds: float
    operator_verification: OperatorVerification = "pending"
    operator_verification_at_iso: Optional[str] = None
    operator_notes: str = ""


@dataclass(frozen=True)
class SoakReport:
    """14-day soak summary + verification status.

    ``ready_to_enable`` fires only when ALL three apply:

      * window covers ≥ 14 days (``window_days``),
      * verified-correct count ≥ ``min_verified_count`` (default 5),
      * correctness rate ≥ ``min_correctness_rate`` (default 0.80).

    ``correctness_rate`` divides ``verified_correct`` by
    ``(verified_correct + verified_incorrect)`` — pending and skipped
    entries do not count for or against. Zero denominator → 0.0 (not
    NaN, so the report stays JSON-clean).
    """

    window_days: int
    window_start_iso: str
    window_end_iso: str
    total_issues_processed: int
    pending_verification: int
    verified_correct: int
    verified_incorrect: int
    skipped: int
    correctness_rate: float
    total_cost_usd: float
    by_outcome: dict[str, int] = field(default_factory=dict)
    sample_pending: tuple[SoakEntry, ...] = field(default_factory=tuple)
    ready_to_enable: bool = False
    ready_reason: str = ""


# ── Path helpers ─────────────────────────────────────────────────────────


def _resolve_dir(log_dir: Path | str) -> Path:
    p = Path(log_dir)
    p.mkdir(parents=True, exist_ok=True)
    return p


def _date_from_iso_ts(ts_iso: str) -> str:
    """Pull a YYYY-MM-DD prefix from an ISO8601 timestamp.

    Tolerates trailing 'Z' and degenerate inputs by falling back to UTC
    today rather than raising — soak logging must never crash the cron.
    """
    try:
        cleaned = ts_iso.replace("Z", "+00:00")
        return datetime.fromisoformat(cleaned).date().isoformat()
    except (TypeError, ValueError):
        return datetime.now(timezone.utc).date().isoformat()


def _date_path(log_dir: Path, date_iso: str) -> Path:
    return log_dir / SOAK_LOG_NAME_FMT.format(date=date_iso)


# ── Atomic JSONL helpers ─────────────────────────────────────────────────


def _read_jsonl_lines(path: Path) -> list[dict]:
    """Read JSONL file → list of dicts. Malformed lines logged + skipped."""
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
                logger.warning(
                    "factory-soak: skipping malformed line in %s", path.name
                )
                continue
    except OSError as e:
        logger.error("factory-soak: failed to read %s: %s", path, e)
    return out


def _atomic_write_jsonl(path: Path, records: list[dict]) -> None:
    """Rewrite ``path`` atomically from ``records`` via a sibling tempfile."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(
        dir=path.parent, prefix=path.name + ".", suffix=".tmp"
    )
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


def _entry_to_dict(entry: SoakEntry) -> dict[str, Any]:
    """Serialize a SoakEntry — tuples become lists for JSON compat."""
    d = asdict(entry)
    # Tuples → lists for JSON. asdict already does this for nested
    # tuples, but we re-apply defensively in case the dataclass shape
    # changes upstream.
    d["block_reasons"] = list(entry.block_reasons)
    d["advise_reasons"] = list(entry.advise_reasons)
    return d


def _dict_to_entry(d: dict[str, Any]) -> SoakEntry:
    """Inverse of :func:`_entry_to_dict`. Used by aggregate + update paths."""
    return SoakEntry(
        issue_number=int(d.get("issue_number", 0) or 0),
        issue_title=str(d.get("issue_title", "")),
        processed_at_iso=str(d.get("processed_at_iso", "")),
        synthesis_outcome=str(d.get("synthesis_outcome", "")),
        rule_fired=int(d.get("rule_fired", 0) or 0),
        block_reasons=tuple(d.get("block_reasons", ()) or ()),
        advise_reasons=tuple(d.get("advise_reasons", ()) or ()),
        would_action=str(d.get("would_action", "none")),  # type: ignore[arg-type]
        cost_usd=float(d.get("cost_usd", 0.0) or 0.0),
        duration_seconds=float(d.get("duration_seconds", 0.0) or 0.0),
        operator_verification=str(  # type: ignore[arg-type]
            d.get("operator_verification", "pending")
        ),
        operator_verification_at_iso=d.get("operator_verification_at_iso"),
        operator_notes=str(d.get("operator_notes", "")),
    )


# ── Public append / update API ───────────────────────────────────────────


def append_soak_entry(entry: SoakEntry, *, log_dir: Path | str = SOAK_LOG_DIR) -> None:
    """Atomic append for a :class:`SoakEntry`.

    Idempotent on ``(issue_number, processed_at_iso)`` — calling twice
    with the same signature is a no-op (the existing record wins, so
    operator verifications are preserved across replays).

    Never raises — IO errors are logged. Soak collection must not block
    the orchestrator's shadow tick.
    """
    try:
        directory = _resolve_dir(log_dir)
        date_iso = _date_from_iso_ts(entry.processed_at_iso)
        path = _date_path(directory, date_iso)

        existing = _read_jsonl_lines(path)
        target_signature = (entry.issue_number, entry.processed_at_iso)
        for rec in existing:
            sig = (
                int(rec.get("issue_number", 0) or 0),
                str(rec.get("processed_at_iso", "")),
            )
            if sig == target_signature:
                # Already logged — preserve existing record (incl. operator
                # verification fields the new entry would have wiped).
                return

        existing.append(_entry_to_dict(entry))
        _atomic_write_jsonl(path, existing)
    except Exception as e:  # pragma: no cover — defensive net
        logger.error("factory-soak: append_soak_entry failed: %s", e)


def update_verification(
    issue_number: int,
    *,
    verification: OperatorVerification,
    notes: str = "",
    log_dir: Path | str = SOAK_LOG_DIR,
) -> bool:
    """Find the most-recent soak entry for ``issue_number`` and update its
    ``operator_verification`` + ``operator_notes``.

    Scans all daily JSONL files in ``log_dir`` (cheap — one-per-day,
    14-day window typical), picks the most-recent record by
    ``processed_at_iso``, and atomically rewrites the day's file with
    the new verification.

    Returns True on success, False if the issue number was not found in
    any soak log.
    """
    directory = Path(log_dir)
    if not directory.exists():
        return False

    if verification not in ("pending", "correct", "incorrect", "skipped"):
        return False

    # Walk all daily files, find most-recent record for this issue.
    candidates: list[tuple[str, Path, int, dict]] = []  # (ts, path, idx, rec)
    for path in sorted(directory.glob("soak-*.jsonl")):
        records = _read_jsonl_lines(path)
        for idx, rec in enumerate(records):
            if int(rec.get("issue_number", 0) or 0) == issue_number:
                candidates.append(
                    (
                        str(rec.get("processed_at_iso", "")),
                        path,
                        idx,
                        rec,
                    )
                )

    if not candidates:
        return False

    # Most-recent by processed_at_iso (ISO sorts lexicographically).
    candidates.sort(key=lambda c: c[0], reverse=True)
    _ts, target_path, target_idx, _target_rec = candidates[0]

    # Re-read to avoid races — cheap on one-day-old JSONL.
    records = _read_jsonl_lines(target_path)
    if target_idx >= len(records):
        return False

    rec = dict(records[target_idx])
    rec["operator_verification"] = verification
    rec["operator_verification_at_iso"] = (
        datetime.now(timezone.utc).isoformat(timespec="seconds")
    )
    rec["operator_notes"] = notes
    records[target_idx] = rec

    try:
        _atomic_write_jsonl(target_path, records)
    except Exception as e:  # pragma: no cover — defensive
        logger.error("factory-soak: update_verification rewrite failed: %s", e)
        return False
    return True


# ── Aggregation ──────────────────────────────────────────────────────────


def _empty_report(
    *,
    window_days: int,
    window_start_iso: str,
    window_end_iso: str,
    reason: str,
) -> SoakReport:
    return SoakReport(
        window_days=window_days,
        window_start_iso=window_start_iso,
        window_end_iso=window_end_iso,
        total_issues_processed=0,
        pending_verification=0,
        verified_correct=0,
        verified_incorrect=0,
        skipped=0,
        correctness_rate=0.0,
        total_cost_usd=0.0,
        by_outcome={},
        sample_pending=(),
        ready_to_enable=False,
        ready_reason=reason,
    )


def aggregate_soak_window(
    *,
    days: int = 14,
    end_date_iso: Optional[str] = None,
    log_dir: Path | str = SOAK_LOG_DIR,
    min_correctness_rate: float = 0.80,
    min_verified_count: int = 5,
) -> SoakReport:
    """Aggregate the last ``days`` days of soak logs into a :class:`SoakReport`.

    ``ready_to_enable`` is True iff all three of:

      * ``window_days >= 14``
      * ``verified_correct >= min_verified_count``
      * ``correctness_rate >= min_correctness_rate``

    are satisfied. ``ready_reason`` always contains a human-readable
    explanation even when ``ready_to_enable`` is True (so the operator
    sees what passed).

    Missing daily files contribute zero records — no exception. Bad
    lines inside an existing file are skipped (logged).
    """
    if days <= 0:
        days = 14
    directory = _resolve_dir(log_dir)

    end_date = (
        datetime.fromisoformat(end_date_iso).date()
        if end_date_iso
        else datetime.now(timezone.utc).date()
    )
    start_date = end_date - timedelta(days=days - 1)
    window_start_iso = start_date.isoformat()
    window_end_iso = end_date.isoformat()

    # Gather entries across the window.
    entries: list[SoakEntry] = []
    for offset in range(days):
        d = start_date + timedelta(days=offset)
        path = _date_path(directory, d.isoformat())
        for rec in _read_jsonl_lines(path):
            entries.append(_dict_to_entry(rec))

    if not entries:
        return _empty_report(
            window_days=days,
            window_start_iso=window_start_iso,
            window_end_iso=window_end_iso,
            reason=(
                "no soak entries in window — shadow harness has not "
                "processed any issues yet"
            ),
        )

    pending = 0
    correct = 0
    incorrect = 0
    skipped = 0
    total_cost = 0.0
    by_outcome: dict[str, int] = {}

    for entry in entries:
        if entry.operator_verification == "correct":
            correct += 1
        elif entry.operator_verification == "incorrect":
            incorrect += 1
        elif entry.operator_verification == "skipped":
            skipped += 1
        else:
            pending += 1
        total_cost += entry.cost_usd
        by_outcome[entry.synthesis_outcome] = (
            by_outcome.get(entry.synthesis_outcome, 0) + 1
        )

    denom = correct + incorrect
    correctness_rate = (correct / denom) if denom else 0.0

    # Sample pending — most-recent first, capped at 5.
    pending_entries = [
        e for e in entries if e.operator_verification == "pending"
    ]
    pending_entries.sort(key=lambda e: e.processed_at_iso, reverse=True)
    sample_pending = tuple(pending_entries[:5])

    # Compose ready_to_enable + reason.
    ready, reason = _compute_ready(
        window_days=days,
        verified_correct=correct,
        correctness_rate=correctness_rate,
        min_correctness_rate=min_correctness_rate,
        min_verified_count=min_verified_count,
    )

    return SoakReport(
        window_days=days,
        window_start_iso=window_start_iso,
        window_end_iso=window_end_iso,
        total_issues_processed=len(entries),
        pending_verification=pending,
        verified_correct=correct,
        verified_incorrect=incorrect,
        skipped=skipped,
        correctness_rate=round(correctness_rate, 6),
        total_cost_usd=round(total_cost, 6),
        by_outcome=dict(sorted(by_outcome.items())),
        sample_pending=sample_pending,
        ready_to_enable=ready,
        ready_reason=reason,
    )


def _compute_ready(
    *,
    window_days: int,
    verified_correct: int,
    correctness_rate: float,
    min_correctness_rate: float,
    min_verified_count: int,
) -> tuple[bool, str]:
    """Decide ``ready_to_enable`` + return a human-readable reason."""
    failures: list[str] = []
    if window_days < 14:
        failures.append(
            f"window {window_days}d < required 14d"
        )
    if verified_correct < min_verified_count:
        failures.append(
            f"verified_correct {verified_correct} < required {min_verified_count}"
        )
    if correctness_rate < min_correctness_rate:
        failures.append(
            f"correctness_rate {correctness_rate:.2%} < required "
            f"{min_correctness_rate:.0%}"
        )

    if failures:
        return False, "not ready: " + "; ".join(failures)

    return True, (
        f"ready to enable — {window_days}d window with {verified_correct} "
        f"verified-correct issues at {correctness_rate:.2%} correctness "
        f"(floor {min_correctness_rate:.0%})"
    )


# ── Discord formatting ───────────────────────────────────────────────────


def format_report_for_discord(report: SoakReport) -> str:
    """Render a :class:`SoakReport` as a Discord-friendly markdown block.

    Used by the ``/soak_status`` operator command. Compact (≤ ~30 lines)
    so the operator can read it without scrolling.
    """
    lines = [
        "**Factory Soak Harness — 14d Status**",
        f"Window: `{report.window_start_iso}` → `{report.window_end_iso}` "
        f"({report.window_days}d)",
        "",
        f"Total issues processed: **{report.total_issues_processed}**",
        f"  pending verification: {report.pending_verification}",
        f"  verified correct:     {report.verified_correct}",
        f"  verified incorrect:   {report.verified_incorrect}",
        f"  skipped:              {report.skipped}",
        f"Correctness rate: **{report.correctness_rate:.2%}**",
        f"Total cost: ${report.total_cost_usd:.4f}",
        "",
    ]
    if report.by_outcome:
        lines.append("**By outcome:**")
        for outcome, count in report.by_outcome.items():
            lines.append(f"  `{outcome}` × {count}")
        lines.append("")

    if report.sample_pending:
        lines.append("**Pending verification (most recent 5):**")
        for entry in report.sample_pending:
            title = entry.issue_title[:60]
            lines.append(
                f"  #{entry.issue_number} — `{entry.synthesis_outcome}` "
                f"— {title}"
            )
        lines.append("")

    status_emoji = "[READY]" if report.ready_to_enable else "[NOT READY]"
    lines.append(f"**{status_emoji}** {report.ready_reason}")
    return "\n".join(lines)


# ── SoakHarness — orchestrator wrapper ───────────────────────────────────


class SoakHarness:
    """Wraps :class:`FactoryOrchestrator`'s pipeline for shadow-mode runs.

    Reuses the orchestrator's collaborators (implement runner, validate
    runner, synthesizer) so the soak harness exercises the same code
    path the production loop will. Routing is intercepted: the
    synthesizer's outcome is logged to the soak JSONL instead of being
    applied to GitHub.

    Per-tick discipline:

      * Acquires the orchestrator's GLOBAL lock so we don't shadow-run
        in parallel with a real tick.
      * Per-target locks are NOT taken — the soak harness never mutates
        external state, so contention on a real-orchestrator-held issue
        is fine. (The real orchestrator's lock would still block its
        own parallel run.)

    The harness reads the same ``factory:accepted`` queue the production
    orchestrator does. If the production orchestrator is enabled
    simultaneously (operator misconfiguration), it would still take
    action — the soak harness only records what it WOULD have done.
    Operators should run them mutually-exclusive: shadow first, prod
    second, never both at once.
    """

    def __init__(
        self,
        *,
        orchestrator: object,  # FactoryOrchestrator (duck-typed)
        log_dir: Path | str = SOAK_LOG_DIR,
    ) -> None:
        self._orchestrator = orchestrator
        self._log_dir = Path(log_dir)

    async def shadow_tick(self) -> tuple[SoakEntry, ...]:
        """Run one shadow tick. Returns the entries written this tick.

        Steps:

          1. List ``factory:accepted`` issues via the same ``gh``-CLI
             helper the orchestrator uses (imported lazily so tests can
             patch a single symbol).
          2. For each issue, run implement → validate → synthesize via
             the orchestrator's injected collaborators.
          3. Build a :class:`SoakEntry` with the synthesizer's verdict.
          4. Append it to the soak log (idempotent).
          5. Return the tuple of entries written this tick.

        Failures inside the per-issue loop are caught — one bad issue
        cannot block the rest of the tick. The error is recorded as a
        ``would_action="none"`` entry with synthesis_outcome describing
        the failure phase.
        """
        # Lazy import — keep this module importable in environments
        # where the orchestrator's optional deps aren't loaded.
        from bridge.factory.operator_commands import is_paused as _is_paused
        from bridge.services import factory_orchestrator as orch_mod

        # Sprint 14.11 — shadow harness honors the same pause flag the
        # production orchestrator does. The flag lives next to the
        # orchestrator's data dir; we read its data_dir attribute via
        # the harness's injected orchestrator. Falling back to the
        # default ``Path("data/factory-paused.flag")`` keeps tests
        # passing without an orchestrator.
        orch_data_dir = getattr(self._orchestrator, "data_dir", None)
        if orch_data_dir is not None:
            pause_flag_path = Path(orch_data_dir) / "factory-paused.flag"
        else:
            pause_flag_path = Path("data/factory-paused.flag")
        if _is_paused(pause_flag_path):
            logger.info(
                "factory-soak: pause flag present — skipping shadow tick"
            )
            return ()

        try:
            issues = orch_mod._gh_list_accepted(
                getattr(self._orchestrator, "_repo", "your-org/bumba-open-harness")
            )
        except Exception as e:
            logger.exception("factory-soak: list accepted failed: %s", e)
            return ()

        written: list[SoakEntry] = []
        for issue in issues:
            issue_number = int(issue.get("number", 0) or 0)
            if not issue_number:
                continue
            issue_title = str(issue.get("title", ""))
            issue_body = str(issue.get("body") or "")

            entry = await self._shadow_one_issue(
                issue_number=issue_number,
                issue_title=issue_title,
                issue_body=issue_body,
            )
            if entry is not None:
                append_soak_entry(entry, log_dir=self._log_dir)
                written.append(entry)

        return tuple(written)

    async def _shadow_one_issue(
        self,
        *,
        issue_number: int,
        issue_title: str,
        issue_body: str,
    ) -> Optional[SoakEntry]:
        """Run the pipeline for one issue, return a :class:`SoakEntry`.

        Never raises — failures land in a SoakEntry with
        ``would_action="none"`` and ``synthesis_outcome`` describing the
        failure phase. Returns None only for true skip cases (no PR
        produced by implement, or empty issue number).
        """
        from bridge.factory.seven_rule_synthesizer import (
            FactorySynthesisOutcome,
            SynthesisInput,
        )
        from bridge.services import factory_orchestrator as orch_mod

        start_iso = datetime.now(timezone.utc).isoformat(timespec="seconds")
        start_t = time.monotonic()
        cumulative_cost = 0.0

        repo = getattr(self._orchestrator, "_repo", "your-org/bumba-open-harness")
        cost_cap_per_issue = getattr(
            self._orchestrator,
            "_cost_cap_per_issue",
            orch_mod.DEFAULT_COST_CAP_PER_ISSUE_USD,
        )

        # Phase 1 — implement.
        try:
            impl_runner = getattr(self._orchestrator, "_implement", None)
            if impl_runner is None:
                return None
            impl_result = impl_runner(issue_number, repo=repo)
            if asyncio.iscoroutine(impl_result):
                impl_result = await impl_result
        except Exception as e:
            logger.exception(
                "factory-soak: implement raised on #%s: %s", issue_number, e
            )
            return SoakEntry(
                issue_number=issue_number,
                issue_title=issue_title,
                processed_at_iso=start_iso,
                synthesis_outcome="implement_failed",
                rule_fired=0,
                block_reasons=(str(e)[:200],),
                advise_reasons=(),
                would_action="would_escalate",
                cost_usd=cumulative_cost,
                duration_seconds=time.monotonic() - start_t,
            )

        cumulative_cost += float(getattr(impl_result, "cost_usd", 0.0) or 0.0)
        pr_number = getattr(impl_result, "pr_number", None)
        pr_url = getattr(impl_result, "pr_url", None) or ""
        impl_failed_phase = getattr(impl_result, "failed_phase", None)

        if impl_failed_phase or pr_number is None:
            return SoakEntry(
                issue_number=issue_number,
                issue_title=issue_title,
                processed_at_iso=start_iso,
                synthesis_outcome="implement_incomplete",
                rule_fired=0,
                block_reasons=(
                    f"implement failed at {impl_failed_phase}"
                    if impl_failed_phase
                    else "no PR produced",
                ),
                advise_reasons=(),
                would_action="would_escalate",
                cost_usd=cumulative_cost,
                duration_seconds=time.monotonic() - start_t,
            )

        # Phase 2 — validate.
        try:
            diff_text = orch_mod._gh_pr_diff(int(pr_number), repo)
            validate_runner = getattr(self._orchestrator, "_validate", None)
            if validate_runner is None:
                raise RuntimeError("orchestrator missing _validate runner")
            validate_result = await validate_runner(
                issue_body=issue_body,
                pr_url=pr_url,
                diff_text=diff_text,
            )
        except Exception as e:
            logger.exception(
                "factory-soak: validate raised on #%s: %s", issue_number, e
            )
            return SoakEntry(
                issue_number=issue_number,
                issue_title=issue_title,
                processed_at_iso=start_iso,
                synthesis_outcome="validate_failed",
                rule_fired=0,
                block_reasons=(str(e)[:200],),
                advise_reasons=(),
                would_action="would_escalate",
                cost_usd=cumulative_cost,
                duration_seconds=time.monotonic() - start_t,
            )

        cumulative_cost += float(
            getattr(validate_result, "total_cost_usd", 0.0) or 0.0
        )

        # Phase 3 — synthesize.
        try:
            synth = getattr(self._orchestrator, "_synthesize", None)
            if synth is None:
                raise RuntimeError("orchestrator missing _synthesize runner")
            decision = synth(
                SynthesisInput(
                    validate_result=validate_result,
                    total_cost_usd=cumulative_cost,
                    retry_count=0,
                ),
                cost_cap_usd=cost_cap_per_issue,
            )
        except Exception as e:
            logger.exception(
                "factory-soak: synthesize raised on #%s: %s",
                issue_number, e,
            )
            return SoakEntry(
                issue_number=issue_number,
                issue_title=issue_title,
                processed_at_iso=start_iso,
                synthesis_outcome="synthesize_failed",
                rule_fired=0,
                block_reasons=(str(e)[:200],),
                advise_reasons=(),
                would_action="would_escalate",
                cost_usd=cumulative_cost,
                duration_seconds=time.monotonic() - start_t,
            )

        outcome = getattr(decision, "outcome", None)
        outcome_str = (
            outcome.value
            if outcome is not None and hasattr(outcome, "value")
            else "unknown"
        )
        # Map outcome → would_action for fast operator scanning.
        if outcome in (
            FactorySynthesisOutcome.READY_FOR_OPERATOR,
            FactorySynthesisOutcome.READY_WITH_NOTES,
        ):
            would_action: ActionTaken = "would_proceed"
        elif outcome in (
            FactorySynthesisOutcome.NEEDS_FIX,
            FactorySynthesisOutcome.RETRY_REVIEWERS,
        ):
            # NEEDS_FIX / RETRY_REVIEWERS would proceed (in-loop) rather
            # than escalate to the operator. The harness does not run
            # the fix-loop in shadow mode — that's a separate cost.
            would_action = "would_proceed"
        else:
            would_action = "would_escalate"

        return SoakEntry(
            issue_number=issue_number,
            issue_title=issue_title,
            processed_at_iso=start_iso,
            synthesis_outcome=outcome_str,
            rule_fired=int(getattr(decision, "rule_fired", 0) or 0),
            block_reasons=tuple(
                getattr(decision, "block_reasons", ()) or ()
            ),
            advise_reasons=tuple(
                getattr(decision, "advise_reasons", ()) or ()
            ),
            would_action=would_action,
            cost_usd=cumulative_cost,
            duration_seconds=time.monotonic() - start_t,
        )


__all__ = [
    "ActionTaken",
    "OperatorVerification",
    "SOAK_LOG_DIR",
    "SOAK_LOG_NAME_FMT",
    "SoakEntry",
    "SoakHarness",
    "SoakReport",
    "aggregate_soak_window",
    "append_soak_entry",
    "format_report_for_discord",
    "update_verification",
]
