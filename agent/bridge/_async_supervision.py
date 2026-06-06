"""Supervision helper for fire-and-forget asyncio tasks.

Replaces bare ``asyncio.create_task(coro, name=...)`` calls so that an
un-retained task at least logs its failure rather than swallowing it.
"""

from __future__ import annotations

import asyncio
import logging

log = logging.getLogger(__name__)


def spawn_background_task(
    coro,
    *,
    name: str,
    logger: logging.Logger = log,
) -> asyncio.Task:
    """Create a fire-and-forget task whose exceptions are logged.

    The returned Task should still be retained by the caller if the
    caller wants ownership; this helper guarantees that an un-retained
    task at least logs its failure rather than swallowing it.
    """
    task = asyncio.create_task(coro, name=name)

    def _done(t: asyncio.Task) -> None:
        if t.cancelled():
            logger.info("Background task %s was cancelled", name)
            return
        exc = t.exception()
        if exc is not None:
            logger.exception(
                "Background task %s failed: %s", name, exc, exc_info=exc
            )

    task.add_done_callback(_done)
    return task
