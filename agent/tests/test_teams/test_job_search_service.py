"""Tests for job_search cron services routing via DepartmentRegistry (sprint D5.6).

Sprint #1755 — both services now return :class:`ServiceResult` (not bool);
``svc.run()`` assertions read ``result.ok`` / ``result.skip_reason``.

Sprint R2.1 (#1893) — ``svc.run()`` constructs an ``_build_and_run``
coroutine and hands it to ``asyncio.run``. Tests that patch
``asyncio.run`` MUST close the coroutine argument; otherwise it is
garbage-collected unawaited and emits a ``RuntimeWarning``. Use
``_closing_asyncio_run`` (below) instead of ``return_value=`` /
``side_effect=`` on the ``asyncio.run`` patch.
"""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch

import pytest

from bridge.services.result import ServiceResult
from teams._types import BridgeDeps, TeamResult


def _closing_asyncio_run(result=None, raises=None):
    """Build a side_effect for ``patch('...asyncio.run')`` that closes the
    coroutine argument before returning ``result`` (or raising ``raises``).

    Without this, the coroutine produced by ``_build_and_run()`` leaks and
    emits a ``RuntimeWarning: coroutine ... was never awaited`` once the GC
    finalizes it. Closing it is the minimal-surface fix that lets the test
    keep its synchronous structure without invoking the real async path.
    """
    def _side_effect(coro):
        try:
            coro.close()
        finally:
            if raises is not None:
                raise raises
        return result
    return _side_effect


# ---------------------------------------------------------------------------
# BridgeDeps.for_cron — Sprint 02.08 replaced _build_standalone_deps with the
# real-object classmethod. Detailed assertions live in
# agent/tests/test_job_search_cron_deps.py; this is a smoke check only.
# ---------------------------------------------------------------------------

class TestBuildStandaloneDeps:
    def test_for_cron_builds_valid_bridge_deps(self, tmp_path):
        async def _build():
            return await BridgeDeps.for_cron(
                department="job_search",
                session_id="test-session",
                data_dir=str(tmp_path),
            )

        deps = asyncio.run(_build())

        assert isinstance(deps, BridgeDeps)
        assert deps.session_id == "test-session"
        assert deps.department == "job_search"
        assert deps.memory_store is not None
        assert deps.event_bus is not None
        assert deps.trust_manager is not None
        assert deps.cost_tracker is not None
        assert deps.knowledge_search is not None


# ---------------------------------------------------------------------------
# JobSearchPrepareService
# ---------------------------------------------------------------------------

class TestJobSearchPrepareService:
    def test_instantiates_without_error(self, tmp_path):
        from job_search.service import JobSearchPrepareService
        svc = JobSearchPrepareService(data_dir=tmp_path, chat_id="")
        assert svc is not None

    def test_should_run_outside_window_returns_false(self, tmp_path):
        from job_search.service import JobSearchPrepareService
        svc = JobSearchPrepareService(data_dir=tmp_path, run_hour=3)
        # With run_hour=3 and current time almost certainly outside +-30min, should return False
        # (unless tests happen to run at 02:30-03:30; acceptable edge case)
        # We test the logic by patching datetime
        with patch("job_search.service.datetime") as mock_dt:
            mock_now = MagicMock()
            mock_now.hour = 14
            mock_now.minute = 0
            mock_dt.now.return_value = mock_now
            result = svc.should_run()
        assert result is False

    def test_run_skipped_when_should_run_false(self, tmp_path):
        from job_search.service import JobSearchPrepareService
        svc = JobSearchPrepareService(data_dir=tmp_path)

        with patch.object(svc, "should_run", return_value=False):
            result = svc.run()

        assert isinstance(result, ServiceResult)
        assert result.skip_reason is not None

    def test_run_routes_through_department_run_prepare(self, tmp_path):
        from job_search.service import JobSearchPrepareService

        svc = JobSearchPrepareService(data_dir=tmp_path)

        mock_result = TeamResult(
            department="job_search",
            manager_output="Prepare complete. Staged 3 listings.",
            success=True,
            total_cost_usd=0.15,
        )

        with patch.object(svc, "should_run", return_value=True), \
             patch("job_search.service._run_preflight", return_value=(True, [])), \
             patch("job_search.service.asyncio.run",
                   side_effect=_closing_asyncio_run(result=mock_result)) as mock_run, \
             patch("job_search.department.run_prepare") as mock_fn:
            result = svc.run()

        assert isinstance(result, ServiceResult)
        assert result.ok is True
        assert result.skip_reason is None
        # asyncio.run was called (wraps run_prepare coroutine)
        mock_run.assert_called_once()

    def test_run_records_failure_on_exception(self, tmp_path):
        from job_search.service import JobSearchPrepareService

        svc = JobSearchPrepareService(data_dir=tmp_path)

        with patch.object(svc, "should_run", return_value=True), \
             patch("job_search.service._run_preflight", return_value=(True, [])), \
             patch("job_search.service.asyncio.run",
                   side_effect=_closing_asyncio_run(raises=RuntimeError("exploded"))), \
             patch.object(svc, "record_failure") as mock_failure:
            with pytest.raises(RuntimeError):
                svc.run()

        mock_failure.assert_called_once()
        assert "exploded" in mock_failure.call_args[0][0]

    def test_run_records_failure_on_team_result_failure(self, tmp_path):
        from job_search.service import JobSearchPrepareService

        svc = JobSearchPrepareService(data_dir=tmp_path)
        mock_result = TeamResult(
            department="job_search",
            manager_output="",
            success=False,
            error="budget exhausted",
        )

        with patch.object(svc, "should_run", return_value=True), \
             patch("job_search.service._run_preflight", return_value=(True, [])), \
             patch("job_search.service.asyncio.run",
                   side_effect=_closing_asyncio_run(result=mock_result)), \
             patch.object(svc, "record_failure") as mock_fail:
            result = svc.run()

        assert isinstance(result, ServiceResult)
        assert result.ok is False  # TeamResult.success=False → FAIL
        assert result.skip_reason is None
        mock_fail.assert_called_once()


