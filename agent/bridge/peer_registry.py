"""Issue #78 / #769 -- Agent registry data model for cross-machine coordination.

Maintains a SQLite-backed registry of peer agents with heartbeat tracking,
capability discovery, and stale-peer pruning.  Records survive process
restart by persisting to the bridge's ``data/memory.db`` (default) or any
other SQLite path supplied at construction time.

Schema is created with ``CREATE TABLE IF NOT EXISTS`` so it does not
collide with ``database.py``'s migration counter (currently at 9).

The schema is intentionally bridge-owned.  bumba-memory-mcp also has a
``peers`` table, but it is a discovery/messaging table with a different
contract and cannot round-trip this module's ``PeerRecord`` without loss.
See ``docs/architecture/peer-registry-ownership.md`` for the #2512 boundary
decision and the adapter conditions required before any future migration.
"""

from __future__ import annotations

import enum
import json
import logging
import sqlite3
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger(__name__)

PEER_REGISTRY_OWNERSHIP_DOC = "docs/architecture/peer-registry-ownership.md"


# ------------------------------------------------------------------
# Enums
# ------------------------------------------------------------------

class PeerStatus(enum.Enum):
    ONLINE = "online"
    OFFLINE = "offline"
    DEGRADED = "degraded"
    UNKNOWN = "unknown"


# ------------------------------------------------------------------
# Data classes
# ------------------------------------------------------------------

@dataclass(frozen=True)
class PeerMetadata:
    machine: str
    branch: str
    model: str
    version: str
    capabilities: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class PeerRecord:
    peer_id: str
    name: str
    status: PeerStatus
    metadata: PeerMetadata
    last_heartbeat: float
    registered_at: float
    tags: list[str] = field(default_factory=list)


