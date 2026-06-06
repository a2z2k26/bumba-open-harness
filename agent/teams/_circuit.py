"""Z4.4.4 — Per-department circuit breakers.

Implements a standard 3-state circuit breaker (CLOSED → OPEN → HALF_OPEN)
per department. When a department's team fails consecutively, the circuit
opens and fast-fails further requests until a cooldown elapses.
"""
from __future__ import annotations

import time
from enum import Enum
from dataclasses import dataclass, field


class CircuitState(Enum):
    CLOSED = "closed"      # normal operation
    OPEN = "open"          # fast-failing
    HALF_OPEN = "half_open"  # testing recovery


class CircuitOpenError(Exception):
    """Raised when a request is attempted while the circuit is OPEN."""


@dataclass
class CircuitBreaker:
    """Per-department circuit breaker."""
    department: str
    failure_threshold: int = 3        # consecutive failures before opening
    cooldown_seconds: float = 30.0    # seconds before trying again (HALF_OPEN)

    _state: CircuitState = field(default=CircuitState.CLOSED, init=False)
    _consecutive_failures: int = field(default=0, init=False)
    _opened_at: float | None = field(default=None, init=False)

    @property
    def state(self) -> CircuitState:
        """Return current state, auto-transitioning OPEN→HALF_OPEN after cooldown."""
        if self._state == CircuitState.OPEN and self._opened_at is not None:
            if time.monotonic() - self._opened_at >= self.cooldown_seconds:
                self._state = CircuitState.HALF_OPEN
        return self._state

    def before_call(self) -> None:
        """Call before each department request. Raises CircuitOpenError if OPEN."""
        if self.state == CircuitState.OPEN:
            raise CircuitOpenError(
                f"Circuit for department '{self.department}' is OPEN "
                f"(cooldown: {self.cooldown_seconds}s)"
            )

    def record_success(self) -> None:
        """Record a successful call. Resets failure count, closes circuit."""
        self._consecutive_failures = 0
        self._state = CircuitState.CLOSED
        self._opened_at = None

    def record_failure(self) -> None:
        """Record a failed call. Opens circuit if threshold exceeded."""
        self._consecutive_failures += 1
        if self._state == CircuitState.HALF_OPEN or \
                self._consecutive_failures >= self.failure_threshold:
            self._state = CircuitState.OPEN
            self._opened_at = time.monotonic()

    def reset(self) -> None:
        """Force circuit back to CLOSED (for testing/admin)."""
        self._state = CircuitState.CLOSED
        self._consecutive_failures = 0
        self._opened_at = None


class CircuitBreakerRegistry:
    """Manages one CircuitBreaker per department."""

    def __init__(self, failure_threshold: int = 3, cooldown_seconds: float = 30.0):
        self._breakers: dict[str, CircuitBreaker] = {}
        self._failure_threshold = failure_threshold
        self._cooldown_seconds = cooldown_seconds

    def get(self, department: str) -> CircuitBreaker:
        """Return (creating if needed) the breaker for a department."""
        if department not in self._breakers:
            self._breakers[department] = CircuitBreaker(
                department=department,
                failure_threshold=self._failure_threshold,
                cooldown_seconds=self._cooldown_seconds,
            )
        return self._breakers[department]

    def reset_all(self) -> None:
        """Reset all breakers (useful for tests)."""
        for b in self._breakers.values():
            b.reset()


# Module-level singleton
_registry = CircuitBreakerRegistry()


def get_registry() -> CircuitBreakerRegistry:
    return _registry
