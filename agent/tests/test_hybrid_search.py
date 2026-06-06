"""Tests for bridge.hybrid_search — RRF scoring, merge, hybrid search."""

from __future__ import annotations

import json
from dataclasses import fields as dataclass_fields
from datetime import datetime, timezone

import pytest

from bridge.hybrid_search import (
    RRF_K,
    SUMMARY_MAX_CHARS,
    WEIGHT_FTS5,
    WEIGHT_VECTOR,
    Event,
    HybridSearch,
    MemoryRef,
    Observation,
    SearchResult,
    compute_rrf_score,
    merge_results,
)
from bridge.local_embeddings import LocalEmbeddingEngine


@pytest.fixture
def engine(tmp_path):
    """Create a LocalEmbeddingEngine with hash fallback."""
    return LocalEmbeddingEngine(model_dir=tmp_path / "nomodel")


@pytest.fixture
def hybrid(engine, tmp_path):
    """Create a HybridSearch instance."""
    return HybridSearch(
        engine,
        metrics_file=tmp_path / "search_metrics.jsonl",
    )


# ── RRF Score Computation ──

class TestRRFScore:
    def test_fts5_only(self):
        score = compute_rrf_score(fts5_rank=1, vector_rank=None)
        expected = WEIGHT_FTS5 * (1.0 / (RRF_K + 1))
        assert abs(score - expected) < 1e-10

    def test_vector_only(self):
        score = compute_rrf_score(fts5_rank=None, vector_rank=1)
        expected = WEIGHT_VECTOR * (1.0 / (RRF_K + 1))
        assert abs(score - expected) < 1e-10

    def test_both_sources(self):
        score = compute_rrf_score(fts5_rank=1, vector_rank=1)
        expected = WEIGHT_FTS5 / (RRF_K + 1) + WEIGHT_VECTOR / (RRF_K + 1)
        assert abs(score - expected) < 1e-10

    def test_higher_rank_lower_score(self):
        score1 = compute_rrf_score(fts5_rank=1, vector_rank=None)
        score10 = compute_rrf_score(fts5_rank=10, vector_rank=None)
        assert score1 > score10

    def test_no_ranks_zero_score(self):
        assert compute_rrf_score(None, None) == 0.0

    def test_custom_weights(self):
        score = compute_rrf_score(
            fts5_rank=1, vector_rank=None,
            weight_fts5=1.0, weight_vector=0.0,
        )
        assert score > 0


# ── Result Merging ──

class TestMergeResults:
    def test_merge_disjoint(self):
        fts5 = [("doc1", "content1", "cat1", 10.0)]
        vector = [("doc2", 0.95)]
        merged = merge_results(fts5, vector)
        assert len(merged) == 2
        ids = {r.doc_id for r in merged}
        assert ids == {"doc1", "doc2"}

    def test_merge_overlapping(self):
        fts5 = [("doc1", "content", "cat", 10.0)]
        vector = [("doc1", 0.9)]
        merged = merge_results(fts5, vector)
        assert len(merged) == 1
        r = merged[0]
        assert r.fts5_rank == 1
        assert r.vector_rank == 1
        assert r.rrf_score > 0

    def test_overlap_scores_higher(self):
        # Doc in both lists should score higher than doc in only one
        fts5 = [("both", "c", "cat", 10.0), ("fts5_only", "c", "cat", 5.0)]
        vector = [("both", 0.9), ("vec_only", 0.8)]
        merged = merge_results(fts5, vector)
        both_result = next(r for r in merged if r.doc_id == "both")
        fts5_only = next(r for r in merged if r.doc_id == "fts5_only")
        assert both_result.rrf_score > fts5_only.rrf_score

    def test_top_k_limits(self):
        fts5 = [(f"doc{i}", f"content{i}", "cat", float(20 - i)) for i in range(20)]
        merged = merge_results(fts5, [], top_k=5)
        assert len(merged) == 5

    def test_empty_both(self):
        merged = merge_results([], [])
        assert merged == []

    def test_sorted_by_rrf_descending(self):
        fts5 = [("a", "c", "cat", 10.0), ("b", "c", "cat", 5.0)]
        vector = [("c", 0.99)]
        merged = merge_results(fts5, vector)
        scores = [r.rrf_score for r in merged]
        assert scores == sorted(scores, reverse=True)

    def test_preserves_metadata(self):
        fts5 = [("doc1", "the content", "facts", 8.0)]
        merged = merge_results(fts5, [])
        assert merged[0].content == "the content"
        assert merged[0].category == "facts"


