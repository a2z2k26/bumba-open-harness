"""Tests for workflow_runs table in WorkOrderStore (sprint F-W.2)."""

from __future__ import annotations

from pathlib import Path

import pytest

from bridge.work_order_store import WorkflowRun, WorkOrderStore


@pytest.fixture()
def store(tmp_path: Path) -> WorkOrderStore:
    return WorkOrderStore(tmp_path / "test.db")


def _make_run(
    run_id: str = "run-1",
    workflow_name: str = "weekly-ceo-review",
    status: str = "running",
    current_step: str | None = "gather-signals",
    context: dict | None = None,
    cost_usd: float = 0.0,
    created_at: str = "2026-04-18T08:00:00",
    completed_at: str | None = None,
) -> WorkflowRun:
    return WorkflowRun(
        id=run_id,
        workflow_name=workflow_name,
        status=status,
        current_step=current_step,
        context=context or {},
        cost_usd=cost_usd,
        created_at=created_at,
        completed_at=completed_at,
    )


class TestWorkflowRunsCRUD:
    def test_save_and_get(self, store: WorkOrderStore) -> None:
        run = _make_run()
        store.save_workflow_run(run)
        fetched = store.get_workflow_run("run-1")
        assert fetched is not None
        assert fetched.id == "run-1"
        assert fetched.workflow_name == "weekly-ceo-review"
        assert fetched.status == "running"
        assert fetched.current_step == "gather-signals"
        assert fetched.cost_usd == 0.0

    def test_get_nonexistent(self, store: WorkOrderStore) -> None:
        assert store.get_workflow_run("does-not-exist") is None

    def test_context_roundtrip(self, store: WorkOrderStore) -> None:
        run = _make_run(context={"signals": "some data", "count": 42})
        store.save_workflow_run(run)
        fetched = store.get_workflow_run("run-1")
        assert fetched is not None
        assert fetched.context["signals"] == "some data"
        assert fetched.context["count"] == 42

    def test_save_upserts(self, store: WorkOrderStore) -> None:
        run = _make_run()
        store.save_workflow_run(run)
        # Update status
        run.status = "completed"
        run.completed_at = "2026-04-18T08:05:00"
        store.save_workflow_run(run)
        fetched = store.get_workflow_run("run-1")
        assert fetched is not None
        assert fetched.status == "completed"
        assert fetched.completed_at == "2026-04-18T08:05:00"


class TestListActiveRuns:
    def test_active_runs_excludes_terminal(self, store: WorkOrderStore) -> None:
        store.save_workflow_run(_make_run("r1", status="running"))
        store.save_workflow_run(_make_run("r2", status="awaiting_approval"))
        store.save_workflow_run(_make_run("r3", status="completed"))
        store.save_workflow_run(_make_run("r4", status="failed"))

        active = store.list_active_runs()
        ids = {r.id for r in active}
        assert "r1" in ids
        assert "r2" in ids
        assert "r3" not in ids
        assert "r4" not in ids

    def test_empty_when_no_active(self, store: WorkOrderStore) -> None:
        store.save_workflow_run(_make_run("r1", status="completed"))
        assert store.list_active_runs() == []


class TestListRunsForWorkflow:
    def test_filters_by_workflow(self, store: WorkOrderStore) -> None:
        store.save_workflow_run(_make_run("r1", workflow_name="workflow-a"))
        store.save_workflow_run(_make_run("r2", workflow_name="workflow-b"))
        store.save_workflow_run(_make_run("r3", workflow_name="workflow-a"))

        runs = store.list_runs_for_workflow("workflow-a")
        assert len(runs) == 2
        assert all(r.workflow_name == "workflow-a" for r in runs)

    def test_limit_respected(self, store: WorkOrderStore) -> None:
        for i in range(5):
            store.save_workflow_run(_make_run(f"r{i}", workflow_name="wf"))
        runs = store.list_runs_for_workflow("wf", limit=3)
        assert len(runs) == 3


class TestUpdateRunStep:
    def test_updates_step_and_context(self, store: WorkOrderStore) -> None:
        run = _make_run()
        store.save_workflow_run(run)
        store.update_run_step(
            "run-1",
            current_step="synthesize",
            context={"signals": "data"},
            cost_usd=0.50,
        )
        fetched = store.get_workflow_run("run-1")
        assert fetched is not None
        assert fetched.current_step == "synthesize"
        assert fetched.context["signals"] == "data"
        assert fetched.cost_usd == 0.50


class TestCompleteRun:
    def test_complete_sets_terminal_fields(self, store: WorkOrderStore) -> None:
        run = _make_run()
        store.save_workflow_run(run)
        store.complete_run("run-1", "completed", {"digest": "summary"}, 1.25)
        fetched = store.get_workflow_run("run-1")
        assert fetched is not None
        assert fetched.status == "completed"
        assert fetched.context["digest"] == "summary"
        assert fetched.cost_usd == 1.25
        assert fetched.completed_at is not None
        assert fetched.current_step is None

    def test_failed_status(self, store: WorkOrderStore) -> None:
        run = _make_run()
        store.save_workflow_run(run)
        store.complete_run("run-1", "failed", {}, 0.1)
        fetched = store.get_workflow_run("run-1")
        assert fetched is not None
        assert fetched.status == "failed"

    def test_invalid_terminal_status(self, store: WorkOrderStore) -> None:
        run = _make_run()
        store.save_workflow_run(run)
        with pytest.raises(ValueError, match="Invalid terminal status"):
            store.complete_run("run-1", "running", {}, 0.0)


class TestSchemaExists:
    def test_tables_present(self, store: WorkOrderStore) -> None:
        cursor = store._conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
        tables = {row[0] for row in cursor.fetchall()}
        assert "work_orders" in tables
        assert "workflow_runs" in tables

    def test_indexes_present(self, store: WorkOrderStore) -> None:
        cursor = store._conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index'"
        )
        indexes = {row[0] for row in cursor.fetchall()}
        assert "idx_wr_status" in indexes
        assert "idx_wr_workflow" in indexes
