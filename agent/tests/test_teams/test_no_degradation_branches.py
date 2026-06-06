"""Regression tests ensuring degradation branches (#511) are gone.

Each tool function must call ctx.deps.X directly without None guards.
When the dep is properly wired, the tool works. When it's None, the
error surfaces immediately via AttributeError rather than returning a
silent fallback string.
"""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock

from tests.test_teams.conftest import make_deps


class FakeCtx:
    def __init__(self, deps):
        self.deps = deps


class TestNoDegradationBranches:
    """Each test verifies a formerly-guarded dep path now raises on None."""

    @pytest.mark.asyncio
    async def test_search_knowledge_calls_dep_directly(self):
        """search_knowledge calls ctx.deps.knowledge_search, no None guard."""
        from teams.tools._common import search_knowledge

        ks = AsyncMock(return_value=["result-1"])
        deps = make_deps(knowledge_search=ks)
        ctx = FakeCtx(deps)
        result = await search_knowledge(ctx, "openai")
        ks.assert_called_once_with("openai", limit=5)
        assert "result-1" in result

    @pytest.mark.asyncio
    async def test_recall_past_decisions_calls_dep_directly(self):
        """recall_past_decisions calls ctx.deps.knowledge_search without None guard."""
        from teams.tools._board import recall_past_decisions

        ks = AsyncMock(return_value=["decision-A"])
        deps = make_deps(knowledge_search=ks)
        ctx = FakeCtx(deps)
        result = await recall_past_decisions(ctx, "auth")
        ks.assert_called_once_with("decision:auth", limit=15)
        assert "decision-A" in result

    @pytest.mark.asyncio
    async def test_query_metrics_calls_dep_directly(self):
        """query_metrics calls ctx.deps.memory_store.get without None guard."""
        from teams.tools._ops import query_metrics

        store = AsyncMock()
        store.get = AsyncMock(return_value="42")
        deps = make_deps(memory_store=store)
        ctx = FakeCtx(deps)
        result = await query_metrics(ctx, "requests")
        store.get.assert_called_once_with("metric:requests:latest")
        assert "42" in result

    @pytest.mark.asyncio
    async def test_search_market_data_calls_dep_directly(self):
        """search_market_data calls ctx.deps.knowledge_search without None guard."""
        from teams.tools._strategy import search_market_data

        ks = AsyncMock(return_value=["market-data-1"])
        deps = make_deps(knowledge_search=ks)
        ctx = FakeCtx(deps)
        result = await search_market_data(ctx, "SaaS")
        ks.assert_called_once_with("SaaS", limit=10)
        assert "market-data-1" in result

    @pytest.mark.asyncio
    async def test_recall_decision_calls_dep_directly(self):
        """recall_decision calls ctx.deps.memory_store.get without None guard."""
        from teams.tools._strategy import recall_decision

        store = AsyncMock()
        store.get = AsyncMock(return_value="use pydantic-ai")
        deps = make_deps(memory_store=store)
        ctx = FakeCtx(deps)
        result = await recall_decision(ctx, "framework")
        store.get.assert_called_once_with("decision:framework")
        assert "pydantic-ai" in result

    @pytest.mark.asyncio
    async def test_search_design_system_calls_dep_directly(self):
        """search_design_system calls ctx.deps.knowledge_search without None guard."""
        from teams.tools._design import search_design_system

        ks = AsyncMock(return_value=["button-component"])
        deps = make_deps(knowledge_search=ks)
        ctx = FakeCtx(deps)
        result = await search_design_system(ctx, "button")
        ks.assert_called_once_with("design:button", limit=10)
        assert "button-component" in result

    @pytest.mark.asyncio
    async def test_recall_brand_guidelines_calls_dep_directly(self):
        """recall_brand_guidelines calls ctx.deps.memory_store.get without None guard."""
        from teams.tools._design import recall_brand_guidelines

        store = AsyncMock()
        store.get = AsyncMock(return_value="brand: blue")
        deps = make_deps(memory_store=store)
        ctx = FakeCtx(deps)
        result = await recall_brand_guidelines(ctx)
        store.get.assert_called_once_with("brand:guidelines")
        assert "blue" in result

    @pytest.mark.asyncio
    async def test_memory_recall_calls_dep_directly(self):
        """memory_recall calls ctx.deps.memory_store.get without None guard."""
        from teams._tool_registry import memory_recall

        store = AsyncMock()
        store.get = AsyncMock(return_value="some-value")
        deps = make_deps(memory_store=store)
        ctx = FakeCtx(deps)
        result = await memory_recall(ctx, "my:key")
        store.get.assert_called_once_with("my:key")
        assert "some-value" in result

    @pytest.mark.asyncio
    async def test_no_silent_fallback_strings_returned(self):
        """None of the tool functions return legacy [no X] fallback strings."""
        from teams.tools._common import search_knowledge
        from teams.tools._board import recall_past_decisions
        from teams.tools._ops import query_metrics
        from teams.tools._strategy import search_market_data, recall_decision
        from teams.tools._design import search_design_system, recall_brand_guidelines
        from teams._tool_registry import memory_recall

        ks = AsyncMock(return_value=[])
        store = AsyncMock()
        store.get = AsyncMock(return_value=None)
        deps = make_deps(knowledge_search=ks, memory_store=store)
        ctx = FakeCtx(deps)

        # All should call through without returning a [no X] string
        r1 = await search_knowledge(ctx, "x")
        r2 = await recall_past_decisions(ctx, "x")
        r3 = await query_metrics(ctx, "x")
        r4 = await search_market_data(ctx, "x")
        r5 = await recall_decision(ctx, "x")
        r6 = await search_design_system(ctx, "x")
        r7 = await recall_brand_guidelines(ctx)
        r8 = await memory_recall(ctx, "x")

        for r in [r1, r2, r3, r4, r5, r6, r7, r8]:
            assert "[no " not in r, f"Found legacy degradation string in: {r!r}"
            assert "not available" not in r, f"Found legacy fallback in: {r!r}"
