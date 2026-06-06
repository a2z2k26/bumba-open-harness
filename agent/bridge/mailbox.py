"""Mailbox — dual-DB single-writer subprocess primitive.

Two subsystems (experiment_loop, factory implement) need to write structured
data from worker subprocesses back to the bridge while avoiding the cardinal
SQLite write-conflict trap: never let two processes write to the same SQLite
file concurrently.

The mailbox solves this with a dual-DB single-writer pattern:

- Worker DB: ``data/<name>-mbox-worker.sqlite`` — only the subprocess writes;
  the bridge reads.
- Bridge DB: ``data/<name>-mbox-bridge.sqlite`` — only the bridge writes; the
  subprocess reads.

Both are single-writer; no contention possible. Mailbox messages have a
``direction`` (``worker_to_bridge`` / ``bridge_to_worker``), an opaque
``payload`` (JSON), and a ``seq`` for ordering. Idempotent reads via the
``after_seq`` cursor.

Concept-only port informed by the Karpathy NanoClaw v2 dual-DB pattern; no
source code copy.
"""

from __future__ import annotations

import contextlib
import json
import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator, Literal, Optional

Direction = Literal["worker_to_bridge", "bridge_to_worker"]
Role = Literal["bridge", "worker"]


@dataclass(frozen=True)
class MailboxMessage:
    """One mailbox message. Persisted in either the worker DB or bridge DB."""

    seq: int
    direction: Direction
    payload: dict
    enqueued_at_iso: str
    correlation_id: Optional[str] = None


@dataclass(frozen=True)
class MailboxConfig:
    """Mailbox identity + storage paths."""

    name: str
    data_dir: Path
    schema_version: int = 1

    @property
    def worker_db_path(self) -> Path:
        return self.data_dir / f"{self.name}-mbox-worker.sqlite"

    @property
    def bridge_db_path(self) -> Path:
        return self.data_dir / f"{self.name}-mbox-bridge.sqlite"


# Schema for both DBs (identical layout, different writers).
_SCHEMA = """
CREATE TABLE IF NOT EXISTS mailbox_messages (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    direction TEXT NOT NULL CHECK(direction IN ('worker_to_bridge','bridge_to_worker')),
    payload TEXT NOT NULL,
    enqueued_at_iso TEXT NOT NULL,
    correlation_id TEXT
);
CREATE INDEX IF NOT EXISTS idx_mailbox_direction_seq
    ON mailbox_messages(direction, seq);
"""

