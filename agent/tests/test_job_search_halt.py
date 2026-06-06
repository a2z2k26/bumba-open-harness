"""Halt-gate tests for job-search (audit-2026-05-16.C.04 / #2059).

C.01 (#2056) shipped the shared ``HaltPolicy`` contract at
``bridge/halt.py``. This sprint wires both job-search entry points to
honor it:

  * CLI    — ``python -m job_search`` (``job_search/__main__.py``)
  * Cron   — ``JobSearchPrepareService`` / ``JobSearchExecuteService``
             (``job_search/service.py``); the cron loop also gates
             continuation after preflight, before the LLM call.

These tests do NOT exercise the cost-parsing path (Session C's
D.07 / #2068 owns that). They cover only the gate.
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bridge.services.result import ServiceResult
from job_search._pipeline import _build_halt_policy
from job_search.service import JobSearchExecuteService, JobSearchPrepareService


_STATE_FILE = "job_search-state.json"


# ---------------------------------------------------------------------------
# Helper: write/clear the halt flag in a tmp data dir
# ---------------------------------------------------------------------------

def _set_halt(data_dir: Path, reason: str = "operator halt for test") -> Path:
    flag = data_dir / "halt.flag"
    flag.write_text(reason)
    return flag


def _clear_halt(data_dir: Path) -> None:
    flag = data_dir / "halt.flag"
    flag.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# _build_halt_policy — sanity contract
# ---------------------------------------------------------------------------

def test_build_halt_policy_reflects_file_state():
    with tempfile.TemporaryDirectory() as tmp:
        data_dir = Path(tmp)
        policy = _build_halt_policy(data_dir)

        # No flag → not blocked.
        d = policy.check_start("job-search")
        assert d.blocked is False
        assert d.reason is None

        # Flag present → blocked, reason carries the file contents.
        _set_halt(data_dir, "scripted-test-reason")
        d = policy.check_start("job-search")
        assert d.blocked is True
        assert d.reason is not None
        assert "scripted-test-reason" in d.reason
        assert "job-search" in d.reason

        # check_continue follows the same source.
        c = policy.check_continue("job-search")
        assert c.blocked is True


# ---------------------------------------------------------------------------
# Service — JobSearchPrepareService halt at entry
# ---------------------------------------------------------------------------

def test_prepare_service_halt_at_entry_returns_skip(monkeypatch):
    with tempfile.TemporaryDirectory() as tmp:
        data_dir = Path(tmp)
        _set_halt(data_dir, "halt set before prepare")
        svc = JobSearchPrepareService(data_dir=data_dir, chat_id="")

        with (
            patch.object(svc, "should_run", return_value=True),
            patch("job_search.service._run_preflight") as mock_preflight,
            patch("job_search.department.run_prepare", new_callable=AsyncMock) as mock_run,
        ):
            result = svc.run()

        assert isinstance(result, ServiceResult)
        assert result.ok is True
        assert result.skip_reason is not None
        assert "halt" in result.skip_reason
        # Preflight and department must NOT have been called.
        mock_preflight.assert_not_called()
        mock_run.assert_not_called()
        # State reflects skip, not failure.
        st = svc.load_state(filename=_STATE_FILE)
        assert st["consecutive_failures"] == 0
        assert st["last_skipped_at"] is not None


def test_prepare_service_no_halt_proceeds_to_preflight(monkeypatch):
    """Negative path — halt absent, normal flow reaches department call."""
    with tempfile.TemporaryDirectory() as tmp:
        data_dir = Path(tmp)
        _clear_halt(data_dir)
        svc = JobSearchPrepareService(data_dir=data_dir, chat_id="")

        ok_result = MagicMock()
        ok_result.success = True
        ok_result.error = None
        ok_result.manager_output = "ok"
        ok_result.total_cost_usd = 0.0

        with (
            patch.object(svc, "should_run", return_value=True),
            patch("job_search.service._run_preflight", return_value=(True, [])),
            patch("job_search.department.run_prepare", new_callable=AsyncMock) as mock_run,
        ):
            mock_run.return_value = ok_result
            result = svc.run()

        assert result.ok is True
        assert result.skip_reason is None
        mock_run.assert_awaited()


# ---------------------------------------------------------------------------
# Service — mid-run halt: halt appears after preflight, before _build_and_run
# ---------------------------------------------------------------------------

def test_prepare_service_halt_after_preflight_skips_llm(monkeypatch):
    """Halt arrives between preflight and the department call. The
    check_continue gate must skip the LLM run; record_skipped not record_failure.
    """
    with tempfile.TemporaryDirectory() as tmp:
        data_dir = Path(tmp)
        _clear_halt(data_dir)
        svc = JobSearchPrepareService(data_dir=data_dir, chat_id="")

        # Side effect: set the halt flag DURING preflight so check_continue trips.
        def _preflight_then_halt(*_args, **_kwargs):
            _set_halt(data_dir, "halt set mid-run")
            return (True, [])

        with (
            patch.object(svc, "should_run", return_value=True),
            patch(
                "job_search.service._run_preflight",
                side_effect=_preflight_then_halt,
            ),
            patch("job_search.department.run_prepare", new_callable=AsyncMock) as mock_run,
        ):
            result = svc.run()

        assert isinstance(result, ServiceResult)
        assert result.ok is True
        assert result.skip_reason is not None
        assert "halt" in result.skip_reason
        mock_run.assert_not_called()
        st = svc.load_state(filename=_STATE_FILE)
        assert st["consecutive_failures"] == 0


# ---------------------------------------------------------------------------
# Service — JobSearchExecuteService halt at entry
# ---------------------------------------------------------------------------

def test_execute_service_halt_at_entry_returns_skip(monkeypatch):
    with tempfile.TemporaryDirectory() as tmp:
        data_dir = Path(tmp)
        _set_halt(data_dir, "halt set before execute")
        svc = JobSearchExecuteService(data_dir=data_dir, chat_id="")

        with (
            patch.object(svc, "should_run", return_value=True),
            patch("job_search.service._run_preflight") as mock_preflight,
            patch("job_search.department.run_execute", new_callable=AsyncMock) as mock_run,
        ):
            result = svc.run()

        assert isinstance(result, ServiceResult)
        assert result.ok is True
        assert result.skip_reason is not None
        assert "halt" in result.skip_reason
        mock_preflight.assert_not_called()
        mock_run.assert_not_called()


# ---------------------------------------------------------------------------
# CLI — __main__.main blocks before any work when halt is set
# ---------------------------------------------------------------------------

def test_cli_halt_at_entry_exits_zero_and_prints_reason(capsys, monkeypatch):
    """Operator halts the daemon; the CLI must not start job-search work.

    Exit code 0 (predictable for scripted callers — "blocked by halt" is
    not a noisy failure, it's a deliberate operator state). Reason printed
    to stderr so log scrapers see why.
    """
    with tempfile.TemporaryDirectory() as tmp:
        data_dir = Path(tmp)
        _set_halt(data_dir, "halt set for CLI test")

        # Force the CLI to use our tmp data_dir by patching _resolve_data_root
        # (consulted by _build_halt_policy when no data_dir is passed).
        monkeypatch.setattr(
            "job_search._pipeline._resolve_data_root",
            lambda: data_dir,
        )
        # argv simulating `python -m job_search prepare`
        monkeypatch.setattr(sys, "argv", ["job_search", "prepare"])

        from job_search import __main__ as cli_mod

        # Department + agent paths should NOT be reached. Patch both for safety.
        with (
            patch("job_search.__main__._run_via_team", new_callable=AsyncMock) as mock_team,
            patch("job_search.agent.JobSearchAgent") as mock_agent_cls,
        ):
            with pytest.raises(SystemExit) as excinfo:
                cli_mod.main()

        assert excinfo.value.code == 0
        captured = capsys.readouterr()
        assert "halt" in captured.err.lower()
        mock_team.assert_not_called()
        mock_agent_cls.assert_not_called()


def test_cli_no_halt_proceeds_to_pipeline(capsys, monkeypatch):
    """Negative path — halt absent, CLI reaches the pipeline."""
    with tempfile.TemporaryDirectory() as tmp:
        data_dir = Path(tmp)
        _clear_halt(data_dir)

        monkeypatch.setattr(
            "job_search._pipeline._resolve_data_root",
            lambda: data_dir,
        )
        monkeypatch.setattr(sys, "argv", ["job_search", "prepare"])

        from job_search import __main__ as cli_mod

        # Pretend team mode is off so we exercise the simpler legacy path.
        with (
            patch("job_search.__main__._is_team_enabled", return_value=False),
            patch("job_search.agent.JobSearchAgent") as mock_agent_cls,
        ):
            mock_agent = mock_agent_cls.return_value
            mock_agent.prepare = AsyncMock(return_value="agent ran prepare")
            cli_mod.main()  # must not raise

        captured = capsys.readouterr()
        assert "agent ran prepare" in captured.out
        mock_agent_cls.assert_called_once()


# ---------------------------------------------------------------------------
# CLI — --test-url smoke path also honors halt
# ---------------------------------------------------------------------------

def test_cli_smoke_test_halt_at_entry_exits_zero(capsys, monkeypatch):
    """The --test-url smoke branch is autonomous work too — must respect halt."""
    with tempfile.TemporaryDirectory() as tmp:
        data_dir = Path(tmp)
        _set_halt(data_dir, "halt blocks smoke test")

        monkeypatch.setattr(
            "job_search._pipeline._resolve_data_root",
            lambda: data_dir,
        )
        monkeypatch.setattr(
            sys, "argv", ["job_search", "--test-url", "https://example.com/job"]
        )

        from job_search import __main__ as cli_mod

        with patch(
            "job_search.__main__._run_smoke_test", new_callable=AsyncMock
        ) as mock_smoke:
            with pytest.raises(SystemExit) as excinfo:
                cli_mod.main()

        assert excinfo.value.code == 0
        captured = capsys.readouterr()
        assert "halt" in captured.err.lower()
        mock_smoke.assert_not_called()
