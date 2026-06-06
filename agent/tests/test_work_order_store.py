"""Tests for WorkOrder SQLite persistence."""

from __future__ import annotations

from pathlib import Path

import pytest

from bridge.work_order import Environment, WorkOrder, WorkOrderStatus
from bridge.work_order_store import WorkflowRun, WorkOrderStore


@pytest.fixture
def store(tmp_path: Path) -> WorkOrderStore:
    db_path = tmp_path / "test_workorders.db"
    # Sprint R2.3 (#1895) — yield + close so the fixture doesn't leak
    # ``ResourceWarning: unclosed database`` once GC catches the
    # ``self._conn`` field.
    s = WorkOrderStore(db_path)
    yield s
    s.close()


@pytest.fixture
def sample_wo() -> WorkOrder:
    return WorkOrder.create(
        intent="Build auth API",
        skill="backend-architect",
        project="my-project",
    ).with_environment(Environment.TMUX, "Parallel work needed")


def test_save_and_get(store: WorkOrderStore, sample_wo: WorkOrder) -> None:
    store.save(sample_wo)
    retrieved = store.get(sample_wo.id)
    assert retrieved is not None
    assert retrieved.id == sample_wo.id
    assert retrieved.intent == sample_wo.intent
    assert retrieved.environment == Environment.TMUX


def test_get_nonexistent(store: WorkOrderStore) -> None:
    assert store.get("nonexistent-id") is None


def test_save_updates_existing(store: WorkOrderStore, sample_wo: WorkOrder) -> None:
    store.save(sample_wo)
    updated = sample_wo.transition(WorkOrderStatus.ASSIGNED)
    store.save(updated)
    retrieved = store.get(sample_wo.id)
    assert retrieved is not None
    assert retrieved.status == WorkOrderStatus.ASSIGNED


def test_list_by_project(store: WorkOrderStore) -> None:
    wo1 = WorkOrder.create(intent="task 1", skill="a", project="proj-a")
    wo2 = WorkOrder.create(intent="task 2", skill="b", project="proj-a")
    wo3 = WorkOrder.create(intent="task 3", skill="c", project="proj-b")
    store.save(wo1)
    store.save(wo2)
    store.save(wo3)
    results = store.list_by_project("proj-a")
    assert len(results) == 2
    assert all(wo.project == "proj-a" for wo in results)


def test_list_by_status(store: WorkOrderStore, sample_wo: WorkOrder) -> None:
    store.save(sample_wo)
    assigned = sample_wo.transition(WorkOrderStatus.ASSIGNED)
    wo2 = WorkOrder.create(intent="other", skill="x", project="p")
    store.save(assigned)
    store.save(wo2)
    results = store.list_by_status(WorkOrderStatus.PENDING)
    assert len(results) == 1
    assert results[0].id == wo2.id


def test_list_children(store: WorkOrderStore) -> None:
    parent = WorkOrder.create(intent="parent", skill="chief", project="p")
    child1 = WorkOrder.create(intent="child1", skill="a", project="p", parent_id=parent.id)
    child2 = WorkOrder.create(intent="child2", skill="b", project="p", parent_id=parent.id)
    store.save(parent)
    store.save(child1)
    store.save(child2)
    children = store.list_children(parent.id)
    assert len(children) == 2


def test_delete(store: WorkOrderStore, sample_wo: WorkOrder) -> None:
    store.save(sample_wo)
    store.delete(sample_wo.id)
    assert store.get(sample_wo.id) is None


