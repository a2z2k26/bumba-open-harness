"""Tests for the spawn_background_task supervision helper."""

from __future__ import annotations

import asyncio
import logging
from unittest.mock import MagicMock

from bridge import _async_supervision


def test_spawn_background_task_logs_exception():
    """A coroutine that raises must trigger logger.exception with the exc."""
    boom = RuntimeError("kaboom")

    async def explodes():
        raise boom

    mock_logger = MagicMock(spec=logging.Logger)

    async def run():
        task = _async_supervision.spawn_background_task(
            explodes(), name="explodes-test", logger=mock_logger
        )
        try:
            await task
        except RuntimeError:
            pass
        # Yield once so the done-callback runs.
        await asyncio.sleep(0)

    asyncio.run(run())

    assert mock_logger.exception.called, "logger.exception was not invoked"
    call = mock_logger.exception.call_args
    # Exception object must be passed via exc_info= so the traceback survives.
    assert call.kwargs.get("exc_info") is boom
    # Task name must appear in the positional args of the log call.
    assert "explodes-test" in call.args


def test_spawn_background_task_logs_cancellation_at_info_level():
    """A cancelled task must emit an INFO log mentioning the task name."""

    async def sleeps_forever():
        await asyncio.sleep(3600)

    mock_logger = MagicMock(spec=logging.Logger)

    async def run():
        task = _async_supervision.spawn_background_task(
            sleeps_forever(), name="sleeps-test", logger=mock_logger
        )
        # Let the task actually start running before cancelling.
        await asyncio.sleep(0)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        # Yield once so the done-callback runs.
        await asyncio.sleep(0)

    asyncio.run(run())

    assert mock_logger.info.called, "logger.info was not invoked on cancellation"
    call = mock_logger.info.call_args
    assert "sleeps-test" in call.args
    # And the exception path must NOT have fired.
    assert not mock_logger.exception.called
