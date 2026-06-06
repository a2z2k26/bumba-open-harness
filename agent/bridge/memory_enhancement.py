"""Memory enhancement — intent classification, importance scoring, pruning.

Provides the intelligence layer on top of the knowledge base:
- Intent classification for memory entries
- Composite importance scoring with decay
- Sliding context window assembly
- Auto-pruning of low-importance entries
- Memory analytics

Wired into capture by Sprint Mem-3 (epic: memory-tier-architecture).
Wired into retrieval by Sprint Mem-6 (`assemble_context_window` tier-aware
mode + Branch 0 in `KnowledgeMixin.search_knowledge`).
"""

from __future__ import annotations

import logging
import math
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from bridge.tag_parser import strip_private_spans

if TYPE_CHECKING:
    from bridge.memory_tiers import MemoryTier

log = logging.getLogger(__name__)

# Intent classification
VALID_INTENTS = {"fact", "preference", "decision", "context", "instruction"}

# Keywords for rule-based intent classification
INTENT_KEYWORDS: dict[str, list[str]] = {
    "preference": [
        "prefer", "like", "dislike", "want", "always", "never",
        "favorite", "rather", "style", "format",
    ],
    "decision": [
        "decided", "chose", "picked", "selected", "agreed",
        "will use", "going with", "settled on",
    ],
    "instruction": [
        "must", "should", "never", "always", "rule", "requirement",
        "don't", "do not", "make sure", "ensure",
    ],
    "context": [
        "working on", "currently", "right now", "today", "this week",
        "in progress", "started", "planning",
    ],
}

# Importance scoring weights
WEIGHT_SALIENCE = 0.3
WEIGHT_ACCESS_FREQ = 0.15
WEIGHT_RECENCY = 0.2
WEIGHT_INTENT_MATCH = 0.2
WEIGHT_VECTOR_RELEVANCE = 0.15

# Decay
DEFAULT_HALF_LIFE_DAYS = 30
ARCHIVE_THRESHOLD = 0.1
DEFAULT_CONTEXT_WINDOW = 20
MAX_CONTEXT_TOKENS = 4000  # Approximate token budget


def classify_intent(text: str) -> str:
    """Classify text into an intent category using rule-based matching.

    Returns one of: fact, preference, decision, context, instruction.
    Default: fact (most common).
    """
    # Strip claude-mem-style `<private>` redaction spans before any capture-side
    # logic touches the content. This is the earliest hook on the capture path
    # — keyword scoring, importance, and context formatting all see the
    # already-redacted text. Concept-only port (AGPL-3.0).
    text = strip_private_spans(text)
    text_lower = text.lower()

    # Score each intent
    scores: dict[str, int] = {}
    for intent, keywords in INTENT_KEYWORDS.items():
        score = sum(1 for kw in keywords if kw in text_lower)
        if score > 0:
            scores[intent] = score

    if not scores:
        return "fact"

    return max(scores, key=scores.get)  # type: ignore[arg-type]


@dataclass
class ScoredEntry:
    """A memory entry with computed importance score."""

    key: str
    value: str
    category: str
    intent: str = "fact"
    salience: float = 0.5
    access_count: int = 0
    last_accessed: float = 0.0
    created_at: float = 0.0
    importance: float = 0.0


def compute_importance(
    entry: ScoredEntry,
    *,
    half_life_days: float = DEFAULT_HALF_LIFE_DAYS,
    intent_boost: str | None = None,
) -> float:
    """Compute composite importance score for a memory entry.

    Formula: importance = salience * (1 - decay) + access_freq * 0.3 + recency * 0.2
    """
    now = time.time()

    # Decay based on age
    if entry.created_at > 0:
        age_days = (now - entry.created_at) / 86400
    else:
        age_days = 0

    decay = 1.0 - math.exp(-0.693 * age_days / half_life_days)  # ln(2) ≈ 0.693
    salience_component = entry.salience * (1.0 - decay) * WEIGHT_SALIENCE / 0.3

    # Access frequency (normalized: 0 = never, 1 = frequently)
    access_norm = min(entry.access_count / 10.0, 1.0) if entry.access_count > 0 else 0.0
    access_component = access_norm * WEIGHT_ACCESS_FREQ / 0.15

    # Recency of last access
    if entry.last_accessed > 0:
        hours_since = (now - entry.last_accessed) / 3600
        recency = max(0.0, 1.0 - hours_since / 168)  # 1 week decay
    else:
        recency = 0.0
    recency_component = recency * WEIGHT_RECENCY / 0.2

    # Intent match boost
    intent_component = 0.0
    if intent_boost and entry.intent == intent_boost:
        intent_component = 0.3

    importance = (
        salience_component * WEIGHT_SALIENCE
        + access_component * WEIGHT_ACCESS_FREQ
        + recency_component * WEIGHT_RECENCY
        + intent_component * WEIGHT_INTENT_MATCH
    )

    return min(1.0, max(0.0, importance))


