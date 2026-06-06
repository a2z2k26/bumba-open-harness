"""Tests for ``bridge.fitness`` (Sprint 02.02 — canonical fitness metric).

Covers:
- ``FitnessSnapshot`` immutability (frozen dataclass).
- ``fitness_delta`` arithmetic + sentinel propagation.
- ``current_fitness`` happy path with mocked subprocess output.
- ``current_fitness`` sentinel paths: subprocess crash, parse failure.
- ``experiment_loop._ensure_db`` migration round-trip on existing DBs.
- ``experiment_loop._append_fitness_history`` JSONL round-trip.
"""

from __future__ import annotations

import dataclasses
import json
import sqlite3
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# bridge.fitness lives under agent/bridge — already on sys.path in this test
# tree because tests/conftest pushes agent/ in.
from bridge import fitness

# experiment_loop is in agent/scripts (not on sys.path by default).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import experiment_loop  # noqa: E402


# ---------------------------------------------------------------------------
# FitnessSnapshot — immutability
# ---------------------------------------------------------------------------


class TestFitnessSnapshotImmutability:
    """The dataclass is frozen so callers cannot mutate measurements in place."""

    def _snapshot(self) -> fitness.FitnessSnapshot:
        return fitness.FitnessSnapshot(
            metric_name=fitness.METRIC_NAME,
            value=1.23,
            sample_count=42,
            captured_at=datetime(2026, 5, 1, tzinfo=timezone.utc),
        )

    def test_dataclass_is_frozen(self) -> None:
        params = fitness.FitnessSnapshot.__dataclass_params__  # type: ignore[attr-defined]
        assert params.frozen is True

    def test_setattr_raises(self) -> None:
        snap = self._snapshot()
        with pytest.raises(dataclasses.FrozenInstanceError):
            snap.value = 9.99  # type: ignore[misc]

    def test_replace_returns_new_instance(self) -> None:
        snap = self._snapshot()
        replaced = dataclasses.replace(snap, value=5.0)
        assert snap.value == 1.23  # original untouched
        assert replaced.value == 5.0
        assert replaced is not snap


# ---------------------------------------------------------------------------
# fitness_delta — arithmetic + sentinel propagation
# ---------------------------------------------------------------------------


class TestFitnessDelta:
    """Positive delta means improvement (faster after)."""

    def _snap(self, value: float, sample_count: int = 10) -> fitness.FitnessSnapshot:
        return fitness.FitnessSnapshot(
            metric_name=fitness.METRIC_NAME,
            value=value,
            sample_count=sample_count,
            captured_at=datetime(2026, 5, 1, tzinfo=timezone.utc),
        )

    def test_improvement_is_positive(self) -> None:
        before = self._snap(2.0)
        after = self._snap(1.5)
        assert fitness.fitness_delta(before, after) == pytest.approx(0.5)

    def test_regression_is_negative(self) -> None:
        before = self._snap(1.0)
        after = self._snap(2.5)
        assert fitness.fitness_delta(before, after) == pytest.approx(-1.5)

    def test_no_change_is_zero(self) -> None:
        snap = self._snap(1.0)
        assert fitness.fitness_delta(snap, snap) == 0.0

    def test_sentinel_after_yields_negative_infinity(self) -> None:
        before = self._snap(1.0)
        after = fitness._sentinel()
        assert fitness.fitness_delta(before, after) == float("-inf")


# ---------------------------------------------------------------------------
# current_fitness — happy path + sentinels
# ---------------------------------------------------------------------------


# Canned ``pytest --durations=0 -vv`` stdout fragment. Includes setup/teardown
# rows that should NOT count, plus three ``call`` rows we DO count.
CANNED_DURATIONS_OUTPUT = """\
====== test session starts ======
collected 3 items

tests/test_a.py::test_one PASSED
tests/test_a.py::test_two PASSED
tests/test_a.py::test_three PASSED

============================== slowest durations ===============================
0.40s call     tests/test_a.py::test_one
0.20s call     tests/test_a.py::test_two
0.60s call     tests/test_a.py::test_three
0.05s setup    tests/test_a.py::test_one
0.01s teardown tests/test_a.py::test_one
3 passed in 1.23s
"""


class TestCurrentFitness:
    """Happy path + every documented sentinel branch."""

    def test_parses_mean_from_canned_output(self) -> None:
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = CANNED_DURATIONS_OUTPUT
        mock_result.stderr = ""

        with patch.object(fitness.subprocess, "run", return_value=mock_result):
            snap = fitness.current_fitness()

        # Mean of (0.40, 0.20, 0.60) = 0.40. Setup/teardown rows are ignored.
        assert snap.value == pytest.approx(0.40)
        assert snap.sample_count == 3
        assert snap.metric_name == fitness.METRIC_NAME
        assert snap.captured_at.tzinfo is not None

    def test_sentinel_on_nonzero_exit(self) -> None:
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stdout = CANNED_DURATIONS_OUTPUT  # would parse, but exit != 0
        mock_result.stderr = "test failed"

        with patch.object(fitness.subprocess, "run", return_value=mock_result):
            snap = fitness.current_fitness()

        assert snap.value == float("inf")
        assert snap.sample_count == 0

    def test_sentinel_on_empty_stdout(self) -> None:
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = ""
        mock_result.stderr = ""

        with patch.object(fitness.subprocess, "run", return_value=mock_result):
            snap = fitness.current_fitness()

        assert snap.value == float("inf")
        assert snap.sample_count == 0

    def test_sentinel_on_subprocess_crash(self) -> None:
        def _crash(*args, **kwargs):
            raise OSError("pytest binary missing")

        with patch.object(fitness.subprocess, "run", side_effect=_crash):
            snap = fitness.current_fitness()

        assert snap.value == float("inf")
        assert snap.sample_count == 0

    def test_sentinel_on_timeout(self) -> None:
        import subprocess as _subprocess

        def _raise(*args, **kwargs):
            raise _subprocess.TimeoutExpired(cmd="pytest", timeout=1)

        with patch.object(fitness.subprocess, "run", side_effect=_raise):
            snap = fitness.current_fitness()

        assert snap.value == float("inf")
        assert snap.sample_count == 0


