"""Sprint 02.09 — verify ``preflight_check`` is wired into the cron services.

Before this sprint, ``agent/job_search/preflight.py`` defined a
``preflight_check`` with 7 environment validations (secrets file, OAuth +
Notion tokens, gws CLI for execute, criteria/candidate JSON config files,
SQLite DB writability, Notion API reachability, dedup state) but **nothing
called it from the cron path**. ``JobSearchPrepareService.run()`` and
``JobSearchExecuteService.run()`` proceeded past missing
``notion_api_token``, unwritable DB, stale Gmail creds and only surfaced
failure mid-phase — cost incurred, partial state written.

These tests are the regression guard for the gate added at the top of each
``run()`` method. The contract:

  - preflight_check returns (ok=True, errors=[])
      → run() proceeds normally (department call happens)
  - preflight_check returns (ok=False, errors=["..."])
      → run() returns False
      → record_skipped() was called with an actionable SkipReason taxonomy
      → consecutive_failures was NOT incremented (env problem, not a service bug)
      → the department call (run_prepare / run_execute) was NEVER invoked
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from bridge.services.result import ServiceResult
from job_search.service import (
    JobSearchExecuteService,
    JobSearchPrepareService,
    _failure_key,
    _preflight_skip_reason,
)

_STATE_FILE = "job_search-state.json"


def _state(svc) -> dict:
    return svc.load_state(filename=_STATE_FILE)


def _ok_team_result(manager_output: str = "ok") -> MagicMock:
    """A TeamResult-shaped success object the service treats as success."""
    result = MagicMock()
    result.success = True
    result.error = None
    result.manager_output = manager_output
    result.total_cost_usd = 0.0
    return result


# ---------------------------------------------------------------------------
# Test 1 — preflight OK → prepare proceeds and calls department.run_prepare
# ---------------------------------------------------------------------------

def test_prepare_preflight_ok_proceeds_to_department_call():
    """preflight_check ok=True → department.run_prepare is invoked, run() returns True."""
    with tempfile.TemporaryDirectory() as tmp:
        svc = JobSearchPrepareService(data_dir=tmp, chat_id="")

        with (
            patch.object(svc, "should_run", return_value=True),
            patch("job_search.service._run_preflight", return_value=(True, [])) as mock_pf,
            patch("job_search.department.run_prepare", new_callable=AsyncMock) as mock_prepare,
        ):
            mock_prepare.return_value = _ok_team_result()

            result = svc.run()

        # Preflight was consulted with run_type="prepare"
        mock_pf.assert_called_once()
        _, pf_kwargs = mock_pf.call_args
        # _run_preflight is called positionally: (data_dir, run_type=...)
        # accept either positional or keyword binding for run_type
        if "run_type" in pf_kwargs:
            assert pf_kwargs["run_type"] == "prepare"
        else:
            # positional: second arg is run_type
            assert mock_pf.call_args.args[1] == "prepare"

        # Department was invoked exactly once
        mock_prepare.assert_called_once()

        # Service treated this as a real run
        assert isinstance(result, ServiceResult)
        assert result.ok is True
        assert result.skip_reason is None
        st = _state(svc)
        assert st["total_runs"] == 1
        assert st["consecutive_failures"] == 0
        assert st["last_run"] is not None


# ---------------------------------------------------------------------------
# Test 2 — preflight FAIL on prepare → skip recorded, no department call
# ---------------------------------------------------------------------------

def test_prepare_preflight_failure_records_skip_and_skips_department():
    """preflight_check ok=False → record_skipped, no department call, no failure bump."""
    with tempfile.TemporaryDirectory() as tmp:
        svc = JobSearchPrepareService(data_dir=tmp, chat_id="")

        # Pre-seed something so we can verify counters move correctly.
        # consecutive_failures should NOT increment on a preflight skip.
        svc.record_failure("previous unrelated error", filename=_STATE_FILE)
        assert _state(svc)["consecutive_failures"] == 1
        assert _state(svc)["total_failures"] == 1

        errors = ["notion_api_token missing from .secrets"]

        with (
            patch.object(svc, "should_run", return_value=True),
            patch("job_search.service._run_preflight", return_value=(False, errors)),
            patch("job_search.department.run_prepare", new_callable=AsyncMock) as mock_prepare,
        ):
            result = svc.run()

        # Department was never called — preflight short-circuited
        mock_prepare.assert_not_called()

        # run() returned a SKIP ServiceResult (preflight failure is an env
        # issue, not a service bug)
        assert isinstance(result, ServiceResult)
        assert result.skip_reason == "missing_secret:notion_api_token"
        assert result.ok is True  # SKIP is a correct no-op, not a failure

        st = _state(svc)
        # record_skipped() reset consecutive_failures to 0 (correct: env issue,
        # not a service bug)
        assert st["consecutive_failures"] == 0
        # skip telemetry written
        assert st["total_skipped"] >= 1
        assert st["last_skipped_reason"] == "missing_secret:notion_api_token"
        assert st["last_skipped_class"] == "missing_secret"
        # success counter UNCHANGED (no real work happened)
        assert st["total_runs"] == 0
        # failure counter UNCHANGED from the pre-seeded state — the skip
        # must NOT bump total_failures even though it was technically a
        # bad outcome
        assert st["total_failures"] == 1


# ---------------------------------------------------------------------------
# Test 3 — preflight FAIL on execute → same skip semantics
# ---------------------------------------------------------------------------

def test_execute_preflight_failure_records_skip_and_skips_department():
    """Mirror of Test 2 for the EXECUTE cron — different errors, same shape."""
    with tempfile.TemporaryDirectory() as tmp:
        svc = JobSearchExecuteService(data_dir=tmp, chat_id="")

        errors = [
            "gws CLI not found — needed for outreach email sending",
        ]

        with (
            patch.object(svc, "should_run", return_value=True),
            patch("job_search.service._run_preflight", return_value=(False, errors)) as mock_pf,
            patch("job_search.department.run_execute", new_callable=AsyncMock) as mock_execute,
        ):
            result = svc.run()

        # Preflight was called with run_type="execute" (gws CLI check is
        # gated on run_type=="execute" in preflight.py — calling with the
        # wrong run_type would be a real bug)
        mock_pf.assert_called_once()
        if "run_type" in mock_pf.call_args.kwargs:
            assert mock_pf.call_args.kwargs["run_type"] == "execute"
        else:
            assert mock_pf.call_args.args[1] == "execute"

        # Department.run_execute was never invoked
        mock_execute.assert_not_called()

        # run() returned a SKIP ServiceResult
        assert isinstance(result, ServiceResult)
        assert result.skip_reason == "dependency_unavailable:gws"
        assert result.ok is True  # SKIP is a correct no-op

        st = _state(svc)
        assert st["total_runs"] == 0
        assert st["consecutive_failures"] == 0
        assert st["total_skipped"] >= 1
        assert st["last_skipped_reason"] == "dependency_unavailable:gws"
        assert st["last_skipped_class"] == "dependency_unavailable"


# ---------------------------------------------------------------------------
# Test 4 — preflight skip MUST NOT increment consecutive_failures
# ---------------------------------------------------------------------------

def test_preflight_skip_does_not_increment_consecutive_failures():
    """Three consecutive preflight failures must leave consecutive_failures at 0.

    This is the contract that protects monitor.sh / escalation alerts from
    firing on transient env issues. A real service bug fires
    failure.detected after 3 consecutive failures; an env issue (missing
    secret, unreachable Notion) must NOT.
    """
    with tempfile.TemporaryDirectory() as tmp:
        events: list[tuple[str, dict]] = []

        def capture(event_name, payload):
            events.append((event_name, payload))

        svc = JobSearchPrepareService(data_dir=tmp, chat_id="", event_callback=capture)

        errors = ["notion_api_token missing from .secrets"]

        with (
            patch.object(svc, "should_run", return_value=True),
            patch("job_search.service._run_preflight", return_value=(False, errors)),
            patch("job_search.department.run_prepare", new_callable=AsyncMock),
        ):
            for _ in range(3):
                result = svc.run()
                assert isinstance(result, ServiceResult)
                assert result.skip_reason is not None  # all 3 are SKIPs

        st = _state(svc)
        # Critical invariant: env-side preflight failures must NOT pollute
        # the consecutive_failures counter that drives escalation
        assert st["consecutive_failures"] == 0
        # The skip counter, however, ticks up each time
        assert st["total_skipped"] == 3
        assert st["total_runs"] == 0
        assert st["total_failures"] == 0

        # And no failure.detected events were emitted — only schedule.skipped
        failure_events = [e for e in events if e[0] == "failure.detected"]
        skipped_events = [e for e in events if e[0] == "schedule.skipped"]
        assert failure_events == []
        assert len(skipped_events) == 3


# ---------------------------------------------------------------------------
# Test 5 — preflight OK on execute → department.run_execute is invoked
# ---------------------------------------------------------------------------

def test_execute_preflight_ok_proceeds_to_department_call():
    """Symmetry check for Test 1 on the EXECUTE cron."""
    with tempfile.TemporaryDirectory() as tmp:
        svc = JobSearchExecuteService(data_dir=tmp, chat_id="")

        with (
            patch.object(svc, "should_run", return_value=True),
            patch("job_search.service._run_preflight", return_value=(True, [])),
            patch("job_search.department.run_execute", new_callable=AsyncMock) as mock_execute,
        ):
            mock_execute.return_value = _ok_team_result(manager_output="executed 1")

            result = svc.run()

        mock_execute.assert_called_once()
        assert isinstance(result, ServiceResult)
        assert result.ok is True
        assert result.skip_reason is None
        st = _state(svc)
        assert st["total_runs"] == 1
        assert st["consecutive_failures"] == 0


# ---------------------------------------------------------------------------
# Test 6 — preflight skip taxonomy
# ---------------------------------------------------------------------------

def test_preflight_skip_reason_maps_to_actionable_taxonomy():
    """Preflight skips should populate last_skipped_class for stale-skip audits."""
    assert _preflight_skip_reason("notion_api_token missing from .secrets").render() == (
        "missing_secret:notion_api_token"
    )
    assert _preflight_skip_reason("claude_oauth_token missing from .secrets").render() == (
        "missing_secret:claude_oauth_token"
    )
    assert _preflight_skip_reason("Notion API token is invalid (401)").render() == (
        "missing_secret:notion_api_token"
    )
    assert _preflight_skip_reason("Criteria config not found: /tmp/criteria.json").render() == (
        "missing_config:job_search.criteria"
    )
    assert _preflight_skip_reason("Candidate config invalid: nope").render() == (
        "missing_config:job_search.candidate"
    )
    assert _preflight_skip_reason("gws CLI not found — needed for outreach email sending").render() == (
        "dependency_unavailable:gws"
    )
    assert _preflight_skip_reason("Notion API unreachable: timeout").render() == (
        "dependency_unavailable:notion_api"
    )
    assert _preflight_skip_reason("Database not writable: unable to open").render() == (
        "dependency_unavailable:job_search_db"
    )
    assert _preflight_skip_reason("Already ran prepare today").render() == (
        "not_due (already ran prepare today)"
    )


# ---------------------------------------------------------------------------
# Test 7 — _failure_key slug derivation
# ---------------------------------------------------------------------------

def test_failure_key_slugifies_first_token():
    """The skip_reason ``preflight_failed:<key>`` is grep-friendly.

    Make sure ``_failure_key`` extracts a stable token — first whitespace
    chunk, stripped of trailing punctuation — even when preflight returns
    sentence-style errors.
    """
    # Real strings from preflight.py
    assert _failure_key("notion_api_token missing from .secrets") == "notion_api_token"
    assert _failure_key("claude_oauth_token missing from .secrets") == "claude_oauth_token"
    assert _failure_key("Secrets file not found: /tmp/.secrets") == "Secrets"
    assert _failure_key("Database not writable: unable to open") == "Database"
    assert _failure_key("Notion API token is invalid (401)") == "Notion"
    assert _failure_key("Already ran prepare today") == "Already"
    assert _failure_key("gws CLI not found — needed for outreach email sending") == "gws"
    # Edge cases
    assert _failure_key("") == "unknown"
    assert _failure_key("   ") == "unknown"


# ---------------------------------------------------------------------------
# Test 8 — should_run=False short-circuit happens BEFORE preflight (cheaper)
# ---------------------------------------------------------------------------

def test_should_run_false_skips_preflight_too():
    """If should_run() returns False (outside window), preflight isn't called.

    Preflight does file IO and an HTTP probe to Notion — meaningful cost.
    The window check should short-circuit ahead of it.
    """
    with tempfile.TemporaryDirectory() as tmp:
        svc = JobSearchPrepareService(data_dir=tmp, chat_id="")

        with (
            patch.object(svc, "should_run", return_value=False),
            patch("job_search.service._run_preflight") as mock_pf,
        ):
            result = svc.run()

        # Preflight was NOT consulted because should_run already said no
        mock_pf.assert_not_called()
        assert isinstance(result, ServiceResult)
        assert result.skip_reason is not None  # outside-window SKIP

        st = _state(svc)
        # Skipped via the should_run path (not preflight) so reason matches
        assert st["last_skipped_reason"] != "preflight_failed:unknown"
        assert "outside window" in (st["last_skipped_reason"] or "").lower() or \
               "already ran today" in (st["last_skipped_reason"] or "").lower()


# ---------------------------------------------------------------------------
# Test 9 — file-path locator returns the canonical paths
# ---------------------------------------------------------------------------

def test_preflight_paths_resolve_to_expected_locations(tmp_path: Path):
    """``_preflight_paths`` returns the same paths the rest of the cron uses."""
    from job_search.service import _preflight_paths

    paths = _preflight_paths(tmp_path)

    assert paths["secrets_path"] == tmp_path / ".secrets"
    # criteria + candidate live next to job_search/service.py — i.e. inside
    # the job_search package
    assert paths["criteria_path"].name == "criteria.json"
    assert paths["criteria_path"].parent.name == "job_search"
    assert paths["candidate_path"].name == "candidate.json"
    assert paths["candidate_path"].parent.name == "job_search"
    assert paths["db_path"] == tmp_path / "job_search.db"
    assert paths["state_dir"] == tmp_path
