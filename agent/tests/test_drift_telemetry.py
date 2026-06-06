"""Tests for drift telemetry and daily digest.

Sprint 4.7 — Phase 4 (Harness Hardening).

Exercises the telemetry module (record writing, reading, round-trip)
and the daily digest (baseline computation, anomaly detection,
formatting). Edge cases: empty files, single-day data, zero-stddev,
and deliberate 10x anomaly injection.
"""
from __future__ import annotations

import json
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from bridge.drift_telemetry import (
    METRIC_FIELDS,
    MetricsRecord,
    load_metrics,
    record_metrics,
)

# The daily_digest script lives in agent/scripts/ and does its own
# sys.path manipulation for standalone CLI use. When imported from
# within the agent/ test suite, we import from the scripts package.
import sys
from pathlib import Path as _Path

_SCRIPTS_DIR = str(_Path(__file__).resolve().parent.parent / "scripts")
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

from daily_digest import (  # noqa: E402
    Anomaly,
    compute_baseline,
    detect_anomalies,
    format_digest,
    main,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _days_ago_iso(days: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()


def _make_record(
    session_id: str = "sess-1",
    timestamp: str | None = None,
    **overrides: float,
) -> MetricsRecord:
    """Build a MetricsRecord with sensible defaults."""
    defaults: dict[str, float] = {
        "velocity": 2.0,
        "bundling_indicator": 150.0,
        "work_depth": 12.0,
        "test_frequency": 300.0,
        "honesty_indicator": 1.5,
        "dialogue_responsiveness": 5.0,
        "engagement_indicator": 3.0,
    }
    defaults.update(overrides)
    return MetricsRecord(
        session_id=session_id,
        timestamp=timestamp or _now_iso(),
        **defaults,
    )


# ---------------------------------------------------------------------------
# MetricsRecord dataclass
# ---------------------------------------------------------------------------


class TestMetricsRecord:
    def test_frozen(self):
        record = _make_record()
        with pytest.raises(AttributeError):
            record.velocity = 999.0  # type: ignore[misc]

    def test_default_metric_values_are_zero(self):
        record = MetricsRecord(session_id="s1", timestamp=_now_iso())
        for field in METRIC_FIELDS:
            assert getattr(record, field) == 0.0

    def test_metric_fields_constant_matches_dataclass(self):
        """Verify the METRIC_FIELDS tuple stays in sync with the dataclass."""
        record = MetricsRecord(session_id="s1", timestamp=_now_iso())
        for field in METRIC_FIELDS:
            assert hasattr(record, field), f"MetricsRecord missing field: {field}"

    def test_all_seven_metrics_present(self):
        assert len(METRIC_FIELDS) == 7


# ---------------------------------------------------------------------------
# record_metrics — writing
# ---------------------------------------------------------------------------


class TestRecordMetrics:
    def test_creates_file_and_writes_json_line(self, tmp_path: Path):
        path = tmp_path / "metrics.jsonl"
        record = _make_record()
        record_metrics(record, path)

        assert path.exists()
        lines = path.read_text().strip().split("\n")
        assert len(lines) == 1
        obj = json.loads(lines[0])
        assert obj["session_id"] == "sess-1"
        assert obj["velocity"] == 2.0

    def test_appends_multiple_records(self, tmp_path: Path):
        path = tmp_path / "metrics.jsonl"
        record_metrics(_make_record(session_id="s1"), path)
        record_metrics(_make_record(session_id="s2"), path)

        lines = path.read_text().strip().split("\n")
        assert len(lines) == 2
        assert json.loads(lines[0])["session_id"] == "s1"
        assert json.loads(lines[1])["session_id"] == "s2"

    def test_creates_parent_directories(self, tmp_path: Path):
        path = tmp_path / "deep" / "nested" / "metrics.jsonl"
        record_metrics(_make_record(), path)
        assert path.exists()

    def test_preserves_all_metric_fields(self, tmp_path: Path):
        path = tmp_path / "metrics.jsonl"
        record = _make_record(
            velocity=1.1,
            bundling_indicator=2.2,
            work_depth=3.3,
            test_frequency=4.4,
            honesty_indicator=5.5,
            dialogue_responsiveness=6.6,
            engagement_indicator=7.7,
        )
        record_metrics(record, path)

        obj = json.loads(path.read_text().strip())
        assert obj["velocity"] == 1.1
        assert obj["bundling_indicator"] == 2.2
        assert obj["work_depth"] == 3.3
        assert obj["test_frequency"] == 4.4
        assert obj["honesty_indicator"] == 5.5
        assert obj["dialogue_responsiveness"] == 6.6
        assert obj["engagement_indicator"] == 7.7


# ---------------------------------------------------------------------------
# load_metrics — reading
# ---------------------------------------------------------------------------


class TestLoadMetrics:
    def test_returns_empty_for_missing_file(self, tmp_path: Path):
        path = tmp_path / "nonexistent.jsonl"
        assert load_metrics(path) == []

    def test_returns_empty_for_empty_file(self, tmp_path: Path):
        path = tmp_path / "empty.jsonl"
        path.write_text("")
        assert load_metrics(path) == []

    def test_round_trip_write_then_read(self, tmp_path: Path):
        path = tmp_path / "metrics.jsonl"
        original = _make_record(session_id="rt-1", velocity=42.0)
        record_metrics(original, path)

        loaded = load_metrics(path, days=1)
        assert len(loaded) == 1
        assert loaded[0].session_id == "rt-1"
        assert loaded[0].velocity == 42.0

    def test_filters_by_date(self, tmp_path: Path):
        path = tmp_path / "metrics.jsonl"
        # Write a recent record and an old record
        record_metrics(
            _make_record(session_id="recent", timestamp=_now_iso()), path
        )
        record_metrics(
            _make_record(session_id="old", timestamp=_days_ago_iso(10)), path
        )

        loaded = load_metrics(path, days=7)
        assert len(loaded) == 1
        assert loaded[0].session_id == "recent"

    def test_skips_malformed_lines(self, tmp_path: Path):
        path = tmp_path / "metrics.jsonl"
        record_metrics(_make_record(session_id="good"), path)
        # Append garbage
        with open(path, "a") as f:
            f.write("this is not json\n")
            f.write("{malformed\n")

        loaded = load_metrics(path, days=1)
        assert len(loaded) == 1
        assert loaded[0].session_id == "good"

    def test_skips_non_dict_lines(self, tmp_path: Path):
        path = tmp_path / "metrics.jsonl"
        with open(path, "w") as f:
            f.write(json.dumps([1, 2, 3]) + "\n")
            f.write(json.dumps("just a string") + "\n")

        assert load_metrics(path, days=1) == []

    def test_handles_missing_optional_fields(self, tmp_path: Path):
        """Records with missing metric fields should default to 0.0."""
        path = tmp_path / "metrics.jsonl"
        minimal = {
            "session_id": "minimal",
            "timestamp": _now_iso(),
        }
        with open(path, "w") as f:
            f.write(json.dumps(minimal) + "\n")

        loaded = load_metrics(path, days=1)
        assert len(loaded) == 1
        assert loaded[0].velocity == 0.0
        assert loaded[0].engagement_indicator == 0.0

    def test_multiple_records_round_trip(self, tmp_path: Path):
        path = tmp_path / "metrics.jsonl"
        for i in range(5):
            record_metrics(
                _make_record(session_id=f"s{i}", velocity=float(i)),
                path,
            )

        loaded = load_metrics(path, days=1)
        assert len(loaded) == 5
        assert [r.velocity for r in loaded] == [0.0, 1.0, 2.0, 3.0, 4.0]


# ---------------------------------------------------------------------------
# compute_baseline
# ---------------------------------------------------------------------------


class TestComputeBaseline:
    def test_empty_records_returns_all_zeros(self):
        baseline = compute_baseline([])
        for field in METRIC_FIELDS:
            assert baseline[field] == (0.0, 0.0)

    def test_single_record_has_zero_stddev(self):
        records = [_make_record(velocity=10.0)]
        baseline = compute_baseline(records)
        mean, stddev = baseline["velocity"]
        assert mean == 10.0
        assert stddev == 0.0

    def test_known_data_mean_and_stddev(self):
        """Three records with velocity [2, 4, 6]: mean=4, stddev=sqrt(8/3)."""
        records = [
            _make_record(velocity=2.0, timestamp=_days_ago_iso(i))
            for i in range(3)
        ]
        # Override velocities
        records = [
            MetricsRecord(
                session_id=f"s{i}",
                timestamp=records[i].timestamp,
                velocity=v,
            )
            for i, v in enumerate([2.0, 4.0, 6.0])
        ]
        baseline = compute_baseline(records)
        mean, stddev = baseline["velocity"]
        assert abs(mean - 4.0) < 1e-9
        expected_stddev = math.sqrt(
            ((2 - 4) ** 2 + (4 - 4) ** 2 + (6 - 4) ** 2) / 3
        )
        assert abs(stddev - expected_stddev) < 1e-9

    def test_all_fields_computed(self):
        records = [_make_record()]
        baseline = compute_baseline(records)
        assert set(baseline.keys()) == set(METRIC_FIELDS)

    def test_identical_values_have_zero_stddev(self):
        records = [_make_record(velocity=5.0) for _ in range(10)]
        baseline = compute_baseline(records)
        mean, stddev = baseline["velocity"]
        assert mean == 5.0
        assert stddev == 0.0


# ---------------------------------------------------------------------------
# detect_anomalies
# ---------------------------------------------------------------------------


class TestDetectAnomalies:
    def test_no_anomalies_when_within_range(self):
        baseline = {f: (5.0, 1.0) for f in METRIC_FIELDS}
        today = _make_record(
            velocity=5.5,
            bundling_indicator=5.0,
            work_depth=4.5,
            test_frequency=5.0,
            honesty_indicator=5.0,
            dialogue_responsiveness=5.0,
            engagement_indicator=5.0,
        )
        anomalies = detect_anomalies(today, baseline)
        assert anomalies == []

    def test_detects_anomaly_at_exactly_2_sigma(self):
        baseline = {f: (10.0, 1.0) for f in METRIC_FIELDS}
        today = _make_record(velocity=12.0)  # exactly 2 sigma
        anomalies = detect_anomalies(today, baseline)
        velocity_anomalies = [a for a in anomalies if a.metric == "velocity"]
        assert len(velocity_anomalies) == 1
        assert velocity_anomalies[0].sigma == 2.0

    def test_detects_anomaly_above_2_sigma(self):
        baseline = {f: (10.0, 1.0) for f in METRIC_FIELDS}
        today = _make_record(velocity=15.0)  # 5 sigma
        anomalies = detect_anomalies(today, baseline)
        velocity_anomalies = [a for a in anomalies if a.metric == "velocity"]
        assert len(velocity_anomalies) == 1
        assert velocity_anomalies[0].sigma == 5.0

    def test_detects_anomaly_below_mean(self):
        """Negative deviation should also be flagged."""
        baseline = {f: (10.0, 1.0) for f in METRIC_FIELDS}
        today = _make_record(velocity=7.5)  # -2.5 sigma
        anomalies = detect_anomalies(today, baseline)
        velocity_anomalies = [a for a in anomalies if a.metric == "velocity"]
        assert len(velocity_anomalies) == 1
        assert velocity_anomalies[0].sigma == 2.5

    def test_zero_stddev_different_value_is_anomaly(self):
        """When stddev is 0 and current != mean, sigma should be inf."""
        baseline = {"velocity": (5.0, 0.0)}
        today = _make_record(velocity=6.0)
        anomalies = detect_anomalies(today, baseline)
        velocity_anomalies = [a for a in anomalies if a.metric == "velocity"]
        assert len(velocity_anomalies) == 1
        assert math.isinf(velocity_anomalies[0].sigma)

    def test_zero_stddev_same_value_passes(self):
        """When stddev is 0 and current == mean, no anomaly."""
        baseline = {"velocity": (5.0, 0.0)}
        today = _make_record(velocity=5.0)
        anomalies = detect_anomalies(today, baseline)
        velocity_anomalies = [a for a in anomalies if a.metric == "velocity"]
        assert velocity_anomalies == []

    def test_multiple_anomalies_detected(self):
        baseline = {f: (10.0, 1.0) for f in METRIC_FIELDS}
        today = _make_record(
            velocity=15.0,  # 5 sigma
            bundling_indicator=20.0,  # 10 sigma
            work_depth=10.5,  # 0.5 sigma - should pass
        )
        anomalies = detect_anomalies(today, baseline)
        flagged = {a.metric for a in anomalies}
        assert "velocity" in flagged
        assert "bundling_indicator" in flagged
        assert "work_depth" not in flagged

    def test_missing_baseline_field_is_skipped(self):
        """If a field is not in the baseline dict, it's ignored."""
        baseline = {"velocity": (5.0, 1.0)}  # only one field
        today = _make_record(velocity=5.0, bundling_indicator=9999.0)
        anomalies = detect_anomalies(today, baseline)
        assert all(a.metric == "velocity" or False for a in anomalies)

    def test_anomaly_is_frozen(self):
        a = Anomaly(
            metric="velocity", current=10.0, mean=5.0, stddev=1.0, sigma=5.0
        )
        with pytest.raises(AttributeError):
            a.sigma = 0.0  # type: ignore[misc]

    def test_deliberate_10x_jump_detected(self):
        """Inject a 10x jump in one metric and verify detection.

        Scenario: baseline velocity averages 2 PRs/hr with stddev 0.5.
        Today's session has velocity=20 (10x jump). This should be
        flagged at 36 sigma.
        """
        baseline = {f: (2.0, 0.5) for f in METRIC_FIELDS}
        today = _make_record(velocity=20.0)
        anomalies = detect_anomalies(today, baseline)
        velocity_anomalies = [a for a in anomalies if a.metric == "velocity"]
        assert len(velocity_anomalies) == 1
        assert velocity_anomalies[0].sigma == 36.0
        assert velocity_anomalies[0].current == 20.0


# ---------------------------------------------------------------------------
# format_digest
# ---------------------------------------------------------------------------


class TestFormatDigest:
    def test_no_anomalies_returns_all_clear(self):
        digest = format_digest([])
        assert "within normal range" in digest

    def test_single_anomaly_formatting(self):
        anomalies = [
            Anomaly(
                metric="velocity",
                current=15.0,
                mean=5.0,
                stddev=2.0,
                sigma=5.0,
            )
        ]
        digest = format_digest(anomalies)
        assert "1 anomaly" in digest
        assert "Velocity" in digest
        assert "15.00" in digest
        assert "5.00" in digest
        assert "5.0 sigma" in digest

    def test_multiple_anomalies_formatting(self):
        anomalies = [
            Anomaly(
                metric="velocity",
                current=15.0,
                mean=5.0,
                stddev=2.0,
                sigma=5.0,
            ),
            Anomaly(
                metric="work_depth",
                current=50.0,
                mean=10.0,
                stddev=3.0,
                sigma=13.33,
            ),
        ]
        digest = format_digest(anomalies)
        assert "2 anomalies" in digest
        assert "Velocity" in digest
        assert "Work depth" in digest

    def test_inf_sigma_formatted(self):
        anomalies = [
            Anomaly(
                metric="velocity",
                current=10.0,
                mean=5.0,
                stddev=0.0,
                sigma=float("inf"),
            )
        ]
        digest = format_digest(anomalies)
        assert "inf sigma" in digest


# ---------------------------------------------------------------------------
# Integration: end-to-end write -> baseline -> detect -> format
# ---------------------------------------------------------------------------


class TestEndToEnd:
    def test_full_pipeline(self, tmp_path: Path):
        """Write 7 days of baseline data, then a today record with
        anomalous velocity. The digest should flag it.
        """
        path = tmp_path / "bridge-metrics.jsonl"

        # Write baseline: 7 sessions across 7 days, velocity ~2.0
        for day in range(1, 8):
            record_metrics(
                _make_record(
                    session_id=f"baseline-{day}",
                    timestamp=_days_ago_iso(day),
                    velocity=2.0,
                    bundling_indicator=150.0,
                ),
                path,
            )

        # Write today's record with 10x velocity jump
        today_record = _make_record(
            session_id="today-1",
            timestamp=_now_iso(),
            velocity=20.0,
            bundling_indicator=150.0,
        )
        record_metrics(today_record, path)

        # Load and compute
        all_records = load_metrics(path, days=8)
        assert len(all_records) == 8

        today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        today_records = [
            r for r in all_records if r.timestamp.startswith(today_str)
        ]
        baseline_records = [
            r for r in all_records if not r.timestamp.startswith(today_str)
        ]

        assert len(today_records) == 1
        assert len(baseline_records) == 7

        baseline = compute_baseline(baseline_records)
        anomalies = detect_anomalies(today_records[0], baseline)

        # Velocity should be flagged (10x jump on zero-stddev baseline)
        velocity_anomalies = [a for a in anomalies if a.metric == "velocity"]
        assert len(velocity_anomalies) == 1
        assert velocity_anomalies[0].current == 20.0
        assert math.isinf(velocity_anomalies[0].sigma)

        digest = format_digest(anomalies)
        assert "anomal" in digest.lower()
        assert "Velocity" in digest

    def test_all_normal_no_anomalies(self, tmp_path: Path):
        """When today matches the baseline, no anomalies."""
        path = tmp_path / "bridge-metrics.jsonl"

        for day in range(1, 8):
            record_metrics(
                _make_record(
                    session_id=f"b-{day}",
                    timestamp=_days_ago_iso(day),
                    velocity=2.0 + day * 0.1,
                ),
                path,
            )

        record_metrics(
            _make_record(
                session_id="today",
                timestamp=_now_iso(),
                velocity=2.4,
            ),
            path,
        )

        all_records = load_metrics(path, days=8)
        today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        today_records = [
            r for r in all_records if r.timestamp.startswith(today_str)
        ]
        baseline_records = [
            r for r in all_records if not r.timestamp.startswith(today_str)
        ]

        baseline = compute_baseline(baseline_records)
        anomalies = detect_anomalies(today_records[0], baseline)

        velocity_anomalies = [a for a in anomalies if a.metric == "velocity"]
        assert velocity_anomalies == []


# ---------------------------------------------------------------------------
# CLI entrypoint smoke test
# ---------------------------------------------------------------------------


class TestMainCLI:
    def test_no_data_prints_message(self, tmp_path: Path, capsys):
        path = tmp_path / "nonexistent.jsonl"
        main(["--metrics-path", str(path)])
        captured = capsys.readouterr()
        assert "No metrics data found" in captured.out

    def test_no_today_data_prints_message(self, tmp_path: Path, capsys):
        path = tmp_path / "metrics.jsonl"
        # Only write old data
        record_metrics(
            _make_record(session_id="old", timestamp=_days_ago_iso(3)),
            path,
        )
        main(["--metrics-path", str(path)])
        captured = capsys.readouterr()
        assert "No metrics recorded today" in captured.out

    def test_with_data_prints_digest(self, tmp_path: Path, capsys):
        path = tmp_path / "metrics.jsonl"
        for day in range(1, 4):
            record_metrics(
                _make_record(
                    session_id=f"b-{day}",
                    timestamp=_days_ago_iso(day),
                    velocity=2.0,
                ),
                path,
            )
        record_metrics(
            _make_record(
                session_id="today",
                timestamp=_now_iso(),
                velocity=2.0,
            ),
            path,
        )
        main(["--metrics-path", str(path)])
        captured = capsys.readouterr()
        # Should print something — either all-clear or anomalies
        assert len(captured.out.strip()) > 0
