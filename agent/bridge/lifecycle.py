"""Subprocess lifecycle state machine.

Tracks Claude subprocess through IDLE -> SPAWNING -> ACTIVE -> COMPLETING ->
COMPLETED/FAILED with per-state timeouts and aggregate metrics.
"""

from __future__ import annotations

import enum
import logging
import time
from dataclasses import dataclass

logger = logging.getLogger(__name__)


class State(enum.Enum):
    IDLE = "idle"
    SPAWNING = "spawning"
    ACTIVE = "active"
    COMPLETING = "completing"
    COMPLETED = "completed"
    FAILED = "failed"


_TRANSITIONS: dict[State, set[State]] = {
    State.IDLE: {State.SPAWNING},
    State.SPAWNING: {State.ACTIVE, State.FAILED},
    State.ACTIVE: {State.COMPLETING, State.FAILED},
    State.COMPLETING: {State.COMPLETED, State.FAILED},
    State.COMPLETED: {State.IDLE},
    State.FAILED: {State.IDLE},
}


@dataclass
class StateTimeouts:
    """Per-state timeout configuration in seconds."""
    spawning: float = 30.0
    active: float = 1800.0
    completing: float = 30.0


@dataclass
class LifecycleMetrics:
    total_runs: int = 0
    total_failures: int = 0
    total_duration_ms: float = 0.0
    last_failure_reason: str = ""

    @property
    def avg_duration_ms(self) -> float:
        if self.total_runs == 0:
            return 0.0
        return self.total_duration_ms / self.total_runs

    @property
    def failure_rate(self) -> float:
        if self.total_runs == 0:
            return 0.0
        return self.total_failures / self.total_runs


class SubprocessLifecycle:
    """FSM for Claude subprocess lifecycle."""

    def __init__(self, timeouts: StateTimeouts | None = None) -> None:
        self._state = State.IDLE
        self._timeouts = timeouts or StateTimeouts()
        self._state_entered_at: float = time.monotonic()
        self._run_started_at: float = 0.0
        self.metrics = LifecycleMetrics()

    @property
    def state(self) -> State:
        return self._state

    @property
    def state_duration(self) -> float:
        return time.monotonic() - self._state_entered_at

    def transition(self, new_state: State, reason: str = "") -> None:
        """Transition to a new state. Raises ValueError on invalid transition."""
        valid = _TRANSITIONS.get(self._state, set())
        if new_state not in valid:
            raise ValueError(
                f"Invalid transition: {self._state.value} -> {new_state.value}"
            )

        old = self._state
        self._state = new_state
        self._state_entered_at = time.monotonic()

        if new_state == State.SPAWNING:
            self._run_started_at = self._state_entered_at
        elif new_state == State.COMPLETED:
            duration = (self._state_entered_at - self._run_started_at) * 1000
            self.metrics.total_runs += 1
            self.metrics.total_duration_ms += duration
        elif new_state == State.FAILED:
            self.metrics.total_runs += 1
            self.metrics.total_failures += 1
            self.metrics.last_failure_reason = reason

        logger.info(
            "Lifecycle: %s -> %s%s",
            old.value, new_state.value,
            f" ({reason})" if reason else "",
        )

    def check_timeout(self) -> str | None:
        """Check if current state has exceeded its timeout. Returns reason or None."""
        dur = self.state_duration
        if self._state == State.SPAWNING and dur > self._timeouts.spawning:
            return f"spawn_timeout ({self._timeouts.spawning}s)"
        if self._state == State.ACTIVE and dur > self._timeouts.active:
            return f"active_timeout ({self._timeouts.active}s)"
        if self._state == State.COMPLETING and dur > self._timeouts.completing:
            return f"completing_timeout ({self._timeouts.completing}s)"
        return None

    def reset(self) -> None:
        """Reset to IDLE after COMPLETED or FAILED."""
        if self._state in (State.COMPLETED, State.FAILED):
            self._state = State.IDLE
            self._state_entered_at = time.monotonic()

    def get_status(self) -> dict:
        return {
            "state": self._state.value,
            "state_duration_s": round(self.state_duration, 1),
            "metrics": {
                "total_runs": self.metrics.total_runs,
                "total_failures": self.metrics.total_failures,
                "failure_rate": round(self.metrics.failure_rate, 3),
                "avg_duration_ms": round(self.metrics.avg_duration_ms, 0),
            },
        }
