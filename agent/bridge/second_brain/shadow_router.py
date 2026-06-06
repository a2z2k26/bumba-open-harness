"""shadow_router.py — 14-day shadow + auto-routing decision harness.

Sprint 05.11 (issue #1021) of the 2026-04-25 reference-audit bundle.
ADR sign-off: ``agent/docs/architecture/second-brain.md`` Decision 4
(``__AZ__`` 2026-05-01) — observe-before-acting on the consolidation →
wiki direct-emit path.

Why this exists
---------------
Sprint 05.07 (#1015) shipped :class:`ConsolidationContributor`, which
emits curated consolidation digests into
``bumba-contributions/curated/consolidation/{YYYY-MM-DD}-digest.md``.
The operator promotes those to canonical via ``/promote`` (Sprint
05.10).

Before we cut over to *auto*-promoting consolidation outputs (i.e.
Bumba writing canonical wiki pages directly), we need 14 days of
shadow-mode evidence. For each contribution observed, the auto-router
records the decision it *would* have made — promote, leave_curated, or
reject — alongside the operator's eventual real action. After 14 days
the operator inspects the agreement rate via ``/shadow_report``; if the
shadow router and the operator agreed >= 90% of the time over 50+
decided contributions, the flag flips from "shadow" to "active".

This module **never modifies vault files**. It only writes JSONL to
``data/shadow-router/shadow-{YYYY-MM-DD}.jsonl`` per UTC day.

Defensive contract
------------------
- Idempotent: ``append_shadow_entry`` is a no-op when an entry with the
  same ``(contribution_relpath, shadow_decision_at_iso)`` already
  exists.
- Atomic: ``update_actual_outcome`` rewrites the day's JSONL via
  ``mkstemp + os.replace``.
- Defensive: ``aggregate_shadow_window`` tolerates missing day files
  (treated as zero-contribution days).
- Pure-function ``evaluate_contribution`` so the heuristic stays
  test-friendly and side-effect free.

License: NO LICENSE (Karpathy gist). Concept-only port — no source
copied. PR description affirms ``concept-only-no-license``.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Literal, Optional

logger = logging.getLogger(__name__)


ShadowDecision = Literal["promote", "leave_curated", "reject"]
"""Decisions the auto-router would have taken in shadow mode."""

ActualOutcome = Literal["promoted", "left_curated", "rejected", "pending"]
"""Operator outcome stamped onto a shadow entry once /promote or
/reject_wiki fires. ``pending`` is the initial state."""


# Default JSONL log dir, mirrors ``data/shadow-router/`` under the
# bridge's data root. Caller usually passes an absolute path so this
# constant is just the relative shape the spec spells out.
SHADOW_LOG_DIR = Path("data/shadow-router")
SHADOW_LOG_NAME_FMT = "shadow-{date}.jsonl"
"""Filename template; ``{date}`` is ``YYYY-MM-DD`` (UTC)."""


# Word-count floor below which a consolidation digest is too short to be
# canonical wiki material — shadow router would leave_curated.
_MIN_PROMOTE_WORDS = 100


@dataclass(frozen=True)
class ShadowEntry:
    """One shadow-routed contribution + its decision + the eventual
    operator outcome.

    Frozen so callers can stash entries in sets / dict keys and the
    update-outcome path always returns a NEW entry (immutability per
    project rules).

    Attributes:
        contribution_relpath: Vault-relative path of the contribution
            the auto-router observed (e.g.
            ``bumba-contributions/curated/consolidation/2026-05-01-digest.md``).
        contribution_authored_at_iso: ISO8601 UTC timestamp the
            contribution itself carried (matches ``Contribution.authored_at``).
        shadow_decision: What the auto-router would have done.
        shadow_decision_at_iso: When the auto-router made the call
            (ISO8601 UTC, naive→aware coerced).
        shadow_reason: One-line human-readable explanation of why the
            heuristic returned ``shadow_decision``.
        actual_outcome: The eventual operator outcome —  ``pending``
            until ``/promote`` or ``/reject_wiki`` correlates back.
        actual_outcome_at_iso: When the operator action was correlated
            (or ``None`` while still pending).
    """

    contribution_relpath: str
    contribution_authored_at_iso: str
    shadow_decision: ShadowDecision
    shadow_decision_at_iso: str
    shadow_reason: str
    actual_outcome: ActualOutcome
    actual_outcome_at_iso: Optional[str]


@dataclass(frozen=True)
class ShadowReport:
    """14-day rolling summary of shadow vs actual.

    Attributes:
        window_days: Width of the rolling window (default 14).
        window_start_iso: Inclusive start of the window (UTC date string).
        window_end_iso: Inclusive end of the window (UTC date string).
        total_contributions: All shadow entries inside the window.
        pending_count: Entries the operator has not acted on yet.
        decided_count: Entries with ``actual_outcome != "pending"``.
        agreement_count: Entries whose shadow decision matched the
            operator outcome (promote↔promoted, leave_curated↔left_curated,
            reject↔rejected).
        disagreement_count: Decided entries that did NOT match.
        agreement_rate: ``agreement_count / decided_count`` in [0.0,
            1.0]; 0.0 when ``decided_count == 0``.
        by_decision: Per-shadow-decision breakdown of counts.
        sample_disagreements: Up to 10 example entries where shadow !=
            actual; sorted by ``shadow_decision_at_iso`` so the operator
            sees the most recent first when the report is rendered.
    """

    window_days: int
    window_start_iso: str
    window_end_iso: str
    total_contributions: int
    pending_count: int
    decided_count: int
    agreement_count: int
    disagreement_count: int
    agreement_rate: float
    by_decision: dict
    sample_disagreements: tuple


# ---------------- pure heuristic ---------------- #


def evaluate_contribution(
    contribution_body: str,
    *,
    contribution_relpath: str,
    word_count: Optional[int] = None,
    lint_findings: Optional[Iterable[object]] = None,
) -> tuple[ShadowDecision, str]:
    """Apply the auto-router's heuristic.

    Pure function — no I/O, no logging side effects. Returns a
    ``(decision, reason)`` pair so callers can record both.

    Order matters:

    1. **Lint errors → reject.** Any ``LintFinding`` whose ``severity``
       is ``"error"`` (defensive ``getattr`` on the duck-typed object)
       disqualifies the contribution. Reason cites the first error.
    2. **Too short → leave_curated.** Bodies below 100 words are not
       canonical-quality even if they came out of consolidation.
    3. **Consolidation path with no errors → promote.** The path
       contains ``"consolidation"`` AND no lint errors AND >= 100 words.
    4. **Else → leave_curated.** Conservative default — anything not
       matching the consolidation shape stays in curated/staging for
       manual operator review.

    Args:
        contribution_body: Markdown body of the contribution. Used for
            word-count fallback when ``word_count`` is None.
        contribution_relpath: Vault-relative path; used for the path
            heuristic in step 3.
        word_count: Pre-computed word count. When ``None``, this
            function counts whitespace-split tokens in the body.
        lint_findings: Optional iterable of ``LintFinding``-shaped
            objects. We duck-type on ``severity`` and ``message`` so
            tests can pass simple stand-ins without importing lint.

    Returns:
        ``(decision, one-line reason)``.
    """
    # Step 1 — lint error short-circuit.
    if lint_findings is not None:
        for finding in lint_findings:
            severity = getattr(finding, "severity", None)
            if severity == "error":
                first_msg = getattr(finding, "message", "") or ""
                # Single-line reason — flatten any embedded newlines.
                first_msg = first_msg.replace("\n", " ").strip()
                if first_msg:
                    return (
                        "reject",
                        f"lint error blocks promotion: {first_msg}",
                    )
                return ("reject", "lint error blocks promotion")

    # Compute word count if not supplied. Whitespace-split is good
    # enough for a coarse threshold; the lint pass is the real gate.
    if word_count is None:
        word_count = len(contribution_body.split()) if contribution_body else 0

    # Step 2 — too short.
    if word_count < _MIN_PROMOTE_WORDS:
        return (
            "leave_curated",
            f"body too short for canonical promotion ({word_count} < "
            f"{_MIN_PROMOTE_WORDS} words)",
        )

    # Step 3 — consolidation path with adequate length.
    if "consolidation" in contribution_relpath:
        return (
            "promote",
            f"consolidation digest passes lint and length floor "
            f"({word_count} words)",
        )

    # Step 4 — conservative default.
    return (
        "leave_curated",
        "non-consolidation source — operator review preferred",
    )


# ---------------- I/O primitives ---------------- #


def _utc_now_iso() -> str:
    """ISO8601 UTC ``YYYY-MM-DDTHH:MM:SSZ``."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _date_from_iso(iso: str) -> str:
    """Extract the ``YYYY-MM-DD`` UTC date from an ISO8601 timestamp.

    Tolerates trailing ``Z`` (RFC3339 UTC marker). Falls back to today
    if parsing fails — defensive so a malformed timestamp never crashes
    the shadow log writer.
    """
    if not iso:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%d")


