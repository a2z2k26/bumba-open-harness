"""Tests for the Zone 4 operator report loader (Z4-23 #2449).

The report loader (``bridge.zone4_report``) reads the run manifests the
Zone 4 pipeline persists under ``zone4_artifact_root`` (one
``<run-id>/manifest.json`` per run — see ``bridge/run_artifacts.py`` and
``teams/_team.py::_finalize_run_relay``) and aggregates them by department
for a time window.

Contract under test:

- Reads metadata only — never loads artifact bodies. Asserted by writing a
  large artifact file alongside the manifest and confirming the loader's
  byte count comes from the manifest entry, not a file read.
- Aggregates runs, success/failure (by class), provider primary/fallback
  counts, token sums, artifact counts, missing-surface counts, average and
  longest duration.
- Filters by window (24h / 7d / explicit since/until).
- Links back to manifest paths rather than embedding outputs.
- Empty data yields an empty (but well-formed) report.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from bridge.zone4_report import (
    Zone4Report,
    build_report,
    parse_window,
)


# ---------------------------------------------------------------------------
# Fixtures — write synthetic manifests into a tmp artifact root
# ---------------------------------------------------------------------------


def _write_manifest(
    root: Path,
    run_id: str,
    *,
    department: str,
    status: str = "success",
    completed_at: datetime,
    primary_model: str = "anthropic:claude-opus-4-6",
    fallback_model: str | None = None,
    input_tokens: int = 0,
    output_tokens: int = 0,
    request_count: int = 0,
    duration_seconds: float = 0.0,
    failure_class: str | None = None,
    artifacts: int = 0,
    surfaces: int = 0,
) -> Path:
    """Write one manifest.json matching the run_artifacts schema."""
    run_dir = root / run_id
    run_dir.mkdir(parents=True)
    telemetry: dict[str, str] = {
        "primary_model": primary_model,
        "input_tokens": str(input_tokens),
        "output_tokens": str(output_tokens),
        "request_count": str(request_count),
        "duration_seconds": str(duration_seconds),
    }
    if fallback_model is not None:
        telemetry["fallback_model"] = fallback_model
    if failure_class is not None:
        telemetry["failure_class"] = failure_class

    artifact_entries = [
        {
            "path": f"out-{i}.md",
            "kind": "result",
            "agent": f"{department}-specialist",
            "bytes": 1024,
            "sha256": "deadbeef",
        }
        for i in range(artifacts)
    ]
    surface_ids = [f"surface-{i}" for i in range(surfaces)]

    payload = {
        "schema_version": 1,
        "run_id": run_id,
        "session_id": f"cs-{run_id}",
        "department": department,
        "directive_id": None,
        "started_at_utc": (completed_at - timedelta(seconds=duration_seconds))
        .strftime("%Y-%m-%dT%H:%M:%SZ"),
        "completed_at_utc": completed_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "chief": f"{department}-chief",
        "status": status,
        "artifacts": artifact_entries,
        "surfaces": surface_ids,
        "telemetry": telemetry,
        "project_root": None,
    }
    manifest_path = run_dir / "manifest.json"
    manifest_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return manifest_path


@pytest.fixture
def now() -> datetime:
    return datetime(2026, 6, 1, 12, 0, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# parse_window
# ---------------------------------------------------------------------------


class TestParseWindow:
    def test_24h(self, now: datetime):
        start, end, label = parse_window("24h", now=now)
        assert label == "24h"
        assert end == now
        assert start == now - timedelta(hours=24)

    def test_7d(self, now: datetime):
        start, end, label = parse_window("7d", now=now)
        assert label == "7d"
        assert start == now - timedelta(days=7)

    def test_explicit_since_until(self, now: datetime):
        start, end, label = parse_window(
            None,
            since="2026-05-01T00:00:00Z",
            until="2026-05-02T00:00:00Z",
            now=now,
        )
        assert start == datetime(2026, 5, 1, tzinfo=timezone.utc)
        assert end == datetime(2026, 5, 2, tzinfo=timezone.utc)
        assert "2026-05-01" in label

    def test_unknown_window_raises(self, now: datetime):
        with pytest.raises(ValueError):
            parse_window("99z", now=now)

    def test_since_after_until_raises(self, now: datetime):
        with pytest.raises(ValueError):
            parse_window(
                None,
                since="2026-05-02T00:00:00Z",
                until="2026-05-01T00:00:00Z",
                now=now,
            )


# ---------------------------------------------------------------------------
# build_report — empty data
# ---------------------------------------------------------------------------


def test_empty_root_yields_empty_report(tmp_path: Path, now: datetime):
    report = build_report(tmp_path, window="24h", now=now)
    assert isinstance(report, Zone4Report)
    assert report.window == "24h"
    assert report.total_runs == 0
    assert report.departments == ()


def test_missing_root_yields_empty_report(tmp_path: Path, now: datetime):
    report = build_report(tmp_path / "does-not-exist", window="24h", now=now)
    assert report.total_runs == 0
    assert report.departments == ()


# ---------------------------------------------------------------------------
# build_report — aggregation
# ---------------------------------------------------------------------------


def test_mixed_success_failure_aggregation(tmp_path: Path, now: datetime):
    _write_manifest(
        tmp_path, "run-1", department="strategy", status="success",
        completed_at=now - timedelta(hours=1),
        primary_model="anthropic:claude-opus-4-6",
        input_tokens=100, output_tokens=50, request_count=3,
        duration_seconds=10.0, artifacts=2, surfaces=1,
    )
    _write_manifest(
        tmp_path, "run-2", department="strategy", status="failed",
        completed_at=now - timedelta(hours=2),
        primary_model="openrouter:x-ai/grok",
        input_tokens=10, output_tokens=0, request_count=1,
        duration_seconds=30.0, failure_class="usage_limit_exceeded",
        artifacts=0, surfaces=0,
    )
    _write_manifest(
        tmp_path, "run-3", department="qa", status="success",
        completed_at=now - timedelta(hours=3),
        primary_model="anthropic:claude-sonnet-4-6",
        fallback_model="openrouter:fallback",
        input_tokens=20, output_tokens=20, request_count=2,
        duration_seconds=5.0, artifacts=1, surfaces=1,
    )

    report = build_report(tmp_path, window="24h", now=now)

    assert report.total_runs == 3
    depts = {d.department: d for d in report.departments}
    assert set(depts) == {"strategy", "qa"}

    strategy = depts["strategy"]
    assert strategy.runs == 2
    assert strategy.success == 1
    assert strategy.failure == 1
    assert strategy.failures_by_class == {"usage_limit_exceeded": 1}
    # Provider path: opus is anthropic (primary), grok is openrouter (primary)
    assert strategy.primary_provider_counts["anthropic"] == 1
    assert strategy.primary_provider_counts["openrouter"] == 1
    assert strategy.input_tokens == 110
    assert strategy.output_tokens == 50
    assert strategy.artifact_count == 2
    assert strategy.missing_surface_count == 1  # run-2 wrote 0 surfaces
    # avg duration over the two runs = (10 + 30) / 2 = 20
    assert strategy.average_duration_seconds == pytest.approx(20.0)
    assert strategy.longest_duration_seconds == pytest.approx(30.0)

    qa = depts["qa"]
    assert qa.runs == 1
    assert qa.fallback_provider_counts["openrouter"] == 1
    assert qa.missing_surface_count == 0


def test_window_filters_out_old_runs(tmp_path: Path, now: datetime):
    # In-window run.
    _write_manifest(
        tmp_path, "run-recent", department="design", status="success",
        completed_at=now - timedelta(hours=2), artifacts=1, surfaces=1,
    )
    # Out-of-window run (8 days old; 7d window excludes it).
    _write_manifest(
        tmp_path, "run-old", department="design", status="success",
        completed_at=now - timedelta(days=8), artifacts=1, surfaces=1,
    )
    report_24h = build_report(tmp_path, window="24h", now=now)
    assert report_24h.total_runs == 1

    report_7d = build_report(tmp_path, window="7d", now=now)
    assert report_7d.total_runs == 1  # 8-day-old still excluded

    # A wider explicit window catches both.
    report_all = build_report(
        tmp_path,
        since=(now - timedelta(days=30)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        until=now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        now=now,
    )
    assert report_all.total_runs == 2


def test_report_links_manifest_paths_not_bodies(tmp_path: Path, now: datetime):
    manifest_path = _write_manifest(
        tmp_path, "run-link", department="ops", status="success",
        completed_at=now - timedelta(hours=1), artifacts=1, surfaces=1,
    )
    # Write a large artifact body next to the manifest. The loader must not
    # read it — proven by the report carrying the manifest path and the
    # byte total coming from the manifest entry (1024), not the real file.
    big = tmp_path / "run-link" / "out-0.md"
    big.write_text("X" * 5_000_000, encoding="utf-8")

    report = build_report(tmp_path, window="24h", now=now)
    ops = report.departments[0]
    assert ops.department == "ops"
    assert str(manifest_path) in ops.manifest_paths
    # bytes total from manifest entry, not the 5MB real file
    assert ops.artifact_bytes == 1024


def test_running_status_counts_as_neither_success_nor_failure(
    tmp_path: Path, now: datetime
):
    _write_manifest(
        tmp_path, "run-inflight", department="board", status="running",
        completed_at=now - timedelta(minutes=5),
    )
    report = build_report(tmp_path, window="24h", now=now)
    board = report.departments[0]
    assert board.runs == 1
    assert board.success == 0
    assert board.failure == 0
    assert board.running == 1


def test_corrupt_manifest_is_skipped_not_fatal(tmp_path: Path, now: datetime):
    _write_manifest(
        tmp_path, "run-good", department="qa", status="success",
        completed_at=now - timedelta(hours=1), artifacts=1, surfaces=1,
    )
    bad_dir = tmp_path / "run-bad"
    bad_dir.mkdir()
    (bad_dir / "manifest.json").write_text("{not json", encoding="utf-8")

    report = build_report(tmp_path, window="24h", now=now)
    assert report.total_runs == 1
    assert report.skipped_count == 1


def test_to_dict_shape_matches_api_sketch(tmp_path: Path, now: datetime):
    _write_manifest(
        tmp_path, "run-x", department="strategy", status="success",
        completed_at=now - timedelta(hours=1),
        primary_model="anthropic:claude-opus-4-6",
        input_tokens=100, output_tokens=50, request_count=3,
        duration_seconds=10.0, artifacts=2, surfaces=1,
    )
    report = build_report(tmp_path, window="24h", now=now)
    payload = report.to_dict()
    assert payload["window"] == "24h"
    assert payload["total_runs"] == 1
    assert isinstance(payload["departments"], list)
    dept = payload["departments"][0]
    for key in (
        "department", "runs", "success", "failures", "providers",
        "fallback_providers", "input_tokens", "output_tokens",
        "artifacts", "fallbacks", "missing_surfaces",
        "average_duration_seconds", "longest_duration_seconds",
        "manifest_paths",
    ):
        assert key in dept, f"missing key {key!r} in department report dict"
