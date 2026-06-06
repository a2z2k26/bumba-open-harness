"""Tests for MS0.2: blocking I/O elimination.

Verifies that sync file I/O in security.py and app.py is properly
offloaded to threads via asyncio.to_thread().
"""

import asyncio
import json
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bridge.security import SecurityManager


@pytest.fixture
def tmp_dirs():
    """Create temp directories for data and logs."""
    import shutil
    data_dir = tempfile.mkdtemp()
    log_dir = tempfile.mkdtemp()
    yield data_dir, log_dir
    shutil.rmtree(data_dir, ignore_errors=True)
    shutil.rmtree(log_dir, ignore_errors=True)


@pytest.fixture
def mock_config(tmp_dirs):
    """Create a mock BridgeConfig."""
    data_dir, log_dir = tmp_dirs
    config = MagicMock()
    config.data_dir = data_dir
    config.log_dir = log_dir
    config.tool_failure_window = 300
    config.tool_failure_threshold = 5
    config.crash_loop_window = 300
    config.crash_loop_threshold = 3
    config.db_size_alert = 500 * 1024 * 1024
    config.db_size_warn = 200 * 1024 * 1024
    return config


@pytest.fixture
def mock_db():
    """Create a mock Database."""
    db = AsyncMock()
    db.execute = AsyncMock()
    db.commit = AsyncMock()
    return db


@pytest.fixture
def security(mock_db, mock_config):
    """Create a SecurityManager with mock dependencies."""
    return SecurityManager(mock_db, mock_config)


class TestLogEventNonBlocking:
    """Verify that log_event JSONL write is offloaded to a thread."""

    @pytest.mark.asyncio
    async def test_log_event_writes_jsonl_via_thread(self, security, tmp_dirs):
        """log_event should write JSONL using _append_jsonl_sync via asyncio.to_thread."""
        _, log_dir = tmp_dirs
        jsonl_path = Path(log_dir) / "audit.jsonl"

        await security.log_event("test_event", details={"key": "value"})

        assert jsonl_path.exists()
        content = jsonl_path.read_text().strip()
        entry = json.loads(content)
        assert entry["event_type"] == "test_event"
        assert entry["details"] == {"key": "value"}

    @pytest.mark.asyncio
    async def test_log_event_uses_asyncio_to_thread(self, security):
        """Verify that asyncio.to_thread is called for the JSONL write."""
        with patch("bridge.security.asyncio.to_thread", new_callable=AsyncMock) as mock_to_thread:
            await security.log_event("test_event")
            mock_to_thread.assert_called_once()
            # First arg should be _append_jsonl_sync
            assert mock_to_thread.call_args[0][0] == security._append_jsonl_sync

    @pytest.mark.asyncio
    async def test_append_jsonl_sync_is_sync(self, security, tmp_dirs):
        """_append_jsonl_sync should be a regular sync method (not async)."""
        assert not asyncio.iscoroutinefunction(security._append_jsonl_sync)

    @pytest.mark.asyncio
    async def test_log_event_jsonl_failure_does_not_raise(self, security):
        """JSONL write failure should be logged, not raised."""
        security._jsonl_path = Path("/nonexistent/dir/audit.jsonl")
        # Should not raise
        await security.log_event("test_event")


class TestSecurityMethodsAreSyncCallable:
    """Verify security methods remain sync (suitable for asyncio.to_thread wrapping)."""

    def test_check_halt_flag_is_sync(self, security):
        assert not asyncio.iscoroutinefunction(security.check_halt_flag)

    def test_set_halt_is_sync(self, security):
        assert not asyncio.iscoroutinefunction(security.set_halt)

    def test_clear_halt_is_sync(self, security):
        assert not asyncio.iscoroutinefunction(security.clear_halt)

    def test_record_crash_timestamp_is_sync(self, security):
        assert not asyncio.iscoroutinefunction(security.record_crash_timestamp)

    def test_check_crash_loop_is_sync(self, security):
        assert not asyncio.iscoroutinefunction(security.check_crash_loop)

    def test_verify_kernel_hashes_is_sync(self, security):
        assert not asyncio.iscoroutinefunction(security.verify_kernel_hashes)


class TestHaltFlagRoundTrip:
    """Integration: halt flag set/check/clear works correctly."""

    def test_set_and_check(self, security):
        security.set_halt("test_reason")
        assert security.check_halt_flag() == "test_reason"

    def test_set_and_clear(self, security):
        security.set_halt("test_reason")
        security.clear_halt()
        assert security.check_halt_flag() is None

    def test_is_halted(self, security):
        assert not security.is_halted()
        security.set_halt("test")
        assert security.is_halted()


class TestKernelHashesInThread:
    """verify_kernel_hashes should be safe to call from asyncio.to_thread."""

    @pytest.mark.asyncio
    async def test_verify_kernel_hashes_via_to_thread(self, security, tmp_dirs):
        """verify_kernel_hashes can be called via asyncio.to_thread without error."""
        data_dir = tmp_dirs[0]
        # No baseline file — should return ["baseline file missing"]
        result = await asyncio.to_thread(security.verify_kernel_hashes)
        assert result == ["baseline file missing"]

    @pytest.mark.asyncio
    async def test_verify_kernel_hashes_with_valid_baseline(self, security, tmp_dirs):
        """With a valid baseline, verify_kernel_hashes returns empty list for matching files."""
        data_dir = tmp_dirs[0]
        # Create a test file and its baseline
        test_file = Path(data_dir) / "test.py"
        test_file.write_text("print('hello')")

        import hashlib
        file_hash = hashlib.sha256(test_file.read_bytes()).hexdigest()
        baseline = {"files": {str(test_file): file_hash}}
        baseline_path = Path(data_dir) / "kernel-baseline.json"
        baseline_path.write_text(json.dumps(baseline))

        result = await asyncio.to_thread(security.verify_kernel_hashes, baseline_path)
        assert result == []


class TestFallbackInvokeWrapping:
    """Verify that fallback.invoke is sync and suitable for asyncio.to_thread."""

    def test_fallback_invoke_is_sync(self):
        from bridge.fallback import FallbackChain
        chain = FallbackChain(api_key="")
        assert not asyncio.iscoroutinefunction(chain.invoke)

    @pytest.mark.asyncio
    async def test_fallback_invoke_via_to_thread(self):
        """fallback.invoke can be called via asyncio.to_thread."""
        from bridge.fallback import FallbackChain
        chain = FallbackChain(api_key="")  # No key = returns error result
        result = await asyncio.to_thread(chain.invoke, "test")
        assert result.error is not None


class TestCrashLoopDetection:
    """Crash loop detection works correctly via sync methods."""

    def test_no_crash_log(self, security):
        assert not security.check_crash_loop()

    def test_below_threshold(self, security, mock_config):
        mock_config.crash_loop_threshold = 5
        # Record 2 timestamps — below threshold of 5
        security.record_crash_timestamp()
        security.record_crash_timestamp()
        assert not security.check_crash_loop()

    def test_at_threshold(self, security, mock_config):
        mock_config.crash_loop_threshold = 3
        mock_config.crash_loop_window = 300
        for _ in range(3):
            security.record_crash_timestamp()
        assert security.check_crash_loop()
