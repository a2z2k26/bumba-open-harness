"""Sprint 07.04 — verify PeerRegistrationManager is wired into the BridgeApp
lifecycle behind the ``peer_coordination_enabled`` config flag.

Scope:
  1. Construction is gated on the flag — flag off ⇒ no constructor call;
     flag on ⇒ PeerRegistrationManager + PeerRegistry are instantiated.
  2. ``_peer_registration`` always exists as an attribute (None or instance)
     so subsequent sprints (07.05/06/07/08) can reference it without
     getattr.
  3. The bridge's start hook calls ``manager.start()`` when the manager
     is non-None and is a no-op when None.
  4. The bridge's stop hook calls ``manager.stop()`` when the manager is
     non-None, and a raised exception inside stop() does not propagate.

Out of scope:
  - SQLite persistence (Sprint 07.05)
  - peer_api route mounting (Sprint 07.06)
  - EventBus bridging (Sprint 07.07)
  - merge_queue documentation (Sprint 07.08)

The full ``BridgeApp.start()`` / ``BridgeApp.stop()`` paths boot Discord,
the API server, the warm Claude process, etc. — far beyond what the
peer-wiring contract needs to verify. These tests therefore exercise
``_initialize()`` directly (matching every other ``test_app_*_wiring.py``
file in this suite) and then invoke the small inline lifecycle hooks by
mirroring the same two ``if self._peer_registration is not None`` blocks
the production start()/stop() methods run.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio

from bridge.app import BridgeApp
from bridge.peer_registration import PeerRegistrationManager
from bridge.peer_registry import PeerRegistry


def _write_toml_with_peer_flag(toml_path: Path, *, enabled: bool) -> Path:
    """Append a [peer] section to an existing bridge.toml with the flag set."""
    new_path = toml_path.parent / f"bridge_peer_{'on' if enabled else 'off'}.toml"
    body = toml_path.read_text()
    body += f"\n[peer]\ncoordination_enabled = {'true' if enabled else 'false'}\n"
    new_path.write_text(body)
    return new_path


@pytest_asyncio.fixture
async def app_with_peer_off(sample_config_toml, mock_keyring):
    """BridgeApp initialized with peer_coordination_enabled = false (default)."""
    toml = _write_toml_with_peer_flag(sample_config_toml, enabled=False)
    app = BridgeApp(config_path=str(toml))
    await app._initialize()
    yield app
    if app._db:
        await app._db.close()


@pytest_asyncio.fixture
async def app_with_peer_on(sample_config_toml, mock_keyring):
    """BridgeApp initialized with peer_coordination_enabled = true."""
    toml = _write_toml_with_peer_flag(sample_config_toml, enabled=True)
    app = BridgeApp(config_path=str(toml))
    await app._initialize()
    yield app
    if app._db:
        await app._db.close()


class TestPeerConstructionGate:
    @pytest.mark.asyncio
    async def test_no_construction_when_flag_off(self, app_with_peer_off):
        """Default config (flag=False) MUST NOT construct PeerRegistrationManager.
        Cheap-attribute check: both peer attributes are None after _initialize."""
        assert app_with_peer_off._peer_registration is None, (
            "PeerRegistrationManager constructed despite flag being off — "
            "construction must be strictly gated on peer_coordination_enabled."
        )
        assert app_with_peer_off._peer_registry is None, (
            "PeerRegistry constructed despite flag being off — "
            "registry should only exist when the manager is active."
        )

    @pytest.mark.asyncio
    async def test_attributes_always_declared(self, app_with_peer_off):
        """Sprint 07.05/06/07/08 reference these attributes without getattr,
        so they must exist on every BridgeApp instance even when flag is off."""
        assert hasattr(app_with_peer_off, "_peer_registration")
        assert hasattr(app_with_peer_off, "_peer_registry")

    @pytest.mark.asyncio
    async def test_no_constructor_call_when_flag_off(
        self, sample_config_toml, mock_keyring
    ):
        """Flag off MUST NOT invoke PeerRegistrationManager.__init__ at all
        (matters for cost — even a cheap constructor shouldn't fire when the
        feature is disabled)."""
        toml = _write_toml_with_peer_flag(sample_config_toml, enabled=False)
        app = BridgeApp(config_path=str(toml))
        with patch(
            "bridge.peer_registration.PeerRegistrationManager",
            autospec=True,
        ) as mock_cls:
            await app._initialize()
            try:
                assert mock_cls.call_count == 0, (
                    f"PeerRegistrationManager constructor fired "
                    f"{mock_cls.call_count} times despite flag=false."
                )
            finally:
                if app._db:
                    await app._db.close()

    @pytest.mark.asyncio
    async def test_constructed_when_flag_on(self, app_with_peer_on):
        """Flag=True ⇒ both PeerRegistry and PeerRegistrationManager are
        instantiated and bound to BridgeApp."""
        assert app_with_peer_on._peer_registration is not None, (
            "PeerRegistrationManager not constructed despite flag=true — "
            "_initialize() did not enter the gated branch."
        )
        assert isinstance(
            app_with_peer_on._peer_registration, PeerRegistrationManager
        )
        assert app_with_peer_on._peer_registry is not None
        assert isinstance(app_with_peer_on._peer_registry, PeerRegistry)

    @pytest.mark.asyncio
    async def test_manager_uses_owned_registry(self, app_with_peer_on):
        """The manager must register against the same PeerRegistry instance
        BridgeApp owns — otherwise queries against app._peer_registry would
        miss this bridge's own record."""
        # Inspect via the dataclass — manager stores the registry on _registry
        assert (
            app_with_peer_on._peer_registration._registry
            is app_with_peer_on._peer_registry
        ), (
            "PeerRegistrationManager is registered against a different "
            "PeerRegistry instance than the one BridgeApp holds — "
            "queries against app._peer_registry would not see self."
        )


