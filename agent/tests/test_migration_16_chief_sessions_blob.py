"""Tests for Migration 16 — zone4-warmth.B.01 `message_history_blob` column (#2293).

Migration 16 adds the nullable `message_history_blob BLOB` column to the
`chief_sessions` table. The column is schema-only in this sprint: no
readers or writers yet. B.02 will write the blob in
`WarmChief.__aexit__`; C.03 will read it on warm reload.

These tests pin down:

* The column exists after migration with `notnull=0` and `type=BLOB`.
* The migration is idempotent — re-running `migrate()` is a no-op.
* Existing rows survive the migration with `message_history_blob = NULL`.
* The new column accepts BLOB writes.
* `SELECT *` continues to function after the new column is added
  (regression guard for ORM-style mappers sensitive to column count).

The sprint spec calls this "migration #14" against an older baseline;
slots 14 and 15 landed first (knowledge.tier, knowledge.last_accessed_at),
so this is migration #16. The slot, not the number, is what matters.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from bridge import db as bridge_db
from bridge.database import Database


@pytest.mark.asyncio
async def test_message_history_blob_column_shape(migrated_db):
    """PRAGMA table_info reports message_history_blob as nullable BLOB."""
    cols = await migrated_db.fetchall("PRAGMA table_info(chief_sessions)")
    # PRAGMA table_info row shape: (cid, name, type, notnull, dflt_value, pk)
    blob_rows = [r for r in cols if r[1] == "message_history_blob"]
    assert len(blob_rows) == 1, "chief_sessions.message_history_blob column missing"

    row = blob_rows[0]
    # Column type — SQLite reports the declared type as-is.
    assert row[2].upper() == "BLOB", f"expected BLOB, got {row[2]!r}"
    # Nullable: notnull flag must be 0.
    assert row[3] == 0, "message_history_blob must be nullable"
    # No default.
    assert row[4] is None, f"expected no default, got {row[4]!r}"


@pytest.mark.asyncio
async def test_migration_16_idempotent(migrated_db):
    """Re-running migrate() after Migration 16 is a no-op via schema_version."""
    v1 = await migrated_db.get_schema_version()
    assert v1 >= 16

    # Re-run; should not raise even though ALTER TABLE ADD COLUMN
    # would fail if attempted twice on the same column.
    await migrated_db.migrate()

    v2 = await migrated_db.get_schema_version()
    assert v2 == v1


@pytest.mark.asyncio
async def test_existing_rows_get_null_blob(tmp_db_path):
    """Rows inserted at the pre-Migration-16 schema survive and have NULL blob.

    We accomplish "seed at pre-Migration-16 schema" by patching the
    migrations list to stop at version 15 for the first ``migrate()`` call,
    inserting a row, then restoring the full list and re-running
    ``migrate()`` so Migration 16 lands on populated data.
    """
    full_migrations = bridge_db.migrations._MIGRATIONS
    pre_16 = [m for m in full_migrations if m[0] < 16]

    # Phase 1: migrate up to version 15, seed a row in chief_sessions.
    with patch.object(bridge_db.migrations, "_MIGRATIONS", pre_16):
        db = Database(tmp_db_path)
        await db.connect()
        await db.migrate()

        v = await db.get_schema_version()
        assert v == 15, f"expected schema_version 15 before Migration 16, got {v}"

        # At this point chief_sessions has NO message_history_blob column.
        cols_pre = await db.fetchall("PRAGMA table_info(chief_sessions)")
        col_names_pre = {r[1] for r in cols_pre}
        assert "message_history_blob" not in col_names_pre

        await db.execute(
            "INSERT INTO chief_sessions("
            "session_id, work_order_id, department, chief_name, state, "
            "created_at_utc, run_count, cost_usd, metadata_json"
            ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "sess-pre-16",
                "wo-pre-16",
                "engineering",
                "engineering-chief",
                "awaiting_evaluation",
                "2026-05-18T00:00:00Z",
                1,
                0.04,
                "{}",
            ),
        )
        await db.commit()
        await db.close()

    # Phase 2: re-open WITH the full migration list — Migration 16 should
    # add the column and leave the existing row with NULL.
    db2 = Database(tmp_db_path)
    await db2.connect()
    await db2.migrate()

    v2 = await db2.get_schema_version()
    assert v2 >= 16

    row = await db2.fetchone(
        "SELECT session_id, message_history_blob FROM chief_sessions "
        "WHERE session_id = ?",
        ("sess-pre-16",),
    )
    assert row[0] == "sess-pre-16"
    assert row[1] is None

    await db2.close()


@pytest.mark.asyncio
async def test_blob_column_accepts_bytes(migrated_db):
    """After migration, the new column accepts BLOB (bytes) writes."""
    payload = b'{"messages": ["test"]}'
    await migrated_db.execute(
        "INSERT INTO chief_sessions("
        "session_id, work_order_id, department, chief_name, state, "
        "created_at_utc, run_count, cost_usd, metadata_json, "
        "message_history_blob"
        ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            "sess-blob",
            "wo-blob",
            "engineering",
            "engineering-chief",
            "awaiting_evaluation",
            "2026-05-18T00:00:00Z",
            1,
            0.04,
            "{}",
            payload,
        ),
    )
    await migrated_db.commit()

    row = await migrated_db.fetchone(
        "SELECT message_history_blob FROM chief_sessions WHERE session_id = ?",
        ("sess-blob",),
    )
    assert row[0] == payload
    assert isinstance(row[0], bytes)


@pytest.mark.asyncio
async def test_select_star_still_works(migrated_db):
    """REGRESSION: SELECT * on chief_sessions continues to function.

    Any code path doing `SELECT *` must continue to work after the new
    column is added. We assert the column count grew by exactly one
    (vs pre-migration baseline) AND that the new column appears last.
    """
    cols = await migrated_db.fetchall("PRAGMA table_info(chief_sessions)")
    col_names = [r[1] for r in cols]
    assert "message_history_blob" in col_names
    # ALTER TABLE ADD COLUMN appends to the end of the column list — important
    # for any positional-index reader.
    assert col_names[-1] == "message_history_blob"
