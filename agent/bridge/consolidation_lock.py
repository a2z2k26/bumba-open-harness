"""PID-based consolidation lock.

The lock file's mtime IS the lastConsolidatedAt timestamp.
Body contains the holding process PID.
Stale threshold: 60 minutes.

Pattern adopted from Claude Code's autoDream system.
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass
from pathlib import Path


LOCK_FILE = ".consolidate-lock"
STALE_THRESHOLD_S = 3600  # 60 minutes


@dataclass(frozen=True)
class LockResult:
    acquired: bool
    prior_mtime: float  # 0 if lock didn't exist
    holder_pid: int | None  # PID of current holder (if blocked)


def _is_process_alive(pid: int) -> bool:
    """Check if a process is running."""
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ProcessLookupError):
        return False


class ConsolidationLock:
    """Manages consolidation locking with mtime-as-timestamp."""

    def __init__(self, data_dir: str | Path) -> None:
        self._lock_path = Path(data_dir) / LOCK_FILE

    def read_last_consolidated_at(self) -> float:
        """Return the mtime of the lock file (= last consolidation time).
        Returns 0 if the lock file doesn't exist (never consolidated).
        """
        try:
            return self._lock_path.stat().st_mtime
        except FileNotFoundError:
            return 0.0

    def try_acquire(self) -> LockResult:
        """Attempt to acquire the consolidation lock.

        Returns LockResult with acquired=True if successful.
        On success, prior_mtime is the pre-acquire mtime (for rollback).
        On failure, holder_pid identifies the blocking process.
        """
        prior_mtime = 0.0

        if self._lock_path.exists():
            stat = self._lock_path.stat()
            prior_mtime = stat.st_mtime
            age_s = time.time() - stat.st_mtime

            try:
                holder_pid = int(self._lock_path.read_text().strip())
            except (ValueError, OSError):
                holder_pid = None

            # If lock is fresh and holder is alive, we're blocked
            if age_s < STALE_THRESHOLD_S and holder_pid and _is_process_alive(holder_pid):
                return LockResult(acquired=False, prior_mtime=prior_mtime, holder_pid=holder_pid)

        # Write our PID
        self._lock_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock_path.write_text(str(os.getpid()))

        # Race resolution: re-read to verify we won
        try:
            written_pid = int(self._lock_path.read_text().strip())
            if written_pid != os.getpid():
                return LockResult(acquired=False, prior_mtime=prior_mtime, holder_pid=written_pid)
        except (ValueError, OSError):
            return LockResult(acquired=False, prior_mtime=prior_mtime, holder_pid=None)

        return LockResult(acquired=True, prior_mtime=prior_mtime, holder_pid=None)

    def rollback(self, prior_mtime: float) -> None:
        """Rewind lock state on consolidation failure."""
        if prior_mtime == 0.0:
            # Lock didn't exist before — remove it
            self._lock_path.unlink(missing_ok=True)
            return

        # Clear PID, rewind mtime
        self._lock_path.write_text("")
        os.utime(self._lock_path, (prior_mtime, prior_mtime))

    def record_completion(self) -> None:
        """Stamp the lock file with current time (successful consolidation)."""
        self._lock_path.write_text(str(os.getpid()))
        # mtime is now = current time, which is lastConsolidatedAt

    def release(self) -> None:
        """Clear PID from lock without changing mtime."""
        if self._lock_path.exists():
            # Capture current mtime before modifying
            stat = self._lock_path.stat()
            prior_mtime = stat.st_mtime

            # Clear PID
            self._lock_path.write_text("")

            # Restore mtime
            os.utime(self._lock_path, (prior_mtime, prior_mtime))
