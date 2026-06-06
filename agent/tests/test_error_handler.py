"""Comprehensive tests for bridge.error_handler.

Covers every error_type branch: auth, rate_limit, content_filter,
max_turns, binary_not_found, oom/segfault, error_during_execution,
timeout, unknown (with retries and fallback).  Also tests cross-cutting
concerns: routing_feedback, session_recovery, skill_evolution,
reflexion_ctx, hooks dispatch, and security logging.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from unittest.mock import AsyncMock, MagicMock

import pytest

from bridge.error_handler import ErrorAction, handle_processing_error


# ---------------------------------------------------------------------------
# Helpers — lightweight fakes for the 20+ keyword deps
# ---------------------------------------------------------------------------


@dataclass
class FakeMsg:
    id: int = 1
    chat_id: str = "chat-1"
    text: str = "hello"
    attempt_count: int = 1
    platform_message_id: str = "plat-1"


@dataclass
class FakeResult:
    error_type: str = ""
    exit_code: int = 1
    stderr_output: str = "some error"
    response_text: str = ""
    model: str = "sonnet"


@dataclass
class FakeConfig:
    claude_max_retries: int = 3
    rate_limit_initial_backoff: int = 30
    rate_limit_max_backoff: int = 1800
    rate_limit_multiplier: float = 2.0
    rate_limit_jitter: float = 0.5


def _make_deps(**overrides) -> dict:
    """Build the full keyword-arg dict for handle_processing_error."""
    security = AsyncMock()
    security.log_event = AsyncMock()
    security.check_anomalies = AsyncMock(return_value=[])
    security.set_halt = MagicMock()

    deps = {
        "msg": FakeMsg(),
        "result": FakeResult(),
        "session_id": "sess-1",
        "config": FakeConfig(),
        "queue": AsyncMock(),
        "security": security,
        "discord": AsyncMock(),
        "commands": MagicMock(),
    }
    deps.update(overrides)
    return deps


# ---------------------------------------------------------------------------
# ErrorAction dataclass
# ---------------------------------------------------------------------------


class TestErrorAction:
    def test_default_no_halt(self) -> None:
        action = ErrorAction()
        assert action.should_halt is False
        assert action.halt_reason == ""

    def test_custom_values(self) -> None:
        action = ErrorAction(should_halt=True, halt_reason="auth_expired")
        assert action.should_halt is True
        assert action.halt_reason == "auth_expired"


# ---------------------------------------------------------------------------
# Cross-cutting: security logging, anomaly checks, error recording
# ---------------------------------------------------------------------------


class TestCrossCutting:
    async def test_records_error_on_commands(self) -> None:
        deps = _make_deps(result=FakeResult(error_type="unknown"))
        await handle_processing_error(**deps)
        deps["commands"].record_error.assert_called_once()

    async def test_logs_security_event(self) -> None:
        deps = _make_deps(result=FakeResult(error_type="unknown"))
        await handle_processing_error(**deps)
        deps["security"].log_event.assert_awaited_once()
        call_args = deps["security"].log_event.call_args
        assert call_args[0][0] == "tool_failure"

    async def test_checks_anomalies(self) -> None:
        deps = _make_deps(result=FakeResult(error_type="unknown"))
        await handle_processing_error(**deps)
        deps["security"].check_anomalies.assert_awaited()

    async def test_anomaly_alerts_sent_to_discord(self) -> None:
        deps = _make_deps(result=FakeResult(error_type="unknown"))
        deps["security"].check_anomalies = AsyncMock(return_value=["alert1", "alert2"])
        await handle_processing_error(**deps)
        assert deps["discord"].send_alert.await_count == 2

    async def test_no_hooks_kwarg_accepted(self) -> None:
        """Sprint 01.08b: handle_processing_error no longer accepts a `hooks`
        kwarg — HookDispatcher was deleted after the Mac mini audit. Passing
        hooks= must raise TypeError; the surrounding error-handling flow runs
        unaffected without it."""
        deps = _make_deps(result=FakeResult(error_type="unknown"))
        # Default deps have no `hooks` key; call should succeed
        await handle_processing_error(**deps)
        # Explicit hooks= kwarg must now raise
        with pytest.raises(TypeError, match="hooks"):
            await handle_processing_error(hooks=AsyncMock(), **deps)


# ---------------------------------------------------------------------------
# Routing feedback
# ---------------------------------------------------------------------------


class TestRoutingFeedback:
    async def test_routing_feedback_recorded(self) -> None:
        rf = MagicMock()
        deps = _make_deps(
            result=FakeResult(error_type="unknown"),
            routing_feedback=rf,
            classify_task_fn=lambda text, tags: "code",
        )
        await handle_processing_error(**deps)
        rf.record_model_use.assert_called_once()
        kwargs = rf.record_model_use.call_args[1]
        assert kwargs["success"] is False
        assert kwargs["task_type"] == "code"

    async def test_routing_feedback_exception_swallowed(self) -> None:
        rf = MagicMock()
        rf.record_model_use.side_effect = RuntimeError("boom")
        deps = _make_deps(result=FakeResult(error_type="unknown"), routing_feedback=rf)
        # Should not raise
        await handle_processing_error(**deps)


# ---------------------------------------------------------------------------
# Session recovery
# ---------------------------------------------------------------------------


class TestSessionRecovery:
    async def test_session_recovery_triggered(self) -> None:
        sr = MagicMock()
        sr.record_error.return_value = True
        sr.can_recover.return_value = True

        sm = AsyncMock()

        deps = _make_deps(
            result=FakeResult(error_type="unknown"),
            session_recovery=sr,
            session_mgr=sm,
        )
        await handle_processing_error(**deps)
        sr.record_error.assert_called_once_with("sess-1", "unknown")
        sm.expire_with_summary.assert_awaited_once()
        sr.record_recovery.assert_called_once()

    async def test_session_recovery_not_triggered_when_can_recover_false(self) -> None:
        sr = MagicMock()
        sr.record_error.return_value = True
        sr.can_recover.return_value = False

        sm = AsyncMock()

        deps = _make_deps(
            result=FakeResult(error_type="unknown"),
            session_recovery=sr,
            session_mgr=sm,
        )
        await handle_processing_error(**deps)
        sm.expire_with_summary.assert_not_awaited()


# ---------------------------------------------------------------------------
# Skill evolution
# ---------------------------------------------------------------------------


class TestSkillEvolution:
    async def test_skill_evolution_recorded(self) -> None:
        se = MagicMock()
        deps = _make_deps(
            result=FakeResult(error_type="timeout", stderr_output="timed out"),
            skill_evolution=se,
            classify_task_fn=lambda text, tags: "analysis",
        )
        await handle_processing_error(**deps)
        se.record_failure.assert_called_once()
        kwargs = se.record_failure.call_args[1]
        assert kwargs["error_type"] == "timeout"
        assert kwargs["task_type"] == "analysis"

    async def test_skill_evolution_exception_swallowed(self) -> None:
        se = MagicMock()
        se.record_failure.side_effect = RuntimeError("nope")
        deps = _make_deps(result=FakeResult(error_type="timeout"), skill_evolution=se)
        await handle_processing_error(**deps)  # No raise


# ---------------------------------------------------------------------------
# Reflexion context
# ---------------------------------------------------------------------------


class TestReflexionCtx:
    async def test_reflexion_pair_added(self) -> None:
        rc = MagicMock()
        deps = _make_deps(
            result=FakeResult(error_type="content_filter", stderr_output="filtered"),
            reflexion_ctx=rc,
        )
        await handle_processing_error(**deps)
        rc.add_pair.assert_called_once()
        kwargs = rc.add_pair.call_args[1]
        assert "content_filter" in kwargs["reflection"]


# ---------------------------------------------------------------------------
# Auth error path
# ---------------------------------------------------------------------------


class TestAuthError:
    async def test_auth_without_refresher_halts(self) -> None:
        deps = _make_deps(result=FakeResult(error_type="auth"))
        action = await handle_processing_error(**deps)
        assert action.should_halt is True
        assert action.halt_reason == "auth_expired"
        deps["queue"].fail.assert_awaited_once()
        deps["discord"].send_message.assert_awaited()

    async def test_auth_with_successful_refresh_retries(self) -> None:
        tr = MagicMock()
        force_refresh = AsyncMock(return_value=True)

        deps = _make_deps(
            result=FakeResult(error_type="auth"),
            token_refresher=tr,
            force_token_refresh_fn=force_refresh,
        )
        action = await handle_processing_error(**deps)
        assert action.should_halt is False
        deps["queue"].retry.assert_awaited_once()
        deps["queue"].fail.assert_not_awaited()

    async def test_auth_with_failed_refresh_halts(self) -> None:
        tr = MagicMock()
        force_refresh = AsyncMock(return_value=False)

        deps = _make_deps(
            result=FakeResult(error_type="auth"),
            token_refresher=tr,
            force_token_refresh_fn=force_refresh,
        )
        action = await handle_processing_error(**deps)
        assert action.should_halt is True
        assert action.halt_reason == "auth_expired"


# ---------------------------------------------------------------------------
# Rate limit error path
# ---------------------------------------------------------------------------


class TestRateLimitError:
    async def test_rate_limit_retries_message(self) -> None:
        deps = _make_deps(result=FakeResult(error_type="rate_limit"))
        action = await handle_processing_error(**deps)
        assert action.should_halt is False
        deps["queue"].retry.assert_awaited_once()
        deps["queue"].rate_limit_all.assert_awaited_once()
        deps["commands"].record_rate_limit.assert_called_once()

    async def test_rate_limit_with_rate_limiter(self) -> None:
        rl = MagicMock()
        deps = _make_deps(result=FakeResult(error_type="rate_limit"), rate_limiter=rl)
        await handle_processing_error(**deps)
        rl.on_rate_limited.assert_called_once()

    async def test_rate_limit_sends_user_message(self) -> None:
        deps = _make_deps(result=FakeResult(error_type="rate_limit"))
        await handle_processing_error(**deps)
        deps["discord"].send_message.assert_awaited()
        msg_text = deps["discord"].send_message.call_args[0][1]
        assert "Rate limited" in msg_text

    async def test_rate_limit_checks_anomalies(self) -> None:
        deps = _make_deps(result=FakeResult(error_type="rate_limit"))
        deps["security"].check_anomalies = AsyncMock(
            side_effect=[[], ["rl_alert"]]  # First call (tool_failure), second (rate_limit)
        )
        await handle_processing_error(**deps)
        # Two check_anomalies calls: one for tool_failure, one for rate_limit
        assert deps["security"].check_anomalies.await_count == 2

    async def test_rate_limit_with_shutdown_event(self) -> None:
        shutdown = asyncio.Event()
        deps = _make_deps(
            result=FakeResult(error_type="rate_limit"),
            shutdown_event=shutdown,
        )
        # Trigger shutdown immediately so wait_for doesn't actually wait
        shutdown.set()
        await handle_processing_error(**deps)
        # Should complete without hanging


# ---------------------------------------------------------------------------
# Content filter error path
# ---------------------------------------------------------------------------


class TestContentFilterError:
    async def test_content_filter_fails_message(self) -> None:
        deps = _make_deps(result=FakeResult(error_type="content_filter"))
        action = await handle_processing_error(**deps)
        assert action.should_halt is False
        deps["queue"].fail.assert_awaited_once_with(1, "content_filter")
        deps["discord"].send_message.assert_awaited()
        msg_text = deps["discord"].send_message.call_args[0][1]
        assert "filtered" in msg_text.lower()


# ---------------------------------------------------------------------------
# Max turns error path
# ---------------------------------------------------------------------------


class TestMaxTurnsError:
    async def test_max_turns_with_response_sends_it(self) -> None:
        send_fn = AsyncMock()
        deps = _make_deps(
            result=FakeResult(error_type="error_max_turns", response_text="partial response"),
            send_response_fn=send_fn,
        )
        action = await handle_processing_error(**deps)
        assert action.should_halt is False
        send_fn.assert_awaited_once_with("chat-1", "partial response", "plat-1")
        deps["queue"].complete.assert_awaited_once()

    async def test_max_turns_without_response(self) -> None:
        send_fn = AsyncMock()
        deps = _make_deps(
            result=FakeResult(error_type="max_turns", response_text=""),
            send_response_fn=send_fn,
        )
        await handle_processing_error(**deps)
        send_fn.assert_not_awaited()
        deps["queue"].complete.assert_awaited_once()

    async def test_max_turns_sends_continue_hint(self) -> None:
        deps = _make_deps(result=FakeResult(error_type="error_max_turns"))
        await handle_processing_error(**deps)
        msg = deps["discord"].send_message.call_args[0][1]
        assert "continue" in msg.lower()


# ---------------------------------------------------------------------------
# Binary not found error path
# ---------------------------------------------------------------------------


class TestBinaryNotFoundError:
    async def test_binary_not_found_halts(self) -> None:
        deps = _make_deps(result=FakeResult(error_type="binary_not_found"))
        action = await handle_processing_error(**deps)
        assert action.should_halt is True
        assert action.halt_reason == "binary_not_found"
        deps["queue"].fail.assert_awaited_once()


# ---------------------------------------------------------------------------
# OOM / segfault error path
# ---------------------------------------------------------------------------


class TestOomSegfaultError:
    async def test_oom_retries_when_under_max(self) -> None:
        deps = _make_deps(
            result=FakeResult(error_type="oom"),
            config=FakeConfig(claude_max_retries=3),
        )
        deps["msg"].attempt_count = 1
        action = await handle_processing_error(**deps)
        assert action.should_halt is False
        deps["queue"].retry.assert_awaited_once()

    async def test_segfault_fails_after_max_retries(self) -> None:
        deps = _make_deps(
            result=FakeResult(error_type="segfault"),
            config=FakeConfig(claude_max_retries=3),
        )
        deps["msg"].attempt_count = 3
        action = await handle_processing_error(**deps)
        assert action.should_halt is False
        deps["queue"].fail.assert_awaited_once()
        msg_text = deps["discord"].send_message.call_args[0][1]
        assert "3 attempts" in msg_text


# ---------------------------------------------------------------------------
# Error during execution path
# ---------------------------------------------------------------------------


class TestErrorDuringExecution:
    async def test_retries_when_under_max(self) -> None:
        deps = _make_deps(result=FakeResult(error_type="error_during_execution"))
        deps["msg"].attempt_count = 1
        await handle_processing_error(**deps)
        deps["queue"].retry.assert_awaited_once()

    async def test_fails_after_max_retries_with_response(self) -> None:
        send_fn = AsyncMock()
        deps = _make_deps(
            result=FakeResult(error_type="error_during_execution", response_text="partial"),
            send_response_fn=send_fn,
        )
        deps["msg"].attempt_count = 3
        await handle_processing_error(**deps)
        deps["queue"].fail.assert_awaited_once()
        send_fn.assert_awaited_once()

    async def test_fails_after_max_retries_without_response(self) -> None:
        send_fn = AsyncMock()
        deps = _make_deps(
            result=FakeResult(error_type="error_during_execution", response_text=""),
            send_response_fn=send_fn,
        )
        deps["msg"].attempt_count = 3
        await handle_processing_error(**deps)
        send_fn.assert_not_awaited()


# ---------------------------------------------------------------------------
# Timeout error path
# ---------------------------------------------------------------------------


class TestTimeoutError:
    async def test_timeout_halts(self) -> None:
        deps = _make_deps(result=FakeResult(error_type="timeout"))
        action = await handle_processing_error(**deps)
        assert action.should_halt is True
        assert action.halt_reason == "timeout"
        deps["queue"].complete.assert_awaited_once()

    async def test_timeout_delivers_partial_response(self) -> None:
        send_fn = AsyncMock()
        deps = _make_deps(
            result=FakeResult(error_type="timeout", response_text="partial"),
            send_response_fn=send_fn,
        )
        await handle_processing_error(**deps)
        send_fn.assert_awaited_once_with("chat-1", "partial", "plat-1")

    async def test_timeout_sends_resume_hint(self) -> None:
        deps = _make_deps(result=FakeResult(error_type="timeout"))
        await handle_processing_error(**deps)
        msg_text = deps["discord"].send_message.call_args[0][1]
        assert "/resume" in msg_text


# ---------------------------------------------------------------------------
# Unknown error path (with retries and fallback)
# ---------------------------------------------------------------------------


class TestUnknownError:
    async def test_unknown_retries_when_under_max(self) -> None:
        deps = _make_deps(result=FakeResult(error_type="something_weird"))
        deps["msg"].attempt_count = 1
        action = await handle_processing_error(**deps)
        assert action.should_halt is False
        deps["queue"].retry.assert_awaited_once()

    async def test_unknown_fails_after_max_retries(self) -> None:
        deps = _make_deps(result=FakeResult(error_type="something_weird"))
        deps["msg"].attempt_count = 3
        action = await handle_processing_error(**deps)
        deps["queue"].fail.assert_awaited_once()

    async def test_unknown_with_empty_error_type(self) -> None:
        deps = _make_deps(result=FakeResult(error_type=""))
        deps["msg"].attempt_count = 3
        await handle_processing_error(**deps)
        deps["queue"].fail.assert_awaited_once_with(1, "unknown")

    async def test_unknown_fallback_succeeds(self) -> None:
        @dataclass
        class FakeFallbackResult:
            error: str | None = None
            response_text: str = "fallback response"

        fallback = MagicMock()
        fallback.is_configured = True
        fallback.invoke.return_value = FakeFallbackResult()

        deps = _make_deps(result=FakeResult(error_type="weird"))
        deps["msg"].attempt_count = 3
        deps["fallback"] = fallback

        action = await handle_processing_error(**deps)
        assert action.should_halt is False
        deps["queue"].complete.assert_awaited_once()
        deps["discord"].send_message.assert_awaited()

    async def test_unknown_fallback_fails_gracefully(self) -> None:
        fallback = MagicMock()
        fallback.is_configured = True
        fallback.invoke.side_effect = RuntimeError("fallback down")

        deps = _make_deps(result=FakeResult(error_type="weird"))
        deps["msg"].attempt_count = 3
        deps["fallback"] = fallback

        action = await handle_processing_error(**deps)
        deps["queue"].fail.assert_awaited_once()

    async def test_unknown_no_fallback_configured(self) -> None:
        fallback = MagicMock()
        fallback.is_configured = False

        deps = _make_deps(result=FakeResult(error_type="weird"))
        deps["msg"].attempt_count = 3
        deps["fallback"] = fallback

        await handle_processing_error(**deps)
        fallback.invoke.assert_not_called()
        deps["queue"].fail.assert_awaited_once()


# ---------------------------------------------------------------------------
# Return value
# ---------------------------------------------------------------------------


class TestReturnValue:
    async def test_always_returns_error_action(self) -> None:
        for error_type in ["auth", "rate_limit", "content_filter", "timeout", "unknown"]:
            deps = _make_deps(result=FakeResult(error_type=error_type))
            action = await handle_processing_error(**deps)
            assert isinstance(action, ErrorAction)
