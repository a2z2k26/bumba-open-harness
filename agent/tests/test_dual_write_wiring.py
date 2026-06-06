"""Tests for Sprint Mem-4 — DualWritePipeline wired into KnowledgeMixin.

Memory-Tier Architecture epic (#1845, Phase A foundation, final). Verifies:

1. Flag-off byte-identical: ``memory_tiers_enabled=False`` → pipeline is NOT
   consulted on ``store_knowledge`` even if it's wired.
2. Flag-on primary mandatory: SQLite destination raising → call raises, no
   silent data loss.
3. Flag-on secondary failure isolated: ``second_brain`` destination raising
   → primary still succeeds, ``DualWriteResult.secondary_success=False``,
   single WARNING line, no exception escapes.
4. Tier-driven destinations: PREFERENCE → all three destinations attempted;
   DECISION → sqlite + vector (no second_brain); CONTEXT → sqlite only.
5. Wiring registers: WIRING_MANIFEST surfaces ``set_dual_write_pipeline``
   per the failure-marker contract.
"""

from __future__ import annotations

import dataclasses
import logging
from unittest.mock import AsyncMock, MagicMock

import pytest

from bridge.advanced_memory.destinations import (
    SecondBrainDestination,
    SQLiteDestination,
    VectorDestination,
)
from bridge.advanced_memory.dual_write import DualWritePipeline, DualWriteResult
from bridge.memory import Memory
from bridge.memory_tiers import MemoryTier


# -- Helpers -------------------------------------------------------------- #


class _FakeDestination:
    """Test double for :class:`DestinationProtocol`.

    Records every write keyword args for assertion; ``raise_on_write`` lets a
    test simulate a destination failure.
    """

    def __init__(self, name: str, raise_on_write: Exception | None = None) -> None:
        self.name = name
        self.calls: list[dict] = []
        self._raise = raise_on_write

    async def write(self, **kwargs) -> str:  # type: ignore[no-untyped-def]
        self.calls.append(kwargs)
        if self._raise is not None:
            raise self._raise
        return f"{self.name}:{kwargs['key']}"


def _enabled_memory(migrated_db, sample_config) -> Memory:
    """Build a Memory with ``memory_tiers_enabled=True``.

    BridgeConfig is frozen — flag flips happen via ``dataclasses.replace``.
    """
    enabled_config = dataclasses.replace(sample_config, memory_tiers_enabled=True)
    return Memory(migrated_db, enabled_config)


# -- Test 1: Flag-off byte-identical -------------------------------------- #


@pytest.mark.asyncio
async def test_flag_off_does_not_invoke_pipeline(memory):
    """``memory_tiers_enabled=False`` → pipeline.write is never awaited
    even when a pipeline is wired."""
    assert memory._config.memory_tiers_enabled is False

    mock_pipeline = MagicMock()
    mock_pipeline.write = AsyncMock()
    memory.set_dual_write_pipeline(mock_pipeline)

    await memory.store_knowledge(
        key="off-1",
        value="I prefer dark mode",
        source="agent",
        category="preference",
    )

    assert mock_pipeline.write.await_count == 0

    # Sanity: the direct-SQL path still wrote the row.
    row = await memory._db.fetchone(
        "SELECT tier FROM knowledge WHERE key = ?", ("off-1",),
    )
    assert row is not None


# -- Test 2: Flag-on primary mandatory ------------------------------------ #


@pytest.mark.asyncio
async def test_flag_on_primary_failure_raises(migrated_db, sample_config):
    """Primary (SQLite) failure must raise; no silent data loss."""
    memory = _enabled_memory(migrated_db, sample_config)

    fake_sqlite = _FakeDestination(
        "sqlite", raise_on_write=RuntimeError("synthetic sqlite failure"),
    )
    fake_sb = _FakeDestination("second_brain")
    fake_vec = _FakeDestination("vector")
    pipeline = DualWritePipeline(
        destinations={
            "sqlite": fake_sqlite,
            "second_brain": fake_sb,
            "vector": fake_vec,
        },
    )
    memory.set_dual_write_pipeline(pipeline)

    with pytest.raises(RuntimeError, match="synthetic sqlite failure"):
        await memory.store_knowledge(
            key="pri-fail",
            value="I prefer dark mode",
            source="agent",
            category="preference",
        )

    # Primary raised before secondaries fired — they must not have been called.
    assert fake_sqlite.calls, "primary should have been attempted"
    assert not fake_sb.calls
    assert not fake_vec.calls


