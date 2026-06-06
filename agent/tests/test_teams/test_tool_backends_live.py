"""Tests for Z4.2 — Strategy and Design tool backend verification.

Proves that tool functions reach real Memory/MemoryKVAdapter backends
by seeding canary strings and asserting they appear in tool output.
"""

from __future__ import annotations

import dataclasses

import pytest
import pytest_asyncio

from bridge.config import BridgeConfig
from bridge.database import Database
from bridge.memory import Memory, MemoryKVAdapter
from teams._types import BridgeDeps
from teams.tools._design import (
    lookup_component,
    recall_brand_guidelines,
    search_design_system,
)
from teams.tools._strategy import (
    analyze_competitor,
    recall_decision,
    search_market_data,
)

pytestmark = pytest.mark.live  # Skip in offline CI — requires live DB


# ---------- helpers ----------

class FakeCtx:
    """Minimal stand-in for RunContext[BridgeDeps]."""

    def __init__(self, deps: BridgeDeps) -> None:
        self.deps = deps


# ---------- fixtures ----------

@pytest_asyncio.fixture
async def live_memory(tmp_path):
    """Create a real Memory backed by an in-memory SQLite database."""
    db = Database(tmp_path / "test_backends.db")
    await db.connect()
    await db.migrate()

    config = dataclasses.replace(BridgeConfig(), data_dir=str(tmp_path))
    memory = Memory(db, config)

    # Seed canary entries
    await memory.store_knowledge(
        "competitor:OpenAI",
        "CANARY-Z42-openai-competitor-data",
        tags="competitor",
        source="agent",
        category="reference",
    )
    await memory.store_knowledge(
        "decision:use-pydantic-ai",
        "CANARY-Z42-decision-pydantic-ai",
        tags="decision",
        source="agent",
        category="decision",
    )
    await memory.store_knowledge(
        "brand:guidelines",
        "CANARY-Z42-brand-guidelines-data",
        tags="brand",
        source="agent",
        category="reference",
    )
    await memory.store_knowledge(
        "design:button",
        "CANARY-Z42-design-button-component",
        tags="design,component",
        source="agent",
        category="reference",
    )

    yield memory
    await db.close()


@pytest.fixture
def bridge_deps(live_memory: Memory) -> BridgeDeps:
    """BridgeDeps wired to real Memory backends."""
    from unittest.mock import MagicMock
    return BridgeDeps(
        session_id="z42-test",
        department="strategy",
        operator_id="",
        memory_store=MemoryKVAdapter(live_memory),
        knowledge_search=live_memory.search_knowledge,
        event_bus=MagicMock(),
        trust_manager=MagicMock(),
        cost_tracker=MagicMock(),
    )


# ---------- Strategy tool tests ----------

class TestStrategyToolBackends:
    @pytest.mark.asyncio
    async def test_search_market_data_returns_canary(self, bridge_deps):
        ctx = FakeCtx(bridge_deps)
        result = await search_market_data(ctx, "OpenAI")
        assert "CANARY-Z42" in result

    @pytest.mark.asyncio
    async def test_analyze_competitor_returns_canary(self, bridge_deps):
        ctx = FakeCtx(bridge_deps)
        result = await analyze_competitor(ctx, "OpenAI")
        assert "CANARY-Z42" in result

    @pytest.mark.asyncio
    async def test_recall_decision_returns_canary(self, bridge_deps):
        ctx = FakeCtx(bridge_deps)
        result = await recall_decision(ctx, "use-pydantic-ai")
        assert "CANARY-Z42" in result


# ---------- Design tool tests ----------

class TestDesignToolBackends:
    @pytest.mark.asyncio
    async def test_search_design_system_returns_canary(self, bridge_deps):
        ctx = FakeCtx(bridge_deps)
        result = await search_design_system(ctx, "button")
        assert "CANARY-Z42" in result

    @pytest.mark.asyncio
    async def test_lookup_component_returns_canary(self, bridge_deps):
        ctx = FakeCtx(bridge_deps)
        result = await lookup_component(ctx, "button")
        assert "CANARY-Z42" in result

    @pytest.mark.asyncio
    async def test_recall_brand_guidelines_returns_canary(self, bridge_deps):
        ctx = FakeCtx(bridge_deps)
        result = await recall_brand_guidelines(ctx)
        assert "CANARY-Z42" in result
