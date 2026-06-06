"""OAuth token refresher: background task to keep Claude Code access token fresh."""

from __future__ import annotations

import asyncio
import json
import logging
import time
import urllib.request
import urllib.error
import urllib.parse
from collections.abc import Callable, Coroutine
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Claude Code OAuth constants (from Claude Code source)
OAUTH_TOKEN_URL = "https://console.anthropic.com/v1/oauth/token"
_CLIENT_ID = "9d1c250a-e61b-44d9-88ed-5944d1962f5e"

# Refresh proactively: 1 hour before expiry, or every 6 hours if no expiry known
_REFRESH_MARGIN_S = 3600
REFRESH_INTERVAL_SECONDS = 6 * 3600
_MILLISECONDS_EPOCH_THRESHOLD = 10_000_000_000


def _normalize_expires_at(value: int | float) -> float:
    """Return a Unix expiry timestamp in seconds.

    Older callers pass milliseconds; RuntimeSecrets passes seconds. Values
    above year-2286 seconds are treated as milliseconds.
    """
    if not value:
        return 0.0
    expires_at = float(value)
    if expires_at > _MILLISECONDS_EPOCH_THRESHOLD:
        return expires_at / 1000.0
    return expires_at


class TokenRefresher:
    """Manages OAuth token lifecycle for the bridge.

    Holds the current access token in memory and refreshes it
    using the refresh_token before it expires. Updates .secrets
    file so the token persists across bridge restarts.
    """

    def __init__(
        self,
        access_token: str,
        refresh_token: str,
        secrets_file: str = "",
        expires_at_ms: int = 0,
        alert_callback: Callable[[str], Coroutine[Any, Any, None]] | None = None,
    ) -> None:
        self._access_token = access_token
        self._refresh_token = refresh_token
        self._secrets_file = secrets_file or str(Path.home() / "data" / ".secrets")
        self._expires_at = _normalize_expires_at(expires_at_ms)
        self._alert_callback = alert_callback
        self._on_refresh_callback: Callable[[], Coroutine[Any, Any, None]] | None = None
        self._task: asyncio.Task[None] | None = None
        self._lock = asyncio.Lock()

    def set_on_refresh(self, callback: Callable[[], Coroutine[Any, Any, None]]) -> None:
        """Register a callback to fire after each successful token refresh."""
        self._on_refresh_callback = callback

    @property
    def access_token(self) -> str:
        """Current valid access token."""
        return self._access_token

    def start(self) -> None:
        """Start the background refresh loop."""
        if not self._refresh_token:
            logger.warning("No refresh token — token refresh disabled")
            return
        self._task = asyncio.create_task(self._refresh_loop())
        logger.info("Token refresher started (expires_at=%.0f)", self._expires_at)

    async def stop(self) -> None:
        """Stop the background refresh loop."""
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _refresh_loop(self) -> None:
        """Periodically refresh the access token before it expires."""
        while True:
            try:
                wait_time = self._next_refresh_delay()
                logger.info(
                    "Next token refresh in %d seconds (%.1f hours)",
                    wait_time, wait_time / 3600,
                )
                await asyncio.sleep(wait_time)

                async with self._lock:
                    await self._do_refresh()

            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error(
                    "Token refresh failed: %s. "
                    "OAuth tokens may expire — Claude calls will fail. "
                    "Check .secrets file and Anthropic OAuth endpoint.", e
                )
                if self._alert_callback:
                    try:
                        await self._alert_callback(
                            f"[ALERT] Token refresh failed: {e}\nRetrying in 5 minutes."
                        )
                    except Exception:
                        pass
                # Retry in 5 minutes on failure
                await asyncio.sleep(300)

    def _next_refresh_delay(self) -> float:
        """Calculate seconds until next refresh is needed."""
        if self._expires_at > 0:
            remaining = self._expires_at - time.time()
            # Refresh 1 hour before expiry
            delay = max(remaining - _REFRESH_MARGIN_S, 60)
            # But don't wait longer than 6 hours
            return min(delay, REFRESH_INTERVAL_SECONDS)
        # No expiry info: refresh every 6 hours
        return REFRESH_INTERVAL_SECONDS

    async def _do_refresh(self) -> None:
        """Call the OAuth token endpoint to get a new access token."""
        logger.info("Refreshing OAuth access token...")

        # Run the blocking HTTP call in a thread
        result = await asyncio.to_thread(self._call_refresh_endpoint)

        if result is None:
            raise RuntimeError("Refresh endpoint returned no data")

        new_access = result.get("access_token", "")
        new_refresh = result.get("refresh_token", "")
        expires_in = result.get("expires_in", 0)

        if not new_access:
            raise RuntimeError(f"No access_token in refresh response: {list(result.keys())}")

        old_len = len(self._access_token)
        self._access_token = new_access

        # Update refresh token if a new one was issued
        if new_refresh:
            self._refresh_token = new_refresh

        # Update expiry
        if expires_in:
            self._expires_at = time.time() + expires_in
        else:
            self._expires_at = 0.0

        logger.info(
            "Token refreshed: %d→%d chars, expires_in=%ds",
            old_len, len(new_access), expires_in,
        )

        # Persist to .secrets file
        await asyncio.to_thread(self._update_secrets_file)

        # Notify subscribers (e.g. warm process needs to cycle for new token)
        if self._on_refresh_callback:
            try:
                await self._on_refresh_callback()
            except Exception as e:
                logger.warning("Post-refresh callback failed: %s", e)

    def _call_refresh_endpoint(self) -> dict[str, Any]:
        """Synchronous HTTP POST to the OAuth refresh endpoint."""
        data = urllib.parse.urlencode({
            "grant_type": "refresh_token",
            "client_id": _CLIENT_ID,
            "refresh_token": self._refresh_token,
        }).encode("utf-8")

        req = urllib.request.Request(
            OAUTH_TOKEN_URL,
            data=data,
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "User-Agent": "claude-code/1.0",
                "Accept": "application/json",
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310
                body = resp.read().decode("utf-8")
                parsed = json.loads(body)
                if not isinstance(parsed, dict):
                    raise RuntimeError(
                        f"OAuth refresh returned non-dict payload: "
                        f"{type(parsed).__name__}"
                    )
                # Narrow JSON object to dict[str, Any] at the boundary;
                # the server contract is a JSON object so non-string keys
                # would be a server-side bug, not something to coerce
                # silently.
                return {str(k): v for k, v in parsed.items()}
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")
            logger.error(
                "OAuth refresh HTTP %d: %s", e.code, body[:500],
            )
            raise RuntimeError(f"OAuth refresh failed: HTTP {e.code}") from e
        except urllib.error.URLError as e:
            raise RuntimeError(f"OAuth refresh network error: {e.reason}") from e

    def _update_secrets_file(self) -> None:
        """Rewrite the .secrets file with the new token values (atomic write)."""
        import os

        path = Path(self._secrets_file)
        if not path.exists():
            logger.warning("Secrets file not found: %s", path)
            return

        lines = path.read_text().splitlines()
        new_lines = []
        found_access = False
        found_refresh = False

        for line in lines:
            stripped = line.strip()
            if stripped.startswith("claude_oauth_token="):
                new_lines.append(f"claude_oauth_token={self._access_token}")
                found_access = True
            elif stripped.startswith("claude_oauth_refresh_token="):
                new_lines.append(f"claude_oauth_refresh_token={self._refresh_token}")
                found_refresh = True
            else:
                new_lines.append(line)

        if not found_access:
            new_lines.append(f"claude_oauth_token={self._access_token}")
        if not found_refresh and self._refresh_token:
            new_lines.append(f"claude_oauth_refresh_token={self._refresh_token}")

        # Atomic write: write to temp file in same dir, then rename
        content = "\n".join(new_lines) + "\n"
        tmp_path = path.with_suffix(".tmp")
        tmp_path.write_text(content)
        os.chmod(tmp_path, 0o600)  # ensure 0600 before atomic rename
        os.rename(str(tmp_path), str(path))  # atomic on POSIX same-filesystem
        logger.info("Secrets file updated atomically: %s", path)