# WAL + busy_timeout — single-writer assumed, but readers may overlap on the
# read-side DB and we want to be polite under concurrent access.
_PRAGMAS = (
    "PRAGMA journal_mode=WAL;",
    "PRAGMA busy_timeout=3000;",
    "PRAGMA synchronous=NORMAL;",
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _connect(path: Path) -> sqlite3.Connection:
    """Open a SQLite connection with WAL pragmas applied.

    ``check_same_thread=False`` lets a cached write connection be used from
    a worker thread that's distinct from the constructor thread — safe under
    the mailbox's single-writer invariant (the API never issues concurrent
    writes on the same connection).
    """
    conn = sqlite3.connect(
        str(path),
        isolation_level=None,
        timeout=3.0,
        check_same_thread=False,
    )
    for pragma in _PRAGMAS:
        conn.execute(pragma)
    return conn


class Mailbox:
    """Dual-DB single-writer mailbox.

    Both processes use the same Mailbox API but only write to their own DB.

    - The bridge calls ``Mailbox(config, role='bridge')``. It writes to the
      bridge DB (direction ``bridge_to_worker``) and reads the worker DB
      (direction ``worker_to_bridge``).
    - The worker calls ``Mailbox(config, role='worker')``. It writes to the
      worker DB (direction ``worker_to_bridge``) and reads the bridge DB
      (direction ``bridge_to_worker``).

    Each DB is single-writer. No SQLite WAL corruption possible.
    """

    def __init__(self, config: MailboxConfig, *, role: Role) -> None:
        if role not in ("bridge", "worker"):
            raise ValueError(f"role must be 'bridge' or 'worker', got {role!r}")
        self._config = config
        self._role = role
        if role == "bridge":
            self._write_path = config.bridge_db_path
            self._read_path = config.worker_db_path
            self._send_direction: Direction = "bridge_to_worker"
            self._read_direction: Direction = "worker_to_bridge"
        else:
            self._write_path = config.worker_db_path
            self._read_path = config.bridge_db_path
            self._send_direction = "worker_to_bridge"
            self._read_direction = "bridge_to_worker"
        self._write_conn: Optional[sqlite3.Connection] = None
        # Serializes API calls on the single shared write connection. The
        # single-writer DB invariant is preserved per-role; the lock just
        # protects the cached connection across stray multi-thread callers.
        self._write_lock = threading.Lock()

    # -- lifecycle ---------------------------------------------------------

    @property
    def role(self) -> Role:
        return self._role

    @property
    def config(self) -> MailboxConfig:
        return self._config

    def init_db(self) -> None:
        """Idempotently create schema on this role's write-side DB.

        Sets WAL mode + busy_timeout. Safe to call multiple times.
        """
        self._config.data_dir.mkdir(parents=True, exist_ok=True)
        with self._write_lock:
            conn = self._ensure_write_conn()
            conn.executescript(_SCHEMA)

    def close(self) -> None:
        """Close the write-side connection if open. Idempotent."""
        with self._write_lock:
            if self._write_conn is not None:
                with contextlib.suppress(sqlite3.Error):
                    self._write_conn.close()
                self._write_conn = None

    # -- writes ------------------------------------------------------------

    def send(
        self,
        payload: dict,
        *,
        correlation_id: Optional[str] = None,
    ) -> int:
        """Append a message in the role's outbound direction.

        Returns the assigned ``seq``. Atomic — single INSERT + commit. Raises
        ``ValueError`` if ``payload`` is not JSON-serializable.
        """
        try:
            payload_json = json.dumps(payload)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"payload must be JSON-serializable: {exc}"
            ) from exc

        with self._write_lock:
            conn = self._ensure_write_conn()
            # Ensure schema exists even if init_db() was skipped.
            conn.executescript(_SCHEMA)

            cursor = conn.execute(
                """INSERT INTO mailbox_messages
                       (direction, payload, enqueued_at_iso, correlation_id)
                   VALUES (?, ?, ?, ?)""",
                (
                    self._send_direction,
                    payload_json,
                    _now_iso(),
                    correlation_id,
                ),
            )
            seq = cursor.lastrowid
        if seq is None:
            raise RuntimeError("INSERT into mailbox_messages returned no rowid")
        return int(seq)

    # -- reads -------------------------------------------------------------

    def read_since(
        self,
        *,
        after_seq: int = 0,
        limit: int = 100,
    ) -> list[MailboxMessage]:
        """Read messages in the role's inbound direction with seq > ``after_seq``.

        Returns up to ``limit`` messages, ordered by seq ascending. Defensive on
        missing DB — returns ``[]`` if the other role hasn't initialized yet.
        """
        if not self._read_path.exists():
            return []
        if limit <= 0:
            return []
        try:
            with contextlib.closing(_connect(self._read_path)) as conn:
                rows = conn.execute(
                    """SELECT seq, direction, payload, enqueued_at_iso, correlation_id
                       FROM mailbox_messages
                       WHERE direction = ? AND seq > ?
                       ORDER BY seq ASC
                       LIMIT ?""",
                    (self._read_direction, int(after_seq), int(limit)),
                ).fetchall()
        except sqlite3.OperationalError:
            # Other side created the file but hasn't written schema yet.
            return []

        return [
            MailboxMessage(
                seq=int(row[0]),
                direction=row[1],
                payload=json.loads(row[2]),
                enqueued_at_iso=row[3],
                correlation_id=row[4],
            )
            for row in rows
        ]

    def latest_seq(self) -> int:
        """Return the highest seq in the inbound direction. 0 if empty/missing."""
        if not self._read_path.exists():
            return 0
        try:
            with contextlib.closing(_connect(self._read_path)) as conn:
                row = conn.execute(
                    """SELECT MAX(seq) FROM mailbox_messages WHERE direction = ?""",
                    (self._read_direction,),
                ).fetchone()
        except sqlite3.OperationalError:
            return 0
        if row is None or row[0] is None:
            return 0
        return int(row[0])

    # -- maintenance -------------------------------------------------------

    def vacuum(self, *, keep_last_n: int = 10000) -> int:
        """Trim the OUTBOUND-direction table to keep only the last N messages.

        Safe — only affects the role's write DB. Returns count deleted.
        """
        if keep_last_n < 0:
            raise ValueError("keep_last_n must be >= 0")
        with self._write_lock:
            conn = self._ensure_write_conn()
            # Find the cutoff seq: we want to keep the top N rows by seq for
            # our send direction.
            cutoff_row = conn.execute(
                """SELECT seq FROM mailbox_messages
                   WHERE direction = ?
                   ORDER BY seq DESC
                   LIMIT 1 OFFSET ?""",
                (self._send_direction, keep_last_n),
            ).fetchone()
            if cutoff_row is None:
                return 0
            cutoff_seq = int(cutoff_row[0])
            cursor = conn.execute(
                """DELETE FROM mailbox_messages
                   WHERE direction = ? AND seq <= ?""",
                (self._send_direction, cutoff_seq),
            )
            return int(cursor.rowcount or 0)

    # -- internals ---------------------------------------------------------

    def _ensure_write_conn(self) -> sqlite3.Connection:
        if self._write_conn is None:
            self._config.data_dir.mkdir(parents=True, exist_ok=True)
            self._write_conn = _connect(self._write_path)
        return self._write_conn


@contextlib.contextmanager
def open_mailbox(config: MailboxConfig, *, role: Role) -> Iterator[Mailbox]:
    """Context manager that ``init_db()``'s on enter and closes on exit."""
    mailbox = Mailbox(config, role=role)
    try:
        mailbox.init_db()
        yield mailbox
    finally:
        mailbox.close()
