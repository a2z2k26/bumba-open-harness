"""Self-diagnosis runbook engine for automated failure analysis."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)


@dataclass
class DiagnosisStep:
    id: str
    check: str
    passed: bool
    output: str
    fix: str | None = None


@dataclass
class DiagnosisResult:
    runbook_id: str
    runbook_name: str
    steps: list[DiagnosisStep]
    resolution: str
    escalation: str
    overall_passed: bool

    def format_summary(self) -> str:
        """Format diagnosis as human-readable text."""
        status = "PASS" if self.overall_passed else "FAIL"
        lines = [f"Diagnosis: {self.runbook_name} [{status}]"]
        for step in self.steps:
            icon = "+" if step.passed else "X"
            lines.append(f"  [{icon}] {step.check}: {step.output[:200]}")
            if step.fix:
                lines.append(f"      Fix: {step.fix}")
        if not self.overall_passed:
            lines.append(f"  Resolution: {self.resolution}")
            lines.append(f"  Escalation: {self.escalation}")
        return "\n".join(lines)


class RunbookEngine:
    """Load and execute YAML-based diagnostic runbooks."""

    def __init__(self, runbook_dir: str | Path = "config/runbooks") -> None:
        self._dir = Path(runbook_dir)
        self._runbooks: dict[str, dict] = {}

    def load_runbooks(self) -> int:
        """Load all YAML runbooks from directory. Returns count loaded."""
        if not self._dir.exists():
            logger.warning("Runbook directory not found: %s", self._dir)
            return 0

        loaded = 0
        for path in sorted(self._dir.glob("*.yaml")):
            if path.name == "schema.yaml":
                continue
            try:
                with open(path) as f:
                    rb = yaml.safe_load(f)
                if rb and isinstance(rb, dict) and "id" in rb:
                    self._runbooks[rb["id"]] = rb
                    loaded += 1
            except Exception as e:
                logger.warning("Failed to load runbook %s: %s", path.name, e)

        logger.info("Loaded %d runbook(s) from %s", loaded, self._dir)
        return loaded

    @property
    def runbooks(self) -> dict[str, dict]:
        return self._runbooks

    def match_triggers(self, health_state: dict) -> list[dict]:
        """Return runbooks whose triggers match the current health state.

        Supports simple key-value condition matching against the flattened
        health state dictionary.
        """
        matched = []
        for rb in self._runbooks.values():
            trigger = rb.get("trigger", {})
            if self._evaluate_trigger(trigger, health_state):
                matched.append(rb)
        return matched

    def _evaluate_trigger(self, trigger: dict, state: dict) -> bool:
        """Evaluate trigger conditions against health state."""
        if not trigger:
            return False

        # Check simple condition
        condition = trigger.get("condition")
        if condition and self._eval_condition(condition, state):
            return True

        # Check OR conditions
        or_conditions = trigger.get("or", [])
        for cond in or_conditions:
            if self._eval_condition(cond, state):
                return True

        return False

    @staticmethod
    def _eval_condition(condition: str, state: dict) -> bool:
        """Evaluate a simple condition string against state dict.

        Supports: key == "value", key < number, key > number
        """
        for op in ("==", "!=", "<", ">", "<=", ">="):
            if op in condition:
                parts = condition.split(op, 1)
                if len(parts) != 2:
                    continue
                key = parts[0].strip()
                expected = parts[1].strip().strip('"').strip("'")

                actual = state.get(key)
                if actual is None:
                    # Try dotted path: components.token.status
                    actual = state
                    for part in key.split("."):
                        if isinstance(actual, dict):
                            actual = actual.get(part)
                        else:
                            actual = None
                            break

                if actual is None:
                    continue

                try:
                    if op == "==":
                        return str(actual) == expected
                    elif op == "!=":
                        return str(actual) != expected
                    elif op in ("<", ">", "<=", ">="):
                        a = float(actual)
                        b = float(expected)
                        if op == "<":
                            return a < b
                        elif op == ">":
                            return a > b
                        elif op == "<=":
                            return a <= b
                        elif op == ">=":
                            return a >= b
                except (ValueError, TypeError):
                    continue
                return False
        return False

    async def execute_runbook(
        self, runbook: dict, timeout: int = 5
    ) -> DiagnosisResult:
        """Execute all diagnostic steps in a runbook."""
        steps = []
        for step_def in runbook.get("steps", []):
            cmd = step_def.get("command", "echo SKIP")
            try:
                proc = await asyncio.create_subprocess_shell(
                    cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                try:
                    stdout, _ = await asyncio.wait_for(
                        proc.communicate(), timeout=timeout
                    )
                    output = stdout.decode().strip()
                    passed = proc.returncode == 0 and "FAIL" not in output.upper()
                except asyncio.TimeoutError:
                    proc.kill()
                    await proc.wait()
                    output = "TIMEOUT"
                    passed = False
            except Exception as e:
                output = str(e)
                passed = False

            steps.append(DiagnosisStep(
                id=step_def.get("id", "unknown"),
                check=step_def.get("check", ""),
                passed=passed,
                output=output,
                fix=step_def.get("fix") if not passed else None,
            ))

        return DiagnosisResult(
            runbook_id=runbook["id"],
            runbook_name=runbook.get("name", runbook["id"]),
            steps=steps,
            resolution=runbook.get("resolution", ""),
            escalation=runbook.get("escalation", ""),
            overall_passed=all(s.passed for s in steps),
        )
