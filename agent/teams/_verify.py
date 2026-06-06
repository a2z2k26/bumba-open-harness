"""Output verification gates for Zone 4 department results (sprint B2.3 + 04.15).

``verify_team_result`` applies 8 deterministic checks to a ``TeamResult``
before it is returned to the caller. Each failing check appends a
human-readable violation message. An empty list means all gates passed.

Gates
-----
1. Non-empty output       — manager_output must be non-empty
2. No error keywords      — output must not contain sentinel failure strings
3. Structured output valid — if structured is present, TeamOutput must parse cleanly
4. Cost within budget     — total_cost_usd <= config.constraints.cost_limit_usd
5. Duration within limit  — duration_seconds <= config.constraints.timeout_seconds
6. Specialist count cap   — len(employee_results) <= len(config.employees)
7. No hallucination markers — output must not contain known LLM refusal/hallucination strings
8. Specialist count floor — len(employee_results) >= constraints.expected_min_specialists
                              (sprint 04.15; default 0 disables; real depts opt in)

Drift mitigation (Z4-S00 #1384)
-------------------------------
This gate list is mirrored in the operator-facing playbook at
``docs/zone4/team-playbook.md`` Section 6. When you add Gate 9 (or change
any existing gate's semantics), update both files in the same PR. The
playbook carries a ``<!-- last-verified: YYYY-MM-DD -->`` header so
drift between this file and the playbook is auditable.
"""

from __future__ import annotations

import logging

from teams._types import DepartmentConfig, TeamOutput, TeamResult

log = logging.getLogger(__name__)

# Gate 2: error keywords that indicate a silent tool failure propagating into output
_ERROR_KEYWORDS: frozenset[str] = frozenset({
    "traceback (most recent call last)",
    "exception:",
    "error:",
    "runtimeerror",
    "attributeerror",
    "keyerror",
    "valueerror",
    "typeerror",
})

# Gate 7: hallucination / refusal markers
_HALLUCINATION_MARKERS: frozenset[str] = frozenset({
    "as an ai language model",
    "i cannot assist",
    "i'm unable to assist",
    "i am unable to assist",
    "i do not have the ability",
    "i cannot provide",
    "i'm not able to provide",
    "i am not able to provide",
    "[placeholder]",
    "[insert",
    "lorem ipsum",
})


def verify_team_result(
    result: TeamResult,
    config: DepartmentConfig,
) -> list[str]:
    """Apply 7 output gates to *result* and return a list of violation messages.

    Returns an empty list if all gates pass (the happy path).

    This function is pure (no I/O, no side effects) so it is trivially
    testable and safe to call from any context.
    """
    violations: list[str] = []
    output_lower = result.manager_output.lower()

    # Gate 1 — non-empty output
    if not result.manager_output.strip():
        violations.append(
            "Gate 1 FAIL: manager_output is empty — no answer was produced"
        )

    # Gate 2 — no error keywords
    for kw in _ERROR_KEYWORDS:
        if kw in output_lower:
            violations.append(
                f"Gate 2 FAIL: error keyword {kw!r} found in manager_output"
            )
            break  # one violation per gate is sufficient

    # Gate 3 — structured output valid
    if result.structured is not None:
        if not isinstance(result.structured, TeamOutput):
            violations.append(
                "Gate 3 FAIL: result.structured is set but is not a TeamOutput instance"
            )
        elif not result.structured.answer.strip():
            violations.append(
                "Gate 3 FAIL: result.structured.answer is empty"
            )

    # Gate 4 — cost within budget
    limit = config.constraints.cost_limit_usd
    if result.total_cost_usd > limit:
        violations.append(
            f"Gate 4 FAIL: total_cost_usd={result.total_cost_usd:.4f} exceeds "
            f"limit={limit:.4f}"
        )

    # Gate 5 — duration within timeout
    timeout = config.constraints.timeout_seconds
    if result.duration_seconds > timeout:
        violations.append(
            f"Gate 5 FAIL: duration_seconds={result.duration_seconds:.1f} exceeds "
            f"timeout={timeout}s"
        )

    # Gate 6 — specialist count does not exceed configured employee count
    max_specialists = len(config.employees)
    actual_specialists = len(result.employee_results)
    if actual_specialists > max_specialists:
        violations.append(
            f"Gate 6 FAIL: employee_results has {actual_specialists} entries but "
            f"config only defines {max_specialists} employees"
        )

    # Gate 7 — no hallucination markers
    for marker in _HALLUCINATION_MARKERS:
        if marker in output_lower:
            violations.append(
                f"Gate 7 FAIL: hallucination/refusal marker {marker!r} found in output"
            )
            break

    # Gate 8 (sprint 04.15) — minimum specialist count floor.
    # Default Constraints.expected_min_specialists=0 disables this gate so
    # existing direct-answer tests stay green; real production department
    # YAMLs opt in by setting expected_min_specialists to a positive integer
    # (commonly len(employees) for strict delegation enforcement).
    expected_min = config.constraints.expected_min_specialists
    if expected_min > 0 and actual_specialists < expected_min:
        violations.append(
            f"Gate 8 FAIL: employee_results has {actual_specialists} entries but "
            f"expected at least {expected_min} (per-department minimum-specialist "
            f"floor)"
        )

    if violations:
        log.warning(
            "verify_team_result.violations department=%s count=%d",
            result.department,
            len(violations),
        )

    return violations
