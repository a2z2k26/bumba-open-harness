"""Tests for lifecycle.py: SubprocessLifecycle state machine."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from bridge.lifecycle import State, StateTimeouts, SubprocessLifecycle


# ---------------------------------------------------------------------------
# Initial state
# ---------------------------------------------------------------------------

def test_initial_state_idle():
    """New lifecycle starts in IDLE state."""
    lc = SubprocessLifecycle()
    assert lc.state == State.IDLE


# ---------------------------------------------------------------------------
# Valid transitions
# ---------------------------------------------------------------------------

def test_valid_transition_idle_to_spawning():
    """IDLE -> SPAWNING is valid."""
    lc = SubprocessLifecycle()
    lc.transition(State.SPAWNING)
    assert lc.state == State.SPAWNING


def test_valid_transition_spawning_to_active():
    """SPAWNING -> ACTIVE is valid."""
    lc = SubprocessLifecycle()
    lc.transition(State.SPAWNING)
    lc.transition(State.ACTIVE)
    assert lc.state == State.ACTIVE


def test_valid_transition_active_to_completing():
    """ACTIVE -> COMPLETING is valid."""
    lc = SubprocessLifecycle()
    lc.transition(State.SPAWNING)
    lc.transition(State.ACTIVE)
    lc.transition(State.COMPLETING)
    assert lc.state == State.COMPLETING


def test_valid_transition_completing_to_completed():
    """COMPLETING -> COMPLETED is valid."""
    lc = SubprocessLifecycle()
    lc.transition(State.SPAWNING)
    lc.transition(State.ACTIVE)
    lc.transition(State.COMPLETING)
    lc.transition(State.COMPLETED)
    assert lc.state == State.COMPLETED


# ---------------------------------------------------------------------------
# Invalid transitions
# ---------------------------------------------------------------------------

def test_invalid_transition_raises():
    """Invalid transition raises ValueError."""
    lc = SubprocessLifecycle()
    with pytest.raises(ValueError, match="Invalid transition"):
        lc.transition(State.ACTIVE)  # IDLE -> ACTIVE not allowed


# ---------------------------------------------------------------------------
# Timeouts
# ---------------------------------------------------------------------------

def test_check_timeout_spawning():
    """Timeout detected when SPAWNING exceeds its limit."""
    timeouts = StateTimeouts(spawning=5.0, active=100.0, completing=10.0)
    lc = SubprocessLifecycle(timeouts=timeouts)
    lc.transition(State.SPAWNING)

    # Mock time so state_duration > 5s
    entered_at = lc._state_entered_at
    with patch("bridge.lifecycle.time.monotonic", return_value=entered_at + 6.0):
        reason = lc.check_timeout()

    assert reason is not None
    assert "spawn_timeout" in reason


def test_check_timeout_active():
    """Timeout detected when ACTIVE exceeds its limit."""
    timeouts = StateTimeouts(spawning=100.0, active=10.0, completing=100.0)
    lc = SubprocessLifecycle(timeouts=timeouts)
    lc.transition(State.SPAWNING)
    lc.transition(State.ACTIVE)

    entered_at = lc._state_entered_at
    with patch("bridge.lifecycle.time.monotonic", return_value=entered_at + 11.0):
        reason = lc.check_timeout()

    assert reason is not None
    assert "active_timeout" in reason


def test_check_timeout_no_timeout():
    """No timeout when within limits."""
    lc = SubprocessLifecycle()
    lc.transition(State.SPAWNING)

    # Just entered — well within 30s default
    reason = lc.check_timeout()
    assert reason is None


# ---------------------------------------------------------------------------
# Reset
# ---------------------------------------------------------------------------

def test_reset_from_completed():
    """reset() from COMPLETED returns to IDLE."""
    lc = SubprocessLifecycle()
    lc.transition(State.SPAWNING)
    lc.transition(State.ACTIVE)
    lc.transition(State.COMPLETING)
    lc.transition(State.COMPLETED)

    lc.reset()
    assert lc.state == State.IDLE


def test_reset_from_failed():
    """reset() from FAILED returns to IDLE."""
    lc = SubprocessLifecycle()
    lc.transition(State.SPAWNING)
    lc.transition(State.FAILED, reason="crash")

    lc.reset()
    assert lc.state == State.IDLE


def test_reset_from_active_ignored():
    """reset() from ACTIVE is ignored (only works from terminal states)."""
    lc = SubprocessLifecycle()
    lc.transition(State.SPAWNING)
    lc.transition(State.ACTIVE)

    lc.reset()
    assert lc.state == State.ACTIVE  # unchanged


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------

def test_metrics_total_runs():
    """total_runs increments on COMPLETED and FAILED."""
    lc = SubprocessLifecycle()

    # Successful run
    lc.transition(State.SPAWNING)
    lc.transition(State.ACTIVE)
    lc.transition(State.COMPLETING)
    lc.transition(State.COMPLETED)
    assert lc.metrics.total_runs == 1

    # Failed run
    lc.reset()
    lc.transition(State.SPAWNING)
    lc.transition(State.FAILED, reason="error")
    assert lc.metrics.total_runs == 2


def test_metrics_failure_rate():
    """failure_rate = total_failures / total_runs."""
    lc = SubprocessLifecycle()

    # One success
    lc.transition(State.SPAWNING)
    lc.transition(State.ACTIVE)
    lc.transition(State.COMPLETING)
    lc.transition(State.COMPLETED)

    # One failure
    lc.reset()
    lc.transition(State.SPAWNING)
    lc.transition(State.FAILED, reason="crash")

    assert lc.metrics.total_runs == 2
    assert lc.metrics.total_failures == 1
    assert lc.metrics.failure_rate == pytest.approx(0.5)


def test_metrics_avg_duration():
    """avg_duration_ms tracks average time from SPAWNING to COMPLETED."""
    timeouts = StateTimeouts(spawning=100.0, active=1800.0, completing=100.0)
    lc = SubprocessLifecycle(timeouts=timeouts)

    # Simulate a run: SPAWNING at t=100, COMPLETED at t=102 -> 2000ms
    with patch("bridge.lifecycle.time.monotonic", return_value=100.0):
        lc.transition(State.SPAWNING)
    with patch("bridge.lifecycle.time.monotonic", return_value=100.5):
        lc.transition(State.ACTIVE)
    with patch("bridge.lifecycle.time.monotonic", return_value=101.5):
        lc.transition(State.COMPLETING)
    with patch("bridge.lifecycle.time.monotonic", return_value=102.0):
        lc.transition(State.COMPLETED)

    assert lc.metrics.total_runs == 1
    # Duration = (102.0 - 100.0) * 1000 = 2000ms
    assert lc.metrics.avg_duration_ms == pytest.approx(2000.0)
