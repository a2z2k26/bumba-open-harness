#!/usr/bin/env python3
"""Batch inject ## Gotchas sections into the top-20 priority SKILL.md files.

Usage:
    python scripts/inject_gotchas.py [--db PATH] [--skills-dir PATH] [--dry-run]

Reads failure pattern data via SkillEvolutionEngine.generate_gotchas() and
appends a ## Gotchas section to each SKILL.md that has recorded failures.
Existing ## Gotchas sections are replaced (not duplicated).

Exits 0 on success.  Non-zero if any file write fails.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

# Allow running from repo root
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bridge.skill_evolution import SkillEvolutionEngine  # noqa: E402

# Priority skills — ranked by operational importance.
# The script processes these first, then fills remaining slots from the skills
# directory up to 20 total.
PRIORITY_SKILLS = [
    "webapp-testing",
    "system-health-check",
    "error-diagnosis",
    "log-analysis",
    "hook-development",
    "command-development",
    "async-python-patterns",
    "architecture-patterns",
    "code-review-excellence",
    "debugging-strategies",
    "error-handling-patterns",
    "audit-review",
    "operator-communication",
    "using-superpowers",
    "mcp-integration",
    "git-advanced-workflows",
    "nodejs-backend-patterns",
    "fastapi-templates",
    "sql-optimization-patterns",
    "prompt-engineering-patterns",
]

TARGET_COUNT = 20

# Regex to find an existing ## Gotchas section (greedy to end of section)
_GOTCHAS_RE = re.compile(
    r"^## Gotchas\n.*?(?=\n## |\Z)",
    re.MULTILINE | re.DOTALL,
)

# Regex to find ## References (insertion point)
_REFERENCES_RE = re.compile(r"^## References", re.MULTILINE)


def _find_skill_md(skills_dir: Path, skill_name: str) -> Path | None:
    """Locate SKILL.md for a given skill name."""
    candidate = skills_dir / skill_name / "SKILL.md"
    if candidate.exists():
        return candidate
    return None


def _inject_gotchas(content: str, gotchas: str) -> str:
    """Inject or replace ## Gotchas in SKILL.md content.

    Insertion order:
    1. Replace existing ## Gotchas section if present.
    2. Insert before ## References if that section exists.
    3. Append at end of file.
    """
    # Strip trailing whitespace from gotchas
    gotchas = gotchas.rstrip()

    # Case 1: replace existing
    if _GOTCHAS_RE.search(content):
        return _GOTCHAS_RE.sub(gotchas, content, count=1)

    # Case 2: insert before ## References
    m = _REFERENCES_RE.search(content)
    if m:
        return content[: m.start()] + gotchas + "\n\n" + content[m.start() :]

    # Case 3: append
    if not content.endswith("\n"):
        content += "\n"
    return content + "\n" + gotchas + "\n"


def _validate_frontmatter(content: str) -> bool:
    """Check that YAML frontmatter is intact (starts and ends with ---)."""
    if not content.startswith("---"):
        return True  # no frontmatter to corrupt
    parts = content.split("---", 2)
    return len(parts) >= 3


def main() -> int:
    parser = argparse.ArgumentParser(description="Inject gotchas into SKILL.md files")
    parser.add_argument(
        "--db",
        default=str(Path.home() / "data" / "memory.db"),
        help="Path to failure patterns database (default: ~/data/memory.db)",
    )
    parser.add_argument(
        "--skills-dir",
        default=str(Path(__file__).resolve().parent.parent / "config" / "claude-files" / "skills"),
        help="Path to skills directory",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be done without writing files",
    )
    args = parser.parse_args()

    skills_dir = Path(args.skills_dir)
    if not skills_dir.is_dir():
        print(f"ERROR: Skills directory not found: {skills_dir}", file=sys.stderr)
        return 1

    engine = SkillEvolutionEngine(db_path=args.db)

    # Build target list: priority skills first, then fill from directory
    targets: list[str] = []
    seen: set[str] = set()

    for name in PRIORITY_SKILLS:
        if _find_skill_md(skills_dir, name):
            targets.append(name)
            seen.add(name)
        if len(targets) >= TARGET_COUNT:
            break

    # Fill remaining slots from directory (alphabetical)
    if len(targets) < TARGET_COUNT:
        for entry in sorted(skills_dir.iterdir()):
            if entry.is_dir() and entry.name not in seen:
                if (entry / "SKILL.md").exists():
                    targets.append(entry.name)
                    seen.add(entry.name)
                    if len(targets) >= TARGET_COUNT:
                        break

    injected = 0
    skipped = 0
    errors = 0

    for skill_name in targets:
        skill_md = _find_skill_md(skills_dir, skill_name)
        if not skill_md:
            continue

        gotchas = engine.generate_gotchas(skill_name)
        if not gotchas:
            skipped += 1
            if args.dry_run:
                print(f"  SKIP {skill_name}: no failure data")
            continue

        original = skill_md.read_text()
        updated = _inject_gotchas(original, gotchas)

        if not _validate_frontmatter(updated):
            print(f"  ERROR {skill_name}: frontmatter corrupted, skipping", file=sys.stderr)
            errors += 1
            continue

        if args.dry_run:
            print(f"  WOULD INJECT {skill_name}: {gotchas.count(chr(10))} lines")
        else:
            try:
                skill_md.write_text(updated)
                injected += 1
                print(f"  INJECTED {skill_name}")
            except OSError as e:
                print(f"  ERROR {skill_name}: {e}", file=sys.stderr)
                errors += 1

    print(f"\nDone: {injected} injected, {skipped} skipped (no data), {errors} errors")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
