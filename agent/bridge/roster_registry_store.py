"""SQLite-backed persistence for operator-registered roster specialists.

Sprint RR.1 (issue #2593) — the storage + validation layer behind the
self-serve roster registry. The chief's ``Roster`` is YAML-derived and
read-only (``teams/_factory.py::roster_from_department_config``); this store
holds the operator's runtime *overlay* — specialists added without a YAML
edit or redeploy. RR.2 appends these to the YAML base at roster-build time.

Mirrors ``bridge/work_order_store.py`` conventions: ``sqlite3.connect`` with
``PRAGMA journal_mode=WAL``, schema via ``executescript``, and **parameterized
queries only** (no string interpolation into SQL).

The load-bearing seam (the #1 risk flagged in the spec's seam-audit table):
the chief agent is cached on ``(team_name, agent_name)`` only
(``teams/_agent_cache.py``); the roster overlay is NOT part of the cache key.
So a registration is invisible until the team's cached chief is invalidated.
``register`` / ``unregister`` therefore fire an ``on_change(department)``
callback AFTER a successful write — wired to ``AgentCache.invalidate`` in
production so the next chief build for that department picks up the overlay.
Absent callback is a clean no-op (tests, ad-hoc callers).
"""

from __future__ import annotations

import logging
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

# A handle the store consults at registration time to validate against the
# live department configs. Returns the department's config (anything exposing
# an ``employees`` iterable of objects with a ``name``) or ``None`` when the
# department does not exist. In production this wraps
# ``DepartmentRegistry.get_config`` (which raises KeyError on unknown depts —
# the adapter at the call site catches that and returns None). Typed loosely
# so tests can pass a lightweight fake.
ConfigLookup = Callable[[str], Any]

_SCHEMA = """
CREATE TABLE IF NOT EXISTS registered_specialists (
    department    TEXT NOT NULL,
    name          TEXT NOT NULL,
    agent_ref     TEXT NOT NULL,
    registered_at TEXT NOT NULL,
    registered_by TEXT NOT NULL DEFAULT 'operator',
    PRIMARY KEY (department, name)
);
CREATE INDEX IF NOT EXISTS idx_rs_department ON registered_specialists(department);
"""


@dataclass(frozen=True)
class RegisteredSpecialist:
    """One operator-registered specialist (the overlay row).

    ``agent_ref`` names an existing employee agent config in ``department`` —
    it is NOT a brand-new specialist definition (that is WS4 territory). RR.2
    resolves ``agent_ref`` to a full ``SpecialistSpec`` at roster-build time.
    """

    department: str
    name: str
    agent_ref: str
    registered_at: str  # ISO-8601 UTC
    registered_by: str = "operator"


@dataclass(frozen=True)
class RegisterResult:
    """Outcome of a ``register`` call.

    Never raises on a validation failure — returns ``ok=False`` with a clear,
    distinct ``error`` so the REST/Discord surfaces (RR.3/RR.4) can surface a
    400/operator message rather than a 500.
    """

    ok: bool
    specialist: RegisteredSpecialist | None = None
    error: str | None = None


def _employee_names(config: Any) -> set[str]:
    """Extract the set of employee (YAML built-in) names from a dept config.

    Reads ``config.employees`` — each an object with a ``name`` attribute
    (``AgentSpec`` in production, a fake in tests). The YAML-derived roster
    names equal these employee names (see ``roster_from_department_config``),
    so this set is exactly the shadow-of-built-in guard.
    """
    return {emp.name for emp in getattr(config, "employees", ())}


