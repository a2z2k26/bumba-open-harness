"""Board Phase 1 — Metering workstream (issue #2390).

Covers the three genuine gaps the metering AC names, given the prior
cost-attribution work already in place:

1. ``RunMetrics`` value object + ``SynthesisResult.metrics`` on the
   factory/board synthesizer result (``bridge.synthesizer``).
2. Cumulative cost accumulation in ``ServiceBase.record_success`` —
   ``data/service_state/<name>-state.json`` gains ``total_cost_usd``
   alongside ``total_runs``.
3. ``/services`` (``render_services_table`` / ``render_service_detail``)
   surfaces the cumulative per-service cost total.
"""

from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path

import pytest

from bridge.services.base import REQUIRED_STATE_FIELDS, ServiceBase
from bridge.services.result import (
    ServiceResult,
    render_service_detail,
    render_services_table,
    write_last_run,
)
from bridge.synthesizer import RunMetrics, SynthesisResult, SynthesisMode


# ---------------------------------------------------------------------------
# 1. RunMetrics + SynthesisResult.metrics
# ---------------------------------------------------------------------------


class TestRunMetrics:
    def test_run_metrics_is_frozen(self):
        m = RunMetrics(tokens_in=10, tokens_out=20, cost_usd=0.5, duration_ms=1200)
        with pytest.raises(Exception):
            m.tokens_in = 99  # type: ignore[misc]

    def test_run_metrics_fields(self):
        m = RunMetrics(tokens_in=10, tokens_out=20, cost_usd=0.5, duration_ms=1200)
        assert m.tokens_in == 10
        assert m.tokens_out == 20
        assert m.cost_usd == 0.5
        assert m.duration_ms == 1200

    def test_run_metrics_defaults_zero(self):
        m = RunMetrics()
        assert m.tokens_in == 0
        assert m.tokens_out == 0
        assert m.cost_usd == 0.0
        assert m.duration_ms == 0

    def test_run_metrics_add_is_immutable(self):
        a = RunMetrics(tokens_in=1, tokens_out=2, cost_usd=0.1, duration_ms=100)
        b = RunMetrics(tokens_in=3, tokens_out=4, cost_usd=0.2, duration_ms=200)
        c = a.add(b)
        # New object; operands unchanged.
        assert c is not a and c is not b
        assert a.tokens_in == 1 and b.tokens_in == 3
        assert c.tokens_in == 4
        assert c.tokens_out == 6
        assert c.cost_usd == pytest.approx(0.3)
        assert c.duration_ms == 300


class TestSynthesisResultMetrics:
    def test_metrics_field_defaults_none(self):
        r = SynthesisResult(success=True, combined="x")
        assert r.metrics is None

    def test_metrics_field_carried(self):
        m = RunMetrics(tokens_in=5, tokens_out=6, cost_usd=0.01, duration_ms=10)
        r = SynthesisResult(success=True, combined="x", metrics=m)
        assert r.metrics is m
        assert r.metrics.cost_usd == 0.01

    def test_result_still_frozen(self):
        r = SynthesisResult(success=True, combined="x")
        with pytest.raises(Exception):
            r.success = False  # type: ignore[misc]

    def test_existing_fields_preserved(self):
        # Back-compat: positional/keyword shape from before metrics existed.
        r = SynthesisResult(
            success=True,
            combined="abc",
            warnings=["w1"],
            mode=SynthesisMode.CONCATENATE,
        )
        assert r.success is True
        assert r.combined == "abc"
        assert r.warnings == ("w1",)
        assert r.mode == SynthesisMode.CONCATENATE
        assert r.metrics is None


# ---------------------------------------------------------------------------
# 2. Cumulative cost in ServiceBase.record_success
# ---------------------------------------------------------------------------


