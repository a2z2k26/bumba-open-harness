"""Tests for the Sprint 22 PR B operator notification hook.

Covers:
- ``should_notify`` decision matrix: kind × urgency × to_agent
- ``maybe_notify_operator`` calls Discord on notifiable surfaces
- ``maybe_notify_operator`` is a no-op for FYI / RESULT / FLAG / specialist→chief
- IMMEDIATE messages contain ``@operator`` mention; ATTENTION does not
- Discord client raise → no exception escapes; logged warning
- Missing app / Discord client / operator chat_id → silent no-op
- End-to-end: chief surface() tool call triggers a Discord DM via the hook
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio

from bridge.database import Database
from bridge.surface_notify import (
    _format_message,
    maybe_notify_operator,
    should_notify,
)
from bridge.surface_store import new_surface_id
from teams._factory import build_employee_agents, build_manager_agent
from teams._types import (
    AgentSpec,
    BridgeDeps,
    Constraints,
    DepartmentConfig,
    Surface,
    SurfaceKind,
    Urgency,
)
from tests.test_teams.conftest import make_deps


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def db(tmp_path: Path) -> Database:
    db_path = tmp_path / "test-notify.db"
    database = Database(db_path)
    await database.connect()
    await database.migrate()
    yield database
    await database.close()


def _surface(
    *,
    kind: SurfaceKind,
    urgency: Urgency,
    to_agent: str = "main",
    from_agent: str = "strategy-product-chief",
    correlation_id: str | None = "dir-test12345678",
    payload: dict | None = None,
) -> Surface:
    return Surface(
        surface_id=new_surface_id(),
        from_agent=from_agent,
        to_agent=to_agent,
        kind=kind,
        urgency=urgency,
        correlation_id=correlation_id,
        payload=payload or {"summary": "operator needed"},
        created_at_utc=datetime.now(timezone.utc),
    )


def _fake_app(*, send_raises: bool = False) -> MagicMock:
    """Build a duck-typed BridgeApp with a fake Discord client."""
    app = MagicMock()
    if send_raises:
        app._discord.send_message = AsyncMock(side_effect=RuntimeError("boom"))
    else:
        app._discord.send_message = AsyncMock(return_value=None)
    app._config.operator_discord_id = "operator-chat-1"
    return app


# ---------------------------------------------------------------------------
# should_notify — pure decision matrix
# ---------------------------------------------------------------------------


class TestShouldNotify:
    def test_specialist_to_chief_never_notifies(self) -> None:
        # to_agent != "main" → always silent regardless of kind+urgency
        for kind in SurfaceKind:
            for urgency in Urgency:
                s = _surface(
                    kind=kind, urgency=urgency, to_agent="some-chief"
                )
                assert should_notify(s) is False, (
                    f"{kind.value}/{urgency.value} to chief unexpectedly notifies"
                )

    def test_fyi_never_notifies(self) -> None:
        for kind in SurfaceKind:
            s = _surface(kind=kind, urgency=Urgency.FYI)
            assert should_notify(s) is False, (
                f"{kind.value}/fyi unexpectedly notifies"
            )

    def test_result_never_notifies(self) -> None:
        for urgency in Urgency:
            s = _surface(kind=SurfaceKind.RESULT, urgency=urgency)
            assert should_notify(s) is False

    def test_flag_never_notifies(self) -> None:
        for urgency in Urgency:
            s = _surface(kind=SurfaceKind.FLAG, urgency=urgency)
            assert should_notify(s) is False

    @pytest.mark.parametrize("kind", [
        SurfaceKind.BLOCKER,
        SurfaceKind.POLICY_Q,
        SurfaceKind.CROSS_TEAM,
        SurfaceKind.SCOPE_REQUEST,
    ])
    def test_attention_notifiable_kinds_to_main(
        self, kind: SurfaceKind
    ) -> None:
        s = _surface(kind=kind, urgency=Urgency.ATTENTION)
        assert should_notify(s) is True

    @pytest.mark.parametrize("kind", [
        SurfaceKind.BLOCKER,
        SurfaceKind.POLICY_Q,
        SurfaceKind.CROSS_TEAM,
        SurfaceKind.SCOPE_REQUEST,
    ])
    def test_immediate_notifiable_kinds_to_main(
        self, kind: SurfaceKind
    ) -> None:
        s = _surface(kind=kind, urgency=Urgency.IMMEDIATE)
        assert should_notify(s) is True


# ---------------------------------------------------------------------------
# Message formatting
# ---------------------------------------------------------------------------


class TestFormatMessage:
    def test_immediate_includes_at_operator_mention(self) -> None:
        s = _surface(kind=SurfaceKind.BLOCKER, urgency=Urgency.IMMEDIATE)
        msg = _format_message(s)
        assert "@operator" in msg
        assert "BLOCKER" in msg
        assert "immediate" in msg

    def test_attention_omits_at_operator_mention(self) -> None:
        s = _surface(kind=SurfaceKind.POLICY_Q, urgency=Urgency.ATTENTION)
        msg = _format_message(s)
        assert "@operator" not in msg
        assert "POLICY_Q" in msg

    def test_summary_present_with_default_when_missing(self) -> None:
        # _surface()'s default payload includes a summary; explicitly override
        # to empty to exercise the "(no summary)" fallback
        s = Surface(
            surface_id=new_surface_id(),
            from_agent="strategy-product-chief",
            to_agent="main",
            kind=SurfaceKind.BLOCKER,
            urgency=Urgency.ATTENTION,
            correlation_id="dir-test",
            payload={},
            created_at_utc=datetime.now(timezone.utc),
        )
        msg = _format_message(s)
        assert "no summary" in msg

    def test_includes_ack_hint(self) -> None:
        s = _surface(kind=SurfaceKind.BLOCKER, urgency=Urgency.ATTENTION)
        msg = _format_message(s)
        assert f"/ack {s.surface_id}" in msg

    def test_correlation_id_in_message(self) -> None:
        s = _surface(
            kind=SurfaceKind.BLOCKER,
            urgency=Urgency.ATTENTION,
            correlation_id="dir-abc123def456",
        )
        msg = _format_message(s)
        assert "dir-abc123def456" in msg


# ---------------------------------------------------------------------------
# maybe_notify_operator — dispatch path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestMaybeNotifyOperator:
    async def test_notifies_blocker_attention(self) -> None:
        app = _fake_app()
        s = _surface(kind=SurfaceKind.BLOCKER, urgency=Urgency.ATTENTION)
        sent = await maybe_notify_operator(s, app)
        assert sent is True
        app._discord.send_message.assert_awaited_once()
        chat_id, text = app._discord.send_message.call_args.args
        assert chat_id == "operator-chat-1"
        assert "BLOCKER" in text
        assert "@operator" not in text  # ATTENTION, not IMMEDIATE

    async def test_notifies_policy_q_immediate_with_mention(self) -> None:
        app = _fake_app()
        s = _surface(kind=SurfaceKind.POLICY_Q, urgency=Urgency.IMMEDIATE)
        sent = await maybe_notify_operator(s, app)
        assert sent is True
        text = app._discord.send_message.call_args.args[1]
        assert "@operator" in text

    async def test_silent_for_fyi(self) -> None:
        app = _fake_app()
        s = _surface(kind=SurfaceKind.BLOCKER, urgency=Urgency.FYI)
        sent = await maybe_notify_operator(s, app)
        assert sent is False
        app._discord.send_message.assert_not_awaited()

    async def test_silent_for_result(self) -> None:
        app = _fake_app()
        s = _surface(kind=SurfaceKind.RESULT, urgency=Urgency.IMMEDIATE)
        sent = await maybe_notify_operator(s, app)
        assert sent is False
        app._discord.send_message.assert_not_awaited()

    async def test_silent_for_specialist_to_chief(self) -> None:
        app = _fake_app()
        s = _surface(
            kind=SurfaceKind.BLOCKER,
            urgency=Urgency.IMMEDIATE,
            to_agent="strategy-product-chief",
        )
        sent = await maybe_notify_operator(s, app)
        assert sent is False
        app._discord.send_message.assert_not_awaited()

    async def test_no_app_returns_false_no_raise(self) -> None:
        s = _surface(kind=SurfaceKind.BLOCKER, urgency=Urgency.ATTENTION)
        sent = await maybe_notify_operator(s, None)
        assert sent is False

    async def test_no_discord_client_silent(self) -> None:
        app = MagicMock()
        app._discord = None
        app._config.operator_discord_id = "anything"
        s = _surface(kind=SurfaceKind.BLOCKER, urgency=Urgency.ATTENTION)
        sent = await maybe_notify_operator(s, app)
        assert sent is False

    async def test_no_operator_chat_id_silent(self) -> None:
        app = MagicMock()
        app._discord.send_message = AsyncMock(return_value=None)
        app._config.operator_discord_id = ""
        # Also defang the operator.chat_id fallback
        app._config.operator = MagicMock(spec=[])
        s = _surface(kind=SurfaceKind.BLOCKER, urgency=Urgency.ATTENTION)
        sent = await maybe_notify_operator(s, app)
        assert sent is False
        app._discord.send_message.assert_not_awaited()

    async def test_discord_raise_returns_false_no_propagate(self) -> None:
        app = _fake_app(send_raises=True)
        s = _surface(kind=SurfaceKind.BLOCKER, urgency=Urgency.IMMEDIATE)
        sent = await maybe_notify_operator(s, app)
        assert sent is False  # logged + swallowed
        app._discord.send_message.assert_awaited_once()


# ---------------------------------------------------------------------------
# End-to-end: chief surface() tool fires the notification
# ---------------------------------------------------------------------------


def _config() -> DepartmentConfig:
    return DepartmentConfig(
        name="dept-n",
        zone=4,
        description="",
        manager=AgentSpec(
            name="n-chief", model="anthropic:claude-opus-4-6", role="chief"
        ),
        employees=(
            AgentSpec(
                name="alpha", model="anthropic:claude-sonnet-4-6", role="alpha"
            ),
        ),
        constraints=Constraints(cost_limit_usd=1.0, timeout_seconds=60),
    )


def _deps_with_app(db: Database, app, *, directive_id: str = "dir-fixture001") -> BridgeDeps:
    base = make_deps(department="dept-n")
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
        app=app,
    )


@pytest.mark.asyncio
class TestChiefSurfaceFiresNotification:
    async def test_chief_blocker_immediate_fires_dm(self, db: Database) -> None:
        config = _config()
        employees = build_employee_agents(config)
        manager = build_manager_agent(config, employees)
        surface_tool = manager._function_toolset.tools["surface"]

        app = _fake_app()

        class _Ctx:
            deps = _deps_with_app(db, app)

        await surface_tool.function(
            _Ctx(),
            kind="blocker",
            urgency="immediate",
            payload={"summary": "I cannot proceed"},
        )

        # Discord DM dispatched
        app._discord.send_message.assert_awaited_once()
        text = app._discord.send_message.call_args.args[1]
        assert "BLOCKER" in text
        assert "@operator" in text
        assert "I cannot proceed" in text

    async def test_chief_result_fyi_does_not_fire(self, db: Database) -> None:
        config = _config()
        employees = build_employee_agents(config)
        manager = build_manager_agent(config, employees)
        surface_tool = manager._function_toolset.tools["surface"]

        app = _fake_app()

        class _Ctx:
            deps = _deps_with_app(db, app)

        await surface_tool.function(
            _Ctx(), kind="result", urgency="fyi",
            payload={"answer": "synthesis"},
        )
        app._discord.send_message.assert_not_awaited()

    async def test_specialist_blocker_does_not_fire(
        self, db: Database
    ) -> None:
        """Specialist-to-chief surfaces never page the operator."""
        config = _config()
        employees = build_employee_agents(config)
        surface_tool = employees["alpha"]._function_toolset.tools["surface"]

        app = _fake_app()

        # Build deps with task_id already populated via dataclass replace
        from dataclasses import replace
        deps_with_task = replace(_deps_with_app(db, app), task_id="task-fixture001")

        class _Ctx:
            deps = deps_with_task

        # Specialist's surface() goes to chief, not main → never fires
        await surface_tool.function(
            _Ctx(),
            kind="blocker",
            urgency="immediate",
            payload={"summary": "specialist hit a wall"},
        )
        app._discord.send_message.assert_not_awaited()
