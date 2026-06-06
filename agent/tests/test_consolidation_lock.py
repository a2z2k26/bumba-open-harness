"""Tests for ConsolidationLock with mtime-as-timestamp."""

import os
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from bridge.consolidation_lock import (
    ConsolidationLock,
    LockResult,
    STALE_THRESHOLD_S,
)


@pytest.fixture
def temp_data_dir(tmp_path):
    """Provide a temporary data directory."""
    return tmp_path


@pytest.fixture
def lock(temp_data_dir):
    """Provide a ConsolidationLock instance."""
    return ConsolidationLock(temp_data_dir)


class TestLockAcquisition:
    """Test basic lock acquisition."""

    def test_acquire_when_no_lock_exists(self, lock, temp_data_dir):
        """Lock acquisition succeeds when no lock file exists."""
        result = lock.try_acquire()

        assert result.acquired is True
        assert result.prior_mtime == 0.0
        assert result.holder_pid is None

        # Verify lock file was written
        lock_file = temp_data_dir / ".consolidate-lock"
        assert lock_file.exists()
        assert int(lock_file.read_text().strip()) == os.getpid()

    def test_acquire_when_fresh_lock_held(self, lock, temp_data_dir):
        """Lock acquisition fails when a fresh lock is held by live process."""
        lock_file = temp_data_dir / ".consolidate-lock"

        # Simulate a fresh lock held by a different process (not us)
        fake_pid = 9999
        lock_file.parent.mkdir(parents=True, exist_ok=True)
        lock_file.write_text(str(fake_pid))
        lock_file.touch()  # Fresh mtime

        # Mock process check: fake PID is alive
        with patch("bridge.consolidation_lock._is_process_alive", return_value=True):
            result = lock.try_acquire()

        assert result.acquired is False
        assert result.holder_pid == fake_pid
        assert result.prior_mtime > 0

    def test_acquire_stale_lock_dead_process(self, lock, temp_data_dir):
        """Lock acquisition succeeds when lock is stale (>60min) even if holder alive."""
        lock_file = temp_data_dir / ".consolidate-lock"
        lock_file.parent.mkdir(parents=True, exist_ok=True)

        # Create stale lock (70 min old)
        fake_pid = 9999
        stale_mtime = time.time() - (STALE_THRESHOLD_S + 600)
        lock_file.write_text(str(fake_pid))
        os.utime(lock_file, (stale_mtime, stale_mtime))

        result = lock.try_acquire()

        assert result.acquired is True
        assert result.prior_mtime == stale_mtime

    def test_acquire_fresh_lock_dead_process(self, lock, temp_data_dir):
        """Lock acquisition succeeds when holder process is dead."""
        lock_file = temp_data_dir / ".consolidate-lock"
        lock_file.parent.mkdir(parents=True, exist_ok=True)

        # Fresh lock held by dead process
        fake_pid = 9999
        lock_file.write_text(str(fake_pid))
        lock_file.touch()

        with patch("bridge.consolidation_lock._is_process_alive", return_value=False):
            result = lock.try_acquire()

        assert result.acquired is True
        assert result.prior_mtime > 0


class TestLockRelease:
    """Test lock release behavior."""

    def test_release_clears_pid_preserves_mtime(self, lock, temp_data_dir):
        """Release clears PID but preserves mtime."""
        # Acquire first
        lock.try_acquire()
        lock_file = temp_data_dir / ".consolidate-lock"

        mtime_after_acquire = lock_file.stat().st_mtime
        time.sleep(0.1)  # Ensure time has passed

        # Release
        lock.release()

        # PID should be cleared
        assert lock_file.read_text().strip() == ""

        # mtime should be unchanged
        assert lock_file.stat().st_mtime == mtime_after_acquire

    def test_release_on_nonexistent_lock(self, lock, temp_data_dir):
        """Release on nonexistent lock doesn't raise."""
        # Should not raise
        lock.release()


class TestRollback:
    """Test rollback behavior on consolidation failure."""

    def test_rollback_with_prior_mtime(self, lock, temp_data_dir):
        """Rollback restores prior mtime when lock existed before."""
        lock_file = temp_data_dir / ".consolidate-lock"
        lock_file.parent.mkdir(parents=True, exist_ok=True)

        # Set an initial mtime
        prior_mtime = time.time() - 1000
        lock_file.write_text("12345")
        os.utime(lock_file, (prior_mtime, prior_mtime))

        # Acquire (overwrites PID)
        result = lock.try_acquire()
        assert result.prior_mtime == prior_mtime

        time.sleep(0.1)
        new_mtime = lock_file.stat().st_mtime
        assert new_mtime > prior_mtime

        # Rollback
        lock.rollback(prior_mtime)

        # mtime should be restored
        assert lock_file.stat().st_mtime == prior_mtime
        assert lock_file.read_text().strip() == ""

    def test_rollback_with_zero_prior_mtime(self, lock, temp_data_dir):
        """Rollback removes lock file when prior_mtime was 0 (lock didn't exist)."""
        lock_file = temp_data_dir / ".consolidate-lock"

        # Acquire (creates lock)
        lock.try_acquire()
        assert lock_file.exists()

        # Rollback with prior_mtime=0
        lock.rollback(0.0)

        # Lock file should be gone
        assert not lock_file.exists()


