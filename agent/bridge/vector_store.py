"""Vector store — sqlite-vec integration for ANN search.

Wraps sqlite-vec virtual table for approximate nearest neighbor search.
Falls back to brute-force Python cosine similarity when sqlite-vec
extension is not available.

Virtual table: memory_vec USING vec0(embedding float[768])
"""

from __future__ import annotations

import logging
import math
import sqlite3
import struct
from pathlib import Path

log = logging.getLogger(__name__)

EMBEDDING_DIM = 768


def _pack_vec(vec: list[float]) -> bytes:
    """Pack float list as little-endian float32 blob."""
    return struct.pack(f"<{len(vec)}f", *vec)


def _unpack_vec(blob: bytes) -> list[float]:
    """Unpack float32 blob to float list."""
    count = len(blob) // 4
    return list(struct.unpack(f"<{count}f", blob))


def _cosine_sim(a: list[float], b: list[float]) -> float:
    """Compute cosine similarity."""
    dot = sum(x * y for x, y in zip(a, b))
    mag_a = math.sqrt(sum(x * x for x in a))
    mag_b = math.sqrt(sum(x * x for x in b))
    if mag_a == 0 or mag_b == 0:
        return 0.0
    return dot / (mag_a * mag_b)


class VectorStore:
    """SQLite-based vector store with optional sqlite-vec ANN acceleration."""

    def __init__(self, db_path: str | Path, dimension: int = EMBEDDING_DIM) -> None:
        self.db_path = str(db_path)
        self.dimension = dimension
        self._conn: sqlite3.Connection | None = None
        self._has_vec0 = False

    def connect(self) -> None:
        """Connect and initialize vector store."""
        self._conn = sqlite3.connect(self.db_path)
        self._has_vec0 = self._try_load_vec0()

        if self._has_vec0:
            self._ensure_vec_table()
            log.info("Vector store using sqlite-vec ANN")
        else:
            self._ensure_brute_table()
            log.info("Vector store using brute-force fallback")

    def _try_load_vec0(self) -> bool:
        """Try to load sqlite-vec extension."""
        if not self._conn:
            return False

        # Try common locations
        for lib_path in [
            "data/lib/vec0.dylib",
            "data/lib/vec0.so",
            "/usr/local/lib/vec0.dylib",
        ]:
            try:
                self._conn.enable_load_extension(True)
                self._conn.load_extension(lib_path.replace(".dylib", "").replace(".so", ""))
                # Verify
                self._conn.execute("SELECT vec_version()").fetchone()
                return True
            except (sqlite3.OperationalError, AttributeError):
                continue

        return False

    def _ensure_vec_table(self) -> None:
        """Create sqlite-vec virtual table if not exists."""
        if not self._conn:
            return
        try:
            self._conn.execute(
                f"CREATE VIRTUAL TABLE IF NOT EXISTS memory_vec "
                f"USING vec0(embedding float[{self.dimension}])"
            )
            self._conn.commit()
        except sqlite3.OperationalError as e:
            log.warning("Failed to create vec table: %s", e)
            self._has_vec0 = False
            self._ensure_brute_table()

    def _ensure_brute_table(self) -> None:
        """Create fallback brute-force vector table."""
        if not self._conn:
            return
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS memory_vectors (
                doc_id TEXT PRIMARY KEY,
                embedding BLOB NOT NULL,
                updated_at TEXT DEFAULT (datetime('now'))
            )
        """)
        self._conn.commit()

    def insert(self, doc_id: str, embedding: list[float]) -> None:
        """Insert or update a vector."""
        if not self._conn:
            raise RuntimeError("Not connected")

        blob = _pack_vec(embedding)

        if self._has_vec0:
            try:
                # sqlite-vec uses rowid mapping
                self._conn.execute(
                    "INSERT OR REPLACE INTO memory_vec (rowid, embedding) VALUES (?, ?)",
                    (hash(doc_id) & 0x7FFFFFFFFFFFFFFF, blob),
                )
                # Also store doc_id mapping
                self._conn.execute("""
                    CREATE TABLE IF NOT EXISTS vec_id_map (
                        rowid INTEGER PRIMARY KEY,
                        doc_id TEXT UNIQUE
                    )
                """)
                self._conn.execute(
                    "INSERT OR REPLACE INTO vec_id_map (rowid, doc_id) VALUES (?, ?)",
                    (hash(doc_id) & 0x7FFFFFFFFFFFFFFF, doc_id),
                )
            except sqlite3.OperationalError:
                # Fallback if vec0 insert fails
                self._conn.execute(
                    "INSERT OR REPLACE INTO memory_vectors (doc_id, embedding) VALUES (?, ?)",
                    (doc_id, blob),
                )
        else:
            self._conn.execute(
                "INSERT OR REPLACE INTO memory_vectors (doc_id, embedding) VALUES (?, ?)",
                (doc_id, blob),
            )
        self._conn.commit()

    def upsert_from_text(
        self,
        *,
        doc_id: str,
        text: str,
        metadata: dict[str, object] | None = None,
        embedding_engine: "object | None" = None,
    ) -> str:
        """Upsert a doc by embedding ``text`` inline, then calling :meth:`insert`.

        Sprint Mem-4.5 (issue #1867) — single-call adapter consumed by
        :class:`bridge.advanced_memory.destinations.VectorDestination`.
        The DualWritePipeline calls this on every PREFERENCE / DECISION-tier
        knowledge write when ``memory_tiers_enabled = true``.

        ``metadata`` is accepted for protocol parity with the other
        destinations but is NOT persisted in the underlying SQLite vector
        tables — the schema is ``(doc_id, embedding)`` only. The metadata
        is included at DEBUG-log level so an operator triaging a recall
        miss has the trail without growing the schema.

        ``embedding_engine`` is optional. When None, a lazy default
        :class:`bridge.local_embeddings.LocalEmbeddingEngine` is used —
        ``LocalEmbeddingEngine.embed`` is synchronous and idempotent, so
        repeated upserts of the same text are cache hits via the engine's
        internal cache (when configured).

        Args:
            doc_id: Stable identifier for the upsert (matches the
                knowledge-table key in the dual-write call site).
            text: Text to embed. Empty strings are still embedded for
                cache-key consistency; deletion of an entry is the
                caller's job via :meth:`delete`.
            metadata: Optional opaque metadata; not stored.
            embedding_engine: Optional dependency-injected embedder
                exposing ``embed(text: str) -> list[float]``. When None,
                a default :class:`LocalEmbeddingEngine` is constructed
                (hash-fallback when no model is on disk; still
                deterministic).

        Returns:
            The ``doc_id`` passed in (mirrors the other destinations'
            "return the destination-local id" convention).

        Raises:
            RuntimeError: the underlying connection isn't open, or the
                resolved embedder produced an empty / dimensionless
                vector.
        """
        if self._conn is None:
            raise RuntimeError("VectorStore.upsert_from_text: not connected")
        engine = embedding_engine
        if engine is None:
            # Lazy import to avoid cyclic deps at module load.
            from .local_embeddings import LocalEmbeddingEngine
            engine = LocalEmbeddingEngine()
        embed_fn = getattr(engine, "embed", None)
        if embed_fn is None or not callable(embed_fn):
            raise RuntimeError(
                "VectorStore.upsert_from_text: embedding_engine must "
                "expose a callable .embed(text) method",
            )
        embedding = embed_fn(text)
        if not embedding:
            raise RuntimeError(
                f"VectorStore.upsert_from_text: embedding generation "
                f"returned an empty vector for doc_id={doc_id!r}",
            )
        self.insert(doc_id, list(embedding))
        if metadata:
            log.debug(
                "VectorStore.upsert_from_text: doc_id=%s metadata_keys=%s",
                doc_id, sorted(metadata.keys()),
            )
        return doc_id

    def delete(self, doc_id: str) -> None:
        """Delete a vector."""
        if not self._conn:
            return

        if self._has_vec0:
            rowid = hash(doc_id) & 0x7FFFFFFFFFFFFFFF
            try:
                self._conn.execute("DELETE FROM memory_vec WHERE rowid = ?", (rowid,))
                self._conn.execute("DELETE FROM vec_id_map WHERE doc_id = ?", (doc_id,))
            except sqlite3.OperationalError:
                pass
        else:
            self._conn.execute("DELETE FROM memory_vectors WHERE doc_id = ?", (doc_id,))
        self._conn.commit()

    def search(
        self,
        query_embedding: list[float],
        top_k: int = 20,
    ) -> list[tuple[str, float]]:
        """Search for nearest neighbors.

        Returns list of (doc_id, similarity_score) sorted by similarity descending.
        """
        if not self._conn:
            return []

        if self._has_vec0:
            return self._search_ann(query_embedding, top_k)
        return self._search_brute(query_embedding, top_k)

    def _search_ann(self, query_embedding: list[float], top_k: int) -> list[tuple[str, float]]:
        """ANN search via sqlite-vec."""
        try:
            blob = _pack_vec(query_embedding)
            rows = self._conn.execute(  # type: ignore
                """SELECT rowid, distance FROM memory_vec
                   WHERE embedding MATCH ? ORDER BY distance LIMIT ?""",
                (blob, top_k),
            ).fetchall()

            results: list[tuple[str, float]] = []
            for rowid, distance in rows:
                # Map rowid back to doc_id
                row = self._conn.execute(  # type: ignore
                    "SELECT doc_id FROM vec_id_map WHERE rowid = ?", (rowid,)
                ).fetchone()
                if row:
                    similarity = 1.0 - distance  # cosine distance → similarity
                    results.append((row[0], similarity))

            return results
        except sqlite3.OperationalError as e:
            log.warning("ANN search failed, falling back to brute-force: %s", e)
            return self._search_brute(query_embedding, top_k)

    def _search_brute(self, query_embedding: list[float], top_k: int) -> list[tuple[str, float]]:
        """Brute-force cosine similarity search."""
        if not self._conn:
            return []

        rows = self._conn.execute(
            "SELECT doc_id, embedding FROM memory_vectors"
        ).fetchall()

        scored: list[tuple[str, float]] = []
        for doc_id, blob in rows:
            doc_vec = _unpack_vec(blob)
            sim = _cosine_sim(query_embedding, doc_vec)
            scored.append((doc_id, sim))

        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:top_k]

    def count(self) -> int:
        """Count stored vectors."""
        if not self._conn:
            return 0
        try:
            if self._has_vec0:
                row = self._conn.execute("SELECT COUNT(*) FROM vec_id_map").fetchone()
            else:
                row = self._conn.execute("SELECT COUNT(*) FROM memory_vectors").fetchone()
            return row[0] if row else 0
        except sqlite3.OperationalError:
            return 0

    @property
    def is_ann_available(self) -> bool:
        """Whether sqlite-vec ANN is available."""
        return self._has_vec0

    def close(self) -> None:
        """Close database connection."""
        if self._conn:
            self._conn.close()
            self._conn = None
