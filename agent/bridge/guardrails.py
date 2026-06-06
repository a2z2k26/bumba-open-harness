"""MS5.8 — Guardrail Tripwires.

Parallel input/output validation with fast-fail for safety. Tripwires detect
prompt injection, data leakage, hallucination indicators, and size violations.

Actions: PASS, LOG, WARN, BLOCK, ESCALATE
"""

from __future__ import annotations

import json
import logging
import re
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Action constants (priority order: ESCALATE > BLOCK > WARN > LOG > PASS)
# ---------------------------------------------------------------------------

ACTION_PASS = "PASS"
ACTION_LOG = "LOG"
ACTION_WARN = "WARN"
ACTION_BLOCK = "BLOCK"
ACTION_ESCALATE = "ESCALATE"

_ACTION_PRIORITY = {
    ACTION_PASS: 0,
    ACTION_LOG: 1,
    ACTION_WARN: 2,
    ACTION_BLOCK: 3,
    ACTION_ESCALATE: 4,
}

# ---------------------------------------------------------------------------
# Severity constants
# ---------------------------------------------------------------------------

SEVERITY_CRITICAL = "critical"
SEVERITY_HIGH = "high"
SEVERITY_MEDIUM = "medium"
SEVERITY_LOW = "low"

# ---------------------------------------------------------------------------
# Default patterns
# ---------------------------------------------------------------------------

INJECTION_PATTERNS = [
    r"ignore\s+(all\s+)?previous\s+instructions",
    r"you\s+are\s+now\s+",
    r"system\s+prompt\s+override",
    r"disregard\s+(all\s+)?prior",
    r"new\s+instructions?\s*:",
    r"act\s+as\s+if\s+you\s+are",
    r"pretend\s+you\s+are",
    r"override\s+your\s+(instructions|rules|guidelines)",
    r"forget\s+(everything|all|your\s+instructions)",
    # R7: base64_block — long base64 strings that may embed encoded instructions
    r"[A-Za-z0-9+/]{60,}={0,2}",
    # R7: authority_spoof — impersonation of AI identity or privileged roles
    r"(?:i\s+am\s+claude|as\s+claude|you\s+are\s+now|ignore\s+previous|i\s+am\s+an?\s+ai\s+assistant|^(?:ADMIN|OPERATOR|ROOT|SUDO):)",
]

# Named pattern registry for test assertions and targeted lookups
INJECTION_PATTERNS_NAMED: dict[str, str] = {
    "instruction_override": r"ignore\s+(all\s+)?previous\s+instructions",
    "you_are_now": r"you\s+are\s+now\s+",
    "system_prompt_override": r"system\s+prompt\s+override",
    "disregard_prior": r"disregard\s+(all\s+)?prior",
    "new_instructions": r"new\s+instructions?\s*:",
    "act_as_if": r"act\s+as\s+if\s+you\s+are",
    "pretend": r"pretend\s+you\s+are",
    "override_rules": r"override\s+your\s+(instructions|rules|guidelines)",
    "forget_instructions": r"forget\s+(everything|all|your\s+instructions)",
    "base64_block": r"[A-Za-z0-9+/]{60,}={0,2}",
    "authority_spoof": r"(?:i\s+am\s+claude|as\s+claude|you\s+are\s+now|ignore\s+previous|i\s+am\s+an?\s+ai\s+assistant|^(?:ADMIN|OPERATOR|ROOT|SUDO):)",
}

SENSITIVE_DATA_PATTERNS = [
    r"(?:sk|pk)[-_](?:live|test)[-_][a-zA-Z0-9]{20,}",  # Stripe keys
    r"(?:ghp|gho|ghu|ghs|ghr)_[a-zA-Z0-9]{36,}",  # GitHub tokens
    r"xoxb-[0-9]{10,}-[a-zA-Z0-9]{20,}",  # Slack bot tokens
    r"AKIA[0-9A-Z]{16}",  # AWS access keys
    r"\b\d{3}-\d{2}-\d{4}\b",  # SSN
    r"\b\d{4}[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{4}\b",  # Credit cards
]

UNCERTAINTY_PHRASES = [
    "i'm not sure",
    "i think",
    "possibly",
    "might be",
    "not certain",
    "i believe",
    "could be wrong",
    "don't quote me",
]

