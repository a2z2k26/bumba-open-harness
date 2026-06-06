"""Local embedding engine — generates vector embeddings without external APIs.

Supports ONNX (CPU) and CoreML (Apple Silicon) backends.
Falls back to a lightweight hash-based stub when no model is installed,
enabling the hybrid search pipeline to function in degraded mode.

Model: snowflake-arctic-embed-m-v2.0 (768-dim)
"""

from __future__ import annotations

import hashlib
import logging
import math
import sqlite3
import struct
import threading
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

EMBEDDING_DIM = 768
MAX_TOKENS = 512
DEFAULT_MODEL_DIR = "data/models/arctic-embed"
BATCH_SIZE = 32

# EmbeddingGemma (#2560) requires task-specific prompt prefixes — skipping them
# measurably degrades retrieval. The model is asymmetric: queries and stored
# documents get different prefixes. We tag the query side (recall path) and the
# document side (store path) explicitly via the `is_query` arg on embed().
# Detection is by model dir name so arctic-embed and other backends are
# unaffected (they ignore prefixes).
GEMMA_QUERY_PREFIX = "task: search result | query: "
GEMMA_DOCUMENT_PREFIX = "title: none | text: "


def _hash_text(text: str) -> str:
    """SHA-256 hash of text for cache key."""
    return hashlib.sha256(text.encode()).hexdigest()


