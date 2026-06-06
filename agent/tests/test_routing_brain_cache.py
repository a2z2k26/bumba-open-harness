"""Tests for routing brain LRU cache (#572 sub-bet 2)."""
from __future__ import annotations

from bridge.routing_brain import RoutingBrain, _LRUCache


def test_cache_hit_returns_same_decision():
    brain = RoutingBrain(cache_enabled=True)
    d1 = brain.decide("fix the failing test", modality="text")
    d2 = brain.decide("fix the failing test", modality="text")
    # Same message + modality → same routing decision
    assert d1.intent == d2.intent
    assert d1.environment == d2.environment


def test_cache_miss_on_different_message():
    brain = RoutingBrain(cache_enabled=True)
    d1 = brain.decide("fix test", modality="text")
    d2 = brain.decide("deploy to production", modality="text")
    # Different messages — both should succeed even if different decisions
    assert d1 is not d2


def test_cache_disabled():
    brain = RoutingBrain(cache_enabled=False)
    assert brain._cache is None
    # Should still work without cache
    d = brain.decide("test message")
    assert d is not None


def test_lru_cache_put_get():
    cache = _LRUCache(maxsize=3, ttl_s=3600)
    from bridge.routing_brain import RoutingDecision
    from bridge.intent_classifier import Intent
    decision = RoutingDecision(
        intent=Intent.BUILD,
        confidence=0.9,
        complexity=3,
        modality="text",
        environment="subagent",
        reason="test",
        department_hint=None,
    )
    cache.put("hello world", "text", decision)
    result = cache.get("hello world", "text")
    assert result is not None
    assert result.intent == Intent.BUILD


def test_lru_cache_miss_returns_none():
    cache = _LRUCache()
    assert cache.get("missing", "text") is None


def test_lru_cache_evicts_oldest():
    cache = _LRUCache(maxsize=2, ttl_s=3600)
    from bridge.routing_brain import RoutingDecision
    from bridge.intent_classifier import Intent

    def _decision():
        return RoutingDecision(
            intent=Intent.BUILD, confidence=0.9, complexity=3,
            modality="text", environment="subagent", reason="t", department_hint=None,
        )

    cache.put("msg1", "text", _decision())
    cache.put("msg2", "text", _decision())
    cache.put("msg3", "text", _decision())  # Should evict msg1

    assert cache.get("msg1", "text") is None
    assert cache.get("msg2", "text") is not None
    assert cache.get("msg3", "text") is not None


def test_lru_cache_ttl_expiry():
    """Test TTL expiry by directly manipulating the cache's internal timestamp."""
    import time as time_module
    cache = _LRUCache(maxsize=5, ttl_s=1)
    from bridge.routing_brain import RoutingDecision
    from bridge.intent_classifier import Intent

    decision = RoutingDecision(
        intent=Intent.BUILD, confidence=0.9, complexity=3,
        modality="text", environment="subagent", reason="t", department_hint=None,
    )
    cache.put("expiring", "text", decision)

    # Verify it's cached
    assert cache.get("expiring", "text") is not None

    # Manually back-date the cache entry by 2s to simulate TTL expiry
    key = cache._key("expiring", "text")
    old_decision, _ = cache._cache[key]
    cache._cache[key] = (old_decision, time_module.time() - 2)

    # Now the TTL of 1s is exceeded, so get() should return None
    assert cache.get("expiring", "text") is None


def test_lru_cache_clear():
    cache = _LRUCache()
    from bridge.routing_brain import RoutingDecision
    from bridge.intent_classifier import Intent
    d = RoutingDecision(
        intent=Intent.BUILD, confidence=0.9, complexity=3,
        modality="text", environment="subagent", reason="t", department_hint=None,
    )
    cache.put("test", "text", d)
    cache.clear()
    assert cache.get("test", "text") is None
