"""Daily vault backup primitives — Sprint 05.0b (issue #1019).

Even with the operator's Obsidian vault git-versioned per the
2026-05-01 second-brain ADR (Decision 1), an operator who hasn't
committed in 3 days could lose work if a Bumba write goes wrong.
This module ships the safety net: a daily ``.tar.gz`` snapshot of
the vault written before any Bumba write session begins.

Scope (this sprint):
- Pure-function primitives + tests; no daemon wiring.
- Sprint 05.07 calls :func:`ensure_snapshot_today` ahead of any
  contribution write.

Design notes:
- **Read-only on the vault.** Snapshots are created from a read; the
  vault itself is never written.
- **Atomic writes.** Snapshots write to ``<date>.tmp.tar.gz`` first
  and rename to ``<date>.tar.gz`` only on success. A crash mid-write
  leaves the ``.tmp.tar.gz`` (which the next call ignores) and no
  partial canonical file.
- **Excluded subtrees.** ``.obsidian/`` (workspace state),
  ``.git/`` (large + redundant with git-versioning), and
  ``.trash/`` (Obsidian's soft-delete) are skipped to keep
  snapshots focused on the operator's content.
- **Retention.** :func:`prune_old_snapshots` defaults to 30 days and
  refuses to drop below 7 — that floor is a safety rail, not an
  arbitrary lower bound.
"""

from __future__ import annotations

import logging
import tarfile
import time
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)


# Subdirectories under the vault that the snapshot intentionally skips.
EXCLUDED_DIR_NAMES: frozenset[str] = frozenset({".obsidian", ".git", ".trash"})

# Default output directory under ``agent/data/`` (resolved against the
# repo agent root by callers that pass ``output_dir=None``).
DEFAULT_BACKUP_DIRNAME: str = "second-brain-backups"

# Default retention for :func:`prune_old_snapshots`.
DEFAULT_KEEP_DAYS: int = 30

# Hard floor — refuse to drop retention below this many days. Lowering
# this would risk losing recovery options; the operator can raise it
# but not lower it through the public API.
MIN_KEEP_DAYS: int = 7


def _default_output_dir() -> Path:
    """Return the canonical default output dir under ``agent/data/``.

    Resolved relative to this module so the path stays correct in both
    the source repo (``/home/bumba/Documents/bumba-open-harness/agent/...``)
    and the runtime tree (``/opt/bumba-harness/agent/...``). Callers
    who pass an explicit ``output_dir`` bypass this entirely.
    """
    # bridge/second_brain/backup.py → agent/data/second-brain-backups/
    agent_root = Path(__file__).resolve().parent.parent.parent
    return agent_root / "data" / DEFAULT_BACKUP_DIRNAME


def _resolve_output_dir(output_dir: Path | None) -> Path:
    """Return an absolute, mkdir-ed output directory."""
    out = Path(output_dir) if output_dir is not None else _default_output_dir()
    out.mkdir(parents=True, exist_ok=True)
    return out


def _today_iso() -> str:
    """Return today's date in YYYY-MM-DD form (UTC-naive local date).

    Snapshot filenames use the operator's local date so a "daily" cadence
    matches the operator's wall clock, not UTC midnight.
    """
    return datetime.now().strftime("%Y-%m-%d")


def _snapshot_filename(date_str: str) -> str:
    return f"{date_str}.tar.gz"


def _temp_filename(date_str: str) -> str:
    return f"{date_str}.tmp.tar.gz"


def _tar_filter(tarinfo: tarfile.TarInfo) -> tarfile.TarInfo | None:
    """tarfile filter — drop entries whose path passes through an excluded dir.

    Inspecting the tar member name (POSIX path with forward slashes)
    instead of the on-disk path keeps the filter platform-stable.
    """
    parts = tarinfo.name.split("/")
    if any(part in EXCLUDED_DIR_NAMES for part in parts):
        return None
    return tarinfo


