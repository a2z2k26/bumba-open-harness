"""Tests for bridge.vector_store — brute-force vector search (sqlite-vec fallback)."""

from __future__ import annotations


import pytest

from bridge.vector_store import VectorStore, _cosine_sim, _pack_vec, _unpack_vec


@pytest.fixture
def store(tmp_path):
    """Create a VectorStore with brute-force fallback."""
    db_path = tmp_path / "vectors.db"
    vs = VectorStore(db_path)
    vs.connect()
    yield vs
    vs.close()


class TestPackUnpack:
    def test_roundtrip(self):
        vec = [1.0, -0.5, 0.0, 0.123]
        packed = _pack_vec(vec)
        unpacked = _unpack_vec(packed)
        for a, b in zip(vec, unpacked):
            assert abs(a - b) < 1e-6

    def test_dimension_preserved(self):
        vec = [0.1] * 768
        packed = _pack_vec(vec)
        assert len(packed) == 768 * 4
        unpacked = _unpack_vec(packed)
        assert len(unpacked) == 768


class TestCosineSim:
    def test_identical(self):
        v = [1.0, 0.0, 0.0]
        assert abs(_cosine_sim(v, v) - 1.0) < 1e-6

    def test_orthogonal(self):
        assert abs(_cosine_sim([1.0, 0.0], [0.0, 1.0])) < 1e-6

    def test_zero_vector(self):
        assert _cosine_sim([0.0], [1.0]) == 0.0


class TestVectorStore:
    def test_insert_and_count(self, store):
        store.insert("doc1", [0.1] * 768)
        assert store.count() == 1

    def test_insert_multiple(self, store):
        for i in range(5):
            store.insert(f"doc{i}", [0.1 * (i + 1)] * 768)
        assert store.count() == 5

    def test_search_returns_results(self, store):
        store.insert("doc1", [1.0, 0.0, 0.0] + [0.0] * 765)
        store.insert("doc2", [0.0, 1.0, 0.0] + [0.0] * 765)
        query = [1.0, 0.0, 0.0] + [0.0] * 765
        results = store.search(query, top_k=2)
        assert len(results) == 2
        # doc1 should be most similar
        assert results[0][0] == "doc1"
        assert results[0][1] > results[1][1]

    def test_search_top_k(self, store):
        for i in range(10):
            store.insert(f"doc{i}", [float(i)] * 768)
        results = store.search([9.0] * 768, top_k=3)
        assert len(results) == 3

    def test_search_empty(self, store):
        results = store.search([1.0] * 768)
        assert results == []

    def test_delete(self, store):
        store.insert("doc1", [0.1] * 768)
        assert store.count() == 1
        store.delete("doc1")
        assert store.count() == 0

    def test_upsert(self, store):
        store.insert("doc1", [0.1] * 768)
        store.insert("doc1", [0.9] * 768)  # Same doc_id
        assert store.count() == 1

    def test_is_ann_available_false(self, store):
        # Without sqlite-vec extension, should be False
        assert store.is_ann_available is False

    def test_close_idempotent(self, store):
        store.close()
        assert store._conn is None
        store.close()  # Should not raise
        # Second close keeps the connection field cleared.
        assert store._conn is None

    def test_search_similarity_order(self, store):
        # Insert docs with varying similarity to query
        store.insert("close", [0.9, 0.1] + [0.0] * 766)
        store.insert("far", [0.1, 0.9] + [0.0] * 766)
        query = [1.0, 0.0] + [0.0] * 766
        results = store.search(query)
        assert results[0][0] == "close"

    def test_not_connected(self, tmp_path):
        vs = VectorStore(tmp_path / "test.db")
        # Not connected — should handle gracefully
        assert vs.count() == 0
        assert vs.search([1.0] * 768) == []
