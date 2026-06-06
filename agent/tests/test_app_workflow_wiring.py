"""Sprint 04.06 — verify WorkflowRegistry + WorkflowEngine wiring.

Both modules (workflow_registry.py 221 LOC, workflow_engine.py 592 LOC)
were fully implemented but BridgeApp had zero references — /workflows
short-circuited with "WorkflowRegistry is not initialised." This sprint
constructs both during _initialize() and the existing Sprint 01.03
WIRING_MANIFEST entries (set_workflow_registry / set_workflow_engine,
both required=False with reason "Plan 04 owns construction") finally fire
real sources.

Tests below are intentionally focused — full /workflows command behaviour
(list / trigger / cancel) ships in Sprint 04.07. This file proves only
that:
  1. Both modules are constructed during _initialize.
  2. The CommandHandler-side attributes get populated via the manifest.
  3. /workflows list no longer short-circuits on the un-initialised path.
"""

from __future__ import annotations

import pytest
import pytest_asyncio

from bridge.app import BridgeApp
from bridge.workflow_engine import WorkflowEngine
from bridge.workflow_registry import WorkflowRegistry


@pytest_asyncio.fixture
async def wired_app(tmp_path, sample_config_toml, mock_keyring):
    """Construct + _initialize a BridgeApp without starting Discord."""
    app = BridgeApp(config_path=str(sample_config_toml))
    await app._initialize()
    yield app

    if app._db:
        await app._db.close()


class TestWorkflowConstruction:
    @pytest.mark.asyncio
    async def test_workflow_registry_constructed(self, wired_app):
        """WorkflowRegistry must be instantiated during _initialize."""
        assert wired_app._workflow_registry is not None, (
            "BridgeApp._workflow_registry is still None after _initialize — "
            "Sprint 04.06 construction did not fire."
        )
        assert isinstance(wired_app._workflow_registry, WorkflowRegistry), (
            f"Expected WorkflowRegistry, got "
            f"{type(wired_app._workflow_registry).__name__}"
        )

    @pytest.mark.asyncio
    async def test_workflow_engine_constructed(self, wired_app):
        """WorkflowEngine must be instantiated during _initialize."""
        assert wired_app._workflow_engine is not None, (
            "BridgeApp._workflow_engine is still None after _initialize — "
            "Sprint 04.06 construction did not fire."
        )
        assert isinstance(wired_app._workflow_engine, WorkflowEngine), (
            f"Expected WorkflowEngine, got "
            f"{type(wired_app._workflow_engine).__name__}"
        )


class TestCommandHandlerWiring:
    @pytest.mark.asyncio
    async def test_command_handler_receives_workflow_registry(self, wired_app):
        """The Sprint 01.03 manifest entry set_workflow_registry must fire and
        propagate the same WorkflowRegistry instance onto CommandHandler."""
        ch = wired_app._commands
        assert ch._workflow_registry is not None, (
            "CommandHandler._workflow_registry is still None — the manifest "
            "entry set_workflow_registry did not fire."
        )
        assert ch._workflow_registry is wired_app._workflow_registry, (
            "CommandHandler._workflow_registry is not the same instance as "
            "BridgeApp._workflow_registry — wiring picked up a stale or "
            "duplicate object."
        )

    @pytest.mark.asyncio
    async def test_command_handler_receives_workflow_engine(self, wired_app):
        """The Sprint 01.03 manifest entry set_workflow_engine must fire and
        propagate the same WorkflowEngine instance onto CommandHandler."""
        ch = wired_app._commands
        assert ch._workflow_engine is not None, (
            "CommandHandler._workflow_engine is still None — the manifest "
            "entry set_workflow_engine did not fire."
        )
        assert ch._workflow_engine is wired_app._workflow_engine, (
            "CommandHandler._workflow_engine is not the same instance as "
            "BridgeApp._workflow_engine — wiring picked up a stale or "
            "duplicate object."
        )


class TestWorkflowsCommandReachable:
    @pytest.mark.asyncio
    async def test_workflows_command_no_longer_short_circuits(self, wired_app):
        """/workflows list must no longer return the
        'WorkflowRegistry is not initialised.' short-circuit. Full /workflows
        wiring (list / trigger / cancel) is owned by Sprint 04.07; this test
        only verifies the registry is reachable via the command path."""
        ch = wired_app._commands
        # _cmd_workflows is the dispatcher target for /workflows.
        result = await ch._cmd_workflows(chat_id="test-chat", args="")
        assert result != "WorkflowRegistry is not initialised.", (
            "/workflows still short-circuits with the un-initialised message — "
            "Sprint 04.06 wiring did not reach CommandHandler."
        )
