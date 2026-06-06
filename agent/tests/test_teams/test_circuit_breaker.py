"""Tests for Z4.4.4 — Per-department circuit breakers."""
from __future__ import annotations

import time
from unittest.mock import patch

import pytest

from teams._circuit import (
    CircuitBreaker,
    CircuitBreakerRegistry,
    CircuitOpenError,
    CircuitState,
)


# ---------------------------------------------------------------------------
# CircuitBreaker tests
# ---------------------------------------------------------------------------

def test_circuit_starts_closed():
    """Test 1: Circuit starts in CLOSED state."""
    cb = CircuitBreaker(department="qa")
    assert cb.state == CircuitState.CLOSED


def test_before_call_succeeds_when_closed():
    """Test 2: before_call() succeeds (no exception) when circuit is CLOSED."""
    cb = CircuitBreaker(department="qa")
    cb.before_call()  # must not raise


def test_record_failure_threshold_opens_circuit():
    """Test 3: record_failure() x threshold opens circuit."""
    cb = CircuitBreaker(department="qa", failure_threshold=3)
    assert cb.state == CircuitState.CLOSED

    cb.record_failure()
    assert cb.state == CircuitState.CLOSED
    cb.record_failure()
    assert cb.state == CircuitState.CLOSED
    cb.record_failure()  # 3rd failure hits threshold
    assert cb.state == CircuitState.OPEN


def test_before_call_raises_when_open():
    """Test 4: before_call() raises CircuitOpenError when circuit is OPEN."""
    cb = CircuitBreaker(department="qa", failure_threshold=1)
    cb.record_failure()  # opens immediately at threshold=1
    assert cb.state == CircuitState.OPEN

    with pytest.raises(CircuitOpenError, match="qa"):
        cb.before_call()


def test_record_success_resets_to_closed():
    """Test 5: record_success() resets failure count and closes circuit."""
    cb = CircuitBreaker(department="eng", failure_threshold=3)
    cb.record_failure()
    cb.record_failure()
    assert cb._consecutive_failures == 2

    cb.record_success()
    assert cb.state == CircuitState.CLOSED
    assert cb._consecutive_failures == 0
    assert cb._opened_at is None


def test_half_open_transition_after_cooldown():
    """Test 6: Circuit transitions OPEN→HALF_OPEN after cooldown elapses."""
    cb = CircuitBreaker(department="ops", failure_threshold=1, cooldown_seconds=30.0)
    cb.record_failure()
    assert cb._state == CircuitState.OPEN

    # Simulate time passing beyond cooldown
    with patch("teams._circuit.time.monotonic", return_value=cb._opened_at + 31.0):
        assert cb.state == CircuitState.HALF_OPEN


def test_failure_in_half_open_reopens_immediately():
    """Test 7: A failure in HALF_OPEN re-opens the circuit immediately."""
    cb = CircuitBreaker(department="design", failure_threshold=3, cooldown_seconds=30.0)
    # Force to HALF_OPEN
    cb._state = CircuitState.HALF_OPEN
    cb._opened_at = time.monotonic()

    cb.record_failure()
    # Should re-open even though failure_threshold (3) not yet reached
    assert cb._state == CircuitState.OPEN


def test_reset_force_closes_circuit():
    """Test 8: reset() force-closes the circuit regardless of state."""
    cb = CircuitBreaker(department="strategy", failure_threshold=1)
    cb.record_failure()
    assert cb._state == CircuitState.OPEN

    cb.reset()
    assert cb.state == CircuitState.CLOSED
    assert cb._consecutive_failures == 0
    assert cb._opened_at is None


# ---------------------------------------------------------------------------
# CircuitBreakerRegistry tests
# ---------------------------------------------------------------------------

def test_registry_get_returns_same_instance():
    """Test 9: CircuitBreakerRegistry.get() returns the same instance for the same department."""
    registry = CircuitBreakerRegistry()
    cb1 = registry.get("qa")
    cb2 = registry.get("qa")
    assert cb1 is cb2


def test_registry_reset_all_resets_all_breakers():
    """Test 10: CircuitBreakerRegistry.reset_all() resets all registered breakers."""
    registry = CircuitBreakerRegistry(failure_threshold=1)
    qa_cb = registry.get("qa")
    eng_cb = registry.get("eng")

    qa_cb.record_failure()
    eng_cb.record_failure()
    assert qa_cb._state == CircuitState.OPEN
    assert eng_cb._state == CircuitState.OPEN

    registry.reset_all()
    assert qa_cb.state == CircuitState.CLOSED
    assert eng_cb.state == CircuitState.CLOSED