# ---------------------------------------------------------------------------
# Thresholds
# ---------------------------------------------------------------------------

MAX_INPUT_SIZE = 50_000  # 50 KB
MAX_OUTPUT_SIZE = 100_000  # 100 KB
UNCERTAINTY_THRESHOLD = 3  # phrases before triggering


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class TripwireResult:
    """Result from a single tripwire check."""

    tripwire_id: str = ""
    triggered: bool = False
    action: str = ACTION_PASS
    severity: str = ""
    details: str = ""
    latency_ms: float = 0.0


@dataclass
class GuardrailResult:
    """Aggregate result from all tripwire checks."""

    passed: bool = True
    triggered_tripwires: list[TripwireResult] = field(default_factory=list)
    action: str = ACTION_PASS  # highest-severity action
    details: str = ""
    redacted_text: str = ""  # response with sensitive tokens stripped (Sprint 06.04)


@dataclass
class GuardrailConfig:
    """Runtime configuration for the guardrail engine."""

    injection_enabled: bool = True
    sensitive_input_enabled: bool = True
    size_input_enabled: bool = True
    sensitive_output_enabled: bool = True
    canary_enabled: bool = True
    uncertainty_enabled: bool = True
    hallucination_enabled: bool = True
    size_output_enabled: bool = True
    custom_injection_patterns: list[str] = field(default_factory=list)
    canary_tokens: list[str] = field(default_factory=list)
    known_secrets: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# GuardrailEngine
# ---------------------------------------------------------------------------


