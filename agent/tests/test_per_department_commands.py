"""Tests for #1071 Part 1 — per-department slash commands.

When ``set_departments(registry)`` is called the handler dynamically
registers ``_cmd_<dept>`` for each department name. The command takes a
free-form task and dispatches via ``_cmd_route``; with ``--directive``
anywhere in the args it dispatches via ``_cmd_direct`` (issuing a
Phase 5 Directive).

Existing class-level handlers (notably ``_cmd_board``) are not
clobbered.
"""
from __future__ import annotations

import unittest.mock as mock

import pytest

from bridge.claude_runner import ClaudeResult
from bridge.commands import BRIDGE_COMMANDS, CommandHandler
from bridge.dispatcher import DispatchResult
from bridge.work_order import Environment


def _fake_app() -> mock.MagicMock:
    app = mock.MagicMock()
    app.config.operator.chat_id = "operator-chat"
    app.config.data_dir = None
    return app


def _make_handler(department_names: list[str]) -> CommandHandler:
    h = CommandHandler.__new__(CommandHandler)
    h._departments = None
    h._circuit_registry = None
    h._memory = None
    h._autonomy = None
    h._cost_tracker = None
    h._app = _fake_app()
    registry = mock.MagicMock()
    registry.department_names.return_value = department_names
    h.set_departments(registry)
    return h


class TestDynamicRegistration:
    def test_registers_handler_for_each_department(self) -> None:
        h = _make_handler(["strategy", "design", "qa"])
        for dept in ("strategy", "design", "qa"):
            assert hasattr(h, f"_cmd_{dept}"), (
                f"missing _cmd_{dept} after set_departments"
            )
            assert dept in BRIDGE_COMMANDS

    def test_does_not_clobber_existing_class_handler(self) -> None:
        """`board` has a hand-written _cmd_board; dynamic registration
        must not replace it on the class or shadow it on the instance."""
        original = CommandHandler._cmd_board
        h = _make_handler(["board", "qa"])
        # Class method untouched
        assert CommandHandler._cmd_board is original
        # No instance-level shadow was set
        assert "_cmd_board" not in h.__dict__
        # But `board` is still in BRIDGE_COMMANDS
        assert "board" in BRIDGE_COMMANDS

    def test_no_registry_is_a_noop(self) -> None:
        h = CommandHandler.__new__(CommandHandler)
        h._departments = None
        # Direct call must not raise
        h._register_department_commands()
        # Nothing got attached as an instance attr
        assert not any(
            k.startswith("_cmd_") for k in h.__dict__
        )


class TestDispatchSemantics:
    @pytest.mark.asyncio
    async def test_empty_args_returns_usage(self) -> None:
        h = _make_handler(["strategy"])
        out = await h._cmd_strategy("op", "")
        assert "Usage" in out
        assert "/strategy" in out
        assert "--directive" in out

    @pytest.mark.asyncio
    async def test_plain_dispatches_to_route(self) -> None:
        h = _make_handler(["strategy"])
        with mock.patch.object(
            h, "_cmd_route", new=mock.AsyncMock(return_value="ROUTE_OK")
        ) as mocked:
            out = await h._cmd_strategy("chat-1", "size the audio AI market")
        assert out == "ROUTE_OK"
        mocked.assert_awaited_once_with(
            "chat-1", "strategy size the audio AI market"
        )

    @pytest.mark.asyncio
    async def test_directive_flag_dispatches_to_direct(self) -> None:
        h = _make_handler(["strategy"])
        with mock.patch.object(
            h, "_cmd_direct", new=mock.AsyncMock(return_value="DIRECT_OK")
        ) as mocked:
            out = await h._cmd_strategy(
                "chat-2", "--directive size the audio AI market"
            )
        assert out == "DIRECT_OK"
        mocked.assert_awaited_once_with(
            "chat-2", "strategy size the audio AI market"
        )

    @pytest.mark.asyncio
    async def test_directive_flag_can_be_anywhere(self) -> None:
        h = _make_handler(["qa"])
        with mock.patch.object(
            h, "_cmd_direct", new=mock.AsyncMock(return_value="DIRECT_OK")
        ) as mocked:
            await h._cmd_qa("c", "investigate flake --directive in test_x")
        mocked.assert_awaited_once_with(
            "c", "qa investigate flake in test_x"
        )

    @pytest.mark.asyncio
    async def test_directive_flag_alone_returns_usage(self) -> None:
        h = _make_handler(["ops"])
        out = await h._cmd_ops("op", "--directive")
        assert "Usage" in out
        assert "--directive" in out


class TestEndToEndViaHandle:
    @pytest.mark.asyncio
    async def test_handle_routes_per_department_command(self) -> None:
        h = _make_handler(["design"])
        with mock.patch.object(
            h, "_cmd_route", new=mock.AsyncMock(return_value="OK")
        ):
            out = await h.handle("op", "design", "redesign hero")
        assert out == "OK"

    @pytest.mark.asyncio
    async def test_handle_unknown_command_still_friendly(self) -> None:
        h = _make_handler(["design"])
        out = await h.handle("op", "frobnicate", "")
        assert "Unknown command" in out

    @pytest.mark.asyncio
    async def test_engineering_command_dispatches_to_zone3(self) -> None:
        h = _make_handler(["design"])
        # #2437 inserted an EngineeringDispatcher branch ahead of the legacy
        # WorkOrder/_cmd_dispatch fallback this test verifies. Force the
        # dispatcher to None so _cmd_engineering takes the fallback path
        # (the path under test). Without this, _build_engineering_dispatcher
        # returns a real dispatcher in the test env and the handler returns
        # before reaching _cmd_dispatch.
        h._build_engineering_dispatcher = mock.MagicMock(return_value=None)
        with mock.patch.object(
            h, "_cmd_dispatch", new=mock.AsyncMock(return_value="DISPATCH_OK")
        ) as mocked:
            out = await h.handle("op", "engineering", "ship the smallest feature")

        assert out == "DISPATCH_OK"
        mocked.assert_awaited_once_with("op", "ship the smallest feature")

    @pytest.mark.asyncio
    async def test_engineering_command_assigns_engineering_chief_when_dispatcher_wired(
        self,
    ) -> None:
        h = _make_handler(["design"])
        captured = {}

        async def _dispatch(wo):
            captured["wo"] = wo
            return DispatchResult(
                valid=True,
                handled=True,
                reason="executed",
                result=ClaudeResult(
                    response_text="engineering done",
                    session_id="subagent-eng",
                ),
            )

        # #2437: force the EngineeringDispatcher branch off so the legacy
        # WorkOrder/_dispatcher.dispatch path this test verifies actually runs.
        h._build_engineering_dispatcher = mock.MagicMock(return_value=None)
        h._dispatcher = mock.MagicMock()
        h._dispatcher.dispatch = mock.AsyncMock(side_effect=_dispatch)

        out = await h.handle("op", "engineering", "fix the release gate")

        wo = captured["wo"]
        assert wo.environment is Environment.SUBAGENT
        assert wo.assignment.agent_type == "engineering"
        assert wo.assignment.agent_id == "engineering-chief"
        assert "engineering done" in out
