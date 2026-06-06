"""Integration tests: Memory lifecycle — knowledge -> daily log -> consolidation -> context assembly.

Sprint 16.4: End-to-end memory lifecycle covering:
- Knowledge store/retrieve/search/archive
- Knowledge extraction from conversation
- Context assembly with stored knowledge
- Salience decay sweep
- Consolidation pipeline promotion of high-access entries
- Goal lifecycle (store -> complete -> verify)
- Tag processing (REMEMBER, FORGET, GOAL, DONE)
- Daily log integration (write -> read -> verify)
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import pytest
import pytest_asyncio

from bridge.consolidation import (
    ConsolidationReport,
    PromotionResult,
    decay,
    inventory,
    run_pipeline,
)
from bridge.daily_log import DailyLogWriter
from bridge.database import Database
from bridge.memory import Memory
from bridge.tag_parser import ParsedTag, TagType


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@dataclass
class _MinimalConfig:
    """Minimal stand-in for BridgeConfig with only fields Memory and DailyLogWriter need."""

    data_dir: str = "/tmp"
    memory_context_window: int = 20
    memory_max_context_tokens: int = 4000
    memory_summary_count: int = 3
    # Sprint 03.06 — memory write-ahead log fields. Memory.__init__ reads
    # memory_wal_path unconditionally; memory_wal_enabled gates whether
    # the WAL actually persists (default OFF mirrors BridgeConfig).
    memory_wal_enabled: bool = False
    memory_wal_path: str = "memory_wal.jsonl"


@pytest_asyncio.fixture
async def db(tmp_path: Path):
    """Connected and migrated in-memory-equivalent DB (file-backed for FTS5 support)."""
    db_path = tmp_path / "lifecycle.db"
    db = Database(db_path)
    await db.connect()
    await db.migrate()
    yield db
    await db.close()


@pytest.fixture
def config(tmp_path: Path) -> _MinimalConfig:
    """Minimal config pointing data_dir at a temp directory."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    return _MinimalConfig(data_dir=str(data_dir))


@pytest_asyncio.fixture
async def mem(db: Database, config: _MinimalConfig) -> Memory:
    """Memory instance backed by the test database."""
    return Memory(db, config)


@pytest.fixture
def daily_log(config: _MinimalConfig) -> DailyLogWriter:
    """DailyLogWriter instance using the temp data_dir."""
    return DailyLogWriter(config)


# ---------------------------------------------------------------------------
# Test 1: Knowledge store -> retrieve -> search
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_knowledge_store_retrieve_search(mem: Memory):
    """Store knowledge entries, retrieve by key, and find via FTS5 search."""
    await mem.store_knowledge(
        "tool:pytest", "Use pytest for all Python testing", tags="testing,python", source="agent", category="tool"
    )
    await mem.store_knowledge(
        "tool:ruff", "Ruff is the preferred Python linter", tags="linting,python", source="agent", category="tool"
    )

    # Retrieve by exact key
    value = await mem.get_knowledge("tool:pytest")
    assert value is not None
    assert "pytest" in value

    # Search via FTS5
    results = await mem.search_knowledge("pytest testing")
    assert len(results) >= 1
    keys = [r["key"] for r in results]
    assert "tool:pytest" in keys


# ---------------------------------------------------------------------------
# Test 2: Knowledge archiving excludes from search
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_knowledge_archive_excludes_from_search(mem: Memory):
    """Archived entries should not appear in FTS5 search results."""
    await mem.store_knowledge("ref:stale-info", "This info is outdated", category="reference")

    archived = await mem.archive_knowledge("ref:stale-info")
    assert archived is True

    results = await mem.search_knowledge("outdated info")
    keys = [r["key"] for r in results]
    assert "ref:stale-info" not in keys


