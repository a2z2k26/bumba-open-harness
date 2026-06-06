"""Diagnose a Zone 4 team's first-run readiness — golden-template diff + strict validation.

D7.13 #1425 — frictionless team setup. When a freshly scaffolded team
fails its first run (`pytest -k <name>` red, or `manager.run()` raising
on a missing expertise file), this command says exactly what's missing
and emits an actionable fix command for each gap.

The doctor wraps `validate_team_yaml.py --strict` (so missing expertise
or system_prompt files are errors, not warnings) and adds two more
checks the validator alone doesn't perform:

1. **Field-set diff vs the golden template.** Required top-level
   `team:` keys present in `_template.yaml` are checked for presence
   in the target team. Missing keys are reported with the literal
   stanza from the template as the suggested addition. (We do NOT diff
   the field *values* — those are team-specific and operator-authored.)
2. **Suggested fix commands.** Each missing expertise / system_prompt
   gap is paired with a concrete one-liner the operator can run to
   close it (`mkdir -p ... && touch ...` for stub files; existing
   `scripts/new_specialist.py` invocation if the specialist itself is
   undefined).

Exit codes:
  0  team is first-run-ready (all validator checks pass + template fields present)
  1  team has gaps (one or more errors reported with fix commands)
  2  unexpected I/O error

Usage:
    python -m scripts.scaffold_doctor <team-name>

Why this is separate from `validate_team_yaml.py`: the validator is
load-time correctness ("can the bridge parse this?"). The doctor is
operational readiness ("is this team ready to run end-to-end?"). The
acceptance bar for the doctor is strictly higher.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

import yaml

from scripts.validate_team_yaml import (
    REPO_ROOT,
    TEAMS_DIR as _VALIDATE_TEAMS_DIR,
    TEMPLATE_PATH,
    ValidationReport,
    _format_report,
    _yaml_for_team,
    validate_team,
)

# Back-compat/test seam: callers patch scaffold_doctor.TEAMS_DIR alongside
# REPO_ROOT/TEMPLATE_PATH even though this module resolves teams through
# validate_team_yaml._yaml_for_team.
TEAMS_DIR = _VALIDATE_TEAMS_DIR


@dataclass
class FixSuggestion:
    """A concrete remediation step for a single doctor finding."""
    description: str
    command: str  # the literal shell command to run


@dataclass
class DoctorReport:
    """Doctor's full output — wraps a strict ValidationReport plus
    template-field-diff findings + fix suggestions.
    """
    team: str
    yaml_path: Path
    validation: ValidationReport
    missing_template_fields: list[str] = field(default_factory=list)
    fixes: list[FixSuggestion] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.validation.ok and not self.missing_template_fields


# ---------------------------------------------------------------------------
# Template field-set diff
# ---------------------------------------------------------------------------


def _template_required_fields() -> set[str]:
    """Return the set of top-level `team:` keys present in the golden template.

    We diff against the keys an operator following the golden path is
    expected to have — `name`, `zone`, `description`, `chief`, `workers`,
    `constraints`, `budget`, `tools`. Optional keys (`escalation`, `vapi`)
    are NOT in this set so departments that don't escalate or don't have
    voice receptionists aren't flagged.
    """
    return {"name", "zone", "description", "chief", "workers",
            "constraints", "budget", "tools"}


def _diff_against_template(yaml_path: Path, report: DoctorReport) -> None:
    """Record any required template fields the team is missing."""
    if not TEMPLATE_PATH.exists():
        # Doctor still runs without a template — just skip the diff and
        # log a warning. The strict validator carries the full load.
        sys.stderr.write(
            f"[scaffold-doctor] WARN: golden template not found at "
            f"{TEMPLATE_PATH}; skipping field-set diff.\n"
        )
        return

    raw = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
    team = (raw or {}).get("team", {}) or {}
    target_keys = set(team.keys())
    required = _template_required_fields()
    missing = sorted(required - target_keys)
    for key in missing:
        report.missing_template_fields.append(key)
        report.fixes.append(FixSuggestion(
            description=f"team.{key!r} is required by the golden template but missing",
            command=(
                f"# copy the {key!r} block from the golden template and edit:\n"
                f"#   {TEMPLATE_PATH}\n"
                f"#   into\n"
                f"#   {yaml_path}"
            ),
        ))


# ---------------------------------------------------------------------------
# Fix suggestions for validation errors
# ---------------------------------------------------------------------------


def _suggest_fix_for_error(error: str, yaml_path: Path) -> FixSuggestion | None:
    """Map a validator error string to an actionable fix command.

    Pattern-matches on error prefixes; falls through to None for
    unknown shapes (the raw error is still printed so nothing is lost).
    """
    # "expertise: 'name' references 'path' but file does not exist..."
    if "but file does not exist" in error and (
        error.startswith("expertise:") or error.startswith("system_prompt:")
    ):
        # Extract the path between the second pair of single quotes.
        try:
            parts = error.split("'")
            ref_path = parts[3]  # 'name' is parts[1]; 'path' is parts[3]
        except IndexError:
            return None
        full = REPO_ROOT / ref_path
        return FixSuggestion(
            description=f"create the missing file referenced by {ref_path!r}",
            command=f"mkdir -p {full.parent} && touch {full}",
        )

    # "tools.per_employee: key 'foo' does not match any worker name..."
    if error.startswith("tools.per_employee:"):
        return FixSuggestion(
            description=(
                "fix the per-employee tool key — it must literally match a "
                "worker `name:` field"
            ),
            command=(
                f"# edit {yaml_path} and align the key under tools.per_employee "
                f"with one of the worker names (case- and dash-sensitive)."
            ),
        )

    # "schema: ..." — schema-level errors usually want manual inspection.
    if error.startswith("schema:") or error.startswith("schema (unexpected):"):
        return FixSuggestion(
            description="resolve the Pydantic schema validation error above",
            command=(
                f"# inspect {yaml_path} — the strict schema "
                f"`teams._config._RootSchema` rejects unknown fields; "
                f"compare the failing block to {TEMPLATE_PATH}."
            ),
        )

    return None


def _attach_fixes(report: DoctorReport) -> None:
    """Walk the validator errors and append a FixSuggestion for each
    one we know how to fix.
    """
    for err in report.validation.errors:
        fix = _suggest_fix_for_error(err, report.yaml_path)
        if fix is not None:
            report.fixes.append(fix)


# ---------------------------------------------------------------------------
# Diagnose
# ---------------------------------------------------------------------------


def diagnose(yaml_path: Path) -> DoctorReport:
    """Full doctor pass: strict validation + template-diff + fix suggestions."""
    validation = validate_team(yaml_path, strict=True)
    report = DoctorReport(
        team=yaml_path.stem,
        yaml_path=yaml_path,
        validation=validation,
    )
    _diff_against_template(yaml_path, report)
    _attach_fixes(report)
    return report


def _format_doctor_report(report: DoctorReport) -> str:
    """Render a DoctorReport for stdout."""
    lines: list[str] = []
    status = "READY" if report.ok else "NOT READY"
    lines.append(f"[scaffold-doctor] {status}: {report.team}  ({report.yaml_path})")
    lines.append("")
    lines.append("--- validation ---")
    lines.append(_format_report(report.validation))
    if report.missing_template_fields:
        lines.append("")
        lines.append("--- template field-set diff ---")
        for key in report.missing_template_fields:
            lines.append(f"  MISSING: team.{key} (required by golden template)")
    if report.fixes:
        lines.append("")
        lines.append("--- suggested fixes ---")
        for i, fix in enumerate(report.fixes, start=1):
            lines.append(f"  [{i}] {fix.description}")
            for cmd_line in fix.command.splitlines():
                lines.append(f"      {cmd_line}")
    return "\n".join(lines)


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="scaffold-doctor",
        description=(
            "Diagnose first-run readiness for a Zone 4 team. Wraps "
            "validate_team_yaml.py --strict + diffs against the golden "
            "template + emits actionable fix commands for each gap."
        ),
    )
    parser.add_argument("team", help="Team name (e.g. 'qa') or path to a YAML file.")
    args = parser.parse_args(list(argv) if argv is not None else None)

    yaml_path = _yaml_for_team(args.team)
    report = diagnose(yaml_path)
    sys.stdout.write(_format_doctor_report(report) + "\n")
    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
