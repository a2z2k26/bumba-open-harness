"""Tests for ``bridge.mad_confidence`` (Sprint 02.04 / spec ref-audit-02-05, issue #979)."""

from __future__ import annotations

import json
import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from bridge import mad_confidence
from bridge.mad_confidence import (
    MADResult,
    MIN_SAMPLES_FOR_SIGNIFICANCE,
    compute_mad,
    confidence_band_seconds,
    is_significant,
    load_recent_fitness,
    mad_result,
)


# ----------------------------------------------------------------------
# compute_mad — defensive contract
# ----------------------------------------------------------------------


class TestComputeMAD:
    def test_empty_returns_zero(self):
        assert compute_mad([]) == 0.0

    def test_single_sample_returns_zero(self):
        # Single sample has no spread to measure.
        assert compute_mad([5.0]) == 0.0

    def test_zero_variance_returns_zero(self):
        # Every deviation from the median is exactly 0.
        assert compute_mad([1.0, 1.0, 1.0]) == 0.0

    def test_known_input_1_2_3_4_5(self):
        # median=3, deviations=[2,1,0,1,2], median(deviations)=1.0
        assert compute_mad([1.0, 2.0, 3.0, 4.0, 5.0]) == 1.0

    def test_robust_to_outlier(self):
        # MAD is robust: one big spike does NOT blow up the noise floor.
        # median([1,1,1,1,100]) = 1; deviations=[0,0,0,0,99]; median=0.
        # Compare to stdev which would explode.
        assert compute_mad([1.0, 1.0, 1.0, 1.0, 100.0]) == 0.0

    def test_accepts_iterable_not_just_list(self):
        # Generator should work — Iterable is the declared type.
        gen = (float(x) for x in [1, 2, 3, 4, 5])
        assert compute_mad(gen) == 1.0


# ----------------------------------------------------------------------
# mad_result — full structured output
# ----------------------------------------------------------------------


class TestMADResult:
    def test_default_k_is_2_0(self):
        # K = 2.0 is the operator-signed conservative-95% default.
        assert mad_confidence.K_DEFAULT == 2.0

    def test_known_input_k_2(self):
        # values = [1,2,3]; median=2; deviations=[1,0,1]; mad=1.0; k*mad=2.0
        result = mad_result([1.0, 2.0, 3.0], k=2.0)
        assert result.median == 2.0
        assert result.mad == 1.0
        assert result.sample_count == 3
        assert result.confidence_seconds == 2.0

    def test_known_input_k_1_96(self):
        # K=1.96 (true Gaussian 95%) — confidence_seconds = 1.96 * 1.0
        result = mad_result([1.0, 2.0, 3.0], k=1.96)
        assert result.confidence_seconds == pytest.approx(1.96)

    def test_empty_input_returns_zero_band(self):
        result = mad_result([])
        assert result.median == 0.0
        assert result.mad == 0.0
        assert result.sample_count == 0
        assert result.confidence_seconds == 0.0

    def test_frozen_dataclass(self):
        # Immutability rule: a MADResult instance must reject mutation.
        result = mad_result([1.0, 2.0, 3.0])
        with pytest.raises(Exception):  # FrozenInstanceError or AttributeError
            result.median = 99.0  # type: ignore[misc]


# ----------------------------------------------------------------------
# is_significant — warm-up + threshold logic
# ----------------------------------------------------------------------


class TestIsSignificant:
    def _result(self, *, sample_count: int, confidence: float) -> MADResult:
        return MADResult(
            median=3.0,
            mad=1.0,
            sample_count=sample_count,
            confidence_seconds=confidence,
        )

    def test_delta_exceeds_band_returns_true(self):
        r = self._result(sample_count=5, confidence=2.0)
        assert is_significant(2.5, r) is True

    def test_delta_below_band_returns_false(self):
        r = self._result(sample_count=5, confidence=2.0)
        assert is_significant(1.0, r) is False

    def test_negative_delta_uses_absolute_value(self):
        # Regression at -2.5s is just as significant as improvement at +2.5s.
        r = self._result(sample_count=5, confidence=2.0)
        assert is_significant(-2.5, r) is True

    def test_delta_at_exact_band_is_not_significant(self):
        # ``>`` not ``>=`` — a delta exactly at the band edge is noise.
        r = self._result(sample_count=5, confidence=2.0)
        assert is_significant(2.0, r) is False

    def test_warmup_below_min_samples_always_false(self):
        # Even a huge delta is non-significant during warm-up.
        r = self._result(sample_count=2, confidence=0.001)
        assert is_significant(999.0, r) is False
        assert MIN_SAMPLES_FOR_SIGNIFICANCE == 3

    def test_warmup_at_min_samples_can_fire(self):
        r = self._result(sample_count=3, confidence=2.0)
        assert is_significant(2.5, r) is True


