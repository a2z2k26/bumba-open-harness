"""Tests for bridge.temporal_knowledge — versioned knowledge with temporal queries."""

from __future__ import annotations

import sqlite3
import time
from datetime import datetime, timedelta, timezone

import pytest

from bridge.temporal_knowledge import (
    DEFAULT_TIER,
    PROMOTION_SIGNALS,
    VALID_TIERS,
    ChangeRecord,
    TemporalKnowledgeStore,
    VersionedEntry,
    assign_tier,
    backfill_default_tier,
    promote_tier,
)


@pytest.fixture
def store(tmp_path):
    """Return a TemporalKnowledgeStore backed by a tmp_path SQLite file."""
    return TemporalKnowledgeStore(db_path=tmp_path / "temporal.db")


@pytest.fixture
def memory_store():
    """Return an in-memory TemporalKnowledgeStore (no tmp_path needed)."""
    return TemporalKnowledgeStore()


# -- TestCreateAndGet --


class TestCreateAndGet:
    def test_put_creates_entry(self, store):
        entry = store.put("project.name", "Bumba", reason="initial setup", changed_by="operator")
        assert isinstance(entry, VersionedEntry)
        assert entry.key == "project.name"
        assert entry.value == "Bumba"
        assert entry.version == 1
        assert entry.change_type == "create"
        assert entry.valid_to is None
        assert entry.reason == "initial setup"
        assert entry.changed_by == "operator"

    def test_get_retrieves_current(self, store):
        store.put("color", "blue")
        result = store.get("color")
        assert result is not None
        assert result.value == "blue"
        assert result.version == 1

    def test_get_nonexistent_returns_none(self, store):
        assert store.get("nonexistent") is None

    def test_put_defaults(self, store):
        entry = store.put("key", "val")
        assert entry.reason == ""
        assert entry.changed_by == "agent"


# -- TestUpdate --


class TestUpdate:
    def test_update_increments_version(self, store):
        store.put("city", "Tokyo")
        entry2 = store.put("city", "Osaka", reason="moved")
        assert entry2.version == 2
        assert entry2.change_type == "update"
        assert entry2.value == "Osaka"

    def test_previous_version_gets_valid_to(self, store):
        store.put("city", "Tokyo")
        store.put("city", "Osaka")

        history = store.get_history("city")
        assert len(history) == 2
        # The first version should have been closed (we verify via get_at later)
        # Current version should be v2
        current = store.get("city")
        assert current is not None
        assert current.version == 2
        assert current.valid_to is None

    def test_triple_update(self, store):
        store.put("x", "1")
        store.put("x", "2")
        entry = store.put("x", "3")
        assert entry.version == 3
        assert store.get("x").value == "3"


# -- TestGetAt --


class TestGetAt:
    def test_temporal_query_returns_correct_version(self, store):
        e1 = store.put("status", "alpha")
        t1 = e1.valid_from

        # Small delay to ensure distinct timestamps
        time.sleep(0.01)

        e2 = store.put("status", "beta")
        t2 = e2.valid_from

        # Query at t1 should return "alpha"
        result = store.get_at("status", t1)
        assert result is not None
        assert result.value == "alpha"

        # Query at t2 should return "beta"
        result = store.get_at("status", t2)
        assert result is not None
        assert result.value == "beta"

    def test_get_at_before_creation_returns_none(self, store):
        past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        store.put("late_key", "value")
        assert store.get_at("late_key", past) is None

    def test_get_at_nonexistent_key(self, store):
        now = datetime.now(timezone.utc).isoformat()
        assert store.get_at("nope", now) is None


# -- TestHistory --


class TestHistory:
    def test_full_timeline_shows_all_changes(self, store):
        store.put("plan", "v1-plan", reason="initial")
        store.put("plan", "v2-plan", reason="revised")
        store.put("plan", "v3-plan", reason="final")

        history = store.get_history("plan")
        assert len(history) == 3

        assert history[0].version == 1
        assert history[0].change_type == "create"
        assert history[0].old_value is None
        assert history[0].new_value == "v1-plan"

        assert history[1].version == 2
        assert history[1].change_type == "update"
        assert history[1].old_value == "v1-plan"
        assert history[1].new_value == "v2-plan"

        assert history[2].version == 3
        assert history[2].old_value == "v2-plan"
        assert history[2].new_value == "v3-plan"

    def test_history_empty_for_unknown_key(self, store):
        assert store.get_history("unknown") == []

    def test_history_records_are_change_records(self, store):
        store.put("k", "v")
        history = store.get_history("k")
        assert len(history) == 1
        assert isinstance(history[0], ChangeRecord)


# -- TestDelete --


