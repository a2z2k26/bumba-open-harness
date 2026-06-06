"""Baseline ingest — record existing operator vault notes as grandfathered.

Sprint 05.0a (issue #1018) of the 2026-04-25 reference-audit bundle.
ADR signoff: ``agent/docs/architecture/second-brain.md`` Decision 1
(operator's existing Obsidian vault is the canonical wiki location,
``__AZ__`` 2026-05-01).

Why this exists
---------------
The operator's vault holds hundreds of pre-existing notes that were
authored before the second-brain subsystem ships. Without a baseline,
the day-1 lint pass (Sprint 05.09) would treat every existing page as
new and surface every cross-page contradiction / orphan / broken
wikilink as a proposal — flooding ``/proposals``.

This module records the full set of existing ``.md`` files (path +
content sha256 + mtime) at ingest time. Sprint 05.09's lint consults
``is_grandfathered`` and skips any file matched by path AND sha256.
Files the operator edits *after* baseline drift their hash and lose
grandfather status — exactly what we want.

Read-only contract
------------------
**This module never writes to the operator's vault.** It only reads
``.md`` files and computes hashes. All output is written to
``agent/data/second-brain-baseline.jsonl``.

Concept-only — no third-party source copied.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)


# Default baseline JSONL path, relative to the agent root. Resolved
# absolutely below so callers can override via the ``output`` /
# ``baseline`` keyword args.
_DEFAULT_BASELINE_PATH = (
    Path(__file__).resolve().parent.parent.parent
    / "data"
    / "second-brain-baseline.jsonl"
)

_HASH_CHUNK_BYTES = 65536


@dataclass(frozen=True)
class BaselineRecord:
    """One grandfathered note from the baseline ingest.

    Frozen so the in-memory baseline map is immutable once loaded.

    Attributes:
        path: Absolute path to the ``.md`` file at ingest time.
        sha256: Hex digest of the file's content. Matches against
            re-hashes determine whether a note has drifted.
        mtime: File modification timestamp at ingest (POSIX seconds).
        grandfathered_at: UTC datetime when this record was written.
    """

    path: Path
    sha256: str
    mtime: float
    grandfathered_at: datetime


def _hash_file(path: Path) -> str:
    """Compute SHA-256 of ``path`` content. Streams in chunks."""
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(_HASH_CHUNK_BYTES), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _walk_markdown_files(vault_root: Path):
    """Yield absolute paths of ``.md`` files under ``vault_root``.

    Skips any directory whose name starts with ``.`` (e.g. ``.git/``,
    ``.obsidian/``) and any file whose name starts with ``.``. Other
    file extensions (``.txt``, ``.json``) are ignored — only ``.md``.
    """
    for dirpath, dirnames, filenames in os.walk(vault_root):
        # Mutate dirnames in place to prune dot-directories from the walk.
        # os.walk reads this list to determine subsequent descents.
        dirnames[:] = sorted(d for d in dirnames if not d.startswith("."))
        for filename in sorted(filenames):
            if filename.startswith("."):
                continue
            if not filename.endswith(".md"):
                continue
            yield Path(dirpath) / filename


def _record_to_json(record: BaselineRecord) -> str:
    """Serialise a record to one JSONL line."""
    return json.dumps(
        {
            "path": str(record.path),
            "sha256": record.sha256,
            "mtime": record.mtime,
            "grandfathered_at": record.grandfathered_at.isoformat(),
        },
        ensure_ascii=False,
        sort_keys=True,
    )


def _record_from_json(line: str) -> BaselineRecord:
    """Parse one JSONL line into a record. Raises on malformed input."""
    data = json.loads(line)
    return BaselineRecord(
        path=Path(data["path"]),
        sha256=str(data["sha256"]),
        mtime=float(data["mtime"]),
        grandfathered_at=datetime.fromisoformat(data["grandfathered_at"]),
    )


def _atomic_write(target: Path, lines: list[str]) -> None:
    """Write ``lines`` to ``target`` atomically (write-tmp-then-rename)."""
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=target.name + ".",
        suffix=".tmp",
        dir=str(target.parent),
    )
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            for line in lines:
                fh.write(line)
                fh.write("\n")
        os.replace(tmp_path, target)
    except BaseException:
        # Best-effort cleanup; never mask the original error.
        try:
            tmp_path.unlink()
        except FileNotFoundError:
            pass
        raise


def load_baseline(path: Path | None = None) -> dict[Path, BaselineRecord]:
    """Read the baseline JSONL into a ``path → BaselineRecord`` map.

    Args:
        path: Optional override for the baseline JSONL location. When
            ``None``, uses ``agent/data/second-brain-baseline.jsonl``.

    Returns:
        Dict keyed by note path. Empty dict if the baseline file does
        not exist (treated as "no baseline yet" rather than an error).
    """
    target = Path(path) if path is not None else _DEFAULT_BASELINE_PATH
    if not target.is_file():
        return {}
    records: dict[Path, BaselineRecord] = {}
    with target.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                record = _record_from_json(line)
            except (ValueError, KeyError) as exc:
                logger.warning(
                    "second-brain baseline: skipping malformed line: %s", exc,
                )
                continue
            records[record.path] = record
    return records


def ingest_baseline(
    vault_root: Path,
    *,
    output: Path | None = None,
    enabled: bool = True,
) -> int:
    """Walk the operator's Obsidian vault and grandfather every ``.md`` file.

    Reads-only over the vault. Writes the baseline JSONL to
    ``agent/data/second-brain-baseline.jsonl`` (or ``output`` override).
    Idempotent: re-running on the same vault yields zero new records
    because identical (path, sha256, mtime) triples are deduplicated.

    Args:
        vault_root: Absolute path to the operator's vault root.
        output: Optional override for the baseline JSONL location.
        enabled: Gate from ``BridgeConfig.second_brain_baseline_enabled``.
            When False the function is a no-op (returns 0). Defaults to
            True so callers that don't thread config are unaffected.

    Returns:
        The count of NEW records appended on this invocation. Zero on
        a no-op re-run (or when ``enabled=False``); total record count
        on first ingest.

    Raises:
        FileNotFoundError: ``vault_root`` does not exist.
        NotADirectoryError: ``vault_root`` exists but is not a directory.
    """
    if not enabled:
        logger.debug("second-brain baseline ingest skipped: second_brain_baseline_enabled=False")
        return 0

    vault_root = Path(vault_root)
    if not vault_root.exists():
        raise FileNotFoundError(f"Vault root not found: {vault_root}")
    if not vault_root.is_dir():
        raise NotADirectoryError(f"Vault root is not a directory: {vault_root}")

    target = Path(output) if output is not None else _DEFAULT_BASELINE_PATH
    existing = load_baseline(target)

    # A record is "the same" if path + sha256 + mtime all match. Path
    # alone is too loose (operator could rename then re-author), and
    # sha256 alone collapses two identical-content notes at different
    # paths.
    existing_keys: set[tuple[Path, str, float]] = {
        (rec.path, rec.sha256, rec.mtime) for rec in existing.values()
    }

    now = datetime.now(timezone.utc)
    new_records: list[BaselineRecord] = []
    for md_path in _walk_markdown_files(vault_root):
        try:
            stat = md_path.stat()
            sha = _hash_file(md_path)
        except OSError as exc:
            logger.warning(
                "second-brain baseline: cannot read %s: %s", md_path, exc,
            )
            continue
        key = (md_path, sha, stat.st_mtime)
        if key in existing_keys:
            continue
        new_records.append(
            BaselineRecord(
                path=md_path,
                sha256=sha,
                mtime=stat.st_mtime,
                grandfathered_at=now,
            ),
        )

    if not new_records:
        # Nothing changed — leave any existing file untouched so its
        # mtime is a reliable "last actual ingest" signal. Empty vault
        # with no baseline yet: no file is written (spec: "Empty vault →
        # 0 records, no error").
        logger.info(
            "second-brain baseline: no new records (%d existing)", len(existing),
        )
        return 0

    # Merge: keep all existing records, append new ones. The merged set
    # is keyed by path so re-hashed entries replace prior versions of
    # the same path (defensive — should not occur because we filter via
    # existing_keys, but cheap to keep deterministic).
    merged: dict[Path, BaselineRecord] = dict(existing)
    for rec in new_records:
        merged[rec.path] = rec

    lines = [
        _record_to_json(merged[p])
        for p in sorted(merged.keys(), key=lambda x: str(x))
    ]
    _atomic_write(target, lines)
    logger.info(
        "second-brain baseline: ingested %d new records (%d total) → %s",
        len(new_records), len(merged), target,
    )
    return len(new_records)


def is_grandfathered(
    path: Path,
    *,
    baseline: Path | None = None,
) -> bool:
    """Return True if ``path`` was grandfathered by a prior baseline ingest.

    Matches by path AND sha256: a file present in the baseline whose
    content has since drifted (operator edit) is no longer
    grandfathered. Files not in the baseline at all (post-baseline new
    notes) are also not grandfathered — the lint subsystem applies its
    full rule set to them.

    Args:
        path: Absolute path to the note.
        baseline: Optional override for the baseline JSONL location.

    Returns:
        True iff the path is in the baseline and its current content
        matches the grandfathered hash.
    """
    records = load_baseline(baseline)
    record = records.get(Path(path))
    if record is None:
        return False
    try:
        current_sha = _hash_file(Path(path))
    except (OSError, FileNotFoundError):
        return False
    return current_sha == record.sha256
