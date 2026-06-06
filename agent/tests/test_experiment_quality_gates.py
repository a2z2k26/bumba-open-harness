"""Tests for the ruff + mypy backpressure gates (Sprint 02.07b, issue #982).

Spec: docs/specs/2026-04-25-reference-audit/spec-02-07b-add-ruff-mypy-backpressure-gates-after-pytest.md

Covers:

* ``run_ruff_gate`` happy + sad + timeout paths
* ``run_mypy_gate`` happy + sad + timeout paths
* ``run_quality_gates`` short-circuit semantics (ruff fail → mypy not invoked)
* ``run_quality_gates`` empty-input vacuous pass
* ``all_passed`` / ``summarize`` helpers
* Integration: pytest pass + quality fail → ``validate_experiment``
  returns ``status=discard`` with notes populated.

Subprocess invocations are mocked — the unit tests do not actually run
ruff or mypy. The integration test mocks ``run_quality_gates`` directly
to keep the test fast and deterministic.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Tests sit in ``agent/tests/`` and the gate module sits in
# ``agent/scripts/`` (the experiment loop is a script, not part of the
# bridge package). Mirror the import shim that ``test_experiment_loop``
# already uses.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import experiment_quality_gates as gates  # noqa: E402


def _completed(returncode: int, stdout: str = "", stderr: str = "") -> MagicMock:
    """Build a MagicMock that quacks like ``subprocess.CompletedProcess``."""
    m = MagicMock()
    m.returncode = returncode
    m.stdout = stdout
    m.stderr = stderr
    return m


# ---------------------------------------------------------------------------
# run_ruff_gate
# ---------------------------------------------------------------------------


class TestRunRuffGate:
    def test_empty_changed_files_passes_vacuously(self):
        result = gates.run_ruff_gate([])
        assert result.outcome == "pass"
        assert result.name == "ruff"
        assert result.summary == ""

    def test_only_non_python_changed_files_passes_vacuously(self):
        # Markdown / TOML edits should never trigger ruff.
        result = gates.run_ruff_gate([Path("README.md"), Path("pyproject.toml")])
        assert result.outcome == "pass"

    def test_clean_file_passes(self):
        with patch.object(gates.subprocess, "run") as mock_run:
            mock_run.return_value = _completed(0, stdout="", stderr="")
            result = gates.run_ruff_gate([Path("/tmp/clean.py")])
        assert result.outcome == "pass"
        assert result.name == "ruff"
        assert result.summary == ""
        # Sanity-check that ruff was invoked with `check` and the file path.
        call_args = mock_run.call_args[0][0]
        assert "ruff" in call_args
        assert "check" in call_args
        assert "/tmp/clean.py" in call_args

    def test_dirty_file_fails_with_summary(self):
        ruff_output = (
            "/tmp/dirty.py:3:1: F401 [*] `os` imported but unused\n"
            "/tmp/dirty.py:5:1: E501 line too long (95 > 88)\n"
            "/tmp/dirty.py:8:9: F841 unused variable `x`\n"
        )
        with patch.object(gates.subprocess, "run") as mock_run:
            mock_run.return_value = _completed(1, stdout=ruff_output, stderr="")
            result = gates.run_ruff_gate([Path("/tmp/dirty.py")])
        assert result.outcome == "fail"
        assert result.name == "ruff"
        assert "ruff:" in result.summary
        assert "3 issue(s)" in result.summary
        assert result.stdout == ruff_output

    def test_timeout_returns_fail_with_reason(self):
        with patch.object(gates.subprocess, "run") as mock_run:
            mock_run.side_effect = subprocess.TimeoutExpired(cmd="ruff", timeout=1)
            result = gates.run_ruff_gate([Path("/tmp/slow.py")], timeout_s=1)
        assert result.outcome == "fail"
        assert "timed out" in result.summary
        assert result.stderr.startswith("timeout")


# ---------------------------------------------------------------------------
# run_mypy_gate
# ---------------------------------------------------------------------------


class TestRunMypyGate:
    def test_empty_changed_files_passes_vacuously(self):
        result = gates.run_mypy_gate([])
        assert result.outcome == "pass"
        assert result.name == "mypy"

    def test_clean_file_passes(self):
        with patch.object(gates.subprocess, "run") as mock_run:
            mock_run.return_value = _completed(0, stdout="", stderr="")
            result = gates.run_mypy_gate([Path("/tmp/clean.py")])
        assert result.outcome == "pass"
        call_args = mock_run.call_args[0][0]
        assert "mypy" in call_args

    def test_typed_errors_fails_with_count(self):
        mypy_output = (
            "/tmp/dirty.py:5: error: Incompatible types in assignment  [assignment]\n"
            "/tmp/dirty.py:9: error: Argument 1 has incompatible type  [arg-type]\n"
        )
        with patch.object(gates.subprocess, "run") as mock_run:
            mock_run.return_value = _completed(1, stdout=mypy_output, stderr="")
            result = gates.run_mypy_gate([Path("/tmp/dirty.py")])
        assert result.outcome == "fail"
        assert result.name == "mypy"
        assert "2 error(s)" in result.summary

    def test_timeout_returns_fail_with_reason(self):
        with patch.object(gates.subprocess, "run") as mock_run:
            mock_run.side_effect = subprocess.TimeoutExpired(cmd="mypy", timeout=1)
            result = gates.run_mypy_gate([Path("/tmp/slow.py")], timeout_s=1)
        assert result.outcome == "fail"
        assert "timed out" in result.summary


# ---------------------------------------------------------------------------
# run_quality_gates — orchestration / short-circuit
# ---------------------------------------------------------------------------


class TestRunQualityGates:
    def test_empty_changed_files_returns_two_vacuous_passes(self):
        # No subprocess calls should be made — ruff and mypy both
        # short-circuit on empty input. We still get two GateResults
        # so the caller can render the gate row in the digest.
        with patch.object(gates.subprocess, "run") as mock_run:
            results = gates.run_quality_gates([])
        assert len(results) == 2
        assert results[0].name == "ruff"
        assert results[1].name == "mypy"
        assert results[0].outcome == "pass"
        assert results[1].outcome == "pass"
        mock_run.assert_not_called()

    def test_clean_change_runs_both_gates(self):
        with patch.object(gates.subprocess, "run") as mock_run:
            mock_run.return_value = _completed(0, stdout="", stderr="")
            results = gates.run_quality_gates([Path("/tmp/clean.py")])
        assert len(results) == 2
        assert all(r.outcome == "pass" for r in results)
        # Both gates were invoked.
        assert mock_run.call_count == 2

    def test_ruff_fail_short_circuits_mypy_not_invoked(self):
        # ruff returns exit 1 → run_quality_gates must NOT call mypy.
        with patch.object(gates.subprocess, "run") as mock_run:
            mock_run.return_value = _completed(1, stdout="x.py:1:1: E501\n", stderr="")
            results = gates.run_quality_gates([Path("/tmp/dirty.py")])
        assert len(results) == 1
        assert results[0].name == "ruff"
        assert results[0].outcome == "fail"
        # Exactly one subprocess invocation — the ruff one.
        assert mock_run.call_count == 1

    def test_ruff_passes_mypy_fails(self):
        # First call (ruff) clean; second call (mypy) dirty.
        ruff_clean = _completed(0, stdout="", stderr="")
        mypy_dirty = _completed(
            1,
            stdout="/tmp/x.py:1: error: bad\n",
            stderr="",
        )
        with patch.object(gates.subprocess, "run") as mock_run:
            mock_run.side_effect = [ruff_clean, mypy_dirty]
            results = gates.run_quality_gates([Path("/tmp/x.py")])
        assert len(results) == 2
        assert results[0].outcome == "pass"
        assert results[1].outcome == "fail"

    def test_returns_tuple_immutable(self):
        with patch.object(gates.subprocess, "run") as mock_run:
            mock_run.return_value = _completed(0, stdout="", stderr="")
            results = gates.run_quality_gates([Path("/tmp/x.py")])
        # Tuple, not list — caller cannot mutate.
        assert isinstance(results, tuple)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class TestHelpers:
    def test_all_passed_true_on_all_passes(self):
        r = (
            gates.GateResult("ruff", "pass", "", "", "", 0.1),
            gates.GateResult("mypy", "pass", "", "", "", 0.2),
        )
        assert gates.all_passed(r) is True

    def test_all_passed_false_on_any_fail(self):
        r = (
            gates.GateResult("ruff", "pass", "", "", "", 0.1),
            gates.GateResult("mypy", "fail", "mypy: 1 error(s)", "", "", 0.2),
        )
        assert gates.all_passed(r) is False

    def test_all_passed_empty_tuple_vacuously_true(self):
        assert gates.all_passed(()) is True

    def test_summarize_joins_failures(self):
        r = (
            gates.GateResult("ruff", "fail", "ruff: 5 issue(s)", "", "", 0.1),
            gates.GateResult("mypy", "fail", "mypy: 2 error(s)", "", "", 0.2),
        )
        assert gates.summarize(r) == "ruff: 5 issue(s) / mypy: 2 error(s)"

    def test_summarize_empty_when_all_pass(self):
        r = (
            gates.GateResult("ruff", "pass", "", "", "", 0.1),
            gates.GateResult("mypy", "pass", "", "", "", 0.2),
        )
        assert gates.summarize(r) == ""


# ---------------------------------------------------------------------------
# Integration: validate_experiment wires the gate after pytest
# ---------------------------------------------------------------------------


class TestValidateExperimentIntegratesGates:
    """When pytest passes but quality gates fail, the iteration is discarded.

    Mocks the worktree subprocess calls (git diff, git diff --stat, pytest)
    and the quality-gate runner to keep the test deterministic.
    """

    def _mock_worktree(self, mock_run: MagicMock, *, pytest_exit: int) -> None:
        # Order of subprocess.run calls inside validate_experiment:
        #   1. git diff --name-only
        #   2. git diff --stat
        #   3. pytest tests/ -q --tb=short
        mock_run.side_effect = [
            _completed(0, stdout="agent/bridge/foo.py\n", stderr=""),
            _completed(0, stdout="1 file changed, 5 insertions", stderr=""),
            _completed(pytest_exit, stdout="1813 passed in 23s", stderr=""),
        ]

    def test_pytest_pass_quality_pass_keeps(self, tmp_path):
        import experiment_loop

        worktree = tmp_path / "wt"
        (worktree / "agent").mkdir(parents=True)

        clean_results = (
            gates.GateResult("ruff", "pass", "", "", "", 0.1),
            gates.GateResult("mypy", "pass", "", "", "", 0.2),
        )

        with patch.object(experiment_loop, "subprocess") as mock_sub, \
             patch.object(experiment_loop, "run_quality_gates", return_value=clean_results):
            mock_sub.TimeoutExpired = subprocess.TimeoutExpired
            self._mock_worktree(mock_sub.run, pytest_exit=0)
            result = experiment_loop.validate_experiment(str(worktree))

        assert result["status"] == "keep"
        # Notes populated with both gates' results, both passing.
        assert "lint_regressions" in result["notes"]
        assert result["notes"]["lint_regressions"]["ruff"]["outcome"] == "pass"
        assert result["notes"]["lint_regressions"]["mypy"]["outcome"] == "pass"

    def test_pytest_pass_quality_fail_discards_with_reason(self, tmp_path):
        import experiment_loop

        worktree = tmp_path / "wt"
        (worktree / "agent").mkdir(parents=True)

        dirty_results = (
            gates.GateResult(
                "ruff",
                "fail",
                "ruff: 5 issue(s)",
                "x.py:1:1: F401\n" * 5,
                "",
                0.1,
            ),
        )

        with patch.object(experiment_loop, "subprocess") as mock_sub, \
             patch.object(experiment_loop, "run_quality_gates", return_value=dirty_results):
            mock_sub.TimeoutExpired = subprocess.TimeoutExpired
            self._mock_worktree(mock_sub.run, pytest_exit=0)
            result = experiment_loop.validate_experiment(str(worktree))

        assert result["status"] == "discard"
        # Diff summary tagged with the lint regression reason.
        assert "lint-regression" in result["diff_summary"]
        assert "ruff: 5 issue(s)" in result["diff_summary"]
        # Notes carry the structured lint_regressions for the JSONL.
        assert "lint_regressions" in result["notes"]
        ruff_note = result["notes"]["lint_regressions"]["ruff"]
        assert ruff_note["outcome"] == "fail"
        assert "5 issue(s)" in ruff_note["summary"]

    def test_pytest_fail_skips_quality_gates(self, tmp_path):
        """When pytest fails, quality gates are NOT invoked — pytest decision dominates."""
        import experiment_loop

        worktree = tmp_path / "wt"
        (worktree / "agent").mkdir(parents=True)

        with patch.object(experiment_loop, "subprocess") as mock_sub, \
             patch.object(experiment_loop, "run_quality_gates") as mock_gates:
            mock_sub.TimeoutExpired = subprocess.TimeoutExpired
            self._mock_worktree(mock_sub.run, pytest_exit=1)
            result = experiment_loop.validate_experiment(str(worktree))

        assert result["status"] == "discard"
        # Quality gates were skipped — pytest already signed the death warrant.
        mock_gates.assert_not_called()


# ---------------------------------------------------------------------------
# GateResult dataclass invariants
# ---------------------------------------------------------------------------


class TestGateResultImmutability:
    def test_frozen_dataclass(self):
        r = gates.GateResult("ruff", "pass", "", "", "", 0.1)
        with pytest.raises(Exception):
            r.outcome = "fail"  # type: ignore[misc]