class TestCumulativeCost:
    def setup_method(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.svc = ServiceBase(data_dir=self.tmp_dir)

    def teardown_method(self):
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_total_cost_usd_in_required_fields(self):
        assert "total_cost_usd" in REQUIRED_STATE_FIELDS
        assert REQUIRED_STATE_FIELDS["total_cost_usd"] == 0.0

    def test_record_success_default_cost_zero(self):
        self.svc.record_success(150, filename="test-state.json")
        state = self.svc.load_state("test-state.json")
        assert state["total_cost_usd"] == 0.0

    def test_record_success_accumulates_cost(self):
        self.svc.record_success(100, filename="test-state.json", cost_usd=0.25)
        self.svc.record_success(100, filename="test-state.json", cost_usd=0.30)
        state = self.svc.load_state("test-state.json")
        assert state["total_cost_usd"] == pytest.approx(0.55)
        assert state["total_runs"] == 2

    def test_record_success_negative_cost_clamped(self):
        # Defensive: a parser glitch should never decrement the cumulative.
        self.svc.record_success(100, filename="test-state.json", cost_usd=-5.0)
        state = self.svc.load_state("test-state.json")
        assert state["total_cost_usd"] == 0.0

    def test_skip_and_failure_do_not_add_cost(self):
        self.svc.record_success(100, filename="test-state.json", cost_usd=0.10)
        self.svc.record_failure("boom", filename="test-state.json")
        self.svc.record_skipped("nothing_to_do", filename="test-state.json")
        state = self.svc.load_state("test-state.json")
        assert state["total_cost_usd"] == pytest.approx(0.10)

    def test_load_state_backfills_total_cost_for_legacy_file(self):
        # Legacy state file written before this field existed.
        legacy = {k: v for k, v in REQUIRED_STATE_FIELDS.items() if k != "total_cost_usd"}
        legacy["total_runs"] = 3
        path = Path(self.tmp_dir) / "service_state" / "legacy-state.json"
        path.write_text(json.dumps(legacy))
        state = self.svc.load_state("legacy-state.json")
        assert state["total_cost_usd"] == 0.0
        assert state["total_runs"] == 3


# ---------------------------------------------------------------------------
# 3. /services surfaces cumulative cost
# ---------------------------------------------------------------------------


class TestServicesCostRendering:
    def setup_method(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.data_dir = Path(self.tmp_dir)
        self.state_dir = self.data_dir / "service_state"
        self.state_dir.mkdir(parents=True, exist_ok=True)

    def teardown_method(self):
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def _write_cumulative(self, service: str, total_cost_usd: float, total_runs: int) -> None:
        path = self.state_dir / f"{service}-state.json"
        state = dict(REQUIRED_STATE_FIELDS)
        state["total_cost_usd"] = total_cost_usd
        state["total_runs"] = total_runs
        path.write_text(json.dumps(state))

    def test_table_shows_cumulative_cost(self):
        # Per-run line comes from last_run.json; cumulative from <name>-state.json.
        write_last_run(
            self.state_dir,
            ServiceResult(service="briefing", ok=True, work_items=2, duration_ms=500, cost_usd=0.05),
        )
        self._write_cumulative("briefing", total_cost_usd=1.23, total_runs=10)
        out = render_services_table(self.data_dir)
        assert "briefing" in out
        # Cumulative total surfaced somewhere in the table.
        assert "1.23" in out

    def test_table_without_cumulative_file_still_renders(self):
        write_last_run(
            self.state_dir,
            ServiceResult(service="email", ok=True, work_items=0, duration_ms=200, cost_usd=0.0),
        )
        out = render_services_table(self.data_dir)
        assert "email" in out  # no crash when <name>-state.json absent

    def test_detail_shows_cumulative_cost(self):
        write_last_run(
            self.state_dir,
            ServiceResult(service="retro", ok=True, work_items=1, duration_ms=300, cost_usd=0.07),
        )
        self._write_cumulative("retro", total_cost_usd=2.50, total_runs=20)
        out = render_service_detail(self.data_dir, "retro")
        assert "2.50" in out
        assert "20" in out  # total_runs surfaced alongside cumulative cost