# ----------------------------------------------------------------------
# load_recent_fitness — JSONL parsing + defensive contract
# ----------------------------------------------------------------------


class TestLoadRecentFitness:
    def test_missing_file_returns_empty_list(self):
        # Defensive: an absent file must NOT raise.
        assert load_recent_fitness(Path("/nonexistent/path/to/file.jsonl")) == []

    def test_empty_file_returns_empty_list(self, tmp_path: Path):
        f = tmp_path / "experiments.jsonl"
        f.write_text("")
        assert load_recent_fitness(f) == []

    def test_skips_malformed_lines(self, tmp_path: Path):
        f = tmp_path / "experiments.jsonl"
        f.write_text(
            json.dumps({"iter_id": 1, "fitness_delta": 0.5}) + "\n"
            "not valid json\n"
            "{broken json\n"
            + json.dumps({"iter_id": 2, "fitness_delta": 0.7}) + "\n"
        )
        assert load_recent_fitness(f) == [0.5, 0.7]

    def test_skips_records_without_fitness_delta(self, tmp_path: Path):
        f = tmp_path / "experiments.jsonl"
        f.write_text(
            json.dumps({"iter_id": 1}) + "\n"
            + json.dumps({"iter_id": 2, "fitness_delta": None}) + "\n"
            + json.dumps({"iter_id": 3, "fitness_delta": 0.3}) + "\n"
        )
        assert load_recent_fitness(f) == [0.3]

    def test_skips_non_numeric_fitness_delta(self, tmp_path: Path):
        f = tmp_path / "experiments.jsonl"
        f.write_text(
            json.dumps({"iter_id": 1, "fitness_delta": "garbage"}) + "\n"
            + json.dumps({"iter_id": 2, "fitness_delta": 0.4}) + "\n"
        )
        assert load_recent_fitness(f) == [0.4]

    def test_returns_last_window_entries(self, tmp_path: Path):
        # 25 valid records, window=10 → last 10 only.
        f = tmp_path / "experiments.jsonl"
        lines = [
            json.dumps({"iter_id": i, "fitness_delta": float(i)}) for i in range(25)
        ]
        f.write_text("\n".join(lines) + "\n")
        result = load_recent_fitness(f, window=10)
        assert result == [float(i) for i in range(15, 25)]

    def test_window_larger_than_file_returns_all(self, tmp_path: Path):
        f = tmp_path / "experiments.jsonl"
        lines = [
            json.dumps({"iter_id": i, "fitness_delta": float(i)}) for i in range(3)
        ]
        f.write_text("\n".join(lines) + "\n")
        assert load_recent_fitness(f, window=100) == [0.0, 1.0, 2.0]

    def test_zero_or_negative_window_returns_empty(self, tmp_path: Path):
        f = tmp_path / "experiments.jsonl"
        f.write_text(json.dumps({"fitness_delta": 1.0}) + "\n")
        assert load_recent_fitness(f, window=0) == []
        assert load_recent_fitness(f, window=-5) == []

    def test_extracts_fitness_delta_from_real_schema_shape(self, tmp_path: Path):
        # Mirrors the real shape written by experiment_loop.append_experiments_jsonl —
        # full record with fitness_delta among many fields.
        f = tmp_path / "experiments.jsonl"
        record = {
            "iter_id": 1,
            "commit_hash": "abc",
            "branch": "experiment/x",
            "tests_passed": 100,
            "tests_failed": 0,
            "tests_total": 100,
            "status": "keep",
            "description": "test change",
            "diff_summary": "1 file",
            "cost_usd": 0.05,
            "duration_seconds": 12.3,
            "fitness_delta": 0.42,
            "created_at": "2026-05-01T00:00:00",
            "notes": {},
        }
        f.write_text(json.dumps(record) + "\n")
        assert load_recent_fitness(f) == [0.42]

    def test_string_path_accepted(self, tmp_path: Path):
        # API accepts ``Path | str`` per signature.
        f = tmp_path / "experiments.jsonl"
        f.write_text(json.dumps({"fitness_delta": 1.5}) + "\n")
        assert load_recent_fitness(str(f)) == [1.5]


