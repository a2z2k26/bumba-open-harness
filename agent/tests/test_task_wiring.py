"""Tests for Sprint 21 PR — Task lifecycle wiring through delegate().

Covers:
- ``delegate(specialist, task)`` writes a Task row before invoking the
  specialist and transitions ASSIGNED → IN_PROGRESS → DONE on success.
- The Task carries directive_id from ctx.deps when set.
- Multiple delegations from one chief share the parent directive_id.
- A specialist exception transitions the Task to BLOCKED.
- When ctx.deps.database is None, delegate() runs unchanged with no
  Task table writes (backward compat).
- The specialist's child BridgeDeps carries task_id (Surface
  correlation prep).
- Existing EmployeeResult collector behaviour is preserved alongside
  the new Task layer.
"""
from __future__ import annotations

from pathlib import Path

import pytest
import pytest_asyncio

from datetime import datetime, timezone

from pydantic_ai import RunContext

from bridge.database import Database
from bridge.directive_store import (
    insert_directive as insert_directive_record,
    new_directive_id,
)
from bridge.task_store import (
    get_history,
    get_status,
    list_by_directive,
)
from teams._factory import build_employee_agents, build_manager_agent
from teams._types import (
    AgentSpec,
    BridgeDeps,
    Constraints,
    DepartmentConfig,
    Directive,
    EmployeeResult,
    TaskStatus,
)
from tests.test_teams.conftest import (
    make_chief_delegating_model,
    make_deps,
    make_specialist_text_model,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def db(tmp_path: Path) -> Database:
    db_path = tmp_path / "test-task-wiring.db"
    database = Database(db_path)
    await database.connect()
    await database.migrate()
    yield database
    await database.close()


def _config() -> DepartmentConfig:
    return DepartmentConfig(
        name="dept-t",
        zone=4,
        description="",
        manager=AgentSpec(name="t-chief", model="anthropic:claude-opus-4-6", role="chief"),
        employees=(
            AgentSpec(name="alpha", model="anthropic:claude-sonnet-4-6", role="alpha"),
            AgentSpec(name="beta", model="anthropic:claude-sonnet-4-6", role="beta"),
        ),
        constraints=Constraints(cost_limit_usd=1.0, timeout_seconds=60),
    )


async def _seed_directive(db: Database, *, directive_id: str | None = None) -> str:
    """Insert a real directive row so tasks with directive_id satisfy the FK."""
    did = directive_id or new_directive_id()
    d = Directive(
        directive_id=did,
        from_agent="main",
        to_chief="t-chief",
        intent="parent directive",
        constraints=(),
        deadline_utc=None,
        priority="p1",
        issued_at_utc=datetime.now(timezone.utc),
        context={},
        operator_id="op",
    )
    await insert_directive_record(db, d)
    return did


def _deps_with_db(db: Database, *, directive_id: str | None = None) -> BridgeDeps:
    base = make_deps(department="dept-t")
    return BridgeDeps(
        session_id=base.session_id,
        department=base.department,
        operator_id=base.operator_id,
        memory_store=base.memory_store,
        event_bus=base.event_bus,
        trust_manager=base.trust_manager,
        cost_tracker=base.cost_tracker,
        knowledge_search=base.knowledge_search,
        cost_limit_usd=base.cost_limit_usd,
        database=db,
        directive_id=directive_id,
    )


# ---------------------------------------------------------------------------
# delegate() writes a Task row
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestDelegateWritesTask:
    async def test_success_path_writes_assigned_in_progress_done(
        self, db: Database
    ) -> None:
        config = _config()
        employees = build_employee_agents(config)
        collector: list[EmployeeResult] = []
        manager = build_manager_agent(
            config, employees, employee_results_collector=collector
        )

        directive_id = await _seed_directive(db)
        deps = _deps_with_db(db, directive_id=directive_id)
        emp_model = make_specialist_text_model("alpha output")
        mgr_model = make_chief_delegating_model(
            [("alpha", "do alpha work")], final_answer="ok"
        )

        with employees["alpha"].override(model=emp_model):
            with manager.override(model=mgr_model):
                await manager.run("task", deps=deps)

        # Exactly one task row should exist
        rows = await db.fetchall("SELECT * FROM tasks", ())
        assert len(rows) == 1
        assert rows[0]["to_specialist"] == "alpha"
        assert rows[0]["from_chief"] == "t-chief"
        assert rows[0]["directive_id"] == directive_id
        assert rows[0]["status"] == "done"

        # History records the full lifecycle
        history = await get_history(db, rows[0]["task_id"])
        statuses = [h["to_status"] for h in history]
        assert statuses == ["assigned", "in_progress", "done"]

    async def test_specialist_exception_writes_blocked(
        self, db: Database
    ) -> None:
        config = _config()
        employees = build_employee_agents(config)
        collector: list[EmployeeResult] = []
        manager = build_manager_agent(
            config, employees, employee_results_collector=collector
        )

        deps = _deps_with_db(db)

        # Specialist raises
        from pydantic_ai.messages import ModelMessage, ModelResponse
        from pydantic_ai.models.function import AgentInfo, FunctionModel

        async def _boom(_msgs: list[ModelMessage], _info: AgentInfo) -> ModelResponse:
            raise RuntimeError("specialist exploded")

        emp_model = FunctionModel(_boom, model_name="boom")
        mgr_model = make_chief_delegating_model(
            [("alpha", "alpha task")], final_answer="recovered"
        )

        with employees["alpha"].override(model=emp_model):
            with manager.override(model=mgr_model):
                await manager.run("task", deps=deps)

        rows = await db.fetchall("SELECT * FROM tasks", ())
        assert len(rows) == 1
        assert rows[0]["status"] == "blocked"
        # EmployeeResult collector still recorded the failure
        assert len(collector) == 1
        assert collector[0].success is False
        assert "specialist exploded" in (collector[0].error or "")

    async def test_multiple_delegations_share_directive_id(
        self, db: Database
    ) -> None:
        config = _config()
        employees = build_employee_agents(config)
        manager = build_manager_agent(config, employees)

        directive_id = await _seed_directive(db)
        deps = _deps_with_db(db, directive_id=directive_id)

        emp_a = make_specialist_text_model("alpha out")
        emp_b = make_specialist_text_model("beta out")
        mgr_model = make_chief_delegating_model(
            [("alpha", "alpha work"), ("beta", "beta work")],
            final_answer="synthesised",
        )

        with employees["alpha"].override(model=emp_a):
            with employees["beta"].override(model=emp_b):
                with manager.override(model=mgr_model):
                    await manager.run("task", deps=deps)

        tasks = await list_by_directive(db, directive_id)
        assert len(tasks) == 2
        specialists = {t.to_specialist for t in tasks}
        assert specialists == {"alpha", "beta"}
        for t in tasks:
            assert t.directive_id == directive_id
            assert await get_status(db, t.task_id) == TaskStatus.DONE


# ---------------------------------------------------------------------------
# Backward compat: no database / no directive_id
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestBackwardCompat:
    async def test_no_database_no_writes_no_errors(self) -> None:
        """When ctx.deps.database is None, delegate runs unchanged."""
        config = _config()
        employees = build_employee_agents(config)
        collector: list[EmployeeResult] = []
        manager = build_manager_agent(
            config, employees, employee_results_collector=collector
        )

        deps = make_deps(department="dept-t")  # database is None
        assert deps.database is None

        emp_model = make_specialist_text_model("alpha output")
        mgr_model = make_chief_delegating_model(
            [("alpha", "alpha work")], final_answer="ok"
        )
        with employees["alpha"].override(model=emp_model):
            with manager.override(model=mgr_model):
                # Must not raise
                await manager.run("task", deps=deps)

        # Collector still populated (existing path)
        assert len(collector) == 1
        assert collector[0].employee_name == "alpha"

    async def test_no_directive_id_task_still_recorded(
        self, db: Database
    ) -> None:
        """Task is still recorded even without a directive_id (legacy /route).

        directive_id NULL is allowed by the FK.
        """
        config = _config()
        employees = build_employee_agents(config)
        manager = build_manager_agent(config, employees)

        deps = _deps_with_db(db, directive_id=None)
        emp_model = make_specialist_text_model("alpha output")
        mgr_model = make_chief_delegating_model(
            [("alpha", "alpha work")], final_answer="ok"
        )
        with employees["alpha"].override(model=emp_model):
            with manager.override(model=mgr_model):
                await manager.run("task", deps=deps)

        rows = await db.fetchall("SELECT * FROM tasks", ())
        assert len(rows) == 1
        assert rows[0]["directive_id"] is None
        assert rows[0]["status"] == "done"


# ---------------------------------------------------------------------------
# Specialist sees task_id on its child BridgeDeps
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_specialist_sees_task_id_on_child_deps(db: Database) -> None:
    """The specialist's child BridgeDeps must carry task_id for future
    Surface correlation. We capture deps inside a custom specialist tool
    that the FunctionModel triggers by returning a tool call."""
    config = _config()
    employees = build_employee_agents(config)

    captured_task_ids: list[str | None] = []

    # Register a marker tool on the specialist that captures ctx.deps.task_id.
    # RunContext is imported at module scope so pydantic-ai's lazy
    # get_type_hints can resolve the annotation against this module's
    # globals.
    @employees["alpha"].tool
    async def capture_task_id(ctx: RunContext[BridgeDeps]) -> str:
        """Capture the current task_id from deps."""
        captured_task_ids.append(getattr(ctx.deps, "task_id", None))
        return "captured"

    manager = build_manager_agent(config, employees)

    # Specialist FunctionModel: call _capture_task_id then return text
    from pydantic_ai.messages import (
        ModelMessage, ModelResponse, TextPart, ToolCallPart,
    )
    from pydantic_ai.models.function import AgentInfo, FunctionModel

    spec_call_count = {"n": 0}

    async def _spec(_msgs: list[ModelMessage], _info: AgentInfo) -> ModelResponse:
        spec_call_count["n"] += 1
        if spec_call_count["n"] == 1:
            return ModelResponse(parts=[
                ToolCallPart(tool_name="capture_task_id", args={})
            ])
        return ModelResponse(parts=[TextPart(content="alpha output")])

    directive_id = await _seed_directive(db)
    deps = _deps_with_db(db, directive_id=directive_id)
    mgr_model = make_chief_delegating_model(
        [("alpha", "alpha work")], final_answer="ok"
    )

    with employees["alpha"].override(model=FunctionModel(_spec, model_name="spec")):
        with manager.override(model=mgr_model):
            await manager.run("task", deps=deps)

    # The specialist saw a non-None task_id
    assert len(captured_task_ids) == 1
    assert captured_task_ids[0] is not None
    assert captured_task_ids[0].startswith("task-")
