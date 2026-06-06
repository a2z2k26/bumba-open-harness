"""query.py — retrieval side of the second-brain subsystem.

Sprint 05.08 (issue #1016) of the 2026-04-25 reference-audit bundle.
ADR sign-off: ``agent/docs/architecture/second-brain.md`` Decision 4
(``__AZ__`` 2026-05-01).

Why this exists
---------------
Sprint 05.08 needs ONE place that takes an operator (or bridge) query
string and returns ranked notes from the second brain. Two-tier
strategy keeps the index-first guarantee from Karpathy's gist while
letting Plan 03's hybrid_search engine carry the load once the wiki
has volume:

1. **Tier 1 — index-first**: rank :class:`IngestNote` instances
   produced by :mod:`bridge.second_brain.ingest`. Pure, deterministic,
   fast (no embedding pass, no DB hit). Works while the wiki is small.
2. **Tier 2 — hybrid_search fallback**: when the index returns fewer
   than ``fallthrough_threshold`` hits, fall through to
   :class:`bridge.hybrid_search.HybridSearch` (RRF fusion of FTS5 +
   vector). Costs more latency but covers high-cardinality queries.

Strategy is operator-tunable:

- ``index_first`` (default) — tier 1 → fall through if low hit count.
- ``index_only`` — tier 1 only; never call hybrid_search.
- ``hybrid_only`` — skip tier 1; go straight to hybrid_search.

Concept-only port
-----------------
The two-tier shape is informed by the Karpathy gist
(``concept-only-no-license``). Specifically: index.md as primary
retrieval surface, hybrid_search as the accelerator that earns its
place once the wiki has volume. No source copy.

Defensive contract
------------------
- Pure helpers (``score_index_match``, ``query_index``,
  ``merge_results``, ``query_hybrid``) are synchronous + side-effect
  free; only the top-level :func:`query` is async because the
  hybrid-search adapter may eventually do I/O.
- ``hybrid_only`` with ``hybrid_searcher=None`` is a configuration
  error and raises :class:`ValueError` rather than silently returning
  empty results.
- Deduplication on merge: when the same ``relpath`` appears in both
  tier outputs, the index hit wins (it carries the richer
  :class:`IngestNote`).
"""

from __future__ import annotations

import logging
import time
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Literal, Optional

from .ingest import IngestNote

logger = logging.getLogger(__name__)


QueryStrategy = Literal["index_first", "index_only", "hybrid_only"]
RetrievalSource = Literal["index", "hybrid", "none"]


# How many characters of body to keep around the first match for the
# snippet preview. 200 chars gives enough context to skim without
# blowing the response budget.
_SNIPPET_CHARS = 200

# Recency-bonus thresholds (days) — younger notes get a small score
# boost so freshly authored content surfaces over stale wiki entries
# of equal textual relevance.
_RECENCY_BONUS_DAYS_TIGHT = 7
_RECENCY_BONUS_DAYS_LOOSE = 30
_RECENCY_BONUS_TIGHT = 0.10
_RECENCY_BONUS_LOOSE = 0.05

# Backlink hit base score — used when a note has only a backlink hit
# (no title/body match). A note that wiki-links to one of the query
# terms is structurally relevant beyond mere text overlap.
_BACKLINK_BOOST = 0.30
# Backlink additive boost — used when a note has a text match AND a
# backlink hit. Smaller than the base score to keep the band layout
# sane: text match remains the primary signal.
_BACKLINK_BOOST_ADDITIVE = 0.05

# Grandfathered penalty — operator-canonical content that predates the
# Bumba schema scores lower so freshly curated notes win on ties. Not
# punitive; just a tie-breaker reflecting "Bumba did not author this,
# so we have less confidence in its current relevance signal".
_GRANDFATHERED_PENALTY = 0.10

# Title scoring band — exact match wins; partial coverage scales between
# two anchors so the curve is smooth (rather than a step function).
_TITLE_PARTIAL_MIN = 0.50
_TITLE_PARTIAL_MAX = 0.90
# Body-only matches earn a smaller band — the title is the operator's
# explicit categorical hint, the body is incidental coverage.
_BODY_MATCH_MIN = 0.20
_BODY_MATCH_MAX = 0.50


