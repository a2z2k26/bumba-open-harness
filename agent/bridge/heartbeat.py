"""Dead man's switch: periodic pings to healthchecks.io."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import TYPE_CHECKING

import aiohttp

if TYPE_CHECKING:
    from .health import HealthServer

logger = logging.getLogger(__name__)


class HeartbeatPinger:
    """Pings healthchecks.io every `interval` seconds with bridge health status.

    If health is "degraded" or "unhealthy", pings the /fail endpoint instead.
    If no check_url is configured, the pinger does nothing.

    Sprint 07.09 — exposes ``last_ping_at`` (Unix timestamp of the most
    recent successful ping, or ``None`` if no ping has fired yet) so the
    ``/api/heartbeat/status`` route can report it. Ping failures do NOT
    update the field — operators want to see the last *known-good* tick,
    not the last attempt.
    """

    def __init__(
        self,
        check_url: str | None,
        health_server: HealthServer,
        interval: int = 300,
    ) -> None:
        self._check_url = check_url
        self._health = health_server
        self._interval = interval
        self._task: asyncio.Task | None = None
        self.last_ping_at: float | None = None

    async def start(self) -> None:
        """Start the background ping loop."""
        if not self._check_url:
            logger.info("Heartbeat pinger: no check URL configured, skipping")
            return
        self._task = asyncio.create_task(self._loop())
        logger.info("Heartbeat pinger started (interval=%ds)", self._interval)

    async def stop(self) -> None:
        """Stop the background ping loop."""
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _loop(self) -> None:
        timeout = aiohttp.ClientTimeout(total=10)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            while True:
                try:
                    await asyncio.sleep(self._interval)
                    await self._ping(session)
                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    logger.warning("Heartbeat ping failed: %s", e)

    async def _ping(self, session: aiohttp.ClientSession) -> None:
        """Send one ping to healthchecks.io."""
        health = await self._health.collect_health()
        url = self._check_url
        if health["status"] in ("degraded", "unhealthy"):
            url += "/fail"

        body = json.dumps({
            "status": health["status"],
            "uptime": health["uptime_seconds"],
        })

        async with session.post(url, data=body) as resp:
            logger.debug("Heartbeat ping: %d", resp.status)
            # Sprint 07.09 — record only successful (HTTP 2xx) pings so the
            # /api/heartbeat/status route reflects last-known-good, not the
            # last attempt. Healthchecks.io returns 200 on success.
            if 200 <= resp.status < 300:
                self.last_ping_at = time.time()


async def ping_healthcheck(
    check_url: str | None,
    *,
    success: bool = True,
    error: str = "",
) -> None:
    """One-shot ping for service completion. Used by service runner."""
    if not check_url:
        return
    try:
        url = check_url if success else f"{check_url}/fail"
        timeout = aiohttp.ClientTimeout(total=10)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(url, data=error[:10000] if error else ""):
                pass
    except Exception as e:
        logger.warning("Healthcheck ping failed: %s", e)
