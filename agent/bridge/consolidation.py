"""Consolidation pipeline — pure-function logic for knowledge base maintenance.

6-phase pipeline: Inventory -> Decay -> Contradiction Resolution ->
Merge/Dedup -> Pattern Promotion -> Index/Report.

All functions are pure (except `run_pipeline`, which orchestrates the pure
phases and — when a DreamAgent is wired in deep mode — performs a single
async dream invocation so the report status reflects the actual run state).
The service layer handles DB reads/writes and supplies the agent.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Final, Literal

from .memory import (
    DECAY_EXEMPT_CATEGORIES,
    DECAY_EXEMPT_SOURCES,
    DECAY_RATES,
    SALIENCE_PRUNE_THRESHOLD,
)
from bridge.dispatch_metrics import increment_module_counter

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Deep-resolution status vocabulary (Sprint 05.09)
# ---------------------------------------------------------------------------
# `unavailable` — deep mode requested but no DreamAgent wired
# `completed`   — DreamAgent.run() succeeded
# `error`       — DreamAgent.run() raised, returned success=False, or async
#                 invocation failed (e.g. nested event loop)
# `skipped`     — non-deep mode that still emits a deep_resolution stub for
#                 disambiguation in downstream dashboards
DeepResolutionStatus = Literal["unavailable", "completed", "error", "skipped"]

DEEP_RESOLUTION_STATUSES: Final[tuple[DeepResolutionStatus, ...]] = (
    "unavailable",
    "completed",
    "error",
    "skipped",
)

# ---------------------------------------------------------------------------
# Result dataclasses (all frozen / immutable)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class InventoryReport:
    """Phase 1 result: knowledge base inventory counts."""

    total: int
    by_category: dict[str, int]
    by_source: dict[str, int]
    oldest_entry: str | None
    newest_entry: str | None


@dataclass(frozen=True)
class DecayResult:
    """Phase 2 result: salience decay application."""

    processed: int
    pruned: int
    decayed: int
    exempt: int


@dataclass(frozen=True)
class ContradictionResult:
    """Phase 3 result: contradiction detection."""

    pairs_checked: int
    contradictions_found: int
    resolved: int
    details: list[dict]


@dataclass(frozen=True)
class MergeResult:
    """Phase 4 result: duplicate merging."""

    candidates: int
    merged: int
    kept: int
    details: list[dict]


@dataclass(frozen=True)
class PromotionResult:
    """Phase 5 result: pattern promotion / demotion."""

    evaluated: int
    promoted: int
    demoted: int
    details: list[dict]


@dataclass(frozen=True)
class ConsolidationReport:
    """Phase 6 result: full pipeline report."""

    phase_results: dict[str, object]
    total_duration_ms: int
    mode: str
    timestamp: str


@dataclass
class DeepResolutionResult:
    """Phase result for deep LLM-assisted contradiction resolution."""

    status: str
    resolved: list = field(default_factory=list)



# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Negation words that signal opposing sentiment
_NEGATION_WORDS = frozenset(
    {"not", "never", "don't", "dont", "avoid", "stop", "no", "won't", "wont",
     "can't", "cant", "shouldn't", "shouldnt", "isn't", "isnt", "wasn't",
     "wasnt", "doesn't", "doesnt", "didn't", "didnt", "neither", "nor"}
)

# Common stop words excluded from token overlap calculations
_STOP_WORDS = frozenset(
    {"the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
     "have", "has", "had", "do", "does", "did", "will", "would", "shall",
     "should", "may", "might", "must", "can", "could", "i", "me", "my",
     "we", "our", "you", "your", "he", "she", "it", "they", "them", "their",
     "this", "that", "these", "those", "of", "in", "to", "for", "with",
     "on", "at", "by", "from", "as", "into", "about", "and", "or", "but",
     "if", "so", "than", "too", "very", "just", "also"}
)


def _tokenize(text: str) -> set[str]:
    """Tokenize text into a set of lowercase significant words."""
    words = re.findall(r"[a-z0-9]+", text.lower())
    return {w for w in words if w not in _STOP_WORDS and len(w) > 1}


def _has_negation(text: str) -> bool:
    """Check whether text contains negation words."""
    words = set(re.findall(r"[a-z']+", text.lower()))
    return bool(words & _NEGATION_WORDS)


def _token_overlap_ratio(tokens_a: set[str], tokens_b: set[str]) -> float:
    """Compute token overlap ratio: |A ∩ B| / min(|A|, |B|)."""
    if not tokens_a or not tokens_b:
        return 0.0
    intersection = len(tokens_a & tokens_b)
    denominator = min(len(tokens_a), len(tokens_b))
    return intersection / denominator if denominator > 0 else 0.0


# ---------------------------------------------------------------------------
# Phase 1: Inventory
# ---------------------------------------------------------------------------


def inventory(rows: list[dict]) -> InventoryReport:
    """Count entries by category and source; find oldest/newest timestamps.

    Each row is expected to have at least: category, source, created_at.
    """
    by_category: dict[str, int] = {}
    by_source: dict[str, int] = {}
    oldest: str | None = None
    newest: str | None = None

    for row in rows:
        cat = row.get("category", "unknown")
        src = row.get("source", "unknown")
        by_category[cat] = by_category.get(cat, 0) + 1
        by_source[src] = by_source.get(src, 0) + 1

        created = row.get("created_at")
        if created:
            if oldest is None or created < oldest:
                oldest = created
            if newest is None or created > newest:
                newest = created

    return InventoryReport(
        total=len(rows),
        by_category=by_category,
        by_source=by_source,
        oldest_entry=oldest,
        newest_entry=newest,
    )


# ---------------------------------------------------------------------------
# Phase 2: Decay
# ---------------------------------------------------------------------------


def decay(rows: list[dict], days_elapsed: int = 1) -> DecayResult:
    """Apply salience decay rates; identify entries to prune or update.

    Each row is expected to have: key, category, source, salience.
    Rows are annotated in-place with ``_action`` (one of ``"prune"``,
    ``"decay"``, ``"exempt"``) and ``_new_salience`` where applicable.
    """
    processed = 0
    pruned = 0
    decayed = 0
    exempt = 0

    for row in rows:
        processed += 1
        cat = row.get("category", "")
        src = row.get("source", "")
        salience = row.get("salience", 1.0)

        if salience is None:
            salience = 1.0

        # Exempt check
        if cat in DECAY_EXEMPT_CATEGORIES or src in DECAY_EXEMPT_SOURCES:
            row["_action"] = "exempt"
            exempt += 1
            continue

        # Apply decay
        rate = DECAY_RATES.get(cat, 0.98)  # default to 0.98 for unknown categories
        new_salience = salience * (rate ** days_elapsed)

        if new_salience < SALIENCE_PRUNE_THRESHOLD:
            row["_action"] = "prune"
            row["_new_salience"] = new_salience
            pruned += 1
        else:
            row["_action"] = "decay"
            row["_new_salience"] = new_salience
            decayed += 1

    return DecayResult(
        processed=processed,
        pruned=pruned,
        decayed=decayed,
        exempt=exempt,
    )


# ---------------------------------------------------------------------------
# Phase 3: Contradiction Resolution
# ---------------------------------------------------------------------------


def find_contradictions(rows: list[dict]) -> ContradictionResult:
    """Detect contradictory entries via keyword overlap + negation analysis.

    Compares pairs within the same category.  A contradiction is flagged
    when two entries share significant keyword overlap but one contains
    negation words and the other does not.

    Each row is expected to have: key, value, category.
    """
    pairs_checked = 0
    contradictions: list[dict] = []

    # Group rows by category for efficient comparison
    by_cat: dict[str, list[dict]] = {}
    for row in rows:
        cat = row.get("category", "unknown")
        by_cat.setdefault(cat, []).append(row)

    for cat, group in by_cat.items():
        for i in range(len(group)):
            for j in range(i + 1, len(group)):
                pairs_checked += 1
                a = group[i]
                b = group[j]

                val_a = a.get("value", "")
                val_b = b.get("value", "")

                tokens_a = _tokenize(val_a)
                tokens_b = _tokenize(val_b)

                overlap = _token_overlap_ratio(tokens_a, tokens_b)
                if overlap < 0.3:
                    continue  # Not enough shared content to compare

                neg_a = _has_negation(val_a)
                neg_b = _has_negation(val_b)

                if neg_a != neg_b:
                    contradictions.append({
                        "key_a": a.get("key", ""),
                        "key_b": b.get("key", ""),
                        "category": cat,
                        "overlap": round(overlap, 3),
                        "reason": "negation_mismatch",
                    })

    return ContradictionResult(
        pairs_checked=pairs_checked,
        contradictions_found=len(contradictions),
        resolved=0,  # Resolution is handled by the service layer (or LLM in deep mode)
        details=contradictions,
    )


# ---------------------------------------------------------------------------
# Phase 4: Merge/Dedup
# ---------------------------------------------------------------------------


def merge_duplicates(
    rows: list[dict],
    similarity_threshold: float = 0.85,
) -> MergeResult:
    """Find near-duplicate entries and propose merges.

    Uses token overlap ratio on entry values.  The entry with higher
    salience is kept; the other is marked for archival.

    Each row is expected to have: key, value, salience, category.
    Rows are annotated with ``_merge_action`` (``"keep"`` or ``"archive"``).
    """
    candidates = 0
    merged = 0
    kept_count = 0
    details: list[dict] = []

    # Track which rows have already been merged away
    archived_keys: set[str] = set()

    for i in range(len(rows)):
        if rows[i].get("key", "") in archived_keys:
            continue
        for j in range(i + 1, len(rows)):
            if rows[j].get("key", "") in archived_keys:
                continue

            val_a = rows[i].get("value", "")
            val_b = rows[j].get("value", "")
            tokens_a = _tokenize(val_a)
            tokens_b = _tokenize(val_b)

            overlap = _token_overlap_ratio(tokens_a, tokens_b)
            if overlap < similarity_threshold:
                continue

            candidates += 1
            sal_a = rows[i].get("salience", 1.0) or 1.0
            sal_b = rows[j].get("salience", 1.0) or 1.0

            if sal_a >= sal_b:
                keep, archive = rows[i], rows[j]
            else:
                keep, archive = rows[j], rows[i]

            keep["_merge_action"] = "keep"
            archive["_merge_action"] = "archive"
            archived_keys.add(archive.get("key", ""))
            merged += 1
            kept_count += 1

            details.append({
                "kept": keep.get("key", ""),
                "archived": archive.get("key", ""),
                "overlap": round(overlap, 3),
            })

    return MergeResult(
        candidates=candidates,
        merged=merged,
        kept=kept_count,
        details=details,
    )


# ---------------------------------------------------------------------------
# Phase 5: Pattern Promotion
# ---------------------------------------------------------------------------


def promote_patterns(
    rows: list[dict],
    access_threshold: int = 5,
) -> PromotionResult:
    """Promote high-access entries and demote low-access ones.

    Each row is expected to have: key, access_count, salience.
    Rows are annotated with ``_promotion_action`` and ``_new_salience``.
    """
    from .memory import SALIENCE_MAX

    evaluated = 0
    promoted = 0
    demoted = 0
    details: list[dict] = []

    for row in rows:
        evaluated += 1
        access_count = row.get("access_count", 0) or 0
        salience = row.get("salience", 1.0)
        if salience is None:
            salience = 1.0

        if access_count >= access_threshold:
            new_salience = min(salience + 0.2, SALIENCE_MAX)
            row["_promotion_action"] = "promote"
            row["_new_salience"] = new_salience
            promoted += 1
            details.append({
                "key": row.get("key", ""),
                "action": "promote",
                "access_count": access_count,
                "old_salience": salience,
                "new_salience": new_salience,
            })
        elif access_count == 0 and salience < 0.5:
            new_salience = max(salience - 0.1, 0.0)
            row["_promotion_action"] = "demote"
            row["_new_salience"] = new_salience
            demoted += 1
            details.append({
                "key": row.get("key", ""),
                "action": "demote",
                "access_count": access_count,
                "old_salience": salience,
                "new_salience": new_salience,
            })
        else:
            row["_promotion_action"] = "none"

    return PromotionResult(
        evaluated=evaluated,
        promoted=promoted,
        demoted=demoted,
        details=details,
    )


# ---------------------------------------------------------------------------
# Phase 6: Pipeline orchestrator
# ---------------------------------------------------------------------------


def _run_dream_agent(_dream_agent: object, session_ids: list[str]) -> dict[str, object]:
    """Invoke the dream agent and produce a deep_resolution payload.

    Returns a dict with the new deep-resolution contract:
      - status: one of DEEP_RESOLUTION_STATUSES
      - For "completed": summary, files_touched, entries_pruned,
        contradictions_resolved, merges_performed
      - For "error": error (string)

    DreamAgent.run is async; this helper drives it via ``asyncio.run`` and
    catches any failure (including nested event-loop refusal) and reports
    them as ``status="error"`` rather than letting them escape and corrupt
    the rest of the report.
    """
    try:
        result = asyncio.run(_dream_agent.run(session_ids))
    except Exception as exc:
        log.error("DreamAgent.run() raised %s: %s", type(exc).__name__, exc)
        return {
            "status": "error",
            "error": f"{type(exc).__name__}: {exc}",
        }

    success = bool(getattr(result, "success", False))
    if not success:
        err = getattr(result, "error", None) or "dream_agent_returned_failure"
        return {"status": "error", "error": str(err)}

    return {
        "status": "completed",
        "summary": getattr(result, "summary", "") or "",
        "files_touched": list(getattr(result, "files_touched", []) or []),
        "entries_pruned": int(getattr(result, "entries_pruned", 0) or 0),
        "contradictions_resolved": int(
            getattr(result, "contradictions_resolved", 0) or 0
        ),
        "merges_performed": int(getattr(result, "merges_performed", 0) or 0),
    }


def run_pipeline(
    rows: list[dict],
    mode: str = "standard",
    session_ids: list[str] | None = None,
    _dream_agent: object | None = None,
) -> ConsolidationReport:
    increment_module_counter("consolidation.run_pipeline", tier=3)
    """Orchestrate consolidation phases based on mode.

    Modes:
    - ``micro``:    Inventory + Decay only (early return; no deep_resolution)
    - ``standard``: All 6 phases + deep_resolution=skipped (disambiguation)
    - ``deep``:     All 6 phases + LLM contradiction pass via DreamAgent

    Deep-resolution status semantics (Sprint 05.09):
    - ``unavailable``: deep mode but no agent wired
    - ``completed``:   agent.run() succeeded — payload carries summary stats
    - ``error``:       agent.run() raised or returned success=False
    - ``skipped``:     non-deep mode (standard) — explanatory note included

    Returns a ``ConsolidationReport`` with all phase results.
    """
    start = time.monotonic()
    ts = datetime.now(timezone.utc).isoformat()
    phase_results: dict[str, object] = {}

    # Phase 1: Inventory (always runs)
    try:
        inv = inventory(rows)
        phase_results["inventory"] = inv
    except Exception as e:
        log.error("Consolidation phase 'inventory' failed: %s", e)
        phase_results["inventory"] = {"error": str(e)}

    # Phase 2: Decay (always runs)
    try:
        dec = decay(rows)
        phase_results["decay"] = dec
    except Exception as e:
        log.error("Consolidation phase 'decay' failed: %s", e)
        phase_results["decay"] = {"error": str(e)}

    # Micro mode stops after Decay (no deep_resolution emitted)
    if mode == "micro":
        elapsed_ms = int((time.monotonic() - start) * 1000)
        return ConsolidationReport(
            phase_results=phase_results,
            total_duration_ms=elapsed_ms,
            mode=mode,
            timestamp=ts,
        )

    # Phase 3: Contradiction Resolution
    try:
        contra = find_contradictions(rows)
        phase_results["contradictions"] = contra
    except Exception as e:
        log.error("Consolidation phase 'contradictions' failed: %s", e)
        phase_results["contradictions"] = {"error": str(e)}

    # Phase 4: Merge/Dedup
    try:
        merge = merge_duplicates(rows)
        phase_results["merge"] = merge
    except Exception as e:
        log.error("Consolidation phase 'merge' failed: %s", e)
        phase_results["merge"] = {"error": str(e)}

    # Phase 5: Pattern Promotion
    try:
        promo = promote_patterns(rows)
        phase_results["promotion"] = promo
    except Exception as e:
        log.error("Consolidation phase 'promotion' failed: %s", e)
        phase_results["promotion"] = {"error": str(e)}

    # Deep-resolution branch — status now reflects actual run state
    if mode == "deep":
        if _dream_agent is None:
            phase_results["deep_resolution"] = {
                "status": "unavailable",
                "note": "DreamAgent not wired",
            }
        else:
            sids = list(session_ids) if session_ids else []
            phase_results["deep_resolution"] = _run_dream_agent(_dream_agent, sids)
    else:
        # Non-deep modes (currently: standard) emit a "skipped" stub so
        # downstream dashboards can distinguish "no deep run requested" from
        # "deep requested but unavailable" and from "deep ran successfully".
        phase_results["deep_resolution"] = {
            "status": "skipped",
            "note": f"deep_resolution does not apply to {mode}",
        }

    elapsed_ms = int((time.monotonic() - start) * 1000)
    return ConsolidationReport(
        phase_results=phase_results,
        total_duration_ms=elapsed_ms,
        mode=mode,
        timestamp=ts,
    )
