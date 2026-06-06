"""Tests for bridge.second_brain.backup — Sprint 05.0b (#1019).

Covers the daily vault-backup primitives:
- snapshot_vault: tar.gz output, exclusions, atomicity
- latest_snapshot: lexicographic = chronological
- ensure_snapshot_today: idempotent
- prune_old_snapshots: retention by mtime, safety floor

The vault is high-value (operator's Obsidian notes); these tests pin
the read-only / atomic / excluded-subtree contracts so a regression
that corrupts a snapshot is caught in CI.
"""

from __future__ import annotations

import os
import tarfile
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from bridge.second_brain.backup import (
    DEFAULT_KEEP_DAYS,
    EXCLUDED_DIR_NAMES,
    MIN_KEEP_DAYS,
    ensure_snapshot_today,
    latest_snapshot,
    prune_old_snapshots,
    snapshot_vault,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def fake_vault(tmp_path: Path) -> Path:
    """Build a small fake Obsidian vault with content + excluded subtrees."""
    vault = tmp_path / "MyVault"
    vault.mkdir()

    # Operator content (must be in snapshot).
    (vault / "Daily Notes").mkdir()
    (vault / "Daily Notes" / "2026-04-29.md").write_text("# Today\nNotes...\n")
    (vault / "Projects").mkdir()
    (vault / "Projects" / "bumba.md").write_text("# Bumba\nProject notes\n")
    (vault / "README.md").write_text("# My vault\n")

    # Excluded subtrees (must NOT be in snapshot).
    (vault / ".obsidian").mkdir()
    (vault / ".obsidian" / "workspace.json").write_text("{}")
    (vault / ".git").mkdir()
    (vault / ".git" / "config").write_text("[core]\n")
    (vault / ".trash").mkdir()
    (vault / ".trash" / "deleted.md").write_text("trashed\n")

    return vault


@pytest.fixture
def output_dir(tmp_path: Path) -> Path:
    """Isolated output dir for snapshots."""
    out = tmp_path / "snapshots"
    out.mkdir()
    return out


def _list_member_names(archive: Path) -> list[str]:
    with tarfile.open(archive, "r:gz") as tar:
        return tar.getnames()


# ---------------------------------------------------------------------------
# snapshot_vault
# ---------------------------------------------------------------------------


def test_snapshot_vault_produces_targz_with_md_files(
    fake_vault: Path, output_dir: Path,
) -> None:
    """A snapshot is a valid tar.gz containing every .md file from the vault."""
    snapshot = snapshot_vault(fake_vault, output_dir=output_dir)

    assert snapshot.exists()
    assert snapshot.suffix == ".gz"
    assert snapshot.name.endswith(".tar.gz")

    names = _list_member_names(snapshot)
    # arcname uses the vault basename so members live under MyVault/.
    md_members = [n for n in names if n.endswith(".md")]
    assert any(n.endswith("Daily Notes/2026-04-29.md") for n in md_members)
    assert any(n.endswith("Projects/bumba.md") for n in md_members)
    assert any(n.endswith("README.md") for n in md_members)


def test_snapshot_vault_excludes_obsidian_git_trash(
    fake_vault: Path, output_dir: Path,
) -> None:
    """The three excluded subtrees never appear in the archive."""
    snapshot = snapshot_vault(fake_vault, output_dir=output_dir)
    names = _list_member_names(snapshot)

    for excluded in EXCLUDED_DIR_NAMES:
        for name in names:
            parts = name.split("/")
            assert excluded not in parts, (
                f"excluded dir {excluded!r} leaked into archive at {name!r}"
            )


def test_snapshot_vault_atomic_no_partial_file_on_failure(
    fake_vault: Path, output_dir: Path,
) -> None:
    """If tarring crashes, the output_dir contains no canonical .tar.gz."""

    class BoomError(RuntimeError):
        pass

    def _explode(*_args, **_kwargs):
        raise BoomError("simulated crash mid-write")

    with patch("bridge.second_brain.backup.tarfile.open", side_effect=_explode):
        with pytest.raises(BoomError):
            snapshot_vault(fake_vault, output_dir=output_dir)

    # No final .tar.gz, and the .tmp.tar.gz cleanup ran.
    final_archives = list(output_dir.glob("*.tar.gz"))
    # Some implementations leave .tmp.tar.gz patterns — neither should remain
    # with content.
    canonical = [p for p in final_archives if not p.name.endswith(".tmp.tar.gz")]
    assert canonical == [], f"partial canonical snapshot left behind: {canonical}"


def test_snapshot_vault_missing_vault_raises_clear_error(
    tmp_path: Path, output_dir: Path,
) -> None:
    """Vault dir doesn't exist → FileNotFoundError, not generic crash."""
    missing = tmp_path / "nope"
    with pytest.raises(FileNotFoundError, match="vault_root does not exist"):
        snapshot_vault(missing, output_dir=output_dir)


# ---------------------------------------------------------------------------
# latest_snapshot
# ---------------------------------------------------------------------------


def test_latest_snapshot_empty_dir_returns_none(output_dir: Path) -> None:
    assert latest_snapshot(output_dir=output_dir) is None


def test_latest_snapshot_returns_most_recent_by_filename(
    output_dir: Path,
) -> None:
    """Filenames are YYYY-MM-DD.tar.gz; lexicographic order = chronological."""
    older = output_dir / "2026-04-01.tar.gz"
    middle = output_dir / "2026-04-15.tar.gz"
    newest = output_dir / "2026-04-29.tar.gz"
    for p in (older, middle, newest):
        p.write_bytes(b"fake-archive")

    # Add an in-flight tmp file that must be ignored.
    (output_dir / "2026-04-30.tmp.tar.gz").write_bytes(b"in-flight")

    assert latest_snapshot(output_dir=output_dir) == newest


# ---------------------------------------------------------------------------
# ensure_snapshot_today
# ---------------------------------------------------------------------------


def test_ensure_snapshot_today_idempotent(
    fake_vault: Path, output_dir: Path,
) -> None:
    """Calling twice in the same day returns the same path without recreating."""
    first = ensure_snapshot_today(fake_vault, output_dir=output_dir)
    first_mtime = first.stat().st_mtime

    # Second call: must short-circuit.
    second = ensure_snapshot_today(fake_vault, output_dir=output_dir)

    assert first == second
    assert second.stat().st_mtime == first_mtime, (
        "ensure_snapshot_today re-created an existing snapshot — not idempotent"
    )


def test_ensure_snapshot_today_creates_when_absent(
    fake_vault: Path, output_dir: Path,
) -> None:
    """First call (no snapshot today) creates one and returns its path."""
    assert latest_snapshot(output_dir=output_dir) is None

    snapshot = ensure_snapshot_today(fake_vault, output_dir=output_dir)
    assert snapshot.exists()
    assert snapshot.name.endswith(".tar.gz")
    assert latest_snapshot(output_dir=output_dir) == snapshot


# ---------------------------------------------------------------------------
# prune_old_snapshots
# ---------------------------------------------------------------------------


def _set_mtime(path: Path, days_old: float) -> None:
    """Backdate a file's atime/mtime by ``days_old`` days."""
    t = time.time() - (days_old * 86400)
    os.utime(path, (t, t))


def test_prune_old_snapshots_removes_files_older_than_keep_days(
    output_dir: Path,
) -> None:
    """Snapshots with mtime older than keep_days are deleted; newer ones stay."""
    fresh = output_dir / "2026-04-29.tar.gz"
    aging = output_dir / "2026-04-01.tar.gz"
    ancient = output_dir / "2025-12-01.tar.gz"
    for p in (fresh, aging, ancient):
        p.write_bytes(b"x")

    _set_mtime(fresh, days_old=2)      # recent — keep
    _set_mtime(aging, days_old=20)     # within 30d — keep
    _set_mtime(ancient, days_old=120)  # well outside 30d — drop

    removed = prune_old_snapshots(output_dir=output_dir, keep_days=30)

    assert removed == 1
    assert fresh.exists()
    assert aging.exists()
    assert not ancient.exists()


def test_prune_old_snapshots_default_keep_days_is_30(output_dir: Path) -> None:
    """The default contract is 30-day retention."""
    assert DEFAULT_KEEP_DAYS == 30


def test_prune_old_snapshots_safety_floor_rejects_short_retention(
    output_dir: Path,
) -> None:
    """Refuse to drop retention below the safety floor of 7 days."""
    with pytest.raises(ValueError, match="below safety floor"):
        prune_old_snapshots(output_dir=output_dir, keep_days=MIN_KEEP_DAYS - 1)


def test_prune_old_snapshots_ignores_tmp_files(output_dir: Path) -> None:
    """In-flight ``.tmp.tar.gz`` files are not pruned even when old."""
    in_flight = output_dir / "2025-01-01.tmp.tar.gz"
    in_flight.write_bytes(b"x")
    _set_mtime(in_flight, days_old=400)

    removed = prune_old_snapshots(output_dir=output_dir, keep_days=30)
    assert removed == 0
    assert in_flight.exists()


# ---------------------------------------------------------------------------
# Config flag — quick smoke that the field is on BridgeConfig and defaults OFF.
# ---------------------------------------------------------------------------


def test_second_brain_backup_flag_default_off() -> None:
    """Sprint 05.0b ships with the daemon-wiring flag OFF by default."""
    from bridge.config import BridgeConfig

    config = BridgeConfig()
    assert config.second_brain_backup_enabled is False
    assert hasattr(config, "second_brain_backup_enabled")


def test_second_brain_backup_flag_toml_mapping(tmp_path: Path) -> None:
    """The [second_brain] backup_enabled key threads into the dataclass field."""
    from bridge.config import load_config

    toml = tmp_path / "bridge.toml"
    toml.write_text(
        "[second_brain]\n"
        "backup_enabled = true\n",
    )
    config = load_config(toml, skip_secrets=True, skip_validation=True)
    assert config.second_brain_backup_enabled is True
