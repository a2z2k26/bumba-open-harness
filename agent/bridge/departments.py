"""MS4.9 + MS4.10 — Department Registry.

Department structure for multi-persona agent operations: Engineering,
Data/Analytics, QA, and Ops.  Each department has a lead persona, skills,
and routing keywords for automatic department detection.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from bridge.dispatch_metrics import increment_module_counter

log = logging.getLogger(__name__)


@dataclass
class Department:
    """A department with lead persona and associated skills."""

    name: str
    display_name: str
    persona: str | None = None  # path relative to config/agents/
    skills: list[str] = field(default_factory=list)
    description: str = ""
    status: str = "active"  # active | inactive
    routing_keywords: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Department registry
# ---------------------------------------------------------------------------

DEPARTMENTS: dict[str, Department] = {
    "engineering": Department(
        name="engineering",
        display_name="Engineering",
        persona=None,  # Default persona
        skills=["code-review", "validate"],
        description="Core development, code review, and validation",
        routing_keywords=["code", "implement", "refactor", "build", "develop", "function", "class"],
    ),
    "data": Department(
        name="data",
        display_name="Data & Analytics",
        persona="data-analyst",
        skills=["data-analysis"],
        description="Data analysis, visualization, and insights via DuckDB",
        routing_keywords=["analyze", "data", "csv", "chart", "visualization", "metrics", "query", "sql"],
    ),
    "qa": Department(
        name="qa",
        display_name="Quality Assurance",
        persona="qa-engineer",
        skills=["qa-testing", "load-testing"],
        description="Test planning, test generation, coverage analysis, load testing",
        routing_keywords=["test", "coverage", "regression", "quality", "pytest", "load test"],
    ),
    "ops": Department(
        name="ops",
        display_name="Operations",
        persona="ops-engineer",
        skills=["monitoring"],
        description="Infrastructure monitoring, deployment health, incident response",
        routing_keywords=["deploy", "infra", "monitor", "health", "disk", "memory", "cpu", "incident"],
    ),
}


def get_department(name: str) -> Department | None:
    """Get a department by name."""
    return DEPARTMENTS.get(name.lower())


def list_departments(include_inactive: bool = False) -> list[Department]:
    """List all departments."""
    deps = list(DEPARTMENTS.values())
    if not include_inactive:
        deps = [d for d in deps if d.status == "active"]
    return deps


def detect_department(message: str, metrics: object | None = None) -> str | None:
    increment_module_counter("departments.detect_department", tier=1)
    """Detect which department a message is best suited for.

    Returns department name or None if no clear match.
    Increments the ``department_detections`` counter on successful detection (#22).
    """
    msg_lower = message.lower()
    best_match: str | None = None
    best_score = 0

    for name, dept in DEPARTMENTS.items():
        score = sum(1 for kw in dept.routing_keywords if kw in msg_lower)
        if score > best_score:
            best_score = score
            best_match = name

    result = best_match if best_score > 0 else None
    # Increment detection counter when a department is confidently identified (#22)
    if result is not None and metrics is not None:
        try:
            from .metrics import DEPARTMENT_DETECTIONS
            metrics.increment(DEPARTMENT_DETECTIONS)
        except Exception:
            pass
    return result


def format_departments_table() -> str:
    """Format all departments as a markdown table."""
    lines = [
        "| Department | Lead Persona | Skills | Status |",
        "|------------|-------------|--------|--------|",
    ]
    for dept in list_departments(include_inactive=True):
        persona = dept.persona or "(default)"
        skills = ", ".join(dept.skills) if dept.skills else "none"
        lines.append(f"| {dept.display_name} | {persona} | {skills} | {dept.status} |")
    return "\n".join(lines)


def format_department_detail(name: str) -> str | None:
    """Format detailed view for a single department."""
    dept = get_department(name)
    if not dept:
        return None

    lines = [
        f"# {dept.display_name}",
        f"**Status**: {dept.status}",
        f"**Lead Persona**: {dept.persona or '(default)'}",
        f"**Description**: {dept.description}",
        "",
        "## Skills",
    ]
    for skill in dept.skills:
        lines.append(f"- {skill}")

    lines.extend(["", "## Routing Keywords"])
    lines.append(", ".join(dept.routing_keywords))

    return "\n".join(lines)


def get_persona_for_task(message: str) -> str | None:
    """Get the recommended persona for a task message.

    Returns persona filename (e.g., 'data-analyst') or None for default.
    """
    dept_name = detect_department(message)
    if dept_name:
        dept = DEPARTMENTS[dept_name]
        return dept.persona
    return None
