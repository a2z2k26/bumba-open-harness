"""Surface persistence for Phase 5 Sprint 22 (upward protocol).

Stores ``Surface`` records emitted by specialists to chiefs and by chiefs
to the Main Agent. Mirrors the design of ``directive_store`` and
``task_store`` from Sprints 20 and 21 — parameterised queries, all
boundary validation in Python before SQL runs.

Invariants:
- ``surface_id`` is the primary key, generated server-side via
  ``new_surface_id()``. Callers MUST use the helper.
- ``correlation_id`` is polymorphic: task_id for specialist→chief,
  directive_id for chief→main. NULL allowed for out-of-band surfaces
  emitted from contexts where neither id is in scope (test fixtures,
  cron path).
- Surfaces are immutable. The only mutation possible is setting
  ``read_at_utc`` via ``mark_read()`` (operator acknowledgment).
- All timestamps are ISO-8601 UTC strings.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Optional
from uuid import uuid4

from teams._types import (
    SURFACE_KINDS,
    SURFACE_URGENCIES,
    Surface,
    SurfaceKind,
    Urgency,
)

if TYPE_CHECKING:
    from bridge.database import Database

log = logging.getLogger(__name__)


class MissingSurfaceStoreError(RuntimeError):
    """Raised when a directive/surface workflow runs with no Database wired.

    Sprint P3.5 (2026-05-11 audit): the chief→main RESULT surface is a
    required handoff artifact for any chief session that carries a
    ``directive_id``. Without a Database the surface row cannot be
    persisted and the dashboard / `/api/directives/{id}/tree` reader
    cannot reconstruct the directive graph. Callers in production paths
    must wire a Database; unit tests that genuinely don't need the store
    opt out explicitly via ``BridgeDeps.allow_no_surface_store=True``.
    """


def new_surface_id() -> str:
    """Generate a fresh surface_id of the form ``surf-<12-hex>``."""
    return f"surf-{uuid4().hex[:12]}"


def _safe_publish(event_type: str, payload: dict, correlation_id: str | None) -> None:
    """Best-effort EventBus publish for surface lifecycle events (Sprint 23)."""
    try:
        from bridge.event_bus import EventBus
        EventBus.get_instance().publish(
            event_type, payload, source="surface_store",
            correlation_id=correlation_id or "",
        )
    except Exception as exc:  # noqa: BLE001
        log.debug("surface_store.publish_failed type=%s error=%s", event_type, exc)


def _validate_kind(kind: str) -> None:
    if kind not in SURFACE_KINDS:
        raise ValueError(
            f"Invalid surface kind {kind!r}. "
            f"Must be one of: {', '.join(SURFACE_KINDS)}"
        )


def _validate_urgency(urgency: str) -> None:
    if urgency not in SURFACE_URGENCIES:
        raise ValueError(
            f"Invalid urgency {urgency!r}. "
            f"Must be one of: {', '.join(SURFACE_URGENCIES)}"
        )


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


async def insert_surface(db: "Database", s: Surface) -> None:
    """Persist a Surface row.

    Raises ``ValueError`` if ``s.kind`` or ``s.urgency`` aren't recognised
    (catches the case where a caller bypasses the enum types and passes
    raw strings).
    """
    _validate_kind(s.kind.value if isinstance(s.kind, SurfaceKind) else s.kind)
    _validate_urgency(
        s.urgency.value if isinstance(s.urgency, Urgency) else s.urgency
    )
    created = s.created_at_utc.isoformat()
    await db.execute(
        """INSERT INTO surfaces (
            surface_id, from_agent, to_agent, kind, urgency,
            correlation_id, payload_json, created_at_utc, read_at_utc
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL)""",
        (
            s.surface_id,
            s.from_agent,
            s.to_agent,
            s.kind.value if isinstance(s.kind, SurfaceKind) else s.kind,
            s.urgency.value if isinstance(s.urgency, Urgency) else s.urgency,
            s.correlation_id,
            json.dumps(dict(s.payload)),
            created,
        ),
    )
    await db.commit()
    log.info(
        "surface.inserted id=%s kind=%s urgency=%s from=%s to=%s correlation=%s",
        s.surface_id, s.kind, s.urgency, s.from_agent, s.to_agent,
        s.correlation_id,
    )
    # Sprint 23: dashboard live-update event
    _safe_publish(
        "surface.written",
        {
            "surface_id": s.surface_id,
            "from_agent": s.from_agent,
            "to_agent": s.to_agent,
            "kind": s.kind.value if hasattr(s.kind, "value") else s.kind,
            "urgency": (
                s.urgency.value if hasattr(s.urgency, "value") else s.urgency
            ),
            "correlation_id": s.correlation_id,
        },
        s.correlation_id,
    )


async def mark_read(db: "Database", surface_id: str) -> bool:
    """Set read_at_utc on a surface. Returns True if the row was updated.

    Idempotent — calling twice on the same surface no-ops the second time
    (returns False) so multiple ``/ack`` invocations don't churn timestamps.
    """
    row = await db.fetchone(
        "SELECT read_at_utc FROM surfaces WHERE surface_id = ?",
        (surface_id,),
    )
    if row is None:
        raise ValueError(f"Unknown surface_id: {surface_id}")
    if row["read_at_utc"] is not None:
        return False
    await db.execute(
        "UPDATE surfaces SET read_at_utc = ? WHERE surface_id = ?",
        (_now_iso(), surface_id),
    )
    await db.commit()
    log.info("surface.marked_read id=%s", surface_id)
    # Sprint 23: dashboard live-update event
    _safe_publish(
        "surface.acknowledged", {"surface_id": surface_id}, surface_id,
    )
    return True


def _row_to_surface(row: Any) -> Surface:
    """Hydrate a SQLite row into a Surface dataclass."""
    return Surface(
        surface_id=row["surface_id"],
        from_agent=row["from_agent"],
        to_agent=row["to_agent"],
        kind=SurfaceKind(row["kind"]),
        urgency=Urgency(row["urgency"]),
        correlation_id=row["correlation_id"],
        payload=json.loads(row["payload_json"]),
        created_at_utc=datetime.fromisoformat(row["created_at_utc"]),
    )


async def get_surface(db: "Database", surface_id: str) -> Optional[Surface]:
    """Fetch a surface envelope by id. Returns None if not found.

    Note: the row's ``read_at_utc`` is NOT returned on the dataclass.
    Use ``is_read()`` to query that column directly.
    """
    row = await db.fetchone(
        """SELECT surface_id, from_agent, to_agent, kind, urgency,
                  correlation_id, payload_json, created_at_utc
           FROM surfaces WHERE surface_id = ?""",
        (surface_id,),
    )
    if row is None:
        return None
    return _row_to_surface(row)


async def is_read(db: "Database", surface_id: str) -> Optional[bool]:
    """Return True if the surface has a read_at_utc, False if not, None if unknown."""
    row = await db.fetchone(
        "SELECT read_at_utc FROM surfaces WHERE surface_id = ?",
        (surface_id,),
    )
    if row is None:
        return None
    return row["read_at_utc"] is not None


async def list_by_correlation(
    db: "Database", correlation_id: str
) -> list[Surface]:
    """Return all surfaces tied to ``correlation_id`` in chronological order."""
    rows = await db.fetchall(
        """SELECT surface_id, from_agent, to_agent, kind, urgency,
                  correlation_id, payload_json, created_at_utc
           FROM surfaces
           WHERE correlation_id = ?
           ORDER BY created_at_utc ASC""",
        (correlation_id,),
    )
    return [_row_to_surface(r) for r in rows]


async def list_unread_for_agent(
    db: "Database", to_agent: str
) -> list[Surface]:
    """Return surfaces addressed to ``to_agent`` with read_at_utc IS NULL.

    Ordered by ``created_at_utc`` descending so freshest surfaces first.
    """
    rows = await db.fetchall(
        """SELECT surface_id, from_agent, to_agent, kind, urgency,
                  correlation_id, payload_json, created_at_utc
           FROM surfaces
           WHERE to_agent = ? AND read_at_utc IS NULL
           ORDER BY created_at_utc DESC""",
        (to_agent,),
    )
    return [_row_to_surface(r) for r in rows]


async def list_active(db: "Database", *, limit: int = 50) -> list[Surface]:
    """Return the most recent ``limit`` unread surfaces regardless of recipient.

    Useful for the operator's bird's-eye `/surfaces active` view.
    """
    rows = await db.fetchall(
        """SELECT surface_id, from_agent, to_agent, kind, urgency,
                  correlation_id, payload_json, created_at_utc
           FROM surfaces
           WHERE read_at_utc IS NULL
           ORDER BY created_at_utc DESC
           LIMIT ?""",
        (limit,),
    )
    return [_row_to_surface(r) for r in rows]


async def list_by_kind(
    db: "Database", kind: SurfaceKind | str, *, limit: int = 50
) -> list[Surface]:
    """Return the most recent ``limit`` surfaces of a given kind."""
    kind_str = kind.value if isinstance(kind, SurfaceKind) else kind
    _validate_kind(kind_str)
    rows = await db.fetchall(
        """SELECT surface_id, from_agent, to_agent, kind, urgency,
                  correlation_id, payload_json, created_at_utc
           FROM surfaces
           WHERE kind = ?
           ORDER BY created_at_utc DESC
           LIMIT ?""",
        (kind_str, limit),
    )
    return [_row_to_surface(r) for r in rows]


async def list_all(db: "Database", *, limit: int = 100) -> list[Surface]:
    """Return the most recent ``limit`` surfaces regardless of state."""
    rows = await db.fetchall(
        """SELECT surface_id, from_agent, to_agent, kind, urgency,
                  correlation_id, payload_json, created_at_utc
           FROM surfaces
           ORDER BY created_at_utc DESC
           LIMIT ?""",
        (limit,),
    )
    return [_row_to_surface(r) for r in rows]


async def task_has_result_surface(
    db: "Database", task_id: str
) -> bool:
    """Return True if at least one RESULT surface exists for ``task_id``.

    Used by ``_team.py`` after a manager run completes to detect specialists
    that returned without emitting their mandatory RESULT surface; the
    caller synthesises one with ``payload.synthesized=true`` so dashboards
    always see a result row per task.
    """
    row = await db.fetchone(
        """SELECT 1 FROM surfaces
           WHERE correlation_id = ? AND kind = 'result'
           LIMIT 1""",
        (task_id,),
    )
    return row is not None
