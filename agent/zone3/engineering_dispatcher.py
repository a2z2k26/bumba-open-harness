"""Z3-03 — Zone 3 engineering dispatcher.

A pure-decision + executor-call object. It never reaches the Zone 4 PydanticAI
``DepartmentRegistry``; engineering stays Zone 3. Responsibilities:

  - readiness asks → deterministic roster, zero Claude calls;
  - substantive tasks → select one specialist, build a prompt, call the
    injected executor;
  - QA/Ops/Design/Strategy needs → a *structured* cross-zone handoff result,
    never a silent Zone 4 invocation.

The executor is injected (duck-typed ``.run(...)``) so the dispatcher is unit
testable with a fake and never spawns real Claude in CI. Prompt assembly is a
seam (``prompt_builder``) so Z3-04 can layer governance without touching this
file.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from zone3.claude_p_executor import EngineeringRunResult
from zone3.engineering_config import EngineeringSpecialist, EngineeringTeamConfig


# Readiness intents — deterministic, lowercased substring/equality match.
_READINESS_TERMS = (
    "ready to work",
    "ready?",
    "are you ready",
    "status",
    "roster",
    "who is on the team",
    "who's on the team",
    "what can you do",
)
_READINESS_EXACT = ("ready", "status", "roster", "help")


class _ExecutorLike(Protocol):
    async def run(
        self,
        *,
        specialist: str,
        prompt: str,
        cwd: Path,
        timeout_seconds: int,
    ) -> EngineeringRunResult: ...


PromptBuilder = Callable[[EngineeringTeamConfig, EngineeringSpecialist, str], str]


@dataclass(frozen=True)
class CrossZoneHandoff:
    """A structured request to escalate work to another zone/department.

    Surfaced to the operator; the dispatcher does NOT invoke the target zone.
    """

    target_zone: int
    department: str
    reason: str
    original_task: str


# --- readiness --------------------------------------------------------------


def is_engineering_readiness_prompt(task: str) -> bool:
    """Return True for deterministic roster/status asks (no Claude needed)."""
    text = task.strip().lower()
    if not text:
        return False
    if text.rstrip("?.! ") in _READINESS_EXACT:
        return True
    return any(term in text for term in _READINESS_TERMS)


def render_engineering_readiness(config: EngineeringTeamConfig) -> str:
    """Render a deterministic Zone 3 engineering roster + status."""
    lines = [
        f"Zone 3 engineering team — chief: {config.chief_name} "
        f"({config.chief.model})",
        f"Execution: {config.execution} | timeout: {config.timeout_seconds}s | "
        f"worktree required: {config.require_worktree} | "
        f"local CI required: {config.require_local_ci}",
        "Specialists:",
    ]
    for specialist in config.specialists:
        lines.append(f"  - {specialist.name}: {specialist.when_to_call}")
    return "\n".join(lines)


# --- specialist selection ---------------------------------------------------

# Keyword → specialist-name-fragment routing table. Checked in order; first
# match wins. Deterministic and offline.
_SELECTION_RULES: tuple[tuple[tuple[str, ...], str], ...] = (
    (("review", "diff", "bug-risk", "maintainab", "code quality"), "code-reviewer"),
    (("rest", "graphql", "openapi", "webhook", "endpoint", "auth boundary"), "api-engineer"),
    (("api boundary", "service boundary", "backend", "persistence", "async"), "backend-architect"),
    (("frontend", "ui", "accessibility", "browser", "client-side"), "frontend-developer"),
    (("schema", "migration", "query", "database", "transaction"), "database-specialist"),
    (("ci", "launchd", "deploy", "pipeline", "operational"), "devops-engineer"),
    (("profil", "performance", "load test", "hot-path", "regression"), "performance-engineer"),
    (("tdd", "red-green", "test design", "test discipline"), "tdd-orchestrator"),
    (("adr", "architecture drift", "boundary review", "design validation"), "architect-reviewer"),
    (("refactor", "dead-code", "dead code", "duplication", "cleanup"), "refactoring-specialist"),
)


def select_engineering_specialist(
    config: EngineeringTeamConfig,
    task: str,
) -> EngineeringSpecialist:
    """Pick one specialist deterministically from keyword rules.

    Falls back to ``engineering-backend-architect`` (or the first specialist)
    when nothing matches — never raises, never returns None.
    """
    text = task.lower()
    by_fragment = {
        fragment: specialist
        for specialist in config.specialists
        for fragment in (_name_fragment(specialist.name),)
    }
    for keywords, fragment in _SELECTION_RULES:
        if any(keyword in text for keyword in keywords):
            chosen = by_fragment.get(fragment)
            if chosen is not None:
                return chosen
    return by_fragment.get("backend-architect") or config.specialists[0]


def _name_fragment(name: str) -> str:
    """``engineering-code-reviewer`` -> ``code-reviewer``."""
    return name[len("engineering-") :] if name.startswith("engineering-") else name


# --- cross-zone handoff -----------------------------------------------------

# (keywords, target department). Ops requires an infra/deploy scope term to
# fire; otherwise the work stays inside engineering (engineering-devops handles
# CI/local validation in Zone 3).
_QA_TERMS = ("broader qa", "qa coverage", "qa team", "quality assurance", "manual testing")
_DESIGN_TERMS = ("design review", "visual design", "ux research", "interaction design")
_STRATEGY_TERMS = ("product strategy", "roadmap", "market research", "requirements gathering")
_OPS_TERMS = ("deploy risk", "production deploy", "infra", "infrastructure", "incident", "on-call")
_OPS_REQUIRED_SCOPE = ("infra", "infrastructure", "production", "deploy", "incident", "on-call")


def classify_cross_zone_handoff(task: str) -> CrossZoneHandoff | None:
    """Classify whether ``task`` needs another zone. Returns None to stay Z3."""
    text = task.lower()
    if any(term in text for term in _QA_TERMS):
        return CrossZoneHandoff(4, "qa", "task requests broader QA coverage", task)
    if any(term in text for term in _DESIGN_TERMS):
        return CrossZoneHandoff(4, "design", "task requests design work", task)
    if any(term in text for term in _STRATEGY_TERMS):
        return CrossZoneHandoff(4, "strategy", "task requests product strategy", task)
    if any(term in text for term in _OPS_TERMS) and any(
        scope in text for scope in _OPS_REQUIRED_SCOPE
    ):
        return CrossZoneHandoff(4, "ops", "task has infra/deploy scope", task)
    return None


def render_cross_zone_handoff(handoff: CrossZoneHandoff) -> str:
    return "\n".join(
        [
            f"Cross-zone handoff proposed (NOT auto-invoked): Zone "
            f"{handoff.target_zone} {handoff.department}.",
            f"Reason: {handoff.reason}.",
            f"Original task: {handoff.original_task}",
            "Engineering did not silently invoke another zone. Operator "
            "decides whether to route this.",
        ]
    )


# --- default prompt builder (Z3-04: governance-aware) -----------------------


def _default_prompt_builder(
    config: EngineeringTeamConfig,
    specialist: EngineeringSpecialist,
    task: str,
) -> str:
    """Assemble governance + base prompt + task (Z3-04).

    Falls back to base-prompt + task when no governance bundle exists, so the
    dispatcher stays usable before/while governance bundles are authored.
    """
    from zone3.engineering_prompts import build_engineering_prompt

    try:
        return build_engineering_prompt(config, specialist, task)
    except FileNotFoundError:
        base = (
            specialist.prompt.read_text(encoding="utf-8")
            if specialist.prompt.is_file()
            else ""
        )
        parts = [part for part in (base, f"Task:\n{task}") if part.strip()]
        return "\n\n---\n\n".join(parts)


class EngineeringDispatcher:
    """Routes a task to readiness, a specialist, or a cross-zone handoff."""

    def __init__(
        self,
        *,
        config: EngineeringTeamConfig,
        executor: _ExecutorLike,
        prompt_builder: PromptBuilder | None = None,
    ) -> None:
        self._config = config
        self._executor = executor
        self._prompt_builder = prompt_builder or _default_prompt_builder

    @property
    def config(self) -> EngineeringTeamConfig:
        return self._config

    @property
    def executor(self) -> _ExecutorLike:
        return self._executor

    async def route(self, task: str, *, cwd: Path) -> EngineeringRunResult:
        """Route a task. Readiness + handoff return without spawning Claude."""
        if is_engineering_readiness_prompt(task):
            return self._deterministic_result(
                specialist=self._config.chief_name,
                stdout=render_engineering_readiness(self._config),
            )

        handoff = classify_cross_zone_handoff(task)
        if handoff is not None:
            return self._deterministic_result(
                specialist=self._config.chief_name,
                stdout=render_cross_zone_handoff(handoff),
            )

        specialist = select_engineering_specialist(self._config, task)
        prompt = self._prompt_builder(self._config, specialist, task)
        return await self._executor.run(
            specialist=specialist.name,
            prompt=prompt,
            cwd=cwd,
            timeout_seconds=self._config.timeout_seconds,
        )

    def _deterministic_result(self, *, specialist: str, stdout: str) -> EngineeringRunResult:
        return EngineeringRunResult(
            specialist=specialist,
            success=True,
            stdout=stdout,
            stderr="",
            exit_code=0,
            duration_seconds=0.0,
        )


__all__ = [
    "CrossZoneHandoff",
    "EngineeringDispatcher",
    "PromptBuilder",
    "classify_cross_zone_handoff",
    "is_engineering_readiness_prompt",
    "render_cross_zone_handoff",
    "render_engineering_readiness",
    "select_engineering_specialist",
]
