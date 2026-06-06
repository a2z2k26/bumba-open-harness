"""Tests for Sprint 03.06 — verify WorkOrderStore and WorkOrderStreamManager
are constructed during BridgeApp._initialize() so the api_server.py getattr
callsites at lines 1385/1409/1434/1446 see real instances instead of None.

Sprint 01.04 added ``self._workorder_store = None`` and
``self._workorder_stream = None`` to BridgeApp.__init__ as **attribute-only**
declarations (no WIRING_MANIFEST setter — see app.py:333-341 comment).
This sprint introduces the actual construction step in ``_initialize`` so
the REST endpoints stop returning 503 and the WebSocket stream actually
fans out workorder.* events.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
import pytest_asyncio

from bridge.app import BridgeApp
from bridge.work_order_store import WorkOrderStore
from bridge.workorder_ingest import WorkOrderIngestor
from bridge.workorder_stream import WorkOrderStreamManager


@pytest_asyncio.fixture
async def wired_app(tmp_path, sample_config_toml, mock_keyring):
    """BridgeApp that ran _initialize once. Mirrors the fixture used in
    test_verification_wiring.py and test_app_wiring_parity.py so the
    Sprint 03.06 construction is exercised in a realistic boot path."""
    app = BridgeApp(config_path=str(sample_config_toml))
    await app._initialize()
    yield app
    if app._db:
        await app._db.close()


class TestWorkOrderStoreConstruction:
    @pytest.mark.asyncio
    async def test_workorder_store_constructed_during_initialize(
        self, wired_app: BridgeApp
    ) -> None:
        """After _initialize, _workorder_store is a real WorkOrderStore."""
        assert wired_app._workorder_store is not None
        assert isinstance(wired_app._workorder_store, WorkOrderStore)

    @pytest.mark.asyncio
    async def test_workorder_store_uses_data_dir_path(
        self, wired_app: BridgeApp
    ) -> None:
        """Store db_path lives under the configured data_dir, matching the
        config field default ``workorder_db_path = "workorders.db"``."""
        assert wired_app._workorder_store is not None
        store = wired_app._workorder_store
        # WorkOrderStore.__init__ stores db_path; check that the file lives
        # under the configured data_dir to confirm the path was wired.
        assert wired_app._config is not None
        data_dir = str(wired_app._config.data_dir)
        assert str(store._db_path).startswith(data_dir)
        assert str(store._db_path).endswith("workorders.db")


class TestWorkOrderStreamConstruction:
    @pytest.mark.asyncio
    async def test_workorder_stream_constructed_during_initialize(
        self, wired_app: BridgeApp
    ) -> None:
        """After _initialize, _workorder_stream is a real
        WorkOrderStreamManager with the autonomy event bus wired in."""
        assert wired_app._workorder_stream is not None
        assert isinstance(wired_app._workorder_stream, WorkOrderStreamManager)

    @pytest.mark.asyncio
    async def test_workorder_stream_wires_event_bus(
        self, wired_app: BridgeApp
    ) -> None:
        """wire_event_bus is called during _initialize; the manager records
        this in its private ``_wired`` flag once subscriptions are placed."""
        assert wired_app._workorder_stream is not None
        # _wired flips to True only when event_bus is non-None and
        # wire_event_bus() succeeds. Autonomy is constructed earlier in
        # _initialize, so this should be True under the wired_app fixture.
        assert wired_app._workorder_stream._wired is True


class TestWorkOrderIngestorConstruction:
    @pytest.mark.asyncio
    async def test_workorder_ingestor_constructed_during_initialize(
        self, wired_app: BridgeApp
    ) -> None:
        """After _initialize, completed WO events have a live ingestor."""
        assert wired_app._workorder_ingestor is not None
        assert isinstance(wired_app._workorder_ingestor, WorkOrderIngestor)

    @pytest.mark.asyncio
    async def test_workorder_ingestor_wires_event_bus(
        self, wired_app: BridgeApp
    ) -> None:
        """The ingestor subscribes during _initialize."""
        assert wired_app._workorder_ingestor is not None
        assert wired_app._workorder_ingestor._wired is True


class TestApiServerVisibility:
    @pytest.mark.asyncio
    async def test_api_server_can_read_workorder_store_after_init(
        self, wired_app: BridgeApp
    ) -> None:
        """The api_server.py callsites use getattr(self._bridge,
        "_workorder_store", None). After Sprint 03.06 construction this
        must return a non-None value so the REST handlers stop 503'ing."""
        wo_store = getattr(wired_app, "_workorder_store", None)
        assert wo_store is not None
        assert isinstance(wo_store, WorkOrderStore)

    @pytest.mark.asyncio
    async def test_api_server_can_read_workorder_stream_after_init(
        self, wired_app: BridgeApp
    ) -> None:
        """Same contract for the WebSocket handler at api_server.py:1434."""
        stream_mgr = getattr(wired_app, "_workorder_stream", None)
        assert stream_mgr is not None
        assert isinstance(stream_mgr, WorkOrderStreamManager)


class TestGracefulFailure:
    @pytest.mark.asyncio
    async def test_workorder_store_construction_failure_is_graceful(
        self,
        tmp_path,
        sample_config_toml,
        mock_keyring,
    ) -> None:
        """If WorkOrderStore raises during __init__, _workorder_store stays
        None and the bridge still completes _initialize. This guards
        against a corrupt SQLite file or filesystem error taking the whole
        bridge down."""
        app = BridgeApp(config_path=str(sample_config_toml))

        with patch(
            "bridge.work_order_store.WorkOrderStore.__init__",
            side_effect=RuntimeError("simulated store failure"),
        ):
            await app._initialize()

        try:
            assert app._workorder_store is None
            # Stream should still construct independently of the store
            # since they fail-soft in separate try blocks.
            assert app._workorder_stream is not None
        finally:
            if app._db:
                await app._db.close()

    @pytest.mark.asyncio
    async def test_workorder_stream_construction_failure_is_graceful(
        self,
        tmp_path,
        sample_config_toml,
        mock_keyring,
    ) -> None:
        """Symmetric guard for WorkOrderStreamManager — if it raises, the
        bridge keeps booting and the store is unaffected."""
        app = BridgeApp(config_path=str(sample_config_toml))

        with patch(
            "bridge.workorder_stream.WorkOrderStreamManager.__init__",
            side_effect=RuntimeError("simulated stream failure"),
        ):
            await app._initialize()

        try:
            assert app._workorder_stream is None
            assert app._workorder_store is not None
        finally:
            if app._db:
                await app._db.close()