# ------------------------------------------------------------------
# Schema (per issue #769 spec)
# ------------------------------------------------------------------

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS peers (
    agent_id TEXT PRIMARY KEY,
    hostname TEXT,
    api_url TEXT,
    health_status TEXT,
    registered_at INTEGER,
    last_heartbeat INTEGER,
    metadata TEXT
)
"""


# ------------------------------------------------------------------
# Registry
# ------------------------------------------------------------------

class PeerRegistry:
    """SQLite-backed peer registry with thread-safe access.

    Storage layout:
        - ``peers`` table in ``db_path`` (default ``data/memory.db``).
        - The schema is created lazily on first connection via
          ``CREATE TABLE IF NOT EXISTS`` so we never collide with
          ``database.py``'s numbered migration sequence.

    Architecture:
        - In-memory dict mirrors the table rows for fast reads and to
          preserve object-identity semantics required by existing tests.
        - Every mutator writes through to SQLite first, then updates the
          mirror.  On instantiation we load all existing rows into the
          mirror so records survive restart.
    """

    def __init__(self, db_path: Path | str = "data/memory.db") -> None:
        self._lock = threading.Lock()
        self._db_path = str(db_path)
        self._peers: dict[str, PeerRecord] = {}
        # Hold a single long-lived connection so ``:memory:`` databases
        # stay alive across calls and so we avoid reconnect overhead in
        # the hot path.  ``check_same_thread=False`` matches the rest of
        # the bridge's SQLite usage; all mutations go through
        # ``self._lock``.
        self._conn = sqlite3.connect(self._db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init_schema()
        self._reload_from_disk()

    # -- internal helpers --------------------------------------------

    def close(self) -> None:
        """Close the underlying SQLite connection.  Safe to call more
        than once.  Tests that simulate restart should drop their
        reference instead of calling this -- the OS will close it on
        garbage collection.
        """
        try:
            self._conn.close()
        except Exception as exc:
            log.warning("peer_registry sqlite close failed: %s", exc)

    def _init_schema(self) -> None:
        self._conn.execute(_SCHEMA_SQL)
        self._conn.commit()

    def _row_to_record(self, row: sqlite3.Row) -> PeerRecord:
        meta_blob = row["metadata"] or "{}"
        meta_dict = json.loads(meta_blob)
        peer_meta = PeerMetadata(
            machine=meta_dict.get("machine", ""),
            branch=meta_dict.get("branch", ""),
            model=meta_dict.get("model", ""),
            version=meta_dict.get("version", ""),
            capabilities=list(meta_dict.get("capabilities", [])),
        )
        name = meta_dict.get("name", row["agent_id"])
        tags = list(meta_dict.get("tags", []))
        status_value = row["health_status"] or PeerStatus.UNKNOWN.value
        try:
            status = PeerStatus(status_value)
        except ValueError:
            status = PeerStatus.UNKNOWN
        return PeerRecord(
            peer_id=row["agent_id"],
            name=name,
            status=status,
            metadata=peer_meta,
            last_heartbeat=float(row["last_heartbeat"] or 0),
            registered_at=float(row["registered_at"] or 0),
            tags=tags,
        )

    def _record_to_params(self, record: PeerRecord) -> tuple:
        meta_dict = {
            "machine": record.metadata.machine,
            "branch": record.metadata.branch,
            "model": record.metadata.model,
            "version": record.metadata.version,
            "capabilities": list(record.metadata.capabilities),
            "name": record.name,
            "tags": list(record.tags),
        }
        hostname = record.metadata.machine or ""
        api_url = ""  # Not part of the bridge's PeerRecord contract today.
        return (
            record.peer_id,
            hostname,
            api_url,
            record.status.value,
            int(record.registered_at),
            int(record.last_heartbeat),
            json.dumps(meta_dict, sort_keys=True),
        )

    def _reload_from_disk(self) -> None:
        rows = self._conn.execute("SELECT * FROM peers").fetchall()
        with self._lock:
            self._peers = {row["agent_id"]: self._row_to_record(row) for row in rows}

    def _write(self, record: PeerRecord) -> None:
        params = self._record_to_params(record)
        self._conn.execute(
            "INSERT OR REPLACE INTO peers ("
            "agent_id, hostname, api_url, health_status, "
            "registered_at, last_heartbeat, metadata"
            ") VALUES (?, ?, ?, ?, ?, ?, ?)",
            params,
        )
        self._conn.commit()

    def _delete(self, peer_id: str) -> None:
        self._conn.execute("DELETE FROM peers WHERE agent_id = ?", (peer_id,))
        self._conn.commit()

    # -- mutators ----------------------------------------------------

    def register(self, record: PeerRecord) -> None:
        """Add or replace a peer record."""
        self._write(record)
        with self._lock:
            self._peers[record.peer_id] = record
        log.info("Peer registered: %s (%s)", record.peer_id, record.name)

    def deregister(self, peer_id: str) -> bool:
        """Remove a peer.  Returns True if it existed."""
        with self._lock:
            removed = self._peers.pop(peer_id, None)
        if removed is None:
            return False
        self._delete(peer_id)
        log.info("Peer deregistered: %s", peer_id)
        return True

    def update_heartbeat(self, peer_id: str) -> bool:
        """Bump last_heartbeat to now.  Returns False if peer unknown."""
        now = time.time()
        with self._lock:
            old = self._peers.get(peer_id)
            if old is None:
                return False
            updated = PeerRecord(
                peer_id=old.peer_id,
                name=old.name,
                status=old.status,
                metadata=old.metadata,
                last_heartbeat=now,
                registered_at=old.registered_at,
                tags=old.tags,
            )
            self._peers[peer_id] = updated
        self._write(updated)
        return True

    def update_status(self, peer_id: str, status: PeerStatus) -> bool:
        """Change a peer's status.  Returns False if peer unknown."""
        with self._lock:
            old = self._peers.get(peer_id)
            if old is None:
                return False
            updated = PeerRecord(
                peer_id=old.peer_id,
                name=old.name,
                status=status,
                metadata=old.metadata,
                last_heartbeat=old.last_heartbeat,
                registered_at=old.registered_at,
                tags=old.tags,
            )
            self._peers[peer_id] = updated
        self._write(updated)
        return True

    # -- queries -----------------------------------------------------

    def get(self, peer_id: str) -> PeerRecord | None:
        with self._lock:
            return self._peers.get(peer_id)

    def list_peers(self, status: PeerStatus | None = None) -> list[PeerRecord]:
        with self._lock:
            values = sorted(
                self._peers.values(), key=lambda p: p.registered_at
            )
            if status is None:
                return list(values)
            return [p for p in values if p.status == status]

    def find_by_capability(self, capability: str) -> list[PeerRecord]:
        with self._lock:
            return [
                p for p in self._peers.values()
                if capability in p.metadata.capabilities
            ]

    # -- maintenance -------------------------------------------------

    def prune_stale(self, timeout_seconds: float = 180.0) -> list[str]:
        """Mark peers whose last heartbeat exceeds *timeout_seconds* as
        OFFLINE.  Returns list of peer_ids that were pruned.
        """
        now = time.time()
        pruned: list[str] = []
        updates: list[PeerRecord] = []
        with self._lock:
            for peer_id, record in list(self._peers.items()):
                if record.status == PeerStatus.OFFLINE:
                    continue
                if now - record.last_heartbeat > timeout_seconds:
                    new_record = PeerRecord(
                        peer_id=record.peer_id,
                        name=record.name,
                        status=PeerStatus.OFFLINE,
                        metadata=record.metadata,
                        last_heartbeat=record.last_heartbeat,
                        registered_at=record.registered_at,
                        tags=record.tags,
                    )
                    self._peers[peer_id] = new_record
                    updates.append(new_record)
                    pruned.append(peer_id)
        for record in updates:
            self._write(record)
        if pruned:
            log.info("Pruned stale peers: %s", pruned)
        return pruned
