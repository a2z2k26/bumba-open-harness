"""Tests for bridge.memory (S56)."""

from __future__ import annotations

import pytest

from bridge.memory import _escape_fts5_query


class TestConversationStorage:
    """S54: Store and retrieve conversations."""

    @pytest.mark.asyncio
    async def test_store_and_retrieve(self, memory):
        await memory.store_message("sess-1", "chat-1", "user", "Hello!")
        await memory.store_message("sess-1", "chat-1", "assistant", "Hi there!")

        messages = await memory.get_recent_messages("chat-1")
        assert len(messages) == 2
        assert messages[0]["role"] == "user"
        assert messages[1]["role"] == "assistant"

    @pytest.mark.asyncio
    async def test_message_order(self, memory):
        for i in range(5):
            await memory.store_message("sess-1", "chat-1", "user", f"Message {i}")

        messages = await memory.get_recent_messages("chat-1")
        assert messages[0]["content"] == "Message 0"
        assert messages[-1]["content"] == "Message 4"

    @pytest.mark.asyncio
    async def test_limit(self, memory):
        for i in range(30):
            await memory.store_message("sess-1", "chat-1", "user", f"Message {i}")

        messages = await memory.get_recent_messages("chat-1", limit=5)
        assert len(messages) == 5

    @pytest.mark.asyncio
    async def test_session_messages(self, memory):
        await memory.store_message("sess-1", "chat-1", "user", "In session 1")
        await memory.store_message("sess-2", "chat-1", "user", "In session 2")

        msgs = await memory.get_session_messages("sess-1")
        assert len(msgs) == 1
        assert msgs[0]["content"] == "In session 1"


class TestKnowledge:
    """S55: Knowledge storage and search."""

    @pytest.mark.asyncio
    async def test_store_and_get(self, memory):
        await memory.store_knowledge("user.name", "the operator", tags="personal")
        value = await memory.get_knowledge("user.name")
        assert value == "the operator"

    @pytest.mark.asyncio
    async def test_upsert(self, memory):
        await memory.store_knowledge("key1", "old value")
        await memory.store_knowledge("key1", "new value")
        value = await memory.get_knowledge("key1")
        assert value == "new value"

    @pytest.mark.asyncio
    async def test_search_fts(self, memory):
        await memory.store_knowledge("fact.language", "Python is the primary language", tags="tech")
        await memory.store_knowledge("fact.db", "SQLite with WAL mode", tags="tech")

        results = await memory.search_knowledge("Python")
        assert len(results) >= 1
        assert results[0]["key"] == "fact.language"

    @pytest.mark.asyncio
    async def test_get_nonexistent(self, memory):
        value = await memory.get_knowledge("nonexistent.key")
        assert value is None


class TestContextAssembly:
    """S55: Context assembly."""

    @pytest.mark.asyncio
    async def test_assemble_context(self, memory, migrated_db):
        # Store some messages
        await memory.store_message("sess-1", "chat-1", "user", "Hello")
        await memory.store_message("sess-1", "chat-1", "assistant", "Hi")

        # Store some knowledge
        await memory.store_knowledge("fact.name", "the operator", source="operator")

        context = await memory.assemble_context("chat-1", "sess-1")
        assert "Recent Conversation" in context
        assert "Hello" in context
        assert "Relevant Memory" in context
        assert "the operator" in context

    @pytest.mark.asyncio
    async def test_empty_context(self, memory):
        context = await memory.assemble_context("chat-1", "sess-1")
        # Should return something (even if empty sections are skipped)
        assert isinstance(context, str)


class TestContextFile:
    """S56: Context file writer."""

    def test_write_and_cleanup(self, memory):
        path = memory.write_context_file("# Context\n\nSome text here.")
        assert path.exists()
        assert path.read_text() == "# Context\n\nSome text here."

        memory.cleanup_context_file()
        assert not path.exists()

    def test_cleanup_no_file(self, memory):
        # Should not raise
        memory.cleanup_context_file()


class TestFTS5QueryEscaping:
    """T0.3.1: FTS5 query escaping."""

    def test_simple_word(self):
        assert _escape_fts5_query("Python") == '"Python"'

    def test_multiple_words(self):
        result = _escape_fts5_query("voice manager")
        assert result == '"voice" "manager"'

    def test_hyphenated_term(self):
        """Hyphens should be quoted to prevent FTS5 NOT interpretation."""
        result = _escape_fts5_query("voice-manager")
        assert result == '"voice-manager"'

    def test_embedded_quotes(self):
        """Double quotes in input should be escaped."""
        result = _escape_fts5_query('say "hello"')
        assert result == '"say" '  + '"""hello"""'

    def test_fts5_operators_neutralized(self):
        """FTS5 operators like NOT, AND, OR should be quoted as literals."""
        assert _escape_fts5_query("NOT working") == '"NOT" "working"'
        assert _escape_fts5_query("this AND that") == '"this" "AND" "that"'
        assert _escape_fts5_query("foo OR bar") == '"foo" "OR" "bar"'

    def test_empty_query(self):
        assert _escape_fts5_query("") == "*"
        assert _escape_fts5_query("   ") == "*"

    def test_parentheses(self):
        result = _escape_fts5_query("(test)")
        assert result == '"(test)"'

    def test_asterisk(self):
        result = _escape_fts5_query("test*")
        assert result == '"test*"'


