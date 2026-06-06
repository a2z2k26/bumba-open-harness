"""Destination protocols for ``DualWritePipeline``.

Sprint Mem-4 — Memory-Tier Architecture epic (#1845, Phase A foundation, final).
Sprint Mem-4.5 (issue #1867) replaced the secondary-destination stubs with
real adapter bodies (see :class:`SecondBrainDestination`,
:class:`VectorDestination` below) and verified — by reading
``bridge/second_brain/contributors/__init__.py`` — that the legacy
``ContributorRegistry`` does NOT observe ``KnowledgeMixin`` events. No
double-write exists, so no dedupe was needed in ``app.py``.

Each destination wraps an existing client behind a uniform async interface so
the pipeline doesn't need destination-specific branching. The pipeline holds a
``dict[str, DestinationProtocol]`` keyed by ``name`` and resolves writes
through it; new destinations register here without further surgery to
``dual_write.py``.

Three destinations ship at Mem-4.5:

* :class:`SQLiteDestination` — primary; writes to the real ``knowledge`` table
  via the bridge's async ``Database`` connection. Schema-faithful: uses the
  ``(key, value, tags, source, category, tier)`` columns established by
  Mem-2's migration 14, with ``ON CONFLICT(key)`` upsert semantics that match
  ``KnowledgeMixin.store_knowledge``.

* :class:`SecondBrainDestination` — secondary; appends a Bumba-authored
  knowledge entry to the operator's Obsidian vault via
  :meth:`bridge.second_brain.wiki_repo.WikiRepo.append_knowledge` (Mem-4.5).
  Lands under ``bumba-contributions/staging/memory-tier/{tier}/`` so the
  operator can mass-promote or mass-reject memory-tier contributions without
  affecting daily-log / reflection / consolidation streams.

* :class:`VectorDestination` — secondary; embeds the entry's value inline via
  :meth:`bridge.vector_store.VectorStore.upsert_from_text` (Mem-4.5) and
  upserts the (doc_id, embedding) row. Uses a lazy
  :class:`bridge.local_embeddings.LocalEmbeddingEngine` by default; an
  embedding engine can be injected via the constructor for tests.

The runtime impact remains bounded:

* At ``memory_tiers_enabled = False`` (the default), the pipeline is not
  called and the destinations are not constructed against live clients.
* At ``memory_tiers_enabled = True``, the legacy second_brain
  ``ContributorRegistry`` + ``ShadowRouter`` paths in ``app.py`` continue to
  run. Their observed sources (daily-log files, reflection store rows,
  consolidation digest dir) do not overlap with ``KnowledgeMixin`` writes,
  so the new pipeline's writes are additive — they land at a separate
  ``bumba-contributions/staging/memory-tier/`` subtree.
"""

from __future__ import annotations

import logging
from typing import Any, Protocol, runtime_checkable

logger = logging.getLogger(__name__)


@runtime_checkable
class DestinationProtocol(Protocol):
    """Common write surface for primary and secondary destinations.

    ``name`` is the string the pipeline uses to look up the destination
    (matching the ``destinations`` tuple on a :class:`TierPolicy`). The
    ``write`` coroutine returns a destination-local identifier — for SQLite
    that's the row key, for secondary stores it may be a vault relpath or
    a vector doc-id. The returned identifier is opaque to the pipeline.
    """

    name: str

    async def write(
        self,
        *,
        key: str,
        value: str,
        tags: str,
        source: str,
        category: str,
        tier: str,
        metadata: dict[str, Any] | None,
    ) -> str:
        """Write the entry to this destination.

        Returns:
            Destination-local identifier (opaque to the pipeline).

        Raises:
            Exception: any failure. The pipeline wraps secondary failures in
                try/except + WARNING log; primary failures propagate.
        """
        ...


class SQLiteDestination:
    """Primary destination — writes to the real ``knowledge`` table.

    Uses the same ``INSERT OR REPLACE`` shape as
    ``KnowledgeMixin.store_knowledge`` so a Mem-4 dual-write is functionally
    equivalent to a Mem-3 direct write at the SQLite layer. Returns the
    primary key (``key``) as the destination-local id.
    """

    name = "sqlite"

    def __init__(self, primary_db: Any) -> None:
        """Bind the destination to the bridge's async ``Database``.

        Args:
            primary_db: Object exposing ``execute(sql, params)`` and
                ``commit()`` coroutines. The bridge's ``Database`` (which
                composes ``ConnectionMixin``) is the canonical caller.
        """
        self._db = primary_db

    async def write(
        self,
        *,
        key: str,
        value: str,
        tags: str,
        source: str,
        category: str,
        tier: str,
        metadata: dict[str, Any] | None,
    ) -> str:
        """Insert-or-replace the entry into the ``knowledge`` table."""
        await self._db.execute(
            """INSERT INTO knowledge (key, value, tags, source, category, tier)
               VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT(key) DO UPDATE SET
                   value = excluded.value,
                   tags = excluded.tags,
                   source = excluded.source,
                   category = excluded.category,
                   tier = excluded.tier,
                   updated_at = datetime('now')""",
            (key, value, tags, source, category, tier),
        )
        await self._db.commit()
        return key