class GuardrailEngine:
    """Synchronous guardrail engine with input/output tripwires."""

    def __init__(
        self,
        config: GuardrailConfig | None = None,
        incident_path: Path | None = None,
    ) -> None:
        self._config = config or GuardrailConfig()
        self._incident_path = incident_path
        self._lock = threading.Lock()

        # Pre-compile patterns for performance
        self._compiled_injection: list[re.Pattern[str]] = []
        self._compiled_sensitive: list[re.Pattern[str]] = []
        self._recompile()

        self._metrics = {
            "total_checked": 0,
            "total_blocked": 0,
            "total_escalated": 0,
            "total_warned": 0,
            "total_passed": 0,
            "input_checks": 0,
            "output_checks": 0,
        }

    def _recompile(self) -> None:
        """Compile regex patterns from config."""
        all_injection = INJECTION_PATTERNS + self._config.custom_injection_patterns
        self._compiled_injection = [
            re.compile(p, re.IGNORECASE) for p in all_injection
        ]
        self._compiled_sensitive = [
            re.compile(p) for p in SENSITIVE_DATA_PATTERNS
        ]

    # -- public API ---------------------------------------------------------

    def check_input(
        self, message: str, context: dict | None = None,
    ) -> GuardrailResult:
        """Run all input tripwires and return aggregate result."""
        results: list[TripwireResult] = []

        if self._config.injection_enabled:
            results.append(self._check_injection(message))
        if self._config.sensitive_input_enabled:
            results.append(self._check_sensitive_input(message))
        if self._config.size_input_enabled:
            results.append(self._check_input_size(message))

        result = self._aggregate(results)

        with self._lock:
            self._metrics["total_checked"] += 1
            self._metrics["input_checks"] += 1
            self._update_action_metrics(result)

        if not result.passed:
            self._log_incident(result, "input", message[:200])

        return result

    def check_output(
        self, response: str, context: dict | None = None,
    ) -> GuardrailResult:
        """Run all output tripwires and return aggregate result."""
        results: list[TripwireResult] = []

        if self._config.sensitive_output_enabled:
            results.append(self._check_sensitive_output(response))
        if self._config.canary_enabled:
            results.append(self._check_canary(response))
        if self._config.uncertainty_enabled:
            results.append(self._check_uncertainty(response))
        if self._config.size_output_enabled:
            results.append(self._check_output_size(response))

        result = self._aggregate(results)

        # Populate redacted_text: strip canary tokens and known secrets (Sprint 06.04)
        redacted = response
        for token in self._config.canary_tokens:
            if token:
                redacted = redacted.replace(token, "[REDACTED]")
        for secret in self._config.known_secrets:
            if secret:
                redacted = redacted.replace(secret, "[REDACTED]")
        result.redacted_text = redacted

        with self._lock:
            self._metrics["total_checked"] += 1
            self._metrics["output_checks"] += 1
            self._update_action_metrics(result)

        if not result.passed:
            self._log_incident(result, "output", response[:200])

        return result

    def reload_config(self, config: GuardrailConfig) -> None:
        """Hot-reload configuration (thread-safe)."""
        with self._lock:
            self._config = config
            self._recompile()

    def get_metrics(self) -> dict:
        """Return a snapshot of current metrics."""
        with self._lock:
            return dict(self._metrics)

    # -- input tripwires ----------------------------------------------------

    def _check_injection(self, message: str) -> TripwireResult:
        """IT-01: Detect prompt injection attempts."""
        start = time.monotonic()
        for pattern in self._compiled_injection:
            match = pattern.search(message)
            if match:
                elapsed = (time.monotonic() - start) * 1000
                return TripwireResult(
                    tripwire_id="IT-01",
                    triggered=True,
                    action=ACTION_BLOCK,
                    severity=SEVERITY_HIGH,
                    details=f"Injection pattern matched: {match.group()[:80]}",
                    latency_ms=elapsed,
                )
        elapsed = (time.monotonic() - start) * 1000
        return TripwireResult(tripwire_id="IT-01", latency_ms=elapsed)

    def _check_sensitive_input(self, message: str) -> TripwireResult:
        """IT-02: Detect sensitive data (keys, SSNs, cards) in input."""
        start = time.monotonic()
        for pattern in self._compiled_sensitive:
            match = pattern.search(message)
            if match:
                elapsed = (time.monotonic() - start) * 1000
                return TripwireResult(
                    tripwire_id="IT-02",
                    triggered=True,
                    action=ACTION_WARN,
                    severity=SEVERITY_MEDIUM,
                    details=f"Sensitive data pattern detected in input (pattern: {pattern.pattern[:60]})",
                    latency_ms=elapsed,
                )
        elapsed = (time.monotonic() - start) * 1000
        return TripwireResult(tripwire_id="IT-02", latency_ms=elapsed)

    def _check_input_size(self, message: str) -> TripwireResult:
        """IT-05: Block oversized input messages."""
        start = time.monotonic()
        size = len(message.encode("utf-8"))
        elapsed = (time.monotonic() - start) * 1000
        if size > MAX_INPUT_SIZE:
            return TripwireResult(
                tripwire_id="IT-05",
                triggered=True,
                action=ACTION_BLOCK,
                severity=SEVERITY_MEDIUM,
                details=f"Input size {size} exceeds limit {MAX_INPUT_SIZE}",
                latency_ms=elapsed,
            )
        return TripwireResult(tripwire_id="IT-05", latency_ms=elapsed)

    # -- output tripwires ---------------------------------------------------

    def _check_sensitive_output(self, response: str) -> TripwireResult:
        """OT-01: Detect sensitive data or known secrets in output."""
        start = time.monotonic()

        # Check known secrets from config first (exact match, highest severity)
        for secret in self._config.known_secrets:
            if secret and secret in response:
                elapsed = (time.monotonic() - start) * 1000
                return TripwireResult(
                    tripwire_id="OT-01",
                    triggered=True,
                    action=ACTION_BLOCK,
                    severity=SEVERITY_CRITICAL,
                    details="Known secret detected in output",
                    latency_ms=elapsed,
                )

        # Check regex patterns
        for pattern in self._compiled_sensitive:
            match = pattern.search(response)
            if match:
                elapsed = (time.monotonic() - start) * 1000
                return TripwireResult(
                    tripwire_id="OT-01",
                    triggered=True,
                    action=ACTION_BLOCK,
                    severity=SEVERITY_HIGH,
                    details=f"Sensitive data pattern detected in output (pattern: {pattern.pattern[:60]})",
                    latency_ms=elapsed,
                )

        elapsed = (time.monotonic() - start) * 1000
        return TripwireResult(tripwire_id="OT-01", latency_ms=elapsed)

    def _check_canary(self, response: str) -> TripwireResult:
        """OT-02: Detect canary tokens leaked into output."""
        start = time.monotonic()
        for token in self._config.canary_tokens:
            if token and token in response:
                elapsed = (time.monotonic() - start) * 1000
                return TripwireResult(
                    tripwire_id="OT-02",
                    triggered=True,
                    action=ACTION_ESCALATE,
                    severity=SEVERITY_CRITICAL,
                    details=f"Canary token leaked in output: {token[:20]}...",
                    latency_ms=elapsed,
                )
        elapsed = (time.monotonic() - start) * 1000
        return TripwireResult(tripwire_id="OT-02", latency_ms=elapsed)

    def _check_uncertainty(self, response: str) -> TripwireResult:
        """OT-03: Flag responses with excessive uncertainty markers."""
        start = time.monotonic()
        lower = response.lower()
        count = sum(1 for phrase in UNCERTAINTY_PHRASES if phrase in lower)
        elapsed = (time.monotonic() - start) * 1000

        if count >= UNCERTAINTY_THRESHOLD:
            return TripwireResult(
                tripwire_id="OT-03",
                triggered=True,
                action=ACTION_LOG,
                severity=SEVERITY_LOW,
                details=f"Uncertainty indicators: {count} phrases detected (threshold: {UNCERTAINTY_THRESHOLD})",
                latency_ms=elapsed,
            )
        return TripwireResult(tripwire_id="OT-03", latency_ms=elapsed)

    def _check_output_size(self, response: str) -> TripwireResult:
        """OT-05: Flag oversized output responses."""
        start = time.monotonic()
        size = len(response.encode("utf-8"))
        elapsed = (time.monotonic() - start) * 1000
        if size > MAX_OUTPUT_SIZE:
            return TripwireResult(
                tripwire_id="OT-05",
                triggered=True,
                action=ACTION_WARN,
                severity=SEVERITY_LOW,
                details=f"Output size {size} exceeds limit {MAX_OUTPUT_SIZE}",
                latency_ms=elapsed,
            )
        return TripwireResult(tripwire_id="OT-05", latency_ms=elapsed)

    # -- aggregation --------------------------------------------------------

    def _aggregate(self, results: list[TripwireResult]) -> GuardrailResult:
        """Aggregate tripwire results. Highest-severity action wins.

        BLOCK or ESCALATE => passed = False.
        """
        triggered = [r for r in results if r.triggered]

        if not triggered:
            return GuardrailResult(passed=True, action=ACTION_PASS)

        # Find highest-priority action
        highest_action = ACTION_PASS
        for r in triggered:
            if _ACTION_PRIORITY.get(r.action, 0) > _ACTION_PRIORITY.get(highest_action, 0):
                highest_action = r.action

        passed = highest_action not in (ACTION_BLOCK, ACTION_ESCALATE)

        details_parts = [r.details for r in triggered if r.details]
        combined_details = "; ".join(details_parts)

        return GuardrailResult(
            passed=passed,
            triggered_tripwires=triggered,
            action=highest_action,
            details=combined_details,
        )

    # -- incident logging ---------------------------------------------------

    def _log_incident(
        self, result: GuardrailResult, direction: str, content_preview: str,
    ) -> None:
        """Log a guardrail incident to JSONL file."""
        if not self._incident_path:
            log.warning(
                "Guardrail %s (action=%s): %s",
                direction, result.action, result.details,
            )
            return

        entry = {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "direction": direction,
            "action": result.action,
            "passed": result.passed,
            "details": result.details,
            "content_preview": content_preview[:200],
            "tripwires": [
                {
                    "id": t.tripwire_id,
                    "action": t.action,
                    "severity": t.severity,
                    "details": t.details,
                    "latency_ms": t.latency_ms,
                }
                for t in result.triggered_tripwires
            ],
        }

        try:
            self._incident_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self._incident_path, "a") as f:
                f.write(json.dumps(entry) + "\n")
        except OSError as exc:
            log.error(
                "Failed to write guardrail incident to %s: %s",
                self._incident_path, exc,
            )

    # -- metrics helpers ----------------------------------------------------

    def _update_action_metrics(self, result: GuardrailResult) -> None:
        """Update metrics counters based on result action (caller holds lock)."""
        if result.action == ACTION_BLOCK:
            self._metrics["total_blocked"] += 1
        elif result.action == ACTION_ESCALATE:
            self._metrics["total_escalated"] += 1
        elif result.action == ACTION_WARN:
            self._metrics["total_warned"] += 1
        else:
            self._metrics["total_passed"] += 1
