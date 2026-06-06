"""Executor Protocol — all execution environments implement this.

All executors are async. Exceptions MUST propagate to the dispatcher,
which decides whether to wrap them into a DispatchResult(handled=False)
or re-raise. Executors never swallow exceptions silently.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from bridge.claude_runner import ClaudeResult
    from bridge.work_order import WorkOrder


@runtime_checkable
class Executor(Protocol):
    """An execution environment for WorkOrders.

    Implementations must be async and return a ClaudeResult. They must
    NOT swallow exceptions — any exception propagates to the dispatcher,
    which wraps it into a DispatchResult with handled=False.
    """

    async def execute(self, wo: "WorkOrder") -> "ClaudeResult":
        """Execute a WorkOrder and return the result.

        Args:
            wo: The WorkOrder to execute. Must be in ASSIGNED status.

        Returns:
            ClaudeResult from the execution environment.

        Raises:
            RuntimeError: If the executor is not properly configured.
            Any exception from the underlying execution environment.
        """
        ...
