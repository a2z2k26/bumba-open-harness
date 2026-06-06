"""Tests for /departments and /route operator commands (Z4.3.7)."""

from __future__ import annotations

import unittest.mock as mock

import pytest

from bridge.commands import CommandHandler


@pytest.fixture
def mock_registry():
    """Mock DepartmentRegistry with qa, strategy departments."""
    registry = mock.MagicMock()
    registry.department_names.return_value = ["qa", "strategy"]

    def get_config(name):
        cfg = mock.MagicMock()
        cfg.zone = 4
        cfg.employees = [mock.MagicMock() for _ in range(4)]
        cfg.vapi = mock.MagicMock()
        cfg.vapi.enabled = False
        return cfg

    registry.get_config.side_effect = get_config
    return registry


def _bare_handler():
    """Create a CommandHandler bypassing __init__ with all required attributes set.

    Sprint 04.10/04.11: ``_app`` is set to a duck-typed fake BridgeApp so the
    BridgeDeps.from_app(self._app, ...) call inside _cmd_route / _cmd_handoff
    does not AttributeError when the registry path runs.
    """
    h = CommandHandler.__new__(CommandHandler)
    h._departments = None
    h._circuit_registry = None
    h._memory = None
    h._autonomy = None
    h._cost_tracker = None
    h._app = _fake_app()
    return h


def _fake_app(*, data_dir: str | None = None):
    """Return a minimal duck-typed BridgeApp stand-in for BridgeDeps.from_app."""
    app = mock.MagicMock()
    app.config.operator.chat_id = "operator-chat"
    app.config.data_dir = data_dir
    app.memory = mock.MagicMock()
    app.knowledge_search = mock.MagicMock()
    app.cost_tracker = mock.MagicMock()
    app.event_bus = mock.MagicMock()
    app.trust_manager = mock.MagicMock()
    return app


@pytest.fixture
def handler(mock_registry):
    """CommandHandler with mock registry wired via set_departments."""
    h = _bare_handler()
    h._departments = mock_registry
    return h


@pytest.fixture
def handler_no_registry():
    """CommandHandler with no registry (teams not wired)."""
    return _bare_handler()


class TestDepartmentsCommand:
    @pytest.mark.asyncio
    async def test_lists_departments(self, handler, mock_registry):
        result = await handler._cmd_departments("chat1", "")
        assert "qa" in result
        assert "strategy" in result
        assert "Departments" in result

    @pytest.mark.asyncio
    async def test_shows_zone_and_employee_count(self, handler):
        result = await handler._cmd_departments("chat1", "")
        assert "zone 4" in result
        assert "4 employees" in result

    @pytest.mark.asyncio
    async def test_shows_vapi_status(self, handler):
        result = await handler._cmd_departments("chat1", "")
        assert "voice disabled" in result

    @pytest.mark.asyncio
    async def test_vapi_enabled_shows_voice_enabled(self, mock_registry):
        def get_config_voice_on(name):
            cfg = mock.MagicMock()
            cfg.zone = 4
            cfg.employees = [mock.MagicMock() for _ in range(2)]
            cfg.vapi = mock.MagicMock()
            cfg.vapi.enabled = True
            return cfg

        mock_registry.get_config.side_effect = get_config_voice_on
        h = _bare_handler()
        h._departments = mock_registry
        result = await h._cmd_departments("chat1", "")
        assert "voice enabled" in result

    @pytest.mark.asyncio
    async def test_not_wired(self, handler_no_registry):
        result = await handler_no_registry._cmd_departments("chat1", "")
        assert "not wired" in result.lower()

    @pytest.mark.asyncio
    async def test_empty_registry(self, mock_registry):
        mock_registry.department_names.return_value = []
        h = _bare_handler()
        h._departments = mock_registry
        result = await h._cmd_departments("chat1", "")
        assert "No departments registered" in result

    @pytest.mark.asyncio
    async def test_department_count_in_header(self, handler):
        result = await handler._cmd_departments("chat1", "")
        assert "2" in result  # qa + strategy