class TestRecordCompletion:
    """Test successful consolidation marking."""

    def test_record_completion_updates_pid_and_mtime(self, lock, temp_data_dir):
        """record_completion stamps current time."""
        lock_file = temp_data_dir / ".consolidate-lock"

        # Acquire first
        lock.try_acquire()
        mtime_after_acquire = lock_file.stat().st_mtime
        pid_after_acquire = int(lock_file.read_text().strip())

        time.sleep(0.1)

        # Record completion
        lock.record_completion()

        # mtime should be newer
        mtime_after_completion = lock_file.stat().st_mtime
        assert mtime_after_completion >= mtime_after_acquire

        # PID should still be us
        assert int(lock_file.read_text().strip()) == os.getpid()


class TestReadLastConsolidatedAt:
    """Test reading lastConsolidatedAt from lock mtime."""

    def test_read_when_no_lock_exists(self, lock, temp_data_dir):
        """Returns 0.0 when lock file doesn't exist."""
        assert lock.read_last_consolidated_at() == 0.0

    def test_read_returns_mtime(self, lock, temp_data_dir):
        """Returns the lock file's mtime."""
        # Acquire lock
        lock.try_acquire()

        # Read mtime
        last_consolidated_at = lock.read_last_consolidated_at()

        # Should be close to now
        assert last_consolidated_at > 0
        assert abs(time.time() - last_consolidated_at) < 1.0

    def test_read_after_rollback_shows_old_mtime(self, lock, temp_data_dir):
        """After rollback, read returns the prior mtime."""
        lock_file = temp_data_dir / ".consolidate-lock"
        lock_file.parent.mkdir(parents=True, exist_ok=True)

        # Set initial mtime
        old_mtime = time.time() - 5000
        lock_file.write_text("12345")
        os.utime(lock_file, (old_mtime, old_mtime))

        # Acquire (overwrites)
        result = lock.try_acquire()

        # Verify mtime changed
        new_read = lock.read_last_consolidated_at()
        assert abs(new_read - time.time()) < 1.0

        # Rollback
        lock.rollback(result.prior_mtime)

        # Should read old_mtime again
        restored_read = lock.read_last_consolidated_at()
        assert abs(restored_read - old_mtime) < 0.01


class TestProcessAliveDetection:
    """Test process alive check."""

    def test_process_alive_check_our_pid(self):
        """Our own PID is alive."""
        from bridge.consolidation_lock import _is_process_alive

        assert _is_process_alive(os.getpid()) is True

    def test_process_alive_check_dead_pid(self):
        """Dead PIDs are detected."""
        from bridge.consolidation_lock import _is_process_alive

        # PID 1 is init, but try with a very high PID unlikely to exist
        fake_pid = 999999
        assert _is_process_alive(fake_pid) is False


class TestRaceCondition:
    """Test race condition handling."""

    def test_race_detection_on_write(self, lock, temp_data_dir):
        """When another process wins the race, we detect it."""
        lock_file = temp_data_dir / ".consolidate-lock"
        lock_file.parent.mkdir(parents=True, exist_ok=True)

        # Mock the write operation to succeed, but re-read shows different PID
        fake_other_pid = 9999
        original_write = Path.write_text

        call_count = [0]

        def mock_write(self, text, *args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                # First write (our attempt)
                original_write(self, str(fake_other_pid), *args, **kwargs)
            else:
                original_write(self, text, *args, **kwargs)

        with patch.object(Path, "write_text", mock_write):
            result = lock.try_acquire()

        # Should detect we lost the race
        assert result.acquired is False
        assert result.holder_pid == fake_other_pid


class TestLockResultDataclass:
    """Test LockResult frozen dataclass."""

    def test_lock_result_frozen(self):
        """LockResult is immutable."""
        result = LockResult(acquired=True, prior_mtime=100.0, holder_pid=None)

        with pytest.raises(Exception):  # FrozenInstanceError
            result.acquired = False

    def test_lock_result_repr(self):
        """LockResult has useful repr."""
        result = LockResult(acquired=True, prior_mtime=100.5, holder_pid=1234)
        repr_str = repr(result)

        assert "acquired=True" in repr_str
        assert "prior_mtime=100.5" in repr_str
        assert "holder_pid=1234" in repr_str


class TestGateCascadeOrdering:
    """Test integration: 3-gate cascade (time → activity → lock)."""

    def test_gate_cascade_scenario(self, lock, temp_data_dir):
        """Simulate 3-gate cascade: all gates pass."""
        # Gate 1: time gate (mock, assume passes)
        # Gate 2: activity gate (mock, assume passes)

        # Gate 3: lock gate
        result = lock.try_acquire()

        assert result.acquired is True

        # After successful consolidation
        lock.record_completion()

        # Next cycle: should be able to read consolidated time
        last_at = lock.read_last_consolidated_at()
        assert last_at > 0

    def test_gate_cascade_lock_gate_blocks(self, lock, temp_data_dir):
        """When lock gate fails, cascade stops."""
        lock_file = temp_data_dir / ".consolidate-lock"
        lock_file.parent.mkdir(parents=True, exist_ok=True)

        # Simulate fresh lock held by live process
        fake_pid = 9999
        lock_file.write_text(str(fake_pid))
        lock_file.touch()

        with patch("bridge.consolidation_lock._is_process_alive", return_value=True):
            result = lock.try_acquire()

        # Lock gate fails → cascade stops
        assert result.acquired is False
        assert result.holder_pid == fake_pid
