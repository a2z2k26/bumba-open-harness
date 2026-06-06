"""Tests for executor status surface (Sprint D-R5, #1935).

Covers:
- ``E2BExecutor.execute()`` raises ``RuntimeError`` (gate active) with the
  roadmap reference in the message when not routable
- ``Dispatcher.get_executor_statuses()`` returns the expected status map
- Each executor class docstring carries its status marker
- Docstring references the canonical roadmap doc
"""
from __future__ import annotations

import asyncio
import inspect
from unittest.mock import MagicMock

import pytest

from bridge.executors.department import DepartmentExecutor
from bridge.executors.e2b import E2B_GATE_MESSAGE, E2BExecutor
from bridge.executors.subagent import SubagentExecutor
from bridge.executors.tmux import TmuxExecutor
from bridge.executors.worktree import WorktreeExecutor


# ---------------------------------------------------------------------------
# E2B gate — explicit RuntimeError with roadmap reference when non-routable
# (post-#416: execute() drives a real sandbox run when flag+key+runner present;
# the gate now raises RuntimeError, not NotImplementedError)
# ---------------------------------------------------------------------------


def test_e2b_executor_raises_with_roadmap_reference() -> None:
    """The error message must point readers at the activation checklist."""
    exec_ = E2BExecutor()
    wo = MagicMock()
    wo.id = "test-id-12345678"

    with pytest.raises(RuntimeError) as excinfo:
        asyncio.run(exec_.execute(wo))

    msg = str(excinfo.value)
    assert "executor-roadmap.md" in msg, (
        f"E2B gate message must reference the roadmap doc; got: {msg!r}"
    )
    assert "#416" in msg or "E2B_API_KEY" in msg, (
        f"E2B gate message must reference the credential gap; got: {msg!r}"
    )


def test_e2b_gate_message_constant_includes_roadmap() -> None:
    """The module-level constant carries the same reference."""
    assert "executor-roadmap.md" in E2B_GATE_MESSAGE


# ---------------------------------------------------------------------------
# Docstring status markers — one per executor class
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("executor_cls,expected_marker", [
    (SubagentExecutor, "ACTIVE"),
    (DepartmentExecutor, "ACTIVE"),
    (WorktreeExecutor, "ACTIVE"),  # active_low_traffic — substring match
    (TmuxExecutor, "CONDITIONAL"),
    (E2BExecutor, "CONDITIONAL"),
])
def test_executor_class_docstring_carries_status(executor_cls, expected_marker) -> None:
    """Each executor's class docstring must declare its status marker."""
    doc = executor_cls.__doc__ or ""
    assert expected_marker in doc, (
        f"{executor_cls.__name__} docstring must contain "
        f"status marker {expected_marker!r}; got: {doc[:200]!r}"
    )


@pytest.mark.parametrize("executor_cls", [
    SubagentExecutor, DepartmentExecutor, WorktreeExecutor,
    TmuxExecutor, E2BExecutor,
])
def test_executor_docstring_references_roadmap(executor_cls) -> None:
    """Each executor's class docstring must point at the roadmap doc."""
    doc = executor_cls.__doc__ or ""
    assert "executor-roadmap.md" in doc, (
        f"{executor_cls.__name__} docstring must reference roadmap; "
        f"got: {doc[:200]!r}"
    )


# ---------------------------------------------------------------------------
# Dispatcher.get_executor_statuses() — shape + content
# ---------------------------------------------------------------------------


def test_get_executor_statuses_returns_all_routes() -> None:
    """Every executor in the dispatcher's table appears in the status
    map plus tmux (whether wired or not)."""
    from bridge.dispatcher import Dispatcher
    from bridge.work_order import Environment

    dispatcher = Dispatcher.__new__(Dispatcher)
    # Minimal _executors: subagent + department + worktree + e2b (tmux off)
    dispatcher._executors = {
        Environment.SUBAGENT: MagicMock(),
        Environment.DEPARTMENT: MagicMock(),
        Environment.WORKTREE: MagicMock(),
        Environment.E2B: MagicMock(),
    }

    statuses = dispatcher.get_executor_statuses()
    assert "subagent" in statuses
    assert "department" in statuses
    assert "worktree" in statuses
    assert "e2b" in statuses
    assert "tmux" in statuses