def _entry_log_path(entry: ShadowEntry, *, log_dir: Path) -> Path:
    """Resolve the per-day log path for ``entry``."""
    date_str = _date_from_iso(entry.shadow_decision_at_iso)
    return log_dir / SHADOW_LOG_NAME_FMT.format(date=date_str)


def _atomic_rewrite(target: Path, lines: list[str]) -> None:
    """Atomically rewrite ``target`` with the given JSONL ``lines``.

    Each line in ``lines`` is expected to be a serialized JSON dict
    with a trailing newline. Uses ``mkstemp`` + ``os.replace`` to keep
    the rewrite atomic on POSIX (the platform the bridge ships on).
    """
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix="." + target.name + ".",
        suffix=".tmp",
        dir=str(target.parent),
    )
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            for line in lines:
                fh.write(line)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_path, target)
    except BaseException:
        try:
            tmp_path.unlink()
        except FileNotFoundError:
            pass
        raise


def _read_jsonl_entries(path: Path) -> list[ShadowEntry]:
    """Read ``path`` and return a list of :class:`ShadowEntry`.

    Skips malformed lines defensively. Returns ``[]`` when the file is
    missing or unreadable so callers can pretend a missing day is a
    zero-contribution day.
    """
    if not path.is_file():
        return []
    out: list[ShadowEntry] = []
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        logger.warning("shadow-router: read failed for %s: %s", path, exc)
        return []
    for line in text.splitlines():
        if not line.strip():
            continue
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            logger.debug("shadow-router: skipping malformed line in %s", path)
            continue
        try:
            out.append(
                ShadowEntry(
                    contribution_relpath=str(data["contribution_relpath"]),
                    contribution_authored_at_iso=str(
                        data["contribution_authored_at_iso"]
                    ),
                    shadow_decision=data["shadow_decision"],
                    shadow_decision_at_iso=str(data["shadow_decision_at_iso"]),
                    shadow_reason=str(data.get("shadow_reason", "")),
                    actual_outcome=data.get("actual_outcome", "pending"),
                    actual_outcome_at_iso=data.get("actual_outcome_at_iso"),
                )
            )
        except (KeyError, TypeError):
            logger.debug(
                "shadow-router: skipping incomplete entry in %s", path,
            )
            continue
    return out


