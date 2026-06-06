"""Tests for /dispatch command — Sprint 03.05.

Verifies that BridgeApp._initialize() constructs a RoutingBrain instance and
the WIRING_MANIFEST entry from Sprint 01.03 (set_routing_brain) fires, so
/dispatch no longer short-circuits with "RoutingBrain not configured".
"""

from __future__ import annotations

import pytest
import pytest_asyncio

from bridge.app import BridgeApp
from bridge.routing_brain import RoutingBrain


@pytest_asyncio.fixture
async def initialized_app(sample_config_toml, mock_keyring):
    """A BridgeApp that has run through _initialize() so all wiring fires."""
    app = BridgeApp(config_path=str(sample_config_toml))
    await app._initialize()
    yield app
    if app._db:
        await app._db.close()


class TestRoutingBrainConstruction:
    """Sprint 03.05 contract: RoutingBrain is constructed during _initialize()
    and the manifest entry from Sprint 01.03 fires it onto CommandHandler."""

    @pytest.mark.asyncio
    async def test_routing_brain_set_during_initialize(self, initialized_app):
        """After _initialize(), CommandHandler._routing_brain must be a real
        RoutingBrain instance — not None, not the wire-to-None placeholder."""
        app = initialized_app
        assert app._commands is not None, "CommandHandler not built"
        assert app._commands._routing_brain is not None, (
            "CommandHandler._routing_brain is None after _initialize() — "
            "Sprint 03.05 wiring did not fire."
        )
        assert isinstance(app._commands._routing_brain, RoutingBrain), (
            "CommandHandler._routing_brain is not a RoutingBrain instance: "
            f"got {type(app._commands._routing_brain)!r}"
        )

    @pytest.mark.asyncio
    async def test_app_holds_routing_brain_source_attribute(self, initialized_app):
        """BridgeApp._routing_brain — the manifest source — must also be the
        constructed instance (and the same one wired into CommandHandler)."""
        app = initialized_app
        assert app._routing_brain is not None
        assert isinstance(app._routing_brain, RoutingBrain)
        assert app._routing_brain is app._commands._routing_brain, (
            "BridgeApp._routing_brain and CommandHandler._routing_brain "
            "diverged — manifest is supposed to wire the same instance."
        )


class TestDispatchCommand:
    """Sprint 03.05 contract: /dispatch returns a routing decision instead of
    the not-configured short-circuit once RoutingBrain is wired."""

    @pytest.mark.asyncio
    async def test_dispatch_command_no_longer_returns_not_configured(self, initialized_app):
        """/dispatch <text> must produce a routing decision after _initialize()."""
        app = initialized_app
        response = await app._commands._cmd_dispatch("operator", "fix the typo in the README")
        assert "RoutingBrain not configured" not in response, (
            "Dispatch still short-circuits with 'RoutingBrain not configured' "
            f"after Sprint 03.05 wiring. Response: {response!r}"
        )
        # Either we see the routing-decision summary (no dispatcher wired) or
        # the dispatch-result summary (dispatcher wired). Both contain the
        # Environment line and the Reason line (or Dispatched: line).
        assert "Environment:" in response, (
            f"Expected an Environment line in dispatch response: {response!r}"
        )

    @pytest.mark.asyncio
    async def test_dispatch_usage_message_when_text_empty(self, initialized_app):
        """/dispatch with no args returns the usage hint, regardless of brain wiring."""
        app = initialized_app
        response = await app._commands._cmd_dispatch("operator", "")
        assert "Usage:" in response


class TestGracefulDegradation:
    """If EnvironmentSelector is unavailable, RoutingBrain stays None and the
    /dispatch command preserves its not-configured error path."""

    @pytest.mark.asyncio
    async def test_dispatch_command_when_env_selector_missing(self, initialized_app):
        """Force the env selector path off and reconstruct: RoutingBrain stays None,
        dispatch returns the not-configured error.

        We can't easily force a real failure of the EnvironmentSelector init
        in a unit test (it has no external deps to drop), so we simulate the
        post-init state where _routing_brain is None — the dispatch
        command's error branch must remain reachable."""
        app = initialized_app
        # Simulate the env-selector-missing branch by clearing both the
        # constructed brain and the source attribute.
        app._commands._routing_brain = None
        response = await app._commands._cmd_dispatch("operator", "anything")
        assert "RoutingBrain not configured" in response, (
            "Dispatch command's not-configured graceful-degradation branch "
            f"is no longer reachable. Response: {response!r}"
        )
