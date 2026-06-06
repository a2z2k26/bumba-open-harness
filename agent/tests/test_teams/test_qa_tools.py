"""Tests for QA tool functions."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from tests.test_teams.conftest import make_deps
from teams.tools._common import _run_subprocess
from teams.tools._qa import run_tests, security_scan, coverage_report


@pytest.fixture
def ctx():
    mock = MagicMock()
    mock.deps = make_deps(session_id="s1", department="qa")
    return mock


@pytest.mark.asyncio
async def test_run_tests_invokes_subprocess(ctx):
    with patch("teams.tools._qa._run_subprocess") as mock_run:
        mock_run.return_value = ("5 passed in 0.10s", 0)
        result = await run_tests(ctx, path="tests/")
        assert "5 passed" in result
        mock_run.assert_called_once()


@pytest.mark.asyncio
async def test_run_tests_failed_exit_code(ctx):
    with patch("teams.tools._qa._run_subprocess") as mock_run:
        mock_run.return_value = ("2 failed", 1)
        result = await run_tests(ctx, path="tests/")
        assert "FAILED" in result


@pytest.mark.asyncio
async def test_security_scan_returns_findings_string(ctx):
    with patch("teams.tools._qa._run_subprocess") as mock_run:
        mock_run.return_value = ("No issues identified.", 0)
        result = await security_scan(ctx, path="bridge/")
        assert "No issues" in result


@pytest.mark.asyncio
async def test_run_subprocess_reports_missing_executable():
    with patch(
        "teams.tools._common.asyncio.create_subprocess_exec",
        side_effect=FileNotFoundError("No such file or directory: 'bandit'"),
    ):
        output, code = await _run_subprocess(["bandit", "-r", "."], timeout=1)

    assert code == 127
    assert "COMMAND_UNAVAILABLE" in output
    assert "bandit" in output


@pytest.mark.asyncio
async def test_coverage_report_returns_output(ctx):
    with patch("teams.tools._qa._run_subprocess") as mock_run:
        mock_run.return_value = ("TOTAL 85%", 0)
        result = await coverage_report(ctx, module="bridge/api_server.py")
        assert "85%" in result
