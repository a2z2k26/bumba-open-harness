"""Async SQLite database: connection management, schema migration, FTS5, audit, utilities.

This module is a thin facade over the ``bridge.db`` subpackage. The
implementation was demote-split per issue #1305:

* connection lifecycle + execute/fetch helpers → ``bridge.db.connection``
* schema DDL + versioned migrations runner → ``bridge.db.migrations``
* DB-level maintenance (backup / health / rotation) → ``bridge.db.queries``

Callers continue to import ``Database`` (and the private ``_*`` constants,
preserved for back-compat with tests/tooling) from ``bridge.database`` —
no caller-side change is required.
"""

from __future__ import annotations

import logging
from pathlib import Path

import aiosqlite

from .db.connection import _PRAGMAS, ConnectionMixin
from .db.migrations import (
    _FTS_AND_TRIGGERS,
    _MIGRATIONS,
    _SCHEMA_VERSION_TABLE,
    _TABLES,
    MigrationsMixin,
)
from .db.queries import QueriesMixin

__all__ = ["Database"]

log = logging.getLogger(__name__)

# Re-exported private constants for back-compat. Some tests (e.g.
# ``tests/test_experiment_loop.py``) and tooling import these directly
# from ``bridge.database``; preserving the re-exports keeps the demote-
# split a pure reorg with no caller-side break.
__all__ += [
    "_PRAGMAS",
    "_TABLES",
    "_FTS_AND_TRIGGERS",
    "_SCHEMA_VERSION_TABLE",
    "_MIGRATIONS",
]


class Database(ConnectionMixin, MigrationsMixin, QueriesMixin):
    """Async SQLite database wrapper with migration and utilities.

    Composition: ``ConnectionMixin`` owns the connection lifecycle and
    parameterized execute/fetch helpers, ``MigrationsMixin`` owns
    ``migrate``/``_apply_migrations``/``get_schema_version``, and
    ``QueriesMixin`` owns ``backup``/``backup_with_verify``/
    ``rotate_backups``/``health_check``. See ``bridge/db/`` for the source.
    """

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self._conn: aiosqlite.Connection | None = None
