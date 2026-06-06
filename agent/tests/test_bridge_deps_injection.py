"""Tests for Z4.1 — BridgeDeps injection at /route and VAPI sites."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from bridge.memory import MemoryKVAdapter


# ---------------------------------------------------------------------------
# MemoryKVAdapter unit tests
# ---------------------------------------------------------------------------

class TestMemoryKVAdapter:
    """Adapter delegates get/set to Memory.get_knowledge / store_knowledge."""

    @pytest.fixture
    def mock_memory(self):
        m = MagicMock()
        m.get_knowledge = AsyncMock(return_value=None)
        m.store_knowledge = AsyncMock()
        return m

    def test_get_delegates_to_get_knowledge(self, mock_memory):
        adapter = MemoryKVAdapter(mock_memory)
        result = asyncio.run(adapter.get("some-key"))
        mock_memory.get_knowledge.assert_called_once_with("some-key")
        assert result is None

    def test_set_delegates_to_store_knowledge(self, mock_memory):
        adapter = MemoryKVAdapter(mock_memory)
        asyncio.run(adapter.set("k", "v"))
        mock_memory.store_knowledge.assert_called_once_with("k", "v", source="zone4-tool")

    def test_get_returns_value_from_memory(self, mock_memory):
        mock_memory.get_knowledge = AsyncMock(return_value="stored-value")
        adapter = MemoryKVAdapter(mock_memory)
        result = asyncio.run(adapter.get("k"))
        assert result == "stored-value"


# ---------------------------------------------------------------------------
# CommandHandler._cmd_route — BridgeDeps construction
# ---------------------------------------------------------------------------

class TestCommandHandlerBridgeDepsInjection:
    """BridgeDeps passed to DepartmentRegistry.route() has non-None backends.

    Sprint 04.10: _cmd_route now constructs BridgeDeps via
    BridgeDeps.from_app(self._app, ...) instead of hand-assembling fields from
    self._memory / self._autonomy / self._cost_tracker. The fixture has been
    updated to wire a fake BridgeApp shim — the contract (deps must arrive at
    DepartmentRegistry.route with non-None backends) is unchanged, but the
    *source* of those backends is now the live BridgeApp, not the handler's
    own attributes.
    """

    @pytest.fixture
    def handler(self, tmp_path):
        from bridge.commands import CommandHandler
        handler = CommandHandler.__new__(CommandHandler)

        # Sprint 04.10: BridgeDeps.from_app reads memory/event_bus/etc off
        # self._app — wire a duck-typed fake.
        fake_app = MagicMock()
        fake_app.config.operator.chat_id = "operator-chat"
        fake_app.config.data_dir = None  # sessions_dir derives to None
        fake_app.memory = MagicMock()
        fake_app.memory.search_knowledge = AsyncMock(return_value=[])
        fake_app.knowledge_search = AsyncMock(return_value=[])
        fake_app.cost_tracker = MagicMock()
        fake_app.event_bus = MagicMock()
        fake_app.trust_manager = MagicMock()
        handler._app = fake_app

        # Pre-Sprint 04.10 these attributes were the BridgeDeps source. They
        # remain on the handler for other commands that still consult them.
        handler._memory = fake_app.memory
        handler._autonomy = MagicMock()
        handler._autonomy.event_bus = fake_app.event_bus
        handler._autonomy.trust = fake_app.trust_manager
        handler._cost_tracker = fake_app.cost_tracker

        # Departments mock
        mock_dept = MagicMock()
        mock_result = MagicMock()
        mock_result.success = True
        mock_result.duration_seconds = 0.1
        mock_result.manager_output = "ok"
        mock_dept.route = AsyncMock(return_value=mock_result)
        mock_dept.department_names = MagicMock(return_value=["strategy"])
        handler._departments = mock_dept

        return handler

    def test_route_injects_all_backends(self, handler):
        captured_deps = {}

        async def capture_route(dept, task, deps):
            captured_deps["deps"] = deps
            result = MagicMock()
            result.success = True
            result.duration_seconds = 0.1
            result.manager_output = "ok"
            return result

        handler._departments.route = capture_route

        asyncio.run(
            handler._cmd_route("chat-123", "strategy search X")
        )

        deps = captured_deps["deps"]
        assert deps is not None
        assert deps.memory_store is not None
        assert deps.knowledge_search is not None
        assert deps.event_bus is not None
        assert deps.trust_manager is not None
        assert deps.cost_tracker is not None
        assert deps.session_id == "chat-123"
        assert deps.department == "strategy"

    def test_route_uses_app_fields_not_handler_autonomy(self, handler):
        """Sprint 04.10 contract change: BridgeDeps fields come from app, not
        from handler._autonomy. Setting handler._autonomy = None no longer
        nulls deps.event_bus — the from_app factory reads app.event_bus."""
        handler._autonomy = None
        captured_deps = {}

        async def capture_route(dept, task, deps):
            captured_deps["deps"] = deps
            result = MagicMock()
            result.success = True
            result.duration_seconds = 0.1
            result.manager_output = "ok"
            return result

        handler._departments.route = capture_route
        asyncio.run(
            handler._cmd_route("chat-456", "strategy search Y")
        )

        deps = captured_deps["deps"]
        # The factory now sources event_bus / trust_manager from the live
        # BridgeApp, so they remain non-None even when handler._autonomy is
        # None — this is the post-04.10 contract.
        assert deps.event_bus is not None
        assert deps.trust_manager is not None
        assert deps.memory_store is not None

    def test_route_uses_app_fields_not_handler_memory(self, handler):
        """Sprint 04.10 contract change: BridgeDeps fields come from app, not
        from handler._memory. Setting handler._memory = None no longer nulls
        deps.memory_store — the from_app factory reads app.memory."""
        handler._memory = None
        captured_deps = {}

        async def capture_route(dept, task, deps):
            captured_deps["deps"] = deps
            result = MagicMock()
            result.success = True
            result.duration_seconds = 0.1
            result.manager_output = "ok"
            return result

        handler._departments.route = capture_route
        asyncio.run(
            handler._cmd_route("chat-789", "strategy search Z")
        )

        deps = captured_deps["deps"]
        assert deps.memory_store is not None
        assert deps.knowledge_search is not None


# ---------------------------------------------------------------------------
# APIServer VAPI handler — BridgeDeps construction
# ---------------------------------------------------------------------------

class TestAPIServerVapiBridgeDepsInjection:
    """APIServer VAPI path injects non-None backends from self._bridge."""

    def _make_server(self):
        from bridge.api_server import APIServer
        server = APIServer.__new__(APIServer)

        mock_memory = MagicMock()
        mock_memory.search_knowledge = AsyncMock(return_value=[])

        mock_autonomy = MagicMock()
        mock_autonomy.event_bus = MagicMock()
        mock_autonomy.trust = MagicMock()

        mock_bridge = MagicMock()
        mock_bridge._memory = mock_memory
        mock_bridge._autonomy = mock_autonomy
        mock_bridge._cost_tracker = MagicMock()

        server._bridge = mock_bridge

        mock_cfg = MagicMock()
        mock_cfg.vapi = MagicMock()
        mock_cfg.vapi.enabled = True

        mock_departments = MagicMock()
        mock_departments.get_config = MagicMock(return_value=mock_cfg)

        mock_result = MagicMock()
        mock_result.success = True
        mock_result.duration_seconds = 0.1
        mock_result.manager_output = "ok"
        mock_departments.route = AsyncMock(return_value=mock_result)
        server._departments = mock_departments

        return server

    def test_vapi_injects_all_backends(self):
        """Verify BridgeDeps construction has non-None backends (unit, no HTTP)."""
        from bridge.memory import MemoryKVAdapter
        server = self._make_server()

        # Directly test the construction logic (not the full request cycle)
        _bridge_memory = getattr(server._bridge, "_memory", None)
        _bridge_autonomy = getattr(server._bridge, "_autonomy", None)

        from tests.test_teams.conftest import make_deps
        import uuid
        deps = make_deps(
            session_id=f"vapi-{uuid.uuid4().hex[:12]}",
            department="strategy",
            memory_store=MemoryKVAdapter(_bridge_memory) if _bridge_memory else None,
            knowledge_search=_bridge_memory.search_knowledge if _bridge_memory else None,
            event_bus=(_bridge_autonomy.event_bus if _bridge_autonomy else None),
            trust_manager=(_bridge_autonomy.trust if _bridge_autonomy else None),
            cost_tracker=getattr(server._bridge, "_cost_tracker", None),
        )

        assert deps.memory_store is not None
        assert deps.knowledge_search is not None
        assert deps.event_bus is not None
        assert deps.trust_manager is not None
        assert deps.cost_tracker is not None

    def test_vapi_no_crash_when_bridge_memory_none(self):
        server = self._make_server()
        server._bridge._memory = None

        _bridge_memory = getattr(server._bridge, "_memory", None)
        _bridge_autonomy = getattr(server._bridge, "_autonomy", None)

        from teams._types import BridgeDeps
        import uuid
        from bridge.memory import MemoryKVAdapter
        deps = BridgeDeps(
            session_id=f"vapi-{uuid.uuid4().hex[:12]}",
            operator_id="op-test",
            department="strategy",
            memory_store=MemoryKVAdapter(_bridge_memory) if _bridge_memory else None,
            knowledge_search=_bridge_memory.search_knowledge if _bridge_memory else None,
            event_bus=(_bridge_autonomy.event_bus if _bridge_autonomy else None),
            trust_manager=(_bridge_autonomy.trust if _bridge_autonomy else None),
            cost_tracker=getattr(server._bridge, "_cost_tracker", None),
        )

        assert deps.memory_store is None
        assert deps.knowledge_search is None
