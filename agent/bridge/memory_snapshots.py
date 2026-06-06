"""Agent memory snapshot protocol.

Spawned Claude subprocesses write JSON snapshots to data/memory/snapshots/.
The bridge ingests them into the knowledge store and daily log.
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass

SALIENCE_BY_CATEGORY: dict[str, float] = {
    "decision": 0.9,
    "error": 0.8,
    "lesson": 0.75,
    "insight": 0.7,
    "reference": 0.6,
    "general": 0.5,
}


def salience_for_category(category: str) -> float:
    """Return a default salience float for a given category string.

    Known categories: decision→0.9, error→0.8, lesson→0.75, insight→0.7,
    reference→0.6, general→0.5.  Anything else → 0.4.
    """
    return SALIENCE_BY_CATEGORY.get(category.lower(), 0.4)


@dataclass
class MemorySnapshot:
    """A single knowledge item persisted by a spawned agent subprocess."""

    category: str
    key: str
    value: str
    source: str
    salience: float
    timestamp: str  # ISO 8601


class SnapshotWriter:
    """Used by spawned agents to persist discoveries to disk.

    The bridge later ingests these via SnapshotIngester.
    """

    def __init__(self, snapshots_dir: Path) -> None:
        self._dir = snapshots_dir

    def write(self, snapshot: MemorySnapshot) -> Path:
        """Serialize *snapshot* to JSON and write to the snapshots directory.

        Returns the Path of the written file.
        File name: ``<epoch_ms>_<key_slug>.json``
        """
        self._dir.mkdir(parents=True, exist_ok=True)
        slug = re.sub(r"[^\w-]", "_", snapshot.key.lower())[:40]
        ts_ms = int(time.time() * 1000)
        filename = f"{ts_ms}_{slug}.json"
        path = self._dir / filename
        path.write_text(json.dumps(asdict(snapshot), indent=2), encoding="utf-8")
        return path

    def get_snapshot_instructions(self) -> str:
        """Return a prompt fragment explaining the snapshot protocol to agents."""
        return (
            f"## Memory Snapshot Protocol\n\n"
            f"If you discover something worth remembering, write a snapshot to:\n"
            f"{self._dir}/<timestamp>_<key>.json\n\n"
            f"Format:\n"
            f"{{\n"
            f'  "category": "decision|error|lesson|insight|reference|general",\n'
            f'  "key": "unique-kebab-case-identifier",\n'
            f'  "value": "The knowledge to store (markdown ok)",\n'
            f'  "source": "brief description of where this came from",\n'
            f'  "salience": 0.0-1.0,\n'
            f'  "timestamp": "ISO8601 timestamp"\n'
            f"}}\n"
        )


class SnapshotIngester:
    """Bridge-side component that picks up and ingests agent snapshots."""

    def __init__(self, snapshots_dir: Path) -> None:
        self._dir = snapshots_dir

    # ------------------------------------------------------------------
    # Discovery
    # ------------------------------------------------------------------

    def get_pending_snapshots(self) -> list[Path]:
        """Return sorted list of unprocessed ``.json`` files in the snapshot dir."""
        if not self._dir.exists():
            return []
        return sorted(
            p
            for p in self._dir.iterdir()
            if p.suffix == ".json"
        )

    # ------------------------------------------------------------------
    # Parsing
    # ------------------------------------------------------------------

    def ingest(self, snapshot_path: Path) -> MemorySnapshot:
        """Parse a snapshot JSON file and return a :class:`MemorySnapshot`.

        Raises :class:`ValueError` on JSON decode errors or missing fields.
        """
        try:
            data = json.loads(snapshot_path.read_text(encoding="utf-8"))
            return MemorySnapshot(
                category=data["category"],
                key=data["key"],
                value=data["value"],
                source=data["source"],
                salience=float(data.get("salience", 0.5)),
                timestamp=data.get(
                    "timestamp", datetime.now(timezone.utc).isoformat()
                ),
            )
        except (json.JSONDecodeError, KeyError) as exc:
            raise ValueError(f"Invalid snapshot {snapshot_path}: {exc}") from exc

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def mark_processed(self, snapshot_path: Path) -> Path:
        """Rename *snapshot_path* from ``.json`` to ``.processed``.

        Returns the new path.
        """
        new_path = snapshot_path.with_suffix(".processed")
        snapshot_path.rename(new_path)
        return new_path

    # ------------------------------------------------------------------
    # Deduplication
    # ------------------------------------------------------------------

    def deduplicate(self, snapshot: MemorySnapshot, existing_keys: set[str]) -> bool:
        """Return ``True`` if *snapshot* is new (key not in *existing_keys*).

        Return ``False`` if the key has already been stored.
        """
        return snapshot.key not in existing_keys


# ---------------------------------------------------------------------------
# Async bridge helper
# ---------------------------------------------------------------------------

async def ingest_pending_snapshots(
    snapshots_dir: Path,
    memory_store,  # bridge.memory.Memory
    daily_log=None,  # bridge.daily_log.DailyLog | None
) -> int:
    """Scan *snapshots_dir*, ingest each pending snapshot, return count ingested.

    For each valid snapshot:
    1. Parse it.
    2. Deduplicate against keys already stored in *memory_store*.
    3. Store new snapshots in the knowledge table via *memory_store*.
    4. Optionally append a summary line to *daily_log*.
    5. Mark the snapshot file as processed.

    Invalid files are marked processed and skipped (errors logged to stderr).
    """
    import logging

    log = logging.getLogger(__name__)
    ingester = SnapshotIngester(snapshots_dir)
    pending = ingester.get_pending_snapshots()
    if not pending:
        return 0

    # Fetch existing keys for deduplication
    existing_keys: set[str] = set()
    try:
        rows = await memory_store._db.fetchall(
            "SELECT key FROM knowledge", ()
        )
        existing_keys = {r[0] for r in rows}
    except Exception as exc:  # pragma: no cover
        log.warning("Could not fetch existing knowledge keys: %s", exc)

    ingested = 0
    for path in pending:
        try:
            snap = ingester.ingest(path)
        except ValueError as exc:
            log.warning("Skipping invalid snapshot %s: %s", path.name, exc)
            ingester.mark_processed(path)
            continue

        if not ingester.deduplicate(snap, existing_keys):
            log.debug("Duplicate snapshot key=%s, skipping", snap.key)
            ingester.mark_processed(path)
            continue

        # Persist to knowledge store.
        #
        # Sprint 05.05: ``Memory.store_knowledge`` does NOT accept a
        # ``salience`` kwarg.  Passing it would raise ``TypeError`` the
        # moment any producer wires the snapshot pipeline (currently
        # latent — no producer exists yet).  Preserve the original
        # author's intent — bump salience for the freshly-stored entry
        # — by calling ``Memory._reinforce_entries([snap.key])`` after
        # the insert.  This matches every other read path's salience
        # treatment and keeps ``store_knowledge``'s signature stable.
        try:
            await memory_store.store_knowledge(
                category=snap.category,
                key=snap.key,
                value=snap.value,
                source=snap.source,
            )
            await memory_store._reinforce_entries([snap.key])
            existing_keys.add(snap.key)
            ingested += 1
        except Exception as exc:  # pragma: no cover
            log.error("Failed to store snapshot key=%s: %s", snap.key, exc)
            continue

        # Append to daily log if provided
        if daily_log is not None:
            try:
                daily_log.append(
                    f"[snapshot] {snap.category}/{snap.key}: {snap.value[:120]}",
                    category="snapshot",
                )
            except Exception as exc:  # pragma: no cover
                log.warning("Failed to append snapshot to daily log: %s", exc)

        ingester.mark_processed(path)

    return ingested
