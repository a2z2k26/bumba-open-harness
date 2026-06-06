"""SQLite-backed WorkOrder and WorkflowRun persistence."""

from __future__ import annotations

import json
import logging
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from bridge.work_order import WorkOrder, WorkOrderStatus

log = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS work_orders (
    id TEXT PRIMARY KEY,
    project TEXT NOT NULL,
    parent_id TEXT,
    status TEXT NOT NULL,
    data TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_wo_project ON work_orders(project);
CREATE INDEX IF NOT EXISTS idx_wo_status ON work_orders(status);
CREATE INDEX IF NOT EXISTS idx_wo_parent ON work_orders(parent_id);
"""

# S07 migration: add idempotency_key column (nullable)
_MIGRATION_S07 = """
ALTER TABLE work_orders ADD COLUMN idempotency_key TEXT;
CREATE UNIQUE INDEX IF NOT EXISTS idx_wo_idempotency ON work_orders(idempotency_key)
  WHERE idempotency_key IS NOT NULL;
"""

_WORKFLOW_RUNS_SCHEMA = """
CREATE TABLE IF NOT EXISTS workflow_runs (
    id TEXT PRIMARY KEY,
    workflow_name TEXT NOT NULL,
    status TEXT NOT NULL,
    current_step TEXT,
    context TEXT NOT NULL DEFAULT '{}',
    cost_usd REAL NOT NULL DEFAULT 0.0,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    completed_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_wr_status ON workflow_runs(status);
CREATE INDEX IF NOT EXISTS idx_wr_workflow ON workflow_runs(workflow_name);
"""


# ---------------------------------------------------------------------------
# Data class for workflow runs
# ---------------------------------------------------------------------------


@dataclass
class WorkflowRun:
    """Persisted state for a single workflow execution."""

    id: str
    workflow_name: str
    status: str  # running | awaiting_approval | completed | failed | cancelled
    current_step: str | None
    context: dict  # shared mutable context passed between steps
    cost_usd: float
    created_at: str
    completed_at: str | None


class WorkOrderStore:
    """SQLite-backed WorkOrder and WorkflowRun store."""

    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        self._conn = sqlite3.connect(str(db_path))
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(_SCHEMA)
        self._conn.executescript(_WORKFLOW_RUNS_SCHEMA)
        self._apply_s07_migration()
        self._apply_decomposition_migration()

    def _apply_s07_migration(self) -> None:
        """Add idempotency_key column if not present (idempotent)."""
        # Check if column exists
        cols = {
            row[1]
            for row in self._conn.execute("PRAGMA table_info(work_orders)").fetchall()
        }
        if "idempotency_key" not in cols:
            try:
                self._conn.execute("ALTER TABLE work_orders ADD COLUMN idempotency_key TEXT")
                self._conn.execute(
                    "CREATE UNIQUE INDEX IF NOT EXISTS idx_wo_idempotency "
                    "ON work_orders(idempotency_key) WHERE idempotency_key IS NOT NULL"
                )
                self._conn.commit()
                log.info("WorkOrderStore: applied S07 idempotency_key migration")
            except sqlite3.OperationalError as e:
                log.warning("WorkOrderStore: S07 migration skipped: %s", e)

    def _apply_decomposition_migration(self) -> None:
        """Sprint 07.01 — add ``decomposition_metadata`` column (idempotent).

        A queryable side-channel of the recursive ``Decomposition``
        plan; the canonical truth lives in the ``data`` JSON blob via
        ``WorkOrder.to_dict()`` / ``from_dict()``. Storing a
        normalized projection here lets future code list composite
        WOs by strategy or by atomic flag without scanning every
        row's ``data`` payload.

        Idempotent: a second run is a no-op (column-existence check
        before ``ALTER TABLE``).
        """
        cols = {
            row[1]
            for row in self._conn.execute("PRAGMA table_info(work_orders)").fetchall()
        }
        if "decomposition_metadata" not in cols:
            try:
                self._conn.execute(
                    "ALTER TABLE work_orders ADD COLUMN decomposition_metadata TEXT"
                )
                self._conn.commit()
                log.info(
                    "WorkOrderStore: applied 07.01 decomposition_metadata migration"
                )
            except sqlite3.OperationalError as e:
                log.warning(
                    "WorkOrderStore: decomposition migration skipped: %s", e
                )

    def find_by_idempotency_key(self, key: str) -> WorkOrder | None:
        """Return an existing WorkOrder with the given idempotency key, or None."""
        row = self._conn.execute(
            "SELECT data FROM work_orders WHERE idempotency_key = ?", (key,)
        ).fetchone()
        if row is None:
            return None
        return WorkOrder.from_dict(json.loads(row[0]))

    def save(self, wo: WorkOrder) -> None:
        data = json.dumps(wo.to_dict())
        idempotency_key = getattr(wo, "idempotency_key", None)
        # Sprint 07.01 — projection column. JSON for the Decomposition
        # plan or NULL when the WorkOrder has not been classified.
        decomposition = getattr(wo, "decomposition", None)
        decomposition_metadata = (
            json.dumps(decomposition.to_dict()) if decomposition is not None else None
        )
        self._conn.execute(
            """INSERT INTO work_orders (id, project, parent_id, status, data,
                                       idempotency_key, decomposition_metadata)
               VALUES (?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(id) DO UPDATE SET
                 status = excluded.status,
                 data = excluded.data,
                 idempotency_key = excluded.idempotency_key,
                 decomposition_metadata = excluded.decomposition_metadata,
                 updated_at = datetime('now')""",
            (
                wo.id,
                wo.project,
                wo.parent_id,
                wo.status.value,
                data,
                idempotency_key,
                decomposition_metadata,
            ),
        )
        self._conn.commit()

    def get(self, wo_id: str) -> WorkOrder | None:
        row = self._conn.execute(
            "SELECT data FROM work_orders WHERE id = ?", (wo_id,)
        ).fetchone()
        if row is None:
            return None
        return WorkOrder.from_dict(json.loads(row[0]))

    def list_by_project(self, project: str) -> list[WorkOrder]:
        rows = self._conn.execute(
            "SELECT data FROM work_orders WHERE project = ? ORDER BY created_at",
            (project,),
        ).fetchall()
        return [WorkOrder.from_dict(json.loads(r[0])) for r in rows]

    def list_by_status(self, status: WorkOrderStatus) -> list[WorkOrder]:
        rows = self._conn.execute(
            "SELECT data FROM work_orders WHERE status = ? ORDER BY created_at",
            (status.value,),
        ).fetchall()
        return [WorkOrder.from_dict(json.loads(r[0])) for r in rows]

    def list_children(self, parent_id: str) -> list[WorkOrder]:
        rows = self._conn.execute(
            "SELECT data FROM work_orders WHERE parent_id = ? ORDER BY created_at",
            (parent_id,),
        ).fetchall()
        return [WorkOrder.from_dict(json.loads(r[0])) for r in rows]

    def delete(self, wo_id: str) -> None:
        self._conn.execute("DELETE FROM work_orders WHERE id = ?", (wo_id,))
        self._conn.commit()

    def list_ready_to_dispatch(self, project: str) -> list[WorkOrder]:
        pending = self.list_by_status(WorkOrderStatus.PENDING)
        project_pending = [wo for wo in pending if wo.project == project]
        ready: list[WorkOrder] = []
        for wo in project_pending:
            if not wo.dependencies:
                ready.append(wo)
                continue
            all_deps_complete = True
            for dep_id in wo.dependencies:
                dep = self.get(dep_id)
                if dep is None or dep.status != WorkOrderStatus.COMPLETE:
                    all_deps_complete = False
                    break
            if all_deps_complete:
                ready.append(wo)
        return ready

    def close(self) -> None:
        self._conn.close()

    # ------------------------------------------------------------------
    # WorkflowRun CRUD
    # ------------------------------------------------------------------

    def save_workflow_run(self, run: WorkflowRun) -> None:
        """Insert or replace a workflow run record."""
        self._conn.execute(
            """INSERT INTO workflow_runs
               (id, workflow_name, status, current_step, context, cost_usd,
                created_at, completed_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(id) DO UPDATE SET
                 status = excluded.status,
                 current_step = excluded.current_step,
                 context = excluded.context,
                 cost_usd = excluded.cost_usd,
                 completed_at = excluded.completed_at""",
            (
                run.id,
                run.workflow_name,
                run.status,
                run.current_step,
                json.dumps(run.context),
                run.cost_usd,
                run.created_at,
                run.completed_at,
            ),
        )
        self._conn.commit()

    def get_workflow_run(self, run_id: str) -> WorkflowRun | None:
        """Fetch a workflow run by ID. Returns None if not found."""
        row = self._conn.execute(
            "SELECT id, workflow_name, status, current_step, context, "
            "cost_usd, created_at, completed_at "
            "FROM workflow_runs WHERE id = ?",
            (run_id,),
        ).fetchone()
        if row is None:
            return None
        return self._row_to_run(row)

    def list_active_runs(self) -> list[WorkflowRun]:
        """Return all non-terminal workflow runs (running + awaiting_approval)."""
        rows = self._conn.execute(
            "SELECT id, workflow_name, status, current_step, context, "
            "cost_usd, created_at, completed_at "
            "FROM workflow_runs "
            "WHERE status IN ('running', 'awaiting_approval') "
            "ORDER BY created_at",
        ).fetchall()
        return [self._row_to_run(r) for r in rows]

    def list_runs_for_workflow(
        self, workflow_name: str, limit: int = 20
    ) -> list[WorkflowRun]:
        """Return the most recent runs for a given workflow name."""
        rows = self._conn.execute(
            "SELECT id, workflow_name, status, current_step, context, "
            "cost_usd, created_at, completed_at "
            "FROM workflow_runs WHERE workflow_name = ? "
            "ORDER BY created_at DESC LIMIT ?",
            (workflow_name, limit),
        ).fetchall()
        return [self._row_to_run(r) for r in rows]

    def list_all_runs(
        self, limit: int = 50, status: str | None = None
    ) -> list[WorkflowRun]:
        """Return the most recent runs across all workflows, newest-first.

        Optional ``status`` narrows to a single status value. Used as the
        restart-durable cross-workflow run listing (WS3.4); siblings
        ``list_active_runs`` / ``list_runs_for_workflow`` scope by status set
        or workflow name respectively.
        """
        if status is None:
            rows = self._conn.execute(
                "SELECT id, workflow_name, status, current_step, context, "
                "cost_usd, created_at, completed_at "
                "FROM workflow_runs "
                "ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT id, workflow_name, status, current_step, context, "
                "cost_usd, created_at, completed_at "
                "FROM workflow_runs WHERE status = ? "
                "ORDER BY created_at DESC LIMIT ?",
                (status, limit),
            ).fetchall()
        return [self._row_to_run(r) for r in rows]

    def update_run_step(
        self,
        run_id: str,
        current_step: str,
        context: dict,
        cost_usd: float,
    ) -> None:
        """Update the current step and accumulated cost of an active run."""
        self._conn.execute(
            """UPDATE workflow_runs
               SET current_step = ?, context = ?, cost_usd = ?
               WHERE id = ?""",
            (current_step, json.dumps(context), cost_usd, run_id),
        )
        self._conn.commit()

    def complete_run(
        self,
        run_id: str,
        status: str,
        context: dict,
        cost_usd: float,
    ) -> None:
        """Finalise a workflow run with terminal status and completion time."""
        if status not in {"completed", "failed", "cancelled"}:
            raise ValueError(f"Invalid terminal status: {status!r}")
        self._conn.execute(
            """UPDATE workflow_runs
               SET status = ?, context = ?, cost_usd = ?,
                   completed_at = datetime('now'), current_step = NULL
               WHERE id = ?""",
            (status, json.dumps(context), cost_usd, run_id),
        )
        self._conn.commit()

    @staticmethod
    def _row_to_run(row: tuple) -> WorkflowRun:
        (
            run_id, workflow_name, status, current_step,
            context_json, cost_usd, created_at, completed_at,
        ) = row
        try:
            context = json.loads(context_json) if context_json else {}
        except (json.JSONDecodeError, TypeError):
            context = {}
        return WorkflowRun(
            id=run_id,
            workflow_name=workflow_name,
            status=status,
            current_step=current_step,
            context=context,
            cost_usd=cost_usd,
            created_at=created_at,
            completed_at=completed_at,
        )
