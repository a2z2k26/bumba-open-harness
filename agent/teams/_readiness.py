"""Deterministic department readiness responses."""

from __future__ import annotations

import re
from collections import Counter

from teams._types import AgentSpec, DepartmentConfig, TeamResult


_READY_RE = re.compile(
    r"^(ready|ready to work|are you ready|are you ready to work|status|online|are you online)\??$",
    re.IGNORECASE,
)
_MAX_READINESS_PROMPT_CHARS = 48


def is_readiness_prompt(task: str) -> bool:
    """Return True only for short, exact readiness/status prompts."""
    normalized = " ".join(task.strip().split())
    if not normalized or len(normalized) > _MAX_READINESS_PROMPT_CHARS:
        return False
    return bool(_READY_RE.fullmatch(normalized))


def _model_family(model: str) -> str:
    if ":" not in model:
        return model or "unknown"
    return model.split(":", 1)[0]


def _format_counts(counts: Counter[str]) -> str:
    return ", ".join(
        f"{family}={count}"
        for family, count in sorted(counts.items())
    )


def _model_family_summary(config: DepartmentConfig) -> str:
    specs: tuple[AgentSpec, ...] = (config.manager, *config.employees)
    primary_counts = Counter(_model_family(spec.model) for spec in specs)
    fallback_counts = Counter(
        _model_family(spec.fallback_model)
        for spec in specs
        if spec.fallback_model
    )

    summary = _format_counts(primary_counts)
    if fallback_counts:
        summary = f"{summary}; fallbacks: {_format_counts(fallback_counts)}"
    return summary


def _warm_idle_label(config: DepartmentConfig) -> str:
    warm_idle = config.constraints.warm_idle_timeout_seconds
    if warm_idle is None:
        return "global default"
    return f"{warm_idle}s"


def render_readiness(config: DepartmentConfig) -> TeamResult:
    """Render readiness from config only, without invoking the team runtime."""
    display_name = config.name.replace("_", " ").title()
    lines = [
        "Ready.",
        "Deterministic readiness status; no chief or specialist model run was executed.",
        "",
        f"{display_name} department is online.",
        f"Chief: {config.manager.name} ({config.manager.model})",
        f"Specialists on roster: {len(config.employees)}",
        f"Delegation floor: {config.constraints.expected_min_specialists}",
        f"Warm idle: {_warm_idle_label(config)}",
        f"Timeout: {config.constraints.timeout_seconds}s",
        f"Model families: {_model_family_summary(config)}",
        "Known surface blockers: none for readiness; surface store is not used.",
    ]
    return TeamResult(
        department=config.name,
        manager_output="\n".join(lines),
        success=True,
        error=None,
        duration_seconds=0.0,
    )

