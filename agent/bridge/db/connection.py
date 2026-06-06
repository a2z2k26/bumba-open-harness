"""Async SQLite connection lifecycle and per-statement execute/fetch helpers.

Extracted from ``bridge/database.py`` as part of the issue #1305 demote-split.
Holds the six SQLite pragmas applied on every connect, plus the
``ConnectionMixin`` that owns connect/close/checkpoint and the
parameterized execute/fetchone/fetchall/commit thin wrappers.

The mixin assumes the concrete class provides:

* ``self.db_path`` — ``pathlib.Path`` of the SQLite file.
* ``self._conn`` — ``aiosqlite.Connection | None`` storage slot.

``Database`` (in ``bridge/database.py``) provides both.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import aiosqlite

# -- S35: Connection and pragmas --

# SqlParams: the value side of parameterized statements.
# aiosqlite forwards any tuple of Python primitives that the underlying
# sqlite3 adapter handles (str, int, float, bytes, bool, None, and
# adapter-registered types such as datetime). We keep this as
# ``tuple[Any, ...]`` rather than a narrower union because (a) callers
# already pass mixed Optional[primitive] values and (b) sqlite3's
# adapter registry is open-ended at runtime.
SqlParams = tuple[Any, ...]

_PRAGMAS = [
    "PRAGMA journal_mode = WAL;",
    "PRAGMA busy_timeout = 5000;",
    "PRAGMA synchronous = NORMAL;",
    "PRAGMA cache_size = -64000;",
    "PRAGMA foreign_keys = ON;",
    "PRAGMA temp_store = MEMORY;",
]


class ConnectionMixin:
    """Async SQLite connection lifecycle + per-statement helpers."""

    # These slots are populated by the concrete ``Database`` class.
    db_path: Path
    _conn: aiosqlite.Connection | None

    def _ensure_connected(self) -> aiosqlite.Connection:
        """Return the connection or raise if not connected."""
        if self._conn is None:
            raise RuntimeError(
                "Database not connected. Call connect() before executing queries."
            )
        return self._conn

    async def connect(self) -> None:
        """Open connection and initialize pragmas."""
        self._conn = await aiosqlite.connect(self.db_path)
        self._conn.row_factory = aiosqlite.Row
        await self._init_pragmas()

    async def _init_pragmas(self) -> None:
        """Apply all 6 pragmas on connection open."""
        conn = self._ensure_connected()
        for pragma in _PRAGMAS:
            await conn.execute(pragma)

    async def close(self) -> None:
        """Checkpoint WAL and close connection."""
        if self._conn:
            try:
                await self._conn.execute("PRAGMA wal_checkpoint(TRUNCATE);")
            except Exception:
                pass
            await self._conn.close()
            self._conn = None

    async def execute(self, sql: str, params: SqlParams = ()) -> aiosqlite.Cursor:
        """Execute a single SQL statement."""
        conn = self._ensure_connected()
        return await conn.execute(sql, params)

    async def executemany(
        self, sql: str, params_seq: list[SqlParams]
    ) -> aiosqlite.Cursor:
        """Execute SQL with multiple parameter sets."""
        conn = self._ensure_connected()
        return await conn.executemany(sql, params_seq)

    async def fetchone(
        self, sql: str, params: SqlParams = ()
    ) -> aiosqlite.Row | None:
        """Execute and fetch one row."""
        conn = self._ensure_connected()
        cursor = await conn.execute(sql, params)
        return await cursor.fetchone()

    async def fetchall(
        self, sql: str, params: SqlParams = ()
    ) -> list[aiosqlite.Row]:
        """Execute and fetch all rows.

        ``aiosqlite.Cursor.fetchall`` is typed as ``Iterable[Row]`` but in
        practice always returns a list; the explicit ``list(...)`` makes
        the conversion explicit and satisfies the declared return type.
        """
        conn = self._ensure_connected()
        cursor = await conn.execute(sql, params)
        return list(await cursor.fetchall())

    async def commit(self) -> None:
        """Commit the current transaction."""
        conn = self._ensure_connected()
        await conn.commit()

    async def checkpoint(self) -> None:
        """Force a WAL checkpoint."""
        conn = self._ensure_connected()
        await conn.execute("PRAGMA wal_checkpoint(TRUNCATE);")
