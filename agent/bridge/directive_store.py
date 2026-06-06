"""Directive persistence for Phase 5 Sprint 20 (downward protocol).

Stores ``Directive`` records and lifecycle transitions for directives issued
by the Main Agent to department chiefs. Every status transition appends a
row to ``directive_history`` so the lifecycle is reconstructible after a
bridge restart.

All queries are parameterised — no string interpolation of caller-supplied
values reaches SQLite. The CHECK constraints on ``directives.priority`` and
``directives.status`` (migration #10) are a defence-in-depth backstop, not
the primary validation layer.

Invariants:
- ``directive_id`` is the primary key and is generated server-side via
  ``new_directive_id()``. Callers MUST use the helper rather than passing
  externally-supplied IDs to keep collision risk under our control.
- Directives are immutable once issued. Status moves on the row, history
  rows accumulate; the original ``Directive`` envelope is never rewritten.
- All timestamps are ISO-8601 UTC strings ('+00:00' suffix). The store
  parses them back to ``datetime`` on read.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Optional
from uuid import uuid4

from teams._types import (
    DIRECTIVE_PRIORITIES,
    Directive,
    DirectiveStatus,
)

if TYPE_CHECKING:
    from bridge.database import Database

log = logging.getLogger(__name__)


def new_directive_id() -> str:
    """Generate a fresh directive_id of the form ``dir-<12-hex>``."""
    return f"dir-{uuid4().hex[:12]}"


def _safe_publish(event_type: str, payload: dict, correlation_id: str) -> None:
    """Best-effort EventBus publish for directive lifecycle events.

    Sprint 23 (Phase 5D): WebSocket clients on /ws/events subscribe to
    these so the dashboard reflects status changes without polling.
    Wrapped in try/except — bus failures (e.g. before the singleton is
    initialised in some test contexts) never block store writes.
    """
    try:
        from bridge.event_bus import EventBus
        EventBus.get_instance().publish(
            event_type, payload, source="directive_store",
            correlation_id=correlation_id,
        )
    except Exception as exc:  # noqa: BLE001
        log.debug("directive_store.publish_failed type=%s error=%s", event_type, exc)


def _validate_priority(priority: str) -> None:
    """Raise ValueError if priority isn't one of the allowed strings.

    The CHECK constraint at the SQLite level catches this too, but we want
    a clean Python-side ValueError rather than an opaque IntegrityError so
    callers can present a useful message.
    """
    if priority not in DIRECTIVE_PRIORITIES:
        raise ValueError(
            f"Invalid priority {priority!r}. "
            f"Must be one of: {', '.join(DIRECTIVE_PRIORITIES)}"
        )


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


async def insert_directive(db: "Database", d: Directive) -> None:
    """Persist a fresh Directive in ``ISSUED`` status + write its first history row.

    Raises ``ValueError`` if ``d.priority`` is invalid. Otherwise propagates
    any underlying SQLite error to the caller (caller decides whether the
    failure is fatal to the dispatch flow).
    """
    _validate_priority(d.priority)
    issued_at = d.issued_at_utc.isoformat()
    deadline = d.deadline_utc.isoformat() if d.deadline_utc else None
    now = _now_iso()
    await db.execute(
        """INSERT INTO directives (
            directive_id, from_agent, to_chief, intent, constraints_json,
            deadline_utc, priority, issued_at_utc, status, context_json,
            operator_id, updated_at_utc
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            d.directive_id,
            d.from_agent,
            d.to_chief,
            d.intent,
            json.dumps(list(d.constraints)),
            deadline,
            d.priority,
            issued_at,
            DirectiveStatus.ISSUED.value,
            json.dumps(dict(d.context)),
            d.operator_id,
            now,
        ),
    )
    await db.execute(
        """INSERT INTO directive_history (
            directive_id, from_status, to_status, note, transitioned_at_utc
        ) VALUES (?, ?, ?, ?, ?)""",
        (
            d.directive_id,
            None,  # initial issue has no prior status
            DirectiveStatus.ISSUED.value,
            "issued",
            now,
        ),
    )
    await db.commit()
    log.info(
        "directive.inserted id=%s to_chief=%s priority=%s",
        d.directive_id, d.to_chief, d.priority,
    )
    # Sprint 23: dashboard live-update event
    _safe_publish(
        "directive.issued",
        {
            "directive_id": d.directive_id,
            "to_chief": d.to_chief,
            "priority": d.priority,
            "from_agent": d.from_agent,
            "intent": d.intent,
        },
        d.directive_id,
    )


