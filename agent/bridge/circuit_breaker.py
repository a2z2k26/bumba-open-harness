"""
Orchestration Circuit Breaker — 3-state (CLOSED/OPEN/HALF_OPEN) protection.

Guards calls to downstream services. Distinct from the bridge-level
circuit_breaker.py — this version is designed for the orchestration layer
and supports a registry of named breakers.
"""

import time
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Dict, Optional


class State(str, Enum):
    """Circuit breaker states."""
    CLOSED = "closed"       # Normal operation
    OPEN = "open"           # Failing — reject all calls
    HALF_OPEN = "half_open" # Probing — allow one test call


@dataclass
class CircuitBreakerConfig:
    """Configuration for a single circuit breaker."""
    failure_threshold: int = 5     # Failures in window before opening
    success_threshold: int = 2     # Successes in HALF_OPEN before closing
    timeout_seconds: float = 60.0  # Seconds to wait before probing (OPEN → HALF_OPEN)
    window_seconds: float = 120.0  # Sliding window for failure counting


@dataclass
class CircuitBreakerState:
    """Current runtime state of a circuit breaker."""
    state: State
    failure_count: int
    success_count: int
    last_failure_at: Optional[float]   # monotonic timestamp
    opened_at: Optional[float]         # monotonic timestamp


class CircuitOpenError(Exception):
    """Raised when a call is rejected because the circuit is OPEN."""


class CircuitBreaker:
    """
    3-state circuit breaker.

    CLOSED  → allows calls; tracks failures in a sliding window.
              failures >= threshold → OPEN.
    OPEN    → rejects calls with CircuitOpenError.
              after timeout_seconds → HALF_OPEN.
    HALF_OPEN → allows a single test call.
              success → CLOSED; failure → OPEN.
    """

    def __init__(self, config: Optional[CircuitBreakerConfig] = None, **compat_kwargs) -> None:
        # Support compat kwargs from old orch API: name=, failure_threshold=, recovery_timeout=
        if compat_kwargs and config is None:
            config = CircuitBreakerConfig(
                failure_threshold=compat_kwargs.get("failure_threshold", 5),
                success_threshold=compat_kwargs.get("success_threshold", 1),
                timeout_seconds=compat_kwargs.get("recovery_timeout",
                                                  compat_kwargs.get("timeout_seconds", 30.0)),
                window_seconds=compat_kwargs.get("window_seconds", 120.0),
            )
        self._config = config or CircuitBreakerConfig()
        self._state = State.CLOSED
        self._failure_timestamps: list = []   # monotonic timestamps of recent failures
        self._success_count = 0               # consecutive successes in HALF_OPEN
        self._opened_at: Optional[float] = None
        self._last_failure_at: Optional[float] = None
        self._half_open_probe_in_flight = False
        self._total_trips = 0                 # number of times circuit has opened

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def call(self, func: Callable, *args: Any, **kwargs: Any) -> Any:
        """
        Invoke func if the circuit permits.

        Raises CircuitOpenError if OPEN.
        Automatically records success or failure.
        """
        self._maybe_transition_to_half_open()

        if self._state == State.OPEN:
            raise CircuitOpenError(
                f"Circuit is OPEN (opened {self._seconds_since_open():.1f}s ago). "
                f"Retry after {self._retry_after():.1f}s."
            )

        if self._state == State.HALF_OPEN:
            if self._half_open_probe_in_flight:
                raise CircuitOpenError("Circuit is HALF_OPEN and a probe is already in flight.")
            self._half_open_probe_in_flight = True

        try:
            result = func(*args, **kwargs)
            self.record_success()
            return result
        except Exception as exc:
            self.record_failure(exc)
            raise

    def record_success(self) -> None:
        """Record a successful call."""
        now = time.monotonic()
        self._half_open_probe_in_flight = False

        if self._state == State.HALF_OPEN:
            self._success_count += 1
            if self._success_count >= self._config.success_threshold:
                self._transition_to_closed()
        elif self._state == State.CLOSED:
            # Successes in CLOSED state clear the failure window
            self._prune_failure_window(now)

    def record_failure(self, error: Optional[Exception] = None, *, reason: str = "") -> None:
        """Record a failed call. error or reason can be supplied (compat)."""
        now = time.monotonic()
        self._half_open_probe_in_flight = False
        self._last_failure_at = now
        self._failure_timestamps.append(now)
        self._prune_failure_window(now)

        if self._state == State.HALF_OPEN:
            self._transition_to_open(now)
        elif self._state == State.CLOSED:
            if len(self._failure_timestamps) >= self._config.failure_threshold:
                self._transition_to_open(now)

    def get_state(self) -> CircuitBreakerState:
        """Return a snapshot of the current breaker state."""
        self._maybe_transition_to_half_open()
        return CircuitBreakerState(
            state=self._state,
            failure_count=len(self._failure_timestamps),
            success_count=self._success_count,
            last_failure_at=self._last_failure_at,
            opened_at=self._opened_at,
        )

    def reset(self) -> None:
        """Force the breaker back to CLOSED and clear all counters."""
        self._transition_to_closed()

    # ------------------------------------------------------------------
    # Compat accessors (used by tests and callers migrated from orch)
    # ------------------------------------------------------------------

    @property
    def state(self) -> State:
        """Current breaker state (compat accessor)."""
        self._maybe_transition_to_half_open()
        return self._state

    @property
    def is_available(self) -> bool:
        """True if the circuit allows calls right now (compat accessor)."""
        self._maybe_transition_to_half_open()
        return self._state != State.OPEN

    @property
    def failure_count(self) -> int:
        """Number of failures in the current window (compat accessor)."""
        return len(self._failure_timestamps)

    @property
    def _failure_count(self) -> int:
        """Private compat alias for test assertions."""
        return len(self._failure_timestamps)

    def status(self) -> dict:
        """Return a dict summary of the current state (compat accessor)."""
        s = self.get_state()
        return {
            "state": s.state.value,
            "failure_count": s.failure_count,
            "success_count": s.success_count,
            "last_failure_at": s.last_failure_at,
            "opened_at": s.opened_at,
            "total_trips": self._total_trips,
        }

    def get_status(self) -> dict:
        """Alias for status() (compat)."""
        return self.status()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _prune_failure_window(self, now: float) -> None:
        """Remove failure timestamps older than window_seconds."""
        cutoff = now - self._config.window_seconds
        self._failure_timestamps = [t for t in self._failure_timestamps if t >= cutoff]

    def _maybe_transition_to_half_open(self) -> None:
        """If OPEN and timeout has elapsed, move to HALF_OPEN."""
        if self._state == State.OPEN and self._opened_at is not None:
            if time.monotonic() - self._opened_at >= self._config.timeout_seconds:
                self._state = State.HALF_OPEN
                self._success_count = 0
                self._half_open_probe_in_flight = False

    def _transition_to_open(self, now: float) -> None:
        self._state = State.OPEN
        self._opened_at = now
        self._success_count = 0
        self._total_trips += 1

    def _transition_to_closed(self) -> None:
        self._state = State.CLOSED
        self._failure_timestamps = []
        self._success_count = 0
        self._opened_at = None
        self._half_open_probe_in_flight = False

    def _seconds_since_open(self) -> float:
        if self._opened_at is None:
            return 0.0
        return time.monotonic() - self._opened_at

    def _retry_after(self) -> float:
        if self._opened_at is None:
            return 0.0
        elapsed = time.monotonic() - self._opened_at
        return max(0.0, self._config.timeout_seconds - elapsed)


