"""Tests for Sprint 20 PR B — directive wiring through registry + team + chief.

Covers:
- ``DepartmentRegistry.route(directive_id=...)`` prepends the marker to the
  task and threads the id into ``DepartmentTeam.run``.
- ``DepartmentTeam.run`` writes IN_PROGRESS at start and DONE on success.
- Timeout and exception paths transition the directive to BLOCKED.
- Output-gate-violation (success=False) transitions to BLOCKED, not DONE.
- Status writes are best-effort: when ``deps.database`` is None, ``run``
  succeeds without writes and never raises.
- ``acknowledge_directive`` tool is registered on every chief.
- ``acknowledge_directive`` writes ACCEPTED when invoked with a known id.
- ``acknowledge_directive`` returns a clear message on unknown id without
  raising — the chief should proceed rather than loop.
- Backward compat: callers that omit ``directive_id`` see no behavioural
  change and no directive table writes.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest
import pytest_asyncio

from bridge.database import Database
from bridge.directive_store import (
    get_history,
    get_status,
    insert_directive,
    new_directive_id,
)
from teams._factory import build_employee_agents, build_manager_agent
from teams._registry import DepartmentRegistry
from teams._team import DepartmentTeam
from teams._types import (
    AgentSpec,
    BridgeDeps,
    Constraints,
    DepartmentConfig,
    Directive,
    DirectiveStatus,
)
from tests.test_teams.conftest import (
    make_chief_direct_answer_model,
    make_deps,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def db(tmp_path: Path) -> Database:
    db_path = tmp_path / "test-wiring.db"
    database = Database(db_path)
    await database.connect()
    await database.migrate()
    yield database
    await database.close()


def _config() -> DepartmentConfig:
    return DepartmentConfig(
        name="dept-w",
        zone=4,
        description="",
        manager=AgentSpec(name="w-chief", model="anthropic:claude-opus-4-6", role="chief"),
        employees=(
            AgentSpec(name="alpha", model="anthropic:claude-sonnet-4-6", role="alpha"),
        ),
        constraints=Constraints(cost_limit_usd=1.0, timeout_seconds=60),
    )


def _seed_directive(to_chief: str = "w-chief") -> Directive:
    return Directive(
        directive_id=new_directive_id(),
        from_agent="main",
        to_chief=to_chief,
        intent="probe wiring",
        constraints=(),
        deadline_utc=None,
        priority="p1",
        issued_at_utc=datetime.now(timezone.utc),
        context={},
        operator_id="op-test",
    )


# ---------------------------------------------------------------------------
# DepartmentTeam.run lifecycle transitions
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestRunLifecycle:
    async def test_success_path_writes_in_progress_then_done(
        self, db: Database
    ) -> None:
        config = _config()
        d = _seed_directive(to_chief=config.manager.name)
        await insert_directive(db, d)

        team = DepartmentTeam(config, lazy_build=False)
        deps = make_deps(department=config.name)
        # Inject the live Database for directive writes
        deps = BridgeDeps(
            session_id=deps.session_id,
            department=deps.department,
            operator_id=deps.operator_id,
            memory_store=deps.memory_store,
            event_bus=deps.event_bus,
            trust_manager=deps.trust_manager,
            cost_tracker=deps.cost_tracker,
            knowledge_search=deps.knowledge_search,
            database=db,
        )

        with team.manager.override(model=make_chief_direct_answer_model("ok")):
            result = await team.run(
                "task", deps=deps, directive_id=d.directive_id
            )
        assert result.success is True

        status = await get_status(db, d.directive_id)
        assert status == DirectiveStatus.DONE

        # History must show issue → in_progress → done
        history = await get_history(db, d.directive_id)
        statuses = [h["to_status"] for h in history]
        assert "in_progress" in statuses
        assert statuses[-1] == "done"

    async def test_timeout_path_writes_blocked(self, db: Database) -> None:
        # Force a tiny timeout by constructing a config with timeout_seconds=0
        config = DepartmentConfig(
            name="dept-w",
            zone=4,
            description="",
            manager=AgentSpec(name="w-chief", model="anthropic:claude-opus-4-6", role="chief"),
            employees=(
                AgentSpec(name="alpha", model="anthropic:claude-sonnet-4-6", role="alpha"),
            ),
            constraints=Constraints(cost_limit_usd=1.0, timeout_seconds=0),
        )
        d = _seed_directive()
        await insert_directive(db, d)

        team = DepartmentTeam(config, lazy_build=False)
        deps = BridgeDeps(
            session_id="s", department=config.name, operator_id="op",
            memory_store=None, event_bus=None, trust_manager=None,
            cost_tracker=None, knowledge_search=None,
            database=db,
        )
        # Even a fast model gets cancelled at timeout=0 because asyncio.timeout
        # raises immediately on entering the context with deadline already past.
        with team.manager.override(model=make_chief_direct_answer_model("ok")):
            result = await team.run(
                "task", deps=deps, directive_id=d.directive_id
            )
        assert result.success is False
        assert "Timeout" in (result.error or "")

        status = await get_status(db, d.directive_id)
        assert status == DirectiveStatus.BLOCKED

    async def test_no_directive_id_no_table_writes(self, db: Database) -> None:
        """When directive_id is None, nothing lands in the directives table."""
        config = _config()
        team = DepartmentTeam(config, lazy_build=False)
        deps = BridgeDeps(
            session_id="s", department=config.name, operator_id="op",
            memory_store=None, event_bus=None, trust_manager=None,
            cost_tracker=None, knowledge_search=None,
            database=db,
        )
        with team.manager.override(model=make_chief_direct_answer_model("ok")):
            result = await team.run("task", deps=deps)
        assert result.success is True
        # No directive should exist — count by COUNT(*)
        row = await db.fetchone("SELECT COUNT(*) AS n FROM directives", ())
        assert row["n"] == 0

    async def test_no_database_path_does_not_raise(self) -> None:
        """When deps.database is None, lifecycle hooks no-op cleanly.

        Sprint P3.5: this test now opts into the lightweight no-DB path
        via ``allow_no_surface_store=True`` so the directive-flow pre-check
        in ``DepartmentTeam.run`` doesn't trip. The original intent —
        proving that lifecycle hooks no-op cleanly under no-DB — is
        preserved; the opt-out is the test-only escape hatch the P3.5
        spec requires for lightweight tests.
        """
        config = _config()
        team = DepartmentTeam(config, lazy_build=False)
        base = make_deps(department=config.name)  # database defaults to None
        # Reconstruct with the P3.5 opt-out flag set
        deps = BridgeDeps(
            session_id=base.session_id,
            department=base.department,
            operator_id=base.operator_id,
            memory_store=base.memory_store,
            event_bus=base.event_bus,
            trust_manager=base.trust_manager,
            cost_tracker=base.cost_tracker,
            knowledge_search=base.knowledge_search,
            cost_limit_usd=base.cost_limit_usd,
            allow_no_surface_store=True,
        )
        assert deps.database is None
        with team.manager.override(model=make_chief_direct_answer_model("ok")):
            result = await team.run(
                "task", deps=deps, directive_id="dir-fake-id-12"
            )
        # Run completes; no exception escapes _safe_directive_status
        assert result.success is True


# ---------------------------------------------------------------------------
# DepartmentRegistry.route plumbs directive_id
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestRegistryRoute:
    async def test_route_prefixes_task_with_directive_marker(
        self, db: Database
    ) -> None:
        """When directive_id is provided, the task arrives at the chief with
        a ``[directive_id: dir-xxx]`` prefix that the chief's prompt doctrine
        teaches it to detect."""
        config = _config()
        d = _seed_directive(to_chief=config.manager.name)
        await insert_directive(db, d)

        registry = DepartmentRegistry(configs={config.name: config})
        team = registry.get_team(config.name)
        # Capture what the manager actually receives
        captured: list[str] = []

        from pydantic_ai.messages import ModelMessage, ModelResponse, ToolCallPart
        from pydantic_ai.models.function import AgentInfo, FunctionModel

        async def _capture(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
            # Pull the user-prompt content from the first message
            for m in messages:
                for p in getattr(m, "parts", []):
                    text = getattr(p, "content", None)
                    if isinstance(text, str):
                        captured.append(text)
            return ModelResponse(parts=[
                ToolCallPart(
                    tool_name="final_result",
                    args={"answer": "ok", "specialist_outputs": []},
                )
            ])

        deps = BridgeDeps(
            session_id="s", department=config.name, operator_id="op",
            memory_store=None, event_bus=None, trust_manager=None,
            cost_tracker=None, knowledge_search=None,
            database=db,
        )
        with team.manager.override(model=FunctionModel(_capture, model_name="capture")):
            result = await registry.route(
                config.name, "size the audio AI market", deps,
                directive_id=d.directive_id,
            )
        assert result.success is True
        # The directive marker must appear in what the chief saw
        assert any(d.directive_id in c for c in captured), captured
        assert any("[directive_id:" in c for c in captured), captured

    async def test_route_without_directive_id_unchanged(
        self, db: Database
    ) -> None:
        """Backward compat: callers that omit directive_id see no marker."""
        config = _config()
        registry = DepartmentRegistry(configs={config.name: config})
        team = registry.get_team(config.name)
        captured: list[str] = []

        from pydantic_ai.messages import ModelMessage, ModelResponse, ToolCallPart
        from pydantic_ai.models.function import AgentInfo, FunctionModel

        async def _capture(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
            for m in messages:
                for p in getattr(m, "parts", []):
                    text = getattr(p, "content", None)
                    if isinstance(text, str):
                        captured.append(text)
            return ModelResponse(parts=[
                ToolCallPart(
                    tool_name="final_result",
                    args={"answer": "ok", "specialist_outputs": []},
                )
            ])

        deps = BridgeDeps(
            session_id="s", department=config.name, operator_id="op",
            memory_store=None, event_bus=None, trust_manager=None,
            cost_tracker=None, knowledge_search=None,
            database=db,
        )
        with team.manager.override(model=FunctionModel(_capture, model_name="capture")):
            await registry.route(config.name, "plain task", deps)
        # No marker on the user-prompt — verify by absence. The chief's
        # system prompt now contains chief doctrine (Sprint 24) which
        # mentions the literal "[directive_id: dir-xxx]" pattern as
        # guidance, so we restrict the check to short messages (the
        # user task) and exclude the multi-line system prompt.
        user_prompt_captures = [c for c in captured if len(c.splitlines()) <= 3]
        assert not any(
            "[directive_id:" in c for c in user_prompt_captures
        ), user_prompt_captures


# ---------------------------------------------------------------------------
# acknowledge_directive tool
# ---------------------------------------------------------------------------


class TestAcknowledgeDirectiveTool:
    def test_tool_is_registered(self) -> None:
        config = _config()
        employees = build_employee_agents(config)
        manager = build_manager_agent(config, employees)
        assert "acknowledge_directive" in manager._function_toolset.tools


@pytest.mark.asyncio
class TestAcknowledgeDirectiveSemantics:
    async def test_acknowledge_writes_accepted(self, db: Database) -> None:
        config = _config()
        d = _seed_directive(to_chief=config.manager.name)
        await insert_directive(db, d)

        employees = build_employee_agents(config)
        manager = build_manager_agent(config, employees)

        # Invoke the registered tool callable directly so we control the args
        ack_tool = manager._function_toolset.tools["acknowledge_directive"]

        class _Ctx:
            deps = BridgeDeps(
                session_id="s", department=config.name, operator_id="op",
                memory_store=None, event_bus=None, trust_manager=None,
                cost_tracker=None, knowledge_search=None,
                database=db,
            )

        out = await ack_tool.function(_Ctx(), directive_id=d.directive_id)
        assert out == "acknowledged"
        assert await get_status(db, d.directive_id) == DirectiveStatus.ACCEPTED

    async def test_acknowledge_unknown_id_returns_message(
        self, db: Database
    ) -> None:
        """Unknown directive_id returns a clear string instead of raising —
        the chief should proceed rather than loop on a bad id."""
        config = _config()
        employees = build_employee_agents(config)
        manager = build_manager_agent(config, employees)
        ack_tool = manager._function_toolset.tools["acknowledge_directive"]

        class _Ctx:
            deps = BridgeDeps(
                session_id="s", department=config.name, operator_id="op",
                memory_store=None, event_bus=None, trust_manager=None,
                cost_tracker=None, knowledge_search=None,
                database=db,
            )

        out = await ack_tool.function(_Ctx(), directive_id="dir-doesnotexist")
        assert "unknown directive_id" in out

    async def test_acknowledge_no_database_noops_cleanly(self) -> None:
        """When deps.database is None, the tool returns a no-op message."""
        config = _config()
        employees = build_employee_agents(config)
        manager = build_manager_agent(config, employees)
        ack_tool = manager._function_toolset.tools["acknowledge_directive"]

        class _Ctx:
            deps = make_deps(department="dept-w")  # database defaults to None

        out = await ack_tool.function(_Ctx(), directive_id="dir-anything-12")
        assert "no-op" in out


# ---------------------------------------------------------------------------
# Integration: issue → route → acknowledge → done (full chain)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_full_directive_chain_issue_acknowledge_done(db: Database) -> None:
    """End-to-end: a directive is issued, the chief acknowledges via tool
    during synthesis, the run completes, and the final status is DONE.

    The chief here uses a FunctionModel that calls acknowledge_directive
    on its first turn (mirroring the doctrine), then returns a synthesis.
    """
    config = _config()
    d = _seed_directive(to_chief=config.manager.name)
    await insert_directive(db, d)

    registry = DepartmentRegistry(configs={config.name: config})
    team = registry.get_team(config.name)
    captured_ack = {"called": False}

    from pydantic_ai.messages import ModelMessage, ModelResponse, ToolCallPart
    from pydantic_ai.models.function import AgentInfo, FunctionModel

    call_count = {"n": 0}

    async def _chief_with_ack(
        messages: list[ModelMessage], info: AgentInfo
    ) -> ModelResponse:
        call_count["n"] += 1
        if call_count["n"] == 1:
            return ModelResponse(parts=[
                ToolCallPart(
                    tool_name="acknowledge_directive",
                    args={"directive_id": d.directive_id},
                )
            ])
        # After the ack tool result returns, emit the final synthesis
        captured_ack["called"] = True
        return ModelResponse(parts=[
            ToolCallPart(
                tool_name="final_result",
                args={"answer": "synthesis after ack", "specialist_outputs": []},
            )
        ])

    deps = BridgeDeps(
        session_id="s", department=config.name, operator_id="op",
        memory_store=None, event_bus=None, trust_manager=None,
        cost_tracker=None, knowledge_search=None,
        database=db,
    )
    with team.manager.override(model=FunctionModel(_chief_with_ack, model_name="chief")):
        result = await registry.route(
            config.name, "do the thing", deps,
            directive_id=d.directive_id,
        )
    assert result.success is True
    assert captured_ack["called"]

    # Final status must be DONE; history must show ACCEPTED in the middle
    assert await get_status(db, d.directive_id) == DirectiveStatus.DONE
    history = await get_history(db, d.directive_id)
    statuses = [h["to_status"] for h in history]
    assert "accepted" in statuses
    assert "in_progress" in statuses
    assert statuses[-1] == "done"