class TestFTS5SearchIntegration:
    """T0.3.1: FTS5 search with escaped queries."""

    @pytest.mark.asyncio
    async def test_search_hyphenated_term(self, memory):
        """Hyphenated terms should match entries containing the term."""
        await memory.store_knowledge(
            "config:voice-manager", "Voice manager configuration for Discord",
            tags="voice,config",
        )
        results = await memory.search_knowledge("voice-manager")
        assert len(results) >= 1
        assert any("voice" in r["key"] for r in results)

    @pytest.mark.asyncio
    async def test_search_special_chars_no_error(self, memory):
        """Special FTS5 characters should not cause errors."""
        await memory.store_knowledge(
            "note:operator", 'He said "always use quotes" in configs',
            category="reference",
        )
        # None of these should raise
        results = await memory.search_knowledge('"always use quotes"')
        results = await memory.search_knowledge("NOT working")
        results = await memory.search_knowledge("(test)")
        assert isinstance(results, list)

    @pytest.mark.asyncio
    async def test_search_apostrophe(self, memory):
        """Apostrophes in queries should not cause errors."""
        await memory.store_knowledge("pref:theme", "User's preference is dark mode")
        results = await memory.search_knowledge("user's preference")
        assert isinstance(results, list)

    @pytest.mark.asyncio
    async def test_empty_search_returns_by_salience(self, memory):
        """Empty search should return top entries by salience."""
        await memory.store_knowledge("high-sal", "Important fact", category="preference")
        results = await memory.search_knowledge("")
        assert len(results) >= 1

    @pytest.mark.asyncio
    async def test_existing_simple_search_still_works(self, memory):
        """Existing simple word searches should still work after escaping."""
        await memory.store_knowledge("fact.lang", "Python is the primary language", tags="tech")
        await memory.store_knowledge("fact.db", "SQLite with WAL mode", tags="tech")
        results = await memory.search_knowledge("Python")
        assert len(results) >= 1
        assert any("lang" in r["key"] for r in results)


class TestKnowledgeExtraction:
    """T0.3.2: Knowledge extraction from conversations."""

    @pytest.mark.asyncio
    async def test_extract_remember_pattern(self, memory):
        """'remember that' should store a knowledge entry."""
        count = await memory.extract_and_store_knowledge(
            "remember that my timezone is PST",
            "Got it! I'll remember your timezone is PST.",
        )
        assert count >= 1

    @pytest.mark.asyncio
    async def test_extract_preference_pattern(self, memory):
        """'I prefer' should store a preference."""
        count = await memory.extract_and_store_knowledge(
            "I prefer dark mode",
            "Noted! I'll remember your dark mode preference.",
        )
        assert count >= 1

    @pytest.mark.asyncio
    async def test_extract_no_match(self, memory):
        """Regular conversation should not trigger extraction."""
        count = await memory.extract_and_store_knowledge(
            "What is the weather today?",
            "I don't have real-time weather data.",
        )
        assert count == 0

    @pytest.mark.asyncio
    async def test_extracted_knowledge_is_searchable(self, memory):
        """Knowledge extracted from conversation should be searchable."""
        await memory.extract_and_store_knowledge(
            "remember that deploy scripts go to /tmp/",
            "I'll remember that deploy scripts go to /tmp/.",
        )
        results = await memory.search_knowledge("deploy scripts")
        assert len(results) >= 1


class TestSalienceDecay:
    """T0.3.3: Salience decay sweep."""

    @pytest.mark.asyncio
    async def test_decay_sweep_returns_counts(self, memory):
        """run_decay_sweep should return a dict with decayed and archived counts."""
        result = await memory.run_decay_sweep()
        assert "decayed" in result
        assert "archived" in result

    @pytest.mark.asyncio
    async def test_operator_entries_exempt(self, memory):
        """Operator-sourced entries should not be decayed."""
        await memory.store_knowledge("pref:tz", "PST", source="operator", category="preference")
        # Run decay multiple times
        for _ in range(5):
            await memory.run_decay_sweep()
        # Entry should still be active (not archived)
        value = await memory.get_knowledge("pref:tz")
        assert value == "PST"

    @pytest.mark.asyncio
    async def test_preference_category_exempt(self, memory):
        """Preference category should not be decayed."""
        await memory.store_knowledge("pref:theme", "dark", source="agent", category="preference")
        for _ in range(5):
            await memory.run_decay_sweep()
        value = await memory.get_knowledge("pref:theme")
        assert value == "dark"