def test_get_executor_statuses_marks_tmux_unwired_when_absent() -> None:
    """Without TMUX in the executor table, tmux status is conditional_unwired."""
    from bridge.dispatcher import Dispatcher
    from bridge.work_order import Environment

    dispatcher = Dispatcher.__new__(Dispatcher)
    dispatcher._executors = {
        Environment.SUBAGENT: MagicMock(),
        Environment.DEPARTMENT: MagicMock(),
    }

    statuses = dispatcher.get_executor_statuses()
    assert statuses["tmux"] == "conditional_unwired"


def test_get_executor_statuses_marks_tmux_active_when_wired() -> None:
    """When TMUX is in the executor table, status is conditional_active."""
    from bridge.dispatcher import Dispatcher
    from bridge.work_order import Environment

    dispatcher = Dispatcher.__new__(Dispatcher)
    dispatcher._executors = {
        Environment.SUBAGENT: MagicMock(),
        Environment.TMUX: MagicMock(),
    }

    statuses = dispatcher.get_executor_statuses()
    assert statuses["tmux"] == "conditional_active"


def test_get_executor_statuses_marks_default_e2b_conditional_unwired() -> None:
    """Default-off E2B is visible but not routable."""
    from bridge.dispatcher import Dispatcher
    from bridge.work_order import Environment

    dispatcher = Dispatcher.__new__(Dispatcher)
    dispatcher._executors = {
        Environment.E2B: E2BExecutor(),
    }

    statuses = dispatcher.get_executor_statuses()
    assert statuses["e2b"] == "conditional_unwired"


def test_get_executor_statuses_marks_flag_key_without_runner_unwired() -> None:
    """Flag + key but no wired runner is still non-routable."""
    from bridge.dispatcher import Dispatcher
    from bridge.work_order import Environment

    dispatcher = Dispatcher.__new__(Dispatcher)
    dispatcher._executors = {
        Environment.E2B: E2BExecutor(enabled=True, api_key="e2b-test-key"),
    }

    statuses = dispatcher.get_executor_statuses()
    assert statuses["e2b"] == "conditional_unwired"


def test_get_executor_statuses_marks_fully_wired_e2b_conditional_active() -> None:
    """Flag + key + runner makes E2B routable (conditional_active)."""
    from unittest.mock import AsyncMock

    from bridge.dispatcher import Dispatcher
    from bridge.work_order import Environment

    dispatcher = Dispatcher.__new__(Dispatcher)
    dispatcher._executors = {
        Environment.E2B: E2BExecutor(
            enabled=True, api_key="e2b-test-key", claude_runner=AsyncMock()
        ),
    }

    statuses = dispatcher.get_executor_statuses()
    assert statuses["e2b"] == "conditional_active"


def test_get_executor_statuses_worktree_is_active_low_traffic() -> None:
    """WORKTREE is wired but rarely picked — distinct status from active."""
    from bridge.dispatcher import Dispatcher
    from bridge.work_order import Environment

    dispatcher = Dispatcher.__new__(Dispatcher)
    dispatcher._executors = {
        Environment.WORKTREE: MagicMock(),
    }

    statuses = dispatcher.get_executor_statuses()
    assert statuses["worktree"] == "active_low_traffic"


# ---------------------------------------------------------------------------
# Async signature on E2B (regression — the executor protocol requires async)
# ---------------------------------------------------------------------------


def test_e2b_execute_is_coroutine_function() -> None:
    """E2BExecutor.execute must remain async even though it only raises."""
    assert inspect.iscoroutinefunction(E2BExecutor.execute)