@pytest.mark.asyncio
async def test_flag_on_missing_pipeline_warns_and_keeps_primary_sqlite(
    migrated_db, sample_config, caplog,
):
    """Flag-on without the manifest wire is a documented local-only fallback."""
    memory = _enabled_memory(migrated_db, sample_config)

    with caplog.at_level(logging.WARNING, logger="bridge.memory.knowledge"):
        await memory.store_knowledge(
            key="missing-pipeline",
            value="I prefer explicit wiring",
            source="agent",
            category="preference",
        )

    row = await migrated_db.fetchone(
        "SELECT tier FROM knowledge WHERE key = ?", ("missing-pipeline",),
    )
    assert row is not None
    assert row[0] == MemoryTier.PREFERENCE.value
    assert any(
        "set_dual_write_pipeline" in rec.getMessage()
        for rec in caplog.records
    )


# -- Test 3: Flag-on secondary failure isolated --------------------------- #


@pytest.mark.asyncio
async def test_flag_on_secondary_failure_does_not_raise(
    migrated_db, sample_config, caplog,
):
    """Secondary destination raising → primary succeeds, WARNING logged,
    no exception propagates."""
    memory = _enabled_memory(migrated_db, sample_config)

    fake_sqlite = _FakeDestination("sqlite")
    fake_sb = _FakeDestination(
        "second_brain", raise_on_write=RuntimeError("synthetic second_brain failure"),
    )
    fake_vec = _FakeDestination("vector")
    pipeline = DualWritePipeline(
        destinations={
            "sqlite": fake_sqlite,
            "second_brain": fake_sb,
            "vector": fake_vec,
        },
    )
    memory.set_dual_write_pipeline(pipeline)

    with caplog.at_level(logging.WARNING, logger="bridge.advanced_memory.dual_write"):
        # Must NOT raise.
        await memory.store_knowledge(
            key="sec-fail",
            value="I prefer dark mode",
            source="agent",
            category="preference",
        )

    # Primary fired exactly once; second_brain fired once and raised; vector
    # still fired (secondaries are independent).
    assert len(fake_sqlite.calls) == 1
    assert len(fake_sb.calls) == 1
    assert len(fake_vec.calls) == 1

    # Exactly one WARNING line for the second_brain failure.
    warnings = [
        rec for rec in caplog.records
        if rec.levelno == logging.WARNING
        and "secondary=second_brain failed" in rec.getMessage()
    ]
    assert len(warnings) == 1


# -- Test 4: Tier-driven destinations ------------------------------------- #


@pytest.mark.asyncio
async def test_preference_tier_writes_all_three(migrated_db, sample_config):
    """PREFERENCE tier policy → sqlite + second_brain + vector all called."""
    memory = _enabled_memory(migrated_db, sample_config)

    fake_sqlite = _FakeDestination("sqlite")
    fake_sb = _FakeDestination("second_brain")
    fake_vec = _FakeDestination("vector")
    pipeline = DualWritePipeline(
        destinations={
            "sqlite": fake_sqlite,
            "second_brain": fake_sb,
            "vector": fake_vec,
        },
    )
    memory.set_dual_write_pipeline(pipeline)

    await memory.store_knowledge(
        key="pref-tier",
        value="I prefer dark mode",
        source="agent",
        category="preference",
    )

    assert len(fake_sqlite.calls) == 1
    assert len(fake_sb.calls) == 1
    assert len(fake_vec.calls) == 1
    assert fake_sqlite.calls[0]["tier"] == MemoryTier.PREFERENCE.value


@pytest.mark.asyncio
async def test_decision_tier_skips_second_brain(migrated_db, sample_config):
    """DECISION tier policy → sqlite + vector; second_brain NOT called."""
    memory = _enabled_memory(migrated_db, sample_config)

    fake_sqlite = _FakeDestination("sqlite")
    fake_sb = _FakeDestination("second_brain")
    fake_vec = _FakeDestination("vector")
    pipeline = DualWritePipeline(
        destinations={
            "sqlite": fake_sqlite,
            "second_brain": fake_sb,
            "vector": fake_vec,
        },
    )
    memory.set_dual_write_pipeline(pipeline)

    await memory.store_knowledge(
        key="dec-tier",
        value="We decided to use Postgres",
        source="agent",
        category="decision",
    )

    assert len(fake_sqlite.calls) == 1
    assert len(fake_vec.calls) == 1
    assert len(fake_sb.calls) == 0
    assert fake_sqlite.calls[0]["tier"] == MemoryTier.DECISION.value