@dataclass(frozen=True)
class QueryResult:
    """One retrieved note with retrieval-side metadata.

    ``snippet`` is a short preview around the first match; callers
    typically render it inline with the title. ``score`` is in
    ``[0.0, 1.0]`` after clamping. ``source`` records which tier
    produced the hit so operator dashboards can tell whether the
    fallthrough fired.
    """

    relpath: str
    title: str
    snippet: str
    score: float
    source: RetrievalSource
    note: Optional[IngestNote] = None


@dataclass(frozen=True)
class QueryResponse:
    """Aggregate retrieval result + diagnostics.

    ``fallthrough_triggered`` is the durable signal for the operator
    digest: "did the index alone cover this query, or did we need
    hybrid_search?". When it stays False for weeks at a time, the
    accelerator is a sunk cost and the operator can disable it.
    """

    query: str
    results: tuple[QueryResult, ...]
    total_index_hits: int
    total_hybrid_hits: int
    strategy: QueryStrategy
    fallthrough_triggered: bool
    duration_seconds: float


# ---------------- pure helpers ---------------- #


def _tokenize(text: str) -> list[str]:
    """Lowercase + whitespace-split tokenizer.

    Intentionally minimal — second-brain queries are short operator
    phrases, not full-text search inputs. Punctuation stays attached
    to the token; the score function uses ``in`` substring matching
    which is forgiving of trailing punctuation in titles.
    """
    if not text:
        return []
    return [t for t in text.lower().split() if t]


def _coverage(query_tokens: list[str], target: str) -> float:
    """Fraction of ``query_tokens`` present (substring) in ``target``.

    Returns ``0.0`` when ``query_tokens`` is empty so the caller can
    skip both partial-match bands cleanly. Matching is case-folded
    via lowercased ``target``.
    """
    if not query_tokens:
        return 0.0
    target_lower = target.lower()
    hits = sum(1 for tok in query_tokens if tok in target_lower)
    return hits / len(query_tokens)


def _parse_iso_to_utc(iso_str: str) -> Optional[datetime]:
    """Best-effort ISO-8601 parse → timezone-aware UTC datetime.

    Returns ``None`` when the string is missing/malformed so the
    caller can simply skip the recency bonus. ``IngestNote.last_seen_iso``
    is produced by :func:`datetime.now(timezone.utc).isoformat`, so
    the happy path always parses; this guards against hand-written
    fixtures and downstream serialisation drift.
    """
    if not iso_str:
        return None
    try:
        # Python 3.11+ accepts trailing 'Z' for UTC; older callers may
        # have stripped it — handle both shapes defensively.
        normalized = iso_str.replace("Z", "+00:00") if iso_str.endswith("Z") else iso_str
        dt = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _recency_bonus(last_seen_iso: str, *, now: Optional[datetime] = None) -> float:
    """Return the recency score bonus for ``last_seen_iso``.

    Two tiers: ≤7 days → +0.10, ≤30 days → +0.05, older → 0.0. The
    bonus is intentionally small relative to title-match weight; it
    breaks ties between two equally-relevant notes by preferring the
    fresher one.
    """
    seen = _parse_iso_to_utc(last_seen_iso)
    if seen is None:
        return 0.0
    reference = now or datetime.now(timezone.utc)
    delta_days = (reference - seen).total_seconds() / 86400.0
    if delta_days <= _RECENCY_BONUS_DAYS_TIGHT:
        return _RECENCY_BONUS_TIGHT
    if delta_days <= _RECENCY_BONUS_DAYS_LOOSE:
        return _RECENCY_BONUS_LOOSE
    return 0.0


def _clamp(value: float, lo: float = 0.0, hi: float = 1.0) -> float:
    """Clamp ``value`` to ``[lo, hi]`` — defensive against drift in
    the additive scoring buckets."""
    if value < lo:
        return lo
    if value > hi:
        return hi
    return value


