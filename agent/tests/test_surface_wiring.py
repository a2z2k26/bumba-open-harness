"""Tests for Sprint 22 PR A — Surface tool registration and synthesis.

Covers:
- ``surface()`` tool registered on every specialist (employee agent).
- ``surface()`` tool registered on every chief (manager agent).
- Specialist surface() writes a row with from=specialist, to=chief,
  correlation_id=task_id from ctx.deps.
- Chief surface() writes a row with from=chief, to="main",
  correlation_id=directive_id from ctx.deps.
- Surface store-write failures don't raise to the LLM (best-effort).
- Invalid kind/urgency raise ValueError so the LLM retries.
- ``_team.py`` synthesises missing RESULT surfaces for specialists that
  don't proactively call surface(kind='result').
- ``_team.py`` emits a chief→main RESULT surface on synthesis.
- Backward compat: when deps.database is None, the tool is a no-op
  returning a placeholder surface_id; _team.py synthesis is skipped.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest
import pytest_asyncio

from bridge.database import Database
from bridge.directive_store import insert_directive, new_directive_id
from bridge.surface_store import (
    list_by_correlation,
    task_has_result_surface,
)
from teams._factory import build_employee_agents, build_manager_agent
from teams._registry import DepartmentRegistry
from teams._types import (
    AgentSpec,
    BridgeDeps,
    Constraints,
    DepartmentConfig,
    Directive,
    SurfaceKind,
)
from tests.test_teams.conftest import (
    make_chief_delegating_model,
    make_chief_direct_answer_model,
    make_deps,
    make_specialist_text_model,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def db(tmp_path: Path) -> Database:
    db_path = tmp_path / "test-surface-wiring.db"
    database = Database(db_path)
    await database.connect()
    await database.migrate()
    yield database
    await database.close()


def _config() -> DepartmentConfig:
    return DepartmentConfig(
        name="dept-s",
        zone=4,
        description="",
        manager=AgentSpec(name="s-chief", model="anthropic:claude-opus-4-6", role="chief"),
        employees=(
            AgentSpec(name="alpha", model="anthropic:claude-sonnet-4-6", role="alpha"),
        ),
        constraints=Constraints(cost_limit_usd=1.0, timeout_seconds=60),
    )


async def _seed_directive(db: Database) -> str:
    d = Directive(
        directive_id=new_directive_id(),
        from_agent="main",
        to_chief="s-chief",
        intent="parent",
        constraints=(),
        deadline_utc=None,
        priority="p1",
        issued_at_utc=datetime.now(timezone.utc),
        context={},
        operator_id="op",
    )
    await insert_directive(db, d)
    return d.directive_id


def _deps(
    db: Database | None,
    *,
    directive_id: str | None = None,
    task_id: str | None = None,
    allow_no_surface_store: bool = False,
) -> BridgeDeps:
    base = make_deps(department="dept-s")
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
        task_id=task_id,
        allow_no_surface_store=allow_no_surface_store,
    )


# ---------------------------------------------------------------------------
# Tool registration
# ---------------------------------------------------------------------------


class TestSurfaceToolRegistered:
    def test_specialist_has_surface_tool(self) -> None:
        config = _config()
        employees = build_employee_agents(config)
        assert "surface" in employees["alpha"]._function_toolset.tools

    def test_chief_has_surface_tool(self) -> None:
        config = _config()
        employees = build_employee_agents(config)
        manager = build_manager_agent(config, employees)
        assert "surface" in manager._function_toolset.tools


# ---------------------------------------------------------------------------
# Specialist surface() semantics
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestSpecialistSurface:
    async def test_writes_specialist_to_chief(self, db: Database) -> None:
        config = _config()
        employees = build_employee_agents(config)
        surface_tool = employees["alpha"]._function_toolset.tools["surface"]

        class _Ctx:
            deps = _deps(db, task_id="task-specialist01")

        sid = await surface_tool.function(
            _Ctx(),
            kind="result",
            urgency="fyi",
            payload={"output": "alpha did the work"},
        )
        assert sid.startswith("surf-")
        rows = await db.fetchall(
            "SELECT * FROM surfaces WHERE surface_id = ?", (sid,)
        )
        assert len(rows) == 1
        assert rows[0]["from_agent"] == "alpha"
        assert rows[0]["to_agent"] == "s-chief"
        assert rows[0]["correlation_id"] == "task-specialist01"
        assert rows[0]["kind"] == "result"

    async def test_invalid_kind_raises_value_error(self, db: Database) -> None:
        config = _config()
        employees = build_employee_agents(config)
        surface_tool = employees["alpha"]._function_toolset.tools["surface"]

        class _Ctx:
            deps = _deps(db, task_id="task-x")

        with pytest.raises(ValueError):
            await surface_tool.function(
                _Ctx(), kind="not-a-kind", urgency="fyi"
            )

    async def test_invalid_urgency_raises_value_error(
        self, db: Database
    ) -> None:
        config = _config()
        employees = build_employee_agents(config)
        surface_tool = employees["alpha"]._function_toolset.tools["surface"]

        class _Ctx:
            deps = _deps(db, task_id="task-x")

        with pytest.raises(ValueError):
            await surface_tool.function(
                _Ctx(), kind="flag", urgency="screaming"
            )

    async def test_no_database_with_optout_returns_placeholder(self) -> None:
        """Sprint P3.5: with allow_no_surface_store=True the surface tool
        falls back to placeholder behavior (no row written, no raise).
        This preserves the lightweight test path."""
        config = _config()
        employees = build_employee_agents(config)
        surface_tool = employees["alpha"]._function_toolset.tools["surface"]

        class _Ctx:
            deps = _deps(None, task_id="task-x", allow_no_surface_store=True)

        # No-op: returns a surface_id without writing
        sid = await surface_tool.function(
            _Ctx(), kind="flag", urgency="attention"
        )
        assert sid.startswith("surf-")

    async def test_no_database_no_optout_raises(self) -> None:
        """Sprint P3.5: production deps without DB and without explicit
        opt-out MUST raise MissingSurfaceStoreError when a correlation_id
        (here: task_id) is in scope. This upgrades a silent no-op to a
        loud halt so directive/surface workflows fail safely."""
        from bridge.surface_store import MissingSurfaceStoreError

        config = _config()
        employees = build_employee_agents(config)
        surface_tool = employees["alpha"]._function_toolset.tools["surface"]

        class _Ctx:
            deps = _deps(None, task_id="task-x")  # allow_no_surface_store=False

        with pytest.raises(MissingSurfaceStoreError):
            await surface_tool.function(
                _Ctx(), kind="flag", urgency="attention"
            )

    async def test_no_database_no_correlation_id_returns_placeholder(self) -> None:
        """Sprint P3.5: out-of-band surfaces (no correlation_id in scope)
        keep the original best-effort no-op so test fixtures that call
        surface() outside a directive flow still work without explicit
        opt-out. The fatal path is gated on having a correlation_id."""
        config = _config()
        employees = build_employee_agents(config)
        surface_tool = employees["alpha"]._function_toolset.tools["surface"]

        class _Ctx:
            deps = _deps(None)  # no directive_id, no task_id

        sid = await surface_tool.function(
            _Ctx(), kind="flag", urgency="attention"
        )
        assert sid.startswith("surf-")


# ---------------------------------------------------------------------------
# Chief surface() semantics
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestChiefSurface:
    async def test_writes_chief_to_main(self, db: Database) -> None:
        config = _config()
        employees = build_employee_agents(config)
        manager = build_manager_agent(config, employees)
        surface_tool = manager._function_toolset.tools["surface"]

        directive_id = await _seed_directive(db)

        class _Ctx:
            deps = _deps(db, directive_id=directive_id)

        sid = await surface_tool.function(
            _Ctx(),
            kind="policy_q",
            urgency="immediate",
            payload={"summary": "should we proceed?"},
        )
        rows = await db.fetchall(
            "SELECT * FROM surfaces WHERE surface_id = ?", (sid,)
        )
        assert len(rows) == 1
        assert rows[0]["from_agent"] == "s-chief"
        assert rows[0]["to_agent"] == "main"
        assert rows[0]["correlation_id"] == directive_id
        assert rows[0]["kind"] == "policy_q"
        assert rows[0]["urgency"] == "immediate"


# ---------------------------------------------------------------------------
# _team.py synthesis: missing-result and chief-synthesis
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestTeamSynthesis:
    async def test_synthesises_missing_specialist_result(
        self, db: Database
    ) -> None:
        """Specialist returns text but never calls surface() — _team.py
        must synthesise a RESULT surface so the dashboard sees one."""
        config = _config()
        directive_id = await _seed_directive(db)
        registry = DepartmentRegistry(configs={config.name: config})
        team = registry.get_team(config.name)

        emp_model = make_specialist_text_model("alpha output (no surface)")
        mgr_model = make_chief_delegating_model(
            [("alpha", "alpha work")], final_answer="ok"
        )
        deps = _deps(db, directive_id=directive_id)

        with team.employees["alpha"].override(model=emp_model):
            with team.manager.override(model=mgr_model):
                await registry.route(
                    config.name, "task", deps, directive_id=directive_id,
                )

        # Find the specialist's task
        task_rows = await db.fetchall(
            "SELECT task_id FROM tasks WHERE directive_id = ?",
            (directive_id,),
        )
        assert len(task_rows) == 1
        task_id = task_rows[0]["task_id"]

        # A synthesised RESULT surface exists
        assert await task_has_result_surface(db, task_id) is True
        surfaces = await list_by_correlation(db, task_id)
        result_surfaces = [s for s in surfaces if s.kind == SurfaceKind.RESULT]
        assert len(result_surfaces) == 1
        assert result_surfaces[0].payload.get("synthesized") is True
        assert "alpha output" in result_surfaces[0].payload.get("output", "")

    @pytest.mark.skip(
        reason=(
            "strict-floor activated 2026-05-12 per #1645 + classification doc "
            "(docs/architecture/2026-05-12-1645-delegation-floor-classification.md, "
            "Class A). Test name and semantics specifically claim "
            "chief→main RESULT on direct-answer synthesis is a valid lifecycle, "
            "which is the legacy contract this sprint retires."
        )
    )
    async def test_emits_chief_to_main_result_on_synthesis(
        self, db: Database
    ) -> None:
        config = _config()
        directive_id = await _seed_directive(db)
        registry = DepartmentRegistry(configs={config.name: config})
        team = registry.get_team(config.name)

        mgr_model = make_chief_direct_answer_model("the synthesis answer")
        deps = _deps(db, directive_id=directive_id)

        with team.manager.override(model=mgr_model):
            await registry.route(
                config.name, "task", deps, directive_id=directive_id,
            )

        # A chief→main RESULT surface should exist for this directive
        surfaces = await list_by_correlation(db, directive_id)
        chief_to_main = [
            s for s in surfaces
            if s.from_agent == "s-chief"
            and s.to_agent == "main"
            and s.kind == SurfaceKind.RESULT
        ]
        assert len(chief_to_main) == 1
        assert chief_to_main[0].payload.get("synthesized") is True
        assert "the synthesis answer" in chief_to_main[0].payload.get("answer", "")

    async def test_no_directive_id_no_synthesis(
        self, db: Database
    ) -> None:
        """When there's no directive_id, _team.py skips surface synthesis
        — there's no correlation key to thread through."""
        config = _config()
        registry = DepartmentRegistry(configs={config.name: config})
        team = registry.get_team(config.name)

        emp_model = make_specialist_text_model("alpha output")
        mgr_model = make_chief_delegating_model(
            [("alpha", "work")], final_answer="ok"
        )
        deps = _deps(db, directive_id=None)

        with team.employees["alpha"].override(model=emp_model):
            with team.manager.override(model=mgr_model):
                await registry.route(config.name, "task", deps)

        rows = await db.fetchall("SELECT COUNT(*) AS n FROM surfaces", ())
        assert rows[0]["n"] == 0

    async def test_proactive_chief_surface_not_double_emitted(
        self, db: Database
    ) -> None:
        """If the chief proactively calls surface(kind='result') during the
        run, _team.py must NOT emit a second synthesised one."""
        config = _config()
        directive_id = await _seed_directive(db)
        registry = DepartmentRegistry(configs={config.name: config})
        team = registry.get_team(config.name)

        # Chief FunctionModel: emit a chief→main RESULT surface mid-run,
        # then return the structured TeamOutput on the next turn.
        from pydantic_ai.messages import (
            ModelMessage, ModelResponse, ToolCallPart,
        )
        from pydantic_ai.models.function import AgentInfo, FunctionModel

        call = {"n": 0}

        async def _chief(_msgs: list[ModelMessage], _info: AgentInfo) -> ModelResponse:
            call["n"] += 1
            if call["n"] == 1:
                return ModelResponse(parts=[
                    ToolCallPart(
                        tool_name="surface",
                        args={
                            "kind": "result",
                            "urgency": "fyi",
                            "payload": {"answer": "proactive answer"},
                        },
                    )
                ])
            return ModelResponse(parts=[
                ToolCallPart(
                    tool_name="final_result",
                    args={"answer": "proactive answer", "specialist_outputs": []},
                )
            ])

        deps = _deps(db, directive_id=directive_id)
        with team.manager.override(model=FunctionModel(_chief, model_name="proactive-chief")):
            await registry.route(
                config.name, "task", deps, directive_id=directive_id,
            )

        # Exactly one chief→main RESULT (the proactive one), not two
        surfaces = await list_by_correlation(db, directive_id)
        chief_to_main_results = [
            s for s in surfaces
            if s.from_agent == "s-chief"
            and s.to_agent == "main"
            and s.kind == SurfaceKind.RESULT
        ]
        assert len(chief_to_main_results) == 1
        # The proactive one — synthesized flag should NOT be true
        assert chief_to_main_results[0].payload.get("synthesized") is not True
        assert chief_to_main_results[0].payload.get("answer") == "proactive answer"


