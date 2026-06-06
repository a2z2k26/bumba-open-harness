"""
Error Recovery — frequency-based strategy selection with exponential backoff.

Tracks error occurrences in a sliding window and chooses from 5 recovery
strategies based on how often the same error type has occurred.
"""

import time
from dataclasses import dataclass
from enum import Enum
from typing import Dict, List, Optional


class RecoveryStrategy(str, Enum):
    """Available recovery strategies, ordered by escalation."""
    RESTART = "restart"
    RELOAD = "reload"
    RESET = "reset"
    FALLBACK = "fallback"
    ISOLATE = "isolate"


@dataclass
class ErrorRecord:
    """Single error event."""
    timestamp: float          # monotonic
    error_type: str
    error_message: str
    context: dict
    recovery_attempted: bool = False
    recovery_strategy: Optional[RecoveryStrategy] = None
    recovered: bool = False


@dataclass
class RecoveryResult:
    """Outcome of a recovery attempt."""
    success: bool
    strategy: RecoveryStrategy
    message: str
    retry_after_seconds: float


class ErrorFrequencyTracker:
    """
    Sliding-window frequency counter for error types.

    Records are stored as monotonic timestamps and pruned on each query.
    """

    def __init__(self) -> None:
        # error_type → list of monotonic timestamps
        self._timestamps: Dict[str, List[float]] = {}

    def record(self, error_type: str) -> None:
        if error_type not in self._timestamps:
            self._timestamps[error_type] = []
        self._timestamps[error_type].append(time.monotonic())

    def frequency(self, error_type: str, window_seconds: float = 300.0) -> int:
        """Return the number of occurrences within the last window_seconds."""
        cutoff = time.monotonic() - window_seconds
        timestamps = self._timestamps.get(error_type, [])
        # Prune in-place while we're here
        pruned = [t for t in timestamps if t >= cutoff]
        self._timestamps[error_type] = pruned
        return len(pruned)


# Backoff constants
_BACKOFF_BASE = 1.0
_BACKOFF_MAX = 60.0
_BACKOFF_MULTIPLIER = 2.0


def _backoff(frequency: int) -> float:
    """Exponential backoff: base * multiplier^(frequency-1), capped at max."""
    seconds = _BACKOFF_BASE * (_BACKOFF_MULTIPLIER ** max(0, frequency - 1))
    return min(seconds, _BACKOFF_MAX)


class ErrorRecoveryManager:
    """
    Selects and executes recovery strategies based on error frequency.

    Strategy selection:
        frequency == 1        → RESTART
        frequency in [2, 3]   → RELOAD
        frequency in [4, 5]   → RESET
        frequency in [6, 9]   → FALLBACK
        frequency >= 10       → ISOLATE
    """

    def __init__(self) -> None:
        self._tracker = ErrorFrequencyTracker()
        self._records: List[ErrorRecord] = []

    def record_error(
        self,
        error_type: str,
        error_message: str,
        context: dict,
    ) -> ErrorRecord:
        """Record an error occurrence and return an ErrorRecord."""
        self._tracker.record(error_type)
        record = ErrorRecord(
            timestamp=time.monotonic(),
            error_type=error_type,
            error_message=error_message,
            context=context,
        )
        self._records.append(record)
        return record

    def select_strategy(self, error_type: str, frequency: int) -> RecoveryStrategy:
        """Return the appropriate recovery strategy for the given frequency."""
        if frequency <= 1:
            return RecoveryStrategy.RESTART
        elif frequency <= 3:
            return RecoveryStrategy.RELOAD
        elif frequency <= 5:
            return RecoveryStrategy.RESET
        elif frequency <= 9:
            return RecoveryStrategy.FALLBACK
        else:
            return RecoveryStrategy.ISOLATE

    def execute_recovery(self, error_record: ErrorRecord) -> RecoveryResult:
        """
        Execute recovery for the given error record.

        Selects strategy from current frequency, marks the record, and
        returns a RecoveryResult with retry_after_seconds.
        """
        freq = self._tracker.frequency(error_record.error_type)
        strategy = self.select_strategy(error_record.error_type, freq)
        retry_after = _backoff(freq)

        # Mark the record (ErrorRecord is mutable even though its fields are plain types)
        error_record.recovery_attempted = True
        error_record.recovery_strategy = strategy
        # Stubs all succeed except ISOLATE
        error_record.recovered = strategy != RecoveryStrategy.ISOLATE

        return RecoveryResult(
            success=error_record.recovered,
            strategy=strategy,
            message=(
                f"Applied {strategy.value} for error_type={error_record.error_type!r} "
                f"(frequency={freq}, retry_after={retry_after:.1f}s)"
            ),
            retry_after_seconds=retry_after,
        )

    def get_error_frequency(
        self,
        error_type: str,
        window_seconds: int = 300,
    ) -> int:
        """Return the number of occurrences of error_type within window_seconds."""
        return self._tracker.frequency(error_type, float(window_seconds))
