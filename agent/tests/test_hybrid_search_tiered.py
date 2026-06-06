"""Tests for HybridSearch.search_tiered() — Sprint Mem-5 (#1846).

Validates the per-tier RRF-fused retrieval path introduced for the
memory-tier-architecture epic. The existing ``search()`` regression check
sits at the tail of the file so that any future bisect lands here only if
``search_tiered`` is what changed.

Test DB construction mirrors the production schema's tier-relevant slice:
``knowledge`` (with ``tier`` column + ``idx_knowledge_tier`` index from
Mem-2's Migration 14) plus the ``knowledge_fts`` virtual table and its
insert trigger. We use a sync sqlite3 connection (matching
``HybridSearch.search_tiered``'s expected argument type).
"""

from __future__ import annotations

import logging
import sqlite3

import pytest

from bridge.hybrid_search import HybridSearch, SearchResult
from bridge.local_embeddings import LocalEmbeddingEngine
from bridge.memory_tiers import MemoryTier


# ── Fixtures ──


def _build_tiered_schema(conn: sqlite3.Connection) -> None:
    """Create the minimal knowledge + knowledge_fts schema with tier column.

    Mirrors the production schema post-Migration-14: ``knowledge`` has a
    ``tier`` column with ``idx_knowledge_tier`` index; ``knowledge_fts``
    is the external-content FTS5 table joined by rowid.
    """
    conn.executescript(
        """
        CREATE TABLE knowledge (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            tags TEXT,
            category TEXT DEFAULT 'reference',
            archived INTEGER DEFAULT 0,
            source TEXT NOT NULL DEFAULT 'agent',
            tier TEXT DEFAULT 'context' NOT NULL
        );
        CREATE INDEX idx_knowledge_tier ON knowledge(tier);

        CREATE VIRTUAL TABLE knowledge_fts USING fts5(
            key, value, tags, category,
            content='knowledge',
            content_rowid='rowid'
        );

        CREATE TRIGGER knowledge_ai AFTER INSERT ON knowledge BEGIN
            INSERT INTO knowledge_fts(rowid, key, value, tags, category)
            VALUES (new.rowid, new.key, new.value, new.tags, new.category);
        END;
        """
    )


def _seed(conn: sqlite3.Connection, rows: list[tuple[str, str, str]]) -> None:
    """Seed knowledge rows. Each tuple: (key, value, tier)."""
    for key, value, tier in rows:
        conn.execute(
            "INSERT INTO knowledge (key, value, tier) VALUES (?, ?, ?)",
            (key, value, tier),
        )
    conn.commit()


@pytest.fixture
def engine(tmp_path):
    """Hash-fallback embedding engine — no ONNX/CoreML model required."""
    return LocalEmbeddingEngine(model_dir=tmp_path / "nomodel")


@pytest.fixture
def hybrid(engine, tmp_path):
    return HybridSearch(engine, metrics_file=tmp_path / "metrics.jsonl")


@pytest.fixture
def db():
    """In-memory sqlite3 connection with the tiered schema."""
    conn = sqlite3.connect(":memory:")
    _build_tiered_schema(conn)
    yield conn
    conn.close()


# ── Tests ──


