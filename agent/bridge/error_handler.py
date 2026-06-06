"""Error handling for Claude Code invocation failures.

Extracted from BridgeApp._handle_processing_error for maintainability.
Returns ErrorAction objects — the caller (BridgeApp) performs state mutations.
"""

from __future__ import annotations

import asyncio
import logging
import random
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class ErrorAction:
    """Result of error handling — tells the caller what to do."""

    should_halt: bool = False
    halt_reason: str = ""


async def handle_processing_error(
    *,
    msg,
    result,
    session_id: str,
    config,
    queue,
    security,
    discord,
    commands,
    routing_feedback=None,
    session_recovery=None,
    session_mgr=None,
    skill_evolution=None,
    reflexion_ctx=None,
    token_refresher=None,
    rate_limiter=None,
    fallback=None,
    few_shot=None,
    shutdown_event=None,
    classify_task_fn=None,
    send_response_fn=None,
    force_token_refresh_fn=None,
) -> ErrorAction:
    """Handle all failure modes from Claude Code invocation.

    Returns ErrorAction indicating whether the bridge should halt.
    The caller is responsible for setting self._halted based on the return value.
    """
    action = ErrorAction()
    error_type = result.error_type
    commands.record_error()

    # Routing feedback — record model failure
    if routing_feedback:
        try:
            _tt = classify_task_fn(msg.text, []) if classify_task_fn else "general"
            routing_feedback.record_model_use(
                model_tier=getattr(result, "model", None) or "sonnet",
                task_type=_tt,
                success=False,
                retry_needed=True,
            )
        except Exception as exc:
            logger.warning("routing_feedback record failed during error recovery: %s", exc)

    # Session recovery — record error and check if recovery needed
    if session_recovery and session_id and session_mgr:
        should_recover = session_recovery.record_error(session_id, error_type)
        if should_recover and session_recovery.can_recover(msg.chat_id):
            logger.info("Session %s recovery triggered (3+ consecutive errors)", session_id[:8])
            await session_mgr.expire_with_summary(msg.chat_id, session_id, "error_recovery", None)
            session_recovery.record_recovery(msg.chat_id)

    # Skill evolution — record failure for pattern detection
    if skill_evolution:
        try:
            _tt = classify_task_fn(msg.text, []) if classify_task_fn else "general"
            skill_evolution.record_failure(
                task_type=_tt,
                error_type=error_type,
                error_message=result.stderr_output[:500] if result.stderr_output else error_type,
                context={"chat_id": msg.chat_id},
            )
        except Exception as exc:
            logger.warning("skill_evolution record_failure suppressed during recovery: %s", exc)

    # Reflexion context — add failure for next attempt
    if reflexion_ctx:
        reflexion_ctx.add_pair(
            failed_input=msg.text[:200],
            failed_output=result.stderr_output[:200] if result.stderr_output else error_type,
            reflection=f"Previous attempt failed with {error_type}. Adjust approach.",
        )

    # Log the error
    await security.log_event(
        "tool_failure",
        details={
            "error_type": error_type,
            "exit_code": result.exit_code,
            "stderr": result.stderr_output[:500],
            "tool_name": "claude_runner",
        },
        session_id=session_id,
        chat_id=msg.chat_id,
    )

    # Check anomalies
    alerts = await security.check_anomalies(
        "tool_failure", {"tool_name": "claude_runner"}
    )
    for alert in alerts:
        await discord.send_alert(alert)

    # Sprint 01.08b: error HookDispatcher.dispatch() removed
    # (audit found 0 production hooks; see plan-01-hooks-audit.md)

    # --- Error-type-specific handling ---

    if error_type == "auth":
        # Self-healing: attempt token refresh before halting
        if token_refresher and force_token_refresh_fn:
            refreshed = await force_token_refresh_fn(token_refresher)
            if refreshed:
                logger.info("Token refresh succeeded — retrying message")
                await queue.retry(msg.id)
                return action  # No halt needed

        # Auth expired: signal halt
        action.should_halt = True
        action.halt_reason = "auth_expired"
        await asyncio.to_thread(security.set_halt, "auth_expired")
        await queue.fail(msg.id, "auth_expired")
        await discord.send_message(
            msg.chat_id,
            "Authentication expired. Run `claude` interactively on the Mac Mini to re-authenticate.",
        )

    elif error_type == "rate_limit":
        commands.record_rate_limit()
        if rate_limiter:
            rate_limiter.on_rate_limited()
        await queue.retry(msg.id)
        affected = await queue.rate_limit_all()

        rl_alerts = await security.check_anomalies("rate_limit")
        for alert in rl_alerts:
            await discord.send_alert(alert)

        backoff = min(
            config.rate_limit_initial_backoff * (
                config.rate_limit_multiplier ** (msg.attempt_count - 1)
            ),
            config.rate_limit_max_backoff,
        )
        jitter = backoff * config.rate_limit_jitter * random.random()
        wait_time = backoff + jitter

        await discord.send_message(
            msg.chat_id,
            f"Rate limited. Retrying in {int(wait_time)}s. ({affected} messages queued.)",
        )

        if shutdown_event:
            try:
                await asyncio.wait_for(shutdown_event.wait(), timeout=wait_time)
            except asyncio.TimeoutError:
                pass

    elif error_type == "content_filter":
        await queue.fail(msg.id, "content_filter")
        await discord.send_message(
            msg.chat_id,
            "Message was filtered. Try rephrasing.",
        )

    elif error_type in ("error_max_turns", "max_turns"):
        if result.response_text and send_response_fn:
            await send_response_fn(msg.chat_id, result.response_text, msg.platform_message_id)
        await queue.complete(msg.id)
        await discord.send_message(
            msg.chat_id,
            "Response truncated after max turns. Send 'continue' to resume.",
        )

    elif error_type == "binary_not_found":
        action.should_halt = True
        action.halt_reason = "binary_not_found"
        await asyncio.to_thread(security.set_halt, "binary_not_found")
        await queue.fail(msg.id, "binary_not_found")
        await discord.send_message(
            msg.chat_id,
            "Claude Code binary not found. Agent halted.",
        )

    elif error_type in ("oom", "segfault"):
        if msg.attempt_count < config.claude_max_retries:
            await queue.retry(msg.id)
            await discord.send_message(
                msg.chat_id,
                f"Claude crashed ({error_type}). Retrying...",
            )
        else:
            await queue.fail(msg.id, error_type)
            await discord.send_message(
                msg.chat_id,
                f"Message failed after {msg.attempt_count} attempts ({error_type}).",
            )

    elif error_type == "error_during_execution":
        if msg.attempt_count < config.claude_max_retries:
            await queue.retry(msg.id)
        else:
            await queue.fail(msg.id, "error_during_execution")
            if result.response_text and send_response_fn:
                await send_response_fn(msg.chat_id, result.response_text, msg.platform_message_id)
            await discord.send_message(
                msg.chat_id,
                f"Processing failed after {msg.attempt_count} attempts. Please try again.",
            )

    elif error_type == "timeout":
        # Timeout — deliver partial response, halt, and wait for operator
        if result.response_text and send_response_fn:
            await send_response_fn(msg.chat_id, result.response_text, msg.platform_message_id)
        await queue.complete(msg.id)
        action.should_halt = True
        action.halt_reason = "timeout"
        await asyncio.to_thread(security.set_halt, "timeout")
        await discord.send_message(
            msg.chat_id,
            "Request timed out. Partial response delivered above. Agent halted — send `/resume` to continue.",
        )

    else:
        # Unknown error: retry up to max_retries
        if msg.attempt_count < config.claude_max_retries:
            await queue.retry(msg.id)
            await discord.send_message(
                msg.chat_id,
                f"Error occurred. Retrying ({msg.attempt_count}/{config.claude_max_retries})...",
            )
        else:
            # All retries exhausted — try fallback LLM
            if fallback and fallback.is_configured:
                try:
                    fallback_result = await asyncio.to_thread(fallback.invoke, msg.text)
                    if fallback_result.error is None:
                        await queue.complete(msg.id)
                        await discord.send_message(
                            msg.chat_id, fallback_result.response_text
                        )
                        logger.info("Fallback LLM responded for message %d", msg.id)
                        return action
                except Exception as e:
                    logger.warning("Fallback LLM failed: %s", e)

            await queue.fail(msg.id, error_type or "unknown")
            await discord.send_message(
                msg.chat_id,
                f"Message failed after {msg.attempt_count} attempts. Please resend.",
            )

    return action