def assemble_context_window(
    entries: list[ScoredEntry] | None = None,
    *,
    query_intent: str | None = None,
    max_entries: int = DEFAULT_CONTEXT_WINDOW,
    max_chars: int = MAX_CONTEXT_TOKENS * 4,  # ~4 chars per token
    tier_results: "dict[MemoryTier, list[ScoredEntry]] | None" = None,
    tier_weights: "dict[MemoryTier, float] | None" = None,
) -> list[ScoredEntry]:
    """Assemble the top-N entries for context-window injection.

    Two input modes:

    - **LEGACY** (``tier_results`` is None): behaves identically to the
      pre-Mem-6 ``select_context_window`` — flat list of ``ScoredEntry``,
      ranked by importance with intent-boost and budget culling.
    - **TIERED** (``tier_results`` is not None, Sprint Mem-6 / #1847):
      flattens per-tier ranked lists, multiplies each entry's importance
      by ``tier_weights[tier]`` (defaults to 1.0 per tier when omitted),
      then applies the same ``max_entries`` / ``max_chars`` /
      ``query_intent`` culling as the legacy path.

    When ``tier_results`` is provided, ``entries`` is ignored. When
    neither is provided, returns ``[]``. Honors the immutability rule —
    tier-mode entries are rebuilt as new ``ScoredEntry`` instances so
    the caller's input dict is never mutated.
    """
    # TIERED mode (Mem-6). Build a flat list of ScoredEntry copies with
    # importance × tier_weight applied; legacy ranking/culling code below
    # then runs unchanged.
    if tier_results is not None:
        weights = tier_weights or {}
        flattened: list[ScoredEntry] = []
        for tier, tier_entries in tier_results.items():
            weight = weights.get(tier, 1.0)
            for src in tier_entries:
                flattened.append(
                    ScoredEntry(
                        key=src.key,
                        value=src.value,
                        category=src.category,
                        intent=src.intent,
                        salience=src.salience,
                        access_count=src.access_count,
                        last_accessed=src.last_accessed,
                        created_at=src.created_at,
                        importance=src.importance * weight,
                    )
                )
        entries = flattened
        # In TIERED mode, the per-entry importance already carries the
        # tier weight × pre-computed compute_importance() score. Skip the
        # legacy re-score so we don't overwrite that with intent-boost-only
        # importance and lose the tier weighting.
        _tiered_mode = True
    else:
        _tiered_mode = False

    if not entries:
        return []

    if not _tiered_mode:
        # LEGACY path — score in-place (pre-Mem-6 behaviour, byte-identical
        # when called as `assemble_context_window(entries=...)`).
        for entry in entries:
            entry.importance = compute_importance(entry, intent_boost=query_intent)

    # Sort by importance descending
    ranked = sorted(entries, key=lambda e: e.importance, reverse=True)

    # Select within budget
    selected: list[ScoredEntry] = []
    total_chars = 0
    for entry in ranked:
        entry_chars = len(entry.key) + len(entry.value)
        if total_chars + entry_chars > max_chars:
            break
        selected.append(entry)
        total_chars += entry_chars
        if len(selected) >= max_entries:
            break

    return selected


# Sprint Mem-6 rename — preserve old name for back-compat with the
# pre-rename test fixtures in test_memory_enhancement.py. Zero production
# callers existed at rename time (confirmed by grep -rn). New code should
# call `assemble_context_window`.
select_context_window = assemble_context_window


def find_low_importance(
    entries: list[ScoredEntry],
    threshold: float = ARCHIVE_THRESHOLD,
) -> list[ScoredEntry]:
    """Find entries below the archive threshold."""
    for entry in entries:
        entry.importance = compute_importance(entry)

    return [e for e in entries if e.importance < threshold]


@dataclass
class MemoryAnalytics:
    """Memory system analytics."""

    total_entries: int = 0
    archived_entries: int = 0
    avg_salience: float = 0.0
    avg_importance: float = 0.0
    intent_distribution: dict[str, int] = field(default_factory=dict)
    entries_by_category: dict[str, int] = field(default_factory=dict)
    low_importance_count: int = 0
    recently_accessed_count: int = 0

    def to_dict(self) -> dict:
        return {
            "total_entries": self.total_entries,
            "archived_entries": self.archived_entries,
            "avg_salience": round(self.avg_salience, 3),
            "avg_importance": round(self.avg_importance, 3),
            "intent_distribution": self.intent_distribution,
            "entries_by_category": self.entries_by_category,
            "low_importance_count": self.low_importance_count,
            "recently_accessed_count": self.recently_accessed_count,
        }


def compute_analytics(entries: list[ScoredEntry]) -> MemoryAnalytics:
    """Compute memory analytics from a list of scored entries."""
    analytics = MemoryAnalytics(total_entries=len(entries))

    if not entries:
        return analytics

    total_salience = 0.0
    total_importance = 0.0
    now = time.time()

    for entry in entries:
        entry.importance = compute_importance(entry)
        total_salience += entry.salience
        total_importance += entry.importance

        # Intent distribution
        intent = entry.intent or "fact"
        analytics.intent_distribution[intent] = (
            analytics.intent_distribution.get(intent, 0) + 1
        )

        # Category distribution
        cat = entry.category or "general"
        analytics.entries_by_category[cat] = (
            analytics.entries_by_category.get(cat, 0) + 1
        )

        # Low importance
        if entry.importance < ARCHIVE_THRESHOLD:
            analytics.low_importance_count += 1

        # Recently accessed (within 24h)
        if entry.last_accessed > 0 and now - entry.last_accessed < 86400:
            analytics.recently_accessed_count += 1

    analytics.avg_salience = total_salience / len(entries)
    analytics.avg_importance = total_importance / len(entries)

    return analytics


def format_context_for_claude(entries: list[ScoredEntry]) -> str:
    """Format selected entries as structured context for Claude."""
    if not entries:
        return ""

    lines = ["**Relevant Memory Context:**\n"]
    for entry in entries:
        prefix = f"[{entry.intent}]" if entry.intent != "fact" else ""
        # Defense in depth: strip any claude-mem-style `<private>` span that
        # somehow survived in stored content. Concept-only port (AGPL-3.0).
        safe_value = strip_private_spans(entry.value)
        lines.append(f"- {prefix} **{entry.key}**: {safe_value}")

    return "\n".join(lines)