# ---------------------------------------------------------------------------
# Test 3: Knowledge extraction from conversation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_extract_knowledge_from_conversation(mem: Memory):
    """Operator saying 'remember that...' should trigger knowledge storage."""
    user_text = "Remember that my deployment window is Tuesday mornings."
    assistant_text = "Got it, I'll remember that."

    stored = await mem.extract_and_store_knowledge(user_text, assistant_text)
    assert stored >= 1

    # Verify the extracted fact is in the knowledge store
    results = await mem.search_knowledge("deployment window Tuesday")
    assert len(results) >= 1
    # Source should be operator since it was a user statement
    assert any(r["source"] == "operator" for r in results)


# ---------------------------------------------------------------------------
# Test 4: Context assembly includes stored knowledge
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_context_assembly_includes_knowledge(mem: Memory, db: Database):
    """assemble_context should include relevant knowledge entries."""
    chat_id = "test-chat-ctx"
    session_id = "sess-ctx-001"

    # Store a high-salience knowledge entry
    await mem.store_knowledge(
        "decision:api-pattern", "REST with versioned URLs for all public APIs",
        source="operator", category="decision"
    )

    # Store a conversation message so context isn't empty
    await mem.store_message(session_id, chat_id, "user", "What API pattern do we use?")
    await mem.store_message(session_id, chat_id, "assistant", "We use REST with versioned URLs.")

    context = await mem.assemble_context(chat_id, session_id)

    # Context should contain the knowledge entry
    assert "api-pattern" in context or "REST" in context
    # Context should contain the conversation messages
    assert "API pattern" in context


# ---------------------------------------------------------------------------
# Test 5: Salience decay sweep
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_decay_sweep_reduces_salience(mem: Memory, db: Database):
    """run_decay_sweep should decay non-exempt entries with old access timestamps."""
    # Store entries: one agent-sourced (decayable) and one operator-sourced (exempt)
    await mem.store_knowledge(
        "ref:decay-target", "Ephemeral reference data",
        source="agent", category="reference"
    )
    await mem.store_knowledge(
        "pref:no-decay", "Operator preference is sacred",
        source="operator", category="preference"
    )

    # Backdate the accessed_at to trigger decay (decay only fires if accessed_at < now - 1 day)
    await db.execute(
        "UPDATE knowledge SET accessed_at = datetime('now', '-3 days') WHERE key = 'ref:decay-target'"
    )
    await db.commit()

    # Get salience before
    row_before = await db.fetchone(
        "SELECT salience FROM knowledge WHERE key = 'ref:decay-target'"
    )
    salience_before = row_before[0]

    result = await mem.run_decay_sweep()

    # Verify the decayable entry was processed
    assert result["decayed"] >= 1

    # Salience should have decreased
    row_after = await db.fetchone(
        "SELECT salience FROM knowledge WHERE key = 'ref:decay-target'"
    )
    salience_after = row_after[0]
    assert salience_after < salience_before

    # Operator entry should remain untouched (exempt source)
    row_pref = await db.fetchone(
        "SELECT salience FROM knowledge WHERE key = 'pref:no-decay'"
    )
    assert row_pref[0] == 1.0  # Default salience unchanged


# ---------------------------------------------------------------------------
# Test 6: Consolidation pipeline promotes high-access entries
# ---------------------------------------------------------------------------


def test_consolidation_promotes_high_access():
    """High access_count entries should be promoted by the consolidation pipeline."""
    rows = [
        {"key": "proc:hot", "value": "Frequently accessed process doc",
         "category": "process", "source": "agent", "salience": 1.0,
         "access_count": 10, "created_at": "2026-01-01T00:00:00"},
        {"key": "ref:cold", "value": "Rarely accessed reference",
         "category": "reference", "source": "agent", "salience": 0.4,
         "access_count": 0, "created_at": "2026-01-01T00:00:00"},
    ]

    report = run_pipeline(rows, mode="standard")
    promo = report.phase_results["promotion"]
    assert isinstance(promo, PromotionResult)
    assert promo.promoted >= 1

    # The hot entry should have been annotated for promotion
    hot_row = next(r for r in rows if r["key"] == "proc:hot")
    assert hot_row.get("_promotion_action") == "promote"
    assert hot_row.get("_new_salience", 0) > 1.0


