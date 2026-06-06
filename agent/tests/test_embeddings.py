"""Tests for bridge.embeddings."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from bridge.embeddings import (
    EmbeddingClient,
    cosine_similarity,
    pack_vector,
    unpack_vector,
)


class TestVectorPacking:
    """Pack/unpack float32 vectors."""

    def test_pack_and_unpack_roundtrip(self):
        vec = [0.1, 0.2, 0.3, 0.4, 0.5]
        blob = pack_vector(vec)
        result = unpack_vector(blob)
        for a, b in zip(vec, result):
            assert abs(a - b) < 1e-6

    def test_pack_empty(self):
        blob = pack_vector([])
        assert blob == b""
        assert unpack_vector(blob) == []

    def test_pack_size(self):
        vec = [1.0] * 1536
        blob = pack_vector(vec)
        assert len(blob) == 1536 * 4  # 4 bytes per float32


class TestCosineSimilarity:
    """Cosine similarity computation."""

    def test_identical_vectors(self):
        vec = [0.1, 0.2, 0.3]
        blob = pack_vector(vec)
        sim = cosine_similarity(blob, blob)
        assert abs(sim - 1.0) < 1e-6

    def test_orthogonal_vectors(self):
        a = pack_vector([1.0, 0.0, 0.0])
        b = pack_vector([0.0, 1.0, 0.0])
        sim = cosine_similarity(a, b)
        assert abs(sim) < 1e-6

    def test_opposite_vectors(self):
        a = pack_vector([1.0, 0.0])
        b = pack_vector([-1.0, 0.0])
        sim = cosine_similarity(a, b)
        assert abs(sim - (-1.0)) < 1e-6

    def test_different_lengths(self):
        a = pack_vector([1.0, 2.0])
        b = pack_vector([1.0, 2.0, 3.0])
        sim = cosine_similarity(a, b)
        assert sim == 0.0

    def test_zero_vector(self):
        a = pack_vector([0.0, 0.0])
        b = pack_vector([1.0, 2.0])
        sim = cosine_similarity(a, b)
        assert sim == 0.0

    def test_similar_vectors(self):
        a = pack_vector([1.0, 2.0, 3.0])
        b = pack_vector([1.1, 2.1, 2.9])
        sim = cosine_similarity(a, b)
        assert sim > 0.99


class TestEmbeddingClient:
    """OpenAI embedding client."""

    def test_not_configured_without_key(self):
        client = EmbeddingClient(api_key="")
        assert client.is_configured is False

    def test_configured_with_key(self):
        client = EmbeddingClient(api_key="sk-test")
        assert client.is_configured is True

    def test_generate_without_key_returns_none(self):
        client = EmbeddingClient(api_key="")
        result = client.generate("test text")
        assert result is None

    @patch("bridge.embeddings.urllib.request.urlopen")
    def test_generate_success(self, mock_urlopen):
        vec = [0.1] * 1536
        response_data = {"data": [{"embedding": vec}]}
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(response_data).encode()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        client = EmbeddingClient(api_key="sk-test")
        result = client.generate("test text")

        assert result is not None
        unpacked = unpack_vector(result)
        assert len(unpacked) == 1536

    @patch("bridge.embeddings.urllib.request.urlopen")
    def test_generate_failure_returns_none(self, mock_urlopen):
        import urllib.error
        mock_urlopen.side_effect = urllib.error.URLError("timeout")

        client = EmbeddingClient(api_key="sk-test")
        result = client.generate("test text")
        assert result is None
