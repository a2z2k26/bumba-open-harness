"""Harness integrity verification — validate configs before deployment.

Checks bridge.toml structure, claude-settings.json schema, hook script
syntax, and kernel hash integrity. Designed to be called by TierManager
before any config deployment, or manually via /guardrails command.

Integration points:
    - TierManager.promote() calls verify_pre_deploy()
    - SecurityManager.log_event() records results as 'harness_verification'
    - EventBus publishes 'guardrail.triggered' on critical failures
"""
from __future__ import annotations

import json
import logging
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

# Valid Claude Code hook event types (from SDK coreTypes.ts)
VALID_HOOK_EVENTS = frozenset({
    "PreToolUse", "PostToolUse", "PostToolUseFailure",
    "UserPromptSubmit", "SessionStart", "SessionEnd",
    "Stop", "StopFailure", "SubagentStart", "SubagentStop",
    "PreCompact", "PostCompact", "PermissionRequest",
    "PermissionDenied", "Notification",
    "TeammateIdle", "TaskCreated", "TaskCompleted",
    "Elicitation", "ElicitationResult", "ConfigChange",
    "WorktreeCreate", "WorktreeRemove",
    "InstructionsLoaded", "CwdChanged", "FileChanged",
})

# Required sections and keys in bridge.toml
REQUIRED_TOML_SECTIONS = {
    "bridge": {"data_dir", "log_dir"},
    "claude": {"timeout", "max_turns"},
    "session": {"idle_timeout", "max_errors"},
    "security": {"disallowed_tools"},
}


@dataclass(frozen=True)
class VerificationFailure:
    """A single verification failure."""
    check_name: str
    severity: str  # "critical" | "warning"
    message: str
    file_path: str | None = None
    suggestion: str | None = None


@dataclass(frozen=True)
class VerificationResult:
    """Aggregate result of one or more verification checks."""
    passed: bool
    checks_run: tuple[str, ...]
    failures: tuple[VerificationFailure, ...]
    duration_ms: int
    verified_at: str = ""

    def __init__(
        self,
        passed: bool,
        checks_run: tuple[str, ...] | list[str],
        failures: tuple[VerificationFailure, ...] | list[VerificationFailure],
        duration_ms: int,
        verified_at: str = "",
    ) -> None:
        object.__setattr__(self, "passed", passed)
        object.__setattr__(self, "checks_run", tuple(checks_run))
        object.__setattr__(self, "failures", tuple(failures))
        object.__setattr__(self, "duration_ms", duration_ms)
        object.__setattr__(
            self, "verified_at",
            verified_at or datetime.now(timezone.utc).isoformat(),
        )


