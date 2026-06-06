"""Shared helpers for route modules under ``bridge/api/``.

Split out of ``bridge.api_server`` during Sprint P6.2 (issue #1593). Pure
reorg: ``_error``, ``_ok``, ``_redact_heartbeat_url`` are byte-for-byte
moves from the original module. The originals remain re-exported from
``bridge.api_server`` for back-compat with anything that imports them
directly.
"""
from __future__ import annotations

from typing import Any

from aiohttp import web


def _error(message: str, status: int = 400) -> web.Response:
    return web.json_response({"error": message}, status=status)


def _ok(data: Any, status: int = 200) -> web.Response:
    return web.json_response(data, status=status)


def _redact_heartbeat_url(url: str | None) -> str | None:
    """Reduce a heartbeat ping URL to its host (Sprint 07.09).

    The full URL contains a secret check ID; the operator-facing status
    endpoint should reveal only the provider domain (e.g. ``hc-ping.com``)
    so a leaked status response never grants ping-write access.

    Returns the host string, or ``None`` when no URL is configured. If
    parsing fails the function falls back to ``None`` rather than leaking
    the raw URL.
    """
    if not url:
        return None
    try:
        from urllib.parse import urlparse
        parsed = urlparse(url)
        host = parsed.hostname
        return host or None
    except Exception:  # pragma: no cover — urlparse is very forgiving
        return None
