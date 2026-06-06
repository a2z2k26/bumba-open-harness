"""SECURITY gate — runs bandit on the given Python files.

Falls back to PASS (non-strict warning) if bandit is not installed.
Only HIGH severity issues cause a gate failure by default.
"""
from __future__ import annotations

import json
import logging
import subprocess
from pathlib import Path

from bridge.quality_chain import GateCheckResult, GateLevel

log = logging.getLogger(__name__)

# Minimum bandit severity level that causes gate failure: HIGH | MEDIUM | LOW
_FAIL_SEVERITY = "HIGH"


class SecurityChecker:
    """Gate 4: SECURITY via bandit."""

    def __init__(self, fail_severity: str = _FAIL_SEVERITY) -> None:
        self.fail_severity = fail_severity.upper()

    def __call__(self, project: str, files: list[str]) -> GateCheckResult:
        py_files = [f for f in files if f.endswith(".py")]
        if not py_files:
            return GateCheckResult(
                passed=True,
                gate_level=GateLevel.SECURITY,
                reason="No Python files to scan",
            )

        existing = [f for f in py_files if Path(f).exists()]
        if not existing:
            return GateCheckResult(
                passed=True,
                gate_level=GateLevel.SECURITY,
                reason="No Python files exist on disk (skipping security scan)",
            )

        try:
            result = subprocess.run(
                [
                    "bandit",
                    "-r",
                    "-f", "json",
                    "-l",  # low confidence threshold included
                ] + existing,
                capture_output=True,
                text=True,
                timeout=120,
            )
        except FileNotFoundError:
            log.warning("bandit not installed — security gate skipped (warning mode)")
            return GateCheckResult(
                passed=True,
                gate_level=GateLevel.SECURITY,
                reason="bandit not installed — security scan skipped",
            )
        except subprocess.TimeoutExpired:
            return GateCheckResult(
                passed=False,
                gate_level=GateLevel.SECURITY,
                reason="bandit timed out after 120s",
            )

        # bandit returns 0 for no issues, 1 for issues found, 2 for errors
        if result.returncode == 2:
            return GateCheckResult(
                passed=False,
                gate_level=GateLevel.SECURITY,
                reason=f"bandit error: {result.stderr[:200]}",
            )

        if result.returncode == 0:
            return GateCheckResult(passed=True, gate_level=GateLevel.SECURITY)

        # Parse JSON output to filter by severity
        try:
            data = json.loads(result.stdout)
            issues = data.get("results", [])
        except (json.JSONDecodeError, AttributeError):
            # Can't parse — treat as failure if returncode != 0
            return GateCheckResult(
                passed=False,
                gate_level=GateLevel.SECURITY,
                reason="bandit found security issues (could not parse output)",
            )

        severity_order = {"LOW": 0, "MEDIUM": 1, "HIGH": 2}
        fail_level = severity_order.get(self.fail_severity, 2)

        high_issues = [
            i for i in issues
            if severity_order.get(i.get("issue_severity", "LOW").upper(), 0) >= fail_level
        ]

        if not high_issues:
            return GateCheckResult(passed=True, gate_level=GateLevel.SECURITY)

        summaries = []
        for issue in high_issues[:5]:
            summaries.append(
                f"{issue.get('filename','?')}:{issue.get('line_number','?')} "
                f"[{issue.get('issue_severity','?')}] {issue.get('issue_text','?')}"
            )
        extra = len(high_issues) - len(summaries)
        reason = f"bandit: {len(high_issues)} {self.fail_severity}+ issue(s):\n" + "\n".join(summaries)
        if extra > 0:
            reason += f"\n... ({extra} more)"

        return GateCheckResult(
            passed=False,
            gate_level=GateLevel.SECURITY,
            reason=reason,
        )