def score_index_match(
    query: str,
    note: IngestNote,
    *,
    now: Optional[datetime] = None,
) -> float:
    """Score ``query`` against ``note`` for tier-1 index retrieval.

    Scoring shape:

    - **Exact title match** (case-folded, stripped) → base ``1.0``.
    - **Title contains all query tokens** → base scales up to ``0.90``
      proportional to coverage (so a 1-of-2 partial scores below 0.90).
    - **Title contains some query tokens** → base ``0.50–0.90``.
    - **Body contains query tokens** (no title hit) → base ``0.20–0.50``
      proportional to fraction of tokens covered.
    - **Backlink hit** (no title/body hit) → base ``0.30``; otherwise
      acts as an additive boost ``+0.05``.
    - **Recency bonus** → applies only when at least one match bucket
      fired: ``+0.10`` (≤7d) / ``+0.05`` (≤30d).
    - **Grandfathered penalty** → ``-0.10`` applied when at least one
      match bucket fired.

    Result is clamped to ``[0.0, 1.0]``. Pure function. ``now`` is
    injectable so tests pin the recency boundary deterministically.

    The "match required" gating prevents bonuses from manufacturing a
    non-zero score for an unrelated note (e.g. a fresh, grandfathered
    note with no textual / structural signal stays at ``0.0``).
    """
    query_lower = query.strip().lower()
    if not query_lower:
        return 0.0

    title_lower = (note.title or "").strip().lower()
    body = note.summary or ""  # IngestNote keeps body summary, not full text.
    tokens = _tokenize(query_lower)

    base_score = 0.0
    matched = False

    # Title bands (exact > partial > body-fallback). Only one band fires.
    if title_lower and title_lower == query_lower:
        base_score = 1.0
        matched = True
    else:
        title_cov = _coverage(tokens, note.title or "")
        if title_cov > 0.0:
            base_score = _TITLE_PARTIAL_MIN + (
                (_TITLE_PARTIAL_MAX - _TITLE_PARTIAL_MIN) * title_cov
            )
            matched = True
        else:
            body_cov = _coverage(tokens, body)
            if body_cov > 0.0:
                base_score = _BODY_MATCH_MIN + (
                    (_BODY_MATCH_MAX - _BODY_MATCH_MIN) * body_cov
                )
                matched = True

    # Backlink: serves as both base score (when no other match) and
    # additive boost (when a text match already fired). Without this
    # split, a backlink-only note with backlink-boost > 0 would score
    # nothing despite carrying real structural signal.
    backlink_match = False
    if note.backlinks and tokens:
        joined = " ".join(note.backlinks).lower()
        if any(tok in joined for tok in tokens):
            backlink_match = True

    if backlink_match:
        if matched:
            # Additive boost on top of the existing text match band.
            base_score += _BACKLINK_BOOST_ADDITIVE
        else:
            base_score = _BACKLINK_BOOST
        matched = True

    if not matched:
        # No textual / structural signal — bonuses do not apply. The
        # note is irrelevant to this query.
        return 0.0

    # Recency bonus — small, tie-breaking only.
    base_score += _recency_bonus(note.last_seen_iso, now=now)

    # Grandfathered penalty — operator content scores slightly lower.
    if note.is_grandfathered:
        base_score -= _GRANDFATHERED_PENALTY

    return _clamp(base_score)


def _build_snippet(note: IngestNote, query: str) -> str:
    """Produce a short preview around the first query-token match.

    Falls back to the leading slice of ``note.summary`` when no token
    matches (the note still ranked, e.g. on backlinks). Snippet is
    bounded to :data:`_SNIPPET_CHARS` characters.
    """
    body = note.summary or ""
    if not body:
        return ""
    tokens = _tokenize(query)
    body_lower = body.lower()
    for tok in tokens:
        idx = body_lower.find(tok)
        if idx == -1:
            continue
        # Centre the snippet on the match.
        radius = _SNIPPET_CHARS // 2
        start = max(0, idx - radius)
        end = min(len(body), start + _SNIPPET_CHARS)
        snippet = body[start:end]
        if start > 0:
            snippet = "…" + snippet
        if end < len(body):
            snippet = snippet + "…"
        return snippet
    return body[:_SNIPPET_CHARS]