class TestSearchTieredShape:
    def test_returns_dict_keyed_by_all_tiers(self, hybrid, db):
        """Empty seed → every MemoryTier key present, all values []."""
        result = hybrid.search_tiered("anything", db_connection=db)
        assert isinstance(result, dict)
        assert set(result.keys()) == set(MemoryTier)
        for tier in MemoryTier:
            assert result[tier] == []

    def test_per_tier_filter_isolates_results(self, hybrid, db):
        """Seed 3-3-3 across tiers, all matching the same query — each
        tier returns exactly its own rows."""
        _seed(db, [
            ("p1", "dark mode preference setting", "preference"),
            ("p2", "dark mode toggle in dark theme", "preference"),
            ("p3", "dark mode default behavior", "preference"),
            ("d1", "decision to ship dark mode", "decision"),
            ("d2", "dark mode shipping decision approved", "decision"),
            ("d3", "approved dark mode rollout decision", "decision"),
            ("c1", "context note about dark mode", "context"),
            ("c2", "transient log mentioning dark mode", "context"),
            ("c3", "dark mode context-only ephemeral", "context"),
        ])
        result = hybrid.search_tiered("dark", db_connection=db)
        assert {r.doc_id for r in result[MemoryTier.PREFERENCE]} == {"p1", "p2", "p3"}
        assert {r.doc_id for r in result[MemoryTier.DECISION]} == {"d1", "d2", "d3"}
        assert {r.doc_id for r in result[MemoryTier.CONTEXT]} == {"c1", "c2", "c3"}

    def test_query_plan_uses_idx_knowledge_tier(self, hybrid, db):
        """EXPLAIN QUERY PLAN for the per-tier FTS5 SELECT shows the
        idx_knowledge_tier index in use.

        The ``INDEXED BY idx_knowledge_tier`` hint inside search_tiered
        is the load-bearing piece that makes the index usage explicit.
        Without it, SQLite's planner drives off FTS5 and applies the
        tier predicate as a residual filter — functionally correct but
        skips the index Mem-2 added.
        """
        _seed(db, [("p1", "alpha beta gamma", "preference")])

        # Mirror the literal SELECT issued by search_tiered.
        plan_rows = db.execute(
            """EXPLAIN QUERY PLAN
               SELECT k.key, k.value, k.tags, k.category, rank
               FROM knowledge k INDEXED BY idx_knowledge_tier
               JOIN knowledge_fts ON knowledge_fts.rowid = k.rowid
               WHERE k.tier = ?
                 AND knowledge_fts MATCH ?
                 AND (k.archived IS NULL OR k.archived = 0)
               ORDER BY rank
               LIMIT ?""",
            ("preference", "alpha", 10),
        ).fetchall()
        plan_text = " | ".join(" ".join(str(c) for c in row) for row in plan_rows)
        assert "idx_knowledge_tier" in plan_text, (
            f"Expected idx_knowledge_tier in query plan, got: {plan_text}"
        )


class TestTierWeights:
    def test_explicit_weights_post_scale_rrf(self, hybrid, db):
        """tier_weights={PREFERENCE:1.0, DECISION:0.5} → preference RRF
        of 0.8 must outscore decision RRF of 0.9 after multiplication
        (0.8 * 1.0 = 0.8 vs 0.9 * 0.5 = 0.45)."""
        _seed(db, [
            ("p1", "alpha alpha alpha alpha", "preference"),
            ("d1", "alpha alpha alpha alpha", "decision"),
            ("c1", "alpha alpha alpha alpha", "context"),
        ])
        result = hybrid.search_tiered(
            "alpha",
            db_connection=db,
            tier_weights={
                MemoryTier.PREFERENCE: 1.0,
                MemoryTier.DECISION: 0.5,
                MemoryTier.CONTEXT: 0.1,
            },
        )
        p_score = result[MemoryTier.PREFERENCE][0].rrf_score
        d_score = result[MemoryTier.DECISION][0].rrf_score
        c_score = result[MemoryTier.CONTEXT][0].rrf_score
        # All three matched the same query against identical content —
        # base RRF is the same; the multiplier produces the ordering.
        assert p_score > d_score > c_score
        assert p_score == pytest.approx(d_score * 2, rel=0.01)
        assert d_score == pytest.approx(c_score * 5, rel=0.01)

    def test_default_weights_from_tier_policy(self, hybrid, db):
        """Without explicit tier_weights, weights resolve from
        TierPolicy.retrieval_weight defaults (1.0 / 0.7 / 0.4)."""
        _seed(db, [
            ("p1", "alpha alpha alpha alpha", "preference"),
            ("d1", "alpha alpha alpha alpha", "decision"),
            ("c1", "alpha alpha alpha alpha", "context"),
        ])
        result = hybrid.search_tiered("alpha", db_connection=db)
        p_score = result[MemoryTier.PREFERENCE][0].rrf_score
        d_score = result[MemoryTier.DECISION][0].rrf_score
        c_score = result[MemoryTier.CONTEXT][0].rrf_score
        # Base RRF identical across all three; weights are 1.0 / 0.7 / 0.4
        # from Mem-1 defaults.
        assert p_score > d_score > c_score
        assert d_score == pytest.approx(p_score * 0.7, rel=0.05)
        assert c_score == pytest.approx(p_score * 0.4, rel=0.05)


