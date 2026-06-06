"""Quality gate chain — automated 7-gate verification pipeline.

Bridge-independent: this module has no bridge imports and can be
used by any Python consumer including Pydantic AI agents.
"""

from __future__ import annotations

import enum
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

log = logging.getLogger(__name__)


class GateLevel(enum.IntEnum):
    LINT = 1
    TYPECHECK = 2
    TEST = 3
    SECURITY = 4
    ARCHITECTURE = 5
    CODE_REVIEW = 6
    HUMAN_APPROVAL = 7


@dataclass(frozen=True)
class GateCheckResult:
    passed: bool = True
    gate_level: GateLevel = GateLevel.LINT
    reason: str = ""
    requires_human: bool = False
    escalation_reason: str = ""


GateChecker = Callable[[str, list[str]], GateCheckResult]


@dataclass
class _RegisteredGate:
    level: GateLevel
    checker: GateChecker
    strict: bool = True


@dataclass
class ChainResult:
    passed: bool = True
    failed_at: GateLevel | None = None
    reason: str = ""
    gate_results: list[GateCheckResult] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    requires_human: bool = False
    escalation_reasons: list[str] = field(default_factory=list)


class QualityChain:
    def __init__(self) -> None:
        self._gates: list[_RegisteredGate] = []
        # Per-skill gate profile: skill_name → set of GateLevel
        self._skill_gates: dict[str, set[GateLevel]] = {}
        self._skill_strict: dict[str, bool] = {}

    def register(self, level: GateLevel, checker: GateChecker, *, strict: bool = True) -> None:
        self._gates.append(_RegisteredGate(level=level, checker=checker, strict=strict))
        self._gates.sort(key=lambda g: g.level)

    def register_skill(self, skill: str, gates: list[GateLevel], *, strict: bool = True) -> None:
        """Register which gates apply to a skill.

        Skills not registered here run NO gates (backwards-compatible).
        """
        self._skill_gates[skill] = set(gates)
        self._skill_strict[skill] = strict

    def run_for_skill(self, skill: str, project: str, files: list[str]) -> ChainResult:
        """Run only the gates registered for the given skill.

        If the skill has no gate profile, returns a passing ChainResult
        immediately (backwards-compatible: unknown skills run no gates).
        """
        allowed = self._skill_gates.get(skill)
        if allowed is None:
            log.debug("QualityChain.run_for_skill: skill %r has no registered gates — skipping", skill)
            return ChainResult(passed=True)

        strict_override = self._skill_strict.get(skill, True)
        result = ChainResult()
        for gate in self._gates:
            if gate.level not in allowed:
                continue
            try:
                check = gate.checker(project, files)
            except Exception as e:
                log.exception("Gate %s raised an exception", gate.level.name)
                check = GateCheckResult(passed=False, gate_level=gate.level, reason=f"Gate error: {e}")
            result.gate_results.append(check)
            if check.requires_human:
                result.requires_human = True
                if check.escalation_reason:
                    result.escalation_reasons.append(check.escalation_reason)
                # Park — do not continue chain
                return result
            if not check.passed:
                if strict_override or gate.strict:
                    result.passed = False
                    result.failed_at = gate.level
                    result.reason = check.reason
                    log.warning("Quality gate %s FAILED (strict): %s", gate.level.name, check.reason)
                    return result
                else:
                    result.warnings.append(f"Gate {gate.level.name} warning: {check.reason}")
        return result

    def run(self, project: str, files: list[str]) -> ChainResult:
        result = ChainResult()
        for gate in self._gates:
            try:
                check = gate.checker(project, files)
            except Exception as e:
                log.exception("Gate %s raised an exception", gate.level.name)
                check = GateCheckResult(passed=False, gate_level=gate.level, reason=f"Gate error: {e}")
            result.gate_results.append(check)
            if check.requires_human:
                result.requires_human = True
                if check.escalation_reason:
                    result.escalation_reasons.append(check.escalation_reason)
            if not check.passed:
                if gate.strict:
                    result.passed = False
                    result.failed_at = gate.level
                    result.reason = check.reason
                    log.warning("Quality gate %s FAILED (strict): %s", gate.level.name, check.reason)
                    return result
                else:
                    result.warnings.append(f"Gate {gate.level.name} warning: {check.reason}")
                    log.warning("Quality gate %s FAILED (warning mode): %s", gate.level.name, check.reason)
        return result


# ---------------------------------------------------------------------------
# Config loader — bridge-independent
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class GateConfig:
    """Configuration for a single quality gate."""
    level: int
    enabled: bool = True
    strict: bool = True
    description: str = ""
    escalate_on_failure: bool = False
    escalation_reason: str = ""


@dataclass(frozen=True)
class SkillGateProfile:
    """Per-skill gate profile loaded from YAML."""
    gates: tuple[str, ...]  # gate names, e.g. ("LINT", "TYPECHECK")
    strict: bool = True


@dataclass(frozen=True)
class QualityChainConfig:
    """Loaded quality chain configuration."""
    gates: tuple[GateConfig, ...] = ()
    coverage_threshold: int = 80
    skip_patterns: tuple[str, ...] = ()
    skill_gates: dict[str, SkillGateProfile] = field(default_factory=dict)

    @classmethod
    def from_config(cls, config_path: str | Path) -> QualityChainConfig:
        """Load quality chain config from YAML.

        Bridge-independent — usable by any Python consumer.
        """
        path = Path(config_path)
        if not path.exists():
            log.warning("Quality chain config not found: %s", path)
            return cls()

        try:
            import yaml
        except ImportError:
            log.warning("PyYAML not available, using empty config")
            return cls()

        try:
            data: dict[str, Any] = yaml.safe_load(path.read_text(encoding="utf-8"))
        except Exception:
            log.exception("Failed to parse quality chain config: %s", path)
            return cls()

        gates_data = data.get("gates", {})
        gates: list[GateConfig] = []
        for name, cfg in gates_data.items():
            if not isinstance(cfg, dict):
                continue
            gates.append(GateConfig(
                level=cfg.get("level", 0),
                enabled=cfg.get("enabled", True),
                strict=cfg.get("strict", True),
                description=cfg.get("description", ""),
                escalate_on_failure=cfg.get("escalate_on_failure", False),
                escalation_reason=cfg.get("escalation_reason", ""),
            ))

        gates.sort(key=lambda g: g.level)

        # Parse per-skill gate profiles
        skill_gates_data = data.get("skill_gates", {})
        skill_gates: dict[str, SkillGateProfile] = {}
        for skill_name, skill_cfg in skill_gates_data.items():
            if not isinstance(skill_cfg, dict):
                continue
            raw_gates = skill_cfg.get("gates", [])
            # Normalize gate names to uppercase strings
            gate_names = tuple(str(g).upper() for g in raw_gates)
            skill_gates[skill_name] = SkillGateProfile(
                gates=gate_names,
                strict=skill_cfg.get("strict", True),
            )

        return cls(
            gates=tuple(gates),
            coverage_threshold=data.get("coverage_threshold", 80),
            skip_patterns=tuple(data.get("skip_patterns", [])),
            skill_gates=skill_gates,
        )