def query_index(
    query: str,
    notes: Iterable[IngestNote],
    *,
    k: int = 10,
    min_score: float = 0.20,
    now: Optional[datetime] = None,
) -> tuple[QueryResult, ...]:
    """Tier-1 retrieval: rank ``notes`` by :func:`score_index_match`.

    Returns the top-``k`` :class:`QueryResult` tuples whose score is
    at least ``min_score``. Empty input → empty result. Pure function.

    Sort is stable on ``(relpath)`` to keep equal-score outputs
    deterministic across runs (the spec ships a fixed-fixture latency
    test that depends on this).
    """
    scored: list[tuple[float, IngestNote]] = []
    for note in notes:
        score = score_index_match(query, note, now=now)
        if score >= min_score:
            scored.append((score, note))
    # Stable secondary sort on relpath so equal scores have a
    # deterministic order across runs.
    scored.sort(key=lambda pair: (-pair[0], pair[1].relpath))
    out: list[QueryResult] = []
    for score, note in scored[:k]:
        out.append(
            QueryResult(
                relpath=note.relpath,
                title=note.title,
                snippet=_build_snippet(note, query),
                score=score,
                source="index",
                note=note,
            ),
        )
    return tuple(out)


def _coerce_hybrid_score(raw: Any) -> float:
    """Coerce a hybrid SearchResult score to a clamped ``[0.0, 1.0]`` float.

    ``HybridSearch.search`` reports ``rrf_score`` in roughly
    ``[0.0, 1.0]`` but the upper bound is not strictly enforced by the
    RRF formula. Clamp defensively so :class:`QueryResult.score`
    invariant holds regardless of upstream changes.
    """
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return 0.0
    return _clamp(value)


def query_hybrid(
    query: str,
    *,
    hybrid_searcher: object,
    k: int = 10,
) -> tuple[QueryResult, ...]:
    """Tier-2 retrieval: delegate to a ``HybridSearch``-shaped object.

    The searcher is duck-typed: any object exposing ``search(query, top_k=...)``
    that returns objects with ``doc_id`` / ``content`` / ``rrf_score``
    attributes (i.e. :class:`bridge.hybrid_search.SearchResult`) plugs
    in. The duck typing keeps this layer testable without importing
    the embedding stack.

    Translates each :class:`SearchResult` to a :class:`QueryResult`
    with ``source="hybrid"``. The ``note`` field is left unset
    because the hybrid surface does not carry an :class:`IngestNote`.
    """
    if hybrid_searcher is None:
        raise ValueError("query_hybrid requires a non-None hybrid_searcher")

    search_fn = getattr(hybrid_searcher, "search", None)
    if not callable(search_fn):
        raise TypeError(
            "hybrid_searcher must expose a callable .search(query, top_k=...) method",
        )

    raw_results = search_fn(query, top_k=k)
    if raw_results is None:
        return ()

    out: list[QueryResult] = []
    for raw in raw_results:
        relpath = getattr(raw, "doc_id", "") or ""
        if not relpath:
            continue
        content = getattr(raw, "content", "") or ""
        title = relpath.rsplit("/", 1)[-1].removesuffix(".md") or relpath
        snippet = content[:_SNIPPET_CHARS] if content else ""
        score = _coerce_hybrid_score(getattr(raw, "rrf_score", 0.0))
        out.append(
            QueryResult(
                relpath=relpath,
                title=title,
                snippet=snippet,
                score=score,
                source="hybrid",
            ),
        )
    return tuple(out)


def merge_results(
    index_results: tuple[QueryResult, ...],
    hybrid_results: tuple[QueryResult, ...],
    *,
    k: int = 10,
) -> tuple[QueryResult, ...]:
    """Merge two result tuples by score, dedup by ``relpath``, top-``k``.

    Index results win on tie because they carry the richer
    :class:`IngestNote` payload. Final order is score-descending with
    a stable secondary sort on ``relpath`` so callers see the same
    ordering on identical inputs across runs.
    """
    by_relpath: dict[str, QueryResult] = {}
    # Index first so duplicates from the hybrid set never overwrite.
    for result in index_results:
        by_relpath[result.relpath] = result
    for result in hybrid_results:
        if result.relpath in by_relpath:
            continue
        by_relpath[result.relpath] = result
    merged = sorted(
        by_relpath.values(),
        key=lambda r: (-r.score, r.relpath),
    )
    return tuple(merged[:k])


