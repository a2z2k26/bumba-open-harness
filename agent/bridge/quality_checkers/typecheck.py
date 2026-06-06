"""TYPECHECK gate — runs mypy on the given files.

Falls back to PASS (non-strict warning) if mypy is not installed.
"""
from __future__ import annotations

import logging
import subprocess
from pathlib import Path

from bridge.quality_chain import GateCheckResult, GateLevel

log = logging.getLogger(__name__)


class TypecheckChecker:
    """Gate 2: TYPECHECK via mypy."""

    def __call__(self, project: str, files: list[str]) -> GateCheckResult:
        py_files = [f for f in files if f.endswith(".py")]
        if not py_files:
            return GateCheckResult(
                passed=True,
                gate_level=GateLevel.TYPECHECK,
                reason="No Python files to typecheck",
            )

        existing = [f for f in py_files if Path(f).exists()]
        if not existing:
            return GateCheckResult(
                passed=True,
                gate_level=GateLevel.TYPECHECK,
                reason="No Python files exist on disk (skipping typecheck)",
            )

        try:
            result = subprocess.run(
                [
                    "mypy",
                    "--ignore-missing-imports",
                    "--no-error-summary",
                ] + existing,
                capture_output=True,
                text=True,
                timeout=120,
            )
        except FileNotFoundError:
            log.warning("mypy not installed — typecheck gate skipped (warning mode)")
            return GateCheckResult(
                passed=True,
                gate_level=GateLevel.TYPECHECK,
                reason="mypy not installed — typecheck skipped",
            )
        except subprocess.TimeoutExpired:
            return GateCheckResult(
                passed=False,
                gate_level=GateLevel.TYPECHECK,
                reason="mypy timed out after 120s",
            )

        if result.returncode == 0:
            return GateCheckResult(passed=True, gate_level=GateLevel.TYPECHECK)

        lines = result.stdout.strip().splitlines()
        # Filter out "Found N errors" summary line
        errors = [l for l in lines if ": error:" in l]
        summary = "\n".join(errors[:10])
        if len(errors) > 10:
            summary += f"\n... ({len(errors) - 10} more errors)"

        return GateCheckResult(
            passed=False,
            gate_level=GateLevel.TYPECHECK,
            reason=f"mypy found {len(errors)} type error(s):\n{summary}",
        )
