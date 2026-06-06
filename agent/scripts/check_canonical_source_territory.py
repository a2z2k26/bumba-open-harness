"""Canonical source territory guard (Sprint S7.2, issue #2354).

Scans the **current working tree** for live Python source files at forbidden
repo-root shadow paths. Complements two adjacent guards:

  1. ``.github/workflows/write-destination-guard.yml`` — diff-based; fires on
     PRs that *add or modify* shadow paths. Catches new drift.
  2. ``.pre-commit-config.yaml::forbid-shadow-tree-writes`` — diff-based;
     fires per-file at commit time on the same paths. Catches drift at the
     keystroke.

This script is **state-based**: it inspects the entire tree as it sits on
disk and exits non-zero if shadow files exist, regardless of whether they
were introduced in the current diff. That lets it catch:

  - Accumulated drift that slipped past CI before the guard existed.
  - Local working trees where shadow files were created outside git
    (uncommitted spike code that an agent might later commit).
  - Audit invocations that confirm "the tree is clean right now" without
    needing a PR diff.

Forbidden roots (matches the canonical-write-territory doctrine):

  - ``bridge/``      → use ``agent/bridge/``
  - ``teams/``       → use ``agent/teams/``
  - ``tests/``       → use ``agent/tests/``
  - ``job_search/``  → use ``agent/job_search/``
  - ``pyproject.toml`` at repo root → use ``agent/pyproject.toml``
  - ``uv.lock`` at repo root → use ``agent/uv.lock``

Allowlist is intentionally empty by default. The post-D6-bis canonical
layout has no legitimate live source at these locations.

Stdlib only. Exit codes:

  - 0: tree is clean.
  - 1: shadow files found; paths printed to stderr.

Doctrine: ``docs/architecture/canonical-write-territory.md``.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Repo layout: <repo>/agent/scripts/check_canonical_source_territory.py
SCRIPT_PATH = Path(__file__).resolve()
REPO_ROOT_DEFAULT = SCRIPT_PATH.parent.parent.parent

# Top-level directories that must not contain ANY files (Python or otherwise)
# at the repo root. Matches the doctrine table in canonical-write-territory.md
# and the regex in .github/workflows/write-destination-guard.yml.
FORBIDDEN_ROOT_DIRS: tuple[str, ...] = (
    "bridge",
    "teams",
    "tests",
    "job_search",
)

# Single files that must not exist at repo root.
FORBIDDEN_ROOT_FILES: tuple[str, ...] = (
    "pyproject.toml",
    "uv.lock",
)

# Explicit allowlist for paths that may legitimately appear at a forbidden
# location. Empty by default — the canonical layout permits no exceptions.
# Add entries here only with an operator-signed ADR explaining why.
ALLOWLIST: frozenset[str] = frozenset()


def _scan_forbidden_dirs(repo_root: Path) -> list[str]:
    """Return repo-relative paths of all files under forbidden root dirs.

    Walks each forbidden directory recursively. Returns a sorted list of
    relative paths suitable for printing in error output.
    """
    found: list[str] = []
    for forbidden_dir in FORBIDDEN_ROOT_DIRS:
        root = repo_root / forbidden_dir
        if not root.exists():
            continue
        if not root.is_dir():
            # A file with the same name as a forbidden dir — still drift.
            rel = str(root.relative_to(repo_root))
            if rel not in ALLOWLIST:
                found.append(rel)
            continue
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            rel = str(path.relative_to(repo_root))
            if rel in ALLOWLIST:
                continue
            found.append(rel)
    return sorted(found)


def _scan_forbidden_files(repo_root: Path) -> list[str]:
    """Return repo-relative paths of forbidden root files that exist."""
    found: list[str] = []
    for name in FORBIDDEN_ROOT_FILES:
        path = repo_root / name
        if path.exists() and path.is_file():
            if name not in ALLOWLIST:
                found.append(name)
    return sorted(found)


def check(repo_root: Path) -> list[str]:
    """Return all violating paths (empty list if tree is clean)."""
    return _scan_forbidden_dirs(repo_root) + _scan_forbidden_files(repo_root)


def _print_violations(violations: list[str]) -> None:
    """Write actionable violation report to stderr."""
    print(
        "ERROR: canonical source territory guard found shadow paths at repo root:",
        file=sys.stderr,
    )
    print("", file=sys.stderr)
    for path in violations:
        print(f"    {path}", file=sys.stderr)
    print("", file=sys.stderr)
    print(
        "Canonical paths live under agent/. Move each file to its agent/ "
        "counterpart, e.g.:",
        file=sys.stderr,
    )
    print("    bridge/foo.py        → agent/bridge/foo.py", file=sys.stderr)
    print("    tests/test_foo.py    → agent/tests/test_foo.py", file=sys.stderr)
    print("    pyproject.toml       → agent/pyproject.toml", file=sys.stderr)
    print("", file=sys.stderr)
    print(
        "Doctrine: docs/architecture/canonical-write-territory.md",
        file=sys.stderr,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Fail if live source files exist at forbidden repo-root shadow "
            "paths (bridge/, teams/, tests/, job_search/, root "
            "pyproject.toml, root uv.lock)."
        )
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=REPO_ROOT_DEFAULT,
        help="Repo root to scan (default: resolved from script location).",
    )
    args = parser.parse_args(argv)

    repo_root = args.repo_root.resolve()
    if not repo_root.is_dir():
        print(f"ERROR: --repo-root {repo_root} is not a directory", file=sys.stderr)
        return 2

    violations = check(repo_root)
    if violations:
        _print_violations(violations)
        return 1

    print("OK: canonical source territory is clean.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