class TestDelete:
    def test_delete_removes_from_get(self, store):
        store.put("temp", "data")
        result = store.delete("temp", reason="no longer needed")
        assert result is True
        assert store.get("temp") is None

    def test_delete_nonexistent_returns_false(self, store):
        assert store.delete("ghost") is False

    def test_delete_appears_in_history(self, store):
        store.put("temp", "data")
        store.delete("temp", reason="cleanup")

        history = store.get_history("temp")
        assert len(history) == 2
        assert history[1].change_type == "delete"
        assert history[1].new_value is None
        assert history[1].reason == "cleanup"

    def test_double_delete_returns_false(self, store):
        store.put("temp", "data")
        assert store.delete("temp") is True
        assert store.delete("temp") is False


# -- TestRollback --


class TestRollback:
    def test_rollback_creates_new_version_with_old_value(self, store):
        store.put("config", "v1-config")
        store.put("config", "v2-config")

        rolled = store.rollback("config", to_version=1, reason="revert to v1")
        assert rolled is not None
        assert rolled.version == 3
        assert rolled.value == "v1-config"
        assert rolled.change_type == "rollback"

        current = store.get("config")
        assert current is not None
        assert current.value == "v1-config"
        assert current.version == 3

    def test_rollback_nonexistent_version_returns_none(self, store):
        store.put("k", "v")
        assert store.rollback("k", to_version=99) is None

    def test_rollback_after_delete(self, store):
        store.put("revivable", "original")
        store.delete("revivable")

        rolled = store.rollback("revivable", to_version=1, reason="undoing delete")
        assert rolled is not None
        assert rolled.value == "original"
        assert store.get("revivable") is not None


# -- TestListKeys --


class TestListKeys:
    def test_list_active_keys(self, store):
        store.put("a", "1")
        store.put("b", "2")
        store.put("c", "3")
        store.delete("b")

        keys = store.list_keys(include_deleted=False)
        assert "a" in keys
        assert "c" in keys
        assert "b" not in keys

    def test_list_includes_deleted(self, store):
        store.put("a", "1")
        store.put("b", "2")
        store.delete("b")

        keys = store.list_keys(include_deleted=True)
        assert "a" in keys
        assert "b" in keys

    def test_list_empty_store(self, store):
        assert store.list_keys() == []


# -- TestFormatTimeline --


class TestFormatTimeline:
    def test_format_contains_key_and_versions(self, store):
        store.put("project", "alpha", reason="kickoff", changed_by="operator")
        store.put("project", "beta", reason="phase 2")

        md = store.format_timeline("project")
        assert "## Timeline for `project`" in md
        assert "`v1`" in md
        assert "`v2`" in md
        assert "**[CREATE]**" in md
        assert "**[UPDATE]**" in md
        assert "kickoff" in md
        assert "phase 2" in md

    def test_format_delete_shows_deleted(self, store):
        store.put("tmp", "val")
        store.delete("tmp", reason="done")

        md = store.format_timeline("tmp")
        assert "**[DELETE]**" in md
        assert "_(deleted)_" in md

    def test_format_nonexistent_key(self, store):
        md = store.format_timeline("nope")
        assert "No history found" in md


# -- TestExpiry --


class TestExpiry:
    def test_set_expiry_and_get_expired(self, store):
        store.put("cache_item", "data")
        past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        store.set_expiry("cache_item", past)

        expired = store.get_expired()
        assert "cache_item" in expired

    def test_future_expiry_not_returned(self, store):
        store.put("fresh", "data")
        future = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
        store.set_expiry("fresh", future)

        expired = store.get_expired()
        assert "fresh" not in expired

    def test_no_expiry_not_returned(self, store):
        store.put("permanent", "data")
        assert store.get_expired() == []


# -- TestMultipleKeys --


class TestMultipleKeys:
    def test_keys_are_independent(self, store):
        store.put("x", "10")
        store.put("y", "20")
        store.put("x", "11")

        assert store.get("x").value == "11"
        assert store.get("x").version == 2
        assert store.get("y").value == "20"
        assert store.get("y").version == 1

    def test_delete_one_does_not_affect_other(self, store):
        store.put("keep", "yes")
        store.put("remove", "no")
        store.delete("remove")

        assert store.get("keep") is not None
        assert store.get("remove") is None

    def test_count_reflects_active_keys(self, store):
        assert store.count() == 0
        store.put("a", "1")
        store.put("b", "2")
        assert store.count() == 2
        store.delete("a")
        assert store.count() == 1


# -- TestInMemoryStore --


class TestInMemoryStore:
    def test_memory_store_works(self, memory_store):
        """Verify the in-memory (no db_path) constructor works."""
        entry = memory_store.put("mem_key", "mem_val")
        assert entry.version == 1
        assert memory_store.get("mem_key").value == "mem_val"


# -- Sprint 03.04: L0-L4 memory tier hierarchy --


