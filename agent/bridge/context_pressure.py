"""Context pressure monitoring for transcript compaction.

Tracks message count, estimated tokens, and session duration to produce
a composite pressure score. Recommends compaction when thresholds are
exceeded.

Integration:
    - app.py Stage 1 pre-flight checks call get_pressure()
    - get_pressure_signal() injects hints into Claude context (like BudgetGuard)
    - EventBus receives 'compaction.recommended' when threshold exceeded
    - CompactionAgent (Sprint 2.2) responds to compaction recommendations

Pattern follows BudgetGuard: track → score → signal → act
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass

logger = logging.getLogger(__name__)



def format_handoff_message(capsule_id: str) -> str:
    """Build the structured handoff message emitted at hard-stop.

    The [HANDOFF:capsule_id] marker mirrors the [ACK:msg_id] marker
    from tool_call_gate.py. The runner watches for this marker in the
    dialogue stream and uses its presence to trigger atomic
    capsule-write + session-exit.
    """
    return (
        "CONTEXT PRESSURE HARD-STOP\n\n"
        "I've hit the context-window threshold mid-task. Stopping cleanly "
        "before the next tool call to avoid mid-task summarization "
        "fidelity loss. State for the next session is being captured to a "
        "handoff capsule.\n\n"
        f"[HANDOFF:{capsule_id}]\n\n"
        "Resume in a fresh session — the capsule will be re-injected at "
        "SessionStart (per Sprint E1.3)."
    )

@dataclass(frozen=True)
class CompactionConfig:
    """Configuration for context pressure monitoring."""
    message_limit: int = 40
    token_limit: int = 8000
    duration_limit: int = 7200  # seconds
    auto_trigger_threshold: float = 0.75
    warning_threshold: float = 0.60
    cooldown_seconds: int = 300
    max_consecutive_failures: int = 3

    # Composite score weights
    weight_tokens: float = 0.5
    weight_messages: float = 0.3
    weight_duration: float = 0.2


@dataclass(frozen=True)
class ContextPressure:
    """Snapshot of current context pressure state."""
    message_count: int
    message_limit: int
    estimated_tokens: int
    token_limit: int
    session_duration_seconds: int
    duration_limit: int
    composite_score: float  # 0.0 - 1.0
    recommendation: str  # "ok" | "warn" | "compact_now" | "critical"


class ContextPressureMonitor:
    """Monitors context pressure and recommends compaction.

    Usage:
        monitor = ContextPressureMonitor(config)
        monitor.record_message(estimated_tokens=150)
        pressure = monitor.get_pressure()
        if pressure.recommendation == "compact_now":
            # trigger compaction
    """

    def __init__(self, config: CompactionConfig) -> None:
        self._config = config
        self._message_count = 0
        self._estimated_tokens = 0
        self._session_start = time.monotonic()
        self._last_compact_time = 0.0
        self._consecutive_failures = 0

    def record_message(self, estimated_tokens: int = 0) -> None:
        """Record a new message in the session."""
        self._message_count += 1
        self._estimated_tokens += estimated_tokens

    def get_pressure(self) -> ContextPressure:
        """Calculate current context pressure."""
        elapsed = int(time.monotonic() - self._session_start)

        # Calculate per-dimension ratios (capped at 1.0)
        msg_ratio = min(1.0, self._message_count / max(1, self._config.message_limit))
        token_ratio = min(1.0, self._estimated_tokens / max(1, self._config.token_limit))
        duration_ratio = min(1.0, elapsed / max(1, self._config.duration_limit))

        # Weighted composite
        composite = (
            self._config.weight_tokens * token_ratio
            + self._config.weight_messages * msg_ratio
            + self._config.weight_duration * duration_ratio
        )
        composite = min(1.0, composite)

        # Determine recommendation
        if composite >= 0.90:
            recommendation = "critical"
        elif composite >= self._config.auto_trigger_threshold:
            recommendation = "compact_now"
        elif composite >= self._config.warning_threshold:
            recommendation = "warn"
        else:
            recommendation = "ok"

        return ContextPressure(
            message_count=self._message_count,
            message_limit=self._config.message_limit,
            estimated_tokens=self._estimated_tokens,
            token_limit=self._config.token_limit,
            session_duration_seconds=elapsed,
            duration_limit=self._config.duration_limit,
            composite_score=round(composite, 3),
            recommendation=recommendation,
        )

    def get_pressure_signal(self) -> str | None:
        """Return a context injection hint, or None if pressure is OK.

        Mirrors BudgetGuard.get_pressure_signal() pattern.
        """
        pressure = self.get_pressure()

        if pressure.recommendation == "critical":
            return (
                "CONTEXT PRESSURE CRITICAL: "
                f"{pressure.message_count}/{pressure.message_limit} messages, "
                f"~{pressure.estimated_tokens}/{pressure.token_limit} tokens. "
                "Use /compact immediately to preserve context quality."
            )
        elif pressure.recommendation == "compact_now":
            return (
                "Context pressure is high "
                f"({pressure.composite_score:.0%}). "
                "Consider using /compact to summarize older conversation."
            )
        elif pressure.recommendation == "warn":
            return (
                f"Context at {pressure.composite_score:.0%} capacity. "
                "Be concise to preserve context window."
            )

        return None

    def can_compact(self) -> bool:
        """Check if compaction is allowed (cooldown + failure circuit breaker)."""
        now = time.monotonic()
        if self._consecutive_failures >= self._config.max_consecutive_failures:
            return False
        if self._last_compact_time > 0:
            elapsed_since_compact = now - self._last_compact_time
            if elapsed_since_compact < self._config.cooldown_seconds:
                return False
        return True

    def should_hard_stop(self, *, hard_stop_enabled: bool = True) -> bool:
        """Return True if context pressure has crossed the hard-stop threshold.

        Mirrors the can_compact() predicate-method shape. Reads
        get_pressure().recommendation (computed from the composite score).
        The flag is passed in rather than stored so the runner can flip it
        from BridgeConfig at call time without re-instantiating the monitor.
        Returns False immediately when the flag is off, regardless of pressure.
        """
        if not hard_stop_enabled:
            return False
        return self.get_pressure().recommendation in ("compact_now", "critical")

    def record_compact_success(self, tokens_saved: int = 0) -> None:
        """Record a successful compaction."""
        self._last_compact_time = time.monotonic()
        self._consecutive_failures = 0
        self._estimated_tokens = max(0, self._estimated_tokens - tokens_saved)

    def record_compact_failure(self) -> None:
        """Record a failed compaction attempt."""
        self._consecutive_failures += 1

    def reset(self) -> None:
        """Reset all counters (new session)."""
        self._message_count = 0
        self._estimated_tokens = 0
        self._session_start = time.monotonic()
        self._consecutive_failures = 0