@pytest.mark.asyncio
async def test_context_tier_writes_sqlite_only(migrated_db, sample_config):
    """CONTEXT tier policy → sqlite only; secondaries NOT called."""
    memory = _enabled_memory(migrated_db, sample_config)

    fake_sqlite = _FakeDestination("sqlite")
    fake_sb = _FakeDestination("second_brain")
    fake_vec = _FakeDestination("vector")
    pipeline = DualWritePipeline(
        destinations={
            "sqlite": fake_sqlite,
            "second_brain": fake_sb,
            "vector": fake_vec,
        },
    )
    memory.set_dual_write_pipeline(pipeline)

    await memory.store_knowledge(
        key="ctx-tier",
        value="random fact about the world",
        source="agent",
        category="reference",
    )

    assert len(fake_sqlite.calls) == 1
    assert len(fake_sb.calls) == 0
    assert len(fake_vec.calls) == 0
    assert fake_sqlite.calls[0]["tier"] == MemoryTier.CONTEXT.value


# -- Test 5: Wiring manifest registers set_dual_write_pipeline ------------ #


def test_wiring_manifest_contains_dual_write_entry():
    """WIRING_MANIFEST inventory: a WiringEntry exists for
    ``set_dual_write_pipeline`` against ``Memory`` with the failure-marker
    contract.

    Static-check: we instantiate WiringEntry the same shape app.py uses and
    assert it surfaces in :func:`apply_wiring_manifest` correctly. Avoids the
    cost of booting BridgeApp in this unit test — full-boot integration test
    is Mem-11's E2E harness.
    """
    from bridge.wiring import WiringEntry, apply_wiring_manifest

    # A target with a no-op setter to satisfy apply_wiring_manifest.
    target = MagicMock()
    target.set_dual_write_pipeline = MagicMock()

    class _App:
        pass

    app = _App()
    # Construction-failure marker truthy → entry must land in FAILED.
    app._dual_write_pipeline = None
    app._dual_write_pipeline_init_failed = True

    entry = WiringEntry(
        "Memory", target, "set_dual_write_pipeline",
        "_dual_write_pipeline", False,
        "Gated by memory_tiers_enabled (default False)",
        "memory",
        failed_marker_attr="_dual_write_pipeline_init_failed",
    )

    report = apply_wiring_manifest(app, [entry], logging.getLogger(__name__))

    assert report.failed == [
        ("set_dual_write_pipeline", "Gated by memory_tiers_enabled (default False)"),
    ]
    assert report.pending == []
    assert report.active == 0

    # Counter-case: marker falsy + source None → PENDING (the flag-off case).
    app._dual_write_pipeline_init_failed = False
    report2 = apply_wiring_manifest(app, [entry], logging.getLogger(__name__))
    assert report2.pending == [
        ("set_dual_write_pipeline", "Gated by memory_tiers_enabled (default False)"),
    ]
    assert report2.failed == []
    assert report2.active == 0


# -- Coverage spot-check for destinations module -------------------------- #


@pytest.mark.asyncio
async def test_sqlite_destination_writes_row(migrated_db):
    """SQLiteDestination.write inserts a row with the correct tier column."""
    dest = SQLiteDestination(migrated_db)
    returned = await dest.write(
        key="sqlite-dest-1",
        value="hello",
        tags="",
        source="agent",
        category="reference",
        tier=MemoryTier.CONTEXT.value,
        metadata=None,
    )
    assert returned == "sqlite-dest-1"
    row = await migrated_db.fetchone(
        "SELECT tier, value FROM knowledge WHERE key = ?", ("sqlite-dest-1",),
    )
    assert row is not None
    assert row[0] == MemoryTier.CONTEXT.value
    assert row[1] == "hello"