class TestTierVocabulary:
    """Module-level constants exposing the L0-L4 vocabulary."""

    def test_valid_tiers_are_l0_through_l4(self):
        assert VALID_TIERS == ("L0", "L1", "L2", "L3", "L4")

    def test_default_tier_is_l2(self):
        assert DEFAULT_TIER == "L2"

    def test_promotion_signals_documented(self):
        assert "referenced_again" in PROMOTION_SIGNALS
        assert "operator_pinned" in PROMOTION_SIGNALS
        assert "consolidation_passed" in PROMOTION_SIGNALS


class TestAssignTier:
    """Pure-function classifier — no DB touch."""

    def test_high_importance_returns_l3(self):
        assert assign_tier("doctrine", importance=0.95, age_seconds=0) == "L3"

    def test_recent_medium_importance_returns_l1(self):
        # 6 hours old, importance 0.7 -> recent working memory
        assert assign_tier("note", importance=0.7, age_seconds=6 * 3600) == "L1"

    def test_medium_importance_returns_l2(self):
        # Same importance but older than 1 day -> consolidated
        assert assign_tier("note", importance=0.7, age_seconds=2 * 86400) == "L2"

    def test_low_importance_recent_returns_l0(self):
        assert assign_tier("scratch", importance=0.1, age_seconds=60) == "L0"

    def test_low_importance_stale_returns_l4(self):
        # Low importance + stale -> archive
        assert assign_tier("scratch", importance=0.1, age_seconds=10 * 86400) == "L4"

    def test_empty_content_forces_l0(self):
        assert assign_tier("", importance=0.95, age_seconds=0) == "L0"

    def test_at_threshold_boundaries(self):
        # importance == 0.9 → L3 (>= boundary)
        assert assign_tier("x", importance=0.9, age_seconds=0) == "L3"
        # importance == 0.6 + age == 86400 (1 day exactly) → L1
        assert assign_tier("x", importance=0.6, age_seconds=86400) == "L1"
        # importance == 0.3 → L2
        assert assign_tier("x", importance=0.3, age_seconds=999999) == "L2"


class TestPromoteTier:
    """Pure-function tier promoter."""

    def test_referenced_again_bumps_one_rank(self):
        assert promote_tier("L0", "referenced_again") == "L1"
        assert promote_tier("L1", "referenced_again") == "L2"
        assert promote_tier("L2", "referenced_again") == "L3"
        assert promote_tier("L3", "referenced_again") == "L4"

    def test_referenced_again_caps_at_l4(self):
        assert promote_tier("L4", "referenced_again") == "L4"

    def test_operator_pinned_jumps_to_l3(self):
        assert promote_tier("L0", "operator_pinned") == "L3"
        assert promote_tier("L4", "operator_pinned") == "L3"

    def test_consolidation_passed_bumps_low_tiers_to_l2(self):
        assert promote_tier("L0", "consolidation_passed") == "L2"
        assert promote_tier("L1", "consolidation_passed") == "L2"
        # L2/L3/L4 unchanged
        assert promote_tier("L2", "consolidation_passed") == "L2"
        assert promote_tier("L3", "consolidation_passed") == "L3"
        assert promote_tier("L4", "consolidation_passed") == "L4"

    def test_unknown_signal_is_noop(self):
        assert promote_tier("L1", "garbage") == "L1"
        assert promote_tier("L3", "") == "L3"


