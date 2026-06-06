"""Worktree hygiene — list and optionally remove stale `.claude/worktrees/`.

Sprint P0.5 (2026-05-11 harness audit). The `.claude/worktrees/` directory
accumulates one subdirectory per `Agent` tool call that uses
`isolation: "worktree"`. After hundreds of subagent invocations, the
directory can grow to 6+ GB. This script provides the safe-by-default
cleanup loop the operator can run on a schedule.

Usage:
    # Dry-run report (default): print stale worktrees, delete nothing.
    python scripts/worktree_hygiene.py
    python scripts/worktree_hygiene.py --older-than-days 14

    # Delete: requires --delete AND a clean working status per worktree.
    python scripts/worktree_hygiene.py --older-than-days 14 --delete

Exit codes:
    0  Success (dry-run completed, or all eligible worktrees removed).
    1  At least one worktree could not be removed (dirty, or rm failed).
    2  Bad arguments.

The script intentionally has no dependencies beyond stdlib so it can run
from any host without venv activation.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

# Resolve repo root from this script's location: agent/scripts/ → agent/ → repo
REPO_ROOT = Path(__file__).resolve().parents[2]
WORKTREE_DIR = REPO_ROOT / ".claude" / "worktrees"

DEFAULT_OLDER_THAN_DAYS = 14


@dataclass(frozen=True)
class WorktreeInfo:
    """Snapshot of a single worktree's state."""

    path: Path
    age_days: float
    branch: str
    is_dirty: bool


def _git(cmd: list[str], cwd: Path) -> str:
    """Run a git command in `cwd` and return stdout (or '' on failure)."""
    try:
        result = subprocess.run(
            ["git", *cmd],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        return result.stdout.strip() if result.returncode == 0 else ""
    except (subprocess.TimeoutExpired, OSError):
        return ""


def _describe_worktree(path: Path) -> WorktreeInfo:
    """Inspect one worktree directory and return its state."""
    # Age from mtime (mtime is updated by any write into the tree).
    try:
        mtime = path.stat().st_mtime
    except OSError:
        mtime = 0.0
    age_seconds = max(0.0, time.time() - mtime)
    age_days = age_seconds / 86400.0

    # Branch — best-effort; empty string if git can't tell.
    branch = _git(["branch", "--show-current"], cwd=path) or "(detached)"

    # Dirty = either uncommitted changes OR untracked files present.
    porcelain = _git(["status", "--porcelain"], cwd=path)
    is_dirty = bool(porcelain.strip())

    return WorktreeInfo(
        path=path,
        age_days=age_days,
        branch=branch,
        is_dirty=is_dirty,
    )


def _list_worktrees() -> list[Path]:
    """List all candidate worktree subdirectories. Returns empty list if dir missing."""
    if not WORKTREE_DIR.exists():
        return []
    return sorted(p for p in WORKTREE_DIR.iterdir() if p.is_dir())


def _format_row(info: WorktreeInfo) -> str:
    """Render one worktree as a fixed-width report row."""
    dirty_flag = "DIRTY" if info.is_dirty else "clean"
    rel = info.path.relative_to(REPO_ROOT)
    return (
        f"  {info.age_days:6.1f}d  {dirty_flag:>5}  "
        f"{info.branch:30s}  {rel}"
    )


def _remove_worktree(path: Path) -> tuple[bool, str]:
    """Attempt to remove a worktree. Returns (ok, message)."""
    # Prefer git's worktree-remove machinery — it cleans up the registry
    # entry in `.git/worktrees/` and refuses on dirty/locked trees.
    out = _git(["worktree", "remove", "--force", str(path)], cwd=REPO_ROOT)
    if (path.exists()):
        # Git refused (returns nothing to stdout on refusal). Fall back to
        # a plain rmtree, which loses the registry cleanup but always works.
        try:
            shutil.rmtree(path)
        except OSError as exc:
            return False, f"rm failed: {exc}"
    return True, out or "removed"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="worktree_hygiene",
        description=(
            "List and optionally remove stale .claude/worktrees/ entries. "
            "Dry-run by default; deletion requires --delete AND a clean "
            "worktree status."
        ),
    )
    parser.add_argument(
        "--older-than-days",
        type=float,
        default=DEFAULT_OLDER_THAN_DAYS,
        help=(
            f"Only consider worktrees older than this many days. "
            f"Default: {DEFAULT_OLDER_THAN_DAYS}."
        ),
    )
    parser.add_argument(
        "--delete",
        action="store_true",
        help=(
            "Actually delete eligible worktrees (those past --older-than-days "
            "AND with clean status). Default: dry-run."
        ),
    )
    args = parser.parse_args(argv)

    if args.older_than_days < 0:
        print("ERROR: --older-than-days must be >= 0", file=sys.stderr)
        return 2

    candidates = _list_worktrees()
    if not candidates:
        print(f"No worktrees found at {WORKTREE_DIR}")
        return 0

    print(f"Scanning {len(candidates)} worktree(s) at {WORKTREE_DIR}")
    print(f"Threshold: older than {args.older_than_days} day(s)")
    print()

    eligible: list[WorktreeInfo] = []
    too_young: list[WorktreeInfo] = []
    for path in candidates:
        info = _describe_worktree(path)
        if info.age_days >= args.older_than_days:
            eligible.append(info)
        else:
            too_young.append(info)

    print(f"Eligible (older than threshold): {len(eligible)}")
    if eligible:
        print("  age      status   branch                          path")
        for info in sorted(eligible, key=lambda i: i.age_days, reverse=True):
            print(_format_row(info))

    if too_young:
        print(f"\nToo young to consider: {len(too_young)}")

    if not args.delete:
        print(
            f"\nDry-run only — pass --delete to remove the "
            f"{sum(1 for i in eligible if not i.is_dirty)} clean eligible "
            f"worktree(s)."
        )
        return 0

    # Delete mode: skip dirty, remove clean
    print()
    failures = 0
    removed = 0
    skipped_dirty = 0
    for info in eligible:
        if info.is_dirty:
            skipped_dirty += 1
            print(f"SKIP (dirty): {info.path.relative_to(REPO_ROOT)}")
            continue
        ok, msg = _remove_worktree(info.path)
        if ok:
            removed += 1
            print(f"REMOVED: {info.path.relative_to(REPO_ROOT)} ({msg})")
        else:
            failures += 1
            print(f"FAILED:  {info.path.relative_to(REPO_ROOT)} ({msg})")

    print(
        f"\nSummary: {removed} removed, {skipped_dirty} skipped-dirty, "
        f"{failures} failed"
    )
    return 1 if failures > 0 else 0


if __name__ == "__main__":
    sys.exit(main())
