"""Semantic search via OpenAI embeddings.

Uses text-embedding-3-small via urllib (no dependencies).
Vectors stored as packed float32 BLOBs in SQLite.
"""

from __future__ import annotations

import json
import logging
import math
import struct
import urllib.request
import urllib.error

log = logging.getLogger(__name__)

OPENAI_EMBEDDING_URL = "https://api.openai.com/v1/embeddings"
EMBEDDING_MODEL = "text-embedding-3-small"
EMBEDDING_DIM = 1536  # text-embedding-3-small output dimension


class EmbeddingClient:
    """OpenAI embedding client using stdlib only."""

    def __init__(self, api_key: str, timeout: int = 10) -> None:
        self._api_key = api_key
        self._timeout = timeout

    @property
    def is_configured(self) -> bool:
        """Whether the client has a valid API key."""
        return bool(self._api_key)

    def generate(self, text: str) -> bytes | None:
        """Generate an embedding vector for text.

        Returns packed float32 BLOB or None on failure.
        """
        if not self._api_key:
            return None

        # Truncate long text (model limit ~8191 tokens, ~32K chars)
        text = text[:30000]

        payload = {
            "model": EMBEDDING_MODEL,
            "input": text,
        }

        try:
            data = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(
                OPENAI_EMBEDDING_URL,
                data=data,
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                },
                method="POST",
            )

            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                result = json.loads(resp.read().decode("utf-8"))

            vector = result["data"][0]["embedding"]
            return pack_vector(vector)

        except Exception as e:
            log.warning("Embedding generation failed: %s", e)
            return None


class LocalEmbeddingClient:
    """Adapter exposing a `LocalEmbeddingEngine` through the same duck-typed
    interface as `EmbeddingClient` (`is_configured` + `generate(text) -> bytes`).

    Sprint 05.01 (Plan 05) wires this into `Memory(...)` at construction
    time so the semantic-search read path is reachable without an
    `OPENAI_API_KEY`. The wrapped engine handles the ONNX/CoreML/hash
    fallback chain — this class only handles the type bridging
    (`list[float]` → `bytes` via `pack_vector`).
    """

    def __init__(self, engine: "LocalEmbeddingEngine") -> None:  # type: ignore[name-defined]  # noqa: F821
        self._engine = engine

    @property
    def is_configured(self) -> bool:
        """Always True when an engine is wired in.

        Hash fallback is a valid degraded mode — the search path still
        produces deterministic vectors, hybrid activation should not be
        gated on a real model file being present. Per Sprint 05.01 AC.
        """
        return self._engine is not None

    def generate(self, text: str) -> bytes | None:
        """Generate a packed-float32 embedding for `text`.

        Returns None on engine failure to mirror `EmbeddingClient.generate`.
        Memory's `_generate_embedding` already tolerates None via the
        `if blob:` guard at memory.py.
        """
        try:
            vector = self._engine.embed(text)
        except Exception as e:
            log.warning("LocalEmbeddingClient.generate failed: %s", e)
            return None
        return pack_vector(vector)


def pack_vector(vector: list[float]) -> bytes:
    """Pack a float list into a BLOB (little-endian float32)."""
    return struct.pack(f"<{len(vector)}f", *vector)


def unpack_vector(blob: bytes) -> list[float]:
    """Unpack a BLOB into a float list."""
    count = len(blob) // 4
    return list(struct.unpack(f"<{count}f", blob))


def cosine_similarity(blob_a: bytes, blob_b: bytes) -> float:
    """Compute cosine similarity between two packed vectors.

    Returns value between -1.0 and 1.0.
    """
    vec_a = unpack_vector(blob_a)
    vec_b = unpack_vector(blob_b)

    if len(vec_a) != len(vec_b):
        return 0.0

    dot = sum(a * b for a, b in zip(vec_a, vec_b))
    norm_a = math.sqrt(sum(a * a for a in vec_a))
    norm_b = math.sqrt(sum(b * b for b in vec_b))

    if norm_a == 0 or norm_b == 0:
        return 0.0

    return dot / (norm_a * norm_b)
