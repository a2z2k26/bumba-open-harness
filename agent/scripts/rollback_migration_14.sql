-- Rollback for Migration 14 (Mem-2, memory-tier-architecture epic, #1843)
--
-- Restores `knowledge` to its pre-Mem-2 shape; preserves every row.
-- Drops the auto-created index, then drops the `tier` column itself.
--
-- Requires SQLite >= 3.35 for ALTER TABLE DROP COLUMN.
--     Mac mini runtime ships SQLite 3.43+, so this is safe in place;
--     for older copies, fall back to the standard SQLite 12-step rename
--     dance (CREATE temp table, INSERT SELECT, DROP, RENAME).
--
-- Run on a COPY of memory.db first to verify; only then point at the
-- live runtime DB:
--     sqlite3 memory.db < agent/scripts/rollback_migration_14.sql
--
-- After rolling back, also delete the version row so the migration
-- runner will re-apply Migration 14 on next bridge boot if you want
-- to re-forward:
--     DELETE FROM schema_version WHERE version = 14;

DROP INDEX IF EXISTS idx_knowledge_tier;
ALTER TABLE knowledge DROP COLUMN tier;