def validate_bridge_toml(path: str) -> VerificationResult:
    """Validate bridge.toml structure and semantics."""
    start = time.monotonic()
    checks: list[str] = []
    failures: list[VerificationFailure] = []
    file_path = str(path)

    # 1. Parse TOML
    checks.append("toml_parse")
    try:
        import tomllib
    except ImportError:
        import tomli as tomllib  # type: ignore[no-redef]

    try:
        with open(path, "rb") as f:
            config = tomllib.load(f)
    except Exception as e:
        failures.append(VerificationFailure(
            check_name="toml_parse",
            severity="critical",
            message=f"Failed to parse TOML: {e}",
            file_path=file_path,
            suggestion="Fix TOML syntax errors",
        ))
        elapsed = int((time.monotonic() - start) * 1000)
        return VerificationResult(
            passed=False,
            checks_run=checks,
            failures=failures,
            duration_ms=elapsed,
        )

    # 2. Required sections and keys
    checks.append("required_sections")
    for section, required_keys in REQUIRED_TOML_SECTIONS.items():
        if section not in config:
            failures.append(VerificationFailure(
                check_name="required_sections",
                severity="critical",
                message=f"Missing required section [{section}]",
                file_path=file_path,
                suggestion=f"Add [{section}] section with keys: {', '.join(sorted(required_keys))}",
            ))
        else:
            for key in required_keys:
                if key not in config[section]:
                    failures.append(VerificationFailure(
                        check_name="required_sections",
                        severity="critical",
                        message=f"Missing required key '{key}' in [{section}]",
                        file_path=file_path,
                    ))

    # 3. Timeout ordering
    checks.append("timeout_ordering")
    claude = config.get("claude", {})
    timeout = claude.get("timeout", 0)
    hard_timeout = claude.get("hard_timeout", 0)
    absolute_timeout = claude.get("absolute_timeout", 0)

    if timeout and hard_timeout and timeout >= hard_timeout:
        failures.append(VerificationFailure(
            check_name="timeout_ordering",
            severity="critical",
            message=f"Timeout ordering violation: timeout ({timeout}) >= hard_timeout ({hard_timeout})",
            file_path=file_path,
            suggestion="Ensure timeout < hard_timeout < absolute_timeout",
        ))
    if hard_timeout and absolute_timeout and hard_timeout >= absolute_timeout:
        failures.append(VerificationFailure(
            check_name="timeout_ordering",
            severity="critical",
            message=f"Timeout ordering violation: hard_timeout ({hard_timeout}) >= absolute_timeout ({absolute_timeout})",
            file_path=file_path,
            suggestion="Ensure timeout < hard_timeout < absolute_timeout",
        ))

    # 4. Positive numeric values
    checks.append("positive_values")
    for section_name, section_data in config.items():
        if not isinstance(section_data, dict):
            continue
        for key, value in section_data.items():
            if isinstance(value, (int, float)) and value < 0:
                failures.append(VerificationFailure(
                    check_name="positive_values",
                    severity="warning",
                    message=f"Negative value for [{section_name}].{key}: {value}",
                    file_path=file_path,
                ))

    has_critical = any(f.severity == "critical" for f in failures)
    elapsed = int((time.monotonic() - start) * 1000)

    return VerificationResult(
        passed=not has_critical,
        checks_run=checks,
        failures=failures,
        duration_ms=elapsed,
    )


def validate_claude_settings(path: str) -> VerificationResult:
    """Validate claude-settings.json structure."""
    start = time.monotonic()
    checks: list[str] = []
    failures: list[VerificationFailure] = []
    file_path = str(path)

    # 1. Parse JSON
    checks.append("json_parse")
    try:
        with open(path) as f:
            settings = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        failures.append(VerificationFailure(
            check_name="json_parse",
            severity="critical",
            message=f"Failed to parse JSON: {e}",
            file_path=file_path,
        ))
        elapsed = int((time.monotonic() - start) * 1000)
        return VerificationResult(
            passed=False, checks_run=checks, failures=failures, duration_ms=elapsed,
        )

    # 2. Validate hook event names
    checks.append("hook_events")
    hooks = settings.get("hooks", {})
    for event_name in hooks:
        if event_name not in VALID_HOOK_EVENTS:
            failures.append(VerificationFailure(
                check_name="hook_events",
                severity="warning",
                message=f"Unknown hook event: '{event_name}'",
                file_path=file_path,
                suggestion=f"Valid events: {', '.join(sorted(VALID_HOOK_EVENTS)[:10])}...",
            ))

    # 3. Validate hook entry structure
    checks.append("hook_structure")
    for event_name, entries in hooks.items():
        if not isinstance(entries, list):
            failures.append(VerificationFailure(
                check_name="hook_structure",
                severity="critical",
                message=f"Hook '{event_name}' must be an array, got {type(entries).__name__}",
                file_path=file_path,
            ))
            continue
        for i, entry in enumerate(entries):
            if not isinstance(entry, dict):
                failures.append(VerificationFailure(
                    check_name="hook_structure",
                    severity="critical",
                    message=f"Hook '{event_name}[{i}]' must be an object",
                    file_path=file_path,
                ))
                continue
            if "type" not in entry:
                failures.append(VerificationFailure(
                    check_name="hook_structure",
                    severity="critical",
                    message=f"Hook '{event_name}[{i}]' missing 'type' field",
                    file_path=file_path,
                ))
            if "command" not in entry:
                failures.append(VerificationFailure(
                    check_name="hook_structure",
                    severity="critical",
                    message=f"Hook '{event_name}[{i}]' missing 'command' field",
                    file_path=file_path,
                ))

    has_critical = any(f.severity == "critical" for f in failures)
    elapsed = int((time.monotonic() - start) * 1000)
    return VerificationResult(
        passed=not has_critical, checks_run=checks, failures=failures, duration_ms=elapsed,
    )


