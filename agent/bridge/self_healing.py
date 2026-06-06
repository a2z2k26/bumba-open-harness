"""Self-healing utilities for the bridge: token retry, invocation cap, session recovery, voice checks."""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# -- 1. OAuth Auto-Retry --

MAX_FORCE_REFRESH_ATTEMPTS = 3


async def force_token_refresh(token_refresher) -> bool:
    """Attempt immediate token refresh with 3 retries and exponential backoff.

    Args:
        token_refresher: object with async _do_refresh() method
    Returns True on success, False after all attempts fail.
    """
    for attempt in range(1, MAX_FORCE_REFRESH_ATTEMPTS + 1):
        try:
            await token_refresher._do_refresh()
            logger.info("Force token refresh succeeded on attempt %d", attempt)
            return True
        except Exception as e:
            logger.warning(
                "Force token refresh attempt %d/%d failed: %s",
                attempt, MAX_FORCE_REFRESH_ATTEMPTS, e,
            )
            if attempt < MAX_FORCE_REFRESH_ATTEMPTS:
                backoff = 2 ** (attempt - 1)  # 1s, 2s
                await asyncio.sleep(backoff)

    logger.error("Force token refresh failed after %d attempts", MAX_FORCE_REFRESH_ATTEMPTS)
    return False


# -- 2. Two-Round Invocation Cap --

MAX_INVOCATION_ATTEMPTS = 2

_RETRYABLE_ERRORS = frozenset({"rate_limit", "spawn_error", "timeout"})


async def invoke_with_retry(
    runner,
    message: str,
    session_id: str | None = None,
    system_prompt_file: str | None = None,
    on_first_text=None,
    working_dir: str | None = None,
    model: str | None = None,
) -> "ClaudeResult":
    """Invoke Claude with hard two-attempt cap.

    On first failure with retryable error (timeout, rate_limit), waits 2s and retries once.
    On non-retryable error or second failure, returns the error result.
    Never retries more than once.
    """
    for attempt in range(1, MAX_INVOCATION_ATTEMPTS + 1):
        result = await runner.invoke(
            message,
            session_id=session_id,
            system_prompt_file=system_prompt_file,
            on_first_text=on_first_text,
            working_dir=working_dir,
            model=model,
        )

        if not result.is_error:
            return result

        # Non-retryable error — return immediately
        if result.error_type not in _RETRYABLE_ERRORS:
            logger.info(
                "Non-retryable error '%s' on attempt %d, returning",
                result.error_type, attempt,
            )
            return result

        # Retryable but already on last attempt — return the error
        if attempt >= MAX_INVOCATION_ATTEMPTS:
            logger.warning(
                "Retryable error '%s' on final attempt %d, giving up",
                result.error_type, attempt,
            )
            return result

        # Retryable on first attempt — wait and retry
        logger.info(
            "Retryable error '%s' on attempt %d, waiting 2s before retry",
            result.error_type, attempt,
        )
        await asyncio.sleep(2)

    # Should never reach here, but satisfy type checker
    return result  # type: ignore[possibly-undefined]


# -- 3. Session Error Tracking --

@dataclass
class SessionHealth:
    """Health state for a single session."""

    session_id: str
    consecutive_errors: int = 0
    last_error_type: str = ""
    recovery_count: int = 0
    max_recoveries_per_hour: int = 2


class SessionRecoveryManager:
    """Tracks session errors and triggers recovery when threshold exceeded."""

    CONSECUTIVE_ERROR_THRESHOLD = 3

    def __init__(self) -> None:
        self._sessions: dict[str, SessionHealth] = {}
        self._recovery_timestamps: dict[str, list[float]] = {}

    def _get_or_create(self, session_id: str) -> SessionHealth:
        if session_id not in self._sessions:
            self._sessions[session_id] = SessionHealth(session_id=session_id)
        return self._sessions[session_id]

    def record_error(self, session_id: str, error_type: str) -> bool:
        """Record an error. Returns True if session should be recovered (3+ consecutive errors)."""
        health = self._get_or_create(session_id)
        health.consecutive_errors += 1
        health.last_error_type = error_type

        should_recover = health.consecutive_errors >= self.CONSECUTIVE_ERROR_THRESHOLD
        if should_recover:
            logger.warning(
                "Session %s has %d consecutive errors (%s) — recovery recommended",
                session_id, health.consecutive_errors, error_type,
            )
        return should_recover

    def record_success(self, session_id: str) -> None:
        """Record success, resetting consecutive error counter."""
        health = self._get_or_create(session_id)
        health.consecutive_errors = 0
        health.last_error_type = ""

    def can_recover(self, channel_id: str) -> bool:
        """Check if recovery is allowed (max 2 per channel per hour)."""
        now = time.monotonic()
        timestamps = self._recovery_timestamps.get(channel_id, [])

        # Filter to last hour only
        recent = [t for t in timestamps if now - t < 3600]
        self._recovery_timestamps[channel_id] = recent

        return len(recent) < 2

    def record_recovery(self, channel_id: str) -> None:
        """Record that a recovery was performed."""
        now = time.monotonic()
        if channel_id not in self._recovery_timestamps:
            self._recovery_timestamps[channel_id] = []
        self._recovery_timestamps[channel_id].append(now)
        logger.info("Recovery recorded for channel %s", channel_id)


# -- 4. Voice Backend Health Check --

async def check_voice_backends(
    stt_url: str, tts_url: str, timeout: float = 5.0
) -> dict[str, bool]:
    """Check if STT and TTS backends are reachable.

    Returns {"stt": bool, "tts": bool}.
    Uses aiohttp to hit {url}/health endpoint.
    """
    try:
        import aiohttp
    except ImportError:
        logger.warning("aiohttp not installed — cannot check voice backends")
        return {"stt": False, "tts": False}

    results: dict[str, bool] = {"stt": False, "tts": False}

    async def _check(name: str, url: str) -> None:
        try:
            async with aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=timeout)
            ) as session:
                async with session.get(f"{url}/health") as resp:
                    results[name] = resp.status == 200
        except Exception as e:
            logger.debug("Voice backend %s at %s unreachable: %s", name, url, e)
            results[name] = False

    await asyncio.gather(
        _check("stt", stt_url),
        _check("tts", tts_url),
    )

    logger.info("Voice backend health: stt=%s, tts=%s", results["stt"], results["tts"])
    return results