class SecondBrainDestination:
    """Secondary — appends an entry to the operator's Obsidian vault.

    Delegates to :meth:`bridge.second_brain.wiki_repo.WikiRepo.append_knowledge`
    (Mem-4.5), which builds a :class:`bridge.second_brain.wiki_repo.WikiNote`
    at a deterministic ``bumba-contributions/staging/memory-tier/{tier}/...``
    relpath and writes it through the existing atomic-locked ``WikiRepo.write``
    pipeline.

    ``WikiRepo.append_knowledge`` is synchronous — the lock + atomic-rename
    pipeline never blocks on network I/O. We await nothing here; the method
    body is a plain delegation. The DualWritePipeline still treats failures
    as best-effort (try/except + WARNING).
    """

    name = "second_brain"

    def __init__(self, wiki_repo_or_none: Any) -> None:
        """Bind the destination to a ``WikiRepo`` (or ``None`` when disabled)."""
        self._wiki = wiki_repo_or_none

    async def write(
        self,
        *,
        key: str,
        value: str,
        tags: str,
        source: str,
        category: str,
        tier: str,
        metadata: dict[str, Any] | None,
    ) -> str:
        """Append the entry to the vault and return the written relpath.

        Raises:
            RuntimeError: when no :class:`WikiRepo` was wired at construction
                (``memory_tiers_enabled = true`` but ``second_brain`` is
                disabled or vault path missing — the pipeline records this
                as a secondary failure).
            ValueError: ``key`` is invalid (empty or unslug-gable). Surfaced
                upstream by the pipeline as a secondary failure.
        """
        if self._wiki is None:
            raise RuntimeError("second_brain destination not configured")
        # ``tags`` and ``source`` are observed at the SQLite layer; the
        # vault carries them via the inline metadata block. ``source`` is
        # NOT the WikiNote frontmatter ``source`` enum (which is constrained
        # to {ingest, reflection, consolidation, daily_log}) — append_knowledge
        # hard-codes that to ``"ingest"`` for Bumba-authored memory writes.
        md: dict[str, object] = dict(metadata or {})
        if tags:
            md.setdefault("tags", tags)
        if source:
            md.setdefault("origin_source", source)
        return self._wiki.append_knowledge(
            key=key,
            value=value,
            tier=tier,
            category=category,
            metadata=md,
        )


class VectorDestination:
    """Secondary — embeds + upserts the entry into the vector store.

    Delegates to :meth:`bridge.vector_store.VectorStore.upsert_from_text`
    (Mem-4.5), which runs the embedder inline and calls
    :meth:`bridge.vector_store.VectorStore.insert`. Embedding metadata is
    NOT persisted at the vector-store layer (the SQLite schema is
    ``(doc_id, embedding)`` only); semantic context lives at the
    second_brain destination and the SQLite ``knowledge`` row.

    An optional ``embedding_engine`` can be injected at construction time —
    primarily for tests. Production wiring leaves it ``None`` so the
    underlying ``upsert_from_text`` lazy-loads a default
    :class:`bridge.local_embeddings.LocalEmbeddingEngine`.
    """

    name = "vector"

    def __init__(
        self,
        vector_store_or_none: Any,
        embedding_engine: Any = None,
    ) -> None:
        """Bind the destination to a ``VectorStore`` (+ optional embedder).

        Args:
            vector_store_or_none: A connected
                :class:`bridge.vector_store.VectorStore`, or ``None`` when
                the underlying subsystem is disabled.
            embedding_engine: Optional embedder (test injection). When
                ``None``, ``upsert_from_text`` lazy-loads the default
                :class:`bridge.local_embeddings.LocalEmbeddingEngine`.
        """
        self._store = vector_store_or_none
        self._embedding_engine = embedding_engine

    async def write(
        self,
        *,
        key: str,
        value: str,
        tags: str,
        source: str,
        category: str,
        tier: str,
        metadata: dict[str, Any] | None,
    ) -> str:
        """Embed ``value`` and upsert (``doc_id=key``) into the vector store.

        Returns ``doc_id`` (mirrors the primary-destination convention of
        "return the destination-local id").

        Raises:
            RuntimeError: no :class:`VectorStore` wired, or the embedder
                produced an empty vector. Surfaced upstream as a secondary
                failure.
        """
        if self._store is None:
            raise RuntimeError("vector destination not configured")
        # Vector-store schema is (doc_id, embedding) only; metadata is
        # observable here for parity/logging but not stored downstream.
        vec_metadata: dict[str, object] = {
            "tier": tier,
            "category": category,
        }
        if tags:
            vec_metadata["tags"] = tags
        if source:
            vec_metadata["origin_source"] = source
        if metadata:
            for k, v in metadata.items():
                # Don't clobber the tier/category keys we just set.
                vec_metadata.setdefault(k, v)
        return self._store.upsert_from_text(
            doc_id=key,
            text=value,
            metadata=vec_metadata,
            embedding_engine=self._embedding_engine,
        )