def snapshot_vault(
    vault_root: Path,
    *,
    output_dir: Path | None = None,
) -> Path:
    """Write a ``tar.gz`` snapshot of ``vault_root`` to ``output_dir``.

    Excludes ``.obsidian/``, ``.git/``, and ``.trash/`` subtrees.
    Atomic: writes to ``<date>.tmp.tar.gz`` and renames to
    ``<date>.tar.gz`` on success. Any pre-existing ``.tmp.tar.gz``
    from a crashed prior run is overwritten.

    Args:
        vault_root: Absolute path to the operator's Obsidian vault.
        output_dir: Where to write the snapshot. Defaults to
            ``agent/data/second-brain-backups/``.

    Returns:
        Path to the written ``.tar.gz`` snapshot.

    Raises:
        FileNotFoundError: ``vault_root`` does not exist.
        NotADirectoryError: ``vault_root`` exists but is not a directory.
    """
    vault_root = Path(vault_root)
    if not vault_root.exists():
        raise FileNotFoundError(f"vault_root does not exist: {vault_root}")
    if not vault_root.is_dir():
        raise NotADirectoryError(f"vault_root is not a directory: {vault_root}")

    out = _resolve_output_dir(output_dir)
    date_str = _today_iso()
    final_path = out / _snapshot_filename(date_str)
    tmp_path = out / _temp_filename(date_str)

    # Clean up any leftover tmp file from a crashed prior run.
    if tmp_path.exists():
        tmp_path.unlink()

    try:
        # arcname is the vault root's basename so untarring produces a
        # single top-level directory rather than absolute paths.
        with tarfile.open(tmp_path, "w:gz") as tar:
            tar.add(vault_root, arcname=vault_root.name, filter=_tar_filter)
        tmp_path.replace(final_path)
    except Exception:
        # If anything went wrong, clear the partial tmp file so the
        # output_dir never contains a half-written snapshot.
        if tmp_path.exists():
            tmp_path.unlink()
        raise

    logger.info(
        "second-brain backup written: vault=%s snapshot=%s",
        vault_root, final_path,
    )
    return final_path


def latest_snapshot(*, output_dir: Path | None = None) -> Path | None:
    """Return the most recent snapshot path, or ``None`` if there are none.

    Filenames are ``YYYY-MM-DD.tar.gz`` so lexicographic order equals
    chronological order. ``.tmp.tar.gz`` files (in-flight or crashed)
    are ignored.
    """
    out = _resolve_output_dir(output_dir)
    snapshots = sorted(
        p for p in out.glob("*.tar.gz")
        if not p.name.endswith(".tmp.tar.gz")
    )
    return snapshots[-1] if snapshots else None


def ensure_snapshot_today(
    vault_root: Path,
    *,
    output_dir: Path | None = None,
) -> Path:
    """Idempotent snapshot — create today's archive if it doesn't exist.

    The "before any Bumba write session" gate calls this. If today's
    snapshot already exists, returns its path without re-creating;
    otherwise creates and returns the new path.
    """
    out = _resolve_output_dir(output_dir)
    date_str = _today_iso()
    final_path = out / _snapshot_filename(date_str)
    if final_path.exists():
        logger.debug("snapshot already exists for %s, skipping", date_str)
        return final_path
    return snapshot_vault(vault_root, output_dir=out)


def prune_old_snapshots(
    *,
    output_dir: Path | None = None,
    keep_days: int = DEFAULT_KEEP_DAYS,
) -> int:
    """Delete snapshots older than ``keep_days`` (by mtime).

    Args:
        output_dir: Snapshot directory. Defaults to
            ``agent/data/second-brain-backups/``.
        keep_days: Retain snapshots newer than this many days. Hard
            floor of 7 — values below raise ``ValueError``.

    Returns:
        Count of snapshots removed.

    Raises:
        ValueError: ``keep_days`` is below :data:`MIN_KEEP_DAYS`.
    """
    if keep_days < MIN_KEEP_DAYS:
        raise ValueError(
            f"keep_days={keep_days} below safety floor of {MIN_KEEP_DAYS}",
        )

    out = _resolve_output_dir(output_dir)
    cutoff = time.time() - (keep_days * 86400)
    removed = 0
    for snapshot in out.glob("*.tar.gz"):
        if snapshot.name.endswith(".tmp.tar.gz"):
            continue
        try:
            if snapshot.stat().st_mtime < cutoff:
                snapshot.unlink()
                removed += 1
        except FileNotFoundError:
            # Race with another pruner — fine, move on.
            continue
    if removed:
        logger.info("second-brain backup prune: removed %d snapshot(s)", removed)
    return removed