# ---------------------------------------------------------------------------
# Sprint P3.5 — required surface store + TeamResult.surface_id
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestRequiredSurfaceStore:
    """Sprint P3.5 acceptance: a successful chief session always has a
    chief→main RESULT surface, and the surface_id rides back on
    TeamResult so downstream readers can correlate the session to its
    handoff row."""

    async def test_team_result_surface_id_populated_on_synthesis(
        self, db: Database
    ) -> None:
        """A successful directive-scoped run populates TeamResult.surface_id
        with the chief→main RESULT id that the chief just emitted."""
        config = _config()
        directive_id = await _seed_directive(db)
        registry = DepartmentRegistry(configs={config.name: config})
        team = registry.get_team(config.name)

        mgr_model = make_chief_direct_answer_model("synth answer")
        deps = _deps(db, directive_id=directive_id)

        with team.manager.override(model=mgr_model):
            result = await team.run(
                "task", deps=deps, directive_id=directive_id,
            )

        assert result.success is True
        assert result.surface_id is not None
        assert result.surface_id.startswith("surf-")

        # The id on TeamResult must match the actual row in the surfaces
        # table — proves the handoff artifact is real, not a placeholder.
        surfaces = await list_by_correlation(db, directive_id)
        chief_to_main = [
            s for s in surfaces
            if s.from_agent == "s-chief"
            and s.to_agent == "main"
            and s.kind == SurfaceKind.RESULT
        ]
        assert len(chief_to_main) == 1
        assert chief_to_main[0].surface_id == result.surface_id

    async def test_team_result_surface_id_matches_proactive_chief(
        self, db: Database
    ) -> None:
        """When the chief proactively emits a RESULT surface mid-run, the
        TeamResult.surface_id MUST reference that proactive surface — not
        a synthesised duplicate. Acceptance: 'always has a chief-to-main
        RESULT surface' is satisfied by the proactive one."""
        config = _config()
        directive_id = await _seed_directive(db)
        registry = DepartmentRegistry(configs={config.name: config})
        team = registry.get_team(config.name)

        from pydantic_ai.messages import (
            ModelMessage, ModelResponse, ToolCallPart,
        )
        from pydantic_ai.models.function import AgentInfo, FunctionModel

        call = {"n": 0}

        async def _chief(_m: list[ModelMessage], _i: AgentInfo) -> ModelResponse:
            call["n"] += 1
            if call["n"] == 1:
                return ModelResponse(parts=[
                    ToolCallPart(
                        tool_name="surface",
                        args={
                            "kind": "result",
                            "urgency": "fyi",
                            "payload": {"answer": "proactive"},
                        },
                    )
                ])
            return ModelResponse(parts=[
                ToolCallPart(
                    tool_name="final_result",
                    args={"answer": "proactive", "specialist_outputs": []},
                )
            ])

        deps = _deps(db, directive_id=directive_id)
        with team.manager.override(
            model=FunctionModel(_chief, model_name="proactive-chief")
        ):
            result = await team.run(
                "task", deps=deps, directive_id=directive_id,
            )

        # Surface id on result must equal the proactive surface row's id
        assert result.surface_id is not None
        surfaces = await list_by_correlation(db, directive_id)
        chief_to_main = [
            s for s in surfaces
            if s.from_agent == "s-chief"
            and s.to_agent == "main"
            and s.kind == SurfaceKind.RESULT
        ]
        assert len(chief_to_main) == 1
        assert chief_to_main[0].surface_id == result.surface_id
        # Sanity: this is the proactive one, not a synthesised duplicate
        assert chief_to_main[0].payload.get("synthesized") is not True

    async def test_no_directive_no_surface_id(self, db: Database) -> None:
        """Backwards compat: legacy /route paths without directive_id
        produce a TeamResult with surface_id=None — no surface row is
        written when there's no correlation key."""
        config = _config()
        registry = DepartmentRegistry(configs={config.name: config})
        team = registry.get_team(config.name)

        mgr_model = make_chief_direct_answer_model("answer")
        deps = _deps(db, directive_id=None)

        with team.manager.override(model=mgr_model):
            result = await team.run("task", deps=deps)  # no directive_id

        assert result.success is True
        assert result.surface_id is None

    async def test_run_refuses_when_directive_and_no_database(self) -> None:
        """Sprint P3.5: production path with directive_id but no Database
        and no opt-out MUST fail fast. Returns success=False with a
        diagnostic error rather than running the chief and producing an
        un-correlated answer."""
        from teams._team import DepartmentTeam

        config = _config()
        team = DepartmentTeam(config, lazy_build=False)
        # database=None, allow_no_surface_store=False (default)
        deps = _deps(None, directive_id="dir-fake-12")

        with team.manager.override(
            model=make_chief_direct_answer_model("would-be answer")
        ):
            result = await team.run(
                "task", deps=deps, directive_id="dir-fake-12",
            )

        assert result.success is False
        assert "missing surface store" in (result.error or "")
        assert result.surface_id is None

    async def test_run_allows_no_database_with_optout(self) -> None:
        """Sprint P3.5: lightweight test path — directive_id supplied but
        DB is None — succeeds when allow_no_surface_store=True. The chief
        runs; no surface row is written; surface_id stays None."""
        from teams._team import DepartmentTeam

        config = _config()
        team = DepartmentTeam(config, lazy_build=False)
        deps = _deps(
            None, directive_id="dir-test-12", allow_no_surface_store=True,
        )

        with team.manager.override(model=make_chief_direct_answer_model("ok")):
            result = await team.run(
                "task", deps=deps, directive_id="dir-test-12",
            )

        assert result.success is True
        assert result.surface_id is None  # no DB → no row → no id
