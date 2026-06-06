"""Tests for DreamAgent Mem-7 tier-aware Python-side ops (#1848).

The Mem-7 tier-ops phase runs BEFORE the LLM-side consolidation when:
  - `memory_tiers_enabled = True` AND
  - a database handle is wired into `DreamAgent.__init__`.

These tests cover the deterministic tier ops in isolation — promotion,
demotion, within-tier dedup, per-tier counts, and the flag-off/database-None
back-compat short circuits.

The test fixture builds a minimal `knowledge` table WITHOUT a PRIMARY KEY
on `key` so we can seed duplicate `(tier, key, value)` triples for the
dedup test. The live schema (`bridge/db/migrations.py:_TABLES`) keeps the
PK constraint, so dedup is a defensive no-op in production; the test
schema diverges to exercise the dedup branch.
"""
from __future__ import annotations

import dataclasses
from datetime import datetime, timedelta, timezone

import aiosqlite
import pytest


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

_KNOWLEDGE_SCHEMA = """
CREATE TABLE knowledge (
    key TEXT,
    value TEXT NOT NULL,
    tags TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    expires_at TEXT,
    source TEXT NOT NULL DEFAULT 'agent',
    category TEXT DEFAULT 'reference',
    archived INTEGER DEFAULT 0,
    embedding BLOB,
    salience REAL NOT NULL DEFAULT 1.0,
    accessed_at TEXT,
    access_count INTEGER NOT NULL DEFAULT 0,
    tier TEXT DEFAULT 'context' NOT NULL
);
"""


class _FakeDatabase:
    """Test-only Database wrapper providing execute/fetchall/commit/connect/close.

    Mimics the shape `_run_tier_ops` consumes from the real `bridge.database.Database`.
    Opens an aiosqlite connection on demand; `_run_tier_ops` will connect lazily
    when `_conn is None`.
    """

    def __init__(self, db_path: str):
        self.db_path = db_path
        self._conn: aiosqlite.Connection | None = None
        self.execute_count = 0  # for the no-op tracking test

    async def connect(self) -> None:
        self._conn = await aiosqlite.connect(self.db_path)

    async def close(self) -> None:
        if self._conn is not None:
            await self._conn.close()
            self._conn = None

    async def execute(self, sql: str, params: tuple = ()) -> aiosqlite.Cursor:
        assert self._conn is not None, "FakeDatabase: not connected"
        self.execute_count += 1
        return await self._conn.execute(sql, params)

    async def fetchall(self, sql: str, params: tuple = ()) -> list:
        assert self._conn is not None, "FakeDatabase: not connected"
        cursor = await self._conn.execute(sql, params)
        return await cursor.fetchall()

    async def commit(self) -> None:
        assert self._conn is not None, "FakeDatabase: not connected"
        await self._conn.commit()


async def _seed_knowledge_row(
    db_path: str,
    *,
    key: str,
    value: str,
    tier: str,
    access_count: int = 0,
    accessed_at: str | None = None,
    archived: int = 0,
):
    """Insert one row directly via aiosqlite (no PK, no constraints checked)."""
    if accessed_at is None:
        accessed_at = datetime.now(timezone.utc).isoformat()
    async with aiosqlite.connect(db_path) as conn:
        await conn.execute(
            "INSERT INTO knowledge "
            "(key, value, tier, access_count, accessed_at, archived) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (key, value, tier, access_count, accessed_at, archived),
        )
        await conn.commit()


async def _setup_schema(db_path: str) -> None:
    async with aiosqlite.connect(db_path) as conn:
        await conn.executescript(_KNOWLEDGE_SCHEMA)
        await conn.commit()


@pytest.fixture
def config_flag_on(tmp_path):
    """BridgeConfig with memory_tiers_enabled=True and data_dir = tmp."""
    from bridge.config import BridgeConfig

    return dataclasses.replace(
        BridgeConfig(),
        data_dir=str(tmp_path),
        memory_tiers_enabled=True,
    )


@pytest.fixture
def config_flag_off(tmp_path):
    """BridgeConfig with memory_tiers_enabled=False (default)."""
    from bridge.config import BridgeConfig

    return dataclasses.replace(BridgeConfig(), data_dir=str(tmp_path))