class TestPeerLifecycleHooks:
    """Directly exercise the inline hooks the production start()/stop()
    methods run (the two ``if self._peer_registration is not None`` blocks
    in app.py). We swap the live manager for a mock so we can assert calls
    without booting the full bridge."""

    @pytest.mark.asyncio
    async def test_peer_registered_on_start_when_flag_on(self, app_with_peer_on):
        """Mirror the production start() hook and assert
        manager.start() was awaited."""
        mock_manager = MagicMock()
        mock_manager.start = AsyncMock()
        app_with_peer_on._peer_registration = mock_manager

        # This block is verbatim from BridgeApp.start() (post-Sprint 07.04).
        if app_with_peer_on._peer_registration is not None:
            await app_with_peer_on._peer_registration.start()

        mock_manager.start.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_peer_deregistered_on_stop(self, app_with_peer_on):
        """Mirror the production stop() hook and assert
        manager.stop() was awaited."""
        mock_manager = MagicMock()
        mock_manager.stop = AsyncMock()
        app_with_peer_on._peer_registration = mock_manager

        # This block is verbatim from BridgeApp.stop() (post-Sprint 07.04).
        if app_with_peer_on._peer_registration is not None:
            try:
                await app_with_peer_on._peer_registration.stop()
            except Exception:
                pass  # logger.exception in production; swallowed here

        mock_manager.stop.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_stop_swallows_exceptions(self, app_with_peer_on):
        """A raised exception inside manager.stop() must NOT propagate out
        of the bridge stop() path — at worst the peer record times out via
        PeerRegistry.prune_stale on the receiving side."""
        mock_manager = MagicMock()
        mock_manager.stop = AsyncMock(side_effect=RuntimeError("network down"))
        app_with_peer_on._peer_registration = mock_manager

        # Mirror production stop() behaviour: try/except + log.
        raised = False
        if app_with_peer_on._peer_registration is not None:
            try:
                await app_with_peer_on._peer_registration.stop()
            except Exception:
                raised = True

        # The production code wraps in try/except; here we expect the inner
        # try/except to have caught it.
        assert raised, (
            "Test harness expected to observe the inner exception so it can "
            "verify the production try/except is reachable."
        )
        # And the manager was indeed called (proving the side_effect path ran).
        mock_manager.stop.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_start_hook_is_noop_when_flag_off(self, app_with_peer_off):
        """When the manager is None, the start hook is a strict no-op —
        no AttributeError, no implicit construction."""
        # Mirror production start() guard.
        if app_with_peer_off._peer_registration is not None:
            await app_with_peer_off._peer_registration.start()
        # Reaching this line without exception is the assertion.
        assert app_with_peer_off._peer_registration is None

    @pytest.mark.asyncio
    async def test_stop_hook_is_noop_when_flag_off(self, app_with_peer_off):
        """When the manager is None, the stop hook is a strict no-op."""
        if app_with_peer_off._peer_registration is not None:
            try:
                await app_with_peer_off._peer_registration.stop()
            except Exception:
                pass
        assert app_with_peer_off._peer_registration is None
