"""Tests for Sprint Mem-8 — backfill script + lazy-on-read + strict-mode.

Memory-Tier Architecture epic (#1849).

Covers three deliverables:

1. ``agent/scripts/backfill_memory_tiers.py`` — idempotency, re-classify
   context→preference, skip already-correct rows, resume from state,
   dry-run honours no UPDATEs.
2. ``bridge.memory.knowledge.KnowledgeMixin._lazy_classify_if_null`` —
   read-path lazy classification fires only when flag is on.
3. ``bridge.hybrid_search.HybridSearch.search_tiered`` strict-mode
   filter — NULL-tier rows logged as WARNING.
"""

from __future__ import annotations

import dataclasses
import json
import logging
import sqlite3
import sys
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Path bootstrap — the script lives at agent/scripts/, which is NOT importable
# as ``agent.scripts.*`` from the test runner (it's run from inside agent/
# with sys.path already pointing here). Import the module by file path so
# both ``python -m pytest`` from agent/ and from the repo root work.
# ---------------------------------------------------------------------------

_AGENT_ROOT = Path(__file__).resolve().parent.parent
_SCRIPTS_DIR = _AGENT_ROOT / "scripts"
if str(_AGENT_ROOT) not in sys.path:
    sys.path.insert(0, str(_AGENT_ROOT))
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

import backfill_memory_tiers as backfill_mod  # noqa: E402

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _seed_knowledge_schema(conn: sqlite3.Connection) -> None:
    """Minimal schema matching Migration 14 — just enough columns for the
    backfill script's SELECT/UPDATE to succeed."""
    conn.execute(
        """CREATE TABLE knowledge (
            key TEXT PRIMARY KEY,
            value TEXT,
            tier TEXT DEFAULT 'context' NOT NULL,
            archived INTEGER DEFAULT 0
        )"""
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_knowledge_tier ON knowledge(tier)"
    )
    conn.commit()


def _insert_row(
    conn: sqlite3.Connection, key: str, value: str, tier: str = "context",
) -> None:
    conn.execute(
        "INSERT INTO knowledge (key, value, tier) VALUES (?, ?, ?)",
        (key, value, tier),
    )
    conn.commit()


@pytest.fixture
def seeded_db(tmp_path: Path) -> Path:
    """A fresh sqlite DB with the migration-14 knowledge schema."""
    db_path = tmp_path / "memory.db"
    conn = sqlite3.connect(str(db_path))
    _seed_knowledge_schema(conn)
    conn.close()
    return db_path


# ---------------------------------------------------------------------------
# Test 1: Idempotency — second run reports zero classifications.
# ---------------------------------------------------------------------------


def test_idempotency_second_run_unchanged(seeded_db: Path, tmp_path: Path):
    """Re-running backfill against a fully-classified DB is a no-op."""
    conn = sqlite3.connect(str(seeded_db))
    # Mixed seeding: one preference-text row mis-tiered, one truly context.
    _insert_row(conn, "k-pref", "I prefer dark mode", tier="context")
    _insert_row(conn, "k-ctx", "random unrelated content", tier="context")
    conn.close()

    state_path = tmp_path / "state.json"

    # First pass — reclassifies the preference row.
    state1 = backfill_mod.backfill(
        seeded_db,
        dry_run=False,
        batch_size=100,
        state_path=state_path,
    )
    assert state1["rows_classified"] == 1
    assert state1["rows_unchanged"] == 1

    # Verify the DB shows the reclassification.
    conn = sqlite3.connect(str(seeded_db))
    rows = dict(conn.execute("SELECT key, tier FROM knowledge").fetchall())
    conn.close()
    assert rows["k-pref"] == "preference"
    assert rows["k-ctx"] == "context"

    # Second pass against the same DB — must report zero new classifications.
    # Reset state so the cursor restarts from the beginning of the table.
    state_path.unlink()
    state2 = backfill_mod.backfill(
        seeded_db,
        dry_run=False,
        batch_size=100,
        state_path=state_path,
    )
    assert state2["rows_classified"] == 0
    # k-pref is now 'preference' (no longer 'context'), so the SELECT skips it.
    # k-ctx remains 'context' and stays unchanged.
    assert state2["rows_unchanged"] == 1