def append_shadow_entry(
    entry: ShadowEntry,
    *,
    log_dir: Path = SHADOW_LOG_DIR,
) -> None:
    """Append ``entry`` to the day's JSONL.

    Idempotent on ``(contribution_relpath, shadow_decision_at_iso)`` —
    if a line with both fields already exists, this is a no-op.

    Args:
        entry: The :class:`ShadowEntry` to record.
        log_dir: Root for shadow JSONL files (default
            :data:`SHADOW_LOG_DIR`). Created if absent.
    """
    log_dir = Path(log_dir)
    log_path = _entry_log_path(entry, log_dir=log_dir)

    existing = _read_jsonl_entries(log_path)
    for prior in existing:
        if (
            prior.contribution_relpath == entry.contribution_relpath
            and prior.shadow_decision_at_iso == entry.shadow_decision_at_iso
        ):
            # Already recorded — idempotent no-op.
            return

    log_path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(asdict(entry), sort_keys=True) + "\n"
    # Plain append is fine — we are the only writer in shadow mode.
    # Atomic rewrite is reserved for ``update_actual_outcome``.
    with log_path.open("a", encoding="utf-8") as fh:
        fh.write(line)


def update_actual_outcome(
    contribution_relpath: str,
    *,
    actual_outcome: ActualOutcome,
    decided_at_iso: str,
    log_dir: Path = SHADOW_LOG_DIR,
) -> bool:
    """Stamp the operator outcome onto the matching shadow entry.

    Searches every JSONL file under ``log_dir`` for an entry with
    matching ``contribution_relpath``. When found, rewrites the day's
    JSONL atomically with ``actual_outcome`` + ``actual_outcome_at_iso``
    populated. Returns ``True`` if a matching entry was updated, else
    ``False`` (e.g. the contribution predates shadow mode or the JSONL
    was rotated out).

    Args:
        contribution_relpath: Vault-relative path of the contribution
            the operator just promoted / rejected.
        actual_outcome: ``promoted`` / ``left_curated`` / ``rejected``.
        decided_at_iso: When the operator made the call (ISO8601 UTC).
        log_dir: Shadow log root.

    Returns:
        True iff a shadow entry was found and updated.
    """
    log_dir = Path(log_dir)
    if not log_dir.is_dir():
        return False

    for path in sorted(log_dir.glob("shadow-*.jsonl")):
        entries = _read_jsonl_entries(path)
        if not entries:
            continue
        updated_any = False
        new_entries: list[ShadowEntry] = []
        for prior in entries:
            if (
                prior.contribution_relpath == contribution_relpath
                and prior.actual_outcome == "pending"
            ):
                # Build the replacement entry — frozen dataclass, so
                # we construct a NEW one rather than mutating.
                new_entries.append(
                    ShadowEntry(
                        contribution_relpath=prior.contribution_relpath,
                        contribution_authored_at_iso=(
                            prior.contribution_authored_at_iso
                        ),
                        shadow_decision=prior.shadow_decision,
                        shadow_decision_at_iso=prior.shadow_decision_at_iso,
                        shadow_reason=prior.shadow_reason,
                        actual_outcome=actual_outcome,
                        actual_outcome_at_iso=decided_at_iso,
                    )
                )
                updated_any = True
            else:
                new_entries.append(prior)
        if updated_any:
            lines = [
                json.dumps(asdict(e), sort_keys=True) + "\n"
                for e in new_entries
            ]
            _atomic_rewrite(path, lines)
            return True
    return False


