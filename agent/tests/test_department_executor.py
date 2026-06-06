"""DepartmentExecutor behavior — lift-and-shift regression tests (S02a #561).

AC-3: DepartmentExecutor.execute(wo) is byte-for-byte equivalent to the
pre-sprint dispatcher._dispatch_department(wo).
"""
from __future__ import annotations

from dataclasses import replace
from unittest.mock import AsyncMock, MagicMock

import pytest

from bridge.executors.department import DepartmentExecutor
from bridge.work_order import Environment, WorkOrder, WorkOrderStatus


def _make_wo(dept: str | None = "eng") -> WorkOrder:
    wo = WorkOrder.create(intent="build x", skill="ship-feature", project="prod")
    wo = wo.with_environment(Environment.DEPARTMENT, "department task").transition(
        WorkOrderStatus.ASSIGNED
    )
    return replace(wo, department_target=dept)


@pytest.mark.asyncio
async def test_department_executor_routes_to_registry() -> None:
    """Successful team run returns a ClaudeResult with handled=True semantics."""
    registry = MagicMock()
    registry.department_names = MagicMock(return_value=["eng", "qa"])
    team_result = MagicMock(
        success=True,
        manager_output="all done",
        total_cost_usd=0.05,
        error=None,
    )
    registry.route = AsyncMock(return_value=team_result)

    executor = DepartmentExecutor(department_registry=registry, app=None, event_bus=None)
    result = await executor.execute(_make_wo("eng"))

    assert result.is_error is False
    assert result.response_text == "all done"
    registry.route.assert_awaited_once()


@pytest.mark.asyncio
async def test_department_executor_raises_for_unknown_department() -> None:
    """Routing to a dept not in registry raises ValueError."""
    registry = MagicMock()
    registry.department_names = MagicMock(return_value=["qa"])

    executor = DepartmentExecutor(department_registry=registry, app=None, event_bus=None)

    with pytest.raises(ValueError, match="unknown department"):
        await executor.execute(_make_wo("eng"))


@pytest.mark.asyncio
async def test_department_executor_raises_on_team_failure() -> None:
    """When team_result.success is False, executor raises RuntimeError."""
    registry = MagicMock()
    registry.department_names = MagicMock(return_value=["eng"])
    team_result = MagicMock(
        success=False,
        manager_output="",
        total_cost_usd=0.0,
        error="specialist crashed",
    )
    registry.route = AsyncMock(return_value=team_result)

    executor = DepartmentExecutor(department_registry=registry, app=None, event_bus=None)

    with pytest.raises(RuntimeError, match="failed"):
        await executor.execute(_make_wo("eng"))


@pytest.mark.asyncio
async def test_department_executor_raises_when_registry_missing() -> None:
    """Without a registry, executor raises RuntimeError."""
    executor = DepartmentExecutor(department_registry=None, app=None, event_bus=None)

    with pytest.raises(RuntimeError, match="not configured"):
        await executor.execute(_make_wo("eng"))


@pytest.mark.asyncio
async def test_department_executor_cost_forwarded() -> None:
    """Total cost from team result is forwarded into the ClaudeResult."""
    registry = MagicMock()
    registry.department_names = MagicMock(return_value=["eng"])
    team_result = MagicMock(
        success=True,
        manager_output="output",
        total_cost_usd=1.23,
        error=None,
    )
    registry.route = AsyncMock(return_value=team_result)

    executor = DepartmentExecutor(department_registry=registry, app=None, event_bus=None)
    result = await executor.execute(_make_wo("eng"))

    assert abs(result.cost_usd - 1.23) < 0.001
