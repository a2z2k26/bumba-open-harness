"""Migrate flat expertise files to the frontmatter+sections format expected by expertise_loader.py.

Usage:
    python -m scripts.fix_expertise_frontmatter --dry-run
    python -m scripts.fix_expertise_frontmatter --apply
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import yaml

log = logging.getLogger(__name__)

REQUIRED_SECTIONS = (
    "## Domain Patterns",
    "## Known Risks",
    "## Decision Log",
    "## Cross-Agent Notes",
)

# Map legacy section headers to the required ones (best-effort preservation)
SECTION_MIGRATION_MAP = {
    "## Recurring Patterns": "## Domain Patterns",
    "## Project-Specific Notes": "## Domain Patterns",
    "## Historical Decisions": "## Decision Log",
    "## Risks": "## Known Risks",
    "## Notes": "## Cross-Agent Notes",
}


def infer_agent_zone_department(
    filename: str, teams_dir: Path
) -> tuple[str, int, str]:
    """Infer agent name, zone, and department by scanning team YAML files.

    The agent name is the filename minus ``.md``. Zone and department come from
    the team YAML that references the expertise file.
    """
    agent = filename.removesuffix(".md")
    for team_yaml in sorted(teams_dir.glob("*.yaml")):
        try:
            data = yaml.safe_load(team_yaml.read_text())
        except yaml.YAMLError:
            continue
        team = data.get("team", {})
        zone = int(team.get("zone", 4))
        dept = team.get("name", team_yaml.stem)

        chief = data.get("chief", {})
        if chief.get("name") == agent:
            return agent, zone, dept

        for worker in data.get("workers", []) or []:
            if worker.get("name") == agent:
                return agent, zone, dept

    # Fallback: default to zone 4 and derive department from filename prefix
    if "-" in agent:
        dept = agent.split("-", 1)[0]
    else:
        dept = "unknown"
    return agent, 4, dept


def build_frontmatter(agent: str, zone: int, department: str, type_: str) -> str:
    return (
        f"---\n"
        f"agent: {agent}\n"
        f"zone: {zone}\n"
        f"department: {department}\n"
        f"type: {type_}\n"
        f"max_lines: 500\n"
        f"schema_version: 1\n"
        f"---\n"
    )


def _has_frontmatter(content: str) -> bool:
    return content.lstrip().startswith("---\n")


def _extract_existing_body(content: str) -> str:
    """Strip existing frontmatter if present, return the body."""
    stripped = content.lstrip()
    if not stripped.startswith("---\n"):
        return content
    end = stripped.find("\n---\n", 4)
    if end == -1:
        return content
    return stripped[end + 5:]


def _migrate_sections(body: str) -> str:
    """Rename legacy section headers to required ones."""
    for old, new in SECTION_MIGRATION_MAP.items():
        body = body.replace(old, new)
    return body


def _ensure_required_sections(body: str) -> str:
    """Append any missing required sections at the end."""
    lines = body.rstrip().split("\n")
    present = set()
    for line in lines:
        stripped = line.strip()
        if stripped in REQUIRED_SECTIONS:
            present.add(stripped)

    missing = [s for s in REQUIRED_SECTIONS if s not in present]
    if missing:
        lines.append("")
        for section in missing:
            lines.append(section)
            lines.append("")

    return "\n".join(lines) + "\n"


def migrate_file(path: Path, teams_dir: Path) -> None:
    """Migrate a single expertise file in place. Idempotent."""
    content = path.read_text()

    if _has_frontmatter(content):
        has_all = all(section in content for section in REQUIRED_SECTIONS)
        if has_all:
            return  # Already valid

    agent, zone, department = infer_agent_zone_department(path.name, teams_dir)
    body = _extract_existing_body(content) if _has_frontmatter(content) else content
    body = _migrate_sections(body)
    body = _ensure_required_sections(body)

    frontmatter = build_frontmatter(agent, zone, department, type_="updatable")
    new_content = frontmatter + "\n" + body.lstrip("\n")
    path.write_text(new_content)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Migrate expertise files to frontmatter+sections format"
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument(
        "--expertise-dir",
        type=Path,
        default=Path("config/expertise"),
    )
    parser.add_argument(
        "--teams-dir",
        type=Path,
        default=Path("config/teams"),
    )
    args = parser.parse_args()

    if not args.dry_run and not args.apply:
        parser.error("Specify --dry-run or --apply")

    expertise_files = sorted(args.expertise_dir.glob("*.md"))
    log.info("Found %d expertise files in %s", len(expertise_files), args.expertise_dir)

    for f in expertise_files:
        if f.name.upper() == "README.MD":
            continue
        if args.dry_run:
            print(f"Would migrate: {f}")
        else:
            migrate_file(f, args.teams_dir)
            print(f"Migrated: {f}")

    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    sys.exit(main())
