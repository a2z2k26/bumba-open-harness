"""TMUX pre-warm pool — pre-warm 1-2 idle tmux agent sessions.

Sprint S14: Maintains a pool of warm tmux sessions so the first TMUX
WorkOrder drops from ~15s spin-up to <1s.

Pool contract:
- fill() spawns sessions up to target_size
- acquire() returns a warm slot (or None if pool is empty)
- After acquire(), fill() is triggered asynchronously to refill
- shutdown() kills all warm sessions
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass

log = logging.getLogger(__name__)

DEFAULT_POOL_SIZE = 2


@dataclass
class WarmSlot:
    """A pre-warmed tmux agent session ready for immediate use."""

    session_name: str
    agent_id: str


class TmuxPrewarmPool:
    """Pool of pre-warmed tmux agent sessions.

    Designed to be injected into TmuxExecutor, which calls acquire()
    before falling back to cold spawn.
    """

    def __init__(
        self,
        *,
        tmux_mgr: object | None = None,
        target_size: int = DEFAULT_POOL_SIZE,
    ) -> None:
        self._mgr = tmux_mgr
        self._target = target_size
        self._warm: list[WarmSlot] = []
        self._lock = asyncio.Lock()
        self._filling = False

    async def fill(self) -> None:
        """Spawn idle sessions until pool is at target_size."""
        if self._mgr is None:
            return
        async with self._lock:
            while len(self._warm) < self._target:
                slot = await self._spawn_warm()
                if slot is None:
                    break
                self._warm.append(slot)
                log.info(
                    "TMUX pre-warm pool: %d/%d slots ready",
                    len(self._warm), self._target,
                )

    async def _spawn_warm(self) -> WarmSlot | None:
        """Spawn a single idle tmux session.

        Uses spawn_idle_session if available, else falls back to spawn_agent
        with a sentinel prompt.
        """
        try:
            spawn_idle = getattr(self._mgr, "spawn_idle_session", None)
            if spawn_idle is not None:
                result = await spawn_idle()
            else:
                result = await self._mgr.spawn_agent("idle: awaiting task")  # type: ignore[attr-defined]

            if isinstance(result, str):
                log.warning("TMUX pre-warm: spawn failed: %s", result)
                return None

            session_name = getattr(result, "session_name", getattr(result, "agent_id", ""))
            agent_id = getattr(result, "agent_id", session_name)
            return WarmSlot(session_name=session_name, agent_id=agent_id)
        except Exception:
            log.exception("TMUX pre-warm: spawn_warm exception")
            return None

    async def acquire(self) -> WarmSlot | None:
        """Take a warm slot from the pool, returning None if empty.

        After acquiring, triggers an async refill.
        """
        async with self._lock:
            if not self._warm:
                return None
            slot = self._warm.pop(0)

        log.info("TMUX pre-warm pool: acquired slot %s (pool now %d)", slot.agent_id[:8], len(self._warm))
        # Re-fill asynchronously (don't await — caller should not wait)
        asyncio.create_task(self.fill())
        return slot

    async def shutdown(self) -> None:
        """Kill all warm sessions and clear the pool."""
        async with self._lock:
            count = len(self._warm)
            if self._mgr is not None:
                for slot in self._warm:
                    try:
                        await self._mgr.kill_agent(slot.agent_id)  # type: ignore[attr-defined]
                    except Exception:
                        log.warning("Could not kill warm slot %s", slot.agent_id[:8])
            self._warm.clear()
        if count:
            log.info("TMUX pre-warm pool: shut down %d warm slots", count)

    @property
    def size(self) -> int:
        """Current pool size (not thread-safe — for monitoring only)."""
        return len(self._warm)

    @property
    def target(self) -> int:
        """Target pool size."""
        return self._target
