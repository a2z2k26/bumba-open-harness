"""Executor subpackage — execution environment Protocol and concrete classes.

Exports:
    Executor             — the Protocol all executors implement
    SubagentExecutor     — runs WorkOrders via claude -p subagent invocation
    DepartmentExecutor   — routes WorkOrders to Zone 4 department teams
    WorktreeExecutor     — runs WorkOrders in an isolated git worktree (S02b)
    TmuxExecutor         — runs WorkOrders via TmuxAgentManager (S02c)
    E2BExecutor          — runs WorkOrders in an E2B sandbox via the bumba-sandbox MCP (#416)
    availability_snapshot — per-executor availability map for ``/status`` (E.05 / #2012)
"""
from bridge.executors.base import Executor
from bridge.executors.subagent import SubagentExecutor
from bridge.executors.department import DepartmentExecutor
from bridge.executors.worktree import WorktreeExecutor
from bridge.executors.tmux import TmuxExecutor
from bridge.executors.e2b import E2BExecutor


def availability_snapshot() -> dict[str, str]:
    """Return per-executor availability for /status.

    Sprint **audit-2026-05-16.F.02** (#2075, audit finding SW-4): this is
    now a thin facade over :func:`bridge.executor_availability.default_provider`.
    The provider is the single source of truth for the executor
    availability surface; the legacy dict[str, str] form is preserved
    here so existing callers (``command_handlers/lifecycle.py``,
    ``status_render.format_executor_section``) keep working unchanged.

    Originally landed in sprint E.05 / #416.
    """
    from bridge.executor_availability import snapshot_as_legacy_dict
    return snapshot_as_legacy_dict()


__all__ = [
    "Executor",
    "SubagentExecutor",
    "DepartmentExecutor",
    "WorktreeExecutor",
    "TmuxExecutor",
    "E2BExecutor",
    "availability_snapshot",
]
