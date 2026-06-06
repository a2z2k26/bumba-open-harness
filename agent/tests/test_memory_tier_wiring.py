"""Tests for Sprint Mem-3 — capture-side tier classification wired into KnowledgeMixin.

Memory-Tier Architecture epic (#1844). Verifies:
- Flag-off byte-identical behaviour to pre-Mem-3 (classifier not invoked,
  SQLite DEFAULT 'context' lands on the row).
- Flag-on classification routes preferences and decisions to the matching
  MemoryTier, with anything else falling back to CONTEXT.
- Exception in the classifier falls back to CONTEXT + a single WARNING log
  (never raises).
- Importance is computed at write but NOT persisted (no importance_score
  column on knowledge — write-time score is for forensics only in Mem-3).
"""

from __future__ import annotations

import dataclasses
import logging
from unittest.mock import patch

import pytest

from bridge.memory import Memory


def _tier_enabled_memory(migrated_db, sample_config):
    """Build a Memory instance with memory_tiers_enabled=True.

    BridgeConfig is a frozen dataclass — flag flips happen via
    dataclasses.replace, not attribute assignment. We re-construct
    Memory against the same migrated DB so all tests share the schema.
    """
    enabled_config = dataclasses.replace(sample_config, memory_tiers_enabled=True)
    return Memory(migrated_db, enabled_config)


# -- Test 1: Flag-off byte-identical --

@pytest.mark.asyncio
async def test_flag_off_does_not_invoke_classifier(memory):
    """memory_tiers_enabled=False: classify_intent is never called and the
    row's tier column equals the SQLite DEFAULT ('context')."""
    # Default fixture has memory_tiers_enabled=False.
    assert memory._config.memory_tiers_enabled is False

    with patch(
        "bridge.memory.knowledge.classify_intent",
        side_effect=AssertionError("classifier must not run when flag is off"),
    ) as mock_classify:
        await memory.store_knowledge(
            key="user:test",
            value="I prefer dark mode",
            source="agent",
            category="preference",
        )
        assert mock_classify.call_count == 0

    row = await memory._db.fetchone(
        "SELECT tier FROM knowledge WHERE key = ?", ("user:test",),
    )
    assert row is not None
    # Column default is 'context' (Migration 14, Mem-2).
    assert row[0] == "context"


# -- Test 2: Flag-on classifies preference --

@pytest.mark.asyncio
async def test_flag_on_classifies_preference(migrated_db, sample_config):
    """memory_tiers_enabled=True + preference text → tier='preference'."""
    memory = _tier_enabled_memory(migrated_db, sample_config)

    await memory.store_knowledge(
        key="pref-1",
        value="I prefer dark mode",
        source="agent",
        category="preference",
    )

    row = await memory._db.fetchone(
        "SELECT tier FROM knowledge WHERE key = ?", ("pref-1",),
    )
    assert row is not None
    assert row[0] == "preference"


# -- Test 3: Flag-on classifies decision --

@pytest.mark.asyncio
async def test_flag_on_classifies_decision(migrated_db, sample_config):
    """memory_tiers_enabled=True + decision text → tier='decision'."""
    memory = _tier_enabled_memory(migrated_db, sample_config)

    await memory.store_knowledge(
        key="dec-1",
        value="We decided to use Postgres",
        source="agent",
        category="decision",
    )

    row = await memory._db.fetchone(
        "SELECT tier FROM knowledge WHERE key = ?", ("dec-1",),
    )
    assert row is not None
    assert row[0] == "decision"


# -- Test 4: Flag-on falls back to CONTEXT for fact/instruction/unmapped --

@pytest.mark.asyncio
async def test_flag_on_falls_back_to_context(migrated_db, sample_config):
    """memory_tiers_enabled=True + fact text → tier='context' (safe default)."""
    memory = _tier_enabled_memory(migrated_db, sample_config)

    await memory.store_knowledge(
        key="ctx-1",
        value="random fact about X",
        source="agent",
        category="reference",
    )

    row = await memory._db.fetchone(
        "SELECT tier FROM knowledge WHERE key = ?", ("ctx-1",),
    )
    assert row is not None
    assert row[0] == "context"


# -- Test 5: Classifier exception → CONTEXT + WARNING log --

@pytest.mark.asyncio
async def test_classifier_exception_falls_back_to_context(
    migrated_db, sample_config, caplog,
):
    """Any exception from classify_intent → tier='context', single WARNING,
    no exception escapes."""
    memory = _tier_enabled_memory(migrated_db, sample_config)

    with patch(
        "bridge.memory.knowledge.classify_intent",
        side_effect=RuntimeError("synthetic classifier failure"),
    ):
        with caplog.at_level(logging.WARNING, logger="bridge.memory.knowledge"):
            # Must not raise.
            await memory.store_knowledge(
                key="exc-1",
                value="anything",
                source="agent",
                category="reference",
            )

    row = await memory._db.fetchone(
        "SELECT tier FROM knowledge WHERE key = ?", ("exc-1",),
    )
    assert row is not None
    assert row[0] == "context"

    # Exactly one WARNING from our helper.
    warnings = [
        rec for rec in caplog.records
        if rec.levelno == logging.WARNING
        and "memory_tiers: classifier failed" in rec.getMessage()
    ]
    assert len(warnings) == 1
    assert "exc-1" in warnings[0].getMessage()


# -- Test 6: Importance computed but not persisted --

@pytest.mark.asyncio
async def test_importance_logged_at_debug_not_persisted(
    migrated_db, sample_config, caplog,
):
    """Importance is computed and logged at DEBUG but NOT persisted —
    knowledge table has no importance_score column."""
    memory = _tier_enabled_memory(migrated_db, sample_config)

    with caplog.at_level(logging.DEBUG, logger="bridge.memory.knowledge"):
        await memory.store_knowledge(
            key="imp-1",
            value="I prefer dark mode",
            source="agent",
            category="preference",
        )

    # One DEBUG line carrying the importance score.
    debug_lines = [
        rec for rec in caplog.records
        if rec.levelno == logging.DEBUG
        and "memory_tiers:" in rec.getMessage()
        and "importance=" in rec.getMessage()
        and "imp-1" in rec.getMessage()
    ]
    assert len(debug_lines) >= 1

    # knowledge table has no importance_score column.
    cols = await memory._db.fetchall("PRAGMA table_info(knowledge)")
    col_names = {row[1] for row in cols}
    assert "importance_score" not in col_names
    # tier column is present (Migration 14, Mem-2).
    assert "tier" in col_names