# ---------------------------------------------------------------------------
# Test 7: Goal lifecycle — store -> complete -> verify completed
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_goal_lifecycle(mem: Memory):
    """Store a goal, complete it, verify it is no longer active."""
    key = await mem.store_goal("Deploy the new API endpoint")
    assert key.startswith("goal:")

    # Goal should be in active goals
    active = await mem.get_active_goals()
    assert any(g["key"] == key for g in active)

    # Complete the goal
    completed = await mem.complete_goal("deploy")
    assert completed is True

    # Goal should no longer be active
    active_after = await mem.get_active_goals()
    assert not any(g["key"] == key for g in active_after)

    # The archived goal should have completed status
    row = await mem._db.fetchone("SELECT value FROM knowledge WHERE key = ?", (key,))
    data = json.loads(row[0])
    assert data["status"] == "completed"
    assert "finished_at" in data


# ---------------------------------------------------------------------------
# Test 8: Tag processing — REMEMBER tag
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tag_processing_remember(mem: Memory):
    """Processing a REMEMBER tag should store knowledge."""
    tags = [
        ParsedTag(tag_type=TagType.REMEMBER, value="the operator prefers dark mode"),
    ]

    count = await mem.process_tags(tags)
    assert count == 1

    # Verify the fact was stored
    results = await mem.search_knowledge("dark mode")
    assert len(results) >= 1
    assert any("dark mode" in r["value"] for r in results)


# ---------------------------------------------------------------------------
# Test 9: Tag processing — GOAL + DONE lifecycle
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tag_processing_goal_then_done(mem: Memory):
    """Processing GOAL then DONE tags should create and complete the goal."""
    goal_tag = ParsedTag(tag_type=TagType.GOAL, value="Fix the login bug")
    done_tag = ParsedTag(tag_type=TagType.DONE, value="login bug")

    # Create goal
    count_goal = await mem.process_tags([goal_tag])
    assert count_goal == 1

    active = await mem.get_active_goals()
    assert len(active) >= 1
    assert any("login bug" in g.get("description", "") for g in active)

    # Complete goal
    count_done = await mem.process_tags([done_tag])
    assert count_done == 1

    active_after = await mem.get_active_goals()
    assert not any("login bug" in g.get("description", "") for g in active_after)


# ---------------------------------------------------------------------------
# Test 10: Tag processing — FORGET tag archives matching knowledge
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tag_processing_forget(mem: Memory):
    """Processing a FORGET tag should archive the matching knowledge entry."""
    await mem.store_knowledge("user:old-pref", "I like tabs over spaces", category="preference")

    tags = [
        ParsedTag(tag_type=TagType.FORGET, value="old-pref"),
    ]
    count = await mem.process_tags(tags)
    assert count == 1

    # The entry should now be archived
    row = await mem._db.fetchone(
        "SELECT archived FROM knowledge WHERE key = 'user:old-pref'"
    )
    assert row[0] == 1


# ---------------------------------------------------------------------------
# Test 11: Daily log integration — write entries, read them back
# ---------------------------------------------------------------------------


def test_daily_log_write_and_read(daily_log: DailyLogWriter):
    """Appending entries to the daily log and reading them back."""
    daily_log.append("Knowledge entry stored: tool:pytest", category="memory")
    daily_log.append("Consolidation sweep completed", category="service")
    daily_log.append("User asked about API design")

    content = daily_log.read_today()
    assert "Knowledge entry stored: tool:pytest" in content
    assert "Consolidation sweep completed" in content
    assert "User asked about API design" in content

    # Category tags should be present for tagged entries
    assert "[memory]" in content
    assert "[service]" in content


# ---------------------------------------------------------------------------
# Test 12: Consolidation inventory counts categories correctly
# ---------------------------------------------------------------------------


def test_consolidation_inventory_counts():
    """inventory() should correctly tally entries by category and source."""
    rows = [
        {"key": "a", "category": "reference", "source": "agent", "created_at": "2026-01-01"},
        {"key": "b", "category": "reference", "source": "agent", "created_at": "2026-01-02"},
        {"key": "c", "category": "preference", "source": "operator", "created_at": "2026-01-03"},
        {"key": "d", "category": "decision", "source": "agent", "created_at": "2026-01-04"},
    ]

    report = inventory(rows)
    assert report.total == 4
    assert report.by_category["reference"] == 2
    assert report.by_category["preference"] == 1
    assert report.by_source["operator"] == 1
    assert report.oldest_entry == "2026-01-01"
    assert report.newest_entry == "2026-01-04"