# ---------------------------------------------------------------------------
# JobSearchExecuteService
# ---------------------------------------------------------------------------

class TestJobSearchExecuteService:
    def test_instantiates_without_error(self, tmp_path):
        from job_search.service import JobSearchExecuteService
        svc = JobSearchExecuteService(data_dir=tmp_path, chat_id="")
        assert svc is not None

    def test_should_run_outside_window_returns_false(self, tmp_path):
        from job_search.service import JobSearchExecuteService
        svc = JobSearchExecuteService(data_dir=tmp_path)

        with patch("job_search.service.datetime") as mock_dt:
            mock_now = MagicMock()
            mock_now.hour = 21  # outside 10-20 window
            mock_dt.now.return_value = mock_now
            result = svc.should_run()

        assert result is False

    def test_should_run_inside_window_returns_true(self, tmp_path):
        from job_search.service import JobSearchExecuteService
        svc = JobSearchExecuteService(data_dir=tmp_path)

        with patch("job_search.service.datetime") as mock_dt:
            mock_now = MagicMock()
            mock_now.hour = 14  # inside 10-20 window
            mock_dt.now.return_value = mock_now
            result = svc.should_run()

        assert result is True

    def test_run_skipped_when_should_run_false(self, tmp_path):
        from job_search.service import JobSearchExecuteService
        svc = JobSearchExecuteService(data_dir=tmp_path)

        with patch.object(svc, "should_run", return_value=False):
            result = svc.run()

        assert isinstance(result, ServiceResult)
        assert result.skip_reason is not None

    def test_run_routes_through_department_run_execute(self, tmp_path):
        from job_search.service import JobSearchExecuteService

        svc = JobSearchExecuteService(data_dir=tmp_path)

        mock_result = TeamResult(
            department="job_search",
            manager_output="Execute complete. Submitted 1 application.",
            success=True,
            total_cost_usd=0.08,
        )

        with patch.object(svc, "should_run", return_value=True), \
             patch("job_search.service._run_preflight", return_value=(True, [])), \
             patch("job_search.service.asyncio.run",
                   side_effect=_closing_asyncio_run(result=mock_result)) as mock_run:
            result = svc.run()

        assert isinstance(result, ServiceResult)
        assert result.ok is True
        assert result.skip_reason is None
        mock_run.assert_called_once()


# ---------------------------------------------------------------------------
# Runner integration: service map points to correct classes
# ---------------------------------------------------------------------------

class TestRunnerServiceMap:
    def test_job_search_in_service_map(self):
        from bridge.services.runner import SERVICE_MAP
        assert "job_search" in SERVICE_MAP
        module_path, class_name = SERVICE_MAP["job_search"]
        assert module_path == "job_search.service"
        assert class_name == "JobSearchPrepareService"

    def test_job_search_execute_in_service_map(self):
        from bridge.services.runner import SERVICE_MAP
        assert "job_search_execute" in SERVICE_MAP
        module_path, class_name = SERVICE_MAP["job_search_execute"]
        assert module_path == "job_search.service"
        assert class_name == "JobSearchExecuteService"

    def test_can_import_service_classes(self):
        from bridge.services.runner import _import_service_class
        cls_prepare = _import_service_class("job_search")
        cls_execute = _import_service_class("job_search_execute")

        from job_search.service import JobSearchPrepareService, JobSearchExecuteService
        assert cls_prepare is JobSearchPrepareService
        assert cls_execute is JobSearchExecuteService
