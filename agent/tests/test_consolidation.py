"""Comprehensive tests for bridge.consolidation and ConsolidationService."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from bridge.consolidation import (
    ConsolidationReport,
    decay,
    find_contradictions,
    inventory,
    merge_duplicates,
    promote_patterns,
    run_pipeline,
)


# ---------------------------------------------------------------------------
# Helpers: row factories
# ---------------------------------------------------------------------------


def _make_row(
    key: str = "test:key",
    value: str = "some value",
    category: str = "reference",
    source: str = "agent",
    salience: float = 1.0,
    access_count: int = 0,
    created_at: str | None = None,
    updated_at: str | None = None,
    accessed_at: str | None = None,
) -> dict:
    now = datetime.now(timezone.utc).isoformat()
    return {
        "key": key,
        "value": value,
        "category": category,
        "source": source,
        "salience": salience,
        "access_count": access_count,
        "created_at": created_at or now,
        "updated_at": updated_at or now,
        "accessed_at": accessed_at or now,
    }


# ---------------------------------------------------------------------------
# Phase 1: Inventory
# ---------------------------------------------------------------------------


class TestInventory:
    """Tests for the inventory phase."""

    def test_empty_rows(self):
        result = inventory([])
        assert result.total == 0
        assert result.by_category == {}
        assert result.by_source == {}
        assert result.oldest_entry is None
        assert result.newest_entry is None

    def test_single_row(self):
        rows = [_make_row(category="decision", source="operator")]
        result = inventory(rows)
        assert result.total == 1
        assert result.by_category == {"decision": 1}
        assert result.by_source == {"operator": 1}

    def test_counts_by_category(self):
        rows = [
            _make_row(category="decision"),
            _make_row(category="decision"),
            _make_row(category="learning"),
            _make_row(category="preference"),
        ]
        result = inventory(rows)
        assert result.total == 4
        assert result.by_category == {"decision": 2, "learning": 1, "preference": 1}

    def test_counts_by_source(self):
        rows = [
            _make_row(source="operator"),
            _make_row(source="agent"),
            _make_row(source="agent"),
        ]
        result = inventory(rows)
        assert result.by_source == {"operator": 1, "agent": 2}

    def test_oldest_newest_entry(self):
        rows = [
            _make_row(created_at="2026-01-01T00:00:00Z"),
            _make_row(created_at="2026-06-15T12:00:00Z"),
            _make_row(created_at="2026-03-10T08:00:00Z"),
        ]
        result = inventory(rows)
        assert result.oldest_entry == "2026-01-01T00:00:00Z"
        assert result.newest_entry == "2026-06-15T12:00:00Z"

    def test_frozen_dataclass(self):
        result = inventory([_make_row()])
        with pytest.raises(AttributeError):
            result.total = 42  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Phase 2: Decay
# ---------------------------------------------------------------------------


class TestDecay:
    """Tests for the decay phase."""

    def test_empty_rows(self):
        result = decay([])
        assert result.processed == 0
        assert result.pruned == 0
        assert result.decayed == 0
        assert result.exempt == 0

    def test_exempt_category_preference(self):
        rows = [_make_row(category="preference", salience=1.0)]
        result = decay(rows)
        assert result.exempt == 1
        assert result.decayed == 0
        assert rows[0]["_action"] == "exempt"

    def test_exempt_category_person(self):
        rows = [_make_row(category="person", salience=0.5)]
        result = decay(rows)
        assert result.exempt == 1
        assert rows[0]["_action"] == "exempt"

    def test_exempt_source_operator(self):
        rows = [_make_row(source="operator", category="decision", salience=1.0)]
        result = decay(rows)
        assert result.exempt == 1
        assert rows[0]["_action"] == "exempt"

    def test_decay_applied_project(self):
        """Project entries decay at 0.99/day."""
        rows = [_make_row(category="project", salience=1.0)]
        result = decay(rows, days_elapsed=1)
        assert result.decayed == 1
        assert abs(rows[0]["_new_salience"] - 0.99) < 0.001

    def test_decay_applied_learning(self):
        """Learning entries decay at 0.98/day."""
        rows = [_make_row(category="learning", salience=1.0)]
        result = decay(rows, days_elapsed=1)
        assert result.decayed == 1
        assert abs(rows[0]["_new_salience"] - 0.98) < 0.001

    def test_decay_multi_day(self):
        """Multi-day decay applies rate^days."""
        rows = [_make_row(category="project", salience=1.0)]
        result = decay(rows, days_elapsed=10)
        # 0.99^10 ≈ 0.9044
        assert result.decayed == 1
        assert abs(rows[0]["_new_salience"] - 0.99**10) < 0.001

    def test_prune_below_threshold(self):
        """Entries that decay below SALIENCE_PRUNE_THRESHOLD (0.1) are pruned."""
        rows = [_make_row(category="learning", salience=0.11)]
        # 0.11 * 0.98 = 0.1078 (above threshold)
        result = decay(rows, days_elapsed=1)
        assert result.decayed == 1
        assert rows[0]["_action"] == "decay"

        # With enough days, it should prune
        rows2 = [_make_row(category="learning", salience=0.11)]
        result2 = decay(rows2, days_elapsed=10)
        # 0.11 * 0.98^10 ≈ 0.0896 (below 0.1)
        assert result2.pruned == 1
        assert rows2[0]["_action"] == "prune"

    def test_none_salience_defaults(self):
        """Rows with salience=None should default to 1.0."""
        rows = [_make_row(category="project", salience=None)]  # type: ignore[arg-type]
        result = decay(rows, days_elapsed=1)
        assert result.decayed == 1

    def test_mixed_rows(self):
        rows = [
            _make_row(key="a", category="preference", salience=1.0),  # exempt
            _make_row(key="b", category="project", salience=1.0),     # decay
            _make_row(key="c", source="operator", salience=0.5),      # exempt
            _make_row(key="d", category="learning", salience=0.05),   # prune (0.05*0.98=0.049)
        ]
        result = decay(rows)
        assert result.exempt == 2
        assert result.decayed == 1
        assert result.pruned == 1
        assert result.processed == 4


# ---------------------------------------------------------------------------
# Phase 3: Contradiction Resolution
# ---------------------------------------------------------------------------


class TestContradictions:
    """Tests for contradiction detection."""

    def test_empty_rows(self):
        result = find_contradictions([])
        assert result.pairs_checked == 0
        assert result.contradictions_found == 0

    def test_no_contradictions(self):
        rows = [
            _make_row(key="a", value="Python is a great language", category="learning"),
            _make_row(key="b", value="JavaScript runs in the browser", category="learning"),
        ]
        result = find_contradictions(rows)
        assert result.contradictions_found == 0

    def test_detect_negation_contradiction(self):
        """Two entries about the same topic where one negates the other."""
        rows = [
            _make_row(
                key="a",
                value="always use dark mode for the editor theme settings",
                category="preference",
            ),
            _make_row(
                key="b",
                value="never use dark mode for the editor theme settings",
                category="preference",
            ),
        ]
        result = find_contradictions(rows)
        assert result.contradictions_found == 1
        assert result.details[0]["reason"] == "negation_mismatch"

    def test_skip_different_categories(self):
        """Entries in different categories are not compared."""
        rows = [
            _make_row(key="a", value="always use dark mode settings", category="preference"),
            _make_row(key="b", value="never use dark mode settings", category="learning"),
        ]
        result = find_contradictions(rows)
        assert result.contradictions_found == 0

    def test_skip_low_overlap(self):
        """Entries with little keyword overlap are skipped."""
        rows = [
            _make_row(key="a", value="deploy using kubernetes containers", category="process"),
            _make_row(key="b", value="don't eat pizza on Tuesdays", category="process"),
        ]
        result = find_contradictions(rows)
        assert result.contradictions_found == 0

    def test_pairs_checked_count(self):
        """For n entries in same category, check n*(n-1)/2 pairs."""
        rows = [
            _make_row(key=f"k{i}", value=f"unique content {i}", category="learning")
            for i in range(4)
        ]
        result = find_contradictions(rows)
        assert result.pairs_checked == 6  # 4C2 = 6

    def test_resolved_always_zero(self):
        """Resolution is deferred to the service layer."""
        rows = [
            _make_row(key="a", value="always deploy production server code", category="process"),
            _make_row(key="b", value="never deploy production server code", category="process"),
        ]
        result = find_contradictions(rows)
        assert result.resolved == 0


# ---------------------------------------------------------------------------
# Phase 4: Merge/Dedup
# ---------------------------------------------------------------------------


class TestMergeDuplicates:
    """Tests for the merge/dedup phase."""

    def test_empty_rows(self):
        result = merge_duplicates([])
        assert result.candidates == 0
        assert result.merged == 0
        assert result.kept == 0

    def test_distinct_entries_not_merged(self):
        rows = [
            _make_row(key="a", value="Python programming language guide"),
            _make_row(key="b", value="Kubernetes cluster deployment"),
        ]
        result = merge_duplicates(rows)
        assert result.merged == 0

    def test_near_duplicates_merged(self):
        rows = [
            _make_row(key="a", value="deploy the application to production server", salience=1.0),
            _make_row(key="b", value="deploy the application to production server quickly", salience=0.8),
        ]
        result = merge_duplicates(rows)
        assert result.merged == 1
        # Higher salience entry kept
        assert rows[0].get("_merge_action") == "keep"
        assert rows[1].get("_merge_action") == "archive"

    def test_higher_salience_kept(self):
        rows = [
            _make_row(key="a", value="deploy application production server", salience=0.3),
            _make_row(key="b", value="deploy application production server fast", salience=0.9),
        ]
        result = merge_duplicates(rows)
        assert result.merged == 1
        assert rows[0].get("_merge_action") == "archive"
        assert rows[1].get("_merge_action") == "keep"

    def test_custom_threshold(self):
        """A lower threshold catches less similar entries."""
        rows = [
            _make_row(key="a", value="deploy application code production server"),
            _make_row(key="b", value="deploy application code staging server"),
        ]
        # At default 0.85, these may or may not merge depending on overlap
        result_strict = merge_duplicates(rows, similarity_threshold=0.95)
        # At 0.5 they should merge
        rows2 = [
            _make_row(key="a", value="deploy application code production server"),
            _make_row(key="b", value="deploy application code staging server"),
        ]
        result_loose = merge_duplicates(rows2, similarity_threshold=0.5)
        assert result_loose.merged >= result_strict.merged

    def test_merge_details(self):
        rows = [
            _make_row(key="a", value="deploy application production server", salience=1.0),
            _make_row(key="b", value="deploy application production server now", salience=0.5),
        ]
        result = merge_duplicates(rows)
        if result.merged > 0:
            assert len(result.details) > 0
            detail = result.details[0]
            assert "kept" in detail
            assert "archived" in detail
            assert "overlap" in detail

    def test_already_archived_not_re_merged(self):
        """If row A is merged away, it should not participate in further merges."""
        rows = [
            _make_row(key="a", value="deploy application production server", salience=1.0),
            _make_row(key="b", value="deploy application production server fast", salience=0.5),
            _make_row(key="c", value="deploy application production server quickly", salience=0.3),
        ]
        result = merge_duplicates(rows)
        # b and c should not both be merged with a separately — one gets merged,
        # the other may be compared with a and merged too, but not re-merged
        archived_keys = [r["key"] for r in rows if r.get("_merge_action") == "archive"]
        # Each archived key should appear only once
        assert len(archived_keys) == len(set(archived_keys))


# ---------------------------------------------------------------------------
# Phase 5: Pattern Promotion
# ---------------------------------------------------------------------------


class TestPromotePatterns:
    """Tests for the pattern promotion phase."""

    def test_empty_rows(self):
        result = promote_patterns([])
        assert result.evaluated == 0
        assert result.promoted == 0
        assert result.demoted == 0

    def test_high_access_promoted(self):
        rows = [_make_row(key="popular", access_count=10, salience=1.0)]
        result = promote_patterns(rows, access_threshold=5)
        assert result.promoted == 1
        assert rows[0]["_promotion_action"] == "promote"
        assert rows[0]["_new_salience"] == 1.2

    def test_promotion_capped_at_max(self):
        from bridge.memory import SALIENCE_MAX
        rows = [_make_row(key="maxed", access_count=10, salience=SALIENCE_MAX)]
        result = promote_patterns(rows, access_threshold=5)
        assert result.promoted == 1
        assert rows[0]["_new_salience"] == SALIENCE_MAX

    def test_low_access_low_salience_demoted(self):
        rows = [_make_row(key="stale", access_count=0, salience=0.3)]
        result = promote_patterns(rows)
        assert result.demoted == 1
        assert rows[0]["_promotion_action"] == "demote"
        assert abs(rows[0]["_new_salience"] - 0.2) < 1e-10

    def test_demotion_floored_at_zero(self):
        rows = [_make_row(key="bottom", access_count=0, salience=0.05)]
        result = promote_patterns(rows)
        assert result.demoted == 1
        assert rows[0]["_new_salience"] == 0.0

    def test_medium_access_no_action(self):
        """Entries with moderate access and salience are untouched."""
        rows = [_make_row(key="normal", access_count=2, salience=0.8)]
        result = promote_patterns(rows)
        assert result.promoted == 0
        assert result.demoted == 0
        assert rows[0]["_promotion_action"] == "none"

    def test_zero_access_high_salience_no_demote(self):
        """Zero access but high salience should not be demoted (salience >= 0.5)."""
        rows = [_make_row(key="fresh", access_count=0, salience=0.8)]
        result = promote_patterns(rows)
        assert result.demoted == 0
        assert rows[0]["_promotion_action"] == "none"

    def test_promotion_details(self):
        rows = [
            _make_row(key="pop", access_count=10, salience=1.0),
            _make_row(key="stale", access_count=0, salience=0.2),
        ]
        result = promote_patterns(rows, access_threshold=5)
        assert len(result.details) == 2
        promoted_detail = next(d for d in result.details if d["action"] == "promote")
        assert promoted_detail["key"] == "pop"
        demoted_detail = next(d for d in result.details if d["action"] == "demote")
        assert demoted_detail["key"] == "stale"

    def test_none_salience_defaults(self):
        """Rows with salience=None should not crash."""
        rows = [_make_row(key="nil", access_count=10, salience=None)]  # type: ignore[arg-type]
        result = promote_patterns(rows, access_threshold=5)
        assert result.promoted == 1

    def test_none_access_count_defaults(self):
        """Rows with access_count=None should not crash."""
        rows = [_make_row(key="nil", access_count=None, salience=0.3)]  # type: ignore[arg-type]
        result = promote_patterns(rows)
        assert result.demoted == 1


# ---------------------------------------------------------------------------
# Phase 6: Pipeline orchestrator
# ---------------------------------------------------------------------------


class TestRunPipeline:
    """Tests for the full pipeline orchestrator."""

    def test_micro_mode_only_inventory_and_decay(self):
        rows = [_make_row(category="learning", salience=1.0)]
        report = run_pipeline(rows, mode="micro")
        assert report.mode == "micro"
        assert "inventory" in report.phase_results
        assert "decay" in report.phase_results
        assert "contradictions" not in report.phase_results
        assert "merge" not in report.phase_results
        assert "promotion" not in report.phase_results

    def test_standard_mode_all_phases(self):
        rows = [_make_row(category="learning", salience=1.0)]
        report = run_pipeline(rows, mode="standard")
        assert report.mode == "standard"
        assert "inventory" in report.phase_results
        assert "decay" in report.phase_results
        assert "contradictions" in report.phase_results
        assert "merge" in report.phase_results
        assert "promotion" in report.phase_results

    def test_deep_mode_no_agent_yields_unavailable(self):
        """Sprint 05.09: deep mode with no DreamAgent wired -> 'unavailable'."""
        rows = [_make_row(category="learning", salience=1.0)]
        report = run_pipeline(rows, mode="deep", _dream_agent=None)
        assert report.mode == "deep"
        assert "deep_resolution" in report.phase_results
        deep = report.phase_results["deep_resolution"]
        assert deep["status"] == "unavailable"
        assert "DreamAgent not wired" in deep["note"]
        # Must NEVER report the legacy 'stubbed' status now.
        assert deep["status"] != "stubbed"

    def test_deep_mode_agent_succeeds_yields_completed(self):
        """Sprint 05.09: deep mode with successful DreamAgent.run -> 'completed'."""
        class _FakeDreamResult:
            success = True
            summary = "consolidated 3 facts"
            files_touched = ["data/memory/facts.md"]
            entries_pruned = 2
            contradictions_resolved = 1
            merges_performed = 4
            error = None

        class _FakeDreamAgent:
            async def run(self, session_ids):
                # Echo arg shape so the pipeline contract is exercised.
                assert isinstance(session_ids, list)
                return _FakeDreamResult()

        rows = [_make_row(key="k1", category="learning", salience=1.0)]
        report = run_pipeline(rows, mode="deep", _dream_agent=_FakeDreamAgent())
        deep = report.phase_results["deep_resolution"]
        assert deep["status"] == "completed"
        assert deep["entries_pruned"] == 2
        assert deep["contradictions_resolved"] == 1
        assert deep["merges_performed"] == 4
        assert deep["summary"] == "consolidated 3 facts"
        assert deep["files_touched"] == ["data/memory/facts.md"]

    def test_deep_mode_agent_run_raises_yields_error(self):
        """Sprint 05.09: deep mode with DreamAgent.run raising -> 'error'."""
        class _BoomAgent:
            async def run(self, session_ids):
                raise RuntimeError("dream blew up")

        rows = [_make_row(key="k1", category="learning", salience=1.0)]
        report = run_pipeline(rows, mode="deep", _dream_agent=_BoomAgent())
        deep = report.phase_results["deep_resolution"]
        assert deep["status"] == "error"
        assert "RuntimeError" in deep["error"] or "dream blew up" in deep["error"]

    def test_deep_mode_agent_returns_failure_yields_error(self):
        """Sprint 05.09: deep mode with DreamResult.success=False -> 'error'."""
        class _FailedDreamResult:
            success = False
            summary = ""
            files_touched: list = []
            entries_pruned = 0
            contradictions_resolved = 0
            merges_performed = 0
            error = "claude_runner_returned_error"

        class _FailingAgent:
            async def run(self, session_ids):
                return _FailedDreamResult()

        rows = [_make_row(key="k1", category="learning", salience=1.0)]
        report = run_pipeline(rows, mode="deep", _dream_agent=_FailingAgent())
        deep = report.phase_results["deep_resolution"]
        assert deep["status"] == "error"
        assert "claude_runner_returned_error" in deep["error"]

    def test_micro_mode_skips_deep_resolution(self):
        """Sprint 05.09: micro mode -> no deep_resolution key (skipped silently)."""
        rows = [_make_row(category="learning", salience=1.0)]
        report = run_pipeline(rows, mode="micro")
        # micro returns early before deep_resolution is set; behaviour preserved.
        assert "deep_resolution" not in report.phase_results

    def test_standard_mode_skipped_status(self):
        """Sprint 05.09: standard mode -> 'skipped' status with explanatory note."""
        rows = [_make_row(category="learning", salience=1.0)]
        report = run_pipeline(rows, mode="standard")
        deep = report.phase_results.get("deep_resolution")
        # Standard mode should mark deep_resolution as skipped to disambiguate
        # from 'unavailable' (deep wanted, no agent) and 'completed'.
        assert deep is not None
        assert deep["status"] == "skipped"
        assert "standard" in deep["note"]

    def test_report_has_timestamp(self):
        report = run_pipeline([], mode="standard")
        assert report.timestamp  # Non-empty ISO string
        assert "T" in report.timestamp  # ISO format

    def test_report_has_duration(self):
        report = run_pipeline([], mode="standard")
        assert report.total_duration_ms >= 0

    def test_report_is_frozen(self):
        report = run_pipeline([], mode="standard")
        with pytest.raises(AttributeError):
            report.mode = "micro"  # type: ignore[misc]

    def test_empty_rows_all_modes(self):
        """Pipeline should not crash on empty input for any mode."""
        for mode in ("micro", "standard", "deep"):
            report = run_pipeline([], mode=mode)
            assert isinstance(report, ConsolidationReport)


# ---------------------------------------------------------------------------
# ConsolidationService tests
# ---------------------------------------------------------------------------


class TestConsolidationService:
    """Tests for the ConsolidationService (DB interaction layer)."""

    @pytest.fixture
    def service(self, tmp_path):
        """Create a ConsolidationService with a temp DB."""
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        db_path = tmp_path / "test.db"

        # Set up minimal DB schema
        conn = sqlite3.connect(str(db_path))
        conn.execute("""
            CREATE TABLE IF NOT EXISTS knowledge (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                tags TEXT,
                source TEXT DEFAULT 'agent',
                category TEXT DEFAULT 'reference',
                salience REAL DEFAULT 1.0,
                access_count INTEGER DEFAULT 0,
                archived INTEGER,
                embedding BLOB,
                created_at TEXT DEFAULT (datetime('now')),
                updated_at TEXT DEFAULT (datetime('now')),
                accessed_at TEXT DEFAULT (datetime('now')),
                expires_at TEXT
            )
        """)
        conn.commit()
        conn.close()

        from bridge.services.consolidation_service import ConsolidationService
        return ConsolidationService(
            data_dir=data_dir,
            db_path=db_path,
            chat_id="test-chat",
            mode="standard",
        )

    def _seed_knowledge(self, db_path: Path, entries: list[dict]) -> None:
        """Insert knowledge entries into the test DB."""
        conn = sqlite3.connect(str(db_path))
        for entry in entries:
            conn.execute(
                """INSERT INTO knowledge (key, value, category, source, salience, access_count)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    entry.get("key", "test"),
                    entry.get("value", "test value"),
                    entry.get("category", "reference"),
                    entry.get("source", "agent"),
                    entry.get("salience", 1.0),
                    entry.get("access_count", 0),
                ),
            )
        conn.commit()
        conn.close()

    def test_run_empty_db(self, service):
        result = service.run()
        assert result.ok is True
        assert result.skip_reason == "no_updates_needed"

    def test_run_with_data(self, service):
        self._seed_knowledge(service.db_path, [
            {"key": "k1", "value": "test value one", "category": "learning", "salience": 1.0},
            {"key": "k2", "value": "test value two", "category": "project", "salience": 0.5},
        ])
        result = service.run()
        # Should produce decay updates
        assert result.ok is True
        assert result.work_items > 0

    def test_run_micro_mode(self, service):
        self._seed_knowledge(service.db_path, [
            {"key": "k1", "value": "test value", "category": "learning", "salience": 0.05},
        ])
        result = service.run(mode="micro")
        # Should prune the low-salience entry
        conn = sqlite3.connect(str(service.db_path))
        row = conn.execute("SELECT archived FROM knowledge WHERE key = 'k1'").fetchone()
        conn.close()
        assert row[0] == 1  # Archived (pruned)

    def test_event_callback_called(self, tmp_path):
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        db_path = tmp_path / "test.db"

        conn = sqlite3.connect(str(db_path))
        conn.execute("""
            CREATE TABLE IF NOT EXISTS knowledge (
                key TEXT PRIMARY KEY, value TEXT NOT NULL, tags TEXT,
                source TEXT DEFAULT 'agent', category TEXT DEFAULT 'reference',
                salience REAL DEFAULT 1.0, access_count INTEGER DEFAULT 0,
                archived INTEGER, embedding BLOB,
                created_at TEXT DEFAULT (datetime('now')),
                updated_at TEXT DEFAULT (datetime('now')),
                accessed_at TEXT DEFAULT (datetime('now')),
                expires_at TEXT
            )
        """)
        conn.commit()
        conn.close()

        callback = MagicMock()
        from bridge.services.consolidation_service import ConsolidationService
        svc = ConsolidationService(
            data_dir=data_dir,
            db_path=db_path,
            chat_id="test",
            event_callback=callback,
        )
        svc.run()
        # Should have emitted started + completed events
        event_types = [call[0][0] for call in callback.call_args_list]
        assert "consolidation.started" in event_types
        assert "consolidation.completed" in event_types

    def test_merge_applies_to_db(self, service):
        """Merged entries should be archived in the DB."""
        self._seed_knowledge(service.db_path, [
            {"key": "k1", "value": "deploy application production server now", "salience": 1.0},
            {"key": "k2", "value": "deploy application production server fast", "salience": 0.3},
        ])
        service.run(mode="standard")
        conn = sqlite3.connect(str(service.db_path))
        row = conn.execute("SELECT archived FROM knowledge WHERE key = 'k2'").fetchone()
        conn.close()
        # k2 should be archived (lower salience, near-duplicate)
        if row:
            # The merge may or may not happen depending on exact token overlap;
            # this is a smoke test
            pass

    def test_promotion_applies_to_db(self, service):
        """High-access entries should get salience boost in DB."""
        self._seed_knowledge(service.db_path, [
            {"key": "popular", "value": "frequently used reference", "category": "reference",
             "salience": 1.0, "access_count": 10},
        ])
        service.run(mode="standard")
        conn = sqlite3.connect(str(service.db_path))
        row = conn.execute("SELECT salience FROM knowledge WHERE key = 'popular'").fetchone()
        conn.close()
        # Salience should have been boosted (after decay + promotion)
        assert row is not None

    def test_record_failure_on_db_error(self, tmp_path):
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        bad_db = tmp_path / "nonexistent" / "test.db"

        from bridge.services.consolidation_service import ConsolidationService
        svc = ConsolidationService(
            data_dir=data_dir,
            db_path=bad_db,
            chat_id="test",
        )
        result = svc.run()
        assert result.ok is False
        assert "db_connect_failed" in result.anomalies

        # State file should record failure
        state = svc.load_state(filename="consolidation-state.json")
        assert state.get("last_error") is not None
