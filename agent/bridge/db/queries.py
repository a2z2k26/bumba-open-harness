"""Database-level maintenance helpers: backup, health, rotation.

Extracted from ``bridge/database.py`` as part of the issue #1305 demote-split.

The umbrella issue named this slot ``queries.py`` on the assumption that
``bridge/database.py`` housed per-table CRUD helpers. In practice the
``Database`` class exposes only the parameterized ``execute``/``fetchone``/
``fetchall`` primitives plus database-level maintenance (backup, health
check, log rotation); per-table CRUD lives in caller modules such as
``bridge.memory``, ``bridge.session_manager``, ``bridge.message_queue``,
and the various ``*_store.py`` modules. The slot name is preserved here
for parity with the issue body — these helpers are the closest analogue
to "queries" the module actually owns.

The mixin assumes the concrete class provides:

* ``self.db_path`` — ``pathlib.Path`` of the SQLite file.
* ``self._ensure_connected()`` (from ``ConnectionMixin``).
* ``self.fetchone()`` (from ``ConnectionMixin``).
"""

from __future__ import annotations

import logging
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

import aiosqlite

from .connection import SqlParams

log = logging.getLogger(__name__)


class QueriesMixin:
    """Database-level maintenance helpers."""

    # Provided by the concrete ``Database`` class.
    db_path: Path

    # Provided by ConnectionMixin.
    def _ensure_connected(self) -> aiosqlite.Connection: ...  # type: ignore[empty-body]

    async def fetchone(
        self, sql: str, params: SqlParams = ()
    ) -> aiosqlite.Row | None: ...

    # -- S37: Utilities --

    async def backup(self, dest_path: str | Path) -> Path:
        """Create a hot backup of the database using file copy after checkpoint."""
        dest = Path(dest_path)
        conn = self._ensure_connected()

        await conn.execute("PRAGMA wal_checkpoint(TRUNCATE);")
        shutil.copy2(self.db_path, dest)
        return dest

    async def backup_with_verify(self, dest_path: str | Path) -> tuple[Path, bool]:
        """Create a backup and verify its integrity.

        Returns (backup_path, integrity_ok).
        """
        dest = await self.backup(dest_path)

        try:
            verify_conn = await aiosqlite.connect(dest)
            cursor = await verify_conn.execute("PRAGMA integrity_check;")
            row = await cursor.fetchone()
            ok = row[0] == "ok" if row else False
            await verify_conn.close()
        except Exception as e:
            log.error("Backup integrity check failed: %s", e)
            ok = False

        return dest, ok

    @staticmethod
    def rotate_backups(backup_dir: Path, keep_daily: int = 7, keep_weekly: int = 4) -> int:
        """Remove old backups, keeping the most recent daily and weekly.

        Backup files must match pattern: memory-YYYYMMDD-HHMMSS.db
        Returns count of removed files.
        """
        import re as _re
        from datetime import timedelta

        pattern = _re.compile(r"memory-(\d{8})-(\d{6})\.db$")
        backups = []
        for f in sorted(backup_dir.glob("memory-*.db"), reverse=True):
            m = pattern.match(f.name)
            if m:
                backups.append(f)

        if not backups:
            return 0

        # Keep recent daily
        keep = set(backups[:keep_daily])

        # Keep weekly (one per week, going back)
        now = datetime.now()
        for week in range(keep_weekly):
            cutoff = now - timedelta(weeks=week + 1)
            for b in backups:
                m = pattern.match(b.name)
                if m:
                    date_str = m.group(1)
                    try:
                        file_date = datetime.strptime(date_str, "%Y%m%d")
                        if file_date >= cutoff:
                            keep.add(b)
                            break
                    except ValueError:
                        continue

        removed = 0
        for b in backups:
            if b not in keep:
                b.unlink()
                removed += 1

        return removed

    async def health_check(self) -> dict[str, Any]:
        """Run integrity check and return health metrics."""
        self._ensure_connected()

        integrity = await self.fetchone("PRAGMA integrity_check;")
        integrity_ok = integrity[0] == "ok" if integrity else False

        db_size = self.db_path.stat().st_size if self.db_path.exists() else 0

        wal_path = self.db_path.with_suffix(".db-wal")
        wal_size = wal_path.stat().st_size if wal_path.exists() else 0

        table_counts: dict[str, int] = {}
        for table in ("knowledge", "conversations", "sessions", "message_queue", "audit_log"):
            row = await self.fetchone(f"SELECT COUNT(*) FROM {table};")  # noqa: S608 - static table list
            table_counts[table] = int(row[0]) if row else 0

        return {
            "integrity_ok": integrity_ok,
            "db_size_bytes": db_size,
            "wal_size_bytes": wal_size,
            "table_counts": table_counts,
            "checked_at": datetime.now().isoformat(),
        }
