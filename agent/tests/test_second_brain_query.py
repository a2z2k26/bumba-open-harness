"""Tests for ``bridge.second_brain.query`` — index-first + hybrid fallback.

Sprint 05.08 (issue #1016) of the 2026-04-25 reference-audit bundle.
ADR sign-off: Decision 4 (``__AZ__`` 2026-05-01) — index.md primary,
hybrid_search as accelerator.

Concept-only port — no source copy (Karpathy gist informs the
two-tier retrieval shape only).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from unittest.mock import MagicMock

import pytest

from bridge.second_brain.ingest import IngestNote
from bridge.second_brain.query import (
    QueryResponse,
    QueryResult,
    merge_results,
    query,
    query_hybrid,
    query_index,
    score_index_match,
)


# ---------------- helpers ---------------- #


def _make_note(
    *,
    relpath: str,
    title: str,
    summary: str = "",
    backlinks: tuple[str, ...] = (),
    is_grandfathered: bool = False,
    last_seen_iso: str | None = None,
) -> IngestNote:
    """Construct a minimal :class:`IngestNote` for scoring tests."""
    return IngestNote(
        relpath=relpath,
        kind="operator_canonical",
        title=title,
        summary=summary,
        frontmatter={},
        is_grandfathered=is_grandfathered,
        sha256="0" * 64,
        word_count=len(summary.split()) if summary else 0,
        backlinks=backlinks,
        last_seen_iso=last_seen_iso or datetime.now(timezone.utc).isoformat(),
    )


class _FakeSearchResult:
    """Duck-typed stand-in for :class:`bridge.hybrid_search.SearchResult`."""

    def __init__(
        self,
        doc_id: str,
        content: str = "",
        rrf_score: float = 0.5,
    ) -> None:
        self.doc_id = doc_id
        self.content = content
        self.rrf_score = rrf_score


class _FakeHybridSearcher:
    """Minimal hybrid-searcher fake with call counting."""

    def __init__(self, results: list[Any] | None = None) -> None:
        self.results = results or []
        self.call_count = 0
        self.last_query: str | None = None
        self.last_top_k: int | None = None

    def search(self, q: str, *, top_k: int = 10) -> list[Any]:
        self.call_count += 1
        self.last_query = q
        self.last_top_k = top_k
        return self.results


# ---------------- score_index_match ---------------- #


class TestScoreIndexMatch:
    """Pure scoring function — exact / partial / body / boost / penalty."""

    def test_exact_title_match_returns_one(self) -> None:
        # Use an old timestamp so recency bonus does not push past 1.0.
        old = datetime(2020, 1, 1, tzinfo=timezone.utc).isoformat()
        note = _make_note(relpath="a.md", title="Bumba", last_seen_iso=old)
        assert score_index_match("Bumba", note) == pytest.approx(1.0)

    def test_exact_title_match_case_insensitive(self) -> None:
        old = datetime(2020, 1, 1, tzinfo=timezone.utc).isoformat()
        note = _make_note(relpath="a.md", title="Bumba", last_seen_iso=old)
        assert score_index_match("bumba", note) == pytest.approx(1.0)

    def test_partial_title_match_proportional(self) -> None:
        old = datetime(2020, 1, 1, tzinfo=timezone.utc).isoformat()
        note = _make_note(
            relpath="a.md",
            title="Second Brain Architecture Reference",
            last_seen_iso=old,
        )
        # Three of three query tokens hit the title (full coverage).
        full_cov = score_index_match(
            "second brain architecture", note,
        )
        # Two of three query tokens hit (partial coverage).
        partial_cov = score_index_match(
            "second brain unknown_token", note,
        )
        # Proportional: more coverage → higher score within the 0.5–0.9 band.
        # Full coverage but title contains additional words, so we stay
        # in the partial-band ceiling (0.9) rather than the exact-match cap.
        assert 0.5 <= partial_cov <= 0.9
        assert 0.5 <= full_cov <= 0.9
        assert full_cov > partial_cov

    def test_body_only_match_lower_than_title(self) -> None:
        old = datetime(2020, 1, 1, tzinfo=timezone.utc).isoformat()
        title_match = _make_note(
            relpath="a.md",
            title="Foo Bar",
            summary="unrelated content",
            last_seen_iso=old,
        )
        body_match = _make_note(
            relpath="b.md",
            title="Other Topic",
            summary="this body mentions foo bar prominently",
            last_seen_iso=old,
        )
        title_score = score_index_match("foo bar", title_match)
        body_score = score_index_match("foo bar", body_match)
        assert title_score > body_score

    def test_body_only_score_in_band(self) -> None:
        old = datetime(2020, 1, 1, tzinfo=timezone.utc).isoformat()
        note = _make_note(
            relpath="a.md",
            title="Unrelated",
            summary="the body mentions xyzzy plenty",
            last_seen_iso=old,
        )
        score = score_index_match("xyzzy", note)
        assert 0.20 <= score <= 0.50

    def test_recency_bonus_visible_in_partial_band(self) -> None:
        now = datetime(2026, 5, 1, tzinfo=timezone.utc)
        recent = _make_note(
            relpath="recent.md",
            title="Topic alpha",
            last_seen_iso=(now - timedelta(days=2)).isoformat(),
        )
        stale = _make_note(
            relpath="stale.md",
            title="Topic alpha",
            last_seen_iso=(now - timedelta(days=200)).isoformat(),
        )
        # Partial title match (one of two tokens) keeps the score below
        # the 1.0 cap, so the recency bonus is observable.
        recent_score = score_index_match("Topic", recent, now=now)
        stale_score = score_index_match("Topic", stale, now=now)
        assert recent_score > stale_score

    def test_backlink_only_hit(self) -> None:
        old = datetime(2020, 1, 1, tzinfo=timezone.utc).isoformat()
        note = _make_note(
            relpath="a.md",
            title="Other",
            summary="ignore",
            backlinks=("Topic alpha",),
            last_seen_iso=old,
        )
        # No textual hit on title or summary; the backlink token "topic"
        # is the only signal. Score should be the backlink base 0.30.
        score = score_index_match("topic", note)
        assert score == pytest.approx(0.30)

    def test_grandfathered_penalty(self) -> None:
        old = datetime(2020, 1, 1, tzinfo=timezone.utc).isoformat()
        baseline = _make_note(
            relpath="a.md", title="Topic", last_seen_iso=old,
        )
        grandfathered = _make_note(
            relpath="b.md",
            title="Topic",
            is_grandfathered=True,
            last_seen_iso=old,
        )
        baseline_score = score_index_match("Topic", baseline)
        gf_score = score_index_match("Topic", grandfathered)
        # Both exact-title match → 1.0 base; gf gets penalty applied
        # before clamp, so it lands at 0.9.
        assert baseline_score == pytest.approx(1.0)
        assert gf_score == pytest.approx(0.9)

    def test_score_clamped_to_unit_interval(self) -> None:
        # Stack every bonus + exact-title to push past 1.0; clamp to 1.0.
        now = datetime(2026, 5, 1, tzinfo=timezone.utc)
        note = _make_note(
            relpath="a.md",
            title="Topic",
            backlinks=("Topic",),
            last_seen_iso=(now - timedelta(days=1)).isoformat(),
        )
        score = score_index_match("Topic", note, now=now)
        assert 0.0 <= score <= 1.0
        assert score == pytest.approx(1.0)

    def test_empty_query_returns_zero(self) -> None:
        note = _make_note(relpath="a.md", title="Topic")
        assert score_index_match("   ", note) == 0.0

    def test_no_match_returns_zero(self) -> None:
        # Use a recent timestamp to verify recency bonus does NOT
        # manufacture a non-zero score on an unrelated note.
        recent = datetime.now(timezone.utc).isoformat()
        note = _make_note(
            relpath="a.md",
            title="Completely Unrelated",
            summary="nothing in common",
            last_seen_iso=recent,
        )
        assert score_index_match("xyzzy plover", note) == 0.0


# ---------------- query_index ---------------- #


class TestQueryIndex:
    def test_empty_notes_returns_empty(self) -> None:
        assert query_index("anything", []) == ()

    def test_filters_below_min_score(self) -> None:
        notes = [
            _make_note(relpath="a.md", title="Foo"),
            _make_note(
                relpath="b.md",
                title="Unrelated",
                summary="some body content here",
            ),
        ]
        results = query_index("foo", notes, min_score=0.5)
        # Only the title-match passes the 0.5 floor.
        assert len(results) == 1
        assert results[0].relpath == "a.md"

    def test_returns_top_k_sorted(self) -> None:
        old = datetime(2020, 1, 1, tzinfo=timezone.utc).isoformat()
        notes = [
            _make_note(
                relpath="a.md", title="Topic alpha", last_seen_iso=old,
            ),
            _make_note(relpath="b.md", title="Topic", last_seen_iso=old),
            _make_note(
                relpath="c.md", title="Topic gamma", last_seen_iso=old,
            ),
        ]
        results = query_index("topic", notes, k=2)
        assert len(results) == 2
        # Exact match wins.
        assert results[0].relpath == "b.md"
        # Tie on partial score → relpath secondary sort (a < c).
        assert results[1].relpath == "a.md"

    def test_results_carry_source_index(self) -> None:
        notes = [_make_note(relpath="a.md", title="Hit")]
        results = query_index("Hit", notes)
        assert len(results) == 1
        assert results[0].source == "index"
        assert results[0].note is not None
        assert results[0].note.relpath == "a.md"

    def test_snippet_built_around_match(self) -> None:
        body = "x " * 100 + "marker " + "y " * 100
        note = _make_note(relpath="a.md", title="Other", summary=body)
        results = query_index("marker", [note], min_score=0.0)
        assert results
        snippet = results[0].snippet
        assert "marker" in snippet


# ---------------- query_hybrid ---------------- #


class TestQueryHybrid:
    def test_translates_search_results(self) -> None:
        searcher = _FakeHybridSearcher(
            results=[
                _FakeSearchResult(
                    "foo/bar.md", content="Some body", rrf_score=0.8,
                ),
                _FakeSearchResult(
                    "baz.md",
                    content="other content",
                    rrf_score=0.4,
                ),
            ],
        )
        results = query_hybrid("anything", hybrid_searcher=searcher, k=5)
        assert len(results) == 2
        first = results[0]
        assert first.relpath == "foo/bar.md"
        assert first.title == "bar"  # stripped .md
        assert first.snippet == "Some body"
        assert first.source == "hybrid"
        assert first.note is None
        assert first.score == pytest.approx(0.8)

    def test_score_clamped(self) -> None:
        searcher = _FakeHybridSearcher(
            results=[_FakeSearchResult("a.md", rrf_score=2.5)],
        )
        results = query_hybrid("q", hybrid_searcher=searcher)
        assert results[0].score == pytest.approx(1.0)

    def test_skips_blank_doc_id(self) -> None:
        searcher = _FakeHybridSearcher(
            results=[_FakeSearchResult("", rrf_score=0.9)],
        )
        results = query_hybrid("q", hybrid_searcher=searcher)
        assert results == ()

    def test_none_searcher_raises(self) -> None:
        with pytest.raises(ValueError, match="hybrid_searcher"):
            query_hybrid("q", hybrid_searcher=None)

    def test_searcher_without_search_method_raises(self) -> None:
        class Bad:
            pass

        with pytest.raises(TypeError, match="search"):
            query_hybrid("q", hybrid_searcher=Bad())


# ---------------- merge_results ---------------- #


class TestMergeResults:
    def test_dedupes_by_relpath_index_wins(self) -> None:
        index_note = _make_note(relpath="a.md", title="A")
        index_only = (
            QueryResult(
                relpath="a.md",
                title="A",
                snippet="from index",
                score=0.6,
                source="index",
                note=index_note,
            ),
        )
        hybrid_only = (
            QueryResult(
                relpath="a.md",
                title="A",
                snippet="from hybrid",
                score=0.9,  # higher score; should still lose to index.
                source="hybrid",
            ),
        )
        merged = merge_results(index_only, hybrid_only, k=10)
        assert len(merged) == 1
        assert merged[0].source == "index"
        assert merged[0].note is index_note

    def test_returns_top_k_after_merge(self) -> None:
        index = tuple(
            QueryResult(
                relpath=f"i{i}.md",
                title=f"i{i}",
                snippet="",
                score=0.5,
                source="index",
            )
            for i in range(3)
        )
        hybrid = tuple(
            QueryResult(
                relpath=f"h{i}.md",
                title=f"h{i}",
                snippet="",
                score=0.7,
                source="hybrid",
            )
            for i in range(3)
        )
        merged = merge_results(index, hybrid, k=2)
        assert len(merged) == 2
        # Hybrid wins on score (0.7 > 0.5).
        assert all(r.source == "hybrid" for r in merged)

    def test_sorted_by_score_descending(self) -> None:
        index = (
            QueryResult(
                relpath="a.md",
                title="a",
                snippet="",
                score=0.4,
                source="index",
            ),
            QueryResult(
                relpath="b.md",
                title="b",
                snippet="",
                score=0.9,
                source="index",
            ),
        )
        merged = merge_results(index, (), k=10)
        assert merged[0].relpath == "b.md"
        assert merged[1].relpath == "a.md"


# ---------------- query (top-level async) ---------------- #


@pytest.mark.asyncio
async def test_query_index_only_does_not_invoke_hybrid() -> None:
    notes = [_make_note(relpath="a.md", title="Hit")]
    searcher = MagicMock()
    response = await query(
        "Hit",
        notes=notes,
        hybrid_searcher=searcher,
        strategy="index_only",
    )
    assert isinstance(response, QueryResponse)
    assert response.fallthrough_triggered is False
    assert response.total_hybrid_hits == 0
    assert searcher.search.call_count == 0
    assert response.results
    assert response.results[0].source == "index"


@pytest.mark.asyncio
async def test_query_hybrid_only_without_searcher_raises() -> None:
    with pytest.raises(ValueError, match="hybrid_only"):
        await query(
            "anything",
            notes=[],
            hybrid_searcher=None,
            strategy="hybrid_only",
        )


@pytest.mark.asyncio
async def test_query_index_first_no_fallthrough_when_threshold_met() -> None:
    # 4 distinct hits, threshold is 3 → no fallthrough.
    notes = [
        _make_note(relpath=f"n{i}.md", title="Hit") for i in range(4)
    ]
    searcher = _FakeHybridSearcher()
    response = await query(
        "Hit",
        notes=notes,
        hybrid_searcher=searcher,
        strategy="index_first",
        fallthrough_threshold=3,
    )
    assert response.fallthrough_triggered is False
    assert searcher.call_count == 0
    assert response.total_index_hits == 4
    assert response.total_hybrid_hits == 0


@pytest.mark.asyncio
async def test_query_index_first_fallthrough_when_below_threshold() -> None:
    # Only 1 index hit; threshold = 3 → fallthrough fires.
    notes = [_make_note(relpath="single.md", title="Hit")]
    searcher = _FakeHybridSearcher(
        results=[
            _FakeSearchResult("h1.md", content="x", rrf_score=0.6),
            _FakeSearchResult("h2.md", content="y", rrf_score=0.5),
        ],
    )
    response = await query(
        "Hit",
        notes=notes,
        hybrid_searcher=searcher,
        strategy="index_first",
        fallthrough_threshold=3,
    )
    assert response.fallthrough_triggered is True
    assert searcher.call_count == 1
    assert response.total_index_hits == 1
    assert response.total_hybrid_hits == 2


@pytest.mark.asyncio
async def test_query_end_to_end_merges_distinct_results() -> None:
    # Index gives one hit; hybrid gives two distinct hits → 3 results.
    notes = [_make_note(relpath="single.md", title="Hit")]
    searcher = _FakeHybridSearcher(
        results=[
            _FakeSearchResult("h1.md", content="alpha", rrf_score=0.7),
            _FakeSearchResult("h2.md", content="beta", rrf_score=0.4),
        ],
    )
    response = await query(
        "Hit",
        notes=notes,
        hybrid_searcher=searcher,
        strategy="index_first",
        fallthrough_threshold=3,
        k=10,
    )
    assert len(response.results) == 3
    relpaths = {r.relpath for r in response.results}
    assert relpaths == {"single.md", "h1.md", "h2.md"}
    # Score-descending order across the merged set.
    scores = [r.score for r in response.results]
    assert scores == sorted(scores, reverse=True)


@pytest.mark.asyncio
async def test_query_index_first_no_searcher_does_not_fallthrough() -> None:
    notes = [_make_note(relpath="single.md", title="Hit")]
    response = await query(
        "Hit",
        notes=notes,
        hybrid_searcher=None,
        strategy="index_first",
        fallthrough_threshold=3,
    )
    assert response.fallthrough_triggered is False
    assert response.total_hybrid_hits == 0
    assert len(response.results) == 1


@pytest.mark.asyncio
async def test_query_hybrid_only_skips_index_walk() -> None:
    # Add an index-relevant note; hybrid_only must ignore it.
    notes = [_make_note(relpath="indexed.md", title="Hit")]
    searcher = _FakeHybridSearcher(
        results=[_FakeSearchResult("via-hybrid.md", rrf_score=0.5)],
    )
    response = await query(
        "Hit",
        notes=notes,
        hybrid_searcher=searcher,
        strategy="hybrid_only",
    )
    assert response.total_index_hits == 0
    assert response.total_hybrid_hits == 1
    assert {r.relpath for r in response.results} == {"via-hybrid.md"}


@pytest.mark.asyncio
async def test_query_unknown_strategy_raises() -> None:
    with pytest.raises(ValueError, match="unknown strategy"):
        await query(
            "q",
            notes=[],
            strategy="bogus",  # type: ignore[arg-type]
        )


@pytest.mark.asyncio
async def test_query_records_duration() -> None:
    notes = [_make_note(relpath="a.md", title="Hit")]
    response = await query("Hit", notes=notes, strategy="index_only")
    assert response.duration_seconds >= 0.0