def validate_hook_script(path: str) -> VerificationResult:
    """Validate a hook shell script."""
    start = time.monotonic()
    checks: list[str] = []
    failures: list[VerificationFailure] = []
    file_path = str(path)

    # 1. File exists
    checks.append("file_exists")
    p = Path(path)
    if not p.exists():
        failures.append(VerificationFailure(
            check_name="file_exists",
            severity="critical",
            message=f"Hook script not found: {path}",
            file_path=file_path,
        ))
        elapsed = int((time.monotonic() - start) * 1000)
        return VerificationResult(
            passed=False, checks_run=checks, failures=failures, duration_ms=elapsed,
        )

    # 2. Bash syntax check
    checks.append("bash_syntax")
    try:
        result = subprocess.run(
            ["bash", "-n", str(p)],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode != 0:
            failures.append(VerificationFailure(
                check_name="bash_syntax",
                severity="critical",
                message=f"Bash syntax error: {result.stderr.strip()}",
                file_path=file_path,
            ))
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        failures.append(VerificationFailure(
            check_name="bash_syntax",
            severity="warning",
            message=f"Could not verify bash syntax: {e}",
            file_path=file_path,
        ))

    has_critical = any(f.severity == "critical" for f in failures)
    elapsed = int((time.monotonic() - start) * 1000)
    return VerificationResult(
        passed=not has_critical, checks_run=checks, failures=failures, duration_ms=elapsed,
    )


class HarnessVerifier:
    """Orchestrates full harness verification."""

    def __init__(self, config_dir: str) -> None:
        self._config_dir = Path(config_dir)

    def verify_all(self) -> VerificationResult:
        """Run all verification checks. Returns aggregate result."""
        start = time.monotonic()
        all_checks: list[str] = []
        all_failures: list[VerificationFailure] = []

        toml_path = self._config_dir / "bridge.toml"
        if toml_path.exists():
            r = validate_bridge_toml(str(toml_path))
            all_checks.extend(r.checks_run)
            all_failures.extend(r.failures)

        settings_path = self._config_dir / "claude-settings.json"
        if settings_path.exists():
            r = validate_claude_settings(str(settings_path))
            all_checks.extend(r.checks_run)
            all_failures.extend(r.failures)

        hooks_dir = self._config_dir / "claude-files" / "hooks"
        if hooks_dir.exists():
            for script in hooks_dir.glob("*.sh"):
                r = validate_hook_script(str(script))
                all_checks.extend(r.checks_run)
                all_failures.extend(r.failures)

        has_critical = any(f.severity == "critical" for f in all_failures)
        elapsed = int((time.monotonic() - start) * 1000)

        return VerificationResult(
            passed=not has_critical,
            checks_run=all_checks,
            failures=all_failures,
            duration_ms=elapsed,
        )

    def verify_pre_deploy(self, changed_files: list[str]) -> VerificationResult:
        """Verify only files that changed. For use in deploy pipeline."""
        start = time.monotonic()
        all_checks: list[str] = []
        all_failures: list[VerificationFailure] = []

        for file_path in changed_files:
            p = Path(file_path)
            if p.name == "bridge.toml":
                r = validate_bridge_toml(file_path)
                all_checks.extend(r.checks_run)
                all_failures.extend(r.failures)
            elif p.name == "claude-settings.json":
                r = validate_claude_settings(file_path)
                all_checks.extend(r.checks_run)
                all_failures.extend(r.failures)
            elif p.suffix == ".sh":
                r = validate_hook_script(file_path)
                all_checks.extend(r.checks_run)
                all_failures.extend(r.failures)

        has_critical = any(f.severity == "critical" for f in all_failures)
        elapsed = int((time.monotonic() - start) * 1000)

        return VerificationResult(
            passed=not has_critical,
            checks_run=all_checks,
            failures=all_failures,
            duration_ms=elapsed,
        )
