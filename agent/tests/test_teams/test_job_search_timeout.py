"""Tests for asyncio.timeout wrappers in department.py (sprint D5.5)."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from tests.test_teams.conftest import (
    make_chief_delegating_model,
    make_deps,
    make_specialist_text_model,
)
from teams import DepartmentRegistry
from teams._types import TeamResult


_TEAMS_DIR = Path(__file__).parent.parent.parent / "config" / "teams"


@pytest.fixture
def registry() -> DepartmentRegistry:
    return DepartmentRegistry.from_directory(_TEAMS_DIR)


# ---------------------------------------------------------------------------
# department.py — run_prepare timeout
# ---------------------------------------------------------------------------

class TestRunPrepareTimeout:
    @pytest.mark.asyncio
    async def test_timeout_returns_team_result_with_failure(self, registry):
        """Timeout wraps TimeoutError in a TeamResult(success=False)."""
        from job_search.department import run_prepare

        deps = make_deps(session_id="to-test", department="job_search")

        async def _hang(*args, **kwargs):
            await asyncio.sleep(9999)

        with patch("job_search.department._registry", registry), \
             patch.object(registry, "route", side_effect=_hang), \
             patch("job_search.department._TIMEOUT_PREPARE", 0):
            result = await run_prepare(deps)

        assert isinstance(result, TeamResult)
        assert result.success is False
        assert result.department == "job_search"
        assert result.error is not None
        assert "timed out" in result.error.lower()

    @pytest.mark.asyncio
    async def test_timeout_publishes_event(self, registry):
        """Timeout publishes a job_search.prepare.timeout event to event_bus."""
        from job_search.department import run_prepare

        mock_bus = MagicMock()
        deps = make_deps(session_id="to-test", department="job_search", event_bus=mock_bus)

        async def _hang(*args, **kwargs):
            await asyncio.sleep(9999)

        with patch("job_search.department._registry", registry), \
             patch.object(registry, "route", side_effect=_hang), \
             patch("job_search.department._TIMEOUT_PREPARE", 0):
            await run_prepare(deps)

        mock_bus.publish.assert_called_once()
        call_args = mock_bus.publish.call_args
        assert call_args[0][0] == "job_search.prepare.timeout"

    @pytest.mark.asyncio
    async def test_no_timeout_on_fast_result(self, registry):
        """Fast route call passes through without triggering timeout."""
        # P3.6 strict-floor migration (#1692): job_search is a delegate-mode
        # team (expected_min_specialists=1). Drive a deterministic offline
        # delegation to acquire-and-prepare-specialist so Gate 8 passes and
        # the "no timeout" claim is verifiable.
        from job_search.department import run_prepare

        deps = make_deps(session_id="fast-test", department="job_search")
        team = registry.get_team("job_search")

        emp_model = make_specialist_text_model("done fast")
        mgr_model = make_chief_delegating_model(
            [("acquire-and-prepare-specialist", "prepare")],
            final_answer="done fast",
        )
        with patch("job_search.department._registry", registry), \
             team.employees["acquire-and-prepare-specialist"].override(model=emp_model), \
             team.manager.override(model=mgr_model):
            result = await run_prepare(deps)

        assert result.success is True

    @pytest.mark.asyncio
    async def test_timeout_value_from_yaml_constant(self):
        """_TIMEOUT_PREPARE matches the job_search.yaml constraints.timeout_seconds."""
        from job_search.department import _TIMEOUT_PREPARE
        from teams._config import load_department_config

        cfg = load_department_config(_TEAMS_DIR / "job_search.yaml")
        assert _TIMEOUT_PREPARE == cfg.constraints.timeout_seconds