# ---------------------------------------------------------------------------
# Test 1: Flag-off no-op
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tier_ops_flag_off_is_noop(config_flag_off, tmp_path):
    """memory_tiers_enabled=False → _run_tier_ops returns zeros, never touches DB."""
    from bridge.dream_agent import DreamAgent

    db_path = str(tmp_path / "memory.db")
    await _setup_schema(db_path)
    fake_db = _FakeDatabase(db_path)
    agent = DreamAgent(config_flag_off, database=fake_db)

    result = await agent._run_tier_ops()

    assert result == (0, 0, 0, {})
    # No execute() calls and no connection opened.
    assert fake_db.execute_count == 0
    assert fake_db._conn is None


# ---------------------------------------------------------------------------
# Test 2: Database=None no-op
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tier_ops_database_none_is_noop(config_flag_on):
    """database=None → _run_tier_ops is a no-op even with flag on."""
    from bridge.dream_agent import DreamAgent

    agent = DreamAgent(config_flag_on, database=None)

    result = await agent._run_tier_ops()
    assert result == (0, 0, 0, {})


# ---------------------------------------------------------------------------
# Test 3: Promotion fires at threshold (CONTEXT → DECISION at access_count = 5)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_promotion_fires_at_threshold(config_flag_on, tmp_path):
    """CONTEXT row at access_count = 5 → promoted to DECISION."""
    from bridge.dream_agent import DreamAgent

    db_path = str(tmp_path / "memory.db")
    await _setup_schema(db_path)
    await _seed_knowledge_row(
        db_path, key="ctx-1", value="hot", tier="context", access_count=5
    )
    fake_db = _FakeDatabase(db_path)
    agent = DreamAgent(config_flag_on, database=fake_db)

    promotions, demotions, dedups, per_tier = await agent._run_tier_ops()

    assert promotions == 1
    assert demotions == 0
    assert dedups == 0
    # Verify the row's tier moved.
    async with aiosqlite.connect(db_path) as conn:
        rows = await (await conn.execute("SELECT tier FROM knowledge WHERE key = ?", ("ctx-1",))).fetchall()
    assert len(rows) == 1
    assert rows[0][0] == "decision"


# ---------------------------------------------------------------------------
# Test 4: Promotion does NOT fire below threshold
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_promotion_does_not_fire_below_threshold(config_flag_on, tmp_path):
    """CONTEXT row at access_count = 4 → unchanged (threshold is 5)."""
    from bridge.dream_agent import DreamAgent

    db_path = str(tmp_path / "memory.db")
    await _setup_schema(db_path)
    await _seed_knowledge_row(
        db_path, key="ctx-low", value="cool", tier="context", access_count=4
    )
    fake_db = _FakeDatabase(db_path)
    agent = DreamAgent(config_flag_on, database=fake_db)

    promotions, _, _, _ = await agent._run_tier_ops()
    assert promotions == 0
    async with aiosqlite.connect(db_path) as conn:
        rows = await (await conn.execute("SELECT tier FROM knowledge WHERE key = ?", ("ctx-low",))).fetchall()
    assert rows[0][0] == "context"


# ---------------------------------------------------------------------------
# Test 5: PREFERENCE never promotes (top tier)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_preference_never_promotes(config_flag_on, tmp_path):
    """PREFERENCE row at access_count = 999 → unchanged (no higher tier)."""
    from bridge.dream_agent import DreamAgent

    db_path = str(tmp_path / "memory.db")
    await _setup_schema(db_path)
    await _seed_knowledge_row(
        db_path, key="pref-hot", value="v", tier="preference", access_count=999
    )
    fake_db = _FakeDatabase(db_path)
    agent = DreamAgent(config_flag_on, database=fake_db)

    promotions, _, _, _ = await agent._run_tier_ops()
    assert promotions == 0
    async with aiosqlite.connect(db_path) as conn:
        rows = await (await conn.execute("SELECT tier FROM knowledge WHERE key = ?", ("pref-hot",))).fetchall()
    assert rows[0][0] == "preference"


