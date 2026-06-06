"""Tests for scripts/rtk_cost_baseline_window.py.

D6-bis Chain B prep — verifies the rtk-baseline-window aggregator filters
correctly by window, rolls up costs by model/day/feature, and writes a
markdown summary in the shape the runbook expects.
"""
from __future__ import annotations

import importlib.util
import json
from collections import Counter
from pathlib import Path

import pytest


def _load_module():
    """Import scripts/rtk_cost_baseline_window.py as a module.

    Path resolution: agent/tests/<f>.py → parent → parent → REPO ROOT
    → scripts/rtk_cost_baseline_window.py

    The module is registered in ``sys.modules`` before exec_module runs so
    that ``@dataclass(field(default_factory=...))`` annotation resolution
    can find the module's namespace via ``cls.__module__`` lookup. Without
    this, Python 3.13's dataclass machinery raises AttributeError on
    NoneType when annotations reference classes from the same module.
    """
    import sys
    name = "rtk_cost_baseline_window"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(
        name,
        Path(__file__).resolve().parent.parent.parent
        / "scripts"
        / f"{name}.py",
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def _write_jsonl(path: Path, entries: list[dict]) -> None:
    path.write_text(
        "\n".join(json.dumps(e) for e in entries) + "\n",
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# Window filtering
# ---------------------------------------------------------------------------


class TestWindowFilter:
    def test_includes_entries_in_window(self, tmp_path: Path):
        mod = _load_module()
        log = tmp_path / "cost.jsonl"
        _write_jsonl(log, [
            {"timestamp": "2026-05-09T08:00:00Z", "model": "haiku",
             "input_tokens": 1000, "output_tokens": 200,
             "estimated_cost": 0.002},
            {"timestamp": "2026-05-09T20:00:00Z", "model": "sonnet",
             "input_tokens": 5000, "output_tokens": 1000,
             "estimated_cost": 0.027},
        ])
        summary = mod.aggregate_window(
            log,
            start=mod.parse_iso("2026-05-09T00:00:00Z"),
            end=mod.parse_iso("2026-05-10T00:00:00Z"),
            label="test",
        )
        assert summary.entry_count == 2
        assert summary.total_cost_usd == pytest.approx(0.029)
        assert summary.total_input_tokens == 6000
        assert summary.total_output_tokens == 1200

    def test_excludes_entries_before_window(self, tmp_path: Path):
        mod = _load_module()
        log = tmp_path / "cost.jsonl"
        _write_jsonl(log, [
            # Just before window start — must be excluded
            {"timestamp": "2026-05-08T23:59:59Z", "model": "haiku",
             "input_tokens": 100, "output_tokens": 50,
             "estimated_cost": 0.001},
            # Inside window
            {"timestamp": "2026-05-09T00:00:00Z", "model": "sonnet",
             "input_tokens": 5000, "output_tokens": 1000,
             "estimated_cost": 0.027},
        ])
        summary = mod.aggregate_window(
            log,
            start=mod.parse_iso("2026-05-09T00:00:00Z"),
            end=mod.parse_iso("2026-05-10T00:00:00Z"),
            label="test",
        )
        assert summary.entry_count == 1
        assert summary.total_cost_usd == pytest.approx(0.027)

    def test_excludes_entries_at_or_after_end(self, tmp_path: Path):
        """End is exclusive — an entry at exactly end_ts is excluded."""
        mod = _load_module()
        log = tmp_path / "cost.jsonl"
        _write_jsonl(log, [
            {"timestamp": "2026-05-10T00:00:00Z", "model": "haiku",
             "input_tokens": 100, "output_tokens": 50,
             "estimated_cost": 0.001},
        ])
        summary = mod.aggregate_window(
            log,
            start=mod.parse_iso("2026-05-09T00:00:00Z"),
            end=mod.parse_iso("2026-05-10T00:00:00Z"),
            label="test",
        )
        assert summary.entry_count == 0

    def test_handles_missing_log_file(self, tmp_path: Path):
        mod = _load_module()
        summary = mod.aggregate_window(
            tmp_path / "nope.jsonl",
            start=mod.parse_iso("2026-05-09T00:00:00Z"),
            end=mod.parse_iso("2026-05-10T00:00:00Z"),
            label="test",
        )
        assert summary.entry_count == 0
        assert summary.total_cost_usd == 0.0

    def test_skips_malformed_lines(self, tmp_path: Path):
        """A malformed JSON line, missing-timestamp line, or unparseable
        timestamp must not crash the aggregator.
        """
        mod = _load_module()
        log = tmp_path / "cost.jsonl"
        log.write_text(
            # Mix valid + invalid + empty lines
            '{"timestamp":"2026-05-09T08:00:00Z","model":"haiku","estimated_cost":0.002}\n'
            "not valid json\n"
            "\n"
            '{"no_timestamp":true,"estimated_cost":99}\n'
            '{"timestamp":"not-a-date","estimated_cost":99}\n'
            '{"timestamp":"2026-05-09T20:00:00Z","model":"sonnet","estimated_cost":0.027}\n',
            encoding="utf-8",
        )
        summary = mod.aggregate_window(
            log,
            start=mod.parse_iso("2026-05-09T00:00:00Z"),
            end=mod.parse_iso("2026-05-10T00:00:00Z"),
            label="test",
        )
        assert summary.entry_count == 2
        assert summary.total_cost_usd == pytest.approx(0.029)


# ---------------------------------------------------------------------------
# Roll-up shape
# ---------------------------------------------------------------------------


class TestRollups:
    def test_by_model_counts_calls(self, tmp_path: Path):
        mod = _load_module()
        log = tmp_path / "cost.jsonl"
        _write_jsonl(log, [
            {"timestamp": "2026-05-09T08:00:00Z", "model": "haiku",
             "estimated_cost": 0.002},
            {"timestamp": "2026-05-09T09:00:00Z", "model": "haiku",
             "estimated_cost": 0.003},
            {"timestamp": "2026-05-09T10:00:00Z", "model": "sonnet",
             "estimated_cost": 0.027},
        ])
        summary = mod.aggregate_window(
            log,
            start=mod.parse_iso("2026-05-09T00:00:00Z"),
            end=mod.parse_iso("2026-05-10T00:00:00Z"),
            label="test",
        )
        assert summary.by_model == Counter({"haiku": 2, "sonnet": 1})

    def test_by_day_sums_cost_per_calendar_date(self, tmp_path: Path):
        mod = _load_module()
        log = tmp_path / "cost.jsonl"
        _write_jsonl(log, [
            {"timestamp": "2026-05-09T08:00:00Z", "model": "haiku",
             "estimated_cost": 0.002},
            {"timestamp": "2026-05-09T20:00:00Z", "model": "sonnet",
             "estimated_cost": 0.027},
            {"timestamp": "2026-05-10T08:00:00Z", "model": "opus",
             "estimated_cost": 0.30},
        ])
        summary = mod.aggregate_window(
            log,
            start=mod.parse_iso("2026-05-09T00:00:00Z"),
            end=mod.parse_iso("2026-05-11T00:00:00Z"),
            label="test",
        )
        assert summary.by_day["2026-05-09"] == pytest.approx(0.029)
        assert summary.by_day["2026-05-10"] == pytest.approx(0.30)

    def test_by_feature_groups_calls(self, tmp_path: Path):
        mod = _load_module()
        log = tmp_path / "cost.jsonl"
        _write_jsonl(log, [
            {"timestamp": "2026-05-09T08:00:00Z", "feature": "discord",
             "estimated_cost": 0.002},
            {"timestamp": "2026-05-09T09:00:00Z", "feature": "discord",
             "estimated_cost": 0.003},
            {"timestamp": "2026-05-09T10:00:00Z", "feature": "board",
             "estimated_cost": 0.027},
            # Empty feature → "(unattributed)" bucket
            {"timestamp": "2026-05-09T11:00:00Z", "feature": "",
             "estimated_cost": 0.001},
        ])
        summary = mod.aggregate_window(
            log,
            start=mod.parse_iso("2026-05-09T00:00:00Z"),
            end=mod.parse_iso("2026-05-10T00:00:00Z"),
            label="test",
        )
        assert summary.by_feature["discord"] == 2
        assert summary.by_feature["board"] == 1
        assert summary.by_feature["(unattributed)"] == 1


# ---------------------------------------------------------------------------
# Markdown rendering
# ---------------------------------------------------------------------------


class TestMarkdownRender:
    def test_render_includes_header_and_totals(self):
        mod = _load_module()
        summary = mod.WindowSummary(
            label="pre-rtk-baseline",
            start="2026-05-09T00:00:00+00:00",
            end="2026-05-16T00:00:00+00:00",
            entry_count=3,
            total_cost_usd=0.329,
            total_input_tokens=16000,
            total_output_tokens=3200,
            by_model=Counter({"haiku": 1, "sonnet": 1, "opus": 1}),
            by_day={"2026-05-09": 0.029, "2026-05-10": 0.30},
            by_feature=Counter({"discord": 2, "board": 1}),
        )
        rendered = mod.render_markdown(summary)
        assert "# Cost Window — pre-rtk-baseline" in rendered
        assert "Entries: 3" in rendered
        assert "$0.3290" in rendered
        assert "16,000" in rendered  # input tokens with comma
        assert "## By model" in rendered
        assert "## By day (USD)" in rendered
        assert "## Top features by call count" in rendered
        assert "haiku" in rendered
        assert "discord" in rendered

    def test_render_empty_window_states_so(self):
        mod = _load_module()
        summary = mod.WindowSummary(
            label="empty-week",
            start="2026-05-09T00:00:00+00:00",
            end="2026-05-16T00:00:00+00:00",
        )
        rendered = mod.render_markdown(summary)
        assert "Entries: 0" in rendered
        assert "_No cost entries in this window._" in rendered


# ---------------------------------------------------------------------------
# CLI exit codes
# ---------------------------------------------------------------------------


class TestCLI:
    def test_writes_summary_and_returns_zero_on_data(self, tmp_path: Path):
        mod = _load_module()
        log = tmp_path / "cost.jsonl"
        _write_jsonl(log, [
            {"timestamp": "2026-05-09T08:00:00Z", "model": "haiku",
             "estimated_cost": 0.002},
        ])
        out = tmp_path / "summary.md"
        rc = mod.main([
            "--start", "2026-05-09T00:00:00Z",
            "--end", "2026-05-10T00:00:00Z",
            "--label", "test",
            "--output", str(out),
            "--cost-log", str(log),
        ])
        assert rc == 0
        assert out.exists()
        assert "test" in out.read_text(encoding="utf-8")

    def test_returns_one_when_log_missing(self, tmp_path: Path):
        mod = _load_module()
        out = tmp_path / "summary.md"
        rc = mod.main([
            "--start", "2026-05-09T00:00:00Z",
            "--end", "2026-05-10T00:00:00Z",
            "--label", "test",
            "--output", str(out),
            "--cost-log", str(tmp_path / "nope.jsonl"),
        ])
        # Empty summary written, exit 1 to flag the operator
        assert rc == 1
        assert out.exists()

    def test_returns_two_on_inverted_window(self, tmp_path: Path):
        mod = _load_module()
        out = tmp_path / "summary.md"
        rc = mod.main([
            "--start", "2026-05-10T00:00:00Z",
            "--end", "2026-05-09T00:00:00Z",  # before start → error
            "--label", "test",
            "--output", str(out),
            "--cost-log", str(tmp_path / "nope.jsonl"),
        ])
        assert rc == 2

    def test_returns_two_on_bad_iso_timestamp(self, tmp_path: Path):
        mod = _load_module()
        out = tmp_path / "summary.md"
        rc = mod.main([
            "--start", "not-a-date",
            "--end", "2026-05-09T00:00:00Z",
            "--label", "test",
            "--output", str(out),
            "--cost-log", str(tmp_path / "nope.jsonl"),
        ])
        assert rc == 2
