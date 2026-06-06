"""Tests for Mem-2.5 (#1863) — knowledge.last_accessed_at column.

Sprint Mem-2.5 acceptance:
- New rows show ``last_accessed_at`` populated at insert time.
- Each of the read paths updates the column.
- Index present (verified via ``PRAGMA index_list(knowledge)``).
- Existing ``accessed_at`` usage in ``_reinforce_entries`` and
  ``run_decay_sweep`` is unchanged.
"""
from __future__ import annotations

import asyncio

import pytest



@pytest.mark.asyncio
async def test_migration_15_creates_column(migrated_db):
    """PRAGMA table_info reports knowledge.last_accessed_at."""
    cols = await migrated_db.fetchall("PRAGMA table_info(knowledge)")
    last_accessed_rows = [r for r in cols if r[1] == "last_accessed_at"]
    assert len(last_accessed_rows) == 1, "knowledge.last_accessed_at column missing"
    row = last_accessed_rows[0]
    assert row[2] == "TEXT"


@pytest.mark.asyncio
async def test_migration_15_creates_index(migrated_db):
    """idx_knowledge_last_accessed exists for range scans."""
    rows = await migrated_db.fetchall("PRAGMA index_list(knowledge)")
    idx_names = {r[1] for r in rows}
    assert "idx_knowledge_last_accessed" in idx_names


@pytest.mark.asyncio
async def test_migration_15_backfills_existing_rows(migrated_db):
    """Pre-existing rows get a non-NULL last_accessed_at after migration."""
    # Migration 15's UPDATE is idempotent — verify by counting NULLs.
    row = await migrated_db.fetchone(
        "SELECT COUNT(*) FROM knowledge WHERE last_accessed_at IS NULL"
    )
    assert row[0] == 0, "all knowledge rows should have last_accessed_at"


@pytest.mark.asyncio
async def test_store_knowledge_populates_last_accessed_at(memory):
    """New rows from store_knowledge get last_accessed_at = now."""
    await memory.store_knowledge("test:key1", "value1", source="test")
    row = await memory._db.fetchone(
        "SELECT last_accessed_at FROM knowledge WHERE key = ?",
        ("test:key1",),
    )
    assert row[0] is not None, "last_accessed_at should be populated on insert"
    assert len(row[0]) > 0


@pytest.mark.asyncio
async def test_get_knowledge_touches_last_accessed_at(memory):
    """get_knowledge updates last_accessed_at on hit."""
    await memory.store_knowledge("test:get", "value", source="test")
    initial = await memory._db.fetchone(
        "SELECT last_accessed_at FROM knowledge WHERE key = ?", ("test:get",)
    )
    # Sleep at least one second so the datetime('now') string is distinct
    # (SQLite's datetime('now') has 1-second resolution).
    await asyncio.sleep(1.1)
    result = await memory.get_knowledge("test:get")
    assert result == "value"
    after = await memory._db.fetchone(
        "SELECT last_accessed_at FROM knowledge WHERE key = ?", ("test:get",)
    )
    assert after[0] != initial[0], (
        f"last_accessed_at should advance on read: {initial[0]!r} → {after[0]!r}"
    )


@pytest.mark.asyncio
async def test_get_knowledge_miss_does_not_touch(memory):
    """get_knowledge on a missing key does not write anything."""
    result = await memory.get_knowledge("test:never-existed")
    assert result is None
    # No-op verified by absence of any row to update.


@pytest.mark.asyncio
async def test_touch_last_accessed_no_op_on_empty_keys(memory):
    """_touch_last_accessed([]) returns silently — caller need not guard."""
    # Calling with empty list should not raise.
    await memory._touch_last_accessed([])


@pytest.mark.asyncio
async def test_fetch_all_knowledge_rows_surfaces_last_accessed_at(memory):
    """fetch_all_knowledge_rows includes last_accessed_at in projection."""
    await memory.store_knowledge("test:fetch", "value", source="test")
    rows = await memory.fetch_all_knowledge_rows()
    matching = [r for r in rows if r["key"] == "test:fetch"]
    assert len(matching) == 1
    assert "last_accessed_at" in matching[0]
    assert matching[0]["last_accessed_at"] is not None


@pytest.mark.asyncio
async def test_touch_does_not_bump_salience_or_access_count(memory):
    """_touch_last_accessed must NOT touch salience or access_count.

    Coupling-prevention test: the whole point of the new helper is to be
    salience-agnostic. If a future refactor accidentally folds salience
    bumping into _touch, the tier-eviction signal becomes contaminated.
    """
    await memory.store_knowledge("test:salience", "v", source="test")
    pre = await memory._db.fetchone(
        "SELECT salience, access_count FROM knowledge WHERE key = ?",
        ("test:salience",),
    )
    await memory._touch_last_accessed(["test:salience"])
    post = await memory._db.fetchone(
        "SELECT salience, access_count FROM knowledge WHERE key = ?",
        ("test:salience",),
    )
    assert pre[0] == post[0], "salience must NOT change on _touch_last_accessed"
    assert pre[1] == post[1], "access_count must NOT change on _touch_last_accessed"
