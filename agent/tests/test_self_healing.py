"""Tests for bridge.self_healing (MS2.7)."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bridge.self_healing import (
    MAX_FORCE_REFRESH_ATTEMPTS,
    SessionRecoveryManager,
    check_voice_backends,
    force_token_refresh,
    invoke_with_retry,
)


# -- Mock helpers --


@dataclass
class MockClaudeResult:
    """Lightweight stand-in for ClaudeResult."""

    response_text: str = ""
    session_id: str = ""
    cost_usd: float = 0.0
    num_turns: int = 0
    tools_used: list[str] = field(default_factory=list)
    is_error: bool = False
    error_type: str = ""
    duration_ms: int = 0
    exit_code: int = 0
    stderr_output: str = ""


class MockRunner:
    """Mock ClaudeRunner with configurable invoke() responses."""

    def __init__(self, results: list[MockClaudeResult]) -> None:
        self._results = list(results)
        self._call_count = 0

    async def invoke(self, message, **kwargs) -> MockClaudeResult:
        idx = min(self._call_count, len(self._results) - 1)
        self._call_count += 1
        return self._results[idx]

    @property
    def call_count(self) -> int:
        return self._call_count


# -- 1. force_token_refresh tests --


class TestForceTokenRefresh:
    @pytest.mark.asyncio
    async def test_force_refresh_success_first_try(self):
        """Mock refresher succeeds on first try -> returns True."""
        refresher = MagicMock()
        refresher._do_refresh = AsyncMock(return_value=None)

        result = await force_token_refresh(refresher)

        assert result is True
        assert refresher._do_refresh.await_count == 1

    @pytest.mark.asyncio
    async def test_force_refresh_success_third_try(self):
        """Fails twice, succeeds on third attempt -> returns True."""
        refresher = MagicMock()
        refresher._do_refresh = AsyncMock(
            side_effect=[RuntimeError("fail1"), RuntimeError("fail2"), None]
        )

        result = await force_token_refresh(refresher)

        assert result is True
        assert refresher._do_refresh.await_count == 3

    @pytest.mark.asyncio
    async def test_force_refresh_all_fail(self):
        """Fails all 3 times -> returns False."""
        refresher = MagicMock()
        refresher._do_refresh = AsyncMock(
            side_effect=[RuntimeError("fail")] * MAX_FORCE_REFRESH_ATTEMPTS
        )

        result = await force_token_refresh(refresher)

        assert result is False
        assert refresher._do_refresh.await_count == MAX_FORCE_REFRESH_ATTEMPTS


# -- 2. invoke_with_retry tests --


class TestInvokeWithRetry:
    @pytest.mark.asyncio
    async def test_invoke_retry_success_first(self):
        """No error on first attempt -> returns result, no retry."""
        ok_result = MockClaudeResult(response_text="Hello", is_error=False)
        runner = MockRunner([ok_result])

        result = await invoke_with_retry(runner, "test message")

        assert result.response_text == "Hello"
        assert not result.is_error
        assert runner.call_count == 1

    @pytest.mark.asyncio
    async def test_invoke_retry_timeout_then_success(self):
        """Timeout on 1st attempt, success on 2nd."""
        err = MockClaudeResult(is_error=True, error_type="timeout")
        ok = MockClaudeResult(response_text="Recovered", is_error=False)
        runner = MockRunner([err, ok])

        result = await invoke_with_retry(runner, "test message")

        assert result.response_text == "Recovered"
        assert not result.is_error
        assert runner.call_count == 2

    @pytest.mark.asyncio
    async def test_invoke_retry_non_retryable_no_retry(self):
        """Auth error (non-retryable) -> no retry, returns error immediately."""
        err = MockClaudeResult(is_error=True, error_type="auth")
        runner = MockRunner([err])

        result = await invoke_with_retry(runner, "test message")

        assert result.is_error
        assert result.error_type == "auth"
        assert runner.call_count == 1

    @pytest.mark.asyncio
    async def test_invoke_retry_both_fail(self):
        """Timeout on both attempts -> returns error."""
        err1 = MockClaudeResult(is_error=True, error_type="timeout")
        err2 = MockClaudeResult(is_error=True, error_type="timeout")
        runner = MockRunner([err1, err2])

        result = await invoke_with_retry(runner, "test message")

        assert result.is_error
        assert result.error_type == "timeout"
        assert runner.call_count == 2

    @pytest.mark.asyncio
    async def test_invoke_retry_rate_limit_is_retryable(self):
        """rate_limit is a retryable error -> retries once."""
        err = MockClaudeResult(is_error=True, error_type="rate_limit")
        ok = MockClaudeResult(response_text="OK", is_error=False)
        runner = MockRunner([err, ok])

        result = await invoke_with_retry(runner, "test message")

        assert not result.is_error
        assert runner.call_count == 2

    @pytest.mark.asyncio
    async def test_invoke_retry_passes_all_kwargs(self):
        """All keyword args are forwarded to runner.invoke()."""
        ok = MockClaudeResult(response_text="OK", is_error=False)
        runner = MagicMock()
        runner.invoke = AsyncMock(return_value=ok)

        callback = lambda text: None
        await invoke_with_retry(
            runner,
            "hello",
            session_id="sess-1",
            system_prompt_file="/tmp/p.md",
            on_first_text=callback,
            working_dir="/tmp",
            model="haiku",
        )

        runner.invoke.assert_called_once_with(
            "hello",
            session_id="sess-1",
            system_prompt_file="/tmp/p.md",
            on_first_text=callback,
            working_dir="/tmp",
            model="haiku",
        )


# -- 3. Session Error Tracking tests --


class TestSessionRecoveryManager:
    def test_session_error_tracking_below_threshold(self):
        """2 errors -> returns False (no recovery needed)."""
        mgr = SessionRecoveryManager()
        assert mgr.record_error("s1", "timeout") is False
        assert mgr.record_error("s1", "timeout") is False

    def test_session_error_tracking_at_threshold(self):
        """3 consecutive errors -> returns True (recover)."""
        mgr = SessionRecoveryManager()
        mgr.record_error("s1", "timeout")
        mgr.record_error("s1", "timeout")
        result = mgr.record_error("s1", "timeout")
        assert result is True

    def test_session_success_resets_counter(self):
        """2 errors then success -> counter resets to 0."""
        mgr = SessionRecoveryManager()
        mgr.record_error("s1", "timeout")
        mgr.record_error("s1", "timeout")
        mgr.record_success("s1")
        # After reset, need 3 more errors to trigger recovery
        assert mgr.record_error("s1", "timeout") is False
        assert mgr.record_error("s1", "timeout") is False
        assert mgr._sessions["s1"].consecutive_errors == 2

    def test_session_recovery_rate_limit(self):
        """2 recoveries in 1 hour -> can_recover returns False."""
        mgr = SessionRecoveryManager()
        mgr.record_recovery("ch1")
        mgr.record_recovery("ch1")
        assert mgr.can_recover("ch1") is False

    def test_session_recovery_allowed_after_cooldown(self):
        """Old recoveries (>1 hour) are pruned -> can_recover returns True."""
        mgr = SessionRecoveryManager()
        # Manually inject timestamps from 2 hours ago
        old_time = time.monotonic() - 7200
        mgr._recovery_timestamps["ch1"] = [old_time, old_time + 1]
        assert mgr.can_recover("ch1") is True

    def test_session_recovery_first_time(self):
        """First time checking a channel -> can_recover returns True."""
        mgr = SessionRecoveryManager()
        assert mgr.can_recover("new-channel") is True

    def test_different_sessions_independent(self):
        """Errors on different sessions are tracked independently."""
        mgr = SessionRecoveryManager()
        mgr.record_error("s1", "timeout")
        mgr.record_error("s1", "timeout")
        mgr.record_error("s2", "auth")
        assert mgr._sessions["s1"].consecutive_errors == 2
        assert mgr._sessions["s2"].consecutive_errors == 1


# -- 4. Voice Backend Health Check tests --


class TestVoiceBackendCheck:
    @pytest.mark.asyncio
    async def test_voice_backend_check_both_down(self):
        """No server running -> both False."""
        result = await check_voice_backends(
            "http://127.0.0.1:19999", "http://127.0.0.1:19998", timeout=0.5
        )
        assert result == {"stt": False, "tts": False}

    @pytest.mark.asyncio
    async def test_voice_backend_check_mock_success(self):
        """Mock aiohttp -> both True."""
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=False)

        mock_session = AsyncMock()
        mock_session.get = MagicMock(return_value=mock_response)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        # Build a fake aiohttp module and inject it into sys.modules
        # so the function-level `import aiohttp` picks it up
        fake_aiohttp = MagicMock()
        fake_aiohttp.ClientTimeout = MagicMock(return_value=MagicMock())
        fake_aiohttp.ClientSession = MagicMock(return_value=mock_session)

        with patch.dict("sys.modules", {"aiohttp": fake_aiohttp}):
            result = await check_voice_backends(
                "http://localhost:8100", "http://localhost:8200"
            )

        assert result == {"stt": True, "tts": True}

    @pytest.mark.asyncio
    async def test_voice_backend_check_no_aiohttp(self):
        """When aiohttp is not importable -> returns both False."""

        # Temporarily hide aiohttp from the function-level import
        with patch.dict("sys.modules", {"aiohttp": None}):
            # Force reimport so the function-level import fails
            result = await check_voice_backends(
                "http://localhost:8100", "http://localhost:8200"
            )

        assert result == {"stt": False, "tts": False}
