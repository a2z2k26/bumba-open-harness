"""Tests for scripts/cost_rollup.py (sprint E-O.4).

Verifies that the nightly cost rollup correctly aggregates sessions/*/cost.json
by department x agent and writes z4-cost-daily-YYYYMMDD.json.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

# Add scripts/ to sys.path so we can import cost_rollup as a module.
_SCRIPTS_DIR = Path(__file__).parent.parent / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from cost_rollup import (
    _iter_session_cost_files,
    _session_date,
    _parse_cost_file,
    rollup,
    main,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_cost_json(
    session_id: str,
    departments: list[dict],
) -> dict:
    """Build a minimal cost.json dict matching SessionCostSummary.to_dict()."""
    return {
        "session_id": session_id,
        "departments": departments,
        "total_usd": sum(d.get("total_usd", 0.0) for d in departments),
        "call_count": sum(d.get("call_count", 0) for d in departments),
        "blocked_calls": 0,
        "computed_at": datetime.now(timezone.utc).isoformat(),
    }


def _make_dept(
    dept_name: str,
    agents: list[dict],
    *,
    blocked: int = 0,
) -> dict:
    total_usd = sum(a.get("total_usd", 0.0) for a in agents)
    total_calls = sum(a.get("call_count", 0) for a in agents)
    return {
        "department": dept_name,
        "session_id": "s1",
        "agents": agents,
        "total_usd": total_usd,
        "total_input_tokens": sum(a.get("total_input_tokens", 0) for a in agents),
        "total_output_tokens": sum(a.get("total_output_tokens", 0) for a in agents),
        "call_count": total_calls,
        "blocked_calls": blocked,
    }


def _make_agent(
    name: str,
    usd: float = 0.10,
    calls: int = 5,
    input_tokens: int = 1000,
    output_tokens: int = 200,
) -> dict:
    return {
        "agent_name": name,
        "department": "qa",
        "session_id": "s1",
        "total_usd": usd,
        "call_count": calls,
        "total_input_tokens": input_tokens,
        "total_output_tokens": output_tokens,
        "blocked_calls": 0,
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestIterSessionCostFiles:
    def test_returns_empty_when_no_sessions_dir(self, tmp_path):
        """Test 1: Returns empty list when sessions_dir does not exist."""
        result = _iter_session_cost_files(tmp_path / "nonexistent")
        assert result == []

    def test_finds_cost_json_files(self, tmp_path):
        """Test 2: Finds all cost.json files in session subdirectories."""
        (tmp_path / "session-1").mkdir()
        (tmp_path / "session-1" / "cost.json").write_text("{}", encoding="utf-8")
        (tmp_path / "session-2").mkdir()
        (tmp_path / "session-2" / "cost.json").write_text("{}", encoding="utf-8")

        result = _iter_session_cost_files(tmp_path)
        assert len(result) == 2

    def test_ignores_non_cost_json_files(self, tmp_path):
        """Test 3: Only picks up cost.json, not other JSON files."""
        (tmp_path / "session-1").mkdir()
        (tmp_path / "session-1" / "meta.json").write_text("{}", encoding="utf-8")
        (tmp_path / "session-1" / "cost.json").write_text("{}", encoding="utf-8")

        result = _iter_session_cost_files(tmp_path)
        assert len(result) == 1
        assert result[0].name == "cost.json"


class TestSessionDate:
    def test_reads_date_from_meta_json(self, tmp_path):
        """Test 4: Extracts date from meta.json created_at field."""
        session_dir = tmp_path / "session-abc"
        session_dir.mkdir()
        cost_file = session_dir / "cost.json"
        cost_file.write_text("{}", encoding="utf-8")
        meta = {"created_at": "2026-04-17T08:30:00+00:00"}
        (session_dir / "meta.json").write_text(json.dumps(meta), encoding="utf-8")

        assert _session_date(cost_file) == "2026-04-17"

    def test_falls_back_to_mtime_when_no_meta_json(self, tmp_path):
        """Test 5: Falls back to directory mtime when meta.json is absent."""
        session_dir = tmp_path / "session-xyz"
        session_dir.mkdir()
        cost_file = session_dir / "cost.json"
        cost_file.write_text("{}", encoding="utf-8")

        result = _session_date(cost_file)
        assert result is not None
        assert len(result) == 10  # YYYY-MM-DD

    def test_returns_none_for_corrupt_meta_json(self, tmp_path):
        """Test 6: Returns a date (mtime fallback) when meta.json is corrupt."""
        session_dir = tmp_path / "session-bad"
        session_dir.mkdir()
        cost_file = session_dir / "cost.json"
        cost_file.write_text("{}", encoding="utf-8")
        (session_dir / "meta.json").write_text("not-json!!!", encoding="utf-8")

        # Should fall back to mtime, not raise
        result = _session_date(cost_file)
        assert result is not None


class TestParseCostFile:
    def test_returns_dict_for_valid_json(self, tmp_path):
        """Test 7: Parses valid JSON cost file."""
        f = tmp_path / "cost.json"
        f.write_text('{"session_id": "s1"}', encoding="utf-8")
        result = _parse_cost_file(f)
        assert result == {"session_id": "s1"}

    def test_returns_empty_dict_on_corrupt_json(self, tmp_path):
        """Test 8: Returns empty dict for invalid JSON."""
        f = tmp_path / "cost.json"
        f.write_text("not-json", encoding="utf-8")
        result = _parse_cost_file(f)
        assert result == {}

    def test_returns_empty_dict_for_missing_file(self, tmp_path):
        """Test 9: Returns empty dict when file does not exist."""
        result = _parse_cost_file(tmp_path / "no-such-file.json")
        assert result == {}


class TestRollup:
    def _setup_session(
        self,
        sessions_dir: Path,
        session_id: str,
        date_str: str,
        cost_data: dict,
    ) -> None:
        """Create a session directory with cost.json and meta.json."""
        sdir = sessions_dir / session_id
        sdir.mkdir(parents=True)
        (sdir / "cost.json").write_text(json.dumps(cost_data), encoding="utf-8")
        (sdir / "meta.json").write_text(
            json.dumps({"created_at": f"{date_str}T08:00:00+00:00"}),
            encoding="utf-8",
        )

    def test_empty_sessions_dir_produces_zero_totals(self, tmp_path):
        """Test 10: Empty sessions dir produces rollup with zero totals."""
        result = rollup(
            "2026-04-17",
            sessions_dir=tmp_path / "sessions",
            data_dir=tmp_path / "data",
            dry_run=True,
        )
        assert result["grand_total_cost_usd"] == 0.0
        assert result["sessions_processed"] == 0
        assert result["by_department"] == {}

    def test_aggregates_single_session(self, tmp_path):
        """Test 11: Aggregates cost from a single session correctly."""
        sessions_dir = tmp_path / "sessions"
        cost_data = _make_cost_json(
            "s1",
            [
                _make_dept(
                    "qa",
                    [_make_agent("qa-chief", usd=0.10, calls=5)],
                )
            ],
        )
        self._setup_session(sessions_dir, "s1", "2026-04-17", cost_data)

        result = rollup(
            "2026-04-17",
            sessions_dir=sessions_dir,
            data_dir=tmp_path / "data",
            dry_run=True,
        )
        assert result["sessions_processed"] == 1
        assert "qa" in result["by_department"]
        assert result["by_department"]["qa"]["total_cost_usd"] == pytest.approx(0.10)

    def test_aggregates_multiple_sessions(self, tmp_path):
        """Test 12: Correctly sums cost across multiple sessions."""
        sessions_dir = tmp_path / "sessions"
        for i, usd in enumerate([0.05, 0.08]):
            cost_data = _make_cost_json(
                f"s{i}",
                [_make_dept("qa", [_make_agent("qa-chief", usd=usd)])],
            )
            self._setup_session(sessions_dir, f"s{i}", "2026-04-17", cost_data)

        result = rollup(
            "2026-04-17",
            sessions_dir=sessions_dir,
            data_dir=tmp_path / "data",
            dry_run=True,
        )
        assert result["sessions_processed"] == 2
        assert result["by_department"]["qa"]["total_cost_usd"] == pytest.approx(0.13)

    def test_filters_by_date(self, tmp_path):
        """Test 13: Only sessions matching target_date are included."""
        sessions_dir = tmp_path / "sessions"
        cost_data = _make_cost_json(
            "s1",
            [_make_dept("qa", [_make_agent("qa-chief", usd=0.50)])],
        )
        # Session on the wrong date
        self._setup_session(sessions_dir, "s1", "2026-04-16", cost_data)
        # Session on the right date
        self._setup_session(sessions_dir, "s2", "2026-04-17", cost_data)

        result = rollup(
            "2026-04-17",
            sessions_dir=sessions_dir,
            data_dir=tmp_path / "data",
            dry_run=True,
        )
        assert result["sessions_processed"] == 1

    def test_writes_output_file(self, tmp_path):
        """Test 14: Writes z4-cost-daily-YYYYMMDD.json to data_dir."""
        sessions_dir = tmp_path / "sessions"
        data_dir = tmp_path / "data"
        rollup(
            "2026-04-17",
            sessions_dir=sessions_dir,
            data_dir=data_dir,
        )
        out = data_dir / "z4-cost-daily-20260417.json"
        assert out.exists()
        content = json.loads(out.read_text(encoding="utf-8"))
        assert content["date"] == "2026-04-17"

    def test_dry_run_does_not_write_file(self, tmp_path):
        """Test 15: dry_run=True does not write output file."""
        sessions_dir = tmp_path / "sessions"
        data_dir = tmp_path / "data"
        rollup(
            "2026-04-17",
            sessions_dir=sessions_dir,
            data_dir=data_dir,
            dry_run=True,
        )
        assert not (data_dir / "z4-cost-daily-20260417.json").exists()

    def test_multiple_departments(self, tmp_path):
        """Test 16: Handles multiple departments in one session."""
        sessions_dir = tmp_path / "sessions"
        cost_data = _make_cost_json(
            "s1",
            [
                _make_dept("board", [_make_agent("board-ceo", usd=0.42)]),
                _make_dept("qa", [_make_agent("qa-chief", usd=0.08)]),
            ],
        )
        self._setup_session(sessions_dir, "s1", "2026-04-17", cost_data)

        result = rollup(
            "2026-04-17",
            sessions_dir=sessions_dir,
            data_dir=tmp_path / "data",
            dry_run=True,
        )
        assert "board" in result["by_department"]
        assert "qa" in result["by_department"]
        assert result["grand_total_cost_usd"] == pytest.approx(0.50)

    def test_output_includes_computed_at(self, tmp_path):
        """Test 17: Output includes computed_at timestamp."""
        result = rollup(
            "2026-04-17",
            sessions_dir=tmp_path / "sessions",
            data_dir=tmp_path / "data",
            dry_run=True,
        )
        assert "computed_at" in result
        assert result["computed_at"].startswith("2026")

    def test_blocked_calls_tracked_per_dept(self, tmp_path):
        """Test 18: Blocked calls are tracked in per-department summary."""
        sessions_dir = tmp_path / "sessions"
        cost_data = _make_cost_json(
            "s1",
            [_make_dept("ops", [_make_agent("ops-chief")], blocked=3)],
        )
        self._setup_session(sessions_dir, "s1", "2026-04-17", cost_data)

        result = rollup(
            "2026-04-17",
            sessions_dir=sessions_dir,
            data_dir=tmp_path / "data",
            dry_run=True,
        )
        assert result["by_department"]["ops"]["blocked_calls"] == 3


class TestMain:
    def test_main_dry_run_exits_zero(self, tmp_path, capsys):
        """Test 19: main() with --dry-run exits with code 0."""
        sessions_dir = tmp_path / "sessions"
        data_dir = tmp_path / "data"
        rc = main([
            "--date", "2026-04-17",
            "--sessions-dir", str(sessions_dir),
            "--data-dir", str(data_dir),
            "--dry-run",
        ])
        assert rc == 0

    def test_main_writes_output(self, tmp_path):
        """Test 20: main() without dry-run writes output file."""
        sessions_dir = tmp_path / "sessions"
        data_dir = tmp_path / "data"
        main([
            "--date", "2026-04-17",
            "--sessions-dir", str(sessions_dir),
            "--data-dir", str(data_dir),
        ])
        assert (data_dir / "z4-cost-daily-20260417.json").exists()
