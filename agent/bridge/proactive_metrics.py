"""Proactive mode metrics collection.

Tracks ticks sent, actions taken, sleep durations, and wake interrupts
for operator visibility and system tuning.
"""
from __future__ import annotations

from typing import Any


class ProactiveMetrics:
    """Collects metrics for the proactive tick loop.

    Thread-safe for single-process use (no locking needed — bridge is single-threaded async).
    """

    def __init__(self) -> None:
        """Initialize all counters to zero."""
        self.ticks_sent: int = 0
        self.actions_taken: int = 0
        self.wake_interrupts: int = 0
        self.sleep_durations: list[float] = []
        self._action_types: list[str] = []

    def record_tick(self) -> None:
        """Record that a tick prompt was sent."""
        self.ticks_sent += 1

    def record_action(self, action_type: str) -> None:
        """Record that a proactive action was taken."""
        self.actions_taken += 1
        self._action_types.append(action_type)
        # Keep last 100 action types
        if len(self._action_types) > 100:
            self._action_types = self._action_types[-100:]

    def record_sleep(self, duration_seconds: float) -> None:
        """Record a sleep duration."""
        self.sleep_durations.append(duration_seconds)
        # Keep last 100 sleep durations
        if len(self.sleep_durations) > 100:
            self.sleep_durations = self.sleep_durations[-100:]

    def record_wake_interrupt(self) -> None:
        """Record that an external signal interrupted a sleep."""
        self.wake_interrupts += 1

    @property
    def average_sleep(self) -> float:
        """Average sleep duration in seconds (0 if no sleeps recorded)."""
        if not self.sleep_durations:
            return 0.0
        return sum(self.sleep_durations) / len(self.sleep_durations)

    def reset(self) -> None:
        """Reset all counters (e.g., for hourly reporting)."""
        self.ticks_sent = 0
        self.actions_taken = 0
        self.wake_interrupts = 0
        self.sleep_durations = []
        self._action_types = []

    def to_dict(self) -> dict[str, Any]:
        """Serialize metrics for API/Discord reporting."""
        return {
            "ticks_sent": self.ticks_sent,
            "actions_taken": self.actions_taken,
            "wake_interrupts": self.wake_interrupts,
            "average_sleep_seconds": round(self.average_sleep, 1),
            "sleep_count": len(self.sleep_durations),
        }
