"""Sprint P5.3 (#1588) — one job-search pipeline path.

E2E offline test that exercises the canonical PREPARE and EXECUTE entry
points end-to-end using fakes for every external boundary (preflight,
``BridgeDeps.for_cron``, ``DepartmentRegistry.route``). No network calls,
no SQLite, no real OAuth — just the wiring shape.

What this test pins down:

  * The cron service classes (``JobSearchPrepareService`` /
    ``JobSearchExecuteService``) call ``_run_preflight`` first, then
    ``BridgeDeps.for_cron``, then ``department.run_{prepare,execute}``.
  * Both paths reach the same ``DepartmentRegistry.route("job_search", ...)``
    seam — i.e. the cron path and the CLI ``_run_via_team`` path are the
    same canonical path post-P5.3 (the legacy ``_run_via_team`` that called
    ``registry.route`` directly was retired in P5.3 in favour of routing
    through ``department.run_prepare/run_execute``).
  * Success state is recorded; the service returns ``True``; no
    ``consecutive_failures`` bump.

The acceptance criterion from #1588 is "one documented path from cron
trigger to Notion staging/status update" — this test pins the in-process
half of that path (cron trigger → department.route). The Notion-staging
half is exercised separately by ``test_approval.py`` /
``test_outreach.py`` / ``test_notifier.py``.
"""
from __future__ import annotations

import tempfile
from unittest.mock import AsyncMock, MagicMock, patch

from bridge.services.result import ServiceResult


def _ok_team_result(manager_output: str = "ok") -> MagicMock:
    """TeamResult-shaped success object the service treats as success.

    Service code reads .success / .error / .manager_output / .total_cost_usd.
    total_cost_usd must be a real number — the formatter renders it as
    f"${result.total_cost_usd:.4f}" which raises TypeError on MagicMock.
    """
    result = MagicMock()
    result.success = True
    result.error = None
    result.manager_output = manager_output
    result.total_cost_usd = 0.0
    return result


class TestPrepareE2EOffline:
    """PREPARE cron — full in-process path with fakes at every boundary."""

    def test_prepare_canonical_path_with_fakes(self):
        """cron trigger → preflight → for_cron → department.run_prepare → success."""
        from job_search.service import JobSearchPrepareService

        with tempfile.TemporaryDirectory() as tmp:
            svc = JobSearchPrepareService(data_dir=tmp, chat_id="")

            deps_fake = MagicMock()
            deps_fake.session_id = "jobsearch-prepare-fake"

            with (
                patch.object(svc, "should_run", return_value=True),
                patch("job_search.service._run_preflight", return_value=(True, [])) as mock_pf,
                patch(
                    "teams._types.BridgeDeps.for_cron",
                    new_callable=AsyncMock,
                    return_value=deps_fake,
                ) as mock_deps,
                patch(
                    "job_search.department.run_prepare",
                    new_callable=AsyncMock,
                    return_value=_ok_team_result("prepare-fake-output"),
                ) as mock_run_prepare,
            ):
                result = svc.run()

            assert isinstance(result, ServiceResult)
            assert result.ok is True
            assert result.skip_reason is None

            # Preflight ran first (env gate).
            mock_pf.assert_called_once()
            assert mock_pf.call_args.kwargs == {"run_type": "prepare"} \
                or mock_pf.call_args[1].get("run_type") == "prepare"

            # BridgeDeps.for_cron was called with the canonical department slug.
            mock_deps.assert_awaited_once()
            assert mock_deps.await_args.kwargs.get("department") == "job_search"
            assert mock_deps.await_args.kwargs.get("session_id", "").startswith(
                "jobsearch-prepare-"
            )

            # department.run_prepare received the deps from for_cron.
            mock_run_prepare.assert_awaited_once_with(deps_fake)

            # Success state recorded — consecutive_failures NOT bumped.
            state = svc.load_state(filename="job_search-state.json")
            assert state["consecutive_failures"] == 0
            assert state["total_runs"] == 1
            assert state["last_run"] is not None


class TestExecuteE2EOffline:
    """EXECUTE cron — full in-process path with fakes at every boundary."""

    def test_execute_canonical_path_with_fakes(self):
        """cron trigger → preflight → for_cron → department.run_execute → success."""
        from job_search.service import JobSearchExecuteService

        with tempfile.TemporaryDirectory() as tmp:
            svc = JobSearchExecuteService(data_dir=tmp, chat_id="")

            deps_fake = MagicMock()
            deps_fake.session_id = "jobsearch-execute-fake"

            with (
                patch.object(svc, "should_run", return_value=True),
                patch("job_search.service._run_preflight", return_value=(True, [])) as mock_pf,
                patch(
                    "teams._types.BridgeDeps.for_cron",
                    new_callable=AsyncMock,
                    return_value=deps_fake,
                ) as mock_deps,
                patch(
                    "job_search.department.run_execute",
                    new_callable=AsyncMock,
                    return_value=_ok_team_result("execute-fake-output"),
                ) as mock_run_execute,
            ):
                result = svc.run()

            assert isinstance(result, ServiceResult)
            assert result.ok is True
            assert result.skip_reason is None

            # Preflight ran first with run_type="execute".
            mock_pf.assert_called_once()
            assert mock_pf.call_args.kwargs.get("run_type") == "execute" \
                or (mock_pf.call_args[1].get("run_type") == "execute")

            # BridgeDeps.for_cron was called with the canonical department slug.
            mock_deps.assert_awaited_once()
            assert mock_deps.await_args.kwargs.get("department") == "job_search"
            assert mock_deps.await_args.kwargs.get("session_id", "").startswith(
                "jobsearch-execute-"
            )

            # department.run_execute received the deps from for_cron.
            mock_run_execute.assert_awaited_once_with(deps_fake)

            # Success state recorded.
            state = svc.load_state(filename="job_search-state.json")
            assert state["consecutive_failures"] == 0
            assert state["total_runs"] == 1


class TestSinglePipelinePath:
    """Cron and CLI both arrive at the same ``department.run_*`` seam."""

    def test_cli_run_via_team_routes_through_department(self):
        """P5.3 — ``_run_via_team`` calls ``department.run_prepare`` (not ``registry.route`` directly).

        Before P5.3, the CLI path called ``DepartmentRegistry.route`` directly,
        bypassing the ``asyncio.timeout`` protection in ``department.py``. This
        test pins the canonical join: CLI + cron both go through
        ``department.run_prepare``/``run_execute``.
        """
        import asyncio

        import job_search.__main__ as _main

        deps_fake = MagicMock()
        team_result = _ok_team_result("cli-prepare-output")

        with (
            patch(
                "teams._types.BridgeDeps.for_cron",
                new_callable=AsyncMock,
                return_value=deps_fake,
            ),
            patch(
                "job_search.department.run_prepare",
                new_callable=AsyncMock,
                return_value=team_result,
            ) as mock_run_prepare,
        ):
            summary = asyncio.run(_main._run_via_team("prepare"))

        mock_run_prepare.assert_awaited_once_with(deps_fake)
        assert summary == "cli-prepare-output"
