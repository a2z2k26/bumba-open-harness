"""Hybrid search — combines FTS5 BM25 with vector cosine similarity using RRF.

Reciprocal Rank Fusion (RRF) merges ranked results from keyword (FTS5)
and semantic (vector) search into a single ranked list.

Weights: FTS5 = 0.3, Vector = 0.7 (semantic search prioritized).
RRF formula: score = weight * (1 / (k + rank))  where k = 60.

Sprint 03.02 also adds a 3-layer progressive disclosure API
(``search_ids`` / ``timeline`` / ``get_observations``) — concept-only port
of claude-mem-style 3-layer progressive disclosure (pointer → timeline →
observation). Concept paraphrased; no source copied. Default-OFF behind
``BridgeConfig.memory_v2_disclosure_enabled``.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .local_embeddings import LocalEmbeddingEngine, cosine_similarity
from .memory.conversation import _escape_fts5_query
from .memory_tiers import MemoryTier, load_tier_policies

if TYPE_CHECKING:
    from .config import BridgeConfig

log = logging.getLogger(__name__)

RRF_K = 60  # RRF smoothing constant
WEIGHT_FTS5 = 0.3
WEIGHT_VECTOR = 0.7
DEFAULT_TOP_K = 20


@dataclass
class SearchResult:
    """A single search result with scores from both sources."""

    doc_id: str
    content: str = ""
    category: str = ""
    fts5_rank: int | None = None
    vector_rank: int | None = None
    fts5_score: float = 0.0
    vector_score: float = 0.0
    rrf_score: float = 0.0
    metadata: dict = field(default_factory=dict)


# ── Sprint 03.02 — claude-mem-style 3-layer progressive disclosure ──
#
# Concept-only port (no source code copied from any AGPL implementation).
# Layer 1 (pointer): ``MemoryRef`` — id + 1-line summary + score.
# Layer 2 (timeline): ``Event`` — created/updated/referenced/redacted.
# Layer 3 (observation): ``Observation`` — actual content for a span.
#
# Caller pays content tokens only for the layer it actually expanded.
# Default to ``search_ids``; drill down via ``timeline`` / ``get_observations``
# only when the summary is insufficient.

# Maximum length of a 1-line summary on MemoryRef / Event (chars).
SUMMARY_MAX_CHARS = 120


@dataclass(frozen=True)
class MemoryRef:
    """Layer 1 pointer — id + 1-line summary + RRF score + tier hint.

    ``tier`` is ``"L?"`` until 03.04 lands the L0..L4 tier model.
    No content field — Layer 1 is content-free by construction.
    """

    id: str
    summary: str
    score: float
    tier: str = "L?"


@dataclass(frozen=True)
class Event:
    """Layer 2 timeline entry — when and how the memory changed.

    ``event_type`` is one of ``created | updated | referenced | redacted``.
    No content field — Layer 2 also stays content-free.
    """

    memory_id: str
    timestamp: datetime
    event_type: str
    summary: str


@dataclass(frozen=True)
class Observation:
    """Layer 3 observation — actual content for a span of a memory."""

    memory_id: str
    span_start: int
    span_end: int
    content: str
    source: str


def _truncate_summary(text: str, max_chars: int = SUMMARY_MAX_CHARS) -> str:
    """Return a 1-line summary capped at ``max_chars``.

    Collapses internal whitespace (so multi-line content doesn't leak past
    the cap) and uses an ellipsis for over-long inputs.
    """
    flat = " ".join(text.split())
    if len(flat) <= max_chars:
        return flat
    # Reserve 1 char for the ellipsis — keep total <= max_chars.
    return flat[: max_chars - 1] + "…"


def compute_rrf_score(
    fts5_rank: int | None,
    vector_rank: int | None,
    k: int = RRF_K,
    weight_fts5: float = WEIGHT_FTS5,
    weight_vector: float = WEIGHT_VECTOR,
) -> float:
    """Compute RRF score from individual ranks."""
    score = 0.0
    if fts5_rank is not None:
        score += weight_fts5 * (1.0 / (k + fts5_rank))
    if vector_rank is not None:
        score += weight_vector * (1.0 / (k + vector_rank))
    return score


def merge_results(
    fts5_results: list[tuple[str, str, str, float]],
    vector_results: list[tuple[str, float]],
    k: int = RRF_K,
    weight_fts5: float = WEIGHT_FTS5,
    weight_vector: float = WEIGHT_VECTOR,
    top_k: int = DEFAULT_TOP_K,
) -> list[SearchResult]:
    """Merge FTS5 and vector results using RRF.

    Args:
        fts5_results: List of (doc_id, content, category, bm25_score)
        vector_results: List of (doc_id, cosine_similarity)
        k: RRF smoothing constant
        weight_fts5: Weight for FTS5 scores
        weight_vector: Weight for vector scores
        top_k: Number of results to return

    Returns:
        Merged and sorted list of SearchResult
    """
    results: dict[str, SearchResult] = {}

    # Process FTS5 results
    for rank, (doc_id, content, category, bm25_score) in enumerate(fts5_results, start=1):
        if doc_id not in results:
            results[doc_id] = SearchResult(
                doc_id=doc_id,
                content=content,
                category=category,
            )
        results[doc_id].fts5_rank = rank
        results[doc_id].fts5_score = bm25_score

    # Process vector results
    for rank, (doc_id, sim_score) in enumerate(vector_results, start=1):
        if doc_id not in results:
            results[doc_id] = SearchResult(doc_id=doc_id)
        results[doc_id].vector_rank = rank
        results[doc_id].vector_score = sim_score

    # Compute RRF scores
    for result in results.values():
        result.rrf_score = compute_rrf_score(
            result.fts5_rank,
            result.vector_rank,
            k=k,
            weight_fts5=weight_fts5,
            weight_vector=weight_vector,
        )

    # Sort by RRF score descending
    sorted_results = sorted(results.values(), key=lambda r: r.rrf_score, reverse=True)
    return sorted_results[:top_k]


class HybridSearch:
    """Combines FTS5 keyword search with vector semantic search."""

    def __init__(
        self,
        embedding_engine: LocalEmbeddingEngine,
        *,
        weight_fts5: float = WEIGHT_FTS5,
        weight_vector: float = WEIGHT_VECTOR,
        rrf_k: int = RRF_K,
        metrics_file: str | Path | None = None,
        metrics: Any | None = None,
    ) -> None:
        self.embedding_engine = embedding_engine
        self.weight_fts5 = weight_fts5
        self.weight_vector = weight_vector
        self.rrf_k = rrf_k
        self._metrics_file = Path(metrics_file) if metrics_file else None
        # Sprint Mem-9.5 (#1877) — optional `MetricsCollector` for per-tier
        # `memory.tier.retrievals.<tier>` emit in `search_tiered`. Optional
        # to preserve back-compat with all existing construction sites.
        self._metrics = metrics

    def search(
        self,
        query: str,
        fts5_results: list[tuple[str, str, str, float]],
        documents: dict[str, str] | None = None,
        top_k: int = DEFAULT_TOP_K,
    ) -> list[SearchResult]:
        """Execute hybrid search.

        Args:
            query: Search query text
            fts5_results: Pre-fetched FTS5 results as (doc_id, content, category, score)
            documents: Optional dict of {doc_id: text} for vector search.
                       If None, only FTS5 results are used.
            top_k: Number of results to return

        Returns:
            Merged results sorted by RRF score
        """
        start = time.monotonic()
        fts5_time = 0.0
        vector_time = 0.0

        # FTS5 results are pre-fetched (time measured by caller)
        fts5_time = 0  # Already fetched

        # Vector search
        vector_results: list[tuple[str, float]] = []
        if documents:
            vec_start = time.monotonic()
            query_embedding = self.embedding_engine.embed(query, is_query=True)

            scored: list[tuple[str, float]] = []
            for doc_id, text in documents.items():
                doc_embedding = self.embedding_engine.embed(text)
                sim = cosine_similarity(query_embedding, doc_embedding)
                scored.append((doc_id, sim))

            scored.sort(key=lambda x: x[1], reverse=True)
            vector_results = scored[:top_k * 2]  # Wider net for RRF merge
            vector_time = (time.monotonic() - vec_start) * 1000

        # Merge via RRF
        merged = merge_results(
            fts5_results,
            vector_results,
            k=self.rrf_k,
            weight_fts5=self.weight_fts5,
            weight_vector=self.weight_vector,
            top_k=top_k,
        )

        total_time = (time.monotonic() - start) * 1000

        # Log metrics
        self._log_metrics(
            query=query,
            fts5_count=len(fts5_results),
            vector_count=len(vector_results),
            merged_count=len(merged),
            fts5_time_ms=fts5_time,
            vector_time_ms=vector_time,
            total_time_ms=total_time,
        )

        return merged

    def search_tiered(
        self,
        query: str,
        *,
        db_connection: sqlite3.Connection,
        tier_weights: dict[MemoryTier, float] | None = None,
        limit_per_tier: int = 10,
        config: "BridgeConfig | None" = None,
    ) -> dict[MemoryTier, list[SearchResult]]:
        """Per-tier RRF-fused search returning a tier-keyed dict.

        Each tier is queried separately with a ``WHERE tier = ?`` filter
        (hits ``idx_knowledge_tier`` from Mem-2's migration), RRF-fused
        within tier, and post-scored by ``tier_weights[tier]`` so that
        higher-weight tiers naturally outrank lower-weight tiers when a
        caller merges across tiers.

        The existing ``search()`` method is untouched. This is purely
        additive — Mem-6 (#1847) will wire ``search_tiered`` into the
        prompt-build path behind ``memory_tiers_enabled``.

        Args:
            query: Search query string. Escaped internally before use with
                FTS5's MATCH operator; passed verbatim to vector embedding.
            db_connection: Open ``sqlite3.Connection`` to the bridge
                memory database. Required because per-tier FTS5
                filtering executes SQL against ``knowledge_fts`` JOIN
                ``knowledge``. Caller manages connection lifecycle.
            tier_weights: Per-tier multiplier applied to the RRF score
                after fusion. When None, resolved from
                ``TierPolicy.retrieval_weight`` via
                ``load_tier_policies(config or BridgeConfig())``.
            limit_per_tier: Cap on per-tier result list length. Each
                tier returns at most this many results; the FTS5 query
                fetches up to ``limit_per_tier * 2`` candidates before
                fusion to give RRF room to reorder.
            config: Optional ``BridgeConfig`` for default-weight
                resolution. When None, falls back to module-level
                defaults from ``load_tier_policies(BridgeConfig())``.

        Returns:
            dict mapping each ``MemoryTier`` to a ranked
            ``list[SearchResult]``, length <= ``limit_per_tier``. Tiers
            with no matches return an empty list (key still present —
            never absent).

        Notes:
            - Does NOT gate on ``memory_tiers_enabled``. Callers
              (Mem-6) decide whether to invoke this method.
            - Per-tier scores are multiplied by ``tier_weights[tier]``
              so cross-tier merge ranks higher-weight tiers above
              lower-weight tiers at equal raw RRF score.
            - Vector branch reuses the same per-tier filter via a
              second ``WHERE tier = ?`` query so the documents dict
              passed to RRF is tier-pure. This means vector hits are
              also tier-filtered — no post-filtering needed.
        """
        # Resolve tier weights once. Honor explicit override; fall back
        # to TierPolicy.retrieval_weight defaults from Mem-1.
        if tier_weights is None:
            if config is None:
                from .config import BridgeConfig

                config = BridgeConfig()
            policies = load_tier_policies(config)
            tier_weights = {
                tier: policies[tier].retrieval_weight for tier in MemoryTier
            }

        # Sprint Mem-8 (#1849) — strict-mode fail-loud probe. When the
        # operator opts into strict mode, count NULL/empty tier rows
        # ONCE up front and log a WARNING. Migration 14's DEFAULT 'context'
        # NOT NULL means this should always report 0 on the current
        # schema; a non-zero count is the audible signal that schema
        # drift or a side-channel writer has slipped a NULL-tier row
        # past the gate. The per-tier ``WHERE k.tier = ?`` filter below
        # would silently skip such rows otherwise.
        strict = (
            getattr(config, "strict_tier_required", False) if config else False
        )
        if strict:
            try:
                null_cursor = db_connection.execute(
                    """SELECT COUNT(*) FROM knowledge
                       WHERE (tier IS NULL OR tier = '')
                         AND (archived IS NULL OR archived = 0)"""
                )
                null_count = null_cursor.fetchone()[0]
                if null_count:
                    log.warning(
                        "search_tiered: strict_tier_required filtered %d "
                        "NULL/empty-tier knowledge row(s); they will be "
                        "excluded from all per-tier results",
                        null_count,
                    )
            except sqlite3.Error as exc:
                log.warning(
                    "search_tiered: strict-mode NULL-tier probe failed: %s", exc,
                )

        # Fetch limit_per_tier * 2 candidates per tier so RRF has room
        # to reorder before the final cap.
        fetch_limit = max(limit_per_tier * 2, limit_per_tier)
        fts_query = _escape_fts5_query(query)

        out: dict[MemoryTier, list[SearchResult]] = {}
        for tier in MemoryTier:
            # FTS5 keyword branch — per-tier filter via WHERE tier = ?
            # on the joined `knowledge` row. ``INDEXED BY
            # idx_knowledge_tier`` is a load-bearing hint: it forces
            # SQLite to use Mem-2's tier index rather than driving off
            # FTS5 and applying the tier predicate as a residual filter.
            # Verified by EXPLAIN QUERY PLAN in
            # test_query_plan_uses_idx_knowledge_tier.
            try:
                cursor = db_connection.execute(
                    """SELECT k.key, k.value, k.tags, k.category, rank
                       FROM knowledge k INDEXED BY idx_knowledge_tier
                       JOIN knowledge_fts ON knowledge_fts.rowid = k.rowid
                       WHERE k.tier = ?
                         AND knowledge_fts MATCH ?
                         AND (k.archived IS NULL OR k.archived = 0)
                       ORDER BY rank
                       LIMIT ?""",
                    (tier.value, fts_query, fetch_limit),
                )
                fts_rows = cursor.fetchall()
            except sqlite3.Error as exc:
                log.warning(
                    "search_tiered: FTS5 fetch failed for tier=%s query=%r: %s",
                    tier.value, query, exc,
                )
                fts_rows = []

            fts5_results: list[tuple[str, str, str, float]] = [
                (r[0], r[1] or "", (r[3] or r[2] or ""), float(r[4]))
                for r in fts_rows
            ]

            # Vector branch — same tier filter so documents are tier-pure.
            try:
                doc_cursor = db_connection.execute(
                    """SELECT key, value FROM knowledge
                       WHERE tier = ?
                         AND (archived IS NULL OR archived = 0)
                       LIMIT ?""",
                    (tier.value, fetch_limit),
                )
                doc_rows = doc_cursor.fetchall()
            except sqlite3.Error as exc:
                log.warning(
                    "search_tiered: vector doc fetch failed for tier=%s: %s",
                    tier.value, exc,
                )
                doc_rows = []

            documents: dict[str, str] = {r[0]: (r[1] or "") for r in doc_rows}

            vector_results: list[tuple[str, float]] = []
            if documents:
                query_embedding = self.embedding_engine.embed(query, is_query=True)
                scored: list[tuple[str, float]] = []
                for doc_id, text in documents.items():
                    doc_embedding = self.embedding_engine.embed(text)
                    sim = cosine_similarity(query_embedding, doc_embedding)
                    scored.append((doc_id, sim))
                scored.sort(key=lambda x: x[1], reverse=True)
                vector_results = scored[:fetch_limit]

            # RRF-fuse within tier using the existing merge_results helper.
            merged = merge_results(
                fts5_results,
                vector_results,
                k=self.rrf_k,
                weight_fts5=self.weight_fts5,
                weight_vector=self.weight_vector,
                top_k=limit_per_tier,
            )

            # Apply tier weight as a post-fusion multiplier. Creates new
            # SearchResult instances so the caller can never observe
            # mutation of a merge_results output (immutability rule).
            weight = tier_weights.get(tier, 1.0)
            weighted: list[SearchResult] = [
                SearchResult(
                    doc_id=r.doc_id,
                    content=r.content,
                    category=r.category,
                    fts5_rank=r.fts5_rank,
                    vector_rank=r.vector_rank,
                    fts5_score=r.fts5_score,
                    vector_score=r.vector_score,
                    rrf_score=r.rrf_score * weight,
                    metadata=dict(r.metadata),
                )
                for r in merged
            ]

            out[tier] = weighted

            # Sprint Mem-9.5 (#1877) — emit `memory.tier.retrievals` counter
            # per tier. `MetricsCollector.observe` does not accept labels, so
            # the tier label is folded into the metric name (e.g.
            # `memory.tier.retrievals.preference`). The observation is the
            # per-tier result count, so an empty tier emits a 0.0
            # observation — useful for "tier was queried but returned
            # nothing" auditability.
            if self._metrics is not None:
                self._metrics.observe(
                    f"memory.tier.retrievals.{tier.value}",
                    float(len(weighted)),
                )

        return out

    def _log_metrics(self, **kwargs: Any) -> None:
        """Log search metrics to JSONL file."""
        if not self._metrics_file:
            return
        try:
            self._metrics_file.parent.mkdir(parents=True, exist_ok=True)
            record = {"timestamp": time.time(), **kwargs}
            with open(self._metrics_file, "a") as f:
                f.write(json.dumps(record) + "\n")
        except OSError:
            pass

    def search_fts5_only(
        self,
        fts5_results: list[tuple[str, str, str, float]],
        top_k: int = DEFAULT_TOP_K,
    ) -> list[SearchResult]:
        """Fallback: FTS5-only search (no vector component)."""
        return merge_results(
            fts5_results,
            [],
            k=self.rrf_k,
            weight_fts5=1.0,  # Full weight to FTS5
            weight_vector=0.0,
            top_k=top_k,
        )

    def search_vector_only(
        self,
        query: str,
        documents: dict[str, str],
        top_k: int = DEFAULT_TOP_K,
    ) -> list[SearchResult]:
        """Fallback: vector-only search (no FTS5 component)."""
        query_embedding = self.embedding_engine.embed(query, is_query=True)
        scored: list[tuple[str, float]] = []
        for doc_id, text in documents.items():
            doc_embedding = self.embedding_engine.embed(text)
            sim = cosine_similarity(query_embedding, doc_embedding)
            scored.append((doc_id, sim))

        scored.sort(key=lambda x: x[1], reverse=True)
        return merge_results(
            [],
            scored[:top_k * 2],
            k=self.rrf_k,
            weight_fts5=0.0,
            weight_vector=1.0,
            top_k=top_k,
        )

    # ── Sprint 03.02 — 3-layer progressive disclosure API ──
    #
    # Concept-only port of claude-mem-style 3-layer progressive disclosure.
    # Default-OFF behind ``BridgeConfig.memory_v2_disclosure_enabled``.
    # ``flag_enabled=False`` is the legacy-fallback path that gives callers
    # the existing ``SearchResult`` shape — useful while plan-03 is still in
    # flight and 05.08 hasn't migrated all call sites.

    def search_ids(
        self,
        query: str,
        fts5_results: list[tuple[str, str, str, float]],
        documents: dict[str, str] | None = None,
        top_k: int = DEFAULT_TOP_K,
        *,
        flag_enabled: bool = True,
    ) -> list[MemoryRef] | list[SearchResult]:
        """Layer 1 — return content-free pointers ranked by RRF score.

        Each ``MemoryRef`` carries id + 1-line summary (≤120 chars) + score.
        No ``content`` field by construction: callers pay full-content
        tokens only after explicitly drilling into ``get_observations``.

        When ``flag_enabled`` is False, falls back to the legacy
        ``search()`` shape (full ``SearchResult`` with content). Wire the
        flag from ``BridgeConfig.memory_v2_disclosure_enabled``.
        """
        merged = self.search(query, fts5_results, documents=documents, top_k=top_k)
        if not flag_enabled:
            return merged

        refs: list[MemoryRef] = [
            MemoryRef(
                id=r.doc_id,
                summary=_truncate_summary(r.content),
                score=r.rrf_score,
                tier="L?",
            )
            for r in merged
        ]
        return refs

    def timeline(
        self,
        memory_ref: MemoryRef,
        events: list[tuple[datetime, str, str]] | None = None,
    ) -> list[Event]:
        """Layer 2 — return the timeline for a single memory pointer.

        ``events`` is an injected list of ``(timestamp, event_type, summary)``
        tuples — typed but storage-agnostic. Plan 03.04 will wire this to
        the temporal_knowledge / memory store. Until then, callers pass
        the source events directly so this method stays pure and testable.

        Each ``Event`` is content-free; drill into ``get_observations`` to
        load the actual content for the relevant span.
        """
        if not events:
            return []
        return [
            Event(
                memory_id=memory_ref.id,
                timestamp=ts,
                event_type=event_type,
                summary=_truncate_summary(summary),
            )
            for ts, event_type, summary in events
        ]

    def get_observations(
        self,
        memory_ref: MemoryRef,
        content: str,
        *,
        source: str = "memory",
        span: tuple[int, int] | None = None,
    ) -> list[Observation]:
        """Layer 3 — return the actual content for a memory pointer.

        ``span`` clamps to ``[0, len(content)]`` and is half-open in the
        Pythonic sense (``content[start:end]``). When ``span`` is ``None``,
        returns a single Observation covering the full content.

        Returns an empty list when ``content`` is empty or the clamped
        span has zero length — Layer 3 should never silently fabricate
        substrings.
        """
        if not content:
            return []

        if span is None:
            start, end = 0, len(content)
        else:
            raw_start, raw_end = span
            start = max(0, min(int(raw_start), len(content)))
            end = max(start, min(int(raw_end), len(content)))

        if end <= start:
            return []

        return [
            Observation(
                memory_id=memory_ref.id,
                span_start=start,
                span_end=end,
                content=content[start:end],
                source=source,
            )
        ]
