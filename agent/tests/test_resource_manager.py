"""Tests for bridge.resource_manager (MS2.6)."""

from __future__ import annotations

import os
import time
from pathlib import Path


from bridge.resource_manager import (
    check_disk_usage,
    cleanup_stale_files,
    rotate_logs,
    wal_size_bytes,
)


# ---------------------------------------------------------------------------
# rotate_logs
# ---------------------------------------------------------------------------


def test_rotate_logs_oversized(tmp_path: Path) -> None:
    """A log file exceeding max_size is rotated: renamed to .1, new empty file created."""
    log = tmp_path / "app.log"
    log.write_bytes(b"x" * 2000)

    result = rotate_logs(tmp_path, max_size=1000)

    assert result["rotated"] == 1
    assert log.exists()
    assert log.stat().st_size == 0
    assert (tmp_path / "app.log.1").exists()
    assert (tmp_path / "app.log.1").stat().st_size == 2000


def test_rotate_logs_under_size(tmp_path: Path) -> None:
    """A log file under max_size is not rotated."""
    log = tmp_path / "app.log"
    log.write_bytes(b"x" * 500)

    result = rotate_logs(tmp_path, max_size=1000)

    assert result["rotated"] == 0
    assert log.stat().st_size == 500
    assert not (tmp_path / "app.log.1").exists()


def test_rotate_logs_shifts_existing(tmp_path: Path) -> None:
    """Existing foo.log.1 is shifted to foo.log.2 before rotation."""
    log = tmp_path / "app.log"
    log.write_bytes(b"x" * 2000)
    existing = tmp_path / "app.log.1"
    existing.write_text("old-rotated")

    result = rotate_logs(tmp_path, max_size=1000)

    assert result["rotated"] == 1
    # Original .1 should now be .2
    assert (tmp_path / "app.log.2").read_text() == "old-rotated"
    # New .1 is the freshly rotated file
    assert (tmp_path / "app.log.1").stat().st_size == 2000


def test_rotate_logs_deletes_old(tmp_path: Path) -> None:
    """Rotated file with index >= max_rotated is deleted during shift."""
    log = tmp_path / "app.log"
    log.write_bytes(b"x" * 2000)
    # Create .5 which is at the max_rotated boundary
    overflow = tmp_path / "app.log.5"
    overflow.write_text("overflow")

    result = rotate_logs(tmp_path, max_size=1000, max_rotated=5)

    assert result["rotated"] == 1
    assert result["deleted"] >= 1
    assert not overflow.exists()


def test_rotate_logs_empty_dir(tmp_path: Path) -> None:
    """An empty directory returns zero counts."""
    result = rotate_logs(tmp_path)
    assert result == {"rotated": 0, "deleted": 0}


def test_rotate_logs_deletes_aged_rotated_files(tmp_path: Path) -> None:
    """Rotated files older than max_age_days are deleted."""
    old_file = tmp_path / "app.log.3"
    old_file.write_text("old")
    # Set mtime to 60 days ago
    old_mtime = time.time() - (60 * 86400)
    os.utime(old_file, (old_mtime, old_mtime))

    result = rotate_logs(tmp_path, max_age_days=30)

    assert result["deleted"] >= 1
    assert not old_file.exists()


# ---------------------------------------------------------------------------
# check_disk_usage
# ---------------------------------------------------------------------------


def test_check_disk_usage_returns_fields() -> None:
    """All 4 expected fields are present and numeric."""
    result = check_disk_usage("/")
    assert "total_gb" in result
    assert "used_gb" in result
    assert "free_gb" in result
    assert "used_pct" in result
    for key in ("total_gb", "used_gb", "free_gb", "used_pct"):
        assert isinstance(result[key], float)


def test_check_disk_usage_pct_range() -> None:
    """used_pct is between 0 and 100."""
    result = check_disk_usage("/")
    assert 0 <= result["used_pct"] <= 100


# ---------------------------------------------------------------------------
# cleanup_stale_files
# ---------------------------------------------------------------------------


def test_cleanup_stale_tmp(tmp_path: Path) -> None:
    """An old .tmp file is removed."""
    old_tmp = tmp_path / "cache.tmp"
    old_tmp.write_text("stale")
    old_mtime = time.time() - (10 * 86400)
    os.utime(old_tmp, (old_mtime, old_mtime))

    removed = cleanup_stale_files(tmp_path, max_age_days=7)

    assert removed == 1
    assert not old_tmp.exists()


def test_cleanup_stale_fresh(tmp_path: Path) -> None:
    """A recent .tmp file is kept."""
    fresh_tmp = tmp_path / "recent.tmp"
    fresh_tmp.write_text("fresh")

    removed = cleanup_stale_files(tmp_path, max_age_days=7)

    assert removed == 0
    assert fresh_tmp.exists()


def test_cleanup_stale_messages(tmp_path: Path) -> None:
    """Old service message JSON files are removed."""
    msg_dir = tmp_path / "service_messages"
    msg_dir.mkdir()
    old_msg = msg_dir / "msg-001.json"
    old_msg.write_text('{"text": "hello"}')
    old_mtime = time.time() - (10 * 86400)
    os.utime(old_msg, (old_mtime, old_mtime))

    removed = cleanup_stale_files(tmp_path, max_age_days=7)

    assert removed == 1
    assert not old_msg.exists()


def test_cleanup_stale_nested_tmp(tmp_path: Path) -> None:
    """Old .tmp files in subdirectories are also removed (rglob)."""
    sub = tmp_path / "sub" / "deep"
    sub.mkdir(parents=True)
    old_tmp = sub / "nested.tmp"
    old_tmp.write_text("nested-stale")
    old_mtime = time.time() - (10 * 86400)
    os.utime(old_tmp, (old_mtime, old_mtime))

    removed = cleanup_stale_files(tmp_path, max_age_days=7)

    assert removed == 1
    assert not old_tmp.exists()


# ---------------------------------------------------------------------------
# wal_size_bytes
# ---------------------------------------------------------------------------


def test_wal_size_exists(tmp_path: Path) -> None:
    """WAL file exists: returns its size."""
    db = tmp_path / "memory.db"
    db.touch()
    wal = tmp_path / "memory.db-wal"
    wal.write_bytes(b"\x00" * 4096)

    assert wal_size_bytes(db) == 4096


def test_wal_size_missing(tmp_path: Path) -> None:
    """WAL file does not exist: returns 0."""
    db = tmp_path / "memory.db"
    db.touch()

    assert wal_size_bytes(db) == 0
