"""Worktree GC service — cleans up stale git worktrees every 6 hours.

Sprint S09 sub-bet 3.

Conservative policy:
  - Only prunes worktrees whose working directory is in /private/tmp/
    (never the repo root or named branches).
  - mtime > 24h (configurable).
  - Uses `git worktree remove --force` for each stale entry.
  - Never removes the main worktree.
"""
from __future__ import annotations

import logging
import subprocess
import tempfile
import time
from pathlib import Path

log = logging.getLogger(__name__)

# How old (seconds) a worktree's working directory must be before GC
DEFAULT_AGE_THRESHOLD_S = 86_400  # 24 hours

# Only prune worktrees whose path is inside these directories
_SAFE_PREFIXES = ("/private/tmp/", "/tmp/", tempfile.gettempdir().rstrip("/") + "/")


def _is_safe_to_prune(wt_path: str) -> bool:
    """Return True only if the worktree path is in a known-safe temp directory."""
    return any(wt_path.startswith(p) for p in _SAFE_PREFIXES)


def _get_worktrees(repo_root: Path) -> list[dict]:
    """Return list of worktree dicts with keys: path, branch, head."""
    result = subprocess.run(
        ["git", "worktree", "list", "--porcelain"],
        capture_output=True,
        text=True,
        cwd=str(repo_root),
        timeout=30,
    )
    if result.returncode != 0:
        log.warning("git worktree list failed: %s", result.stderr.strip())
        return []

    worktrees: list[dict] = []
    current: dict = {}
    for line in result.stdout.splitlines():
        if line.startswith("worktree "):
            if current:
                worktrees.append(current)
            current = {"path": line[len("worktree "):].strip()}
        elif line.startswith("branch "):
            current["branch"] = line[len("branch "):].strip()
        elif line.startswith("HEAD "):
            current["head"] = line[len("HEAD "):].strip()
        elif line == "":
            if current:
                worktrees.append(current)
                current = {}
    if current:
        worktrees.append(current)

    return worktrees


def run_worktree_gc(
    repo_root: Path | str | None = None,
    age_threshold_s: float = DEFAULT_AGE_THRESHOLD_S,
) -> dict:
    """Run worktree garbage collection.

    Returns a dict with keys:
        pruned: list of removed worktree paths
        skipped: list of skipped paths with reason
        errors: list of error messages
    """
    if repo_root is None:
        # Try to discover from current file's location
        repo_root = Path(__file__).resolve().parent.parent.parent
    repo_root = Path(repo_root)

    result: dict = {"pruned": [], "skipped": [], "errors": []}
    now = time.time()

    try:
        worktrees = _get_worktrees(repo_root)
    except Exception as e:
        result["errors"].append(f"Failed to list worktrees: {e}")
        return result

    if not worktrees:
        log.debug("No worktrees found")
        return result

    # First entry is always the main worktree — skip it
    main_path = worktrees[0].get("path", "") if worktrees else ""

    for wt in worktrees[1:]:
        wt_path = wt.get("path", "")
        if not wt_path:
            continue

        if wt_path == main_path:
            result["skipped"].append({"path": wt_path, "reason": "main worktree"})
            continue

        if not _is_safe_to_prune(wt_path):
            result["skipped"].append({"path": wt_path, "reason": "not in safe prefix"})
            continue

        p = Path(wt_path)
        if not p.exists():
            # Prunable — already gone from filesystem
            log.info("Pruning missing worktree: %s", wt_path)
            try:
                subprocess.run(
                    ["git", "worktree", "prune"],
                    cwd=str(repo_root),
                    capture_output=True,
                    timeout=30,
                )
                result["pruned"].append(wt_path)
            except Exception as e:
                result["errors"].append(f"prune failed for {wt_path}: {e}")
            continue

        # Check mtime
        try:
            mtime = p.stat().st_mtime
        except OSError:
            result["skipped"].append({"path": wt_path, "reason": "stat failed"})
            continue

        age = now - mtime
        if age < age_threshold_s:
            result["skipped"].append({
                "path": wt_path,
                "reason": f"too recent ({age / 3600:.1f}h < {age_threshold_s / 3600:.0f}h threshold)",
            })
            continue

        log.info("Removing stale worktree: %s (age=%.1fh)", wt_path, age / 3600)
        try:
            remove_result = subprocess.run(
                ["git", "worktree", "remove", "--force", wt_path],
                cwd=str(repo_root),
                capture_output=True,
                text=True,
                timeout=60,
            )
            if remove_result.returncode == 0:
                result["pruned"].append(wt_path)
            else:
                result["errors"].append(
                    f"remove failed for {wt_path}: {remove_result.stderr.strip()}"
                )
        except Exception as e:
            result["errors"].append(f"remove exception for {wt_path}: {e}")

    log.info(
        "Worktree GC complete: pruned=%d skipped=%d errors=%d",
        len(result["pruned"]),
        len(result["skipped"]),
        len(result["errors"]),
    )
    return result
