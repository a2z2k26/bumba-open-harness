"""Executor Protocol contract tests — S02a (#561).

AC-1: Executor Protocol has exactly one public method `execute` (async,
takes WorkOrder, returns ClaudeResult).
"""
from __future__ import annotations

import inspect

from bridge.executors.base import Executor


def test_executor_protocol_has_exactly_one_method():
    """Protocol defines `execute` and nothing else (ignoring dunders)."""
    public = [m for m in dir(Executor) if not m.startswith("_")]
    assert public == ["execute"], f"expected only 'execute', got {public}"


def test_executor_protocol_execute_is_async():
    """`execute` is an async method."""
    assert inspect.iscoroutinefunction(Executor.execute)


def test_executor_protocol_execute_signature():
    """`execute(self, wo: WorkOrder) -> ClaudeResult` shape."""
    sig = inspect.signature(Executor.execute)
    params = list(sig.parameters.values())
    # self + wo
    assert len(params) == 2
    # annotation may be a forward-ref string when under TYPE_CHECKING
    ann = params[1].annotation
    ann_name = ann.__name__ if hasattr(ann, "__name__") else str(ann).strip("'\"")
    assert ann_name == "WorkOrder", f"expected WorkOrder annotation, got {ann!r}"