class TestRouteCommand:
    @pytest.mark.asyncio
    async def test_routes_to_department(self, handler, mock_registry):
        team_result = mock.MagicMock()
        team_result.success = True
        team_result.manager_output = "QA analysis complete."
        team_result.duration_seconds = 1.5

        mock_registry.route = mock.AsyncMock(return_value=team_result)

        result = await handler._cmd_route("chat1", "qa Review the auth module")
        assert "QA analysis complete" in result
        assert "qa" in result

    @pytest.mark.asyncio
    async def test_route_success_links_session_output(
        self,
        mock_registry,
        tmp_path,
    ):
        h = _bare_handler()
        h._app = _fake_app(data_dir=str(tmp_path))
        h._departments = mock_registry
        team_result = mock.MagicMock()
        team_result.success = True
        team_result.manager_output = "QA analysis complete."
        team_result.duration_seconds = 1.5
        mock_registry.route = mock.AsyncMock(return_value=team_result)

        result = await h._cmd_route("chat1", "qa Review the auth module")

        assert "Session transcript" in result
        assert str(tmp_path / "z4-sessions" / "chat1" / "qa" / "conversation.jsonl") in result
        assert "/api/z4/sessions/chat1/departments/qa/conversation" in result

    @pytest.mark.asyncio
    async def test_route_missing_task(self, handler):
        result = await handler._cmd_route("chat1", "qa")
        assert "Usage" in result

    @pytest.mark.asyncio
    async def test_route_empty_args(self, handler):
        result = await handler._cmd_route("chat1", "")
        assert "Usage" in result

    @pytest.mark.asyncio
    async def test_route_unknown_department(self, handler):
        result = await handler._cmd_route("chat1", "engineering do something")
        assert "Unknown department" in result
        assert "engineering" in result

    @pytest.mark.asyncio
    async def test_route_unknown_department_shows_available(self, handler):
        result = await handler._cmd_route("chat1", "eng do something")
        assert "qa" in result or "strategy" in result

    @pytest.mark.asyncio
    async def test_route_failure(self, handler, mock_registry):
        team_result = mock.MagicMock()
        team_result.success = False
        team_result.error = "Timeout after 600s"

        mock_registry.route = mock.AsyncMock(return_value=team_result)

        result = await handler._cmd_route("chat1", "qa some task")
        assert "FAILED" in result
        assert "Timeout" in result

    @pytest.mark.asyncio
    async def test_route_failure_links_session_output(
        self,
        mock_registry,
        tmp_path,
    ):
        h = _bare_handler()
        h._app = _fake_app(data_dir=str(tmp_path))
        h._departments = mock_registry
        team_result = mock.MagicMock()
        team_result.success = False
        team_result.error = "Timeout after 600s"
        mock_registry.route = mock.AsyncMock(return_value=team_result)

        result = await h._cmd_route("chat1", "qa some task")

        assert "FAILED" in result
        assert "Session transcript" in result

    @pytest.mark.asyncio
    async def test_route_exception_handled(self, handler, mock_registry):
        mock_registry.route = mock.AsyncMock(side_effect=RuntimeError("boom"))

        result = await handler._cmd_route("chat1", "qa some task")
        assert "Error routing" in result
        assert "boom" in result

    @pytest.mark.asyncio
    async def test_not_wired(self, handler_no_registry):
        result = await handler_no_registry._cmd_route("chat1", "qa task")
        assert "not wired" in result.lower()

    @pytest.mark.asyncio
    async def test_route_includes_duration(self, handler, mock_registry):
        team_result = mock.MagicMock()
        team_result.success = True
        team_result.manager_output = "Done."
        team_result.duration_seconds = 2.3

        mock_registry.route = mock.AsyncMock(return_value=team_result)

        result = await handler._cmd_route("chat1", "qa run tests")
        assert "2.3s" in result

    @pytest.mark.asyncio
    async def test_route_in_bridge_commands(self):
        from bridge.commands import BRIDGE_COMMANDS
        assert "route" in BRIDGE_COMMANDS

    @pytest.mark.asyncio
    async def test_departments_in_bridge_commands(self):
        from bridge.commands import BRIDGE_COMMANDS
        assert "departments" in BRIDGE_COMMANDS
