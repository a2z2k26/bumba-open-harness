"""Tests for BridgeDeps.from_app() factory (#508) and required fields (#509)."""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock

from teams._types import BridgeDeps


class TestBridgeDepsRequiredFields:
    """Issue #509 — BridgeDeps fields must be required (no = None defaults)."""

    def test_missing_memory_store_raises(self):
        """Constructing without memory_store must raise TypeError."""
        with pytest.raises(TypeError):
            BridgeDeps(
                session_id="s1",
                department="qa",
                operator_id="op",
                # memory_store omitted
                event_bus=MagicMock(),
                trust_manager=MagicMock(),
                cost_tracker=MagicMock(),
                knowledge_search=AsyncMock(return_value=[]),
            )

    def test_missing_event_bus_raises(self):
        """Constructing without event_bus must raise TypeError."""
        with pytest.raises(TypeError):
            BridgeDeps(
                session_id="s1",
                department="qa",
                operator_id="op",
                memory_store=MagicMock(),
                # event_bus omitted
                trust_manager=MagicMock(),
                cost_tracker=MagicMock(),
                knowledge_search=AsyncMock(return_value=[]),
            )

    def test_all_fields_provided_succeeds(self):
        """Constructing with all required fields must succeed."""
        deps = BridgeDeps(
            session_id="s1",
            department="qa",
            operator_id="op",
            memory_store=MagicMock(),
            event_bus=MagicMock(),
            trust_manager=MagicMock(),
            cost_tracker=MagicMock(),
            knowledge_search=AsyncMock(return_value=[]),
        )
        assert deps.session_id == "s1"
        assert deps.department == "qa"
        assert deps.operator_id == "op"

    def test_cost_limit_default(self):
        """cost_limit_usd retains its 2.0 default."""
        deps = BridgeDeps(
            session_id="s1",
            department="qa",
            operator_id="",
            memory_store=MagicMock(),
            event_bus=MagicMock(),
            trust_manager=MagicMock(),
            cost_tracker=MagicMock(),
            knowledge_search=AsyncMock(return_value=[]),
        )
        assert deps.cost_limit_usd == 2.0

    def test_cost_limit_override(self):
        """cost_limit_usd can be overridden."""
        deps = BridgeDeps(
            session_id="s1",
            department="qa",
            operator_id="",
            memory_store=MagicMock(),
            event_bus=MagicMock(),
            trust_manager=MagicMock(),
            cost_tracker=MagicMock(),
            knowledge_search=AsyncMock(return_value=[]),
            cost_limit_usd=5.0,
        )
        assert deps.cost_limit_usd == 5.0


class TestBridgeDepsFromApp:
    """Issue #508 — BridgeDeps.from_app() factory classmethod."""

    def _make_app(self, *, operator_chat_id="op-123", with_memory=True, with_autonomy=True):
        """Build a duck-typed fake BridgeApp with the properties from_app() reads."""
        app = MagicMock()

        # operator_id extraction
        app.config = MagicMock()
        app.config.operator = MagicMock()
        app.config.operator.chat_id = operator_chat_id

        # memory and knowledge_search
        if with_memory:
            app.memory = MagicMock()
            app.knowledge_search = AsyncMock(return_value=[])
        else:
            app.memory = None
            app.knowledge_search = None

        # cost_tracker, event_bus, trust_manager
        app.cost_tracker = MagicMock()
        if with_autonomy:
            app.event_bus = MagicMock()
            app.trust_manager = MagicMock()
        else:
            app.event_bus = None
            app.trust_manager = None

        return app

    def test_from_app_creates_deps(self):
        """from_app() returns a BridgeDeps with correct session_id and department."""
        app = self._make_app()
        deps = BridgeDeps.from_app(app, session_id="abc123", department="qa")
        assert deps.session_id == "abc123"
        assert deps.department == "qa"

    def test_from_app_operator_id(self):
        """from_app() extracts operator_id from app.config.operator.chat_id."""
        app = self._make_app(operator_chat_id="discord-777")
        deps = BridgeDeps.from_app(app, session_id="s1", department="qa")
        assert deps.operator_id == "discord-777"

    def test_from_app_cost_limit_default(self):
        """from_app() with no cost_limit_usd uses default 2.0."""
        app = self._make_app()
        deps = BridgeDeps.from_app(app, session_id="s1", department="qa")
        assert deps.cost_limit_usd == 2.0

    def test_from_app_cost_limit_override(self):
        """from_app() respects explicit cost_limit_usd."""
        app = self._make_app()
        deps = BridgeDeps.from_app(app, session_id="s1", department="qa", cost_limit_usd=3.5)
        assert deps.cost_limit_usd == 3.5

    def test_from_app_wires_memory(self):
        """from_app() sets memory_store from app.memory."""
        app = self._make_app(with_memory=True)
        deps = BridgeDeps.from_app(app, session_id="s1", department="qa")
        assert deps.memory_store is app.memory

    def test_from_app_wires_knowledge_search(self):
        """from_app() sets knowledge_search from app.knowledge_search."""
        app = self._make_app(with_memory=True)
        deps = BridgeDeps.from_app(app, session_id="s1", department="qa")
        assert deps.knowledge_search is app.knowledge_search

    def test_from_app_wires_cost_tracker(self):
        """from_app() sets cost_tracker from app.cost_tracker."""
        app = self._make_app()
        deps = BridgeDeps.from_app(app, session_id="s1", department="qa")
        assert deps.cost_tracker is app.cost_tracker

    def test_from_app_wires_event_bus(self):
        """from_app() sets event_bus from app.event_bus."""
        app = self._make_app(with_autonomy=True)
        deps = BridgeDeps.from_app(app, session_id="s1", department="qa")
        assert deps.event_bus is app.event_bus

    def test_from_app_wires_trust_manager(self):
        """from_app() sets trust_manager from app.trust_manager."""
        app = self._make_app(with_autonomy=True)
        deps = BridgeDeps.from_app(app, session_id="s1", department="qa")
        assert deps.trust_manager is app.trust_manager

    def test_from_app_tolerates_missing_operator_config(self):
        """from_app() falls back to empty string when app has no config.operator.chat_id."""
        app = MagicMock()
        del app.config   # AttributeError on access
        del app._config  # AttributeError on access — ensures both branches fall back
        app.memory = MagicMock()
        app.knowledge_search = AsyncMock(return_value=[])
        app.cost_tracker = MagicMock()
        app.event_bus = MagicMock()
        app.trust_manager = MagicMock()
        deps = BridgeDeps.from_app(app, session_id="s1", department="qa")
        assert deps.operator_id == ""

    def test_from_app_frozen(self):
        """BridgeDeps returned by from_app() is frozen (immutable)."""
        app = self._make_app()
        deps = BridgeDeps.from_app(app, session_id="s1", department="qa")
        with pytest.raises((AttributeError, Exception)):
            deps.session_id = "mutated"  # type: ignore[misc]

    def test_bridge_deps_workflow_default_empty(self):
        """WS3.2 (#2570) — from_app() without a workflow leaves deps.workflow
        empty, so non-workflow construction sites carry no workflow tag."""
        app = self._make_app()
        deps = BridgeDeps.from_app(app, session_id="s1", department="qa")
        assert deps.workflow == ""

    def test_from_app_threads_workflow(self):
        """WS3.2 (#2570) — from_app() sets deps.workflow when given one."""
        app = self._make_app()
        deps = BridgeDeps.from_app(
            app, session_id="s1", department="qa", workflow="wf-x"
        )
        assert deps.workflow == "wf-x"
