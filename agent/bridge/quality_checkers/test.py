"""TEST gate — runs pytest on the project's test directory.

Falls back gracefully when pytest is not installed.

Sprint P8.3 / audit M-3 (#1749): the prior docstring claimed this gate
"uses evidence.capture_evidence_async when available, else direct
subprocess." That wire never existed — there was no import of ``evidence``
in this file and no runtime call site for harness-observed evidence
inside the bridge. ``bridge/evidence.py`` has been moved to
``scripts/evidence.py`` (operator CLI tooling); this gate continues to
use ``subprocess.run`` directly, which is the only path it ever used.
"""
from __future__ import annotations

import logging
import subprocess
from pathlib import Path

from bridge.quality_chain import GateCheckResult, GateLevel

log = logging.getLogger(__name__)


class TestChecker:
    """Gate 3: TEST via pytest.

    Discovers the test directory relative to the project path. If the
    project path is not a directory, falls back to the current directory.
    """

    def __init__(self, coverage_threshold: int = 80) -> None:
        self.coverage_threshold = coverage_threshold

    def __call__(self, project: str, files: list[str]) -> GateCheckResult:
        project_path = Path(project) if project else Path(".")
        test_dir = self._find_test_dir(project_path)

        cmd = ["python3", "-m", "pytest", str(test_dir), "-q", "--tb=short", "-x"]

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=600,
                cwd=str(project_path) if project_path.is_dir() else None,
            )
        except FileNotFoundError:
            log.warning("pytest not installed — test gate skipped")
            return GateCheckResult(
                passed=True,
                gate_level=GateLevel.TEST,
                reason="pytest not installed — test gate skipped",
            )
        except subprocess.TimeoutExpired:
            return GateCheckResult(
                passed=False,
                gate_level=GateLevel.TEST,
                reason="pytest timed out after 600s",
            )

        if result.returncode == 0:
            return GateCheckResult(passed=True, gate_level=GateLevel.TEST)

        # Extract failure summary from output
        output = (result.stdout + result.stderr).strip()
        lines = output.splitlines()
        # Find the summary line
        summary_lines = [l for l in lines if l.startswith("FAILED") or "failed" in l.lower()][:5]
        if not summary_lines:
            summary_lines = lines[-10:]
        summary = "\n".join(summary_lines)

        return GateCheckResult(
            passed=False,
            gate_level=GateLevel.TEST,
            reason=f"pytest failed (exit {result.returncode}):\n{summary}",
        )

    def _find_test_dir(self, project_path: Path) -> Path:
        """Find the tests directory for the given project path."""
        for candidate in ("tests", "test"):
            d = project_path / candidate
            if d.is_dir():
                return d
        # No tests dir found — run from project root (will discover nothing)
        return project_path
