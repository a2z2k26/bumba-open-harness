"""Tests for ``scripts/z4_recovery_drill.py``.

Sprint R4.2 acceptance: cover the four scenarios (failure / requeue /
retry-with-backoff / reaper) end-to-end + the CLI exit-code contract.
The drill is offline + deterministic; tests assert that contract by
running the real scenarios — if the patch leaked, the test would hang
on a live model call.
"""
from __future__ import annotations

import json
from unittest import mock

import pytest

from scripts.z4_recovery_drill import (
    DrillResult,
    ScenarioResult,
    _SCENARIOS,
    main,
    render_json,
    render_text,
    run_drill,
)


# ---------------------------------------------------------------------------
# Per-scenario async tests (drive each scenario directly)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_scenario_failure_returns_pass():
    result = await _SCENARIOS["failure"]()
    assert result.ok is True
    assert result.name == "failure"
    assert result.final_state == "failed"
    assert "chief_dispatcher.routed" in result.events_seen


@pytest.mark.asyncio
async def test_scenario_requeue_returns_pass():
    result = await _SCENARIOS["requeue"]()
    assert result.ok is True
    assert result.name == "requeue"
    assert result.final_state == "warm"
    assert "chief_dispatcher.requeued" in result.events_seen


@pytest.mark.asyncio
async def test_scenario_retry_with_backoff_returns_pass():
    result = await _SCENARIOS["retry_with_backoff"]()
    assert result.ok is True
    assert result.name == "retry_with_backoff"
    assert result.final_state == "warm"
    assert "chief_dispatcher.requeued" in result.events_seen


@pytest.mark.asyncio
async def test_scenario_reaper_returns_pass():
    result = await _SCENARIOS["reaper"]()
    assert result.ok is True
    assert result.name == "reaper"
    assert result.final_state == "shutdown"
    assert "chief_session.timed_out" in result.events_seen


# ---------------------------------------------------------------------------
# Sync wrapper + aggregate
# ---------------------------------------------------------------------------


def test_run_drill_all_scenarios_aggregate_ok():
    result = run_drill(sorted(_SCENARIOS))
    assert result.ok is True
    assert len(result.scenarios) == 4
    assert result.failed_count == 0
    assert {s.name for s in result.scenarios} == set(_SCENARIOS)


def test_run_drill_subset_only_runs_named_scenarios():
    result = run_drill(["failure", "requeue"])
    assert len(result.scenarios) == 2
    assert {s.name for s in result.scenarios} == {"failure", "requeue"}


# ---------------------------------------------------------------------------
# DrillResult invariants
# ---------------------------------------------------------------------------


class TestDrillResultInvariants:
    def test_empty_drill_is_ok_with_zero_scenarios(self):
        result = DrillResult()
        assert result.ok is True
        assert result.failed_count == 0
        assert len(result.scenarios) == 0

    def test_one_failed_scenario_makes_drill_not_ok(self):
        scenarios = (
            ScenarioResult(name="a", ok=True, detail="ok"),
            ScenarioResult(name="b", ok=False, detail="bad"),
        )
        result = DrillResult(scenarios=scenarios)
        assert result.ok is False
        assert result.failed_count == 1


# ---------------------------------------------------------------------------
# Renderers
# ---------------------------------------------------------------------------


class TestRenderText:
    def test_text_output_marks_pass_and_fail(self):
        result = DrillResult(
            scenarios=(
                ScenarioResult(
                    name="a",
                    ok=True,
                    detail="happy",
                    final_state="warm",
                    events_seen=("e",),
                ),
                ScenarioResult(
                    name="b",
                    ok=False,
                    detail="degraded",
                    final_state="failed",
                    error="thing broke",
                ),
            )
        )
        text = render_text(result)
        assert "[PASS] a:" in text
        assert "[FAIL] b:" in text
        assert "thing broke" in text
        assert "events_seen=['e']" in text


class TestRenderJson:
    def test_json_summary_shape(self):
        result = DrillResult(
            scenarios=(
                ScenarioResult(name="a", ok=True, detail="ok"),
                ScenarioResult(name="b", ok=False, detail="bad"),
            )
        )
        payload = json.loads(render_json(result))
        assert payload["ok"] is False
        assert payload["scenario_count"] == 2
        assert payload["failed_count"] == 1
        assert {s["name"] for s in payload["scenarios"]} == {"a", "b"}


# ---------------------------------------------------------------------------
# CLI exit-code contract
# ---------------------------------------------------------------------------


class TestMainExitCodes:
    def test_exit_zero_when_all_scenarios_pass(self, capsys):
        rc = main([])  # default: all four scenarios
        assert rc == 0
        out = capsys.readouterr().out
        assert "ok:             True" in out
        # All four PASS markers should appear.
        assert out.count("[PASS]") == 4

    def test_exit_one_when_any_scenario_fails(self, capsys):
        bad = DrillResult(
            scenarios=(
                ScenarioResult(name="failure", ok=False, detail="x"),
            )
        )
        with mock.patch(
            "scripts.z4_recovery_drill.run_drill", return_value=bad,
        ):
            rc = main(["--scenario", "failure"])
        assert rc == 1
        out = capsys.readouterr().out
        assert "[FAIL] failure" in out

    def test_exit_two_when_run_drill_raises(self, capsys):
        with mock.patch(
            "scripts.z4_recovery_drill.run_drill",
            side_effect=RuntimeError("import broke"),
        ):
            rc = main([])
        assert rc == 2
        err = capsys.readouterr().err
        assert "internal harness error" in err

    def test_scenario_flag_subset(self, capsys):
        rc = main(["--scenario", "failure", "--scenario", "requeue"])
        assert rc == 0
        out = capsys.readouterr().out
        # Two PASS markers, not four.
        assert out.count("[PASS]") == 2
        assert "scenario_count: 2" in out

    def test_json_flag_emits_parseable_payload(self, capsys):
        rc = main(["--scenario", "failure", "--json"])
        assert rc == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["ok"] is True
        assert payload["scenario_count"] == 1
        assert payload["scenarios"][0]["name"] == "failure"
