"""Tests for structured memory tags integration (Feature 2 + Feature 5)."""

from __future__ import annotations

import json

import pytest

from bridge.memory import KNOWLEDGE_CATEGORIES
from bridge.tag_parser import parse_tags


class TestKnowledgeCategories:
    """Feature 5: Knowledge base categories."""

    @pytest.mark.asyncio
    async def test_store_with_category(self, memory):
        await memory.store_knowledge("test:cat", "value", category="project")
        rows = await memory._db.fetchall(
            "SELECT category FROM knowledge WHERE key = 'test:cat'"
        )
        assert rows[0][0] == "project"

    @pytest.mark.asyncio
    async def test_default_category_is_reference(self, memory):
        await memory.store_knowledge("test:default", "value")
        rows = await memory._db.fetchall(
            "SELECT category FROM knowledge WHERE key = 'test:default'"
        )
        assert rows[0][0] == "reference"

    @pytest.mark.asyncio
    async def test_get_knowledge_by_category(self, memory):
        await memory.store_knowledge("a:1", "val1", category="preference")
        await memory.store_knowledge("a:2", "val2", category="preference")
        await memory.store_knowledge("b:1", "val3", category="project")

        prefs = await memory.get_knowledge_by_category("preference")
        assert len(prefs) == 2
        projects = await memory.get_knowledge_by_category("project")
        assert len(projects) == 1

    @pytest.mark.asyncio
    async def test_archive_knowledge(self, memory):
        await memory.store_knowledge("arch:test", "value")
        result = await memory.archive_knowledge("arch:test")
        assert result is True

        # Should not appear in category queries
        entries = await memory.get_knowledge_by_category("reference")
        keys = [e["key"] for e in entries]
        assert "arch:test" not in keys

    @pytest.mark.asyncio
    async def test_archive_nonexistent_returns_false(self, memory):
        result = await memory.archive_knowledge("nonexistent:key")
        assert result is False

    @pytest.mark.asyncio
    async def test_search_excludes_archived(self, memory):
        await memory.store_knowledge("searchtest:item", "findable content")
        await memory.archive_knowledge("searchtest:item")
        results = await memory.search_knowledge("findable")
        keys = [r["key"] for r in results]
        assert "searchtest:item" not in keys

    def test_knowledge_categories_constant(self):
        assert "preference" in KNOWLEDGE_CATEGORIES
        assert "project" in KNOWLEDGE_CATEGORIES
        assert len(KNOWLEDGE_CATEGORIES) == 8


class TestGoals:
    """Feature 2: Goal management via structured tags."""

    @pytest.mark.asyncio
    async def test_store_goal(self, memory):
        key = await memory.store_goal("Finish the report")
        assert key.startswith("goal:")

        value = await memory.get_knowledge(key)
        assert value is not None
        data = json.loads(value)
        assert data["description"] == "Finish the report"
        assert data["status"] == "active"

    @pytest.mark.asyncio
    async def test_store_goal_with_deadline(self, memory):
        key = await memory.store_goal("Ship v2", "tomorrow")
        value = await memory.get_knowledge(key)
        data = json.loads(value)
        assert "deadline" in data

    @pytest.mark.asyncio
    async def test_get_active_goals(self, memory):
        await memory.store_goal("Goal A")
        await memory.store_goal("Goal B")
        goals = await memory.get_active_goals()
        assert len(goals) == 2

    @pytest.mark.asyncio
    async def test_complete_goal(self, memory):
        await memory.store_goal("Write tests")
        result = await memory.complete_goal("write tests")
        assert result is True

        goals = await memory.get_active_goals()
        assert len(goals) == 0

    @pytest.mark.asyncio
    async def test_cancel_goal(self, memory):
        await memory.store_goal("Old project")
        result = await memory.cancel_goal("old project")
        assert result is True

        goals = await memory.get_active_goals()
        assert len(goals) == 0

    @pytest.mark.asyncio
    async def test_complete_nonexistent_goal(self, memory):
        result = await memory.complete_goal("nothing here")
        assert result is False


class TestProcessTags:
    """Integration: tag parsing → memory operations."""

    @pytest.mark.asyncio
    async def test_process_remember_tag(self, memory):
        tags = parse_tags("[REMEMBER: User loves Python]")
        count = await memory.process_tags(tags)
        assert count == 1

        value = await memory.get_knowledge("user:user-loves-python")
        assert value is not None

    @pytest.mark.asyncio
    async def test_process_goal_tag(self, memory):
        tags = parse_tags("[GOAL: Deploy by Friday | DEADLINE: next Friday]")
        count = await memory.process_tags(tags)
        assert count == 1

        goals = await memory.get_active_goals()
        assert len(goals) == 1
        assert "Deploy by Friday" in goals[0]["description"]

    @pytest.mark.asyncio
    async def test_process_done_tag(self, memory):
        await memory.store_goal("Write documentation")
        tags = parse_tags("[DONE: documentation]")
        count = await memory.process_tags(tags)
        assert count == 1

        goals = await memory.get_active_goals()
        assert len(goals) == 0

    @pytest.mark.asyncio
    async def test_process_forget_tag(self, memory):
        await memory.store_knowledge("user:dark-mode", "prefers dark mode", category="preference")
        tags = parse_tags("[FORGET: dark mode]")
        count = await memory.process_tags(tags)
        assert count == 1

    @pytest.mark.asyncio
    async def test_process_multiple_tags(self, memory):
        text = "[REMEMBER: name is the operator] [GOAL: Ship v3 | DEADLINE: tomorrow]"
        tags = parse_tags(text)
        count = await memory.process_tags(tags)
        assert count == 2

    @pytest.mark.asyncio
    async def test_process_cancel_tag(self, memory):
        await memory.store_goal("Cancelled project")
        tags = parse_tags("[CANCEL: cancelled project]")
        count = await memory.process_tags(tags)
        assert count == 1
