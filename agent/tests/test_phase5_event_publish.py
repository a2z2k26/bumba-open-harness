"""Tests for Sprint 23 — store-side EventBus publish hooks.

The dashboard's WebSocket live updates flow through the existing
``/ws/events`` stream by adding 5 new event types
(``directive.issued``, ``directive.status_changed``,
``task.status_changed``, ``surface.written``, ``surface.acknowledged``)
that the stores publish on every state change. These tests verify
those publishes happen.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest
import pytest_asyncio

from bridge.database import Database
from bridge.directive_store import (
    insert_directive,
    mark_done,
    new_directive_id,
)
from bridge.event_bus import EventBus
from bridge.surface_store import (
    insert_surface,
    mark_read,
    new_surface_id,
)
from bridge.task_store import (
    insert_task,
    mark_in_progress,
    new_task_id,
)
from teams._types import (
    Directive,
    Surface,
    SurfaceKind,
    Task,
    Urgency,
)


@pytest_asyncio.fixture
async def db(tmp_path: Path) -> Database:
    db_path = tmp_path / "test-event-publish.db"
    database = Database(db_path)
    await database.connect()
    await database.migrate()
    yield database
    await database.close()


@pytest.fixture
def captured_events() -> list[tuple[str, dict]]:
    """Subscribe to the EventBus singleton and capture every Phase 5 event."""
    bus = EventBus.get_instance()
    captured: list[tuple[str, dict]] = []

    sub_ids: list[str] = []
    for event_type in (
        "directive.issued",
        "directive.status_changed",
        "task.status_changed",
        "surface.written",
        "surface.acknowledged",
    ):
        sid = bus.subscribe(
            event_type,
            lambda evt, captured=captured: captured.append(
                (evt.event_type, evt.payload)
            ),
        )
        sub_ids.append(sid)

    yield captured

    for sid in sub_ids:
        bus.unsubscribe(sid)


# ---------------------------------------------------------------------------
# Directive events
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_insert_directive_publishes_issued(
    db: Database, captured_events: list
) -> None:
    d = Directive(
        directive_id=new_directive_id(),
        from_agent="main",
        to_chief="strategy-product-chief",
        intent="probe",
        constraints=(),
        deadline_utc=None,
        priority="p1",
        issued_at_utc=datetime.now(timezone.utc),
        context={},
        operator_id="op",
    )
    await insert_directive(db, d)

    issued = [e for e in captured_events if e[0] == "directive.issued"]
    assert len(issued) >= 1
    payload = issued[-1][1]
    assert payload["directive_id"] == d.directive_id
    assert payload["to_chief"] == "strategy-product-chief"
    assert payload["priority"] == "p1"


@pytest.mark.asyncio
async def test_directive_status_change_publishes(
    db: Database, captured_events: list
) -> None:
    d = Directive(
        directive_id=new_directive_id(),
        from_agent="main",
        to_chief="qa-chief",
        intent="x",
        constraints=(),
        deadline_utc=None,
        priority="p2",
        issued_at_utc=datetime.now(timezone.utc),
        context={},
        operator_id="op",
    )
    await insert_directive(db, d)
    await mark_done(db, d.directive_id, note="all done")

    transitions = [
        e for e in captured_events
        if e[0] == "directive.status_changed"
        and e[1].get("directive_id") == d.directive_id
    ]
    assert len(transitions) == 1
    payload = transitions[0][1]
    assert payload["from_status"] == "issued"
    assert payload["to_status"] == "done"
    assert payload["note"] == "all done"


# ---------------------------------------------------------------------------
# Task events
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_insert_task_publishes_status_changed(
    db: Database, captured_events: list
) -> None:
    t = Task(
        task_id=new_task_id(),
        directive_id=None,
        from_chief="strategy-product-chief",
        to_specialist="alpha",
        description="research",
        constraints=(),
        deadline_utc=None,
        issued_at_utc=datetime.now(timezone.utc),
    )
    await insert_task(db, t)
    transitions = [
        e for e in captured_events
        if e[0] == "task.status_changed"
        and e[1].get("task_id") == t.task_id
    ]
    assert len(transitions) >= 1
    # Insert publishes a (None → assigned) transition
    insert_evt = next(
        e for e in transitions if e[1].get("from_status") is None
    )
    assert insert_evt[1]["to_status"] == "assigned"
    assert insert_evt[1]["to_specialist"] == "alpha"


@pytest.mark.asyncio
async def test_task_status_change_publishes(
    db: Database, captured_events: list
) -> None:
    t = Task(
        task_id=new_task_id(),
        directive_id=None,
        from_chief="qa-chief",
        to_specialist="beta",
        description="x",
        constraints=(),
        deadline_utc=None,
        issued_at_utc=datetime.now(timezone.utc),
    )
    await insert_task(db, t)
    await mark_in_progress(db, t.task_id, note="invoke")

    progress = [
        e for e in captured_events
        if e[0] == "task.status_changed"
        and e[1].get("task_id") == t.task_id
        and e[1].get("from_status") == "assigned"
    ]
    assert len(progress) == 1
    assert progress[0][1]["to_status"] == "in_progress"
    assert progress[0][1]["note"] == "invoke"


# ---------------------------------------------------------------------------
# Surface events
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_insert_surface_publishes_written(
    db: Database, captured_events: list
) -> None:
    s = Surface(
        surface_id=new_surface_id(),
        from_agent="alpha",
        to_agent="strategy-product-chief",
        kind=SurfaceKind.RESULT,
        urgency=Urgency.FYI,
        correlation_id="task-xyz",
        payload={"answer": "x"},
        created_at_utc=datetime.now(timezone.utc),
    )
    await insert_surface(db, s)
    written = [
        e for e in captured_events
        if e[0] == "surface.written"
        and e[1].get("surface_id") == s.surface_id
    ]
    assert len(written) == 1
    payload = written[0][1]
    assert payload["kind"] == "result"
    assert payload["urgency"] == "fyi"
    assert payload["from_agent"] == "alpha"
    assert payload["correlation_id"] == "task-xyz"


@pytest.mark.asyncio
async def test_mark_read_publishes_acknowledged(
    db: Database, captured_events: list
) -> None:
    s = Surface(
        surface_id=new_surface_id(),
        from_agent="alpha",
        to_agent="main",
        kind=SurfaceKind.BLOCKER,
        urgency=Urgency.IMMEDIATE,
        correlation_id="dir-abc",
        payload={},
        created_at_utc=datetime.now(timezone.utc),
    )
    await insert_surface(db, s)
    await mark_read(db, s.surface_id)

    acked = [
        e for e in captured_events
        if e[0] == "surface.acknowledged"
        and e[1].get("surface_id") == s.surface_id
    ]
    assert len(acked) == 1


@pytest.mark.asyncio
async def test_idempotent_mark_read_does_not_double_publish(
    db: Database, captured_events: list
) -> None:
    s = Surface(
        surface_id=new_surface_id(),
        from_agent="alpha",
        to_agent="main",
        kind=SurfaceKind.FLAG,
        urgency=Urgency.ATTENTION,
        correlation_id="dir-z",
        payload={},
        created_at_utc=datetime.now(timezone.utc),
    )
    await insert_surface(db, s)
    await mark_read(db, s.surface_id)
    await mark_read(db, s.surface_id)  # second call should be a no-op

    acked = [
        e for e in captured_events
        if e[0] == "surface.acknowledged"
        and e[1].get("surface_id") == s.surface_id
    ]
    # Only the first mark_read publishes
    assert len(acked) == 1