# ---------------------------------------------------------------------------
# Test 6: DECISION demotes after 30 days inactivity
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_decision_demotes_after_inactivity_window(config_flag_on, tmp_path):
    """DECISION row with accessed_at = now - 31 days → demoted to CONTEXT."""
    from bridge.dream_agent import DreamAgent

    db_path = str(tmp_path / "memory.db")
    await _setup_schema(db_path)
    stale = (datetime.now(timezone.utc) - timedelta(days=31)).isoformat()
    await _seed_knowledge_row(
        db_path,
        key="dec-stale",
        value="old",
        tier="decision",
        access_count=0,
        accessed_at=stale,
    )
    fake_db = _FakeDatabase(db_path)
    agent = DreamAgent(config_flag_on, database=fake_db)

    promotions, demotions, _, _ = await agent._run_tier_ops()
    assert demotions == 1
    assert promotions == 0
    async with aiosqlite.connect(db_path) as conn:
        rows = await (await conn.execute("SELECT tier FROM knowledge WHERE key = ?", ("dec-stale",))).fetchall()
    assert rows[0][0] == "context"


# ---------------------------------------------------------------------------
# Test 7: PREFERENCE never demotes (curated content)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_preference_never_demotes(config_flag_on, tmp_path):
    """PREFERENCE row with accessed_at = now - 365 days → unchanged."""
    from bridge.dream_agent import DreamAgent

    db_path = str(tmp_path / "memory.db")
    await _setup_schema(db_path)
    ancient = (datetime.now(timezone.utc) - timedelta(days=365)).isoformat()
    await _seed_knowledge_row(
        db_path,
        key="pref-cold",
        value="curated",
        tier="preference",
        access_count=0,
        accessed_at=ancient,
    )
    fake_db = _FakeDatabase(db_path)
    agent = DreamAgent(config_flag_on, database=fake_db)

    _, demotions, _, _ = await agent._run_tier_ops()
    assert demotions == 0
    async with aiosqlite.connect(db_path) as conn:
        rows = await (await conn.execute("SELECT tier FROM knowledge WHERE key = ?", ("pref-cold",))).fetchall()
    assert rows[0][0] == "preference"


# ---------------------------------------------------------------------------
# Test 8: Within-tier dedup collapses exact duplicates
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_within_tier_dedup_collapses_exact_duplicates(config_flag_on, tmp_path):
    """Three rows with identical (tier, key, value) → 2 deletes, 1 survivor."""
    from bridge.dream_agent import DreamAgent

    db_path = str(tmp_path / "memory.db")
    await _setup_schema(db_path)
    # Same key+value+tier three times — only possible because the test
    # schema omits the PK constraint that the live schema enforces.
    for _ in range(3):
        await _seed_knowledge_row(
            db_path, key="dup", value="same", tier="context", access_count=0
        )
    fake_db = _FakeDatabase(db_path)
    agent = DreamAgent(config_flag_on, database=fake_db)

    _, _, dedups, _ = await agent._run_tier_ops()
    assert dedups == 2  # 3 rows → keep 1, delete 2
    async with aiosqlite.connect(db_path) as conn:
        rows = await (await conn.execute("SELECT COUNT(*) FROM knowledge WHERE key = ?", ("dup",))).fetchall()
    assert rows[0][0] == 1


# ---------------------------------------------------------------------------
# Test 9: Per-tier counts populated correctly post-ops
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_per_tier_counts_populated(config_flag_on, tmp_path):
    """After seeding rows across all three tiers, per_tier_counts is accurate."""
    from bridge.dream_agent import DreamAgent

    db_path = str(tmp_path / "memory.db")
    await _setup_schema(db_path)
    # Seed counts that don't trigger promote/demote: access_count=0, recent accessed_at.
    for i in range(3):
        await _seed_knowledge_row(
            db_path, key=f"pref-{i}", value="v", tier="preference"
        )
        await _seed_knowledge_row(
            db_path, key=f"dec-{i}", value="v", tier="decision"
        )
        await _seed_knowledge_row(
            db_path, key=f"ctx-{i}", value="v", tier="context"
        )
    fake_db = _FakeDatabase(db_path)
    agent = DreamAgent(config_flag_on, database=fake_db)

    _, _, _, per_tier = await agent._run_tier_ops()
    assert per_tier == {"preference": 3, "decision": 3, "context": 3}


