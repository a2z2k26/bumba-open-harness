"""Tests for bridge.database (S38)."""

from __future__ import annotations

import pytest

from bridge.database import Database


class TestConnection:
    """S35: Connection and pragmas."""

    @pytest.mark.asyncio
    async def test_connect_and_pragmas(self, tmp_db_path):
        db = Database(tmp_db_path)
        await db.connect()

        row = await db.fetchone("PRAGMA journal_mode;")
        assert row[0] == "wal"

        row = await db.fetchone("PRAGMA busy_timeout;")
        assert row[0] == 5000

        row = await db.fetchone("PRAGMA synchronous;")
        assert row[0] == 1  # NORMAL = 1

        row = await db.fetchone("PRAGMA foreign_keys;")
        assert row[0] == 1

        await db.close()

    @pytest.mark.asyncio
    async def test_close_and_checkpoint(self, tmp_db_path):
        db = Database(tmp_db_path)
        await db.connect()
        await db.migrate()
        await db.execute(
            "INSERT INTO knowledge (key, value) VALUES (?, ?)",
            ("test", "value"),
        )
        await db.commit()
        await db.close()
        assert db._conn is None

        # Reopen and verify data persisted
        db2 = Database(tmp_db_path)
        await db2.connect()
        row = await db2.fetchone("SELECT value FROM knowledge WHERE key = ?", ("test",))
        assert row[0] == "value"
        await db2.close()


class TestMigration:
    """S36: Schema migration."""

    @pytest.mark.asyncio
    async def test_migrate_creates_tables(self, migrated_db):
        tables = await migrated_db.fetchall(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name;"
        )
        table_names = [r[0] for r in tables]
        for expected in ("knowledge", "conversations", "sessions", "message_queue", "audit_log"):
            assert expected in table_names

    @pytest.mark.asyncio
    async def test_idempotent_migrate(self, migrated_db):
        """Running migrate twice should not error."""
        await migrated_db.migrate()
        tables = await migrated_db.fetchall(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name;"
        )
        table_names = [r[0] for r in tables]
        assert "knowledge" in table_names


class TestFTSAndTriggers:
    """S37: FTS5 and audit triggers."""

    @pytest.mark.asyncio
    async def test_fts_sync(self, migrated_db):
        """Insert into knowledge → FTS should index it."""
        await migrated_db.execute(
            "INSERT INTO knowledge (key, value, tags) VALUES (?, ?, ?)",
            ("user.name", "the operator", "personal,identity"),
        )
        await migrated_db.commit()

        rows = await migrated_db.fetchall(
            "SELECT key FROM knowledge_fts WHERE knowledge_fts MATCH ?",
            ("the operator",),
        )
        assert len(rows) == 1
        assert rows[0][0] == "user.name"

    @pytest.mark.asyncio
    async def test_fts_update_sync(self, migrated_db):
        """Update knowledge → FTS should reflect new value."""
        await migrated_db.execute(
            "INSERT INTO knowledge (key, value) VALUES (?, ?)",
            ("test.key", "old_value"),
        )
        await migrated_db.commit()

        await migrated_db.execute(
            "UPDATE knowledge SET value = ?, updated_at = datetime('now') WHERE key = ?",
            ("new_value", "test.key"),
        )
        await migrated_db.commit()

        rows = await migrated_db.fetchall(
            "SELECT key FROM knowledge_fts WHERE knowledge_fts MATCH ?",
            ("new_value",),
        )
        assert len(rows) == 1

        rows = await migrated_db.fetchall(
            "SELECT key FROM knowledge_fts WHERE knowledge_fts MATCH ?",
            ("old_value",),
        )
        assert len(rows) == 0

    @pytest.mark.asyncio
    async def test_audit_no_delete(self, migrated_db):
        await migrated_db.execute(
            "INSERT INTO audit_log (event_type, outcome) VALUES (?, ?)",
            ("test_event", "success"),
        )
        await migrated_db.commit()

        with pytest.raises(Exception, match="cannot be deleted"):
            await migrated_db.execute("DELETE FROM audit_log WHERE event_type = 'test_event'")

    @pytest.mark.asyncio
    async def test_audit_no_update(self, migrated_db):
        await migrated_db.execute(
            "INSERT INTO audit_log (event_type, outcome) VALUES (?, ?)",
            ("test_event", "success"),
        )
        await migrated_db.commit()

        with pytest.raises(Exception, match="cannot be modified"):
            await migrated_db.execute(
                "UPDATE audit_log SET outcome = 'failure' WHERE event_type = 'test_event'"
            )