async def update_status(
    db: "Database",
    directive_id: str,
    new_status: DirectiveStatus,
    *,
    note: Optional[str] = None,
) -> None:
    """Transition a directive's status and append a history row atomically.

    The ``directive_history`` row records the prior status (read just before
    the update) so the audit trail is gap-free even if a caller forgets to
    supply ``note``. Raises ``ValueError`` if ``directive_id`` is unknown.
    """
    row = await db.fetchone(
        "SELECT status FROM directives WHERE directive_id = ?",
        (directive_id,),
    )
    if row is None:
        raise ValueError(f"Unknown directive_id: {directive_id}")

    prior_status = row["status"]
    if prior_status == new_status.value:
        # No-op transition — still emit a history row so retries are visible
        # in the audit log, but log at debug rather than info.
        log.debug(
            "directive.status_noop id=%s status=%s", directive_id, new_status.value
        )

    now = _now_iso()
    await db.execute(
        "UPDATE directives SET status = ?, updated_at_utc = ? WHERE directive_id = ?",
        (new_status.value, now, directive_id),
    )
    await db.execute(
        """INSERT INTO directive_history (
            directive_id, from_status, to_status, note, transitioned_at_utc
        ) VALUES (?, ?, ?, ?, ?)""",
        (directive_id, prior_status, new_status.value, note, now),
    )
    await db.commit()
    log.info(
        "directive.status_changed id=%s %s→%s",
        directive_id, prior_status, new_status.value,
    )
    # Sprint 23: dashboard live-update event
    _safe_publish(
        "directive.status_changed",
        {
            "directive_id": directive_id,
            "from_status": prior_status,
            "to_status": new_status.value,
            "note": note,
        },
        directive_id,
    )


def _row_to_directive(row: Any) -> Directive:
    """Hydrate a SQLite row into a Directive dataclass."""
    deadline_raw = row["deadline_utc"]
    deadline = (
        datetime.fromisoformat(deadline_raw) if deadline_raw else None
    )
    return Directive(
        directive_id=row["directive_id"],
        from_agent=row["from_agent"],
        to_chief=row["to_chief"],
        intent=row["intent"],
        constraints=tuple(json.loads(row["constraints_json"])),
        deadline_utc=deadline,
        priority=row["priority"],
        issued_at_utc=datetime.fromisoformat(row["issued_at_utc"]),
        context=json.loads(row["context_json"]),
        operator_id=row["operator_id"],
    )


async def get_directive(db: "Database", directive_id: str) -> Optional[Directive]:
    """Fetch a directive envelope by id. Returns None if not found.

    Status is NOT returned on the dataclass — call ``get_status`` for that.
    """
    row = await db.fetchone(
        """SELECT directive_id, from_agent, to_chief, intent, constraints_json,
                  deadline_utc, priority, issued_at_utc, context_json, operator_id
           FROM directives WHERE directive_id = ?""",
        (directive_id,),
    )
    if row is None:
        return None
    return _row_to_directive(row)


async def get_status(db: "Database", directive_id: str) -> Optional[DirectiveStatus]:
    """Fetch the live status of a directive. Returns None if not found."""
    row = await db.fetchone(
        "SELECT status FROM directives WHERE directive_id = ?",
        (directive_id,),
    )
    if row is None:
        return None
    return DirectiveStatus(row["status"])