# ---------------------------------------------------------------------------
# DB migration — fitness_delta column round-trip on existing experiments.db
# ---------------------------------------------------------------------------


class TestMigrationFitnessDelta:
    """``_ensure_db`` adds ``fitness_delta REAL`` to existing DBs idempotently."""

    def test_adds_column_to_existing_db(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "experiments.db"
            data_dir = Path(tmp)

            # Pre-migration schema (matches the v1 schema in TestBudgetGate).
            db = sqlite3.connect(str(db_path))
            db.execute("""CREATE TABLE experiment_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                commit_hash TEXT,
                branch TEXT,
                tests_passed INTEGER,
                tests_failed INTEGER,
                tests_total INTEGER,
                status TEXT CHECK(status IN ('keep', 'discard', 'crash')),
                description TEXT,
                diff_summary TEXT,
                cost_usd REAL DEFAULT 0.0,
                duration_seconds REAL,
                created_at TEXT DEFAULT (datetime('now'))
            )""")
            # Seed a row to ensure the migration doesn't drop data.
            db.execute(
                "INSERT INTO experiment_log (status, description) "
                "VALUES ('keep', 'pre-migration row')"
            )
            db.commit()
            db.close()

            with patch.object(experiment_loop, "DB_PATH", db_path), \
                 patch.object(experiment_loop, "DATA_DIR", data_dir):
                experiment_loop._ensure_db()
                # Idempotent: a second run must not raise.
                experiment_loop._ensure_db()

            db = sqlite3.connect(str(db_path))
            cols = {row[1]: row[2] for row in db.execute("PRAGMA table_info(experiment_log)")}
            row = db.execute(
                "SELECT description, fitness_delta FROM experiment_log "
                "WHERE description = 'pre-migration row'"
            ).fetchone()
            db.close()

            assert "fitness_delta" in cols
            assert cols["fitness_delta"].upper() == "REAL"
            # Pre-existing row survives migration; new column defaults to NULL.
            assert row == ("pre-migration row", None)

    def test_round_trip_on_fresh_db(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "experiments.db"
            data_dir = Path(tmp)

            with patch.object(experiment_loop, "DB_PATH", db_path), \
                 patch.object(experiment_loop, "DATA_DIR", data_dir):
                experiment_loop._ensure_db()

            db = sqlite3.connect(str(db_path))
            cols = [row[1] for row in db.execute("PRAGMA table_info(experiment_log)")]
            db.close()
            assert "fitness_delta" in cols


# ---------------------------------------------------------------------------
# fitness_history.jsonl — atomic JSONL append round-trip
# ---------------------------------------------------------------------------


class TestFitnessHistoryAppend:
    """``_append_fitness_history`` produces a parseable JSONL file."""

    def test_append_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            history_path = Path(tmp) / "fitness_history.jsonl"

            with patch.object(experiment_loop, "FITNESS_HISTORY_PATH", history_path):
                experiment_loop._append_fitness_history({
                    "metric_name": fitness.METRIC_NAME,
                    "value": 1.5,
                    "sample_count": 100,
                    "captured_at": "2026-05-01T00:00:00+00:00",
                })
                experiment_loop._append_fitness_history({
                    "metric_name": fitness.METRIC_NAME,
                    "value": 1.4,
                    "sample_count": 100,
                    "captured_at": "2026-05-01T00:10:00+00:00",
                })

            lines = history_path.read_text().splitlines()
            assert len(lines) == 2
            first = json.loads(lines[0])
            second = json.loads(lines[1])
            assert first["value"] == 1.5
            assert second["value"] == 1.4
            assert first["metric_name"] == fitness.METRIC_NAME

    def test_log_result_writes_history_line(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "experiments.db"
            history_path = Path(tmp) / "fitness_history.jsonl"
            data_dir = Path(tmp)

            with patch.object(experiment_loop, "DB_PATH", db_path), \
                 patch.object(experiment_loop, "DATA_DIR", data_dir), \
                 patch.object(experiment_loop, "FITNESS_HISTORY_PATH", history_path):
                experiment_loop._ensure_db()
                experiment_loop.log_result({
                    "commit_hash": "deadbee",
                    "branch": "experiment/fitness-1",
                    "tests_passed": 1,
                    "tests_failed": 0,
                    "tests_total": 1,
                    "status": "keep",
                    "description": "fitness round-trip",
                    "diff_summary": "1 file changed",
                    "cost_usd": 0.01,
                    "duration_seconds": 1.0,
                    "fitness_delta": 0.05,
                    "fitness_snapshot": {
                        "metric_name": fitness.METRIC_NAME,
                        "value": 1.45,
                        "sample_count": 100,
                        "captured_at": "2026-05-01T00:10:00+00:00",
                    },
                })

            assert history_path.exists()
            line = history_path.read_text().strip()
            record = json.loads(line)
            assert record["value"] == 1.45
            assert record["commit_hash"] == "deadbee"
            assert record["fitness_delta"] == 0.05

            # And the DB row carries the fitness_delta column.
            db = sqlite3.connect(str(db_path))
            row = db.execute(
                "SELECT fitness_delta FROM experiment_log WHERE commit_hash = 'deadbee'"
            ).fetchone()
            db.close()
            assert row[0] == 0.05
