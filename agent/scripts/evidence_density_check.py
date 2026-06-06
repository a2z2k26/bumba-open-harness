#!/usr/bin/env python3
"""Evidence-density check for sprint PRs.

Blocks PRs that claim multiple sprints in their title unless each claimed
sprint has a corresponding `.harness/evidence/sprint-<id>/` directory
containing at least one evidence file.

Usage:
    python evidence_density_check.py "feat(harness): Sprint 4.8 + 4.9 work" /path/to/repo

Exit codes:
    0  — all claimed sprints have evidence (or no sprint IDs in title)
    1  — one or more claimed sprints are missing evidence directories/files
"""

from __future__ import annotations

import re
import sys
from pathlib import Path


# Matches patterns like:
#   sprint-4.8   Sprint 4.8   sprint 4.8   sprint-04-09
#   Sprint 4.10  sprint-4.1   Sprint 04.09
#   Sprint 06.15a Sprint 06.15b  (sub-sprint suffixes)
# Captures the numeric ID portion plus optional [a-z] suffix
# (e.g. "4.8", "04-09", "4.10", "06.15a", "06.15b")
_SPRINT_PATTERN = re.compile(
    r"[Ss]print[\s\-_]+"  # "Sprint" or "sprint" followed by separator(s)
    r"(\d+[\.\-]\d+[a-z]?)",  # numeric ID with optional sub-sprint letter suffix
)


def parse_sprint_ids(title: str) -> list[str]:
    """Extract sprint IDs from a PR title string.

    Returns a deduplicated list of normalized sprint IDs (dots as separators).
    """
    raw_matches = _SPRINT_PATTERN.findall(title)
    # Normalize separators: "04-09" -> "04.09", keep "4.8" as-is
    seen: set[str] = set()
    result: list[str] = []
    for raw_id in raw_matches:
        normalized = raw_id.replace("-", ".")
        if normalized not in seen:
            seen.add(normalized)
            result.append(normalized)
    return result


def check_evidence(
    sprint_ids: list[str],
    repo_path: Path,
) -> tuple[list[str], list[str]]:
    """Check that each sprint ID has an evidence directory with files.

    Returns (present, missing) — two lists of sprint IDs.
    """
    present: list[str] = []
    missing: list[str] = []
    for sid in sprint_ids:
        evidence_dir = repo_path / ".harness" / "evidence" / f"sprint-{sid}"
        if evidence_dir.is_dir() and any(evidence_dir.iterdir()):
            present.append(sid)
        else:
            missing.append(sid)
    return present, missing


def format_report(
    sprint_ids: list[str],
    present: list[str],
    missing: list[str],
) -> str:
    """Build a human-readable report of the evidence check."""
    lines: list[str] = []
    if not sprint_ids:
        lines.append("No sprint IDs found in PR title. Skipping evidence check.")
        return "\n".join(lines)

    lines.append(f"Sprint IDs found: {', '.join(sprint_ids)}")
    if present:
        lines.append(f"Evidence present: {', '.join(present)}")
    if missing:
        lines.append(f"Evidence MISSING: {', '.join(missing)}")
        lines.append("")
        lines.append("Missing directories:")
        for sid in missing:
            lines.append(f"  .harness/evidence/sprint-{sid}/")
        lines.append("")
        lines.append("Each claimed sprint must have at least one evidence file.")
    else:
        lines.append("All claimed sprints have evidence. PASS.")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    """Entry point. Returns 0 on pass, 1 on failure."""
    args = argv if argv is not None else sys.argv[1:]
    if len(args) < 2:
        print("Usage: evidence_density_check.py <pr-title> <repo-path>", file=sys.stderr)
        return 2

    title = args[0]
    repo_path = Path(args[1])

    sprint_ids = parse_sprint_ids(title)
    present, missing = check_evidence(sprint_ids, repo_path)
    report = format_report(sprint_ids, present, missing)
    print(report)

    if missing:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