class TestSchemaMigration:
    """ADD COLUMN migration must be idempotent and safe on legacy DBs."""

    def test_fresh_db_has_temporal_tier_column(self, tmp_path):
        store = TemporalKnowledgeStore(db_path=tmp_path / "fresh.db")
        # Direct probe via sqlite3
        with sqlite3.connect(str(tmp_path / "fresh.db")) as conn:
            cols = {row[1] for row in conn.execute("PRAGMA table_info(knowledge_history)")}
        assert "temporal_tier" in cols
        # Fresh inserts get DEFAULT_TIER
        store.put("k", "v")
        assert store.tier("k") == DEFAULT_TIER

    def test_migration_on_legacy_db_is_idempotent(self, tmp_path):
        db_path = tmp_path / "legacy.db"
        # Simulate a legacy DB by creating the table without `tier`
        with sqlite3.connect(str(db_path)) as conn:
            conn.execute(
                "CREATE TABLE knowledge_history ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT, "
                "key TEXT NOT NULL, value TEXT, version INTEGER NOT NULL, "
                "valid_from TEXT NOT NULL, valid_to TEXT, "
                "change_type TEXT NOT NULL, reason TEXT NOT NULL DEFAULT '', "
                "changed_by TEXT NOT NULL DEFAULT 'agent', expires_at TEXT)"
            )
            conn.execute(
                "INSERT INTO knowledge_history "
                "(key, value, version, valid_from, valid_to, change_type, reason, changed_by) "
                "VALUES ('legacy', 'data', 1, '2026-01-01T00:00:00+00:00', NULL, "
                "'create', '', 'agent')"
            )
            conn.commit()

        # Open via TemporalKnowledgeStore — migration runs on init.
        store1 = TemporalKnowledgeStore(db_path=db_path)
        assert store1.get("legacy") is not None

        # Re-opening must NOT fail (no-op via PRAGMA probe).
        store2 = TemporalKnowledgeStore(db_path=db_path)
        assert store2.get("legacy").value == "data"

        # The tier column now exists; the modern SQLite ALTER ... ADD COLUMN
        # ... DEFAULT 'L2' propagates the default to pre-existing rows on
        # SQLite >= 3.35. On older SQLite the value would be NULL — both are
        # valid per spec 03.04b (idempotent backfill closes the gap).
        legacy_tier = store2.tier("legacy")
        assert legacy_tier in (None, "L2")

    def test_null_tier_rows_handled_gracefully(self, tmp_path):
        """NULL-tier rows are queryable via ``query_by_tier(None)`` without errors.

        On modern SQLite the ALTER TABLE ... DEFAULT clause propagates 'L2' to
        pre-existing rows, so this path may be empty in practice — but the
        contract guarantees the call doesn't raise and returns whatever rows
        DO carry NULL (relevant on older SQLite + the gap before 03.04b runs).
        """
        store = TemporalKnowledgeStore(db_path=tmp_path / "null_query.db")
        # Manually NULL out a tier to simulate the legacy / older-SQLite case
        store.put("orphan", "data")
        with sqlite3.connect(str(tmp_path / "null_query.db")) as conn:
            conn.execute("UPDATE knowledge_history SET temporal_tier = NULL WHERE key = 'orphan'")
            conn.commit()
        nulls = store.query_by_tier(None)
        assert any(e.key == "orphan" for e in nulls)
        # And NOT in L2 anymore
        assert all(e.key != "orphan" for e in store.query_by_tier("L2"))


