"""Tests for the AgentCache infrastructure (Phase 1 #2290).

Foundation-only sprint: the cache is exercised here in isolation. Wiring into
`build_manager_agent` / `build_employee_agents` lands in sprints A.02 and A.03.
"""

from __future__ import annotations

import threading
import time
from unittest.mock import MagicMock

from pydantic_ai import Agent

from teams._agent_cache import AgentCache, CacheStats


def _builder_returning(name: str):
    """Builder closure that returns a uniquely-identifiable mock Agent."""
    def _build():
        m = MagicMock(spec=Agent)
        m._builder_name = name  # marker for assertions
        return m
    return _build


def test_get_or_build_on_miss_invokes_builder_and_caches():
    cache = AgentCache()
    builder = _builder_returning("ceo-v1")
    a1 = cache.get_or_build("board", "board-ceo", builder)
    assert a1._builder_name == "ceo-v1"
    assert cache.stats().misses == 1
    assert cache.stats().hits == 0
    assert cache.stats().size == 1


def test_get_or_build_on_hit_returns_cached_does_not_invoke_builder():
    cache = AgentCache()
    builder = MagicMock(side_effect=_builder_returning("ceo"))
    a1 = cache.get_or_build("board", "board-ceo", builder)
    a2 = cache.get_or_build("board", "board-ceo", builder)
    assert a1 is a2  # same instance
    assert builder.call_count == 1  # builder NOT re-invoked
    assert cache.stats().hits == 1
    assert cache.stats().misses == 1


def test_different_agents_same_team_are_distinct_entries():
    cache = AgentCache()
    a = cache.get_or_build("board", "board-ceo", _builder_returning("ceo"))
    b = cache.get_or_build("board", "board-contrarian", _builder_returning("contrarian"))
    assert a is not b
    assert cache.stats().size == 2


def test_same_agent_name_different_team_are_distinct_entries():
    cache = AgentCache()
    a = cache.get_or_build("design", "design-chief", _builder_returning("design"))
    b = cache.get_or_build("qa", "design-chief", _builder_returning("qa"))  # hypothetical collision
    assert a is not b


def test_invalidate_team_removes_all_agents_for_that_team():
    cache = AgentCache()
    cache.get_or_build("board", "board-ceo", _builder_returning("ceo"))
    cache.get_or_build("board", "board-contrarian", _builder_returning("contrarian"))
    cache.get_or_build("design", "design-chief", _builder_returning("design"))
    evicted = cache.invalidate("board")
    assert evicted == 2
    assert cache.stats().size == 1  # only design-chief remains


def test_invalidate_team_with_no_matching_entries_returns_zero():
    cache = AgentCache()
    cache.get_or_build("board", "board-ceo", _builder_returning("ceo"))
    evicted = cache.invalidate("nonexistent-team")
    assert evicted == 0
    assert cache.stats().size == 1


def test_invalidate_all_clears_cache():
    cache = AgentCache()
    cache.get_or_build("board", "board-ceo", _builder_returning("ceo"))
    cache.get_or_build("design", "design-chief", _builder_returning("design"))
    evicted = cache.invalidate_all()
    assert evicted == 2
    assert cache.stats().size == 0


def test_concurrent_get_or_build_same_key_returns_consistent_instance():
    """Concurrent misses may invoke the builder twice (acceptable), but the
    final cached instance is consistent across threads.
    """
    cache = AgentCache()
    builder_call_count = [0]
    builder_lock = threading.Lock()

    def slow_builder():
        with builder_lock:
            builder_call_count[0] += 1
        time.sleep(0.05)  # simulate slow Agent construction
        m = MagicMock(spec=Agent)
        m._instance_id = id(m)
        return m

    results = []
    barrier = threading.Barrier(10)

    def worker():
        barrier.wait()
        results.append(cache.get_or_build("board", "board-ceo", slow_builder))

    threads = [threading.Thread(target=worker) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # All threads received the same cached instance (first-writer-wins).
    assert len(set(id(r) for r in results)) == 1, "All callers should receive same Agent"
    # Builder MAY have been called more than once but cache state is consistent.
    assert cache.stats().size == 1


def test_stats_returns_frozen_snapshot():
    cache = AgentCache()
    cache.get_or_build("board", "board-ceo", _builder_returning("ceo"))
    s = cache.stats()
    assert isinstance(s, CacheStats)
    # Verify it's a snapshot, not a live view: mutating cache after stats()
    # doesn't change the returned stats object.
    cache.get_or_build("design", "design-chief", _builder_returning("design"))
    assert s.size == 1  # original snapshot unchanged


def test_global_singleton_is_importable():
    from teams._agent_cache import GLOBAL_AGENT_CACHE
    assert isinstance(GLOBAL_AGENT_CACHE, AgentCache)
