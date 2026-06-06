"""Thread-safe Agent instance cache for module-global reuse (Phase 1 #2290).

PydanticAI's documented design intent is that Agent objects are instantiated
once and reused across invocations. Today bumba-open-harness rebuilds the chief and
specialist Agents every team run, which is counter to that intent AND
prevents the message_history reuse pattern that Phase 2+ depends on.

This module is infrastructure only. The cache is populated by callers
(`build_manager_agent`, `build_employee_agents`) via `get_or_build`; on a
key miss the builder callback constructs the Agent and the cache stores it.
On a key hit the cached instance is returned directly.

Invalidation is explicit. The cache does NOT TTL or LRU-evict — per-Agent
memory is small and the cache is bounded by (team_count × agent_count),
which is finite and stable (~50 agents across 6 teams as of 2026-05-18).
"""
from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass
from typing import TypeVar

from pydantic_ai import Agent

from teams._types import BridgeDeps

T = TypeVar("T")

# Cache key. `team_name` matches the YAML stem (`board`, `design`, etc.);
# `agent_name` matches the `name:` field on chief or worker.
_CacheKey = tuple[str, str]


@dataclass(frozen=True)
class CacheStats:
    """Read-only snapshot of cache state, for observability."""
    size: int
    hits: int
    misses: int


class AgentCache:
    """Process-local registry of constructed PydanticAI Agent instances.

    Thread-safe. Backed by a `dict` + a `threading.Lock`. Construction is
    racy-but-correct: if two threads call `get_or_build(key, builder)`
    concurrently with a cold key, the builder MAY run twice but only one
    result is stored. The wasted construction is not visible to callers.
    """

    def __init__(self) -> None:
        self._cache: dict[_CacheKey, Agent[BridgeDeps, str]] = {}
        self._lock = threading.Lock()
        self._hits = 0
        self._misses = 0

    def get_or_build(
        self,
        team_name: str,
        agent_name: str,
        builder: Callable[[], Agent[BridgeDeps, str]],
    ) -> Agent[BridgeDeps, str]:
        """Return the cached Agent for (team_name, agent_name), building it
        via `builder()` on cache miss.

        The builder is invoked OUTSIDE the lock to avoid blocking other
        callers during the (potentially slow) Agent construction. This means
        two concurrent misses on the same key may both invoke the builder;
        the second insertion is a no-op (first writer wins).
        """
        key = (team_name, agent_name)
        with self._lock:
            cached = self._cache.get(key)
            if cached is not None:
                self._hits += 1
                return cached
            self._misses += 1

        # Build outside the lock — Agent construction may do I/O
        # (expertise file read, system-prompt assembly).
        agent = builder()

        with self._lock:
            # First-writer-wins. If another thread inserted while we were
            # building, return that instance and discard ours.
            existing = self._cache.get(key)
            if existing is not None:
                return existing
            self._cache[key] = agent
            return agent

    def invalidate(self, team_name: str) -> int:
        """Remove all cached Agents for the given team. Returns the count
        evicted. Use during config reload or test isolation.
        """
        with self._lock:
            keys_to_remove = [k for k in self._cache if k[0] == team_name]
            for k in keys_to_remove:
                del self._cache[k]
            return len(keys_to_remove)

    def invalidate_all(self) -> int:
        """Clear the entire cache. Returns total count evicted."""
        with self._lock:
            n = len(self._cache)
            self._cache.clear()
            return n

    def stats(self) -> CacheStats:
        """Snapshot for observability."""
        with self._lock:
            return CacheStats(
                size=len(self._cache),
                hits=self._hits,
                misses=self._misses,
            )


# Module-global singleton. Production callers (`build_manager_agent`,
# `build_employee_agents`) use this instance. Tests construct their own
# `AgentCache()` instance for isolation.
GLOBAL_AGENT_CACHE: AgentCache = AgentCache()