# ----------------------------------------------------------------------
# confidence_band_seconds — convenience wrapper
# ----------------------------------------------------------------------


class TestConfidenceBandSeconds:
    def test_returns_none_during_warmup(self, tmp_path: Path):
        # Two samples = below MIN_SAMPLES_FOR_SIGNIFICANCE.
        f = tmp_path / "experiments.jsonl"
        f.write_text(
            json.dumps({"fitness_delta": 1.0}) + "\n"
            + json.dumps({"fitness_delta": 2.0}) + "\n"
        )
        assert confidence_band_seconds(jsonl_path=f) is None

    def test_returns_band_when_enough_samples(self, tmp_path: Path):
        # 5 samples, k=2.0 → band = 2.0 * MAD.
        f = tmp_path / "experiments.jsonl"
        for v in [1.0, 2.0, 3.0, 4.0, 5.0]:
            f.write_text(
                (f.read_text() if f.exists() else "")
                + json.dumps({"fitness_delta": v})
                + "\n"
            )
        band = confidence_band_seconds(jsonl_path=f, k=2.0)
        # MAD of [1,2,3,4,5] = 1.0; band = 2.0
        assert band == pytest.approx(2.0)

    def test_missing_file_returns_none(self):
        # Missing file → no values → no band.
        assert confidence_band_seconds(jsonl_path=Path("/nonexistent.jsonl")) is None

    def test_metric_name_is_informational(self, tmp_path: Path):
        # ``metric_name`` is accepted for forward-compat but ignored today.
        f = tmp_path / "experiments.jsonl"
        for v in [1.0, 2.0, 3.0]:
            f.write_text(
                (f.read_text() if f.exists() else "")
                + json.dumps({"fitness_delta": v})
                + "\n"
            )
        a = confidence_band_seconds(metric_name="foo", jsonl_path=f)
        b = confidence_band_seconds(metric_name="bar", jsonl_path=f)
        assert a == b


# ----------------------------------------------------------------------
# Integration — experiment_loop persists confidence_seconds + significant
# ----------------------------------------------------------------------


