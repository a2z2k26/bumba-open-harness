"""Resource management utilities for the bridge (MS2.6)."""

from __future__ import annotations

import logging
import os
import shutil
import time
from collections.abc import Iterable
from pathlib import Path

logger = logging.getLogger(__name__)


# Sprint 07.01 — explicit allowlist of JSONL filenames eligible for rotation in
# the data/ directory. Append-only writers without their own rotation grow
# unbounded otherwise. Adding a name here is an opt-in: only files whose basename
# matches an entry will be rotated. SQLite journal files (*.db-wal / *.db-shm)
# and any other unknown jsonl file are deliberately excluded.
JSONL_ROTATION_ALLOWLIST: frozenset[str] = frozenset(
    {
        "traces.jsonl",
        "metrics.jsonl",
        "cost_tracking.jsonl",
        "bridge-metrics.jsonl",
        "events.jsonl",
    }
)


def _rotate_single_file(
    target: Path,
    max_rotated: int,
) -> tuple[int, int]:
    """Rotate a single file in place.

    Shifts existing rotated siblings (foo.1 -> foo.2, ...), deletes anything at
    or beyond max_rotated, renames the current file to foo.1, and creates a new
    empty file at the original path.

    Returns ``(rotated, deleted)`` counts. ``rotated`` is 0 or 1.
    """
    rotated = 0
    deleted = 0
    parent = target.parent
    base = target.name

    # Shift existing rotated files from highest to lowest
    for i in range(max_rotated, 0, -1):
        src = parent / f"{base}.{i}"
        if not src.exists():
            continue
        if i >= max_rotated:
            try:
                src.unlink()
                deleted += 1
            except OSError as e:
                logger.warning("Failed to delete %s: %s", src, e)
        else:
            dst = parent / f"{base}.{i + 1}"
            try:
                os.replace(str(src), str(dst))
            except OSError as e:
                logger.warning("Failed to rotate %s -> %s: %s", src, dst, e)

    # Rename current file -> .1
    rotated_path = parent / f"{base}.1"
    try:
        os.replace(str(target), str(rotated_path))
    except OSError as e:
        logger.warning("Failed to rotate %s -> %s: %s", target, rotated_path, e)
        return rotated, deleted

    # Create new empty file at the original path
    try:
        target.touch()
        rotated += 1
    except OSError as e:
        logger.warning("Failed to create new %s: %s", target, e)

    return rotated, deleted


def _purge_aged_rotations(
    parent: Path,
    glob_pattern: str,
    max_age_days: int,
) -> int:
    """Delete rotated siblings under ``parent`` matching ``glob_pattern`` whose
    mtime is older than ``max_age_days``. Returns count deleted.
    """
    deleted = 0
    cutoff = time.time() - (max_age_days * 86400)
    for rotated_file in sorted(parent.glob(glob_pattern)):
        try:
            mtime = rotated_file.stat().st_mtime
            if mtime < cutoff:
                rotated_file.unlink()
                deleted += 1
        except OSError as e:
            logger.warning("Failed to delete old rotated file %s: %s", rotated_file, e)
    return deleted


def rotate_logs(
    log_dir: Path,
    max_size: int = 50_000_000,
    max_rotated: int = 5,
    max_age_days: int = 30,
) -> dict[str, int]:
    """Rotate .log files exceeding max_size and delete old rotated files.

    For each .log file larger than max_size:
      - Shift existing rotated files (foo.log.2 -> foo.log.3, etc.)
      - Delete if index >= max_rotated
      - Rename foo.log -> foo.log.1
      - Create new empty foo.log

    Also delete .log.N files older than max_age_days.

    Returns {"rotated": count, "deleted": count}.
    """
    rotated = 0
    deleted = 0

    try:
        if not log_dir.is_dir():
            return {"rotated": 0, "deleted": 0}

        # First pass: rotate oversized logs
        for log_file in sorted(log_dir.glob("*.log")):
            try:
                size = log_file.stat().st_size
            except OSError:
                continue

            if size <= max_size:
                continue

            r, d = _rotate_single_file(log_file, max_rotated)
            rotated += r
            deleted += d

        # Second pass: delete rotated files older than max_age_days
        deleted += _purge_aged_rotations(log_dir, "*.log.[0-9]*", max_age_days)

    except OSError as e:
        logger.warning("Error scanning log directory %s: %s", log_dir, e)

    return {"rotated": rotated, "deleted": deleted}


