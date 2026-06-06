"""Structured JSON logging for the Bumba bridge.

Provides:
- JSONFormatter: outputs each log record as a single JSON line
- CorrelationFilter: injects run_id / session_id / message_id into every record
- set_message_context(): sets correlation IDs for the current async task
"""

from __future__ import annotations

import json
import logging
import traceback
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import Any

# ---------------------------------------------------------------------------
# Context variables — one per correlation dimension
# ---------------------------------------------------------------------------
_run_id: ContextVar[str] = ContextVar("_run_id", default="")
_session_id: ContextVar[str] = ContextVar("_session_id", default="")
_message_id: ContextVar[str] = ContextVar("_message_id", default="")

# Standard LogRecord attributes that should NOT leak into the JSON "extras"
_STANDARD_ATTRS = frozenset({
    "args",
    "created",
    "exc_info",
    "exc_text",
    "filename",
    "funcName",
    "levelname",
    "levelno",
    "lineno",
    "module",
    "msecs",
    "message",
    "msg",
    "name",
    "pathname",
    "process",
    "processName",
    "relativeCreated",
    "stack_info",
    "taskName",
    "thread",
    "threadName",
    # Correlation IDs injected by CorrelationFilter — handled explicitly
    "run_id",
    "session_id",
    "message_id",
})


def set_message_context(session_id: str = "", message_id: str = "") -> None:
    """Set correlation IDs for the current async task / context."""
    _session_id.set(session_id)
    _message_id.set(message_id)


def clear_message_context() -> None:
    """Reset correlation IDs for the current async task / context.

    Call this from a ``finally`` block at the end of any correlated
    work-unit (message-processing handler, ClaudeRunner.invoke, services
    runner) so context never leaks across handler boundaries even when
    an exception unwinds through the entry point.
    """
    _session_id.set("")
    _message_id.set("")


# ---------------------------------------------------------------------------
# CorrelationFilter
# ---------------------------------------------------------------------------
class CorrelationFilter(logging.Filter):
    """Injects ``run_id``, ``session_id``, and ``message_id`` into every log record.

    ``run_id`` is fixed at construction time (one per bridge process).
    ``session_id`` and ``message_id`` are pulled from :mod:`contextvars` so
    they propagate correctly across ``asyncio`` tasks.
    """

    def __init__(self, run_id: str = "", name: str = "") -> None:
        super().__init__(name)
        self._run_id = run_id

    def filter(self, record: logging.LogRecord) -> bool:  # noqa: A003
        record.run_id = self._run_id  # type: ignore[attr-defined]
        record.session_id = _session_id.get()  # type: ignore[attr-defined]
        record.message_id = _message_id.get()  # type: ignore[attr-defined]
        return True


# ---------------------------------------------------------------------------
# JSONFormatter
# ---------------------------------------------------------------------------
class JSONFormatter(logging.Formatter):
    """Formats each log record as a single-line JSON object.

    Output schema::

        {
            "timestamp": "2026-03-13T10:05:00.123000Z",
            "level": "INFO",
            "logger": "bridge.app",
            "message": "...",
            "run_id": "...",
            "session_id": "...",
            "message_id": "...",
            // optional
            "exception": {"type": "...", "message": "...", "traceback": "..."},
            // any extra fields passed via `extra={}`
        }
    """

    def format(self, record: logging.LogRecord) -> str:
        # Build the core payload
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc)
            .isoformat(timespec="microseconds")
            .replace("+00:00", "Z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "run_id": getattr(record, "run_id", ""),
            "session_id": getattr(record, "session_id", ""),
            "message_id": getattr(record, "message_id", ""),
        }

        # Exception info
        if record.exc_info and record.exc_info[0] is not None:
            exc_type, exc_value, exc_tb = record.exc_info
            payload["exception"] = {
                "type": exc_type.__name__ if exc_type else "",
                "message": str(exc_value) if exc_value else "",
                "traceback": "".join(traceback.format_exception(exc_type, exc_value, exc_tb)),
            }

        # Collect any extra attributes that aren't part of the standard set
        for key, value in record.__dict__.items():
            if key.startswith("_") or key in _STANDARD_ATTRS:
                continue
            if key in payload:
                continue
            payload[key] = value

        return json.dumps(payload, default=str)
