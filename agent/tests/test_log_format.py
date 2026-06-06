"""Tests for bridge.log_format — structured JSON logging."""

from __future__ import annotations

import asyncio
import json
import logging

import pytest

from bridge.log_format import (
    CorrelationFilter,
    JSONFormatter,
    set_message_context,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _make_logger(
    name: str = "test",
    run_id: str = "",
) -> tuple[logging.Logger, logging.Handler, list[str]]:
    """Create an isolated logger with JSONFormatter + CorrelationFilter.

    Returns (logger, handler, output_lines) where *output_lines* is a list
    that accumulates formatted strings emitted by the handler.
    """

    class ListHandler(logging.Handler):
        def __init__(self, sink: list[str]) -> None:
            super().__init__()
            self.sink = sink

        def emit(self, record: logging.LogRecord) -> None:
            self.sink.append(self.format(record))

    lines: list[str] = []
    handler = ListHandler(lines)
    handler.setFormatter(JSONFormatter())
    handler.addFilter(CorrelationFilter(run_id=run_id))

    logger = logging.getLogger(f"test.{name}.{id(lines)}")
    logger.handlers.clear()
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG)
    logger.propagate = False

    return logger, handler, lines


# ---------------------------------------------------------------------------
# JSONFormatter tests
# ---------------------------------------------------------------------------
class TestJSONFormatterBasic:
    def test_json_formatter_basic(self) -> None:
        """A plain log message produces valid JSON with required fields."""
        logger, _, lines = _make_logger("basic")

        logger.info("hello world")

        assert len(lines) == 1
        data = json.loads(lines[0])

        assert data["level"] == "INFO"
        assert data["message"] == "hello world"
        assert "timestamp" in data
        assert data["timestamp"].endswith("Z")
        assert "logger" in data
        # Correlation IDs present (empty strings because none set)
        for key in ("run_id", "session_id", "message_id"):
            assert key in data

    def test_json_formatter_exception(self) -> None:
        """A log record with exception info includes type/message/traceback."""
        logger, _, lines = _make_logger("exc")

        try:
            raise ValueError("boom")
        except ValueError:
            logger.exception("something broke")

        data = json.loads(lines[0])
        assert "exception" in data
        exc = data["exception"]
        assert exc["type"] == "ValueError"
        assert exc["message"] == "boom"
        assert "Traceback" in exc["traceback"]
        assert "ValueError: boom" in exc["traceback"]

    def test_json_formatter_non_serializable(self) -> None:
        """Non-serializable extra values fall back to str()."""

        class Unserializable:
            def __repr__(self) -> str:
                return "<Unserializable>"

        logger, _, lines = _make_logger("nonser")

        logger.info("with extra", extra={"widget": Unserializable()})

        data = json.loads(lines[0])
        assert data["widget"] == "<Unserializable>"


# ---------------------------------------------------------------------------
# CorrelationFilter tests
# ---------------------------------------------------------------------------
class TestCorrelationFilter:
    def test_correlation_filter_run_id(self) -> None:
        """Every record gets the run_id passed at construction time."""
        logger, _, lines = _make_logger("runid", run_id="run-abc-123")

        logger.warning("test msg")

        data = json.loads(lines[0])
        assert data["run_id"] == "run-abc-123"

    def test_correlation_context_vars(self) -> None:
        """set_message_context values appear in log output."""
        logger, _, lines = _make_logger("ctxvars", run_id="r1")

        set_message_context(session_id="sess-42", message_id="msg-99")
        try:
            logger.info("correlated")
        finally:
            # Reset so other tests are not affected
            set_message_context()

        data = json.loads(lines[0])
        assert data["session_id"] == "sess-42"
        assert data["message_id"] == "msg-99"
        assert data["run_id"] == "r1"

    @pytest.mark.asyncio
    async def test_correlation_async_isolation(self) -> None:
        """Two concurrent async tasks with different message_ids don't interfere."""
        logger, _, lines = _make_logger("asynciso", run_id="r-iso")

        barrier = asyncio.Barrier(2)

        async def task(msg_id: str, label: str) -> None:
            set_message_context(session_id="shared-sess", message_id=msg_id)
            # Synchronise so both tasks are alive at the same time
            await barrier.wait()
            logger.info(label)

        await asyncio.gather(
            task("msg-A", "from_task_a"),
            task("msg-B", "from_task_b"),
        )

        assert len(lines) == 2
        parsed = {json.loads(line)["message"]: json.loads(line) for line in lines}

        assert parsed["from_task_a"]["message_id"] == "msg-A"
        assert parsed["from_task_b"]["message_id"] == "msg-B"
        # Both share the same session_id
        assert parsed["from_task_a"]["session_id"] == "shared-sess"
        assert parsed["from_task_b"]["session_id"] == "shared-sess"
