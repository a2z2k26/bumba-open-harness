"""new_skill.py — scaffold a new Claude Code skill manifest.

D7.5 finding F-FS: pairs with scaffold_zone4.py — frictionless setup is
the future-state goal. D7.13 (#1425) layers the golden path + validator
+ doctor on top of these scaffolders.


E4.7 (#1253). Mirrors D3.1's new-specialist pattern for the skill family.
E4.8 (#1254). Adds --assignment flag (main | global | <team_name>).

Usage (via skill manifest):
    python3 -m scripts.new_skill <name> --description "..." [--directory]

Usage (direct):
    python3 agent/scripts/new_skill.py <name> --description "..."
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SKILLS_DIR = REPO_ROOT / "agent" / "config" / "skills"
TEAMS_DIR = REPO_ROOT / "agent" / "config" / "teams"
CHECKLIST_DIR = REPO_ROOT / "agent" / "data" / "scaffolding"

_RESERVED_ASSIGNMENTS = {"main", "global"}


def _valid_assignments() -> set[str]:
    """Return the set of valid assignment values: reserved + all team YAML stems."""
    team_names = {p.stem for p in TEAMS_DIR.glob("*.yaml")} if TEAMS_DIR.is_dir() else set()
    return _RESERVED_ASSIGNMENTS | team_names


def _validate_assignment(value: str) -> str:
    valid = _valid_assignments()
    if value not in valid:
        _abort(
            f"--assignment '{value}' not recognised; "
            f"valid values: {sorted(valid)}"
        )
    return value


def _abort(msg: str) -> None:
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(1)


def _target_path(name: str, directory_form: bool) -> Path:
    if directory_form:
        return SKILLS_DIR / name / "SKILL.md"
    return SKILLS_DIR / f"{name}.md"


def _check_collision(name: str) -> None:
    """Abort if a standalone .md or a directory-form entry already exists."""
    if (SKILLS_DIR / f"{name}.md").exists():
        _abort(f"skill '{name}' already exists at agent/config/skills/{name}.md")
    if (SKILLS_DIR / name).is_dir():
        _abort(f"skill '{name}' already exists at agent/config/skills/{name}/")


def _validate_frontmatter(content: str, name: str) -> None:
    """Parse and validate the generated frontmatter via _SkillFrontmatterSchema."""
    from scripts._scaffolding_templates import _SkillFrontmatterSchema

    lines = content.splitlines()
    if not lines or lines[0].strip() != "---":
        _abort(f"generated skill for '{name}' has no frontmatter block")

    fm_lines: list[str] = []
    for line in lines[1:]:
        if line.strip() == "---":
            break
        fm_lines.append(line)

    import yaml
    from pydantic import ValidationError

    try:
        raw = yaml.safe_load("\n".join(fm_lines)) or {}
    except Exception as exc:
        _abort(f"generated frontmatter YAML parse error: {exc}")

    try:
        _SkillFrontmatterSchema.model_validate(raw)
    except ValidationError as exc:
        _abort(f"generated frontmatter failed validation: {exc}")


def _print_checklist(name: str, target: Path) -> None:
    checklist = (
        f"# {name} — skill scaffolding checklist\n\n"
        f"Scaffolded to: {target}\n\n"
        "## Before merging\n\n"
        "- [ ] Replace 'When to use' stub with real trigger conditions\n"
        "- [ ] Replace 'What it does' steps with accurate behavior\n"
        "- [ ] Add at least one example\n"
        "- [ ] Update `allowed-tools` to exactly what this skill needs\n"
        "- [ ] Update `description` to 30+ characters (audit_skill_frontmatter.py gate)\n"
        "- [ ] Run `python3 agent/scripts/audit_skill_frontmatter.py` on the new file\n"
    )
    print(checklist)

    CHECKLIST_DIR.mkdir(parents=True, exist_ok=True)
    out = CHECKLIST_DIR / f"{name}-skill-checklist.md"
    out.write_text(checklist, encoding="utf-8")
    print(f"Checklist saved to: {out.relative_to(REPO_ROOT)}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="new_skill",
        description="Scaffold a new Claude Code skill manifest.",
    )
    parser.add_argument("name", help="Skill name (kebab-case, e.g. my-skill)")
    parser.add_argument(
        "--description",
        default="<one-line description — at least 30 chars>",
        help="Short description for the frontmatter",
    )
    parser.add_argument(
        "--directory",
        action="store_true",
        help="Use directory form (agent/config/skills/<name>/SKILL.md) instead of standalone",
    )
    parser.add_argument(
        "--assignment",
        default="main",
        help="Scope: main (default) | global | <team_name>",
    )
    args = parser.parse_args(argv)

    name: str = args.name
    description: str = args.description
    directory_form: bool = args.directory
    assignment: str = _validate_assignment(args.assignment)

    _check_collision(name)

    from scripts._scaffolding_templates import SKILL_BUNDLE

    result = SKILL_BUNDLE.render(
        name=name,
        description=description,
        directory_form=directory_form,
        assignment=assignment,
    )

    if not result.files:
        _abort("bundle rendered no files")

    _, content = result.files[0]
    target = _target_path(name, directory_form)

    _validate_frontmatter(content, name)

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")

    try:
        rel = target.relative_to(REPO_ROOT)
    except ValueError:
        rel = target
    print(f"Scaffolded: {rel}")
    _print_checklist(name, rel)

    return 0


if __name__ == "__main__":
    sys.exit(main())
