"""Tests for bridge.resource_manager.rotate_jsonl (Sprint 07.01).

Covers the explicit filename allowlist, oversized-file rotation, rotated-sibling
cap, and protection of unrelated files (SQLite journal artefacts, .jsonl files
outside the allowlist, .jsonl files in log_dir rather than data_dir).
"""

from __future__ import annotations

import time
from pathlib import Path

from bridge.resource_manager import (
    JSONL_ROTATION_ALLOWLIST,
    rotate_jsonl,
    rotate_logs,
)


# ---------------------------------------------------------------------------
# Allowlist contract — guards against silent expansion of rotated filenames.
# ---------------------------------------------------------------------------


def test_allowlist_contents_are_locked() -> None:
    """The Sprint 07.01 allowlist enumerates exactly five filenames."""
    assert JSONL_ROTATION_ALLOWLIST == frozenset(
        {
            "traces.jsonl",
            "metrics.jsonl",
            "cost_tracking.jsonl",
            "bridge-metrics.jsonl",
            "events.jsonl",
        }
    )


# ---------------------------------------------------------------------------
# Oversized rotation
# ---------------------------------------------------------------------------


def test_jsonl_rotated_when_oversized(tmp_path: Path) -> None:
    """An allowlisted .jsonl file > max_size is rotated and emptied."""
    jsonl = tmp_path / "traces.jsonl"
    jsonl.write_bytes(b'{"k":"v"}\n' * 500)  # comfortably > 1000 bytes
    original_size = jsonl.stat().st_size
    assert original_size > 1000

    result = rotate_jsonl(tmp_path, max_size=1000)

    assert result["rotated"] == 1
    # New empty file at the original path
    assert jsonl.exists()
    assert jsonl.stat().st_size == 0
    # Rotated sibling carries the original payload
    rotated_sibling = tmp_path / "traces.jsonl.1"
    assert rotated_sibling.exists()
    assert rotated_sibling.stat().st_size == original_size


def test_jsonl_under_max_size_not_rotated(tmp_path: Path) -> None:
    """An allowlisted .jsonl file at or below max_size is left alone."""
    jsonl = tmp_path / "metrics.jsonl"
    jsonl.write_bytes(b"x" * 500)

    result = rotate_jsonl(tmp_path, max_size=1000)

    assert result["rotated"] == 0
    assert jsonl.stat().st_size == 500
    assert not (tmp_path / "metrics.jsonl.1").exists()


# ---------------------------------------------------------------------------
# Rotation cap
# ---------------------------------------------------------------------------


def test_rotation_caps_at_five(tmp_path: Path) -> None:
    """When max_rotated=5 and 5 siblings exist, oldest is dropped on next
    rotation; the rotated set never exceeds max_rotated."""
    jsonl = tmp_path / "events.jsonl"
    jsonl.write_bytes(b"x" * 2000)
    # Pre-populate .1 .. .5 (the maximum rotated siblings)
    for i in range(1, 6):
        (tmp_path / f"events.jsonl.{i}").write_text(f"old-{i}")

    result = rotate_jsonl(tmp_path, max_size=1000, max_rotated=5)

    assert result["rotated"] == 1
    assert result["deleted"] >= 1
    # .5 (oldest) was removed during the shift; the freshly rotated file is .1
    siblings = sorted(p.name for p in tmp_path.glob("events.jsonl.[0-9]*"))
    assert siblings == [
        "events.jsonl.1",
        "events.jsonl.2",
        "events.jsonl.3",
        "events.jsonl.4",
        "events.jsonl.5",
    ]
    # Newest rotated file (.1) carries the live payload
    assert (tmp_path / "events.jsonl.1").stat().st_size == 2000


def test_rotation_does_not_create_more_than_max_rotated(tmp_path: Path) -> None:
    """Even after several rotations, sibling count stays <= max_rotated."""
    jsonl = tmp_path / "cost_tracking.jsonl"
    for _ in range(7):
        jsonl.write_bytes(b"x" * 2000)
        rotate_jsonl(tmp_path, max_size=1000, max_rotated=5)

    siblings = list(tmp_path.glob("cost_tracking.jsonl.[0-9]*"))
    assert len(siblings) <= 5


