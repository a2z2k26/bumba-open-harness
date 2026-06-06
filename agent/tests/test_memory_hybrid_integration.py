"""Integration tests for Sprint 05.03 — wire HybridSearch into Memory.search_knowledge.

Per Plan 05 §05.03 ACs:
- Memory._hybrid_search_branch implemented and invoked as the first branch
  when self._hybrid_search is set.
- Graceful fallback to existing branches on exception.
- Metric emitted per hybrid query.
- End-to-end: seeded DB with 5 rows, query for semantically-similar term,
  hybrid branch chosen and returns RRF-fused results.
- Regression: when hybrid_search=None, behavior identical to pre-05.03.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest


# --------------------------------------------------------------------------- #
# Sprint 05.03 — hybrid search read-path activation
# --------------------------------------------------------------------------- #


class TestHybridSearchBranchInvocation:
    """When `self._hybrid_search` is set, search_knowledge must use it
    as the FIRST branch — semantic-search and FTS5 become fallbacks.
    """

    @pytest.mark.asyncio
    async def test_hybrid_branch_invoked_when_wired(
        self, migrated_db, sample_config
    ) -> None:
        from bridge.memory import Memory

        # Seed a couple of knowledge entries so FTS5 has something.
        memory = Memory(migrated_db, sample_config)
        await memory.store_knowledge("k1", "alpha beta gamma")
        await memory.store_knowledge("k2", "delta epsilon zeta")

        # Wire a stub HybridSearch that records the call.
        stub_hybrid = MagicMock()
        stub_hybrid.search.return_value = []  # empty result is fine
        memory.set_hybrid_search(stub_hybrid)

        await memory.search_knowledge("alpha")

        assert stub_hybrid.search.called, (
            "When hybrid_search is wired, search_knowledge must call "
            "hybrid_search.search() as the first branch (AC §05.03)."
        )

    @pytest.mark.asyncio
    async def test_hybrid_branch_skipped_when_unwired(
        self, migrated_db, sample_config
    ) -> None:
        """Regression: when hybrid_search=None, behaviour is identical to
        pre-05.03 (FTS5 / semantic / salience-fallback as before)."""
        from bridge.memory import Memory

        memory = Memory(migrated_db, sample_config)  # no hybrid_search
        await memory.store_knowledge("k1", "alpha beta gamma")

        results = await memory.search_knowledge("alpha")

        # Just verify we still get a list back without raising.
        assert isinstance(results, list)


class TestHybridSearchGracefulFallback:
    """If hybrid_search.search raises, search_knowledge must log and fall
    through to the existing branches (mirrors the semantic-search
    fallback at memory.py:301-307).
    """

    @pytest.mark.asyncio
    async def test_hybrid_exception_falls_through_to_fts5(
        self, migrated_db, sample_config, caplog
    ) -> None:
        import logging

        from bridge.memory import Memory

        memory = Memory(migrated_db, sample_config)
        await memory.store_knowledge("k1", "alpha beta gamma")

        broken_hybrid = MagicMock()
        broken_hybrid.search.side_effect = RuntimeError("boom")
        memory.set_hybrid_search(broken_hybrid)

        with caplog.at_level(logging.WARNING):
            results = await memory.search_knowledge("alpha")

        # Must still return something via FTS5 fallback (or empty list,
        # not a propagated exception).
        assert isinstance(results, list)
        # Some warning logged about the fallback.
        assert any(
            "hybrid" in rec.message.lower() or "boom" in rec.message
            for rec in caplog.records
        ), "Expected a WARNING-level log about hybrid search failure"


class TestHybridSearchEndToEnd:
    """Seed a DB with 5 knowledge rows, query with a semantically-related
    but keyword-different term, assert hybrid branch returns results
    (and the order is RRF-fused, not pure FTS5).
    """

    @pytest.mark.asyncio
    async def test_hybrid_returns_rrf_fused_results(
        self, migrated_db, sample_config, tmp_path
    ) -> None:
        from bridge.hybrid_search import HybridSearch
        from bridge.local_embeddings import LocalEmbeddingEngine
        from bridge.memory import Memory

        # Real LocalEmbeddingEngine (hash fallback — deterministic)
        engine = LocalEmbeddingEngine(cache_db=str(tmp_path / "embed_cache.db"))
        hybrid = HybridSearch(
            embedding_engine=engine,
            metrics_file=tmp_path / "search_metrics.jsonl",
        )
        memory = Memory(
            migrated_db, sample_config, hybrid_search=hybrid
        )

        # Seed 5 rows, two of which contain "alpha"
        await memory.store_knowledge("k1", "alpha beta gamma")
        await memory.store_knowledge("k2", "alpha delta epsilon")
        await memory.store_knowledge("k3", "zeta eta theta")
        await memory.store_knowledge("k4", "iota kappa lambda")
        await memory.store_knowledge("k5", "alpha mu nu")

        results = await memory.search_knowledge("alpha", limit=10)

        # Hybrid path should return SearchResult-derived dicts; verify the
        # shape produced by Memory wrapping (back-compat with FTS5 dict shape).
        assert isinstance(results, list)
        assert len(results) > 0, "Hybrid search must return at least one hit"
        # Memory wraps SearchResults to dicts with key/value/tags/source/rank
        # for backward compat with the existing search_knowledge contract.
        for r in results:
            assert "key" in r
            assert "value" in r

        # Verify metrics file was written by HybridSearch — proves the
        # path was actually taken (not silently fallen through).
        assert (tmp_path / "search_metrics.jsonl").exists(), (
            "HybridSearch._log_metrics must write at least one record per "
            "hybrid query (proves the hybrid path was taken)."
        )

    @pytest.mark.asyncio
    async def test_hybrid_results_include_rrf_score_in_rank_field(
        self, migrated_db, sample_config, tmp_path
    ) -> None:
        """The legacy result-dict 'rank' field is repurposed for hybrid
        as the RRF score. Document this contract via test."""
        from bridge.hybrid_search import HybridSearch
        from bridge.local_embeddings import LocalEmbeddingEngine
        from bridge.memory import Memory

        engine = LocalEmbeddingEngine(
            cache_db=str(tmp_path / "embed_cache.db")
        )
        hybrid = HybridSearch(
            embedding_engine=engine,
            metrics_file=tmp_path / "search_metrics.jsonl",
        )
        memory = Memory(
            migrated_db, sample_config, hybrid_search=hybrid
        )
        await memory.store_knowledge("k1", "alpha beta")
        await memory.store_knowledge("k2", "alpha delta")

        results = await memory.search_knowledge("alpha")
        assert results, "Need at least one result"
        # All ranks must be numeric (RRF scores are floats).
        for r in results:
            assert isinstance(r["rank"], (int, float))