_ACTIVE_STATUSES: tuple[str, ...] = (
    DirectiveStatus.ISSUED.value,
    DirectiveStatus.ACCEPTED.value,
    DirectiveStatus.IN_PROGRESS.value,
)


async def list_active(db: "Database") -> list[Directive]:
    """Return all directives whose status is not terminal (DONE/BLOCKED/CANCELLED).

    Ordered by ``issued_at_utc`` descending so freshest work surfaces first.
    """
    placeholders = ", ".join("?" for _ in _ACTIVE_STATUSES)
    rows = await db.fetchall(
        f"""SELECT directive_id, from_agent, to_chief, intent, constraints_json,
                   deadline_utc, priority, issued_at_utc, context_json, operator_id
            FROM directives
            WHERE status IN ({placeholders})
            ORDER BY issued_at_utc DESC""",
        _ACTIVE_STATUSES,
    )
    return [_row_to_directive(r) for r in rows]


async def list_by_chief(
    db: "Database", to_chief: str, *, include_terminal: bool = False
) -> list[Directive]:
    """Return directives addressed to ``to_chief``, optionally including terminal ones."""
    if include_terminal:
        rows = await db.fetchall(
            """SELECT directive_id, from_agent, to_chief, intent, constraints_json,
                      deadline_utc, priority, issued_at_utc, context_json, operator_id
               FROM directives
               WHERE to_chief = ?
               ORDER BY issued_at_utc DESC""",
            (to_chief,),
        )
    else:
        placeholders = ", ".join("?" for _ in _ACTIVE_STATUSES)
        rows = await db.fetchall(
            f"""SELECT directive_id, from_agent, to_chief, intent, constraints_json,
                       deadline_utc, priority, issued_at_utc, context_json, operator_id
                FROM directives
                WHERE to_chief = ? AND status IN ({placeholders})
                ORDER BY issued_at_utc DESC""",
            (to_chief, *_ACTIVE_STATUSES),
        )
    return [_row_to_directive(r) for r in rows]


async def list_all(
    db: "Database", *, limit: int = 100
) -> list[Directive]:
    """Return the most recent ``limit`` directives regardless of status."""
    rows = await db.fetchall(
        """SELECT directive_id, from_agent, to_chief, intent, constraints_json,
                  deadline_utc, priority, issued_at_utc, context_json, operator_id
           FROM directives
           ORDER BY issued_at_utc DESC
           LIMIT ?""",
        (limit,),
    )
    return [_row_to_directive(r) for r in rows]


async def get_history(db: "Database", directive_id: str) -> list[dict[str, Any]]:
    """Return the full lifecycle history for a directive in transition order."""
    rows = await db.fetchall(
        """SELECT id, from_status, to_status, note, transitioned_at_utc
           FROM directive_history
           WHERE directive_id = ?
           ORDER BY id ASC""",
        (directive_id,),
    )
    return [dict(r) for r in rows]


# Convenience wrappers used by chief / Main Agent code paths in PR B.
# Kept thin so PR A's surface stays focused on persistence; semantic glue
# (e.g. when to call mark_blocked vs cancel) lives at the call site.


async def mark_accepted(db: "Database", directive_id: str, *, note: Optional[str] = None) -> None:
    await update_status(db, directive_id, DirectiveStatus.ACCEPTED, note=note)


async def mark_in_progress(db: "Database", directive_id: str, *, note: Optional[str] = None) -> None:
    await update_status(db, directive_id, DirectiveStatus.IN_PROGRESS, note=note)


async def mark_done(db: "Database", directive_id: str, *, note: Optional[str] = None) -> None:
    await update_status(db, directive_id, DirectiveStatus.DONE, note=note)


async def mark_blocked(db: "Database", directive_id: str, *, note: Optional[str] = None) -> None:
    await update_status(db, directive_id, DirectiveStatus.BLOCKED, note=note)


async def mark_cancelled(db: "Database", directive_id: str, *, note: Optional[str] = None) -> None:
    await update_status(db, directive_id, DirectiveStatus.CANCELLED, note=note)