# ---------------------------------------------------------------------------
# Scope isolation: rotate_jsonl only touches data_dir, not log_dir
# ---------------------------------------------------------------------------


def test_config_log_dir_jsonl_not_rotated(tmp_path: Path) -> None:
    """A .jsonl file inside log_dir (not data_dir) is not rotated by
    rotate_jsonl. Conversely, rotate_logs (which targets *.log) does not
    rotate it either, so unrelated paths stay untouched."""
    log_dir = tmp_path / "logs"
    data_dir = tmp_path / "data"
    log_dir.mkdir()
    data_dir.mkdir()

    log_jsonl = log_dir / "traces.jsonl"
    log_jsonl.write_bytes(b"x" * 5000)

    # rotate_jsonl is pointed at data_dir, so log_dir jsonl is invisible.
    result = rotate_jsonl(data_dir, max_size=1000)
    assert result["rotated"] == 0
    assert log_jsonl.exists()
    assert log_jsonl.stat().st_size == 5000
    assert not (log_dir / "traces.jsonl.1").exists()

    # rotate_logs targets *.log only; .jsonl in log_dir is also untouched.
    rotate_logs(log_dir, max_size=1000)
    assert log_jsonl.stat().st_size == 5000


# ---------------------------------------------------------------------------
# Allowlist enforcement
# ---------------------------------------------------------------------------


def test_sqlite_journal_not_rotated(tmp_path: Path) -> None:
    """SQLite WAL/SHM files are never rotated, even if they exceed max_size."""
    wal = tmp_path / "memory.db-wal"
    shm = tmp_path / "memory.db-shm"
    wal.write_bytes(b"x" * 5000)
    shm.write_bytes(b"x" * 5000)

    result = rotate_jsonl(tmp_path, max_size=1000)

    assert result["rotated"] == 0
    assert result["deleted"] == 0
    assert wal.stat().st_size == 5000
    assert shm.stat().st_size == 5000
    assert not (tmp_path / "memory.db-wal.1").exists()
    assert not (tmp_path / "memory.db-shm.1").exists()


def test_unknown_jsonl_filename_not_rotated(tmp_path: Path) -> None:
    """A .jsonl file outside the allowlist is not rotated even if oversized."""
    foreign = tmp_path / "third_party.jsonl"
    foreign.write_bytes(b"x" * 5000)

    result = rotate_jsonl(tmp_path, max_size=1000)

    assert result["rotated"] == 0
    assert foreign.exists()
    assert foreign.stat().st_size == 5000
    assert not (tmp_path / "third_party.jsonl.1").exists()


def test_mixed_allowlist_and_foreign_files(tmp_path: Path) -> None:
    """In a mixed directory, only allowlisted files rotate; the rest are kept."""
    allowed = tmp_path / "traces.jsonl"
    foreign = tmp_path / "rogue.jsonl"
    allowed.write_bytes(b"x" * 5000)
    foreign.write_bytes(b"x" * 5000)

    result = rotate_jsonl(tmp_path, max_size=1000)

    assert result["rotated"] == 1
    assert allowed.stat().st_size == 0
    assert (tmp_path / "traces.jsonl.1").exists()
    assert foreign.stat().st_size == 5000
    assert not (tmp_path / "rogue.jsonl.1").exists()


# ---------------------------------------------------------------------------
# Aged rotation purge
# ---------------------------------------------------------------------------


def test_aged_rotation_siblings_purged(tmp_path: Path) -> None:
    """Rotated siblings older than max_age_days are deleted in pass 2."""
    aged = tmp_path / "metrics.jsonl.3"
    aged.write_text("ancient")
    long_ago = time.time() - (40 * 86400)
    import os as _os
    _os.utime(aged, (long_ago, long_ago))

    # No live oversized file; only the aged sibling exists.
    result = rotate_jsonl(tmp_path, max_size=1000, max_age_days=30)

    assert result["deleted"] >= 1
    assert not aged.exists()


def test_missing_data_dir_returns_zero_counts(tmp_path: Path) -> None:
    """A non-existent data_dir is handled gracefully."""
    result = rotate_jsonl(tmp_path / "does-not-exist", max_size=1000)
    assert result == {"rotated": 0, "deleted": 0}
