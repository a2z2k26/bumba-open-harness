"""Handoff TTL tests (sprint B-S.1)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from freezegun import freeze_time

from teams._handoff import HandoffEnvelope


def test_envelope_default_ttl() -> None:
    env = HandoffEnvelope(from_department="strategy", to_department="ops", task="x")
    assert env.ttl_hours == 24.0
    # expires_at is created_at + 24h
    created = datetime.fromisoformat(env.created_at)
    expires = datetime.fromisoformat(env.expires_at)
    # Both should be tz-aware
    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    delta = (expires - created).total_seconds()
    assert 86390 < delta < 86410, f"Expected ~24h delta, got {delta}s"


def test_envelope_custom_ttl() -> None:
    env = HandoffEnvelope(
        from_department="strategy", to_department="ops", task="x", ttl_hours=1.0
    )
    created = datetime.fromisoformat(env.created_at)
    expires = datetime.fromisoformat(env.expires_at)
    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    delta = (expires - created).total_seconds()
    assert 3590 < delta < 3610, f"Expected ~1h delta, got {delta}s"


def test_envelope_is_not_expired_when_fresh() -> None:
    env = HandoffEnvelope(from_department="s", to_department="o", task="x", ttl_hours=1.0)
    assert env.is_expired() is False


def test_envelope_is_expired_for_tiny_ttl() -> None:
    """A very small TTL (~0.001h = ~3.6s) should expire quickly."""
    with freeze_time("2026-05-12 12:00:00") as frozen:
        env = HandoffEnvelope(
            from_department="s", to_department="o", task="x", ttl_hours=0.001  # ~3.6s
        )
        frozen.tick(timedelta(seconds=4))
        assert env.is_expired() is True


def test_envelope_round_trip_preserves_expiry() -> None:
    """JSON round-trip must preserve ttl_hours and recompute expires_at correctly."""
    env = HandoffEnvelope(
        from_department="strategy", to_department="ops", task="audit", ttl_hours=2.0
    )
    restored = HandoffEnvelope.from_json(env.to_json())
    assert restored.ttl_hours == 2.0
    assert restored.expires_at == env.expires_at


def test_continue_handoff_rejects_expired_envelope() -> None:
    """continue_handoff in _ops.py must return an expiry error for stale envelopes."""
    from unittest.mock import AsyncMock, MagicMock

    import asyncio

    from teams.tools._ops import continue_handoff
    from tests.test_teams.conftest import make_deps

    # Create an envelope that's already expired. freeze_time advances the
    # clock past the TTL without wall-clock waiting.
    with freeze_time("2026-05-12 12:00:00") as frozen:
        expired_env = HandoffEnvelope(
            from_department="strategy",
            to_department="ops",
            task="stale task",
            ttl_hours=0.0001,  # expires essentially immediately
        )
        frozen.tick(timedelta(seconds=1))  # ensure it's expired

        # Wire up a memory store that returns the expired envelope
        store: dict[str, str] = {}
        memory_mock = AsyncMock()
        memory_mock.set.side_effect = lambda k, v: store.__setitem__(k, v)
        memory_mock.get.side_effect = lambda k: store.get(k)

        store[f"handoff:{expired_env.correlation_id}"] = expired_env.to_json()

        deps = make_deps(memory_store=memory_mock)
        ctx = MagicMock()
        ctx.deps = deps

        result = asyncio.run(
            continue_handoff(ctx, expired_env.correlation_id)
        )

    assert "expired" in result.lower(), f"Expected expiry message, got: {result!r}"
    assert "do not act" in result.lower() or "fresh" in result.lower(), (
        f"Expected guidance not to act on expired handoff, got: {result!r}"
    )