# ---------------------------------------------------------------------------
# Test 2: Re-classify context → preference.
# ---------------------------------------------------------------------------


def test_reclassify_context_to_preference(seeded_db: Path, tmp_path: Path):
    """A row currently tier='context' whose content classifies as
    preference gets UPDATE'd to 'preference'."""
    conn = sqlite3.connect(str(seeded_db))
    _insert_row(conn, "random-key", "I prefer dark mode", tier="context")
    conn.close()

    state = backfill_mod.backfill(
        seeded_db,
        dry_run=False,
        batch_size=100,
        state_path=tmp_path / "state.json",
    )

    assert state["rows_classified"] == 1
    assert state["rows_unchanged"] == 0

    conn = sqlite3.connect(str(seeded_db))
    tier = conn.execute(
        "SELECT tier FROM knowledge WHERE key = ?", ("random-key",),
    ).fetchone()[0]
    conn.close()
    assert tier == "preference"


# ---------------------------------------------------------------------------
# Test 3: Skip already-correct rows.
# ---------------------------------------------------------------------------


def test_skip_already_correct_rows(seeded_db: Path, tmp_path: Path):
    """A context-tier row whose content classifies as 'fact' stays put."""
    conn = sqlite3.connect(str(seeded_db))
    _insert_row(conn, "k-fact", "this is unrelated trivia about XYZ", tier="context")
    conn.close()

    state = backfill_mod.backfill(
        seeded_db,
        dry_run=False,
        batch_size=100,
        state_path=tmp_path / "state.json",
    )

    assert state["rows_classified"] == 0
    assert state["rows_unchanged"] == 1

    conn = sqlite3.connect(str(seeded_db))
    tier = conn.execute(
        "SELECT tier FROM knowledge WHERE key = ?", ("k-fact",),
    ).fetchone()[0]
    conn.close()
    assert tier == "context"


# ---------------------------------------------------------------------------
# Test 4: Resume from state file picks up where we left off.
# ---------------------------------------------------------------------------


def test_resume_from_state_file(seeded_db: Path, tmp_path: Path):
    """Pre-seed a state file with last_processed_key='k-050'; the next run
    must skip everything alphabetically <= that key and process only k-051..."""
    conn = sqlite3.connect(str(seeded_db))
    for i in range(100):
        _insert_row(
            conn, f"k-{i:03d}", "I prefer dark mode", tier="context",
        )
    conn.close()

    state_path = tmp_path / "state.json"
    # Hand-craft a state that pretends 51 rows are already done.
    state_path.write_text(json.dumps({
        "last_processed_key": "k-050",
        "rows_classified": 51,
        "rows_unchanged": 0,
        "started_at": "2026-05-12T00:00:00+00:00",
        "completed_at": None,
    }))

    state = backfill_mod.backfill(
        seeded_db,
        dry_run=False,
        batch_size=10,
        state_path=state_path,
    )

    # Only k-051..k-099 (49 rows) get processed on this pass.
    # Counters are cumulative — 51 from the pre-seed + 49 from this pass = 100.
    assert state["rows_classified"] == 100
    assert state["last_processed_key"] == "k-099"

    # Only the resumed-from-here rows (k-051..k-099) got actually UPDATEd
    # in the DB — the pre-seed counter was a hand-crafted lie about prior
    # progress. This is exactly what resume promises: pick up where we
    # left off, don't rewind.
    conn = sqlite3.connect(str(seeded_db))
    n_pref = conn.execute(
        "SELECT COUNT(*) FROM knowledge WHERE tier = 'preference'"
    ).fetchone()[0]
    conn.close()
    assert n_pref == 49


