"""Tests for Sprint 04.08 — ConversationLogger writer wiring in DepartmentTeam.run.

Covers:
- BridgeDeps.sessions_dir field (default None, populated via from_app)
- DepartmentRegistry constructs ConversationLogger when sessions_dir is set
- DepartmentTeam.run() writes directive + delegation + result + synthesis lines
- JSONL path matches the reader expectation:
    sessions_dir / session_id / department / "conversation.jsonl"
- Logging exceptions never break the run
- Missing sessions_dir → no writes, no error
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from bridge.conversation_log import (
    ConversationLogger,
    ConversationReader,
    MessageType,
)
from teams._registry import DepartmentRegistry
from teams._team import DepartmentTeam
from teams._types import (
    AgentSpec,
    BridgeDeps,
    Constraints,
    DepartmentConfig,
)
from tests.test_teams.conftest import (
    make_chief_delegating_model,
    make_chief_direct_answer_model,
    make_deps,
    make_specialist_text_model,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _two_specialist_config() -> DepartmentConfig:
    return DepartmentConfig(
        name="test-dept",
        zone=4,
        description="",
        manager=AgentSpec(
            name="chief", model="anthropic:claude-opus-4-6", role="chief"
        ),
        employees=(
            AgentSpec(
                name="specialist-a",
                model="anthropic:claude-sonnet-4-6",
                role="a",
            ),
            AgentSpec(
                name="specialist-b",
                model="anthropic:claude-sonnet-4-6",
                role="b",
            ),
        ),
        constraints=Constraints(cost_limit_usd=1.0, timeout_seconds=60),
    )


def _one_specialist_config() -> DepartmentConfig:
    return DepartmentConfig(
        name="test-dept",
        zone=4,
        description="",
        manager=AgentSpec(
            name="chief", model="anthropic:claude-opus-4-6", role="chief"
        ),
        employees=(
            AgentSpec(
                name="specialist-a",
                model="anthropic:claude-sonnet-4-6",
                role="a",
            ),
        ),
        constraints=Constraints(cost_limit_usd=1.0, timeout_seconds=60),
    )


# ---------------------------------------------------------------------------
# BridgeDeps.sessions_dir field
# ---------------------------------------------------------------------------


def test_bridge_deps_default_sessions_dir_is_none() -> None:
    """BridgeDeps must default sessions_dir to None for backwards compat."""
    deps = make_deps(department="test")
    assert deps.sessions_dir is None


def test_bridge_deps_accepts_sessions_dir(tmp_path: Path) -> None:
    """sessions_dir can be explicitly populated (used by registry)."""
    deps = BridgeDeps(
        session_id="s1",
        department="d1",
        operator_id="op",
        memory_store=MagicMock(),
        event_bus=MagicMock(),
        trust_manager=MagicMock(),
        cost_tracker=MagicMock(),
        knowledge_search=MagicMock(),
        sessions_dir=tmp_path,
    )
    assert deps.sessions_dir == tmp_path


def test_bridge_deps_from_app_populates_sessions_dir(tmp_path: Path) -> None:
    """BridgeDeps.from_app should derive sessions_dir from app.config.data_dir."""
    app = MagicMock()
    app.config.operator.chat_id = ""
    app.config.data_dir = str(tmp_path)
    app.memory = MagicMock()
    app.knowledge_search = MagicMock()
    app.cost_tracker = MagicMock()
    app.event_bus = MagicMock()
    app.trust_manager = MagicMock()

    deps = BridgeDeps.from_app(
        app,
        session_id="sid-1",
        department="dep-1",
    )
    assert deps.sessions_dir == tmp_path / "z4-sessions"


# ---------------------------------------------------------------------------
# DepartmentTeam.run() writes JSONL when sessions_dir is set
# ---------------------------------------------------------------------------


@pytest.mark.skip(
    reason=(
        "strict-floor activated 2026-05-12 per #1645 + classification doc "
        "(docs/architecture/2026-05-12-1645-delegation-floor-classification.md, "
        "Class A). Test name literally says 'zero-specialist' as a valid "
        "outcome — the strict-floor convention retires that contract."
    )
)
@pytest.mark.asyncio
async def test_run_writes_directive_and_synthesis_with_zero_specialists(
    tmp_path: Path,
) -> None:
    """A direct-answer run (no delegations) must produce directive + synthesis."""
    config = _one_specialist_config()
    log_path = tmp_path / "test-session" / "test-dept" / "conversation.jsonl"
    logger = ConversationLogger(log_path)
    team = DepartmentTeam(
        config, lazy_build=False, conversation_logger=logger
    )
    deps = make_deps(session_id="test-session", department="test-dept")

    mgr_model = make_chief_direct_answer_model("direct synthesis")
    with team.manager.override(model=mgr_model):
        result = await team.run("the task", deps=deps)

    assert result.success
    messages = ConversationReader(log_path).read_all()
    # At minimum: 1 directive (operator → chief) + 1 synthesis (chief → operator)
    types = [(m.message_type, m.from_agent, m.to_agent) for m in messages]
    assert (MessageType.DELEGATION, "operator", "chief") in types  # directive
    assert (MessageType.RESULT, "chief", "operator") in types  # synthesis


@pytest.mark.asyncio
async def test_run_writes_delegation_and_response_per_specialist(
    tmp_path: Path,
) -> None:
    """Two delegations must produce 2 DELEGATION + 2 RESULT pairs in order.

    Final order should be:
        DELEGATION (operator → chief)        ← directive
        DELEGATION (chief → specialist-a)    ← delegate
        RESULT     (specialist-a → chief)    ← response
        DELEGATION (chief → specialist-b)
        RESULT     (specialist-b → chief)
        RESULT     (chief → operator)        ← synthesis
    """
    config = _two_specialist_config()
    log_path = tmp_path / "sess-1" / "test-dept" / "conversation.jsonl"
    logger = ConversationLogger(log_path)
    team = DepartmentTeam(
        config, lazy_build=False, conversation_logger=logger
    )
    deps = make_deps(session_id="sess-1", department="test-dept")

    emp_a = make_specialist_text_model("alpha output")
    emp_b = make_specialist_text_model("beta output")
    mgr_model = make_chief_delegating_model(
        [("specialist-a", "two-spec task"), ("specialist-b", "two-spec task")],
        final_answer="synthesis-final",
    )

    with team.employees["specialist-a"].override(model=emp_a):
        with team.employees["specialist-b"].override(model=emp_b):
            with team.manager.override(model=mgr_model):
                result = await team.run("two-spec task", deps=deps)

    assert result.success
    messages = ConversationReader(log_path).read_all()
    # Directive + (delegation + result) per specialist + synthesis = 6
    assert len(messages) == 6, f"expected 6 messages, got {len(messages)}"

    # First is directive (operator → chief)
    assert messages[0].message_type == MessageType.DELEGATION
    assert messages[0].from_agent == "operator"
    assert messages[0].to_agent == "chief"
    assert messages[0].content == "two-spec task"

    # Last is synthesis (chief → operator)
    assert messages[-1].message_type == MessageType.RESULT
    assert messages[-1].from_agent == "chief"
    assert messages[-1].to_agent == "operator"
    assert "synthesis-final" in messages[-1].content

    # Middle four are 2 DELEGATION + 2 RESULT (one pair per specialist)
    middle = messages[1:-1]
    delegations = [m for m in middle if m.message_type == MessageType.DELEGATION]
    results = [m for m in middle if m.message_type == MessageType.RESULT]
    assert len(delegations) == 2
    assert len(results) == 2
    assert {m.to_agent for m in delegations} == {"specialist-a", "specialist-b"}
    assert {m.from_agent for m in results} == {"specialist-a", "specialist-b"}


@pytest.mark.asyncio
async def test_run_path_matches_reader_expectation(tmp_path: Path) -> None:
    """JSONL must land at sessions_dir/sid/dept/conversation.jsonl."""
    config = _one_specialist_config()
    sessions_dir = tmp_path / "z4-sessions"
    log_path = sessions_dir / "abc-session" / "test-dept" / "conversation.jsonl"
    logger = ConversationLogger(log_path)
    team = DepartmentTeam(
        config, lazy_build=False, conversation_logger=logger
    )
    deps = make_deps(session_id="abc-session", department="test-dept")

    mgr_model = make_chief_direct_answer_model("ok")
    with team.manager.override(model=mgr_model):
        await team.run("t", deps=deps)

    # Reader endpoint computes path identically
    assert log_path.exists()
    assert log_path.read_text(encoding="utf-8").strip(), "log file should not be empty"
    # Each line must be valid JSON
    for line in log_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            json.loads(line)  # raises if malformed


# ---------------------------------------------------------------------------
# Missing logger / sessions_dir → no writes, no error
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_with_no_logger_does_not_write_or_error() -> None:
    """When conversation_logger is None, run() works exactly as before."""
    config = _one_specialist_config()
    team = DepartmentTeam(config, lazy_build=False, conversation_logger=None)
    deps = make_deps(session_id="s", department="test-dept")

    mgr_model = make_chief_direct_answer_model("ok")
    with team.manager.override(model=mgr_model):
        result = await team.run("t", deps=deps)

    assert result.success is True


# ---------------------------------------------------------------------------
# Logger exception must not break the run
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_swallows_logger_exceptions(tmp_path: Path) -> None:
    """If logger.log raises, the run still completes successfully."""
    config = _one_specialist_config()
    log_path = tmp_path / "sess" / "test-dept" / "conversation.jsonl"
    logger = ConversationLogger(log_path)

    # Replace .log with a method that always raises
    def _boom(_msg: object) -> None:  # pragma: no cover - signature only
        raise RuntimeError("logger exploded")

    logger.log = _boom  # type: ignore[method-assign]

    team = DepartmentTeam(
        config, lazy_build=False, conversation_logger=logger
    )
    deps = make_deps(session_id="sess", department="test-dept")

    mgr_model = make_chief_direct_answer_model("still ok")
    with team.manager.override(model=mgr_model):
        result = await team.run("t", deps=deps)

    # Run must still report success even though every append crashed
    assert result.success is True
    assert "still ok" in result.manager_output


# ---------------------------------------------------------------------------
# Registry wires the logger when sessions_dir is on deps
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_registry_route_constructs_logger_when_sessions_dir_set(
    tmp_path: Path,
) -> None:
    """DepartmentRegistry.route should attach a ConversationLogger using deps.sessions_dir."""
    config = _one_specialist_config()
    registry = DepartmentRegistry(configs={config.name: config})

    sessions_dir = tmp_path / "z4-sessions"
    deps = BridgeDeps(
        session_id="sess-route",
        department=config.name,
        operator_id="op",
        memory_store=MagicMock(),
        event_bus=MagicMock(),
        trust_manager=MagicMock(),
        cost_tracker=MagicMock(),
        knowledge_search=MagicMock(),
        sessions_dir=sessions_dir,
    )

    # Build the team eagerly so we can override the manager model
    team = registry.get_team(config.name)
    # Force-build (lazy) by touching .manager
    _ = team.manager

    mgr_model = make_chief_direct_answer_model("route-ok")
    with team.manager.override(model=mgr_model):
        result = await registry.route(config.name, "task-via-registry", deps=deps)

    assert result.success is True
    expected_path = (
        sessions_dir / "sess-route" / config.name / "conversation.jsonl"
    )
    assert expected_path.exists(), f"logger should have written to {expected_path}"
    messages = ConversationReader(expected_path).read_all()
    # At least directive + synthesis
    assert len(messages) >= 2


@pytest.mark.asyncio
async def test_registry_route_no_sessions_dir_skips_logging(tmp_path: Path) -> None:
    """When deps.sessions_dir is None, registry must NOT create any log file."""
    config = _one_specialist_config()
    registry = DepartmentRegistry(configs={config.name: config})

    deps = make_deps(session_id="sess-no-log", department=config.name)
    assert deps.sessions_dir is None

    team = registry.get_team(config.name)
    _ = team.manager
    mgr_model = make_chief_direct_answer_model("no-log")
    with team.manager.override(model=mgr_model):
        result = await registry.route(config.name, "task", deps=deps)

    assert result.success is True
    # No files should have been created under tmp_path because no sessions_dir
    # was supplied. Sanity-check tmp_path is empty.
    assert not any(tmp_path.iterdir()), list(tmp_path.iterdir())
