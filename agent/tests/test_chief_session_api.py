"""Tests for the Z4-S12 (#1383) ChiefSession REST endpoints.

Covers:
- ``ChiefSession.to_dict()`` round-trips datetimes, the state enum,
  metadata, and nullable timestamps.
- ``GET /api/chief_sessions`` returns all non-SHUTDOWN sessions when no
  filter is supplied, and filters correctly by work_order_id / state /
  department independently and composed.
- ``GET /api/chief_sessions/{session_id}`` returns the right row, 404s
  on an unknown id, and 503s when the store isn't wired.
- Routes only register when the ``chief_dispatcher_enabled`` flag is on.

Pattern mirrors ``tests/test_api_agents.py``: a MagicMock bridge stub +
a real ``APIServer`` + ``aiohttp`` ``TestClient``. The store fixture is
the in-memory implementation from ``bridge.chief_session_store``.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from bridge.api_server import (
    APIServer,
    cors_middleware,
    create_auth_middleware,
)
from bridge.chief_session import (
    ChiefSession,
    ChiefSessionState,
    new_chief_session_id,
)
from bridge.chief_session_store import InMemoryChiefSessionStore

pytestmark = pytest.mark.socket  # binds localhost sockets via aiohttp TestServer

API_TOKEN = "test-token-chief-sessions"


# ---------------------------------------------------------------------------
# Fixtures and helpers
# ---------------------------------------------------------------------------


def _make_bridge(*, chief_flag: bool = True, store=None) -> MagicMock:
    """Build a MagicMock BridgeApp with the chief-session wiring stub.

    Mirrors ``tests/test_api_agents._make_bridge`` plus the two attributes
    the chief-session handlers consult: ``_config.chief_dispatcher_enabled``
    and ``_chief_session_store``.
    """
    bridge = MagicMock()
    bridge._config = MagicMock()
    bridge._config.data_dir = "/tmp/test-data"
    bridge._config.operator_discord_id = "test-op"
    bridge._config.peer_coordination_enabled = False
    bridge._config.chief_dispatcher_enabled = chief_flag
    bridge._db = AsyncMock()
    bridge._health_server = None
    bridge._tmux_agents = None
    bridge._session_mgr = None
    bridge._cost_tracker = None
    bridge._autonomy = None
    bridge._memory = None
    bridge._commands = None
    bridge._metrics = None
    bridge._tracer = None
    bridge._task_queue = None
    bridge._task_pipeline = None
    bridge._quality_gate = None
    bridge._webhook_receiver = None
    bridge._peer_registry = None
    bridge._chief_session_store = store
    return bridge


async def _create_client(bridge: MagicMock) -> TestClient:
    """Spin up an aiohttp TestClient against a real APIServer instance."""
    server = APIServer(bridge, api_token=API_TOKEN)
    app = web.Application(
        middlewares=[
            cors_middleware,
            create_auth_middleware(server._api_token),
        ]
    )
    server._register_routes(app)
    ts = TestServer(app)
    client = TestClient(ts)
    await client.start_server()
    return client


def _auth() -> dict[str, str]:
    return {"Authorization": f"Bearer {API_TOKEN}"}


def _make_session(
    *,
    work_order_id: str = "wo-1",
    department: str = "engineering",
    chief_name: str = "engineering-chief",
    state: ChiefSessionState = ChiefSessionState.WARM,
    session_id: str | None = None,
    metadata: dict | None = None,
) -> ChiefSession:
    """Build a ChiefSession with sensible defaults for the test fixtures."""
    return ChiefSession(
        session_id=session_id or new_chief_session_id(),
        work_order_id=work_order_id,
        department=department,
        chief_name=chief_name,
        state=state,
        metadata=metadata or {},
    )


# ---------------------------------------------------------------------------
# to_dict() serialiser
# ---------------------------------------------------------------------------


class TestSerializer:
    """Pure-function tests for ``ChiefSession.to_dict()`` — no HTTP."""

    def test_roundtrips_required_fields(self) -> None:
        session = _make_session(
            work_order_id="wo-42",
            department="strategy",
            chief_name="strategy-product-chief",
            state=ChiefSessionState.WARM,
            session_id="cs-deadbeef0001",
        )
        d = session.to_dict()

        assert d["session_id"] == "cs-deadbeef0001"
        assert d["work_order_id"] == "wo-42"
        assert d["department"] == "strategy"
        assert d["chief_name"] == "strategy-product-chief"
        # State must serialise as the lowercase enum value, not the
        # Python repr or the enum object itself.
        assert d["state"] == "warm"
        assert d["run_count"] == 0
        assert d["cost_usd"] == 0.0
        assert d["error"] is None

    def test_datetimes_render_as_iso8601(self) -> None:
        ts = datetime(2026, 5, 9, 12, 30, 45, tzinfo=timezone.utc)
        # Drive through the state machine so multiple datetime fields
        # are populated in one go.
        session = _make_session(state=ChiefSessionState.COLD)
        session = ChiefSession(
            session_id=session.session_id,
            work_order_id=session.work_order_id,
            department=session.department,
            chief_name=session.chief_name,
            state=ChiefSessionState.WARM,
            created_at_utc=ts,
            warmed_at_utc=ts + timedelta(seconds=1),
            execution_started_at_utc=ts + timedelta(seconds=2),
            completed_at_utc=ts + timedelta(seconds=3),
            idle_since_utc=ts + timedelta(seconds=4),
        )
        d = session.to_dict()

        assert d["created_at_utc"] == "2026-05-09T12:30:45+00:00"
        assert d["warmed_at_utc"] == "2026-05-09T12:30:46+00:00"
        assert d["execution_started_at_utc"] == "2026-05-09T12:30:47+00:00"
        assert d["completed_at_utc"] == "2026-05-09T12:30:48+00:00"
        assert d["idle_since_utc"] == "2026-05-09T12:30:49+00:00"

    def test_nullable_datetimes_render_as_none(self) -> None:
        session = _make_session()
        d = session.to_dict()
        # Optional timestamps default to None and must serialise as JSON null.
        assert d["warmed_at_utc"] is None
        assert d["execution_started_at_utc"] is None
        assert d["completed_at_utc"] is None
        assert d["idle_since_utc"] is None

    def test_metadata_round_trips(self) -> None:
        session = _make_session(metadata={"reason": "retry", "attempt": 2})
        d = session.to_dict()
        assert d["metadata"] == {"reason": "retry", "attempt": 2}

    def test_metadata_is_a_copy(self) -> None:
        # Mutating the returned dict's metadata must not bleed back into
        # the source session.
        session = _make_session(metadata={"k": "v"})
        d = session.to_dict()
        d["metadata"]["k"] = "mutated"
        assert session.metadata == {"k": "v"}

    def test_state_serialises_for_each_enum_value(self) -> None:
        # Confirms enum -> string serialisation across the whole state
        # machine; protects against someone changing the enum to use
        # numeric values without rewriting to_dict().
        for state in ChiefSessionState:
            d = _make_session(state=state).to_dict()
            assert d["state"] == state.value


# ---------------------------------------------------------------------------
# Route registration / feature flag
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestRouteRegistration:
    async def test_routes_absent_when_flag_off(self) -> None:
        # When the flag is False the routes must not register — the same
        # contract Sprint 07.06 set for peer_api routes.
        bridge = _make_bridge(chief_flag=False)
        client = await _create_client(bridge)
        try:
            resp = await client.get("/api/chief_sessions", headers=_auth())
            # aiohttp returns 404 for an unregistered route.
            assert resp.status == 404
        finally:
            await client.close()

    async def test_routes_present_when_flag_on(self) -> None:
        bridge = _make_bridge(chief_flag=True, store=InMemoryChiefSessionStore())
        client = await _create_client(bridge)
        try:
            resp = await client.get("/api/chief_sessions", headers=_auth())
            # 200 because the empty store yields {"sessions": [], ...}.
            assert resp.status == 200
        finally:
            await client.close()

    async def test_returns_503_when_store_missing(self) -> None:
        # Flag on, but store not wired — handler must 503, not crash.
        bridge = _make_bridge(chief_flag=True, store=None)
        client = await _create_client(bridge)
        try:
            resp = await client.get("/api/chief_sessions", headers=_auth())
            assert resp.status == 503

            resp = await client.get(
                "/api/chief_sessions/cs-abc", headers=_auth()
            )
            assert resp.status == 503
        finally:
            await client.close()


# ---------------------------------------------------------------------------
# GET /api/chief_sessions — list endpoint
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestListChiefSessions:
    async def _seed(
        self, store: InMemoryChiefSessionStore
    ) -> dict[str, ChiefSession]:
        """Seed the store with a representative mix of sessions.

        Returns a dict so individual tests can reference rows by name.
        """
        sessions = {
            "warm_eng": _make_session(
                work_order_id="wo-1",
                department="engineering",
                state=ChiefSessionState.WARM,
                session_id="cs-warm-eng-01",
            ),
            "warm_eng_2": _make_session(
                work_order_id="wo-1",
                department="engineering",
                state=ChiefSessionState.WARM,
                session_id="cs-warm-eng-02",
            ),
            "executing_strat": _make_session(
                work_order_id="wo-2",
                department="strategy",
                state=ChiefSessionState.EXECUTING,
                session_id="cs-exec-strat-01",
            ),
            "done_eng": _make_session(
                work_order_id="wo-3",
                department="engineering",
                state=ChiefSessionState.DONE,
                session_id="cs-done-eng-01",
            ),
            "shutdown_qa": _make_session(
                work_order_id="wo-4",
                department="qa",
                state=ChiefSessionState.SHUTDOWN,
                session_id="cs-shut-qa-01",
            ),
        }
        for s in sessions.values():
            await store.create(s)
        return sessions

    async def test_no_filter_returns_all_non_shutdown(self) -> None:
        store = InMemoryChiefSessionStore()
        seeded = await self._seed(store)
        bridge = _make_bridge(store=store)
        client = await _create_client(bridge)
        try:
            resp = await client.get("/api/chief_sessions", headers=_auth())
            assert resp.status == 200
            data = await resp.json()

            # SHUTDOWN row excluded from the default aggregate.
            ids = {s["session_id"] for s in data["sessions"]}
            assert seeded["shutdown_qa"].session_id not in ids
            assert seeded["warm_eng"].session_id in ids
            assert seeded["executing_strat"].session_id in ids
            assert seeded["done_eng"].session_id in ids

            assert data["count"] == len(data["sessions"])
            assert data["total"] == 4  # 5 seeded - 1 SHUTDOWN
        finally:
            await client.close()

    async def test_filter_by_state(self) -> None:
        store = InMemoryChiefSessionStore()
        seeded = await self._seed(store)
        bridge = _make_bridge(store=store)
        client = await _create_client(bridge)
        try:
            resp = await client.get(
                "/api/chief_sessions?state=warm", headers=_auth()
            )
            assert resp.status == 200
            data = await resp.json()

            ids = {s["session_id"] for s in data["sessions"]}
            assert ids == {
                seeded["warm_eng"].session_id,
                seeded["warm_eng_2"].session_id,
            }
        finally:
            await client.close()

    async def test_filter_by_unknown_state_returns_400(self) -> None:
        store = InMemoryChiefSessionStore()
        await self._seed(store)
        bridge = _make_bridge(store=store)
        client = await _create_client(bridge)
        try:
            resp = await client.get(
                "/api/chief_sessions?state=banana", headers=_auth()
            )
            assert resp.status == 400
            data = await resp.json()
            assert "banana" in data["error"]
        finally:
            await client.close()

    async def test_filter_by_work_order_id(self) -> None:
        store = InMemoryChiefSessionStore()
        seeded = await self._seed(store)
        bridge = _make_bridge(store=store)
        client = await _create_client(bridge)
        try:
            resp = await client.get(
                "/api/chief_sessions?work_order_id=wo-1", headers=_auth()
            )
            assert resp.status == 200
            data = await resp.json()
            ids = {s["session_id"] for s in data["sessions"]}
            assert ids == {
                seeded["warm_eng"].session_id,
                seeded["warm_eng_2"].session_id,
            }
        finally:
            await client.close()

    async def test_filter_by_department(self) -> None:
        store = InMemoryChiefSessionStore()
        seeded = await self._seed(store)
        bridge = _make_bridge(store=store)
        client = await _create_client(bridge)
        try:
            resp = await client.get(
                "/api/chief_sessions?department=strategy", headers=_auth()
            )
            assert resp.status == 200
            data = await resp.json()
            ids = {s["session_id"] for s in data["sessions"]}
            assert ids == {seeded["executing_strat"].session_id}
        finally:
            await client.close()

    async def test_composed_filters_state_and_department(self) -> None:
        store = InMemoryChiefSessionStore()
        seeded = await self._seed(store)
        bridge = _make_bridge(store=store)
        client = await _create_client(bridge)
        try:
            resp = await client.get(
                "/api/chief_sessions?state=warm&department=engineering",
                headers=_auth(),
            )
            assert resp.status == 200
            data = await resp.json()
            ids = {s["session_id"] for s in data["sessions"]}
            # Both seeded WARM rows are engineering, so the composed
            # filter is identical to state=warm here — what matters is
            # that the post-filter doesn't drop a matching row.
            assert ids == {
                seeded["warm_eng"].session_id,
                seeded["warm_eng_2"].session_id,
            }
        finally:
            await client.close()

    async def test_composed_filters_work_order_and_department_no_match(
        self,
    ) -> None:
        # wo-1 sessions are all engineering, so a strategy filter must
        # produce an empty list.
        store = InMemoryChiefSessionStore()
        await self._seed(store)
        bridge = _make_bridge(store=store)
        client = await _create_client(bridge)
        try:
            resp = await client.get(
                "/api/chief_sessions?work_order_id=wo-1&department=strategy",
                headers=_auth(),
            )
            assert resp.status == 200
            data = await resp.json()
            assert data["sessions"] == []
            assert data["total"] == 0
        finally:
            await client.close()

    async def test_pagination_limit_and_offset(self) -> None:
        store = InMemoryChiefSessionStore()
        # Seed 5 WARM sessions so pagination is observable end-to-end.
        for i in range(5):
            await store.create(
                _make_session(
                    work_order_id="wo-page",
                    state=ChiefSessionState.WARM,
                    session_id=f"cs-page-{i:02d}",
                )
            )
        bridge = _make_bridge(store=store)
        client = await _create_client(bridge)
        try:
            resp = await client.get(
                "/api/chief_sessions?state=warm&limit=2&offset=1",
                headers=_auth(),
            )
            assert resp.status == 200
            data = await resp.json()
            assert data["count"] == 2
            assert data["total"] == 5
            assert data["limit"] == 2
            assert data["offset"] == 1
        finally:
            await client.close()

    async def test_invalid_pagination_returns_400(self) -> None:
        store = InMemoryChiefSessionStore()
        bridge = _make_bridge(store=store)
        client = await _create_client(bridge)
        try:
            resp = await client.get(
                "/api/chief_sessions?limit=abc", headers=_auth()
            )
            assert resp.status == 400

            resp = await client.get(
                "/api/chief_sessions?offset=-1", headers=_auth()
            )
            assert resp.status == 400
        finally:
            await client.close()


# ---------------------------------------------------------------------------
# GET /api/chief_sessions/{session_id} — detail endpoint
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestGetChiefSession:
    async def test_returns_session_when_present(self) -> None:
        store = InMemoryChiefSessionStore()
        # Start at COLD so transition() bumps run_count + populates the
        # execution_started_at_utc timestamp on the WARM -> EXECUTING leg.
        cold = _make_session(
            work_order_id="wo-detail",
            department="engineering",
            state=ChiefSessionState.COLD,
            session_id="cs-detail-01",
            metadata={"trace_id": "abc"},
        )
        warmed = cold.transition(ChiefSessionState.WARM)
        executing = warmed.transition(ChiefSessionState.EXECUTING)
        await store.create(executing)
        bridge = _make_bridge(store=store)
        client = await _create_client(bridge)
        try:
            resp = await client.get(
                f"/api/chief_sessions/{executing.session_id}",
                headers=_auth(),
            )
            assert resp.status == 200
            data = await resp.json()
            assert data["session_id"] == executing.session_id
            assert data["work_order_id"] == "wo-detail"
            assert data["department"] == "engineering"
            assert data["state"] == "executing"
            assert data["metadata"] == {"trace_id": "abc"}
            # run_count was bumped by the WARM -> EXECUTING transition.
            assert data["run_count"] == 1
            assert data["execution_started_at_utc"] is not None
        finally:
            await client.close()

    async def test_returns_404_on_unknown_id(self) -> None:
        store = InMemoryChiefSessionStore()
        bridge = _make_bridge(store=store)
        client = await _create_client(bridge)
        try:
            resp = await client.get(
                "/api/chief_sessions/cs-nonexistent",
                headers=_auth(),
            )
            assert resp.status == 404
            data = await resp.json()
            assert "cs-nonexistent" in data["error"]
        finally:
            await client.close()

    async def test_requires_bearer_auth(self) -> None:
        store = InMemoryChiefSessionStore()
        bridge = _make_bridge(store=store)
        client = await _create_client(bridge)
        try:
            # No auth header — middleware must 401.
            resp = await client.get("/api/chief_sessions")
            assert resp.status == 401

            resp = await client.get("/api/chief_sessions/cs-anything")
            assert resp.status == 401
        finally:
            await client.close()


# ---------------------------------------------------------------------------
# Z4-S42 (#1401) — GET /api/chief_sessions/{session_id}/cost
# ---------------------------------------------------------------------------


def _make_bridge_with_cost(
    *,
    chief_flag: bool = True,
    store=None,
    cost_tracker=None,
) -> MagicMock:
    """Variant of ``_make_bridge`` that wires ``_cost_tracker``.

    The Z4-S12 fixture leaves ``_cost_tracker`` at None because the list
    + detail handlers don't consult it. Z4-S42 needs the attribute set
    (or explicitly None for the 503-path test), so we shadow the helper
    rather than mutate the original to keep the existing 21 tests
    untouched.
    """
    bridge = _make_bridge(chief_flag=chief_flag, store=store)
    bridge._cost_tracker = cost_tracker
    return bridge


class _StubCostTracker:
    """Minimal CostTracker double — only what the cost endpoint touches.

    The handler calls ``get_session_cost(sid)`` and (when
    ``include_entries=true``) ``_read_entries()``. We seed both via
    constructor args so each test can build the exact slice it needs
    without writing to the real JSONL file on disk.
    """

    def __init__(
        self,
        *,
        per_session: dict[str, float] | None = None,
        entries: list | None = None,
        get_session_cost_raises: Exception | None = None,
        read_entries_raises: Exception | None = None,
    ) -> None:
        self._per_session = per_session or {}
        self._entries = entries or []
        self._get_raises = get_session_cost_raises
        self._read_raises = read_entries_raises

    def get_session_cost(self, session_id: str) -> float:
        if self._get_raises is not None:
            raise self._get_raises
        return self._per_session.get(session_id, 0.0)

    def _read_entries(self):  # noqa: D401 - mirrors CostTracker name
        if self._read_raises is not None:
            raise self._read_raises
        return list(self._entries)


def _make_cost_entry(
    *,
    chief_session_id: str = "",
    estimated_cost: float = 0.01,
    model: str = "claude-3-5-haiku-20241022",
    timestamp: str = "2026-05-09T12:00:00+00:00",
):
    """Build a CostEntry with sensible defaults for cost-endpoint tests."""
    from bridge.cost_tracker import CostEntry
    return CostEntry(
        timestamp=timestamp,
        model=model,
        input_tokens=100,
        output_tokens=50,
        estimated_cost=estimated_cost,
        task_type="chief_run",
        was_override=False,
        chief_session_id=chief_session_id,
    )


@pytest.mark.asyncio
class TestChiefSessionCostEndpoint:
    """Coverage for ``GET /api/chief_sessions/{session_id}/cost``."""

    async def test_returns_cached_and_live_totals(self) -> None:
        store = InMemoryChiefSessionStore()
        # Force the cached store-side total to a known non-zero value so
        # the assertion proves we read ``session.cost_usd`` and not zero.
        session = ChiefSession(
            session_id="cs-cost-01",
            work_order_id="wo-cost",
            department="engineering",
            chief_name="engineering-chief",
            state=ChiefSessionState.WARM,
            cost_usd=1.23,
        )
        await store.create(session)
        # Live total is independently controllable — set to a *different*
        # value so the test catches a regression that conflates the two
        # readers.
        cost_tracker = _StubCostTracker(per_session={"cs-cost-01": 1.30})
        bridge = _make_bridge_with_cost(store=store, cost_tracker=cost_tracker)
        client = await _create_client(bridge)
        try:
            resp = await client.get(
                "/api/chief_sessions/cs-cost-01/cost",
                headers=_auth(),
            )
            assert resp.status == 200
            data = await resp.json()
            assert data["session_id"] == "cs-cost-01"
            assert data["session_cost_usd"] == pytest.approx(1.23)
            assert data["total_usd"] == pytest.approx(1.30)
            # Default response must NOT include the entries list.
            assert "entries" not in data
        finally:
            await client.close()

    async def test_returns_404_for_unknown_session(self) -> None:
        store = InMemoryChiefSessionStore()
        cost_tracker = _StubCostTracker()
        bridge = _make_bridge_with_cost(store=store, cost_tracker=cost_tracker)
        client = await _create_client(bridge)
        try:
            resp = await client.get(
                "/api/chief_sessions/cs-missing/cost",
                headers=_auth(),
            )
            assert resp.status == 404
            data = await resp.json()
            assert "cs-missing" in data["error"]
        finally:
            await client.close()

    async def test_route_absent_when_dispatcher_disabled(self) -> None:
        # Flag off — even with store + tracker wired, the route must not
        # register. 404 confirms aiohttp's router rejected the path.
        store = InMemoryChiefSessionStore()
        cost_tracker = _StubCostTracker()
        bridge = _make_bridge_with_cost(
            chief_flag=False,
            store=store,
            cost_tracker=cost_tracker,
        )
        client = await _create_client(bridge)
        try:
            resp = await client.get(
                "/api/chief_sessions/cs-anything/cost",
                headers=_auth(),
            )
            assert resp.status == 404
        finally:
            await client.close()

    async def test_route_absent_when_cost_tracker_missing(self) -> None:
        # Flag on, store wired, but cost tracker is None — registration
        # guard skips the route. The list + detail endpoints still
        # register, so this confirms the guard is independent.
        store = InMemoryChiefSessionStore()
        bridge = _make_bridge_with_cost(store=store, cost_tracker=None)
        client = await _create_client(bridge)
        try:
            # Sanity: the Z4-S12 endpoint *is* still mounted.
            resp = await client.get("/api/chief_sessions", headers=_auth())
            assert resp.status == 200

            resp = await client.get(
                "/api/chief_sessions/cs-anything/cost",
                headers=_auth(),
            )
            # 404 from aiohttp router — route was never registered.
            assert resp.status == 404
        finally:
            await client.close()

    async def test_entries_empty_when_tracker_has_no_matching_rows(
        self,
    ) -> None:
        store = InMemoryChiefSessionStore()
        session = ChiefSession(
            session_id="cs-empty-01",
            work_order_id="wo-x",
            department="engineering",
            chief_name="engineering-chief",
            state=ChiefSessionState.WARM,
        )
        await store.create(session)
        # Tracker has rows tagged with a *different* session id.
        cost_tracker = _StubCostTracker(
            entries=[
                _make_cost_entry(chief_session_id="cs-other"),
                _make_cost_entry(chief_session_id=""),  # untagged row
            ],
        )
        bridge = _make_bridge_with_cost(store=store, cost_tracker=cost_tracker)
        client = await _create_client(bridge)
        try:
            resp = await client.get(
                "/api/chief_sessions/cs-empty-01/cost?include_entries=true",
                headers=_auth(),
            )
            assert resp.status == 200
            data = await resp.json()
            assert data["entries"] == []
        finally:
            await client.close()

    async def test_entries_returned_when_include_param_set(self) -> None:
        store = InMemoryChiefSessionStore()
        session = ChiefSession(
            session_id="cs-entries-01",
            work_order_id="wo-y",
            department="engineering",
            chief_name="engineering-chief",
            state=ChiefSessionState.WARM,
        )
        await store.create(session)
        # Two matching rows + one decoy that must not bleed in.
        cost_tracker = _StubCostTracker(
            per_session={"cs-entries-01": 0.07},
            entries=[
                _make_cost_entry(
                    chief_session_id="cs-entries-01",
                    estimated_cost=0.04,
                    timestamp="2026-05-09T11:00:00+00:00",
                ),
                _make_cost_entry(
                    chief_session_id="cs-entries-01",
                    estimated_cost=0.03,
                    timestamp="2026-05-09T11:30:00+00:00",
                ),
                _make_cost_entry(
                    chief_session_id="cs-other",
                    estimated_cost=999.0,
                ),
            ],
        )
        bridge = _make_bridge_with_cost(store=store, cost_tracker=cost_tracker)
        client = await _create_client(bridge)
        try:
            resp = await client.get(
                "/api/chief_sessions/cs-entries-01/cost?include_entries=true",
                headers=_auth(),
            )
            assert resp.status == 200
            data = await resp.json()
            assert data["session_cost_usd"] == pytest.approx(0.0)  # default
            assert data["total_usd"] == pytest.approx(0.07)
            entries = data["entries"]
            assert len(entries) == 2
            # Decoy row must be filtered out.
            for e in entries:
                assert e["chief_session_id"] == "cs-entries-01"
                # CostEntry serialises as JSON-friendly primitives —
                # timestamp stays a string, all dataclass fields persist.
                assert isinstance(e["timestamp"], str)
                assert e["model"]
                assert "estimated_cost" in e
                assert "input_tokens" in e
                assert "output_tokens" in e
                assert "task_type" in e
        finally:
            await client.close()

    async def test_default_response_excludes_entries(self) -> None:
        # Same shape as the first test, but explicitly asserts that
        # without ``?include_entries=true`` the entries key is absent —
        # protects against a regression where the param parser flips.
        store = InMemoryChiefSessionStore()
        session = ChiefSession(
            session_id="cs-default-01",
            work_order_id="wo-z",
            department="engineering",
            chief_name="engineering-chief",
            state=ChiefSessionState.WARM,
            cost_usd=0.5,
        )
        await store.create(session)
        cost_tracker = _StubCostTracker(
            per_session={"cs-default-01": 0.5},
            entries=[
                _make_cost_entry(chief_session_id="cs-default-01"),
            ],
        )
        bridge = _make_bridge_with_cost(store=store, cost_tracker=cost_tracker)
        client = await _create_client(bridge)
        try:
            # No query string at all.
            resp = await client.get(
                "/api/chief_sessions/cs-default-01/cost",
                headers=_auth(),
            )
            assert resp.status == 200
            data = await resp.json()
            assert "entries" not in data

            # And again with an explicit falsy value.
            resp = await client.get(
                "/api/chief_sessions/cs-default-01/cost?include_entries=0",
                headers=_auth(),
            )
            assert resp.status == 200
            data = await resp.json()
            assert "entries" not in data
        finally:
            await client.close()

    async def test_requires_bearer_auth(self) -> None:
        store = InMemoryChiefSessionStore()
        cost_tracker = _StubCostTracker()
        bridge = _make_bridge_with_cost(store=store, cost_tracker=cost_tracker)
        client = await _create_client(bridge)
        try:
            resp = await client.get("/api/chief_sessions/cs-x/cost")
            assert resp.status == 401
        finally:
            await client.close()