# ---------------------------------------------------------------------------
# Test 5: --dry-run does not issue UPDATEs.
# ---------------------------------------------------------------------------


def test_dry_run_makes_no_updates(seeded_db: Path, tmp_path: Path):
    """dry_run=True increments counters but doesn't touch the DB."""
    conn = sqlite3.connect(str(seeded_db))
    _insert_row(conn, "k-pref", "I prefer dark mode", tier="context")
    conn.close()

    state = backfill_mod.backfill(
        seeded_db,
        dry_run=True,
        batch_size=100,
        state_path=tmp_path / "state.json",
    )

    # Counter advanced ...
    assert state["rows_classified"] == 1
    # ... but DB row unchanged.
    conn = sqlite3.connect(str(seeded_db))
    tier = conn.execute(
        "SELECT tier FROM knowledge WHERE key = ?", ("k-pref",),
    ).fetchone()[0]
    conn.close()
    assert tier == "context"


# ---------------------------------------------------------------------------
# Test 6: Lazy-on-read fires only when memory_tiers_enabled is True.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_lazy_classify_flag_off_is_no_op(memory):
    """Default fixture has memory_tiers_enabled=False; lazy helper does
    nothing — returns the row dict unchanged."""
    assert memory._config.memory_tiers_enabled is False

    row = {"key": "k1", "value": "I prefer dark mode"}
    out = await memory._lazy_classify_if_null(row)

    # No tier was added because the flag is off.
    assert "tier" not in out


@pytest.mark.asyncio
async def test_lazy_classify_flag_on_no_op_when_tier_present(
    migrated_db, sample_config,
):
    """memory_tiers_enabled=True but the row already carries a tier — the
    helper short-circuits without touching the DB."""
    from bridge.memory import Memory

    cfg = dataclasses.replace(sample_config, memory_tiers_enabled=True)
    memory = Memory(migrated_db, cfg)

    row = {"key": "k1", "value": "anything", "tier": "preference"}
    out = await memory._lazy_classify_if_null(row)
    assert out["tier"] == "preference"


@pytest.mark.asyncio
async def test_lazy_classify_flag_on_enriches_from_db(
    migrated_db, sample_config,
):
    """memory_tiers_enabled=True + row dict missing tier + DB row has the
    schema-default 'context': helper enriches the dict from DB without
    issuing any UPDATE."""
    from bridge.memory import Memory

    cfg = dataclasses.replace(sample_config, memory_tiers_enabled=True)
    memory = Memory(migrated_db, cfg)

    # Store a row using the raw DB so we don't go through store_knowledge
    # (which would classify on the way in).
    await memory._db.execute(
        "INSERT INTO knowledge (key, value) VALUES (?, ?)",
        ("k1", "random trivia"),
    )
    await memory._db.commit()

    row = {"key": "k1", "value": "random trivia"}  # no tier field
    out = await memory._lazy_classify_if_null(row)

    # Enriched from DB — schema DEFAULT is 'context'.
    assert out["tier"] == "context"


# ---------------------------------------------------------------------------
# Test 7: Strict mode logs WARNING when NULL-tier rows exist in knowledge.
# ---------------------------------------------------------------------------