# ---------------- top-level entry point ---------------- #


async def query(
    query_text: str,
    *,
    notes: Iterable[IngestNote],
    hybrid_searcher: Optional[object] = None,
    strategy: QueryStrategy = "index_first",
    k: int = 10,
    fallthrough_threshold: int = 3,
    min_score: float = 0.20,
    now: Optional[datetime] = None,
) -> QueryResponse:
    """Top-level retrieval — applies strategy + fallthrough rules.

    Args:
        query_text: Operator-supplied query string.
        notes: :class:`IngestNote` iterable (typically the output of
            :func:`bridge.second_brain.ingest.ingest_vault`). Consumed
            once — pass a tuple/list if the caller needs to retain it.
        hybrid_searcher: Optional :class:`bridge.hybrid_search.HybridSearch`
            (or any duck-typed equivalent). Required for
            ``hybrid_only``; advisory for ``index_first``.
        strategy:
            - ``index_first`` — tier 1 → fall through if hits below
              ``fallthrough_threshold`` AND a searcher is available.
            - ``index_only`` — tier 1 only; never call hybrid_search.
            - ``hybrid_only`` — skip tier 1; call hybrid_search.
        k: Top-K cap on the final merged result.
        fallthrough_threshold: Index-hit count below which the
            ``index_first`` strategy invokes hybrid_search.
        min_score: Tier-1 score floor.
        now: Injectable reference time for recency bonus.

    Returns:
        :class:`QueryResponse` with results, diagnostics, and the
        ``fallthrough_triggered`` signal.

    Raises:
        ValueError: ``strategy="hybrid_only"`` with
            ``hybrid_searcher=None``, or unrecognised strategy.
    """
    start_monotonic = time.monotonic()

    # Materialise once so we can both scan + count without re-iterating.
    notes_tuple: tuple[IngestNote, ...] = tuple(notes)

    if strategy == "hybrid_only":
        if hybrid_searcher is None:
            raise ValueError(
                "strategy='hybrid_only' requires a non-None hybrid_searcher",
            )
        hybrid_results = query_hybrid(query_text, hybrid_searcher=hybrid_searcher, k=k)
        merged = merge_results((), hybrid_results, k=k)
        return QueryResponse(
            query=query_text,
            results=merged,
            total_index_hits=0,
            total_hybrid_hits=len(hybrid_results),
            strategy=strategy,
            fallthrough_triggered=False,
            duration_seconds=time.monotonic() - start_monotonic,
        )

    if strategy not in ("index_first", "index_only"):
        raise ValueError(
            f"unknown strategy {strategy!r}; expected one of "
            "'index_first', 'index_only', 'hybrid_only'",
        )

    index_results = query_index(
        query_text,
        notes_tuple,
        k=k,
        min_score=min_score,
        now=now,
    )

    fallthrough_triggered = False
    hybrid_results: tuple[QueryResult, ...] = ()
    if strategy == "index_first":
        below_threshold = len(index_results) < fallthrough_threshold
        can_fallthrough = hybrid_searcher is not None
        if below_threshold and can_fallthrough:
            fallthrough_triggered = True
            try:
                hybrid_results = query_hybrid(
                    query_text,
                    hybrid_searcher=hybrid_searcher,
                    k=k,
                )
            except (ValueError, TypeError) as exc:
                # Defensive: a malformed searcher should not abort the
                # whole query — log + degrade to index-only output.
                logger.warning(
                    "second-brain query: hybrid fallback raised %s; "
                    "returning index-only results",
                    type(exc).__name__,
                )
                hybrid_results = ()

    merged = merge_results(index_results, hybrid_results, k=k)
    return QueryResponse(
        query=query_text,
        results=merged,
        total_index_hits=len(index_results),
        total_hybrid_hits=len(hybrid_results),
        strategy=strategy,
        fallthrough_triggered=fallthrough_triggered,
        duration_seconds=time.monotonic() - start_monotonic,
    )


__all__ = [
    "QueryResponse",
    "QueryResult",
    "QueryStrategy",
    "RetrievalSource",
    "merge_results",
    "query",
    "query_hybrid",
    "query_index",
    "score_index_match",
]