# ── HybridSearch Class ──

class TestHybridSearch:
    def test_fts5_only_search(self, hybrid):
        fts5 = [("doc1", "hello world", "general", 10.0)]
        results = hybrid.search_fts5_only(fts5)
        assert len(results) == 1
        assert results[0].doc_id == "doc1"

    def test_vector_only_search(self, hybrid):
        docs = {"doc1": "hello world", "doc2": "foo bar"}
        results = hybrid.search_vector_only("hello", docs)
        assert len(results) == 2

    def test_hybrid_search(self, hybrid):
        fts5 = [("doc1", "hello world", "cat", 10.0)]
        docs = {"doc1": "hello world", "doc2": "completely different"}
        results = hybrid.search("hello", fts5, documents=docs)
        assert len(results) >= 1
        # doc1 should rank highest (appears in both)
        assert results[0].doc_id == "doc1"

    def test_hybrid_no_documents(self, hybrid):
        fts5 = [("doc1", "test", "cat", 5.0)]
        results = hybrid.search("test", fts5, documents=None)
        assert len(results) == 1

    def test_metrics_logged(self, hybrid, tmp_path):
        fts5 = [("doc1", "test", "cat", 5.0)]
        hybrid.search("test query", fts5)
        metrics_file = tmp_path / "search_metrics.jsonl"
        assert metrics_file.exists()
        record = json.loads(metrics_file.read_text().strip())
        assert "query" in record
        assert "total_time_ms" in record

    def test_search_returns_top_k(self, hybrid):
        fts5 = [(f"doc{i}", f"content{i}", "cat", float(20 - i)) for i in range(30)]
        results = hybrid.search("test", fts5, top_k=5)
        assert len(results) == 5


# ── Sprint 03.02 — claude-mem-style 3-layer progressive disclosure ──
#
# Concept-only port (no source copied). Tests verify the token-savings
# property: Layer 1 has no content, Layer 2 has no content, Layer 3 only
# returns the bytes the caller asked for.


