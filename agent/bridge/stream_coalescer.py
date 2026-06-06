"""Stream event coalescing for Discord message delivery.

Buffers text deltas and flushes as complete snapshots every 100ms.
Reduces Discord message edits from ~50 to ~5 per response.
"""
from __future__ import annotations

import asyncio
from typing import Callable, Awaitable


class StreamCoalescer:
    """Buffer text deltas, flush as full-so-far snapshots on a timer."""

    FLUSH_INTERVAL_MS: int = 100

    def __init__(self, on_flush: Callable[[str], Awaitable[None]]) -> None:
        self._buffer: list[str] = []
        self._full_text: str = ""
        self._flush_callback = on_flush
        self._timer: asyncio.TimerHandle | None = None
        self._finalized: bool = False

    def push(self, delta: str) -> None:
        """Append a text delta. Schedules a flush if not already scheduled."""
        if self._finalized:
            return
        self._full_text += delta
        self._buffer.append(delta)
        self._schedule_flush()

    async def flush(self) -> None:
        """Flush buffer to callback with full accumulated text."""
        if not self._buffer:
            return
        self._buffer.clear()
        await self._flush_callback(self._full_text)

    async def finalize(self) -> None:
        """Force an immediate final flush and mark stream complete."""
        self._cancel_timer()
        self._finalized = True
        if self._buffer:
            self._buffer.clear()
            await self._flush_callback(self._full_text)

    def reset(self) -> None:
        """Reset all state (for reuse across messages)."""
        self._cancel_timer()
        self._buffer.clear()
        self._full_text = ""
        self._finalized = False

    def _schedule_flush(self) -> None:
        if self._timer is not None:
            return
        try:
            loop = asyncio.get_running_loop()
            self._timer = loop.call_later(
                self.FLUSH_INTERVAL_MS / 1000,
                lambda: asyncio.ensure_future(self._do_flush()),
            )
        except RuntimeError:
            pass  # No running loop (sync context / unit test) — flush called manually

    def _cancel_timer(self) -> None:
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None

    async def _do_flush(self) -> None:
        self._timer = None
        await self.flush()
