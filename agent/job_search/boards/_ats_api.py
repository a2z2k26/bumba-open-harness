"""Shared HTTP + retry helper for ATS-board scrapers (Sprint 06.05).

Used by ``ashby_jobs.py`` (06.05), ``greenhouse_jobs.py`` (06.06), and
``lever_jobs.py`` (06.07). Public API is one coroutine: ``fetch_with_retry``.

Retry policy is exponential backoff with jitter on 5xx and on transport
errors. 4xx is returned to the caller as ``None`` (the per-board parser
decides whether a 404 should be silenced or surfaced — Ashby returns 404
for unknown org tokens, which is a "not configured" signal, not an
outage). Rate-limit handling is the caller's job; this helper does not
share state across calls.
"""
from __future__ import annotations

import asyncio
import logging
import random
from typing import Any

import aiohttp

log = logging.getLogger(__name__)

_USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"

DEFAULT_TIMEOUT_SECONDS: float = 30.0
DEFAULT_MAX_RETRIES: int = 3
_BACKOFF_BASE_SECONDS: float = 0.5


async def fetch_with_retry(
    url: str,
    *,
    headers: dict[str, str] | None = None,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    max_retries: int = DEFAULT_MAX_RETRIES,
    session: aiohttp.ClientSession | None = None,
) -> dict[str, Any] | None:
    """Fetch ``url`` and parse JSON, retrying on transient failures.

    Returns the parsed JSON object on success, ``None`` on persistent
    failure (4xx after no retry, or 5xx / transport error after
    ``max_retries`` attempts). Never raises — board scrapers operate as
    best-effort and an empty result is preferable to crashing the
    scrape phase.

    The optional ``session`` arg lets callers share a single
    ``aiohttp.ClientSession`` across many requests (e.g. iterating the
    company list); if omitted, a new session is created per call.
    """
    merged_headers = {"User-Agent": _USER_AGENT}
    if headers:
        merged_headers.update(headers)

    own_session = session is None
    if own_session:
        session = aiohttp.ClientSession(headers=merged_headers)

    try:
        for attempt in range(max_retries):
            try:
                async with session.get(  # type: ignore[union-attr]
                    url,
                    headers=merged_headers,
                    timeout=aiohttp.ClientTimeout(total=timeout),
                ) as resp:
                    if 200 <= resp.status < 300:
                        return await resp.json(content_type=None)
                    if 400 <= resp.status < 500:
                        log.info(
                            "ATS fetch %s returned %d — not retrying",
                            url,
                            resp.status,
                        )
                        return None
                    log.warning(
                        "ATS fetch %s returned %d (attempt %d/%d)",
                        url,
                        resp.status,
                        attempt + 1,
                        max_retries,
                    )
            except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
                log.warning(
                    "ATS fetch %s failed (%s) (attempt %d/%d)",
                    url,
                    exc,
                    attempt + 1,
                    max_retries,
                )

            if attempt < max_retries - 1:
                delay = _BACKOFF_BASE_SECONDS * (2**attempt) + random.uniform(0, 0.25)
                await asyncio.sleep(delay)

        log.error("ATS fetch %s gave up after %d retries", url, max_retries)
        return None
    finally:
        if own_session:
            await session.close()  # type: ignore[union-attr]