# ---------------- aggregation ---------------- #


_SHADOW_TO_ACTUAL = {
    "promote": "promoted",
    "leave_curated": "left_curated",
    "reject": "rejected",
}
"""Mapping from shadow_decision → matching actual_outcome literal."""


def _empty_by_decision() -> dict:
    """Empty per-decision breakdown skeleton."""
    return {
        "promote": {"total": 0, "agreement": 0, "disagreement": 0, "pending": 0},
        "leave_curated": {
            "total": 0,
            "agreement": 0,
            "disagreement": 0,
            "pending": 0,
        },
        "reject": {"total": 0, "agreement": 0, "disagreement": 0, "pending": 0},
    }


def aggregate_shadow_window(
    *,
    days: int = 14,
    end_date_iso: Optional[str] = None,
    log_dir: Path = SHADOW_LOG_DIR,
) -> ShadowReport:
    """Aggregate shadow entries over the last ``days`` UTC days.

    Window is **inclusive** on both ends. ``end_date_iso=None`` means
    "today (UTC)". Missing day files are treated as zero-contribution
    days — never an exception.

    Args:
        days: Window width (default 14, matches the spec).
        end_date_iso: Inclusive end date as ``YYYY-MM-DD`` UTC. None
            means today.
        log_dir: Shadow log root.

    Returns:
        :class:`ShadowReport` with deterministic, sorted samples.
    """
    log_dir = Path(log_dir)
    if days <= 0:
        days = 1

    if end_date_iso is None:
        end_date = datetime.now(timezone.utc).date()
    else:
        try:
            end_date = datetime.strptime(end_date_iso, "%Y-%m-%d").date()
        except ValueError:
            end_date = datetime.now(timezone.utc).date()
    start_date = end_date - timedelta(days=days - 1)

    entries: list[ShadowEntry] = []
    cursor = start_date
    while cursor <= end_date:
        day_str = cursor.strftime("%Y-%m-%d")
        path = log_dir / SHADOW_LOG_NAME_FMT.format(date=day_str)
        entries.extend(_read_jsonl_entries(path))
        cursor = cursor + timedelta(days=1)

    by_decision = _empty_by_decision()
    pending_count = 0
    decided_count = 0
    agreement_count = 0
    disagreement_count = 0
    disagreements: list[ShadowEntry] = []

    for e in entries:
        bucket = by_decision.get(e.shadow_decision)
        if bucket is None:
            # Unknown decision — skip but don't crash.
            continue
        bucket["total"] = bucket["total"] + 1
        if e.actual_outcome == "pending":
            pending_count += 1
            bucket["pending"] = bucket["pending"] + 1
            continue
        decided_count += 1
        expected = _SHADOW_TO_ACTUAL.get(e.shadow_decision)
        if expected is not None and e.actual_outcome == expected:
            agreement_count += 1
            bucket["agreement"] = bucket["agreement"] + 1
        else:
            disagreement_count += 1
            bucket["disagreement"] = bucket["disagreement"] + 1
            disagreements.append(e)

    if decided_count > 0:
        agreement_rate = agreement_count / decided_count
    else:
        agreement_rate = 0.0

    # Most recent disagreements first; cap at 10 examples so the
    # report stays readable.
    disagreements_sorted = sorted(
        disagreements,
        key=lambda x: x.shadow_decision_at_iso,
        reverse=True,
    )
    sample = tuple(disagreements_sorted[:10])

    return ShadowReport(
        window_days=days,
        window_start_iso=start_date.strftime("%Y-%m-%d"),
        window_end_iso=end_date.strftime("%Y-%m-%d"),
        total_contributions=len(entries),
        pending_count=pending_count,
        decided_count=decided_count,
        agreement_count=agreement_count,
        disagreement_count=disagreement_count,
        agreement_rate=agreement_rate,
        by_decision=by_decision,
        sample_disagreements=sample,
    )