class RosterRegistryStore:
    """SQLite-backed store for operator-registered roster specialists."""

    def __init__(
        self,
        db_path: Path,
        *,
        config_lookup: ConfigLookup,
        on_change: Callable[[str], None] | None = None,
    ) -> None:
        self._db_path = db_path
        self._config_lookup = config_lookup
        self._on_change = on_change
        self._conn = sqlite3.connect(str(db_path))
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(_SCHEMA)

    # ------------------------------------------------------------------
    # writes
    # ------------------------------------------------------------------

    def register(
        self,
        department: str,
        name: str,
        agent_ref: str,
        by: str = "operator",
    ) -> RegisterResult:
        """Validate and persist a registered specialist.

        Rejects (returns ``RegisterResult(ok=False, error=...)``; never
        silently inserts) unless ALL hold:
          - the department exists,
          - ``agent_ref`` resolves to a real employee agent in that dept,
          - ``(department, name)`` does not shadow a YAML built-in,
          - ``(department, name)`` is not already registered.

        On success fires ``on_change(department)`` AFTER the committed write so
        the chief agent for that team rebuilds with the fresh overlay.
        """
        config = self._config_lookup(department)
        if config is None:
            return RegisterResult(
                ok=False, error=f"unknown department: {department!r}"
            )

        employee_names = _employee_names(config)
        if agent_ref not in employee_names:
            return RegisterResult(
                ok=False,
                error=(
                    f"agent_ref {agent_ref!r} does not resolve to an employee "
                    f"in department {department!r}"
                ),
            )

        if name in employee_names:
            return RegisterResult(
                ok=False,
                error=(
                    f"name {name!r} shadows a YAML built-in specialist in "
                    f"department {department!r}"
                ),
            )

        if self._exists(department, name):
            return RegisterResult(
                ok=False,
                error=(
                    f"specialist {name!r} is already registered in department "
                    f"{department!r}"
                ),
            )

        registered_at = datetime.now(timezone.utc).isoformat()
        self._conn.execute(
            """INSERT INTO registered_specialists
                   (department, name, agent_ref, registered_at, registered_by)
               VALUES (?, ?, ?, ?, ?)""",
            (department, name, agent_ref, registered_at, by),
        )
        self._conn.commit()

        specialist = RegisteredSpecialist(
            department=department,
            name=name,
            agent_ref=agent_ref,
            registered_at=registered_at,
            registered_by=by,
        )
        self._fire_on_change(department)
        return RegisterResult(ok=True, specialist=specialist)

    def unregister(self, department: str, name: str) -> bool:
        """Remove a registered specialist. Returns True if a row was removed,
        False when absent. Fires ``on_change(department)`` only on a real
        removal (an absent unregister is a no-op — nothing changed, no
        cache invalidation needed).
        """
        cur = self._conn.execute(
            "DELETE FROM registered_specialists WHERE department = ? AND name = ?",
            (department, name),
        )
        self._conn.commit()
        if cur.rowcount > 0:
            self._fire_on_change(department)
            return True
        return False

    # ------------------------------------------------------------------
    # reads
    # ------------------------------------------------------------------

    def list_for_department(
        self, department: str
    ) -> tuple[RegisteredSpecialist, ...]:
        rows = self._conn.execute(
            """SELECT department, name, agent_ref, registered_at, registered_by
                 FROM registered_specialists
                WHERE department = ?
                ORDER BY registered_at""",
            (department,),
        ).fetchall()
        return tuple(self._row_to_specialist(r) for r in rows)

    def list_all(self) -> tuple[RegisteredSpecialist, ...]:
        rows = self._conn.execute(
            """SELECT department, name, agent_ref, registered_at, registered_by
                 FROM registered_specialists
                ORDER BY department, registered_at"""
        ).fetchall()
        return tuple(self._row_to_specialist(r) for r in rows)

    def close(self) -> None:
        self._conn.close()

    # ------------------------------------------------------------------
    # internals
    # ------------------------------------------------------------------

    def _exists(self, department: str, name: str) -> bool:
        row = self._conn.execute(
            "SELECT 1 FROM registered_specialists WHERE department = ? AND name = ?",
            (department, name),
        ).fetchone()
        return row is not None

    def _fire_on_change(self, department: str) -> None:
        if self._on_change is None:
            return
        try:
            self._on_change(department)
        except Exception:  # noqa: BLE001 — never let a stale-cache hook break a write
            log.exception(
                "roster_registry.on_change_failed department=%s", department
            )

    @staticmethod
    def _row_to_specialist(row: tuple) -> RegisteredSpecialist:
        return RegisteredSpecialist(
            department=row[0],
            name=row[1],
            agent_ref=row[2],
            registered_at=row[3],
            registered_by=row[4],
        )
