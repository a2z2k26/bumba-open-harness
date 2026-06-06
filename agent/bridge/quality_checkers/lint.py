"""LINT gate — runs ruff on the given files.

Falls back to PASS (non-strict warning) if ruff is not installed.
"""
from __future__ import annotations

import logging
import subprocess
from pathlib import Path

from bridge.quality_chain import GateCheckResult, GateLevel

log = logging.getLogger(__name__)


class LintChecker:
    """Gate 1: LINT via ruff."""

    def __call__(self, project: str, files: list[str]) -> GateCheckResult:
        py_files = [f for f in files if f.endswith(".py")]
        if not py_files:
            return GateCheckResult(
                passed=True,
                gate_level=GateLevel.LINT,
                reason="No Python files to lint",
            )

        # Verify files exist on disk
        existing = [f for f in py_files if Path(f).exists()]
        if not existing:
            return GateCheckResult(
                passed=True,
                gate_level=GateLevel.LINT,
                reason="No Python files exist on disk (skipping lint)",
            )

        try:
            result = subprocess.run(
                ["ruff", "check", "--output-format=concise"] + existing,
                capture_output=True,
                text=True,
                timeout=60,
            )
        except FileNotFoundError:
            log.warning("ruff not installed — lint gate skipped (warning mode)")
            return GateCheckResult(
                passed=True,
                gate_level=GateLevel.LINT,
                reason="ruff not installed — lint skipped",
            )
        except subprocess.TimeoutExpired:
            return GateCheckResult(
                passed=False,
                gate_level=GateLevel.LINT,
                reason="ruff timed out after 60s",
            )

        if result.returncode == 0:
            return GateCheckResult(passed=True, gate_level=GateLevel.LINT)

        lines = result.stdout.strip().splitlines()
        summary = "\n".join(lines[:10])
        if len(lines) > 10:
            summary += f"\n... ({len(lines) - 10} more issues)"

        return GateCheckResult(
            passed=False,
            gate_level=GateLevel.LINT,
            reason=f"ruff found {len(lines)} lint issue(s):\n{summary}",
        )
