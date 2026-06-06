"""Tests for Sprint 05.01 — pass LocalEmbeddingClient shim to Memory.

Covers the keystone wiring change in `agent/bridge/app.py` that makes
semantic search reachable, plus the shim itself in `bridge.embeddings`.

AC (from `docs/plans/2026-04-24-activation-plans/plan-05-intelligence-memory-activation.md` §05.01):
- LocalEmbeddingClient shim exists at `bridge/embeddings.py` with
  `.is_configured` property + `.generate(text) -> bytes` method.
- Hash-fallback mode still yields `.is_configured == True` (degrades
  gracefully, doesn't disable hybrid activation entirely).
- When Memory is constructed with a configured client, `search_knowledge`
  calls `_semantic_search` first (semantic-first path, FTS5 fallback).
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest


# --------------------------------------------------------------------------- #
# LocalEmbeddingClient shim — surface tests
# --------------------------------------------------------------------------- #


class TestLocalEmbeddingClientShim:
    """The shim wraps LocalEmbeddingEngine and exposes the duck-typed
    interface that Memory expects (`is_configured` + `generate`).
    """

    def test_shim_class_exists(self) -> None:
        from bridge.embeddings import LocalEmbeddingClient

        assert LocalEmbeddingClient is not None

    def test_shim_is_configured_true_in_hash_fallback(self) -> None:
        """Per §05.01 AC: hash-fallback mode still reports configured.

        The plan explicitly calls this out — we don't want the hybrid
        activation to be gated on a real ONNX/CoreML model file being
        present. The shim is "configured" as long as the engine is
        wired in.
        """
        from bridge.embeddings import LocalEmbeddingClient
        from bridge.local_embeddings import LocalEmbeddingEngine

        engine = LocalEmbeddingEngine()
        client = LocalEmbeddingClient(engine)

        assert client.is_configured is True

    def test_shim_generate_returns_bytes(self) -> None:
        """`generate(text) -> bytes` matches the interface
        `EmbeddingClient.generate` from the OpenAI client.

        Memory passes the BLOB straight to SQLite at
        `memory.py:278`, so the type contract must hold.
        """
        from bridge.embeddings import LocalEmbeddingClient
        from bridge.local_embeddings import LocalEmbeddingEngine

        engine = LocalEmbeddingEngine()
        client = LocalEmbeddingClient(engine)

        blob = client.generate("hello world")

        assert isinstance(blob, bytes)
        assert len(blob) > 0

    def test_shim_generate_deterministic_in_hash_fallback(self) -> None:
        """Hash fallback is by design deterministic per text.

        Same input → same blob. This is what `_deterministic_embedding`
        in local_embeddings.py promises and what we rely on for the
        hash-fallback test contract.
        """
        from bridge.embeddings import LocalEmbeddingClient
        from bridge.local_embeddings import LocalEmbeddingEngine

        engine = LocalEmbeddingEngine()
        client = LocalEmbeddingClient(engine)

        blob_a = client.generate("hello world")
        blob_b = client.generate("hello world")

        assert blob_a == blob_b

    def test_shim_generate_returns_none_on_engine_failure(self) -> None:
        """If the wrapped engine raises, the shim swallows and returns None.

        Mirrors `EmbeddingClient.generate` which returns None on failure.
        Memory's `_generate_embedding` already tolerates None at
        `memory.py:276` — `if blob:` guard.
        """
        from bridge.embeddings import LocalEmbeddingClient

        broken_engine = MagicMock()
        broken_engine.embed.side_effect = RuntimeError("boom")

        client = LocalEmbeddingClient(broken_engine)
        blob = client.generate("anything")

        assert blob is None


# --------------------------------------------------------------------------- #
# Memory(..., embedding_client=shim) call-order
# --------------------------------------------------------------------------- #


class TestMemorySemanticFirstWhenConfigured:
    """When Memory is constructed with a configured client, the read path
    must try semantic search FIRST (per §05.01 AC).

    `search_knowledge` at memory.py:300 is gated on
    `self._embedding_client and self._embedding_client.is_configured`.
    Pre-fix it was always None → always FTS5. Post-fix, semantic first.
    """

    @pytest.mark.asyncio
    async def test_search_knowledge_calls_semantic_search_first(
        self, migrated_db, sample_config
    ) -> None:
        from bridge.embeddings import LocalEmbeddingClient
        from bridge.local_embeddings import LocalEmbeddingEngine
        from bridge.memory import Memory

        engine = LocalEmbeddingEngine()
        client = LocalEmbeddingClient(engine)
        memory = Memory(migrated_db, sample_config, embedding_client=client)

        # Pre-seed one knowledge entry so semantic_search has rows
        # to compare against. Use the public API to avoid coupling
        # to the private SQL.
        await memory.store_knowledge("k1", "alpha beta gamma")

        # Patch _semantic_search to record the call and return a hit.
        # We check call-order by asserting it was invoked.
        called = {"semantic": False, "fts": False}
        original_semantic = memory._semantic_search

        async def spy_semantic(query, limit):
            called["semantic"] = True
            return await original_semantic(query, limit)

        memory._semantic_search = spy_semantic  # type: ignore[assignment]

        results = await memory.search_knowledge("alpha")

        assert called["semantic"] is True, (
            "Semantic search must run first when embedding_client "
            "is configured (AC of Sprint 05.01)."
        )
        # Don't assert on results contents — semantic-vs-FTS hit is
        # tested in 05.03's read-path sprint, not here.

    @pytest.mark.asyncio
    async def test_search_knowledge_skips_semantic_when_no_client(
        self, migrated_db, sample_config
    ) -> None:
        """Pre-fix behaviour: with no embedding_client, semantic is skipped.

        This protects the FTS5-only fallback path that is the legacy
        behaviour and ensures Sprint 05.01 doesn't regress it.
        """
        from bridge.memory import Memory

        memory = Memory(migrated_db, sample_config)
        await memory.store_knowledge("k1", "alpha beta gamma")

        # If _semantic_search were called with no client, it would
        # crash on `self._embedding_client.generate(...)`. So the
        # guard at memory.py:300 must short-circuit.
        results = await memory.search_knowledge("alpha")

        # At least returns something via FTS5 / salience fallback.
        assert isinstance(results, list)


# --------------------------------------------------------------------------- #
# Embedding write path — knowledge.embedding column populates
# --------------------------------------------------------------------------- #


class TestKnowledgeEmbeddingColumnPopulates:
    """Sprint 05.01 fixes the gap where `knowledge.embedding` stayed NULL
    forever. Confirm via an integration test that store_knowledge with a
    configured client triggers the async embedding generation path.

    This is a behavioural integration test against the in-memory SQLite
    fixture; the operator's post-merge runtime check (per AC) will
    confirm the same on the live memory.db.
    """

    @pytest.mark.asyncio
    async def test_store_knowledge_with_client_writes_embedding(
        self, migrated_db, sample_config
    ) -> None:
        import asyncio

        from bridge.embeddings import LocalEmbeddingClient
        from bridge.local_embeddings import LocalEmbeddingEngine
        from bridge.memory import Memory

        engine = LocalEmbeddingEngine()
        client = LocalEmbeddingClient(engine)
        memory = Memory(migrated_db, sample_config, embedding_client=client)

        await memory.store_knowledge("alpha", "alpha beta gamma")

        # store_knowledge fires asyncio.create_task(_generate_embedding)
        # — yield to the loop so it runs.
        for _ in range(5):
            await asyncio.sleep(0)

        row = await migrated_db.fetchone(
            "SELECT embedding FROM knowledge WHERE key = ?", ("alpha",)
        )
        assert row is not None
        assert row[0] is not None, (
            "knowledge.embedding column must be populated when an "
            "embedding_client is wired (AC §05.01)."
        )
        assert isinstance(row[0], bytes)


# --------------------------------------------------------------------------- #
# Sprint 05.02 — hybrid_search kwarg + set_hybrid_search setter on Memory
# --------------------------------------------------------------------------- #


class TestMemoryHybridSearchKwarg:
    """Sprint 05.02 adds a `hybrid_search=None` kwarg to Memory.__init__
    plus a `set_hybrid_search` setter so the BridgeApp wiring manifest can
    fire the wire post-`HybridSearch` construction.

    This sprint ships PLUMBING ONLY — read-path consumption is owned by
    Sprint 05.03. So we only verify the parameter accepts and stores.
    """

    @pytest.mark.asyncio
    async def test_memory_init_accepts_hybrid_search_kwarg(
        self, migrated_db, sample_config
    ) -> None:
        from bridge.memory import Memory

        sentinel = object()
        memory = Memory(migrated_db, sample_config, hybrid_search=sentinel)

        assert memory._hybrid_search is sentinel

    @pytest.mark.asyncio
    async def test_memory_init_default_hybrid_search_is_none(
        self, migrated_db, sample_config
    ) -> None:
        """Backward compatibility: pre-05.02 callers (test fixtures, etc.)
        must keep working without passing hybrid_search."""
        from bridge.memory import Memory

        memory = Memory(migrated_db, sample_config)

        assert memory._hybrid_search is None

    @pytest.mark.asyncio
    async def test_memory_set_hybrid_search_assigns(
        self, migrated_db, sample_config
    ) -> None:
        """The setter is what the BridgeApp wiring manifest calls
        post-HybridSearch construction (per Plan 01 manifest convention)."""
        from bridge.memory import Memory

        memory = Memory(migrated_db, sample_config)
        sentinel = object()

        memory.set_hybrid_search(sentinel)

        assert memory._hybrid_search is sentinel

    @pytest.mark.asyncio
    async def test_search_knowledge_unchanged_when_hybrid_search_none(
        self, migrated_db, sample_config
    ) -> None:
        """05.02 ships plumbing only — with hybrid_search=None, the read
        path must be byte-for-byte identical to pre-sprint behaviour."""
        from bridge.memory import Memory

        memory = Memory(migrated_db, sample_config, hybrid_search=None)
        await memory.store_knowledge("k1", "alpha beta gamma")

        results = await memory.search_knowledge("alpha")

        assert isinstance(results, list)
        # Result content invariants are owned by test_memory.py — we only
        # assert the call did not raise on the new kwarg path.


class TestBridgeAppWiresHybridSearchToMemory:
    """The BridgeApp wiring manifest must fire `set_hybrid_search` on the
    Memory instance once HybridSearch construction completes. This is the
    plumbing wire — read-path consumption is 05.03.
    """

    def test_wiring_manifest_includes_memory_set_hybrid_search(self) -> None:
        """Static check: the WIRING_MANIFEST source code references
        `set_hybrid_search` so the boot-time wiring report logs this entry
        as active or pending. Loose-coupling check — we don't pin exact
        wording.
        """
        from pathlib import Path

        app_src = Path(__file__).resolve().parent.parent / "bridge" / "app.py"
        text = app_src.read_text()
        assert "set_hybrid_search" in text, (
            "BridgeApp must declare a wiring-manifest entry that calls "
            "Memory.set_hybrid_search post-HybridSearch construction."
        )

    def test_localembeddingengine_init_order_unchanged(self) -> None:
        """Per §05.02 AC: LocalEmbeddingEngine init order at startup is
        unchanged — the setter pattern is chosen specifically to avoid
        disturbing it. Sprint 05.01 already moved engine construction to
        right before Memory; 05.02 does NOT move it again.
        """
        from pathlib import Path

        init_src = (
            Path(__file__).resolve().parent.parent / "bridge" / "app_init.py"
        )
        lines = init_src.read_text().splitlines()
        memory_line = next(
            (i for i, ln in enumerate(lines)
             if "self._memory = Memory(self._db" in ln),
            None,
        )
        engine_line = next(
            (i for i, ln in enumerate(lines)
             if "self._embedding_engine = LocalEmbeddingEngine" in ln),
            None,
        )
        assert memory_line is not None, "Memory construction not found"
        assert engine_line is not None, "LocalEmbeddingEngine construction not found"
        # Engine must be constructed BEFORE Memory (Sprint 05.01 invariant).
        assert engine_line < memory_line, (
            "LocalEmbeddingEngine must be constructed before Memory — "
            "Sprint 05.01 invariant. Sprint 05.02 must not regress this."
        )
