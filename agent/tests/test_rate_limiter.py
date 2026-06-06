"""Tests for rate_limiter.py: TokenBucket rate limiter."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from bridge.rate_limiter import TokenBucket


# ---------------------------------------------------------------------------
# Initial state
# ---------------------------------------------------------------------------

def test_initial_full_capacity():
    """New bucket starts at full capacity."""
    bucket = TokenBucket(capacity=10.0, refill_rate=0.5)
    status = bucket.get_status()
    assert status["tokens"] == 10.0
    assert status["capacity"] == 10.0


# ---------------------------------------------------------------------------
# check()
# ---------------------------------------------------------------------------

def test_check_allowed_when_full():
    """check() on a full bucket returns allowed=True, wait=0."""
    bucket = TokenBucket(capacity=5.0, refill_rate=1.0)
    allowed, wait = bucket.check()
    assert allowed is True
    assert wait == 0.0


# ---------------------------------------------------------------------------
# consume()
# ---------------------------------------------------------------------------

def test_consume_reduces_tokens():
    """consume() reduces token count."""
    bucket = TokenBucket(capacity=5.0, refill_rate=1.0)
    allowed, wait = bucket.consume(3.0)
    assert allowed is True
    assert wait == 0.0

    status = bucket.get_status()
    assert status["tokens"] == pytest.approx(2.0, abs=0.1)
    assert status["total_allowed"] == 1


def test_consume_denied_when_empty():
    """consume() denied when insufficient tokens."""
    bucket = TokenBucket(capacity=2.0, refill_rate=0.5)
    # Drain the bucket
    bucket.consume(2.0)

    allowed, wait = bucket.consume(1.0)
    assert allowed is False
    assert wait > 0.0
    assert bucket.get_status()["total_denied"] == 1


# ---------------------------------------------------------------------------
# Refill over time
# ---------------------------------------------------------------------------

def test_refill_over_time():
    """Tokens refill based on elapsed time and refill_rate."""
    bucket = TokenBucket(capacity=10.0, refill_rate=2.0)

    # Drain fully
    bucket._tokens = 0.0
    start_time = bucket._last_refill

    # Advance time by 3 seconds -> should add 6 tokens (2.0 * 3)
    with patch("bridge.rate_limiter.time.monotonic", return_value=start_time + 3.0):
        allowed, wait = bucket.check()

    assert allowed is True
    assert bucket._tokens == pytest.approx(6.0, abs=0.01)


# ---------------------------------------------------------------------------
# wait_and_consume() — async
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_wait_and_consume():
    """wait_and_consume blocks until tokens are available, then consumes."""
    bucket = TokenBucket(capacity=5.0, refill_rate=100.0)  # fast refill
    # Drain the bucket
    bucket.consume(5.0)

    # With refill_rate=100, refill is nearly instant
    await bucket.wait_and_consume(1.0)

    # Should have consumed successfully (total_allowed incremented)
    assert bucket.get_status()["total_allowed"] == 2  # 1 from drain + 1 from wait


# ---------------------------------------------------------------------------
# on_rate_limited()
# ---------------------------------------------------------------------------

def test_on_rate_limited_reduces_refill():
    """on_rate_limited reduces refill_rate by 20%."""
    bucket = TokenBucket(capacity=10.0, refill_rate=1.0)
    original_rate = bucket._refill_rate

    bucket.on_rate_limited()
    assert bucket._refill_rate == pytest.approx(original_rate * 0.8)


def test_on_rate_limited_drains_bucket():
    """on_rate_limited drains all tokens to 0."""
    bucket = TokenBucket(capacity=10.0, refill_rate=1.0)
    assert bucket._tokens == 10.0

    bucket.on_rate_limited()
    assert bucket._tokens == 0.0


# ---------------------------------------------------------------------------
# on_success()
# ---------------------------------------------------------------------------

def test_on_success_restores_refill():
    """on_success slowly restores refill_rate toward original."""
    bucket = TokenBucket(capacity=10.0, refill_rate=0.5)
    original_rate = bucket._capacity / 20.0  # 0.5

    # Reduce the rate first
    bucket._refill_rate = 0.1

    bucket.on_success()
    assert bucket._refill_rate == pytest.approx(0.1 * 1.05)
    assert bucket._refill_rate < original_rate


# ---------------------------------------------------------------------------
# Capacity cap
# ---------------------------------------------------------------------------

def test_capacity_cap_on_refill():
    """Tokens never exceed capacity after refill."""
    bucket = TokenBucket(capacity=5.0, refill_rate=100.0)

    start_time = bucket._last_refill

    # Advance time by 10 seconds -> would add 1000 tokens, but capped at 5
    with patch("bridge.rate_limiter.time.monotonic", return_value=start_time + 10.0):
        bucket._refill()

    assert bucket._tokens == pytest.approx(5.0)


# ---------------------------------------------------------------------------
# get_status()
# ---------------------------------------------------------------------------

def test_get_status():
    """get_status returns all bucket metrics."""
    bucket = TokenBucket(capacity=8.0, refill_rate=0.5)
    bucket.consume(3.0)
    bucket.consume(100.0)  # denied

    status = bucket.get_status()
    assert status["capacity"] == 8.0
    assert status["total_allowed"] == 1
    assert status["total_denied"] == 1
    assert "tokens" in status
    assert "refill_rate" in status
