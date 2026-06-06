"""Job Search department — Z4 registry-backed entry points.

Provides ``run_prepare`` as the PREPARE cron entry point.
Agent construction is handled by DepartmentRegistry / _factory.build_manager_agent;
this module is a thin orchestration wrapper.

Sprint D5.3: Replaces a hypothetical hand-rolled _build_director() with a
single registry.route("job_search", ...) call.
"""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from teams._registry import DepartmentRegistry
from teams._types import BridgeDeps, TeamResult

log = logging.getLogger(__name__)

_TEAMS_DIR = Path(__file__).parent.parent / "config" / "teams"
_TIMEOUT_PREPARE = 3600  # seconds — mirrors job_search.yaml constraints.timeout_seconds

# Module-level registry singleton (built lazily on first call)
_registry: DepartmentRegistry | None = None


def _get_registry() -> DepartmentRegistry:
    global _registry
    if _registry is None:
        _registry = DepartmentRegistry.from_directory(_TEAMS_DIR)
    return _registry


async def run_prepare(deps: BridgeDeps, *, intent: str = "prepare daily job search run") -> TeamResult:
    """Execute the PREPARE pipeline via the DepartmentRegistry.

    Wraps the registry route call with asyncio.timeout so runaway runs
    cannot hang the cron service indefinitely.

    Args:
        deps: BridgeDeps carrying all live app references.
        intent: Natural-language task description passed to the director.

    Returns:
        TeamResult with success flag, output, and cost metadata.
    """
    registry = _get_registry()

    try:
        async with asyncio.timeout(_TIMEOUT_PREPARE):
            result = await registry.route("job_search", intent, deps)
    except asyncio.TimeoutError:
        log.error(
            "job_search PREPARE timed out after %ds — session_id=%s",
            _TIMEOUT_PREPARE,
            deps.session_id,
        )
        # Publish timeout event best-effort
        try:
            deps.event_bus.publish("job_search.prepare.timeout", {
                "session_id": deps.session_id,
                "timeout_seconds": _TIMEOUT_PREPARE,
            })
        except Exception:
            pass
        return TeamResult(
            department="job_search",
            manager_output="",
            success=False,
            error=f"PREPARE timed out after {_TIMEOUT_PREPARE}s",
        )

    return result


async def run_execute(deps: BridgeDeps, *, intent: str = "execute approved job search applications") -> TeamResult:
    """Execute the EXECUTE pipeline via the DepartmentRegistry.

    The execute run is lighter than PREPARE so uses the outreach department
    for outreach sends and job_search for application submission.

    Args:
        deps: BridgeDeps carrying all live app references.
        intent: Natural-language task description.

    Returns:
        TeamResult with success flag, output, and cost metadata.
    """
    registry = _get_registry()

    try:
        async with asyncio.timeout(_TIMEOUT_PREPARE):
            result = await registry.route("job_search", intent, deps)
    except asyncio.TimeoutError:
        log.error(
            "job_search EXECUTE timed out after %ds — session_id=%s",
            _TIMEOUT_PREPARE,
            deps.session_id,
        )
        try:
            deps.event_bus.publish("job_search.execute.timeout", {
                "session_id": deps.session_id,
                "timeout_seconds": _TIMEOUT_PREPARE,
            })
        except Exception:
            pass
        return TeamResult(
            department="job_search",
            manager_output="",
            success=False,
            error=f"EXECUTE timed out after {_TIMEOUT_PREPARE}s",
        )

    return result