def test_strict_mode_logs_warning_on_null_tier(tmp_path: Path, caplog):
    """When strict_tier_required=True, search_tiered logs a WARNING if
    any rows have NULL or empty tier."""
    # Build a DB that mimics what Migration 14 would create, but with one
    # NULL-tier row injected via raw SQL (bypassing the NOT NULL constraint
    # by using a permissive schema).
    db_path = tmp_path / "memory.db"
    conn = sqlite3.connect(str(db_path))
    # Use a permissive variant — no NOT NULL on tier — so we can insert
    # the NULL row that strict-mode is supposed to fail loud about.
    conn.execute(
        """CREATE TABLE knowledge (
            rowid INTEGER PRIMARY KEY,
            key TEXT,
            value TEXT,
            tags TEXT,
            category TEXT,
            tier TEXT,
            archived INTEGER DEFAULT 0
        )"""
    )
    conn.execute(
        """CREATE VIRTUAL TABLE knowledge_fts USING fts5(
            key, value, tags, category, content='knowledge', content_rowid='rowid'
        )"""
    )
    conn.execute("CREATE INDEX idx_knowledge_tier ON knowledge(tier)")

    conn.execute(
        "INSERT INTO knowledge (key, value, tier) VALUES (?, ?, ?)",
        ("k-null", "anything", None),
    )
    conn.execute(
        "INSERT INTO knowledge (key, value, tier) VALUES (?, ?, ?)",
        ("k-ok", "anything", "context"),
    )
    conn.execute(
        "INSERT INTO knowledge_fts (rowid, key, value) "
        "SELECT rowid, key, value FROM knowledge"
    )
    conn.commit()

    # Build a HybridSearch with a zero-cost embedding engine that does the
    # minimum needed for the per-tier vector branch to run without errors.
    from bridge.config import BridgeConfig
    from bridge.hybrid_search import HybridSearch

    class _ZeroEmbed:
        """Trivial embedding engine — emits the same vector for every input
        so cosine similarity is deterministic and non-zero."""
        def embed(self, text: str, is_query: bool = False):  # noqa: D401
            return [1.0, 0.0, 0.0]

    hybrid = HybridSearch(embedding_engine=_ZeroEmbed())
    cfg = BridgeConfig(strict_tier_required=True)

    with caplog.at_level(logging.WARNING, logger="bridge.hybrid_search"):
        hybrid.search_tiered(
            "anything",
            db_connection=conn,
            config=cfg,
            limit_per_tier=5,
        )

    conn.close()

    warnings = [
        rec for rec in caplog.records
        if rec.levelno == logging.WARNING
        and "strict_tier_required" in rec.getMessage()
    ]
    assert len(warnings) >= 1
    assert "1" in warnings[0].getMessage()  # count of NULL rows


def test_strict_mode_off_no_warning(tmp_path: Path, caplog):
    """strict_tier_required=False: no probe, no warning, even when NULL
    rows exist."""
    db_path = tmp_path / "memory.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        """CREATE TABLE knowledge (
            rowid INTEGER PRIMARY KEY,
            key TEXT,
            value TEXT,
            tags TEXT,
            category TEXT,
            tier TEXT,
            archived INTEGER DEFAULT 0
        )"""
    )
    conn.execute(
        """CREATE VIRTUAL TABLE knowledge_fts USING fts5(
            key, value, tags, category, content='knowledge', content_rowid='rowid'
        )"""
    )
    conn.execute("CREATE INDEX idx_knowledge_tier ON knowledge(tier)")
    conn.execute(
        "INSERT INTO knowledge (key, value, tier) VALUES (?, ?, ?)",
        ("k-null", "anything", None),
    )
    conn.execute(
        "INSERT INTO knowledge_fts (rowid, key, value) "
        "SELECT rowid, key, value FROM knowledge"
    )
    conn.commit()

    from bridge.config import BridgeConfig
    from bridge.hybrid_search import HybridSearch

    class _ZeroEmbed:
        def embed(self, text: str, is_query: bool = False):
            return [1.0, 0.0, 0.0]

    hybrid = HybridSearch(embedding_engine=_ZeroEmbed())
    cfg = BridgeConfig()  # strict_tier_required=False by default
    assert cfg.strict_tier_required is False

    with caplog.at_level(logging.WARNING, logger="bridge.hybrid_search"):
        hybrid.search_tiered(
            "anything",
            db_connection=conn,
            config=cfg,
            limit_per_tier=5,
        )

    conn.close()

    strict_warnings = [
        rec for rec in caplog.records
        if "strict_tier_required" in rec.getMessage()
    ]
    assert strict_warnings == []
