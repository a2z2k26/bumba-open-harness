#!/usr/bin/env python3
"""Audit SKILL.md files for missing/vague frontmatter.

Usage:
    python3 scripts/audit_skill_frontmatter.py [--skills-dir PATH] [--output json|text]

Searches ~/.claude/skills/ (and optionally a custom path) for all SKILL.md files.
Checks required and recommended frontmatter fields and outputs a remediation report.

Exit codes:
    0 — All skills pass
    1 — One or more skills have issues
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

# Required fields: missing → error
REQUIRED_FIELDS = ["name", "description"]

# Recommended fields: missing → warning
RECOMMENDED_FIELDS = ["type", "theme", "best_for", "estimated_time"]

# Description shorter than this is considered vague
MIN_DESCRIPTION_LEN = 30

# Default skills search paths
DEFAULT_SKILLS_PATHS = [
    Path.home() / ".claude" / "skills",
    Path.home() / ".claude" / "plugins",
]


def parse_frontmatter(content: str) -> dict | None:
    """Parse YAML frontmatter between --- delimiters.

    Returns a dict of key/value pairs, or None if no frontmatter found.
    Only handles simple key: value lines (no nested YAML).
    """
    lines = content.splitlines()
    if not lines or lines[0].strip() != "---":
        return None

    fm_lines = []
    for line in lines[1:]:
        if line.strip() == "---":
            break
        fm_lines.append(line)
    else:
        # No closing ---
        return None

    fields: dict[str, str] = {}
    current_key = None
    for line in fm_lines:
        # Multi-line values (indented continuation)
        if current_key and line.startswith((" ", "\t")):
            fields[current_key] = fields[current_key] + " " + line.strip()
            continue
        if ":" in line:
            key, _, value = line.partition(":")
            key = key.strip()
            value = value.strip()
            if key:
                fields[key] = value
                current_key = key
    return fields


def has_gotchas_section(content: str) -> bool:
    """Check if the skill file has a ## Gotchas section."""
    return bool(re.search(r"^##\s+Gotchas", content, re.MULTILINE))


def audit_skill_file(path: Path) -> dict:
    """Audit a single SKILL.md file. Returns audit result dict."""
    result: dict = {
        "skill": str(path),
        "name": path.parent.name if path.parent != path else path.stem,
        "missing": [],
        "warnings": [],
        "passing": True,
    }

    try:
        content = path.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        result["missing"].append(f"unreadable: {e}")
        result["passing"] = False
        return result

    fm = parse_frontmatter(content)

    if fm is None:
        result["missing"].append("frontmatter (no --- delimiters found)")
        result["passing"] = False
        return result

    # Check required fields
    for field in REQUIRED_FIELDS:
        if not fm.get(field):
            result["missing"].append(field)

    # Check for vague description
    desc = fm.get("description", "")
    if desc and len(desc) < MIN_DESCRIPTION_LEN:
        result["warnings"].append(
            f"description is vague ({len(desc)} chars, minimum {MIN_DESCRIPTION_LEN})"
        )

    # Check recommended fields
    for field in RECOMMENDED_FIELDS:
        if not fm.get(field):
            result["warnings"].append(f"recommended field missing: {field}")

    # Check for Gotchas section
    if not has_gotchas_section(content):
        result["warnings"].append("no ## Gotchas section")

    # Set passing = False if any required fields are missing
    if result["missing"]:
        result["passing"] = False

    # Include the parsed name from frontmatter if available
    if fm.get("name"):
        result["name"] = fm["name"]

    return result


def find_skill_files(search_paths: list[Path]) -> list[Path]:
    """Find all SKILL.md files under the given search paths."""
    found: list[Path] = []
    for base in search_paths:
        if base.exists():
            for path in base.rglob("SKILL.md"):
                found.append(path)
    # Sort for deterministic output
    return sorted(found)


def run_audit(search_paths: list[Path]) -> dict:
    """Run the full audit. Returns summary dict."""
    skill_files = find_skill_files(search_paths)
    results = [audit_skill_file(f) for f in skill_files]

    passing = [r for r in results if r["passing"]]
    issues = [r for r in results if not r["passing"]]
    with_warnings = [r for r in results if r["warnings"]]

    return {
        "total": len(results),
        "passing": len(passing),
        "with_issues": len(issues),
        "with_warnings": len(with_warnings),
        "issues": issues,
        "warnings_only": [r for r in with_warnings if r["passing"]],
    }


def format_text_report(report: dict) -> str:
    """Format audit results as human-readable text."""
    lines = [
        f"**Skill Frontmatter Audit** — {report['total']} skills scanned",
        f"  Passing: {report['passing']} | Issues: {report['with_issues']} | Warnings: {report['with_warnings']}",
    ]

    if report["issues"]:
        lines.append("\n**Issues (required fields missing):**")
        for r in report["issues"][:20]:
            lines.append(f"  • {r['name']}: missing {', '.join(r['missing'])}")

    if report["warnings_only"]:
        lines.append("\n**Warnings (recommended fields missing or vague):**")
        for r in report["warnings_only"][:20]:
            summary = r["warnings"][0] if r["warnings"] else "unknown"
            lines.append(f"  • {r['name']}: {summary}")

    if not report["issues"] and not report["warnings_only"]:
        lines.append("\nAll skills have complete frontmatter.")

    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Audit SKILL.md files for missing/vague frontmatter."
    )
    parser.add_argument(
        "--skills-dir",
        type=Path,
        help="Additional directory to search for SKILL.md files.",
    )
    parser.add_argument(
        "--output",
        choices=["json", "text"],
        default="text",
        help="Output format (default: text).",
    )
    args = parser.parse_args()

    search_paths = list(DEFAULT_SKILLS_PATHS)
    if args.skills_dir:
        search_paths.insert(0, args.skills_dir)

    report = run_audit(search_paths)

    if args.output == "json":
        print(json.dumps(report, indent=2))
    else:
        print(format_text_report(report))

    return 0 if report["with_issues"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