class TestBackfillDefaultTier:
    """Sprint 03.04b (#994) — idempotent backfill of NULL tier rows.

    Real-world note: SQLite >= 3.35 auto-propagates ``DEFAULT 'L2'`` to
    pre-existing rows during ALTER TABLE ADD COLUMN, so on the runtime
    Mac (sqlite 3.45.x) the backfill is empirically a no-op. These tests
    cover both paths: the modern auto-fill case (returns 0) and the
    older-SQLite simulated case where rows are explicitly NULLed out.
    """

    def test_backfill_pre_state_null_rows(self, tmp_path):
        """Pre-state: NULL-tier rows (simulating older SQLite) → all become 'L2'."""
        db_path = tmp_path / "null_tier.db"
        store = TemporalKnowledgeStore(db_path=db_path)
        store.put("a", "1")
        store.put("b", "2")
        store.put("c", "3")
        # Force NULL on every row (simulates older SQLite that didn't
        # propagate DEFAULT during ADD COLUMN).
        with sqlite3.connect(str(db_path)) as conn:
            conn.execute("UPDATE knowledge_history SET temporal_tier = NULL")
            conn.commit()
            updated = backfill_default_tier(conn)
            conn.commit()
        assert updated == 3
        # Verify: all three keys now report 'L2'.
        assert store.tier("a") == "L2"
        assert store.tier("b") == "L2"
        assert store.tier("c") == "L2"

    def test_backfill_is_idempotent(self, tmp_path):
        """Second call returns 0; no rows touched twice."""
        db_path = tmp_path / "idempotent.db"
        store = TemporalKnowledgeStore(db_path=db_path)
        store.put("k", "v")
        with sqlite3.connect(str(db_path)) as conn:
            conn.execute("UPDATE knowledge_history SET temporal_tier = NULL")
            conn.commit()
            first = backfill_default_tier(conn)
            conn.commit()
            second = backfill_default_tier(conn)
            conn.commit()
        assert first == 1
        assert second == 0

    def test_backfill_no_op_on_modern_sqlite(self, tmp_path):
        """Post-03.04 ALTER TABLE rows already have 'L2' → backfill returns 0.

        On SQLite >= 3.35 (verified empirically on 3.45.3) the DEFAULT clause
        in ``ALTER TABLE ADD COLUMN`` auto-propagates to pre-existing rows.
        ``_apply_tier_migration`` already calls ``backfill_default_tier`` once,
        so by the time we get here every row is 'L2' and a *second* explicit
        call must be a no-op.
        """
        db_path = tmp_path / "modern.db"
        store = TemporalKnowledgeStore(db_path=db_path)
        store.put("a", "1")
        store.put("b", "2")
        with sqlite3.connect(str(db_path)) as conn:
            updated = backfill_default_tier(conn)
        assert updated == 0
        assert store.tier("a") == "L2"
        assert store.tier("b") == "L2"

    def test_backfill_only_touches_null_rows(self, tmp_path):
        """Mixed L1 + NULL: only NULL rows update, L1 rows untouched."""
        db_path = tmp_path / "mixed.db"
        store = TemporalKnowledgeStore(db_path=db_path)
        store.put("ephem", "x")
        store.put("warm", "y")
        store.put("legacy_a", "z1")
        store.put("legacy_b", "z2")
        # ephem -> L0 (capture-side classify simulation), warm -> L1
        store.set_tier("ephem", "L0")
        store.set_tier("warm", "L1")
        # NULL out the "legacy" rows only
        with sqlite3.connect(str(db_path)) as conn:
            conn.execute(
                "UPDATE knowledge_history SET temporal_tier = NULL WHERE key IN ('legacy_a', 'legacy_b')"
            )
            conn.commit()
            updated = backfill_default_tier(conn)
            conn.commit()
        assert updated == 2
        assert store.tier("ephem") == "L0"
        assert store.tier("warm") == "L1"
        assert store.tier("legacy_a") == "L2"
        assert store.tier("legacy_b") == "L2"

    def test_backfill_defensive_on_missing_column(self, tmp_path, caplog):
        """Fresh DB without the tier column does NOT crash; returns 0 + warns."""
        db_path = tmp_path / "no_column.db"
        with sqlite3.connect(str(db_path)) as conn:
            # Build a legacy schema explicitly missing the tier column.
            conn.execute(
                "CREATE TABLE knowledge_history ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT, "
                "key TEXT NOT NULL, value TEXT, version INTEGER NOT NULL, "
                "valid_from TEXT NOT NULL, valid_to TEXT, "
                "change_type TEXT NOT NULL, reason TEXT NOT NULL DEFAULT '', "
                "changed_by TEXT NOT NULL DEFAULT 'agent', expires_at TEXT)"
            )
            conn.commit()
            with caplog.at_level("WARNING", logger="bridge.temporal_knowledge"):
                updated = backfill_default_tier(conn)
        assert updated == 0
        assert any(
            "tier column not present" in rec.getMessage() for rec in caplog.records
        )

    def test_backfill_rejects_invalid_default(self, tmp_path):
        """Guardrail: an invalid tier label raises ValueError before any UPDATE."""
        db_path = tmp_path / "invalid.db"
        store = TemporalKnowledgeStore(db_path=db_path)
        store.put("k", "v")
        with sqlite3.connect(str(db_path)) as conn:
            with pytest.raises(ValueError):
                backfill_default_tier(conn, default="L9")  # type: ignore[arg-type]

    def test_migration_invokes_backfill_on_legacy_db(self, tmp_path):
        """Init pass on a legacy DB with pre-existing NULL rows → all 'L2' afterward.

        This is the integration path the runtime actually traverses on first
        boot after the 03.04b deploy.
        """
        db_path = tmp_path / "legacy_init.db"
        # Build legacy schema (no tier column) and seed with rows.
        with sqlite3.connect(str(db_path)) as conn:
            conn.execute(
                "CREATE TABLE knowledge_history ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT, "
                "key TEXT NOT NULL, value TEXT, version INTEGER NOT NULL, "
                "valid_from TEXT NOT NULL, valid_to TEXT, "
                "change_type TEXT NOT NULL, reason TEXT NOT NULL DEFAULT '', "
                "changed_by TEXT NOT NULL DEFAULT 'agent', expires_at TEXT)"
            )
            conn.execute(
                "INSERT INTO knowledge_history "
                "(key, value, version, valid_from, valid_to, change_type, reason, changed_by) "
                "VALUES "
                "('legacy_one', 'a', 1, '2026-01-01T00:00:00+00:00', NULL, 'create', '', 'agent'),"
                "('legacy_two', 'b', 1, '2026-01-01T00:00:00+00:00', NULL, 'create', '', 'agent')"
            )
            conn.commit()
        # On modern SQLite, ALTER TABLE ADD COLUMN auto-fills DEFAULT 'L2', so
        # the backfill helper sees zero NULLs. Either way, both rows must end
        # at 'L2' after init — that is the contract of the combined migration.
        store = TemporalKnowledgeStore(db_path=db_path)
        assert store.tier("legacy_one") == "L2"
        assert store.tier("legacy_two") == "L2"
        # And no rows are NULL.
        with sqlite3.connect(str(db_path)) as conn:
            null_count = conn.execute(
                "SELECT count(*) FROM knowledge_history WHERE temporal_tier IS NULL"
            ).fetchone()[0]
        assert null_count == 0


