"""Tests for session search (FTS5 on conversations) and recall-intent detection."""

from __future__ import annotations

import pytest
import pytest_asyncio

from bridge.database import Database
from bridge.memory import Memory


@pytest_asyncio.fixture
async def search_db(tmp_path):
    """Return a connected + migrated Database (includes migration 8: conversations_fts)."""
    db = Database(tmp_path / "search_test.db")
    await db.connect()
    await db.migrate()
    yield db
    await db.close()


@pytest_asyncio.fixture
async def search_memory(search_db, sample_config):
    """Return a Memory instance with search-capable DB."""
    return Memory(search_db, sample_config)


# ---------------------------------------------------------------------------
# Migration 8: FTS5 table exists
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_migration_8_creates_fts_table(search_db):
    """Migration 8 creates conversations_fts virtual table."""
    version = await search_db.get_schema_version()
    assert version >= 8

    # Verify the FTS5 table exists by querying it
    row = await search_db.fetchone(
        "SELECT COUNT(*) FROM sqlite_master WHERE name = 'conversations_fts'"
    )
    assert row[0] == 1


@pytest.mark.asyncio
async def test_fts_trigger_auto_indexes(search_db):
    """Inserting a conversation auto-populates conversations_fts via trigger."""
    await search_db.execute(
        """INSERT INTO conversations (session_id, chat_id, role, content)
           VALUES ('s1', 'c1', 'user', 'deploy helper issues')""",
    )
    await search_db.commit()

    row = await search_db.fetchone(
        "SELECT COUNT(*) FROM conversations_fts WHERE conversations_fts MATCH '\"deploy\"'"
    )
    assert row[0] == 1


# ---------------------------------------------------------------------------
# search_conversations()
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_search_returns_matches(search_memory):
    """Search finds matching conversations grouped by session."""
    await search_memory.store_message("sess-a", "c1", "user", "How do I deploy the bridge?")
    await search_memory.store_message("sess-a", "c1", "assistant", "Run the deploy script.")
    await search_memory.store_message("sess-b", "c1", "user", "What is the weather today?")

    results = await search_memory.search_conversations("deploy")
    assert len(results) >= 1
    assert results[0]["session_id"] == "sess-a"
    assert results[0]["match_count"] >= 1


@pytest.mark.asyncio
async def test_search_empty_query(search_memory):
    """Empty query returns empty results (not an error)."""
    results = await search_memory.search_conversations("")
    assert results == []


@pytest.mark.asyncio
async def test_search_no_matches(search_memory):
    """Query with no matches returns empty list."""
    await search_memory.store_message("sess-a", "c1", "user", "Hello world")

    results = await search_memory.search_conversations("xyznonexistent")
    assert results == []


@pytest.mark.asyncio
async def test_search_role_filter(search_memory):
    """Role filter limits results to specified roles."""
    await search_memory.store_message("sess-a", "c1", "user", "deploy the bridge")
    await search_memory.store_message("sess-a", "c1", "assistant", "deploy completed")

    # Only user messages
    results = await search_memory.search_conversations("deploy", role_filter=["user"])
    assert len(results) >= 1
    for session in results:
        for match in session["matches"]:
            assert match["role"] == "user"


@pytest.mark.asyncio
async def test_search_multiple_sessions(search_memory):
    """Search across multiple sessions returns grouped results."""
    await search_memory.store_message("sess-1", "c1", "user", "configure the budget limits")
    await search_memory.store_message("sess-2", "c1", "user", "budget is running low")
    await search_memory.store_message("sess-3", "c1", "user", "unrelated topic")

    results = await search_memory.search_conversations("budget")
    session_ids = [r["session_id"] for r in results]
    assert "sess-1" in session_ids
    assert "sess-2" in session_ids
    assert "sess-3" not in session_ids


@pytest.mark.asyncio
async def test_search_limit(search_memory):
    """Limit parameter caps the number of results."""
    for i in range(10):
        await search_memory.store_message(f"sess-{i}", "c1", "user", f"deploy iteration {i}")

    results = await search_memory.search_conversations("deploy", limit=3)
    # Total matches across all sessions should be <= 3
    total = sum(r["match_count"] for r in results)
    assert total <= 3


# ---------------------------------------------------------------------------
# Recall-intent detection in assemble_context
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_recall_intent_detected(search_memory):
    """Messages with recall keywords trigger past conversation search."""
    await search_memory.store_message("sess-old", "c1", "user", "deploy the bridge yesterday")

    context = await search_memory.assemble_context(
        "c1", "sess-new", user_message="do you remember when we talked about deploy?"
    )
    assert "Past Conversations" in context


@pytest.mark.asyncio
async def test_no_recall_intent(search_memory):
    """Messages without recall keywords don't trigger recall search."""
    await search_memory.store_message("sess-old", "c1", "user", "deploy the bridge")

    context = await search_memory.assemble_context(
        "c1", "sess-new", user_message="deploy the bridge again"
    )
    assert "Past Conversations" not in context


@pytest.mark.asyncio
async def test_recall_no_matches(search_memory):
    """Recall-intent with no matching conversations doesn't add section."""
    context = await search_memory.assemble_context(
        "c1", "sess-new", user_message="remember when we discussed xyznonexistent?"
    )
    assert "Past Conversations" not in context
