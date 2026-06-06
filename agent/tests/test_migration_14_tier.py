"""Tests for Migration 14 — Mem-2 knowledge.tier column (#1843).

Migration 14 ships the canonical ``knowledge.tier`` column carrying Mem-1's
MemoryTier vocabulary (``preference`` | ``decision`` | ``context``). These
tests pin down the column shape, the auto-backfill rules, the supporting
index, the NOT NULL constraint, and the migration-runner idempotency
guarantee.

Backfill semantics REUSE Migration 2's prefix conventions, so the canonical
prefix → tier mapping is:

    'user:%'      → preference
    'decision:%'  → decision
    anything else → context  (the DEFAULT)

A backfill test seeds the pre-Migration-14 schema (via temporarily slicing
``_MIGRATIONS`` to versions ≤ 13), inserts rows, then re-applies the full
migration list and asserts the tier values are populated correctly.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
import sqlite3

from bridge import db as bridge_db
from bridge.database import Database


@pytest.mark.asyncio
async def test_tier_column_shape_after_migration(migrated_db):
    """PRAGMA table_info reports knowledge.tier with the right defaults."""
    cols = await migrated_db.fetchall("PRAGMA table_info(knowledge)")
    # PRAGMA table_info row shape: (cid, name, type, notnull, dflt_value, pk)
    tier_rows = [r for r in cols if r[1] == "tier"]
    assert len(tier_rows) == 1, "knowledge.tier column missing"

    row = tier_rows[0]
    assert row[2] == "TEXT"
    assert row[3] == 1, "knowledge.tier must be NOT NULL"
    # SQLite stores the default literal including the quotes.
    assert row[4] == "'context'", f"unexpected default: {row[4]!r}"


@pytest.mark.asyncio
async def test_idx_knowledge_tier_exists(migrated_db):
    """Migration 14 creates idx_knowledge_tier supporting tier-filtered reads."""
    rows = await migrated_db.fetchall(
        "SELECT name FROM sqlite_master WHERE type='index' AND name='idx_knowledge_tier'"
    )
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_auto_backfill_by_key_prefix(tmp_db_path):
    """Seeded pre-Mem-2 rows get the correct tier when Migration 14 runs.

    We accomplish "seed at pre-Migration-14 schema" by patching the
    migrations list to stop at version 13 for the first ``migrate()`` call,
    inserting rows, then restoring the full list and re-running
    ``migrate()`` so Migration 14 lands on populated data.
    """
    full_migrations = bridge_db.migrations._MIGRATIONS
    pre_14 = [m for m in full_migrations if m[0] < 14]

    # Phase 1: migrate up to version 13, seed rows.
    with patch.object(bridge_db.migrations, "_MIGRATIONS", pre_14):
        db = Database(tmp_db_path)
        await db.connect()
        await db.migrate()

        v = await db.get_schema_version()
        assert v == 13, f"expected schema_version 13 before Migration 14, got {v}"

        await db.execute(
            "INSERT INTO knowledge (key, value) VALUES (?, ?)",
            ("user:name", "the operator"),
        )
        await db.execute(
            "INSERT INTO knowledge (key, value) VALUES (?, ?)",
            ("decision:lunch", "thai"),
        )
        await db.execute(
            "INSERT INTO knowledge (key, value) VALUES (?, ?)",
            ("random:foo", "bar"),
        )
        await db.commit()
        await db.close()

    # Phase 2: re-open WITH the full migration list — Migration 14 should
    # auto-backfill on the seeded rows.
    db2 = Database(tmp_db_path)
    await db2.connect()
    await db2.migrate()

    v2 = await db2.get_schema_version()
    assert v2 >= 14

    row = await db2.fetchone(
        "SELECT tier FROM knowledge WHERE key = ?", ("user:name",)
    )
    assert row[0] == "preference"

    row = await db2.fetchone(
        "SELECT tier FROM knowledge WHERE key = ?", ("decision:lunch",)
    )
    assert row[0] == "decision"

    row = await db2.fetchone(
        "SELECT tier FROM knowledge WHERE key = ?", ("random:foo",)
    )
    assert row[0] == "context"

    await db2.close()


@pytest.mark.asyncio
async def test_new_insert_defaults_to_context(migrated_db):
    """Post-Migration-14 INSERTs without an explicit tier land in 'context'."""
    await migrated_db.execute(
        "INSERT INTO knowledge (key, value) VALUES (?, ?)",
        ("ephemeral:hello", "world"),
    )
    await migrated_db.commit()

    row = await migrated_db.fetchone(
        "SELECT tier FROM knowledge WHERE key = ?", ("ephemeral:hello",)
    )
    assert row[0] == "context"


@pytest.mark.asyncio
async def test_migration_14_idempotent(migrated_db):
    """Re-running migrate() after Migration 14 is a no-op via schema_version."""
    v1 = await migrated_db.get_schema_version()
    assert v1 >= 14

    # Re-run; should not raise even though ALTER TABLE ADD COLUMN
    # would fail if attempted twice.
    await migrated_db.migrate()

    v2 = await migrated_db.get_schema_version()
    assert v2 == v1


@pytest.mark.asyncio
async def test_tier_not_null_enforced(migrated_db):
    """INSERTing NULL into tier raises IntegrityError."""
    with pytest.raises(sqlite3.IntegrityError):
        await migrated_db.execute(
            "INSERT INTO knowledge (key, value, tier) VALUES (?, ?, ?)",
            ("k", "v", None),
        )
        await migrated_db.commit()