class TestTierAccessors:
    """tier() / set_tier() / query_by_tier() happy paths."""

    def test_tier_returns_default_l2_for_new_keys(self, store):
        store.put("ref.a", "value")
        assert store.tier("ref.a") == "L2"

    def test_tier_returns_none_for_unknown_key(self, store):
        assert store.tier("nope") is None

    def test_tier_returns_none_for_deleted_key(self, store):
        store.put("temp", "v")
        store.delete("temp")
        assert store.tier("temp") is None

    def test_set_tier_updates_in_place_no_history(self, store):
        store.put("k", "v")
        history_before = store.get_history("k")
        result = store.set_tier("k", "L0", reason="capture-side classify")
        assert result is not None
        assert result.tier == "L0"
        assert store.tier("k") == "L0"
        # set_tier does NOT add a history record
        history_after = store.get_history("k")
        assert len(history_after) == len(history_before)

    def test_set_tier_invalid_raises(self, store):
        store.put("k", "v")
        with pytest.raises(ValueError):
            store.set_tier("k", "L9")  # type: ignore[arg-type]

    def test_set_tier_unknown_key_returns_none(self, store):
        assert store.set_tier("ghost", "L1") is None

    def test_query_by_tier_returns_only_matching(self, store):
        store.put("a", "1")  # L2 default
        store.put("b", "2")
        store.put("c", "3")
        store.set_tier("a", "L0")
        store.set_tier("b", "L3")

        l0 = store.query_by_tier("L0")
        assert {e.key for e in l0} == {"a"}
        l2 = store.query_by_tier("L2")
        assert {e.key for e in l2} == {"c"}
        l3 = store.query_by_tier("L3")
        assert {e.key for e in l3} == {"b"}

    def test_query_by_tier_invalid_raises(self, store):
        with pytest.raises(ValueError):
            store.query_by_tier("L7")  # type: ignore[arg-type]


class TestPromoteDemote:
    """Auditable promote/demote — writes new versions to history."""

    def test_tier_returns_default_l2_for_new_keys(self, store):
        # Spec-named test (also covered above via TestTierAccessors)
        store.put("foo", "bar")
        assert store.tier("foo") == "L2"

    def test_promote_writes_history_entry(self, store):
        store.put("doctrine", "rule")
        before_history = store.get_history("doctrine")
        promoted = store.promote("doctrine", "L3", reason="operator pinned")
        assert promoted is not None
        assert promoted.tier == "L3"
        assert promoted.change_type == "promote"
        assert promoted.value == "rule"  # value preserved across promote
        after_history = store.get_history("doctrine")
        assert len(after_history) == len(before_history) + 1
        assert after_history[-1].change_type == "promote"
        assert after_history[-1].reason == "operator pinned"

    def test_demote_writes_history_entry(self, store):
        store.put("scratch", "data")
        store.promote("scratch", "L3", reason="oops promoted")
        demoted = store.demote("scratch", "L0", reason="meant to keep ephemeral")
        assert demoted is not None
        assert demoted.tier == "L0"
        assert demoted.change_type == "demote"
        history = store.get_history("scratch")
        assert history[-1].change_type == "demote"

    def test_promote_invalid_tier_raises(self, store):
        store.put("k", "v")
        with pytest.raises(ValueError):
            store.promote("k", "L9")  # type: ignore[arg-type]

    def test_promote_then_demote_round_trip(self, store):
        store.put("rt", "value")
        assert store.tier("rt") == "L2"
        store.promote("rt", "L3", reason="up")
        assert store.tier("rt") == "L3"
        store.demote("rt", "L1", reason="down")
        assert store.tier("rt") == "L1"
        # Value preserved through both moves
        current = store.get("rt")
        assert current is not None
        assert current.value == "value"

    def test_promote_unknown_key_returns_none(self, store):
        assert store.promote("ghost", "L3") is None

    def test_promote_carries_tier_through_subsequent_put(self, store):
        store.put("k", "v1")
        store.promote("k", "L3", reason="pin")
        # A subsequent put() update inherits the promoted tier
        store.put("k", "v2", reason="content edit")
        assert store.tier("k") == "L3"


class TestVersionedEntryTierField:
    """VersionedEntry.tier round-trip through put / get / get_at."""

    def test_put_returns_entry_with_default_tier(self, store):
        entry = store.put("k", "v")
        assert entry.tier == DEFAULT_TIER

    def test_get_returns_entry_with_tier(self, store):
        store.put("k", "v")
        result = store.get("k")
        assert result is not None
        assert result.tier == DEFAULT_TIER

    def test_versioned_entry_default_tier_field(self):
        # Positional construction (legacy callers) still works thanks to the
        # tier defaulting to None.
        entry = VersionedEntry(
            key="k",
            value="v",
            version=1,
            valid_from="2026-01-01T00:00:00+00:00",
            valid_to=None,
            change_type="create",
            reason="",
            changed_by="agent",
        )
        assert entry.tier is None


