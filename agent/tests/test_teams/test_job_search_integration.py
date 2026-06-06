"""Integration tests for the job_search department (sprint D5.3)."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import patch

import pytest

from tests.test_teams.conftest import (
    make_chief_delegating_model,
    make_deps,
    make_specialist_text_model,
)
from teams import DepartmentRegistry


_TEAMS_DIR = Path(__file__).parent.parent.parent / "config" / "teams"


@pytest.fixture
def registry() -> DepartmentRegistry:
    return DepartmentRegistry.from_directory(_TEAMS_DIR)


# ---------------------------------------------------------------------------
# job_search department
# ---------------------------------------------------------------------------

class TestJobSearchDepartment:
    def test_job_search_registered(self, registry: DepartmentRegistry):
        assert "job_search" in registry.department_names()

    def test_job_search_config_zone(self, registry: DepartmentRegistry):
        cfg = registry.get_config("job_search")
        assert cfg.zone == 4

    def test_job_search_team_builds(self, registry: DepartmentRegistry):
        team = registry.get_team("job_search")
        assert team.manager is not None
        # Sprint D5.2 (#1363): chief + 4 specialists
        assert len(team.employees) == 4

    @pytest.mark.asyncio
    async def test_run_prepare_routes_through_registry(self, registry: DepartmentRegistry):
        """run_prepare uses registry.route("job_search", ...) — verifies routing."""
        # P3.6 strict-floor migration (#1692): job_search is a delegate-mode
        # team (4 workers, expected_min_specialists=1). Drive a deterministic
        # offline delegation to acquire-and-prepare-specialist so Gate 8
        # passes and the routing assertion holds.
        from job_search.department import run_prepare

        deps = make_deps(session_id="test-prepare", department="job_search")
        team = registry.get_team("job_search")

        emp_model = make_specialist_text_model(
            "Prepare pipeline complete. Staged 3 listings."
        )
        mgr_model = make_chief_delegating_model(
            [("acquire-and-prepare-specialist", "prepare")],
            final_answer="Prepare pipeline complete. Staged 3 listings.",
        )

        # Patch the module-level registry inside department.py to use our fixture
        with patch("job_search.department._registry", registry), \
             team.employees["acquire-and-prepare-specialist"].override(model=emp_model), \
             team.manager.override(model=mgr_model):
            result = await run_prepare(deps)

        assert result.department == "job_search"
        assert result.success is True
        assert "Prepare pipeline complete" in result.manager_output

    @pytest.mark.asyncio
    async def test_run_prepare_timeout(self, registry: DepartmentRegistry):
        """asyncio.TimeoutError is caught and wrapped in TeamResult."""
        from job_search.department import run_prepare

        deps = make_deps(session_id="test-timeout", department="job_search")

        async def _slow_route(*args, **kwargs):
            await asyncio.sleep(9999)

        with patch("job_search.department._registry", registry), \
             patch.object(registry, "route", side_effect=_slow_route), \
             patch("job_search.department._TIMEOUT_PREPARE", 0):
            result = await run_prepare(deps)

        assert result.success is False
        assert "timed out" in (result.error or "").lower()

    @pytest.mark.asyncio
    async def test_run_execute_routes_through_registry(self, registry: DepartmentRegistry):
        # P3.6 strict-floor migration (#1692): job_search delegate-mode team
        # requires ≥1 delegation. Drive an offline delegation to
        # outreach-execute-specialist (the natural specialist for the execute
        # phase) so Gate 8 passes.
        from job_search.department import run_execute

        deps = make_deps(session_id="test-execute", department="job_search")
        team = registry.get_team("job_search")

        emp_model = make_specialist_text_model(
            "Execute pipeline complete. Submitted 2 applications."
        )
        mgr_model = make_chief_delegating_model(
            [("outreach-execute-specialist", "execute")],
            final_answer="Execute pipeline complete. Submitted 2 applications.",
        )

        with patch("job_search.department._registry", registry), \
             team.employees["outreach-execute-specialist"].override(model=emp_model), \
             team.manager.override(model=mgr_model):
            result = await run_execute(deps)

        assert result.department == "job_search"
        assert result.success is True


