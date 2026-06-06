"""Board department tool functions.

The Board is think-and-respond only. Its tools are limited to recall —
no file operations, no subprocess execution.
"""

from __future__ import annotations

import logging
from pydantic_ai import RunContext

from teams._types import BridgeDeps

log = logging.getLogger(__name__)


async def recall_past_decisions(ctx: RunContext[BridgeDeps], topic: str) -> str:
    """Recall past architectural or strategic decisions on a topic."""
    try:
        results = await ctx.deps.knowledge_search(f"decision:{topic}", limit=15)
        if not results:
            return f"No past decisions on: {topic}"
        return "\n\n".join(str(r) for r in results)
    except Exception as e:  # noqa: BLE001
        log.exception("recall_past_decisions failed")
        return f"ERROR: {e}"