class TestVersionedMigrations:
    """Versioned schema migrations."""

    @pytest.mark.asyncio
    async def test_migrations_applied_on_migrate(self, migrated_db):
        """migrate() should apply all versioned migrations."""
        version = await migrated_db.get_schema_version()
        assert version >= 1

    @pytest.mark.asyncio
    async def test_migrations_idempotent(self, migrated_db):
        """Running migrate twice should not error or re-apply."""
        v1 = await migrated_db.get_schema_version()
        await migrated_db.migrate()
        v2 = await migrated_db.get_schema_version()
        assert v1 == v2

    @pytest.mark.asyncio
    async def test_knowledge_has_category_column(self, migrated_db):
        """Migration 1 adds category and archived columns."""
        cols = await migrated_db.fetchall("PRAGMA table_info(knowledge)")
        col_names = [r[1] for r in cols]
        assert "category" in col_names
        assert "archived" in col_names

    @pytest.mark.asyncio
    async def test_async_tasks_table_exists(self, migrated_db):
        """Migration 3 creates async_tasks table."""
        tables = await migrated_db.fetchall(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='async_tasks'"
        )
        assert len(tables) == 1

    @pytest.mark.asyncio
    async def test_embedding_columns_exist(self, migrated_db):
        """Migration 4 adds embedding columns."""
        cols = await migrated_db.fetchall("PRAGMA table_info(knowledge)")
        col_names = [r[1] for r in cols]
        assert "embedding" in col_names

        cols = await migrated_db.fetchall("PRAGMA table_info(conversations)")
        col_names = [r[1] for r in cols]
        assert "embedding" in col_names

    @pytest.mark.asyncio
    async def test_fts5_includes_category(self, migrated_db):
        """Migration 5 rebuilds FTS5 to include category column."""
        # Insert with category
        await migrated_db.execute(
            "INSERT INTO knowledge (key, value, tags, category) VALUES (?, ?, ?, ?)",
            ("pref:dark", "dark mode", "ui", "preference"),
        )
        await migrated_db.commit()

        # Search should find by category content
        rows = await migrated_db.fetchall(
            "SELECT key FROM knowledge_fts WHERE knowledge_fts MATCH ?",
            ("preference",),
        )
        assert len(rows) == 1
        assert rows[0][0] == "pref:dark"


class TestMigration14Idempotency:
    """Migration 14 (Mem-2, #1843): knowledge.tier column idempotency.

    Full column-shape / backfill / NOT NULL coverage lives in
    ``tests/test_migration_14_tier.py``. This class only asserts the
    cross-cutting invariant: running ``migrate()`` a second time after
    Migration 14 has already landed is a no-op via the schema_version
    table — the second pass must not raise.
    """

    @pytest.mark.asyncio
    async def test_migration_14_is_idempotent(self, migrated_db):
        """Re-running migrate() does not re-apply Migration 14."""
        # First migrate() already ran in the fixture; capture state.
        v_before = await migrated_db.get_schema_version()
        assert v_before >= 14

        # Second run must be a no-op — no IntegrityError, no
        # "duplicate column" error from re-applying ALTER TABLE.
        await migrated_db.migrate()

        v_after = await migrated_db.get_schema_version()
        assert v_after == v_before

        # Confirm exactly one schema_version row for Migration 14.
        rows = await migrated_db.fetchall(
            "SELECT COUNT(*) FROM schema_version WHERE version = ?",
            (14,),
        )
        assert rows[0][0] == 1


class TestUtilities:
    """S37: Backup, health check, execute+fetch."""

    @pytest.mark.asyncio
    async def test_execute_and_fetch(self, migrated_db):
        await migrated_db.execute(
            "INSERT INTO knowledge (key, value) VALUES (?, ?)",
            ("k1", "v1"),
        )
        await migrated_db.commit()

        row = await migrated_db.fetchone("SELECT value FROM knowledge WHERE key = ?", ("k1",))
        assert row[0] == "v1"

        rows = await migrated_db.fetchall("SELECT key FROM knowledge;")
        assert len(rows) == 1

    @pytest.mark.asyncio
    async def test_health_check(self, migrated_db):
        health = await migrated_db.health_check()
        assert health["integrity_ok"] is True
        assert health["db_size_bytes"] > 0
        assert "table_counts" in health
        assert health["table_counts"]["knowledge"] == 0

    @pytest.mark.asyncio
    async def test_backup(self, migrated_db, tmp_path):
        await migrated_db.execute(
            "INSERT INTO knowledge (key, value) VALUES (?, ?)",
            ("backup_test", "data"),
        )
        await migrated_db.commit()

        dest = tmp_path / "backup.db"
        result = await migrated_db.backup(dest)
        assert result.exists()
        assert result.stat().st_size > 0