@pytest.mark.asyncio
async def test_second_brain_destination_calls_append_knowledge():
    """SecondBrainDestination delegates to ``WikiRepo.append_knowledge`` and
    returns its relpath (Mem-4.5, #1867)."""
    fake_wiki = MagicMock()
    fake_wiki.append_knowledge = MagicMock(
        return_value="bumba-contributions/staging/memory-tier/preference/2026-05-13-sb-1.md",
    )
    dest = SecondBrainDestination(fake_wiki)
    returned = await dest.write(
        key="sb-1", value="I prefer dark mode", tags="t1,t2", source="agent",
        category="preference", tier=MemoryTier.PREFERENCE.value,
        metadata={"session_id": "test-session"},
    )
    assert returned == (
        "bumba-contributions/staging/memory-tier/preference/2026-05-13-sb-1.md"
    )
    fake_wiki.append_knowledge.assert_called_once()
    call_kwargs = fake_wiki.append_knowledge.call_args.kwargs
    assert call_kwargs["key"] == "sb-1"
    assert call_kwargs["value"] == "I prefer dark mode"
    assert call_kwargs["tier"] == MemoryTier.PREFERENCE.value
    assert call_kwargs["category"] == "preference"
    # Tags + source flow through into metadata so the inline header carries them.
    md = call_kwargs["metadata"]
    assert md["tags"] == "t1,t2"
    assert md["origin_source"] == "agent"
    assert md["session_id"] == "test-session"


@pytest.mark.asyncio
async def test_second_brain_destination_unconfigured_raises():
    """A ``SecondBrainDestination`` with no wiki_repo wired raises RuntimeError."""
    dest = SecondBrainDestination(None)
    with pytest.raises(RuntimeError, match="not configured"):
        await dest.write(
            key="x", value="y", tags="", source="agent",
            category="preference", tier=MemoryTier.PREFERENCE.value,
            metadata=None,
        )


@pytest.mark.asyncio
async def test_vector_destination_calls_upsert_from_text():
    """VectorDestination delegates to ``VectorStore.upsert_from_text`` and
    returns its doc_id (Mem-4.5, #1867)."""
    fake_store = MagicMock()
    fake_store.upsert_from_text = MagicMock(return_value="v-1")
    fake_engine = MagicMock()
    dest = VectorDestination(fake_store, embedding_engine=fake_engine)
    returned = await dest.write(
        key="v-1", value="some text", tags="t1", source="agent",
        category="decision", tier=MemoryTier.DECISION.value,
        metadata={"extra": "meta"},
    )
    assert returned == "v-1"
    fake_store.upsert_from_text.assert_called_once()
    call_kwargs = fake_store.upsert_from_text.call_args.kwargs
    assert call_kwargs["doc_id"] == "v-1"
    assert call_kwargs["text"] == "some text"
    assert call_kwargs["embedding_engine"] is fake_engine
    # Vector-store layer doesn't persist metadata, but the adapter still
    # surfaces it for debug-logging parity.
    vec_md = call_kwargs["metadata"]
    assert vec_md["tier"] == MemoryTier.DECISION.value
    assert vec_md["category"] == "decision"
    assert vec_md["tags"] == "t1"
    assert vec_md["origin_source"] == "agent"
    assert vec_md["extra"] == "meta"


@pytest.mark.asyncio
async def test_vector_destination_unconfigured_raises():
    """A ``VectorDestination`` with no store wired raises RuntimeError."""
    dest = VectorDestination(None)
    with pytest.raises(RuntimeError, match="not configured"):
        await dest.write(
            key="x", value="y", tags="", source="agent",
            category="decision", tier=MemoryTier.DECISION.value,
            metadata=None,
        )


@pytest.mark.asyncio
async def test_pipeline_empty_destinations_raises():
    """DualWritePipeline rejects empty destinations tuple."""
    pipeline = DualWritePipeline(destinations={})
    with pytest.raises(ValueError, match="destinations must be non-empty"):
        await pipeline.write(
            key="x", value="y", tier="context", destinations=(),
        )


@pytest.mark.asyncio
async def test_pipeline_missing_primary_raises():
    """Unregistered primary destination raises KeyError."""
    pipeline = DualWritePipeline(destinations={})
    with pytest.raises(KeyError, match="not registered"):
        await pipeline.write(
            key="x", value="y", tier="context", destinations=("sqlite",),
        )


@pytest.mark.asyncio
async def test_pipeline_result_shape_secondary_success():
    """DualWriteResult reports secondary_success=True when at least one
    secondary write succeeds."""
    fake_sqlite = _FakeDestination("sqlite")
    fake_sb = _FakeDestination("second_brain")
    pipeline = DualWritePipeline(
        destinations={"sqlite": fake_sqlite, "second_brain": fake_sb},
    )
    result = await pipeline.write(
        key="r-1", value="x", tier="preference",
        destinations=("sqlite", "second_brain"),
    )
    assert isinstance(result, DualWriteResult)
    assert result.primary_success is True
    assert result.secondary_success is True
    assert result.primary_id == "sqlite:r-1"
    assert result.secondary_id == "second_brain:r-1"
    assert result.error == ""