def _deterministic_embedding(text: str, dim: int = EMBEDDING_DIM) -> list[float]:
    """Generate a deterministic pseudo-embedding from text hash.

    NOT semantically meaningful — only used as fallback when no model installed.
    Produces reproducible, normalized vectors for testing and degraded operation.
    """
    h = hashlib.sha256(text.encode()).digest()
    expanded = b""
    for i in range(dim // 16 + 1):
        expanded += hashlib.sha256(h + i.to_bytes(4, "big")).digest()

    vec = []
    for i in range(dim):
        byte_val = expanded[i]
        vec.append((byte_val / 127.5) - 1.0)

    magnitude = math.sqrt(sum(v * v for v in vec))
    if magnitude > 0:
        vec = [v / magnitude for v in vec]

    return vec


def _pack_embedding(embedding: list[float]) -> bytes:
    """Pack embedding as binary blob for SQLite storage."""
    return struct.pack(f"{len(embedding)}f", *embedding)


def _unpack_embedding(blob: bytes) -> list[float]:
    """Unpack embedding from binary blob."""
    count = len(blob) // 4
    return list(struct.unpack(f"{count}f", blob))


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """Compute cosine similarity between two vectors."""
    dot = sum(x * y for x, y in zip(a, b))
    mag_a = math.sqrt(sum(x * x for x in a))
    mag_b = math.sqrt(sum(x * x for x in b))
    if mag_a == 0 or mag_b == 0:
        return 0.0
    return dot / (mag_a * mag_b)


class LocalEmbeddingEngine:
    """Generate text embeddings using local model or hash fallback."""

    def __init__(
        self,
        model_dir: str | Path | None = None,
        cache_db: str | Path | None = None,
        batch_size: int = BATCH_SIZE,
    ) -> None:
        self.model_dir = Path(model_dir) if model_dir else Path(DEFAULT_MODEL_DIR)
        self.batch_size = batch_size
        self._model: Any = None
        self._tokenizer: Any = None
        self._backend: str = "none"
        # EmbeddingGemma (#2560) needs task prefixes + emits a pre-pooled
        # sentence vector; set True when the loaded model is a gemma export so
        # embed()/_onnx_embed branch correctly. Detected by the model dir's own
        # name (final path component), not the full path — a parent dir that
        # happens to contain "gemma" must not trigger gemma mode.
        self._is_gemma: bool = "gemma" in self.model_dir.name.lower()
        # Sprint 05.04 — `_backend_name` alias kept in lockstep with `_backend`
        # for the verification probe on the Mac mini runtime. Public access via
        # the `backend` / `backend_name` properties (both lazy-load).
        self._backend_name: str = "none"
        self._cache_conn: sqlite3.Connection | None = None
        # RLock serializes all cache reads and writes across threads.
        # Required because _cache_conn is opened with check_same_thread=False
        # so it may be shared across threads; the lock prevents concurrent
        # cursor use which SQLite does not support safely.
        self._cache_lock: threading.RLock = threading.RLock()
        self._model_version = "stub-1.0"

        if cache_db:
            self._init_cache(Path(cache_db))

    def _init_cache(self, db_path: Path) -> None:
        """Initialize embedding cache in SQLite."""
        db_path.parent.mkdir(parents=True, exist_ok=True)
        # check_same_thread=False allows the connection to be used from
        # worker and async threads; access is serialized via _cache_lock.
        self._cache_conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._cache_conn.execute("""
            CREATE TABLE IF NOT EXISTS embedding_cache (
                text_hash TEXT PRIMARY KEY,
                embedding BLOB NOT NULL,
                model_version TEXT NOT NULL,
                created_at TEXT DEFAULT (datetime('now'))
            )
        """)
        self._cache_conn.commit()

    def _load_model(self) -> bool:
        """Attempt to load ONNX or CoreML model. Returns True if loaded."""
        if self._model is not None:
            return True

        # Resolve the ONNX graph: prefer the canonical `model.onnx`, else fall
        # back to a `model*.onnx` glob (e.g. `model_quantized.onnx`). The graph
        # must NOT be renamed away from its export name — the .onnx_data weights
        # sidecar is referenced by name inside the graph protobuf, so renaming
        # the graph+data pair breaks onnxruntime's external-data resolution
        # (#2560). The install script therefore keeps export names; this glob
        # finds them.
        model_path = self.model_dir / "model.onnx"
        if not model_path.exists() and self.model_dir.is_dir():
            candidates = sorted(
                p for p in self.model_dir.glob("model*.onnx")
                if not p.name.endswith(".onnx_data")
            )
            if candidates:
                model_path = candidates[0]
        coreml_path = self.model_dir / "model.mlpackage"

        if coreml_path.exists():
            try:
                import coremltools as ct
                self._model = ct.models.MLModel(str(coreml_path))
                self._backend = "coreml"
                self._backend_name = "coreml"
                self._model_version = "arctic-embed-coreml"
                log.info("Loaded CoreML embedding model")
                return True
            except Exception as e:
                log.warning("CoreML load failed: %s", e)

        if model_path.exists():
            try:
                import onnxruntime as ort
                self._model = ort.InferenceSession(str(model_path))
                self._backend = "onnx"
                self._backend_name = "onnx"
                self._model_version = "arctic-embed-onnx"
                log.info("Loaded ONNX embedding model")
                return True
            except Exception as e:
                log.warning("ONNX load failed: %s", e)

        log.info("No embedding model found, using hash fallback")
        self._backend = "hash"
        self._backend_name = "hash"
        return False

    def _check_cache(self, text_hash: str) -> list[float] | None:
        """Check cache for existing embedding."""
        if not self._cache_conn:
            return None
        try:
            with self._cache_lock:
                row = self._cache_conn.execute(
                    "SELECT embedding, model_version FROM embedding_cache WHERE text_hash = ?",
                    (text_hash,),
                ).fetchone()
            if row and row[1] == self._model_version:
                return _unpack_embedding(row[0])
        except sqlite3.Error:
            pass
        return None

    def _store_cache(self, text_hash: str, embedding: list[float]) -> None:
        """Store embedding in cache."""
        if not self._cache_conn:
            return
        try:
            with self._cache_lock:
                self._cache_conn.execute(
                    """INSERT OR REPLACE INTO embedding_cache
                       (text_hash, embedding, model_version) VALUES (?, ?, ?)""",
                    (text_hash, _pack_embedding(embedding), self._model_version),
                )
                self._cache_conn.commit()
        except sqlite3.Error as e:
            log.warning("Cache write failed: %s", e)

    def embed(self, text: str, is_query: bool = False) -> list[float]:
        """Generate embedding for a single text. Uses cache if available.

        ``is_query`` selects the EmbeddingGemma task prefix (query vs document)
        — it is a no-op for non-gemma backends, which ignore the prefix. The
        prefixed text is what gets hashed for the cache key, so the query and
        document forms of the same text are cached as distinct vectors (they
        are distinct vectors for an asymmetric model).
        """
        self._load_model()

        prefixed = text
        if self._is_gemma:
            prefixed = (GEMMA_QUERY_PREFIX if is_query else GEMMA_DOCUMENT_PREFIX) + text

        text_hash = _hash_text(prefixed)
        cached = self._check_cache(text_hash)
        if cached is not None:
            return cached

        if self._backend == "hash" or self._model is None:
            embedding = _deterministic_embedding(prefixed)
        else:
            embedding = self._model_embed(prefixed)

        self._store_cache(text_hash, embedding)
        return embedding

    def _model_embed(self, text: str) -> list[float]:
        """Generate embedding using loaded model."""
        if self._backend == "onnx":
            return self._onnx_embed(text)
        elif self._backend == "coreml":
            return self._coreml_embed(text)
        return _deterministic_embedding(text)

    def _onnx_embed(self, text: str) -> list[float]:
        """Run ONNX inference."""
        try:
            from tokenizers import Tokenizer
            if self._tokenizer is None:
                tok_path = self.model_dir / "tokenizer.json"
                self._tokenizer = Tokenizer.from_file(str(tok_path))

            encoded = self._tokenizer.encode(text)
            input_ids = encoded.ids[:MAX_TOKENS]

            import numpy as np
            inputs = {
                "input_ids": np.array([input_ids], dtype=np.int64),
                "attention_mask": np.array([[1] * len(input_ids)], dtype=np.int64),
            }
            outputs = self._model.run(None, inputs)
            # EmbeddingGemma's ONNX export performs mean-pooling in-graph and
            # emits a pre-pooled sentence embedding as its LAST output
            # (shape (batch, 768)). arctic-embed and BERT-style exports emit
            # token-level hidden states as outputs[0] (shape (batch, seq, dim)),
            # from which we take the first token. Branch on the model family.
            if self._is_gemma:
                # sentence_embedding is the final output; index batch row 0.
                embedding = outputs[-1][0].tolist()
            else:
                embedding = outputs[0][0].tolist()

            magnitude = math.sqrt(sum(v * v for v in embedding))
            if magnitude > 0:
                embedding = [v / magnitude for v in embedding]
            return embedding
        except Exception as e:
            log.error("ONNX embedding failed: %s", e)
            return _deterministic_embedding(text)

    def _coreml_embed(self, text: str) -> list[float]:
        """Run CoreML inference."""
        try:
            prediction = self._model.predict({"text": text})
            embedding = list(prediction["embedding"])
            magnitude = math.sqrt(sum(v * v for v in embedding))
            if magnitude > 0:
                embedding = [v / magnitude for v in embedding]
            return embedding
        except Exception as e:
            log.error("CoreML embedding failed: %s", e)
            return _deterministic_embedding(text)

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Generate embeddings for a batch of texts."""
        results: list[list[float]] = []
        for i in range(0, len(texts), self.batch_size):
            batch = texts[i:i + self.batch_size]
            for text in batch:
                results.append(self.embed(text))
        return results

    @property
    def backend(self) -> str:
        """Current backend: 'onnx', 'coreml', 'hash', or 'none'."""
        if self._backend == "none":
            self._load_model()
        return self._backend

    @property
    def backend_name(self) -> str:
        """Alias of ``backend`` exposed under the spec name ``_backend_name``.

        Sprint 05.04: the Mac-mini probe command in the runbook reads
        ``e._backend_name`` directly. This property keeps the alias attribute
        consistent with the lazy-load semantics of the public ``backend``
        property, so callers can use either name interchangeably.
        """
        if self._backend_name == "none":
            self._load_model()
        return self._backend_name

    @property
    def dimension(self) -> int:
        """Embedding dimension."""
        return EMBEDDING_DIM

    def invalidate_cache(self) -> int:
        """Clear all cached embeddings. Returns count removed."""
        if not self._cache_conn:
            return 0
        try:
            with self._cache_lock:
                cursor = self._cache_conn.execute("DELETE FROM embedding_cache")
                self._cache_conn.commit()
                return cursor.rowcount
        except sqlite3.Error:
            return 0

    def close(self) -> None:
        """Close cache connection."""
        if self._cache_conn:
            self._cache_conn.close()
            self._cache_conn = None
