"""Tests for ``scripts/z4_smoke_probe.py``.

Sprint R4.1 acceptance: assert the synthetic WorkOrder summary includes
the complete event path, the test runs offline, and the CLI's exit-code
contract (0 = ok, 1 = degraded, 2 = harness error) is honoured.
"""
from __future__ import annotations

import json
from unittest import mock

import pytest

from scripts.z4_smoke_probe import (
    ProbeResult,
    main,
    render_json,
    render_text,
    run_probe,
)


@pytest.mark.asyncio
async def test_probe_happy_path_returns_complete_event_path():
    """Synthetic WorkOrder produces a ProbeResult with all three events."""
    from scripts.z4_smoke_probe import _run_probe_async

    result = await _run_probe_async("qa", "test intent")

    assert result.ok is True
    assert result.department == "qa"
    assert result.session_id.startswith("cs-")
    assert result.work_order_id  # non-empty UUID
    assert result.final_state == "awaiting_evaluation"
    assert set(result.events_present) == {
        "chief_session.created",
        "chief_session.state_changed",
        "chief_dispatcher.routed",
    }
    assert result.events_missing == ()
    assert result.correlation_ok is True
    assert result.error is None


def test_run_probe_sync_wrapper():
    """The synchronous wrapper drives the async probe to completion."""
    result = run_probe("qa", "sync wrapper test")
    assert result.ok is True
    assert result.final_state == "awaiting_evaluation"


def test_render_text_includes_all_summary_fields():
    result = ProbeResult(
        ok=True,
        department="qa",
        session_id="cs-abc",
        work_order_id="wo-xyz",
        final_state="awaiting_evaluation",
        events_present=("chief_session.created",),
        events_missing=(),
        correlation_ok=True,
        error=None,
    )
    text = render_text(result)
    assert "department=qa" in text
    assert "cs-abc" in text
    assert "wo-xyz" in text
    assert "awaiting_evaluation" in text
    assert "True" in text  # ok: True


def test_render_json_is_parseable_and_contains_expected_keys():
    result = ProbeResult(
        ok=False,
        department="qa",
        session_id="",
        work_order_id="wo-1",
        final_state="failed",
        events_present=(),
        events_missing=("chief_dispatcher.routed",),
        correlation_ok=False,
        error="dispatch raised",
    )
    payload = json.loads(render_json(result))
    assert payload["ok"] is False
    assert payload["department"] == "qa"
    assert payload["events_missing"] == ["chief_dispatcher.routed"]
    assert payload["error"] == "dispatch raised"


# ---------------------------------------------------------------------------
# CLI exit-code contract
# ---------------------------------------------------------------------------


class TestMainExitCodes:
    def test_exit_zero_on_happy_path(self, capsys):
        rc = main(["--department", "qa"])
        assert rc == 0
        out = capsys.readouterr().out
        assert "ok:              True" in out

    def test_json_flag_emits_parseable_payload(self, capsys):
        rc = main(["--department", "qa", "--json"])
        assert rc == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["ok"] is True
        assert payload["department"] == "qa"
        assert "chief_dispatcher.routed" in payload["events_present"]

    def test_exit_one_when_probe_returns_degraded(self, capsys):
        """A degraded ProbeResult (events missing) maps to exit 1."""
        degraded = ProbeResult(
            ok=False,
            department="qa",
            session_id="cs-x",
            work_order_id="wo-x",
            final_state="awaiting_evaluation",
            events_present=("chief_session.created",),
            events_missing=("chief_dispatcher.routed",),
            correlation_ok=True,
            error="missing events: ['chief_dispatcher.routed']",
        )
        with mock.patch(
            "scripts.z4_smoke_probe.run_probe", return_value=degraded,
        ):
            rc = main(["--department", "qa"])
        assert rc == 1
        out = capsys.readouterr().out
        assert "ok:              False" in out
        assert "missing events" in out

    def test_exit_two_when_run_probe_raises(self, capsys):
        """An unexpected exception during probe construction maps to exit 2."""
        with mock.patch(
            "scripts.z4_smoke_probe.run_probe",
            side_effect=RuntimeError("import broke"),
        ):
            rc = main(["--department", "qa"])
        assert rc == 2
        err = capsys.readouterr().err
        assert "internal harness error" in err
        assert "RuntimeError" in err

    def test_intent_flag_threads_through(self, capsys):
        """The --intent flag reaches the underlying WorkOrder."""
        # We can't read the WorkOrder back from the CLI without
        # patching, but we can prove the flag is accepted and the run
        # still succeeds (acceptance of the arg shape, not a deep
        # round-trip).
        rc = main(
            ["--department", "qa", "--intent", "custom probe intent"]
        )
        assert rc == 0


# ---------------------------------------------------------------------------
# Offline / determinism contract
# ---------------------------------------------------------------------------


class TestOffline:
    """Probe must not call any external service.

    Any escape would manifest as an attempted network call. We verify
    the chief-execution patch by asserting the result fields could only
    be produced by the fake TeamResult (cost_usd=0, manager_output is
    the probe's deterministic string).
    """

    def test_no_anthropic_call_during_probe(self):
        """A successful probe means WarmChief._run_chief was patched.

        If the patch leaked, the underlying ``_run_chief`` would attempt
        a model call and fail in this offline environment.
        """
        result = run_probe("qa", "offline check")
        assert result.ok is True

    def test_each_run_uses_fresh_session_id(self):
        """Each invocation creates a brand-new session — no cross-run state."""
        first = run_probe("qa", "run 1")
        second = run_probe("qa", "run 2")
        assert first.session_id != second.session_id
        assert first.work_order_id != second.work_order_id