class TestEmptyAndLimit:
    def test_empty_tier_returns_empty_list_not_missing_key(self, hybrid, db):
        """Seed only one tier — the others map to [] (key present)."""
        _seed(db, [
            ("p1", "alpha beta", "preference"),
            ("p2", "alpha gamma", "preference"),
        ])
        result = hybrid.search_tiered("alpha", db_connection=db)
        assert len(result[MemoryTier.PREFERENCE]) >= 1
        assert result[MemoryTier.DECISION] == []
        assert result[MemoryTier.CONTEXT] == []
        # All three keys present even when empty.
        assert MemoryTier.DECISION in result
        assert MemoryTier.CONTEXT in result

    def test_limit_per_tier_caps_list_length(self, hybrid, db):
        """Seed 15 matching preference rows — limit_per_tier=5 returns ≤5."""
        _seed(db, [
            (f"p{i}", f"alpha row {i}", "preference") for i in range(15)
        ])
        result = hybrid.search_tiered(
            "alpha", db_connection=db, limit_per_tier=5,
        )
        assert len(result[MemoryTier.PREFERENCE]) <= 5
        assert len(result[MemoryTier.PREFERENCE]) > 0  # at least some hits


class TestSearchTieredEscaping:
    @pytest.mark.parametrize(
        "query",
        [
            "Whats my Discord OAuth setup?",
            "Cal.com booking webhook config?",
            "Recent decisions about agent dispatch?",
        ],
    )
    def test_punctuated_queries_do_not_log_fts5_syntax_warnings(
        self,
        hybrid,
        db,
        caplog,
        query,
    ):
        """Operator-style prompts should be safe for tiered FTS5 MATCH."""
        _seed(db, [
            (
                "p-discord-oauth",
                "Whats my Discord OAuth setup for agent login",
                "preference",
            ),
            (
                "c-cal-webhook",
                "Cal.com booking webhook config for scheduling",
                "context",
            ),
            (
                "d-agent-dispatch",
                "Recent decisions about agent dispatch routing",
                "decision",
            ),
        ])

        caplog.set_level(logging.WARNING, logger="bridge.hybrid_search")

        result = hybrid.search_tiered(query, db_connection=db)

        assert set(result) == set(MemoryTier)
        assert [
            record.getMessage()
            for record in caplog.records
            if "search_tiered: FTS5 fetch failed" in record.getMessage()
        ] == []


class TestImmutabilityAndRegression:
    def test_results_are_searchresult_instances(self, hybrid, db):
        """Each value list contains SearchResult instances, not bare tuples."""
        _seed(db, [("p1", "alpha beta gamma", "preference")])
        result = hybrid.search_tiered("alpha", db_connection=db)
        for tier_results in result.values():
            for r in tier_results:
                assert isinstance(r, SearchResult)

    def test_existing_search_untouched(self, hybrid):
        """Regression: the legacy search() method still works as
        test_hybrid_search.py expects. If this breaks, search_tiered
        introduced a side effect on shared state."""
        fts5 = [("doc1", "hello world", "cat", 10.0)]
        docs = {"doc1": "hello world", "doc2": "completely different"}
        results = hybrid.search("hello", fts5, documents=docs)
        assert len(results) >= 1
        assert results[0].doc_id == "doc1"
