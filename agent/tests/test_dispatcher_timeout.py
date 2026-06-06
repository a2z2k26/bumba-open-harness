"""Tests for dispatcher executor timeout enforcement (issue #627).

4 of 5 executors ignored wo.constraints.timeout_ms. The dispatcher must wrap
every executor.execute(wo) call in asyncio.wait_for so a single hung executor
cannot block the bridge main path indefinitely.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

# ---------------------------------------------------------------------------
# Static analysis guard — fail fast if the fix is absent
# ---------------------------------------------------------------------------

def test_dispatcher_source_uses_wait_for() -> None:
    """dispatcher.py must use asyncio.wait_for for every executor call."""
    src = Path(__file__).parent.parent / "bridge" / "dispatcher.py"
    text = src.read_text()
    assert "import asyncio" in text, "dispatcher.py must import asyncio"
    assert "asyncio.wait_for" in text, "dispatcher.py must use asyncio.wait_for for executor calls"
    assert "asyncio.TimeoutError" in text, "dispatcher.py must handle asyncio.TimeoutError"
    assert "executor timeout" in text, "dispatcher.py must return fallthrough reason 'executor timeout'"


def test_dispatcher_records_timeout_fallthrough() -> None:
    """On TimeoutError the dispatcher must call record_dispatch_fallthrough('timeout')."""
    src = Path(__file__).parent.parent / "bridge" / "dispatcher.py"
    text = src.read_text()
    # Must call the helper with "timeout" label
    assert 'record_dispatch_fallthrough("timeout")' in text, (
        "dispatcher must record fallthrough metric with reason='timeout'"
    )


# ---------------------------------------------------------------------------
# Runtime behaviour test — requires bridge package on sys.path
# ---------------------------------------------------------------------------

def _ensure_bridge_on_path() -> bool:
    """Return True if bridge package can be imported."""
    agent_root = Path(__file__).parent.parent.parent  # agent/
    if str(agent_root) not in sys.path:
        sys.path.insert(0, str(agent_root))
    try:
        import bridge.work_order  # noqa: F401
        return True
    except ImportError:
        return False


@pytest.mark.asyncio
async def test_dispatcher_enforces_timeout_ms() -> None:
    """A slow executor must cause _run_executor to return handled=False with 'executor timeout' reason."""
    if not _ensure_bridge_on_path():
        pytest.skip("bridge package not importable — skipping runtime test")

    from bridge.dispatcher import Dispatcher, DispatchResult
    from bridge.work_order import (
        Environment,
        WorkOrder,
        WorkOrderStatus,
        WorkOrderConstraints,
        WorkOrderAssignment,
    )

    # Build a minimal WorkOrder with a 10 ms timeout
    wo = WorkOrder(
        skill="test-skill",
        intent="test intent",
        environment=Environment.SUBAGENT,
        status=WorkOrderStatus.ASSIGNED,
        constraints=WorkOrderConstraints(timeout_ms=10),  # 10 ms → expires fast
        assignment=WorkOrderAssignment(agent_id="agent-1"),
    )

    # A mock executor that sleeps longer than the timeout
    async def _slow_execute(_wo: Any) -> Any:
        await asyncio.sleep(10)  # 10 seconds — well beyond the 10 ms timeout

    mock_executor = MagicMock()
    mock_executor.execute = _slow_execute

    dispatcher = Dispatcher.__new__(Dispatcher)
    result = await dispatcher._run_executor(mock_executor, wo, "subagent")

    assert isinstance(result, DispatchResult)
    assert result.valid is True
    assert result.handled is False
    assert result.reason == "executor timeout"


@pytest.mark.asyncio
async def test_dispatcher_passes_through_on_success() -> None:
    """A fast executor must complete and return handled=True."""
    if not _ensure_bridge_on_path():
        pytest.skip("bridge package not importable — skipping runtime test")

    from bridge.dispatcher import Dispatcher, DispatchResult
    from bridge.work_order import (
        Environment,
        WorkOrder,
        WorkOrderStatus,
        WorkOrderConstraints,
        WorkOrderAssignment,
    )

    wo = WorkOrder(
        skill="test-skill",
        intent="test intent",
        environment=Environment.SUBAGENT,
        status=WorkOrderStatus.ASSIGNED,
        constraints=WorkOrderConstraints(timeout_ms=5000),  # 5 s — plenty
        assignment=WorkOrderAssignment(agent_id="agent-1"),
    )

    # Mock result object that is not an error
    mock_result = MagicMock()
    mock_result.is_error = False

    async def _fast_execute(_wo: Any) -> Any:
        return mock_result

    mock_executor = MagicMock()
    mock_executor.execute = _fast_execute

    dispatcher = Dispatcher.__new__(Dispatcher)
    result = await dispatcher._run_executor(mock_executor, wo, "subagent")

    assert isinstance(result, DispatchResult)
    assert result.valid is True
    assert result.handled is True
    assert result.result is mock_result
