"""SDD/TDD Pipeline state machine."""

from __future__ import annotations

import enum
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable

log = logging.getLogger(__name__)


class SDDStage(enum.Enum):
    SPECIFY = "specify"
    PLAN = "plan"
    TASKS = "tasks"
    IMPLEMENT = "implement"
    VERIFY = "verify"
    COMPLETE = "complete"


class InvalidStageTransitionError(Exception):
    pass


@dataclass
class GateResult:
    passed: bool = True
    reason: str = ""
    warnings: list[str] = field(default_factory=list)


GateChecker = Callable[[str], GateResult]

_FORWARD: dict[SDDStage, SDDStage] = {
    SDDStage.SPECIFY: SDDStage.PLAN,
    SDDStage.PLAN: SDDStage.TASKS,
    SDDStage.TASKS: SDDStage.IMPLEMENT,
    SDDStage.IMPLEMENT: SDDStage.VERIFY,
    SDDStage.VERIFY: SDDStage.COMPLETE,
}

_STAGE_ORDER = [
    SDDStage.SPECIFY, SDDStage.PLAN, SDDStage.TASKS,
    SDDStage.IMPLEMENT, SDDStage.VERIFY, SDDStage.COMPLETE,
]


class SDDPipeline:
    def __init__(
        self,
        *,
        project: str,
        initial_stage: SDDStage = SDDStage.SPECIFY,
        strict_gates: bool = True,
    ) -> None:
        self._project = project
        self._current = initial_stage
        self._strict = strict_gates
        self._gates: dict[tuple[SDDStage, SDDStage], list[GateChecker]] = {}
        self._history: list[dict[str, str]] = []

    @property
    def current_stage(self) -> SDDStage:
        return self._current

    def register_gate(self, from_stage: SDDStage, to_stage: SDDStage, checker: GateChecker) -> None:
        key = (from_stage, to_stage)
        self._gates.setdefault(key, []).append(checker)

    def advance(self, to: SDDStage) -> GateResult:
        expected = _FORWARD.get(self._current)
        if expected is None or to != expected:
            raise InvalidStageTransitionError(
                f"Cannot advance from {self._current.value} to {to.value}. "
                f"Expected: {expected.value if expected else 'none (terminal)'}"
            )

        key = (self._current, to)
        all_warnings: list[str] = []
        for checker in self._gates.get(key, []):
            result = checker(self._project)
            if not result.passed:
                if self._strict:
                    log.warning("Gate blocked %s → %s: %s", self._current.value, to.value, result.reason)
                    return result
                else:
                    all_warnings.append(f"Gate warning (non-blocking): {result.reason}")
                    log.warning("Gate would block %s → %s (warning mode): %s", self._current.value, to.value, result.reason)

        prev = self._current
        self._current = to
        self._history.append({
            "from": prev.value,
            "to": to.value,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
        log.info("Pipeline advanced: %s → %s", prev.value, to.value)
        return GateResult(passed=True, warnings=all_warnings)

    def reject(self, back_to: SDDStage) -> None:
        current_idx = _STAGE_ORDER.index(self._current)
        target_idx = _STAGE_ORDER.index(back_to)
        if target_idx >= current_idx:
            raise InvalidStageTransitionError(
                f"Cannot reject to {back_to.value} — must be a previous stage"
            )
        prev = self._current
        self._current = back_to
        self._history.append({
            "from": prev.value,
            "to": back_to.value,
            "type": "reject",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

    def get_history(self) -> list[dict[str, str]]:
        return list(self._history)