class TestProgressiveDisclosure:
    def test_search_ids_returns_only_summaries_no_content_field(self, hybrid):
        """Layer 1 must be content-free by construction.

        ``MemoryRef`` is a frozen dataclass with no ``content`` field; the
        summary must respect SUMMARY_MAX_CHARS.
        """
        long_content = "lorem ipsum " * 50  # ~600 chars, well over 120
        fts5 = [
            ("doc1", long_content, "cat", 10.0),
            ("doc2", "short content", "cat", 5.0),
        ]
        refs = hybrid.search_ids("query", fts5)
        assert isinstance(refs, list)
        assert all(isinstance(r, MemoryRef) for r in refs)

        field_names = {f.name for f in dataclass_fields(MemoryRef)}
        assert "content" not in field_names
        assert {"id", "summary", "score", "tier"} <= field_names

        # Summary capped + non-empty
        for ref in refs:
            assert len(ref.summary) <= SUMMARY_MAX_CHARS
            assert ref.summary
        assert refs[0].score >= refs[-1].score  # ranked by score descending

    def test_timeline_excludes_content_field(self, hybrid):
        """Layer 2 timeline events must not carry full content."""
        ref = MemoryRef(id="m1", summary="ref summary", score=0.5)
        events_in = [
            (datetime(2026, 4, 26, tzinfo=timezone.utc), "created", "first write"),
            (datetime(2026, 4, 27, tzinfo=timezone.utc), "updated", "edit summary"),
            (datetime(2026, 4, 28, tzinfo=timezone.utc), "referenced", "looked up"),
            (datetime(2026, 4, 29, tzinfo=timezone.utc), "redacted", "PII pruned"),
        ]
        events = hybrid.timeline(ref, events=events_in)
        assert len(events) == 4
        assert all(isinstance(e, Event) for e in events)

        field_names = {f.name for f in dataclass_fields(Event)}
        assert "content" not in field_names
        assert {"memory_id", "timestamp", "event_type", "summary"} <= field_names

        # All events tied to the originating ref
        assert all(e.memory_id == "m1" for e in events)
        # All summaries 1-line and capped
        for e in events:
            assert "\n" not in e.summary
            assert len(e.summary) <= SUMMARY_MAX_CHARS

    def test_get_observations_respects_span_bounds(self, hybrid):
        """Layer 3 spans clamp to content length and never fabricate bytes."""
        ref = MemoryRef(id="m1", summary="x", score=0.1)
        body = "abcdefghij"  # 10 chars

        # Layer-3 dataclass shape — must carry full content + span markers
        obs_fields = {f.name for f in dataclass_fields(Observation)}
        assert {"memory_id", "span_start", "span_end", "content", "source"} <= obs_fields

        # Full-content path (span=None)
        full = hybrid.get_observations(ref, body)
        assert len(full) == 1
        assert isinstance(full[0], Observation)
        assert full[0].content == body
        assert full[0].span_start == 0
        assert full[0].span_end == 10
        assert full[0].source == "memory"
        assert full[0].memory_id == "m1"

        # Mid-span happy path
        mid = hybrid.get_observations(ref, body, span=(2, 6))
        assert len(mid) == 1
        assert mid[0].content == "cdef"
        assert mid[0].span_start == 2
        assert mid[0].span_end == 6

        # Out-of-bounds span clamps to content length
        clamped = hybrid.get_observations(ref, body, span=(8, 999))
        assert len(clamped) == 1
        assert clamped[0].content == "ij"
        assert clamped[0].span_end == 10

        # Negative start clamps to 0
        neg = hybrid.get_observations(ref, body, span=(-5, 3))
        assert len(neg) == 1
        assert neg[0].span_start == 0
        assert neg[0].content == "abc"

        # Empty content
        assert hybrid.get_observations(ref, "") == []

        # Inverted / zero-width span returns empty (no fabrication)
        assert hybrid.get_observations(ref, body, span=(5, 5)) == []
        assert hybrid.get_observations(ref, body, span=(7, 3)) == []

    def test_drill_down_sequence_total_chars_lt_baseline_search(self, hybrid):
        """Token-savings property — Layer 1 + Layer 2 cheaper than full search.

        For a corpus with one big match, the chars carried by ``search_ids``
        + ``timeline`` (no content) must be much smaller than the chars
        carried by the legacy ``search`` (which embeds full content). This
        is the whole point of progressive disclosure.
        """
        big_body = "long form content " * 200  # ~3600 chars
        fts5 = [
            ("doc1", big_body, "cat", 10.0),
            ("doc2", "short", "cat", 5.0),
        ]

        # Baseline: legacy search returns full content
        baseline = hybrid.search("query", fts5)
        baseline_chars = sum(len(r.content) for r in baseline)

        # Drill-down: pointers + timeline (no observations expanded)
        refs = hybrid.search_ids("query", fts5)
        assert isinstance(refs, list) and refs
        first = refs[0]
        events = hybrid.timeline(
            first,
            events=[(datetime(2026, 4, 26, tzinfo=timezone.utc), "created", "init")],
        )
        layer1_chars = sum(len(r.summary) for r in refs)
        layer2_chars = sum(len(e.summary) for e in events)
        drill_chars = layer1_chars + layer2_chars

        # Layer-1+2 must be a small fraction of the baseline content cost
        assert drill_chars < baseline_chars
        assert drill_chars * 4 < baseline_chars  # at least a 4x reduction

    def test_search_ids_with_flag_off_falls_back_to_legacy_search(self, hybrid):
        """Flag-OFF path returns legacy SearchResult shape unchanged.

        Existing call sites (Plans 05/07) must keep working until the
        operator flips ``memory_v2_disclosure_enabled`` on.
        """
        fts5 = [
            ("doc1", "hello world", "cat", 10.0),
            ("doc2", "another doc", "cat", 5.0),
        ]
        legacy = hybrid.search_ids("query", fts5, flag_enabled=False)
        assert isinstance(legacy, list)
        assert all(isinstance(r, SearchResult) for r in legacy)
        # Content preserved on legacy path
        ids = {r.doc_id for r in legacy}
        assert ids == {"doc1", "doc2"}
        assert any(r.content == "hello world" for r in legacy)


class TestProgressiveDisclosureFeatureFlag:
    def test_flag_default_off_on_bridgeconfig(self):
        """Feature flag is reachable on BridgeConfig and defaults False."""
        from bridge.config import BridgeConfig

        cfg = BridgeConfig()
        assert hasattr(cfg, "memory_v2_disclosure_enabled")
        assert cfg.memory_v2_disclosure_enabled is False

    def test_flag_toml_mapping_present(self):
        """`memory.v2_disclosure_enabled` TOML key maps to the flag field."""
        from bridge.config import _TOML_MAP

        assert _TOML_MAP["memory.v2_disclosure_enabled"] == "memory_v2_disclosure_enabled"