class TestExperimentLoopIntegration:
    """End-to-end: experiment_loop.log_result writes the new fields."""

    def setup_method(self):
        self.tmp_dir = Path(tempfile.mkdtemp(prefix="mad-test-"))
        self.db_path = self.tmp_dir / "experiments.db"
        self.jsonl_path = self.tmp_dir / "experiments.jsonl"
        self.md_path = self.tmp_dir / "experiments.md"

        # Minimum schema for log_result's INSERT.
        db = sqlite3.connect(str(self.db_path))
        db.execute("""CREATE TABLE IF NOT EXISTS experiment_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            commit_hash TEXT,
            branch TEXT,
            tests_passed INTEGER,
            tests_failed INTEGER,
            tests_total INTEGER,
            status TEXT,
            description TEXT,
            diff_summary TEXT,
            cost_usd REAL DEFAULT 0.0,
            duration_seconds REAL,
            fitness_delta REAL DEFAULT NULL,
            created_at TEXT DEFAULT (datetime('now'))
        )""")
        db.commit()
        db.close()

    def teardown_method(self):
        import shutil
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def _import_loop(self):
        # Lazy import: experiment_loop lives in scripts/, not bridge/.
        import sys
        agent_dir = Path(__file__).resolve().parent.parent
        scripts_dir = agent_dir / "scripts"
        if str(scripts_dir) not in sys.path:
            sys.path.insert(0, str(scripts_dir))
        import experiment_loop  # type: ignore[import-not-found]
        return experiment_loop

    def test_log_result_persists_confidence_and_significant(self):
        """After 5 prior iterations, log_result writes confidence_seconds + significant."""
        experiment_loop = self._import_loop()

        # Pre-populate experiments.jsonl with 5 prior deltas.
        prior = [
            {"iter_id": i, "fitness_delta": float(i), "status": "keep"}
            for i in range(1, 6)
        ]
        with self.jsonl_path.open("w") as fp:
            for r in prior:
                fp.write(json.dumps(r) + "\n")

        with patch.object(experiment_loop, "DB_PATH", self.db_path), \
             patch.object(experiment_loop, "EXPERIMENTS_JSONL_PATH", self.jsonl_path), \
             patch.object(experiment_loop, "EXPERIMENTS_MD_PATH", self.md_path):
            experiment_loop.log_result({
                "commit_hash": "deadbee",
                "branch": "experiment/mad",
                "tests_passed": 100,
                "tests_failed": 0,
                "tests_total": 100,
                "status": "keep",
                "description": "MAD-integration test",
                "diff_summary": "1 file",
                "cost_usd": 0.01,
                "duration_seconds": 1.0,
                "fitness_delta": 5.0,  # Big enough to be significant past noise floor.
            })

        # The new line should be the LAST line in the JSONL file.
        lines = self.jsonl_path.read_text().splitlines()
        new_line = json.loads(lines[-1])
        assert new_line["commit_hash"] == "deadbee"
        # MAD([1,2,3,4,5]) = 1.0; band = 2.0 * 1.0 = 2.0
        assert new_line["confidence_seconds"] == pytest.approx(2.0)
        # |5.0| > 2.0 → significant
        assert new_line["significant"] is True

    def test_log_result_warmup_returns_null_confidence(self):
        """During warm-up (<3 prior samples) confidence_seconds is null and significant=False."""
        experiment_loop = self._import_loop()

        # Only 2 prior deltas — below MIN_SAMPLES_FOR_SIGNIFICANCE.
        prior = [
            {"iter_id": 1, "fitness_delta": 1.0, "status": "keep"},
            {"iter_id": 2, "fitness_delta": 2.0, "status": "keep"},
        ]
        with self.jsonl_path.open("w") as fp:
            for r in prior:
                fp.write(json.dumps(r) + "\n")

        with patch.object(experiment_loop, "DB_PATH", self.db_path), \
             patch.object(experiment_loop, "EXPERIMENTS_JSONL_PATH", self.jsonl_path), \
             patch.object(experiment_loop, "EXPERIMENTS_MD_PATH", self.md_path):
            experiment_loop.log_result({
                "commit_hash": "warmup1",
                "branch": "experiment/warmup",
                "tests_passed": 100,
                "tests_failed": 0,
                "tests_total": 100,
                "status": "keep",
                "description": "warmup",
                "fitness_delta": 99.0,  # Even big delta is not significant during warmup.
            })

        new_line = json.loads(self.jsonl_path.read_text().splitlines()[-1])
        assert new_line["confidence_seconds"] is None
        assert new_line["significant"] is False

    def test_notifier_consumes_mad_confidence(self):
        """_build_notification picks up the band via confidence_band_seconds."""
        experiment_loop = self._import_loop()

        # 5 prior deltas → enough samples for a real band.
        prior = [
            {"iter_id": i, "fitness_delta": float(i), "status": "keep"}
            for i in range(1, 6)
        ]
        with self.jsonl_path.open("w") as fp:
            for r in prior:
                fp.write(json.dumps(r) + "\n")

        with patch.object(experiment_loop, "EXPERIMENTS_JSONL_PATH", self.jsonl_path), \
             patch.object(experiment_loop, "EXPERIMENTS_MD_PATH", self.md_path), \
             patch.object(experiment_loop, "DATA_DIR", self.tmp_dir):
            notification = experiment_loop._build_notification(
                {
                    "status": "keep",
                    "fitness_snapshot": {
                        "before_value": 12.0,
                        "after_value": 11.0,
                    },
                },
                iter_id="iter-test",
            )

        # MAD-derived band must propagate into the notification.
        assert notification.mad_confidence_seconds is not None
        assert notification.mad_confidence_seconds == pytest.approx(2.0)


# ----------------------------------------------------------------------
# Config integration — BridgeConfig fields
# ----------------------------------------------------------------------


class TestBridgeConfigFields:
    def test_default_window_and_k(self):
        from bridge.config import BridgeConfig

        cfg = BridgeConfig()
        assert cfg.experiment_mad_window == 20
        assert cfg.experiment_mad_k == 2.0

    def test_toml_map_keys_present(self):
        from bridge.config import _TOML_MAP

        assert _TOML_MAP["experiment_loop.mad_window"] == "experiment_mad_window"
        assert _TOML_MAP["experiment_loop.mad_k"] == "experiment_mad_k"

    def test_field_types_match_constants(self):
        # The BridgeConfig defaults must mirror the experiment_loop constants
        # so a runtime override of one stays consistent with the other.
        from bridge.config import BridgeConfig

        cfg = BridgeConfig()
        assert cfg.experiment_mad_window == mad_confidence.WINDOW_DEFAULT
        assert cfg.experiment_mad_k == mad_confidence.K_DEFAULT