# ---------------- observer wrapper ---------------- #


class ShadowRouter:
    """Observer that records what the auto-router *would* have done.

    Hooked into :class:`ConsolidationContributor`'s emit path via
    :meth:`observe`. **Never modifies vault files** — pure JSONL
    sidecar.

    Wires back to the operator commands so ``/promote`` and
    ``/reject_wiki`` can stamp the actual outcome onto the matching
    shadow entry. Stamping failures are non-fatal (the operator action
    itself already succeeded).

    Args:
        wiki_repo: A :class:`bridge.second_brain.wiki_repo.WikiRepo`
            (or anything with a ``vault_root`` attribute) — held to
            allow future enrichment of the heuristic with vault-state
            signals (e.g. orphan check). Currently unused beyond
            initialization, but kept on the constructor surface to
            avoid churn when 05.12 wires in lint findings.
        log_dir: Where to write JSONL entries (default
            :data:`SHADOW_LOG_DIR`).
    """

    def __init__(
        self,
        *,
        wiki_repo: object,
        log_dir: Path = SHADOW_LOG_DIR,
    ) -> None:
        if wiki_repo is None:
            raise ValueError("wiki_repo must not be None")
        self._wiki_repo = wiki_repo
        self._log_dir = Path(log_dir)

    @property
    def log_dir(self) -> Path:
        """JSONL log root."""
        return self._log_dir

    def observe(self, contribution: object) -> ShadowEntry:
        """Compute the shadow decision for ``contribution`` and record.

        ``contribution`` is duck-typed against
        :class:`bridge.second_brain.contributor.Contribution` — we read
        ``relpath``, ``body``, and ``authored_at`` defensively so a
        future Contribution shape change doesn't crash the observer.

        Returns:
            The :class:`ShadowEntry` written (caller may surface it
            on the same code path that emitted the contribution).
        """
        relpath = getattr(contribution, "relpath", "") or ""
        body = getattr(contribution, "body", "") or ""
        authored_at = getattr(contribution, "authored_at", "") or _utc_now_iso()

        decision, reason = evaluate_contribution(
            body,
            contribution_relpath=relpath,
        )
        decided_at = _utc_now_iso()
        entry = ShadowEntry(
            contribution_relpath=relpath,
            contribution_authored_at_iso=authored_at,
            shadow_decision=decision,
            shadow_decision_at_iso=decided_at,
            shadow_reason=reason,
            actual_outcome="pending",
            actual_outcome_at_iso=None,
        )
        try:
            append_shadow_entry(entry, log_dir=self._log_dir)
        except OSError as exc:
            # Non-fatal — shadow mode must never break the contributor.
            logger.warning(
                "shadow-router: append failed (non-fatal): %s", exc,
            )
        return entry

    def observe_all(self, contributions: Iterable[object]) -> list[ShadowEntry]:
        """Record each contribution; returns the list of entries."""
        return [self.observe(c) for c in contributions]

    def correlate_promotion(
        self,
        source_relpath: str,
        *,
        decided_at_iso: str,
    ) -> bool:
        """Operator promoted ``source_relpath`` via /promote.

        Updates the matching shadow entry's actual_outcome to
        ``"promoted"``. Returns True iff a match was found.
        """
        return update_actual_outcome(
            source_relpath,
            actual_outcome="promoted",
            decided_at_iso=decided_at_iso,
            log_dir=self._log_dir,
        )

    def correlate_rejection(
        self,
        source_relpath: str,
        *,
        decided_at_iso: str,
    ) -> bool:
        """Operator rejected ``source_relpath`` via /reject_wiki.

        Updates the matching shadow entry's actual_outcome to
        ``"rejected"``. Returns True iff a match was found.
        """
        return update_actual_outcome(
            source_relpath,
            actual_outcome="rejected",
            decided_at_iso=decided_at_iso,
            log_dir=self._log_dir,
        )


