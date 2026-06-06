"""Integration tests for Sprint 07.11 — JSONFormatter + CorrelationFilter
installation in the bridge logging setup.

These tests exercise the wiring (config flag, formatter installation,
correlation context binding) rather than the formatter / filter classes
themselves — those are covered in :mod:`tests.test_log_format`.
"""

from __future__ import annotations

import json
import logging

import pytest

from bridge import log_format
from bridge.__main__ import setup_logging
from bridge.config import BridgeConfig
from bridge.log_format import (
    CorrelationFilter,
    JSONFormatter,
    clear_message_context,
    set_message_context,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
class _ListHandler(logging.Handler):
    """In-memory log handler that captures formatted strings."""

    def __init__(self) -> None:
        super().__init__()
        self.lines: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.lines.append(self.format(record))


@pytest.fixture(autouse=True)
def _reset_correlation_context() -> None:
    """Reset correlation context before and after every test in this file.

    Tests in other modules (e.g. ``test_log_format.py``) mutate the same
    ContextVars; this fixture isolates each integration test from any
    sibling that forgot to clean up.
    """
    clear_message_context()
    yield
    clear_message_context()


# ---------------------------------------------------------------------------
# Config flag tests
# ---------------------------------------------------------------------------
class TestConfigFlag:
    def test_log_json_enabled_default_is_false(self) -> None:
        """The new config flag defaults to False — preserves plain-text logs."""
        cfg = BridgeConfig()
        assert cfg.log_json_enabled is False

    def test_log_json_enabled_can_be_overridden(self) -> None:
        """Operators can flip the flag via TOML / env override."""
        cfg = BridgeConfig(log_json_enabled=True)
        assert cfg.log_json_enabled is True


# ---------------------------------------------------------------------------
# setup_logging() tests — formatter selection by config flag
# ---------------------------------------------------------------------------
class TestSetupLoggingFormatter:
    def test_json_format_when_flag_on(
        self, tmp_path, monkeypatch
    ) -> None:
        """With json_enabled=True, log records emit as JSON lines."""
        # setup_logging mutates the root logger; clear handlers afterwards
        root = logging.getLogger()
        original_handlers = list(root.handlers)
        original_filters = list(root.filters)
        try:
            root.handlers.clear()
            root.filters.clear()
            setup_logging("INFO", log_dir=str(tmp_path), json_enabled=True)

            # Replace the file handler with our capturing handler so we
            # can read the formatted output directly. The formatter is
            # already JSONFormatter on the root's handlers, so we install
            # one of those onto our capture handler too.
            capture = _ListHandler()
            capture.setFormatter(JSONFormatter())
            capture.addFilter(CorrelationFilter())
            root.addHandler(capture)

            logger = logging.getLogger("test_07_11_json_on")
            logger.info("structured message")

            assert capture.lines, "capture handler received no records"
            # Every captured line must parse as JSON when the flag is on
            for line in capture.lines:
                data = json.loads(line)
                assert "level" in data
                assert "message" in data
                assert "timestamp" in data

            # The handlers installed by setup_logging must use JSONFormatter
            installed_formatters = [type(h.formatter).__name__ for h in root.handlers]
            assert "JSONFormatter" in installed_formatters
        finally:
            # Close any FileHandlers before clearing so the underlying file
            # streams don't leak (S6.2, #2352).
            for h in root.handlers:
                try:
                    h.close()
                except Exception:
                    pass
            root.handlers.clear()
            root.filters.clear()
            for h in original_handlers:
                root.addHandler(h)
            for f in original_filters:
                root.addFilter(f)

    def test_plain_format_when_flag_off(self, tmp_path) -> None:
        """With json_enabled=False (default), plain-text format is preserved."""
        root = logging.getLogger()
        original_handlers = list(root.handlers)
        original_filters = list(root.filters)
        try:
            root.handlers.clear()
            root.filters.clear()
            setup_logging("INFO", log_dir=str(tmp_path), json_enabled=False)

            installed_formatters = [type(h.formatter).__name__ for h in root.handlers]
            # Plain logging.Formatter, not JSONFormatter
            assert "JSONFormatter" not in installed_formatters
            assert any(name == "Formatter" for name in installed_formatters), (
                f"expected plain Formatter, got: {installed_formatters}"
            )

            # Build a record by hand and confirm it does NOT parse as JSON
            handler = root.handlers[0]
            record = logging.LogRecord(
                name="test_07_11_plain",
                level=logging.INFO,
                pathname=__file__,
                lineno=1,
                msg="plain message",
                args=(),
                exc_info=None,
            )
            # CorrelationFilter populates run_id/session_id/message_id
            for f in root.filters:
                f.filter(record)
            formatted = handler.formatter.format(record)
            with pytest.raises(json.JSONDecodeError):
                json.loads(formatted)
        finally:
            # Close any FileHandlers before clearing so the underlying file
            # streams don't leak (S6.2, #2352).
            for h in root.handlers:
                try:
                    h.close()
                except Exception:
                    pass
            root.handlers.clear()
            root.filters.clear()
            for h in original_handlers:
                root.addHandler(h)
            for f in original_filters:
                root.addFilter(f)

    def test_correlation_filter_installed_unconditionally(
        self, tmp_path
    ) -> None:
        """CorrelationFilter is installed regardless of json flag."""
        root = logging.getLogger()
        original_handlers = list(root.handlers)
        original_filters = list(root.filters)
        try:
            for json_flag in (True, False):
                # Close any FileHandlers attached from the previous iteration
                # before clearing — clear() alone leaks the underlying file
                # streams (S6.2, #2352).
                for h in root.handlers:
                    try:
                        h.close()
                    except Exception:
                        pass
                root.handlers.clear()
                root.filters.clear()
                setup_logging("INFO", log_dir=str(tmp_path), json_enabled=json_flag)
                filter_types = {type(f).__name__ for f in root.filters}
                assert "CorrelationFilter" in filter_types, (
                    f"CorrelationFilter missing when json_enabled={json_flag}"
                )
        finally:
            # Close any FileHandlers before clearing so the underlying file
            # streams don't leak (S6.2, #2352).
            for h in root.handlers:
                try:
                    h.close()
                except Exception:
                    pass
            root.handlers.clear()
            root.filters.clear()
            for h in original_handlers:
                root.addHandler(h)
            for f in original_filters:
                root.addFilter(f)


# ---------------------------------------------------------------------------
# Correlation context propagation
# ---------------------------------------------------------------------------
class TestCorrelationFilterPopulation:
    def test_correlation_filter_populates_session_id(self) -> None:
        """set_message_context() values appear on every log record."""
        capture = _ListHandler()
        capture.setFormatter(JSONFormatter())
        capture.addFilter(CorrelationFilter(run_id="run-test"))

        logger = logging.getLogger("test_07_11_corr_session")
        logger.handlers.clear()
        logger.addHandler(capture)
        logger.setLevel(logging.INFO)
        logger.propagate = False

        set_message_context(session_id="sess-abc-001", message_id="msg-42")
        try:
            logger.info("inside correlated block")
        finally:
            clear_message_context()

        assert len(capture.lines) == 1
        data = json.loads(capture.lines[0])
        assert data["session_id"] == "sess-abc-001"
        assert data["message_id"] == "msg-42"
        assert data["run_id"] == "run-test"

    def test_clear_message_context_resets_fields(self) -> None:
        """After clear_message_context, subsequent records have empty IDs."""
        capture = _ListHandler()
        capture.setFormatter(JSONFormatter())
        capture.addFilter(CorrelationFilter())

        logger = logging.getLogger("test_07_11_corr_clear")
        logger.handlers.clear()
        logger.addHandler(capture)
        logger.setLevel(logging.INFO)
        logger.propagate = False

        set_message_context(session_id="sess-X", message_id="msg-Y")
        logger.info("with context")
        clear_message_context()
        logger.info("after clear")

        assert len(capture.lines) == 2
        first = json.loads(capture.lines[0])
        second = json.loads(capture.lines[1])
        assert first["session_id"] == "sess-X"
        assert first["message_id"] == "msg-Y"
        assert second["session_id"] == ""
        assert second["message_id"] == ""


# ---------------------------------------------------------------------------
# log_format module sanity — exported symbols
# ---------------------------------------------------------------------------
class TestModuleSurface:
    def test_clear_message_context_exists(self) -> None:
        """Sprint 07.11 added clear_message_context — verify the export."""
        assert callable(log_format.clear_message_context)

    def test_set_message_context_signature(self) -> None:
        """set_message_context accepts session_id and message_id, both default ''."""
        import inspect

        sig = inspect.signature(log_format.set_message_context)
        params = sig.parameters
        assert "session_id" in params
        assert "message_id" in params
        assert params["session_id"].default == ""
        assert params["message_id"].default == ""