def rotate_jsonl(
    data_dir: Path,
    patterns: Iterable[str] | None = None,
    max_size: int = 50_000_000,
    max_rotated: int = 5,
    max_age_days: int = 30,
    allowlist: frozenset[str] | None = None,
) -> dict[str, int]:
    """Rotate append-only ``*.jsonl`` files in ``data_dir`` (Sprint 07.01).

    Unlike ``rotate_logs``, this is restricted by an explicit filename
    ``allowlist`` (default: ``JSONL_ROTATION_ALLOWLIST``). A file is only
    rotated if its basename appears in the allowlist AND it exceeds
    ``max_size``. The allowlist guards against rotating SQLite journal files
    (``*.db-wal`` / ``*.db-shm``) or any unknown ``.jsonl`` file in the data
    directory.

    Rotation primitives (shift, delete-at-cap, age purge) are shared with
    ``rotate_logs``.

    Args:
        data_dir: Directory to scan. Typically ``config.data_dir``.
        patterns: Glob patterns to match against inside ``data_dir``.
            Defaults to ``["*.jsonl"]``.
        max_size: Bytes; files at or below this size are not rotated.
        max_rotated: Maximum number of rotated siblings retained before the
            oldest is deleted.
        max_age_days: Rotated siblings older than this are purged in the
            second pass.
        allowlist: Override the default basename allowlist. Mostly useful for
            tests.

    Returns:
        ``{"rotated": int, "deleted": int}``.
    """
    rotated = 0
    deleted = 0

    effective_patterns: tuple[str, ...] = tuple(patterns) if patterns else ("*.jsonl",)
    effective_allowlist = allowlist if allowlist is not None else JSONL_ROTATION_ALLOWLIST

    try:
        if not data_dir.is_dir():
            return {"rotated": 0, "deleted": 0}

        # First pass: rotate oversized jsonl files whose basename is allowlisted.
        seen: set[Path] = set()
        for pattern in effective_patterns:
            for jsonl_file in sorted(data_dir.glob(pattern)):
                if jsonl_file in seen:
                    continue
                seen.add(jsonl_file)

                if jsonl_file.name not in effective_allowlist:
                    continue

                try:
                    size = jsonl_file.stat().st_size
                except OSError:
                    continue

                if size <= max_size:
                    continue

                r, d = _rotate_single_file(jsonl_file, max_rotated)
                rotated += r
                deleted += d

        # Second pass: purge aged rotation siblings for each allowlisted name.
        for name in effective_allowlist:
            deleted += _purge_aged_rotations(data_dir, f"{name}.[0-9]*", max_age_days)

    except OSError as e:
        logger.warning("Error scanning data directory %s: %s", data_dir, e)

    return {"rotated": rotated, "deleted": deleted}


def check_disk_usage(path: str | Path = "/") -> dict[str, float]:
    """Return disk usage statistics for the given path.

    Returns {"total_gb": ..., "used_gb": ..., "free_gb": ..., "used_pct": ...}.
    """
    try:
        usage = shutil.disk_usage(str(path))
        total_gb = usage.total / (1024 ** 3)
        used_gb = usage.used / (1024 ** 3)
        free_gb = usage.free / (1024 ** 3)
        used_pct = (usage.used / usage.total * 100) if usage.total > 0 else 0.0
        return {
            "total_gb": round(total_gb, 2),
            "used_gb": round(used_gb, 2),
            "free_gb": round(free_gb, 2),
            "used_pct": round(used_pct, 1),
        }
    except OSError as e:
        logger.warning("Failed to check disk usage for %s: %s", path, e)
        return {"total_gb": 0.0, "used_gb": 0.0, "free_gb": 0.0, "used_pct": 0.0}


def cleanup_stale_files(data_dir: Path, max_age_days: int = 7) -> int:
    """Remove stale temp and service message files older than max_age_days.

    Targets:
      - data_dir/**/*.tmp
      - data_dir/service_messages/*.json

    Returns count of files removed.
    """
    removed = 0
    cutoff = time.time() - (max_age_days * 86400)

    try:
        if not data_dir.is_dir():
            return 0

        # Remove old .tmp files recursively
        for tmp_file in data_dir.rglob("*.tmp"):
            try:
                if tmp_file.stat().st_mtime < cutoff:
                    tmp_file.unlink()
                    removed += 1
            except OSError as e:
                logger.warning("Failed to remove %s: %s", tmp_file, e)

        # Remove old service message JSON files
        service_msg_dir = data_dir / "service_messages"
        if service_msg_dir.is_dir():
            for json_file in service_msg_dir.glob("*.json"):
                try:
                    if json_file.stat().st_mtime < cutoff:
                        json_file.unlink()
                        removed += 1
                except OSError as e:
                    logger.warning("Failed to remove %s: %s", json_file, e)

    except OSError as e:
        logger.warning("Error scanning data directory %s: %s", data_dir, e)

    return removed


def wal_size_bytes(db_path: str | Path) -> int:
    """Return the size in bytes of the WAL file for a SQLite database.

    Returns 0 if the WAL file does not exist.
    """
    wal_path = Path(f"{db_path}-wal")
    try:
        return wal_path.stat().st_size
    except OSError:
        return 0