# ---------------- formatter for /shadow_report ---------------- #


def format_shadow_report(
    report: ShadowReport,
    *,
    promote_threshold: float = 0.90,
    decided_floor: int = 50,
) -> str:
    """Render a :class:`ShadowReport` as a Discord-friendly string.

    Includes:
    - window dates + total / pending / decided counts
    - agreement_rate as a percentage
    - top 5 disagreements (most recent first)
    - "ready to flip" recommendation when
      ``decided_count >= decided_floor`` AND
      ``agreement_rate >= promote_threshold``.

    Args:
        report: Aggregated rolling window.
        promote_threshold: Agreement rate needed to recommend the flip
            (operator-tunable via config; default 0.90).
        decided_floor: Minimum decided contributions before a
            recommendation can fire (default 50, per spec).

    Returns:
        Multi-line string suitable for direct send to Discord.
    """
    lines: list[str] = []
    lines.append(
        f"**Shadow Router Report** ({report.window_start_iso} → "
        f"{report.window_end_iso}, {report.window_days}d)"
    )
    lines.append(
        f"  total: {report.total_contributions}  "
        f"decided: {report.decided_count}  "
        f"pending: {report.pending_count}"
    )
    pct = report.agreement_rate * 100.0
    lines.append(
        f"  agreement: {report.agreement_count}/"
        f"{report.decided_count} ({pct:.1f}%)"
    )
    lines.append("")
    lines.append("By shadow decision:")
    for dec in ("promote", "leave_curated", "reject"):
        bucket = report.by_decision.get(dec, {})
        lines.append(
            f"  - {dec}: total={bucket.get('total', 0)} "
            f"agree={bucket.get('agreement', 0)} "
            f"disagree={bucket.get('disagreement', 0)} "
            f"pending={bucket.get('pending', 0)}"
        )

    if report.sample_disagreements:
        lines.append("")
        lines.append("Top disagreements (most recent first):")
        for e in report.sample_disagreements[:5]:
            lines.append(
                f"  - {e.shadow_decision_at_iso}  "
                f"shadow={e.shadow_decision} actual={e.actual_outcome}  "
                f"`{e.contribution_relpath}`"
            )

    lines.append("")
    if (
        report.decided_count >= decided_floor
        and report.agreement_rate >= promote_threshold
    ):
        lines.append(
            f"**Recommendation:** ready to flip from shadow to active "
            f"(agreement {pct:.1f}% >= {promote_threshold * 100:.0f}% "
            f"on {report.decided_count} >= {decided_floor} decisions)."
        )
    else:
        deficit_decisions = max(0, decided_floor - report.decided_count)
        lines.append(
            f"**Recommendation:** keep observing. "
            f"need >= {decided_floor} decided "
            f"({deficit_decisions} more) AND agreement >= "
            f"{promote_threshold * 100:.0f}% (currently {pct:.1f}%)."
        )
    return "\n".join(lines)


__all__ = [
    "ActualOutcome",
    "SHADOW_LOG_DIR",
    "SHADOW_LOG_NAME_FMT",
    "ShadowDecision",
    "ShadowEntry",
    "ShadowReport",
    "ShadowRouter",
    "aggregate_shadow_window",
    "append_shadow_entry",
    "evaluate_contribution",
    "format_shadow_report",
    "update_actual_outcome",
]