# ---------------------------------------------------------------------------
# Test 13: Consolidation decay exempts operator and preference entries
# ---------------------------------------------------------------------------


def test_consolidation_decay_exemptions():
    """decay() should exempt operator-sourced and preference/person category entries."""
    rows = [
        {"key": "pref:dark", "category": "preference", "source": "operator", "salience": 1.0},
        {"key": "person:operator", "category": "person", "source": "agent", "salience": 1.0},
        {"key": "ref:ephemeral", "category": "reference", "source": "agent", "salience": 0.5},
    ]

    result = decay(rows, days_elapsed=30)

    # Preference and person categories are exempt
    assert rows[0]["_action"] == "exempt"
    assert rows[1]["_action"] == "exempt"

    # Reference from agent should be decayed or pruned
    assert rows[2]["_action"] in ("decay", "prune")
    assert result.exempt == 2


# ---------------------------------------------------------------------------
# Test 14: Full lifecycle — store -> search -> reinforce -> decay -> context
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_full_lifecycle_store_search_decay_context(mem: Memory, db: Database):
    """End-to-end lifecycle: store knowledge, search (reinforces), decay, then assemble context."""
    chat_id = "lifecycle-chat"
    session_id = "sess-lifecycle-001"

    # Phase 1: Store knowledge
    await mem.store_knowledge(
        "process:deploy-flow", "Deploy via git push, operator runs deploy script",
        source="agent", category="process"
    )
    await mem.store_knowledge(
        "pref:timezone", "Operator is in EST timezone",
        source="operator", category="preference"
    )

    # Phase 2: Search (triggers salience reinforcement via _reinforce_entries)
    results = await mem.search_knowledge("deploy flow")
    assert len(results) >= 1

    # Verify salience was reinforced
    row = await db.fetchone("SELECT salience, access_count FROM knowledge WHERE key = 'process:deploy-flow'")
    assert row[0] > 1.0  # Reinforced above default 1.0
    assert row[1] >= 1  # access_count incremented

    # Phase 3: Backdate and decay
    await db.execute(
        "UPDATE knowledge SET accessed_at = datetime('now', '-5 days') WHERE key = 'process:deploy-flow'"
    )
    await db.commit()
    sweep = await mem.run_decay_sweep()
    assert sweep["decayed"] >= 1

    # Phase 4: Store a message and assemble context
    await mem.store_message(session_id, chat_id, "user", "How do I deploy?")
    context = await mem.assemble_context(chat_id, session_id)

    # Context should contain at least the conversation and operator preference
    assert "deploy" in context.lower()


# ---------------------------------------------------------------------------
# Test 15: Daily log + consolidation pipeline interplay
# ---------------------------------------------------------------------------


def test_daily_log_and_consolidation_pipeline(daily_log: DailyLogWriter):
    """The daily log records consolidation results which can be read back."""
    # Simulate a consolidation run and log its results
    rows = [
        {"key": "k1", "category": "reference", "source": "agent", "salience": 1.0,
         "access_count": 7, "created_at": "2026-01-01"},
        {"key": "k2", "category": "tool", "source": "agent", "salience": 0.3,
         "access_count": 0, "created_at": "2026-01-01"},
    ]

    report = run_pipeline(rows, mode="standard")
    assert isinstance(report, ConsolidationReport)

    # Log the results (as the bridge service would)
    inv = report.phase_results["inventory"]
    daily_log.append(
        f"Consolidation complete: {inv.total} entries inventoried, "
        f"duration {report.total_duration_ms}ms",
        category="service",
    )

    content = daily_log.read_today()
    assert "Consolidation complete" in content
    assert "2 entries inventoried" in content
    assert "[service]" in content
