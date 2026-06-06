"""Tests for Z4 handoff event emission (sprint E-O.5).

Verifies that store_handoff and load_handoff emit the correct event types:
  z4.handoff.created   — when a handoff is stored
  z4.handoff.consumed  — when a valid, non-expired handoff is loaded
  z4.handoff.expired   — when a handoff with an expiry in the past is loaded
  z4.handoff.failed    — when deserialisation fails
"""
from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import MagicMock


from teams._handoff import HandoffEnvelope, load_handoff, store_handoff


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class _MemoryStore:
    """In-process dict that mimics the async KV contract."""

    def __init__(self) -> None:
        self._data: dict[str, str] = {}

    async def set(self, key: str, value: str) -> None:
        self._data[key] = value

    async def get(self, key: str) -> str | None:
        return self._data.get(key)


def _make_bus() -> MagicMock:
    """Return a MagicMock that tracks publish calls."""
    bus = MagicMock()
    bus.publish = MagicMock()
    return bus


def _envelope(**kwargs: Any) -> HandoffEnvelope:
    defaults = dict(
        from_department="strategy",
        to_department="ops",
        task="Migrate infra to multi-region",
        findings="Current setup is single-AZ.",
    )
    defaults.update(kwargs)
    return HandoffEnvelope(**defaults)


def _expired_envelope(**kwargs: Any) -> HandoffEnvelope:
    """Return an envelope whose TTL is negative so expires_at is in the past."""
    defaults = dict(
        from_department="strategy",
        to_department="ops",
        task="Migrate infra to multi-region",
        findings="Current setup is single-AZ.",
        ttl_hours=-1.0,  # expires 1h before created_at -> immediately expired
    )
    defaults.update(kwargs)
    return HandoffEnvelope(**defaults)


# ---------------------------------------------------------------------------
# store_handoff
# ---------------------------------------------------------------------------


class TestStoreHandoffEvents:
    def test_emits_created_event(self) -> None:
        """store_handoff publishes z4.handoff.created with expected payload."""
        store = _MemoryStore()
        bus = _make_bus()
        env = _envelope()

        asyncio.run(store_handoff(env, store, event_bus=bus))

        bus.publish.assert_called_once()
        event_type, payload = bus.publish.call_args[0]
        assert event_type == "z4.handoff.created"
        assert payload["correlation_id"] == env.correlation_id
        assert payload["from"] == "strategy"
        assert payload["to"] == "ops"

    def test_no_bus_does_not_raise(self) -> None:
        """store_handoff without an event_bus is a no-op (no error)."""
        store = _MemoryStore()
        env = _envelope()
        asyncio.run(store_handoff(env, store))
        # Without an event bus the call must still complete its storage
        # side: the envelope lands under the correlation_id key.
        assert f"handoff:{env.correlation_id}" in store._data

    def test_no_memory_store_does_not_raise(self) -> None:
        """store_handoff with memory_store=None is a no-op."""
        bus = _make_bus()
        env = _envelope()
        asyncio.run(store_handoff(env, None, event_bus=bus))
        bus.publish.assert_not_called()

    def test_bus_error_does_not_raise(self) -> None:
        """A broken event bus must never propagate out of store_handoff."""
        store = _MemoryStore()
        bus = MagicMock()
        bus.publish.side_effect = RuntimeError("bus down")
        env = _envelope()
        asyncio.run(store_handoff(env, store, event_bus=bus))
        # The bus.publish error was swallowed (no exception out of
        # store_handoff) AND the storage side still completed.
        bus.publish.assert_called_once()
        assert f"handoff:{env.correlation_id}" in store._data


# ---------------------------------------------------------------------------
# load_handoff — consumed
# ---------------------------------------------------------------------------


class TestLoadHandoffConsumedEvent:
    def test_emits_consumed_for_valid_handoff(self) -> None:
        """load_handoff publishes z4.handoff.consumed for a valid envelope."""
        store = _MemoryStore()
        bus = _make_bus()
        env = _envelope()

        asyncio.run(store_handoff(env, store))  # no bus on store
        result = asyncio.run(load_handoff(env.correlation_id, store, event_bus=bus))

        assert result is not None
        assert result.correlation_id == env.correlation_id

        bus.publish.assert_called_once()
        event_type, payload = bus.publish.call_args[0]
        assert event_type == "z4.handoff.consumed"
        assert payload["correlation_id"] == env.correlation_id
        assert payload["from"] == "strategy"
        assert payload["to"] == "ops"

    def test_returns_none_when_not_found(self) -> None:
        """load_handoff returns None and emits nothing when key is absent."""
        store = _MemoryStore()
        bus = _make_bus()
        result = asyncio.run(load_handoff("nonexistent-id", store, event_bus=bus))
        assert result is None
        bus.publish.assert_not_called()


# ---------------------------------------------------------------------------
# load_handoff — expired
# ---------------------------------------------------------------------------


class TestLoadHandoffExpiredEvent:
    def test_emits_expired_for_past_expiry(self) -> None:
        """load_handoff publishes z4.handoff.expired when ttl_hours makes expiry past."""
        env = _expired_envelope()
        store = _MemoryStore()
        bus = _make_bus()

        asyncio.run(store_handoff(env, store))
        result = asyncio.run(load_handoff(env.correlation_id, store, event_bus=bus))

        # Still returns the envelope (caller decides what to do with expired)
        assert result is not None
        bus.publish.assert_called_once()
        event_type, payload = bus.publish.call_args[0]
        assert event_type == "z4.handoff.expired"
        assert payload["correlation_id"] == env.correlation_id
        assert "expires_at" in payload

    def test_does_not_emit_expired_for_future_expiry(self) -> None:
        """load_handoff publishes consumed (not expired) for a future-expiry envelope."""
        env = _envelope(ttl_hours=24.0)  # expires in 24h — not expired
        store = _MemoryStore()
        bus = _make_bus()

        asyncio.run(store_handoff(env, store))
        asyncio.run(load_handoff(env.correlation_id, store, event_bus=bus))

        event_type = bus.publish.call_args[0][0]
        assert event_type == "z4.handoff.consumed"


# ---------------------------------------------------------------------------
# load_handoff — failed
# ---------------------------------------------------------------------------


class TestLoadHandoffFailedEvent:
    def test_emits_failed_for_corrupt_json(self) -> None:
        """load_handoff publishes z4.handoff.failed when the stored value is corrupt."""
        store = _MemoryStore()
        bus = _make_bus()
        cid = "bad-id-123"

        asyncio.run(store.set(f"handoff:{cid}", "NOT-VALID-JSON{{{{"))

        result = asyncio.run(load_handoff(cid, store, event_bus=bus))

        assert result is None
        bus.publish.assert_called_once()
        event_type, payload = bus.publish.call_args[0]
        assert event_type == "z4.handoff.failed"
        assert payload["correlation_id"] == cid
        assert "reason" in payload
