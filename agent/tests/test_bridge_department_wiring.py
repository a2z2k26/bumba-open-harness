"""Tests for bridge → DepartmentRegistry wiring."""

from __future__ import annotations

from unittest.mock import MagicMock


from bridge.commands import CommandHandler
from bridge.dispatcher import Dispatcher


class TestCommandHandlerSetDepartments:
    def test_set_departments_stores_registry(self):
        handler = CommandHandler(
            db=MagicMock(),
            queue=MagicMock(),
            session_manager=MagicMock(),
            claude_runner=MagicMock(),
        )
        mock_registry = MagicMock()
        mock_registry.department_names.return_value = ["qa", "design"]

        handler.set_departments(mock_registry)
        assert handler._departments is mock_registry

    def test_departments_default_none(self):
        handler = CommandHandler(
            db=MagicMock(),
            queue=MagicMock(),
            session_manager=MagicMock(),
            claude_runner=MagicMock(),
        )
        assert handler._departments is None


class TestDispatcherDepartmentWiring:
    def test_dispatcher_receives_department_registry(self):
        """After setup, dispatcher._department_registry is the same object as departments."""
        departments = MagicMock()
        departments.department_names.return_value = ["engineering", "qa"]

        dispatcher = Dispatcher(
            claude_runner=MagicMock(),
            tmux_manager=MagicMock(),
            event_bus=MagicMock(),
            department_registry=departments,
        )

        assert dispatcher._department_registry is departments