# ---------------------------------------------------------------------------
# Test 10: Flag-on prompt includes tier-awareness hint
# ---------------------------------------------------------------------------


def test_prompt_flag_on_includes_tier_hint(config_flag_on):
    """When memory_tiers_enabled=True, _build_prompt contains tier awareness text."""
    from bridge.dream_agent import DreamAgent

    agent = DreamAgent(config_flag_on)
    prompt = agent._build_prompt(["s1"])

    assert "Tier awareness" in prompt
    assert "do not merge entries across different tiers" in prompt.lower()


def test_prompt_flag_off_omits_tier_hint(config_flag_off):
    """When memory_tiers_enabled=False, _build_prompt omits the tier hint."""
    from bridge.dream_agent import DreamAgent

    agent = DreamAgent(config_flag_off)
    prompt = agent._build_prompt(["s1"])

    assert "Tier awareness" not in prompt


# ---------------------------------------------------------------------------
# Test 11: DreamResult new fields default to 0/empty (back-compat)
# ---------------------------------------------------------------------------


def test_dream_result_new_fields_default_to_zero():
    """Existing constructions of DreamResult work without specifying new fields."""
    from bridge.dream_agent import DreamResult

    r = DreamResult(
        success=True,
        summary="x",
        files_touched=[],
        entries_pruned=0,
        contradictions_resolved=0,
        merges_performed=0,
    )
    assert r.tier_promotions == 0
    assert r.tier_demotions == 0
    assert r.tier_dedups == 0
    assert r.per_tier_counts == {}


# ---------------------------------------------------------------------------
# Test 12: run() threads tier-ops counters into DreamResult on JSON success
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_threads_tier_counters_into_result(config_flag_on, tmp_path):
    """run() with flag on + DB wired puts tier-ops counters in DreamResult."""
    from unittest.mock import AsyncMock, patch

    from bridge.claude_runner import ClaudeResult
    from bridge.dream_agent import DreamAgent

    db_path = str(tmp_path / "memory.db")
    await _setup_schema(db_path)
    # Seed one CONTEXT row at the promotion threshold so tier-ops fires.
    await _seed_knowledge_row(
        db_path, key="warm", value="v", tier="context", access_count=5
    )

    fake_db = _FakeDatabase(db_path)
    agent = DreamAgent(config_flag_on, database=fake_db)

    json_payload = (
        '{"summary": "ok", "files_touched": [], '
        '"entries_pruned": 0, "contradictions_resolved": 0, "merges_performed": 0}'
    )
    mock_result = ClaudeResult(response_text=json_payload, is_error=False)

    with patch("bridge.dream_agent.ClaudeRunner") as MockRunner:
        instance = MockRunner.return_value
        instance.invoke = AsyncMock(return_value=mock_result)

        result = await agent.run(["s1"])

    assert result.success is True
    assert result.tier_promotions == 1
    assert result.tier_demotions == 0
    assert result.tier_dedups == 0
    assert "decision" in result.per_tier_counts


# ---------------------------------------------------------------------------
# Test 13: Demotion runs BEFORE promotion (ordering matters)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_demote_before_promote_no_yoyo(config_flag_on, tmp_path):
    """A stale-but-hot DECISION row demotes; then promotion target is gone."""
    from bridge.dream_agent import DreamAgent

    db_path = str(tmp_path / "memory.db")
    await _setup_schema(db_path)
    # Stale DECISION (demotion candidate) — accessed 31 days ago, low access_count.
    stale = (datetime.now(timezone.utc) - timedelta(days=31)).isoformat()
    await _seed_knowledge_row(
        db_path,
        key="dec-stale-hot",
        value="v",
        tier="decision",
        access_count=0,  # not at promotion threshold
        accessed_at=stale,
    )
    fake_db = _FakeDatabase(db_path)
    agent = DreamAgent(config_flag_on, database=fake_db)

    promotions, demotions, _, per_tier = await agent._run_tier_ops()
    # Should have demoted to context, NOT promoted to preference.
    assert demotions == 1
    assert promotions == 0
    async with aiosqlite.connect(db_path) as conn:
        rows = await (await conn.execute("SELECT tier FROM knowledge WHERE key = ?", ("dec-stale-hot",))).fetchall()
    assert rows[0][0] == "context"