class CircuitBreakerRegistry:
    """Named registry for circuit breakers."""

    def __init__(self) -> None:
        self._breakers: Dict[str, CircuitBreaker] = {}

    def register(
        self,
        name: str,
        config: Optional[CircuitBreakerConfig] = None,
    ) -> CircuitBreaker:
        """Create and register a named breaker. Returns existing if already registered."""
        if name not in self._breakers:
            self._breakers[name] = CircuitBreaker(config)
        return self._breakers[name]

    def get(self, name: str, **config_kwargs) -> Optional[CircuitBreaker]:
        """Return the named breaker; auto-registers with config_kwargs if not found."""
        if name not in self._breakers and config_kwargs:
            config = CircuitBreakerConfig(
                failure_threshold=config_kwargs.get("failure_threshold", 5),
                success_threshold=config_kwargs.get("success_threshold", 1),
                timeout_seconds=config_kwargs.get("recovery_timeout", config_kwargs.get("timeout_seconds", 30.0)),
                window_seconds=config_kwargs.get("window_seconds", 120.0),
            )
            self._breakers[name] = CircuitBreaker(config)
        return self._breakers.get(name)

    def list_all(self) -> Dict[str, CircuitBreakerState]:
        """Return a snapshot of all breaker states."""
        return {name: cb.get_state() for name, cb in self._breakers.items()}

    def get_all_status(self) -> Dict[str, dict]:
        """Return status dict for all registered breakers (compat)."""
        return {name: cb.status() for name, cb in self._breakers.items()}