class TestFeatureFlagDefault:
    """Sprint 03.04 feature flag is OFF by default — existing behavior preserved."""

    def test_memory_tiers_disabled_by_default(self):
        from bridge.config import BridgeConfig
        cfg = BridgeConfig()
        assert cfg.memory_tiers_enabled is False

    def test_feature_flag_toml_mapping_exists(self):
        from bridge.config import _TOML_MAP
        assert _TOML_MAP.get("memory_tiers.enabled") == "memory_tiers_enabled"


# -- Sprint 03.07: skill version DAG (issue #997) --


class TestSkillDagSchemaMigration:
    """Schema migration is idempotent on fresh + pre-existing DBs."""

    def test_fresh_db_has_skill_dag_tables(self, store):
        # store is a tmp_path file-backed store from the fixture above
        conn = store._connect()
        try:
            tables = {
                row["name"]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
            assert "skill_dag_node" in tables
            assert "skill_dag_edge" in tables
        finally:
            store._release(conn)

    def test_idempotent_on_existing_db(self, tmp_path):
        from bridge.temporal_knowledge import TemporalKnowledgeStore

        db_path = tmp_path / "kb.db"
        store_a = TemporalKnowledgeStore(db_path=db_path)
        # Insert a node so the second store init must not blow it away.
        node_id = store_a.add_skill_node(
            "linter-fix", 1, body_or_diff="echo hi", diff_kind="full"
        )
        # Re-open the same DB — migration should be a no-op.
        store_b = TemporalKnowledgeStore(db_path=db_path)
        survivor = store_b.get_skill_at_version("linter-fix", 1)
        assert survivor is not None
        assert survivor.id == node_id

    def test_legacy_db_predating_dag_tables(self, tmp_path):
        """Simulate a DB created before 03.07 — only knowledge_history exists."""
        db_path = tmp_path / "legacy.db"
        legacy = sqlite3.connect(db_path)
        try:
            legacy.execute(
                "CREATE TABLE knowledge_history ("
                "id INTEGER PRIMARY KEY, key TEXT, value TEXT, version INTEGER, "
                "valid_from TEXT, valid_to TEXT, change_type TEXT, reason TEXT, "
                "changed_by TEXT, expires_at TEXT)"
            )
            legacy.commit()
        finally:
            legacy.close()

        from bridge.temporal_knowledge import TemporalKnowledgeStore

        # Opening on a legacy DB should add the new tables without error.
        store = TemporalKnowledgeStore(db_path=db_path)
        node_id = store.add_skill_node("linter", 1, "body", diff_kind="full")
        assert node_id > 0
        assert store.get_skill_at_version("linter", 1) is not None


class TestSkillDagAddAndRead:
    """Happy paths for ``add_skill_node`` / ``add_skill_edge`` / read API."""

    def test_add_skill_node_returns_row_id(self, memory_store):
        node_id = memory_store.add_skill_node(
            "test-fix", 1, "body v1", diff_kind="full",
            created_by_trigger="post_exec",
        )
        assert isinstance(node_id, int)
        assert node_id > 0

    def test_add_skill_node_invalid_diff_kind_raises(self, memory_store):
        with pytest.raises(ValueError):
            memory_store.add_skill_node(
                "skill", 1, "body", diff_kind="garbage",  # type: ignore[arg-type]
            )

    def test_add_skill_node_unique_skill_version(self, memory_store):
        memory_store.add_skill_node("dup", 1, "v1", diff_kind="full")
        with pytest.raises(sqlite3.IntegrityError):
            memory_store.add_skill_node("dup", 1, "v1-again", diff_kind="full")

    def test_add_skill_edge_invalid_type_raises(self, memory_store):
        a = memory_store.add_skill_node("a", 1, "body", diff_kind="full")
        b = memory_store.add_skill_node("a", 2, "body2", diff_kind="full")
        with pytest.raises(ValueError):
            memory_store.add_skill_edge(a, b, edge_type="bogus")  # type: ignore[arg-type]

    def test_get_skill_at_version_missing_returns_none(self, memory_store):
        assert memory_store.get_skill_at_version("ghost", 7) is None

    def test_root_version_has_no_parents(self, memory_store):
        memory_store.add_skill_node("seed", 1, "body", diff_kind="full")
        node = memory_store.get_skill_at_version("seed", 1)
        assert node is not None
        assert node.parent_versions == ()


class TestSkillDagLineage:
    """``record_skill_version`` + lineage reconstruction."""

    def test_record_skill_version_chains_to_parent(self, memory_store):
        v1 = memory_store.record_skill_version(
            "fix", "full body v1", diff_kind="full",
            created_by_trigger="post_exec",
        )
        assert v1.version == 1
        assert v1.parent_versions == ()

        v2 = memory_store.record_skill_version(
            "fix",
            "+ added retry",
            parent_versions=[1],
            diff_kind="unified",
            created_by_trigger="post_exec",
        )
        assert v2.version == 2
        assert v2.parent_versions == (1,)

        v3 = memory_store.record_skill_version(
            "fix",
            "+ added timeout",
            parent_versions=[2],
            diff_kind="unified",
        )
        assert v3.version == 3
        assert v3.parent_versions == (2,)

        lineage = memory_store.get_skill_lineage("fix")
        assert [v.version for v in lineage] == [1, 2, 3]
        assert [v.parent_versions for v in lineage] == [(), (1,), (2,)]

    def test_record_skill_version_merge_multi_parent(self, memory_store):
        memory_store.record_skill_version("merge-skill", "v1 body", diff_kind="full")
        memory_store.record_skill_version(
            "merge-skill", "v2 patch", parent_versions=[1], diff_kind="unified"
        )
        memory_store.record_skill_version(
            "merge-skill", "v3 patch", parent_versions=[1], diff_kind="unified"
        )
        v4 = memory_store.record_skill_version(
            "merge-skill",
            "v4 = v2 + v3",
            parent_versions=[2, 3],
            diff_kind="json-patch",
            edge_type="merged_from",
            diff_summary="merged divergent v2 and v3",
        )
        assert v4.version == 4
        assert set(v4.parent_versions) == {2, 3}

        lineage = memory_store.get_skill_lineage("merge-skill")
        v4_in_lineage = next(v for v in lineage if v.version == 4)
        assert set(v4_in_lineage.parent_versions) == {2, 3}

    def test_record_skill_version_missing_parent_raises(self, memory_store):
        memory_store.record_skill_version("solo", "body", diff_kind="full")
        with pytest.raises(ValueError):
            memory_store.record_skill_version(
                "solo", "body2", parent_versions=[99], diff_kind="full"
            )

    def test_get_skill_lineage_empty(self, memory_store):
        assert memory_store.get_skill_lineage("never-recorded") == []

    def test_diff_round_trip_preserves_kind(self, memory_store):
        memory_store.record_skill_version(
            "diffy", "@@ -1 +1 @@\n-old\n+new\n",
            diff_kind="unified", created_by_trigger="periodic",
        )
        node = memory_store.get_skill_at_version("diffy", 1)
        assert node is not None
        assert node.diff_kind == "unified"
        assert node.body_or_diff.startswith("@@")
        assert node.created_by_trigger == "periodic"


class TestSkillDagBackfill:
    """v0 backfill of pre-existing skill_evolution proposals."""

    def test_backfill_inserts_v0_for_each_proposal(self, memory_store):
        proposals = [
            ("legacy-skill-a", "body A"),
            ("legacy-skill-b", "body B"),
        ]
        n = memory_store.backfill_skill_proposals_to_v0(proposals)
        assert n == 2
        a = memory_store.get_skill_at_version("legacy-skill-a", 0)
        assert a is not None
        assert a.body_or_diff == "body A"
        assert a.created_by_trigger == "legacy"
        assert a.diff_kind == "full"
        assert a.parent_versions == ()

    def test_backfill_is_idempotent_when_history_exists(self, memory_store):
        memory_store.add_skill_node("already", 1, "v1 body", diff_kind="full")
        n = memory_store.backfill_skill_proposals_to_v0([("already", "ignored")])
        assert n == 0
        # No v0 was inserted on top of the existing v1.
        assert memory_store.get_skill_at_version("already", 0) is None

    def test_backfill_idempotent_on_re_run(self, memory_store):
        proposals = [("rerun-skill", "body")]
        first = memory_store.backfill_skill_proposals_to_v0(proposals)
        second = memory_store.backfill_skill_proposals_to_v0(proposals)
        assert first == 1
        assert second == 0


class TestSkillDagFeatureFlag:
    """Feature-flag-off path: schema + read API still work; flag is False default."""

    def test_skill_version_dag_disabled_by_default(self):
        from bridge.config import BridgeConfig

        cfg = BridgeConfig()
        assert cfg.skill_version_dag_enabled is False

    def test_feature_flag_toml_mapping_exists(self):
        from bridge.config import _TOML_MAP

        assert (
            _TOML_MAP.get("skill_version_dag.enabled") == "skill_version_dag_enabled"
        )

    def test_existing_knowledge_history_api_unchanged(self, store):
        # With the new tables in place, the knowledge_history surface still
        # works exactly as before — versioned put/get/delete cycle.
        store.put("k", "v1")
        store.put("k", "v2", reason="bump")
        assert store.get("k").value == "v2"  # type: ignore[union-attr]
        history = store.get_history("k")
        assert [r.version for r in history] == [1, 2]
        assert store.delete("k") is True
        assert store.get("k") is None
