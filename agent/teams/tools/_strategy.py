"""Strategy department tool functions."""

from __future__ import annotations

import logging

from pydantic_ai import RunContext

from teams._handoff import HandoffEnvelope, store_handoff
from teams._types import BridgeDeps

log = logging.getLogger(__name__)


async def search_market_data(ctx: RunContext[BridgeDeps], query: str) -> str:
    """Search for market research data matching the query."""
    try:
        results = await ctx.deps.knowledge_search(query, limit=10)
        if not results:
            return f"No results for: {query}"
        return "\n\n".join(str(r) for r in results)
    except Exception as e:  # noqa: BLE001
        log.exception("search_market_data failed")
        return f"ERROR: {e}"


async def analyze_competitor(ctx: RunContext[BridgeDeps], competitor: str) -> str:
    """Look up stored notes about a specific competitor."""
    return await search_market_data(ctx, f"competitor:{competitor}")


async def recall_decision(ctx: RunContext[BridgeDeps], topic: str) -> str:
    """Recall a past architectural or product decision from shared memory."""
    try:
        result = await ctx.deps.memory_store.get(f"decision:{topic}")
        return str(result) if result else f"No decision found for: {topic}"
    except Exception as e:  # noqa: BLE001
        log.exception("recall_decision failed")
        return f"ERROR: {e}"


async def initiate_handoff(
    ctx: RunContext[BridgeDeps], to_department: str, task: str, findings: str
) -> str:
    """Create a HandoffEnvelope and store it in shared memory.

    Returns a confirmation message containing the correlation_id that the
    receiving department will use to load the envelope via ``continue_handoff``.
    """
    envelope = HandoffEnvelope(
        from_department=ctx.deps.department,
        to_department=to_department,
        task=task,
        findings=findings,
    )
    await store_handoff(envelope, ctx.deps.memory_store)
    return (
        f"Handoff initiated to {to_department}. "
        f"correlation_id={envelope.correlation_id}"
    )
