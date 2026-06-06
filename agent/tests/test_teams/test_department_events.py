"""Tests for department lifecycle events published to the EventBus."""

from __future__ import annotations

import unittest.mock as mock
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from pydantic_ai.models.test import TestModel

from bridge.event_bus import (
    DEPARTMENT_DELEGATION_STARTED,
    DEPARTMENT_TASK_COMPLETED,
    DEPARTMENT_TASK_FAILED,
    DEPARTMENT_TASK_STARTED,
)
from tests.test_teams.conftest import (
    make_chief_delegating_model,
    make_deps,
    make_specialist_text_model,
)
from teams import BridgeDeps, DepartmentRegistry


@pytest.fixture
def registry() -> DepartmentRegistry:
    teams_dir = Path(__file__).parent.parent.parent / "config" / "teams"
    return DepartmentRegistry.from_directory(teams_dir)


@pytest.fixture
def deps() -> BridgeDeps:
    return make_deps(session_id="event-test", department="qa")


class TestDepartmentLifecycleEvents:
    @pytest.mark.asyncio
    async def test_task_started_published(self, registry, deps):
        published = []

        mock_bus = MagicMock()
        mock_bus.publish.side_effect = lambda evt, data: published.append((evt, data))

        team = registry.get_team("qa")
        test_model = TestModel(custom_output_args={"answer": "done"}, call_tools=[])

        with patch("bridge.event_bus.EventBus.get_instance", return_value=mock_bus):
            with team.manager.override(model=test_model):
                await registry.route("qa", "run smoke tests", deps)

        started = [e for e in published if e[0] == DEPARTMENT_TASK_STARTED]
        assert len(started) >= 1
        assert started[0][1]["department"] == "qa"

    @pytest.mark.asyncio
    async def test_task_completed_published_on_success(self, registry, deps):
        # P3.6 strict-floor migration (#1692): QA is a delegate-mode team
        # (4 workers, expected_min_specialists=1). The success path under
        # strict-floor IS the delegate path — emit a deterministic offline
        # delegation to qa-engineer so Gate 8 passes and the success event
        # fires as the assertion expects.
        published = []

        mock_bus = MagicMock()
        mock_bus.publish.side_effect = lambda evt, data: published.append((evt, data))

        team = registry.get_team("qa")
        emp_model = make_specialist_text_model("all tests pass")
        mgr_model = make_chief_delegating_model(
            [("qa-engineer", "run tests")], final_answer="all tests pass"
        )

        with patch("bridge.event_bus.EventBus.get_instance", return_value=mock_bus):
            with team.employees["qa-engineer"].override(model=emp_model):
                with team.manager.override(model=mgr_model):
                    result = await registry.route("qa", "run tests", deps)

        assert result.success
        completed = [e for e in published if e[0] == DEPARTMENT_TASK_COMPLETED]
        assert len(completed) >= 1
        assert completed[0][1]["success"] is True

    @pytest.mark.asyncio
    async def test_task_failed_published_on_error(self, registry, deps):
        published = []

        mock_bus = MagicMock()
        mock_bus.publish.side_effect = lambda evt, data: published.append((evt, data))

        team = registry.get_team("qa")

        async def failing_run(*args, **kwargs):
            raise RuntimeError("boom")

        with patch("bridge.event_bus.EventBus.get_instance", return_value=mock_bus):
            with mock.patch.object(team.manager, "run", side_effect=failing_run):
                result = await registry.route("qa", "task", deps)

        assert not result.success
        failed = [e for e in published if e[0] == DEPARTMENT_TASK_FAILED]
        assert len(failed) >= 1

    def test_event_type_constants_importable(self):
        from bridge.event_bus import (
            DEPARTMENT_TASK_COMPLETED,
            DEPARTMENT_TASK_FAILED,
            DEPARTMENT_TASK_STARTED,
        )
        assert DEPARTMENT_TASK_STARTED == "department.task.started"
        assert DEPARTMENT_TASK_COMPLETED == "department.task.completed"
        assert DEPARTMENT_TASK_FAILED == "department.task.failed"
        assert DEPARTMENT_DELEGATION_STARTED == "department.delegation.started"