def test_list_ready_to_dispatch(store: WorkOrderStore) -> None:
    parent = WorkOrder.create(intent="prereq", skill="a", project="p")
    parent = parent.transition(WorkOrderStatus.ASSIGNED)
    parent = parent.transition(WorkOrderStatus.EXECUTING)
    parent = parent.transition(WorkOrderStatus.VERIFYING)
    parent = parent.transition(WorkOrderStatus.COMPLETE)
    store.save(parent)

    dependent = WorkOrder.create(intent="dependent", skill="b", project="p")
    dependent = WorkOrder(
        id=dependent.id, intent=dependent.intent, skill=dependent.skill,
        project=dependent.project, status=dependent.status,
        input=dependent.input, constraints=dependent.constraints,
        output=dependent.output, environment=dependent.environment,
        environment_rationale=dependent.environment_rationale,
        parent_id=dependent.parent_id, context_id=dependent.context_id,
        assignment=dependent.assignment, execution=dependent.execution,
        dependencies=(parent.id,), output_schema=dependent.output_schema,
    )
    store.save(dependent)

    ready = store.list_ready_to_dispatch("p")
    assert len(ready) == 1
    assert ready[0].id == dependent.id


# Sprint R2.3 (#1895) — close() lifecycle regression.

def test_close_releases_sqlite_connection(tmp_path: Path) -> None:
    """``WorkOrderStore.close()`` must release the underlying sqlite handle.

    After close(), subsequent writes raise ``sqlite3.ProgrammingError``
    (closed connection); the file descriptor is gone. Without this, the
    long-lived ``self._conn`` leaks on GC as ``ResourceWarning: unclosed
    database`` — the surface this sprint was filed to eliminate.
    """
    import sqlite3

    db_path = tmp_path / "wo_close.db"
    store = WorkOrderStore(db_path)
    wo = WorkOrder.create(intent="i", skill="s", project="p")
    store.save(wo)  # writes succeed before close

    store.close()

    with pytest.raises(sqlite3.ProgrammingError):
        store.save(wo)  # writes fail after close


def test_close_is_idempotent(tmp_path: Path) -> None:
    """Calling ``close()`` twice must not raise.

    BridgeApp.stop() and test fixtures both call close() defensively.
    Idempotence keeps the cleanup path robust to double-shutdown.
    """
    db_path = tmp_path / "wo_idempotent.db"
    store = WorkOrderStore(db_path)
    store.close()
    store.close()  # second close must be a no-op, not a crash


# ---------------------------------------------------------------------------
# WS3.4 — list_all_runs (cross-workflow durable reader)
# ---------------------------------------------------------------------------


def _make_run(
    run_id: str,
    workflow_name: str,
    status: str,
    created_at: str,
) -> WorkflowRun:
    return WorkflowRun(
        id=run_id,
        workflow_name=workflow_name,
        status=status,
        current_step=None,
        context={},
        cost_usd=0.0,
        created_at=created_at,
        completed_at=None,
    )


def test_list_all_runs_newest_first(store: WorkOrderStore) -> None:
    store.save_workflow_run(_make_run("r1", "alpha", "running", "2026-06-01T00:00:00"))
    store.save_workflow_run(_make_run("r2", "beta", "completed", "2026-06-02T00:00:00"))
    store.save_workflow_run(_make_run("r3", "alpha", "running", "2026-06-03T00:00:00"))

    runs = store.list_all_runs()

    assert [r.id for r in runs] == ["r3", "r2", "r1"]


def test_list_all_runs_status_filter(store: WorkOrderStore) -> None:
    store.save_workflow_run(_make_run("r1", "alpha", "running", "2026-06-01T00:00:00"))
    store.save_workflow_run(
        _make_run("r2", "beta", "completed", "2026-06-02T00:00:00")
    )
    store.save_workflow_run(
        _make_run("r3", "alpha", "completed", "2026-06-03T00:00:00")
    )

    runs = store.list_all_runs(status="completed")

    assert [r.id for r in runs] == ["r3", "r2"]
    assert all(r.status == "completed" for r in runs)


def test_list_all_runs_limit(store: WorkOrderStore) -> None:
    store.save_workflow_run(_make_run("r1", "alpha", "running", "2026-06-01T00:00:00"))
    store.save_workflow_run(_make_run("r2", "beta", "running", "2026-06-02T00:00:00"))
    store.save_workflow_run(_make_run("r3", "alpha", "running", "2026-06-03T00:00:00"))

    runs = store.list_all_runs(limit=2)

    assert len(runs) == 2
    assert [r.id for r in runs] == ["r3", "r2"]
