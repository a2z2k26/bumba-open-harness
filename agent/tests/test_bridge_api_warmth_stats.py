"""Tests for the zone4-warmth.D.02 (#2300) observability surface.

Covers:

- ``GET /api/chief_sessions`` now includes ``idle_seconds`` and
  ``warm_window_remaining_seconds`` for ``AWAITING_EVALUATION`` rows, and
  omits them for every other state.
- ``GET /api/chief_sessions/warmth_stats`` returns the six documented
  aggregate fields, computes the warm-population ages from
  ``idle_since_utc``, and combines the 24h ``chief_dispatcher.routed``
  + ``chief_dispatcher.warmth_reused`` event counts into a reuse rate
  that handles the zero-dispatch edge case.
- Bearer-token auth applies to the new endpoint (401 without
  ``Authorization: Bearer <token>``).

Pattern mirrors ``tests/test_chief_session_api.py``: real ``APIServer``
+ ``InMemoryChiefSessionStore`` + a MagicMock ``BridgeApp``; the event bus
is faked with a tiny stub that returns the seeded event lists from
``replay()``.
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

API_TOKEN = "test-token-warmth-stats"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


class _FakeEventBus:
    """Stand-in for the production ``EventBus``.

    Only ``replay(event_type, since_timestamp)`` is exercised by the new
    handler. The fake stores one list per ``event_type`` and ignores the
    cutoff (tests already construct timestamps inside the 24h window).
    """

    def __init__(self, events: dict[str, list]) -> None:
        self._events = events

    def replay(
        self,
        event_type: str | None = None,
        since_timestamp: str | None = None,
    ) -> list:
        return list(self._events.get(event_type or "", []))


def _make_bridge(
    *,
    chief_flag: bool = True,
    store=None,
    event_bus=None,
    global_timeout: float = 14400.0,
) -> MagicMock:
    """Build a MagicMock BridgeApp tailored for the warmth-stats surface.

    The handler reads ``_config.chief_dispatcher_idle_timeout_seconds`` (for
    the per-row remaining-window computation), ``_departments`` (for the
    D.01 per-team-override helper — left as None so the global timeout
    wins), and ``_autonomy.event_bus`` (for the 24h dispatch counts).
    """
    bridge = MagicMock()
    bridge._config = MagicMock()
    bridge._config.chief_dispatcher_enabled = chief_flag
    bridge._config.chief_dispatcher_idle_timeout_seconds = global_timeout
    bridge._config.data_dir = "/tmp/test-data"
    bridge._config.operator_discord_id = "test-op"
    bridge._config.peer_coordination_enabled = False
    bridge._db = AsyncMock()
    bridge._health_server = None
    bridge._tmux_agents = None
    bridge._session_mgr = None
    bridge._cost_tracker = None
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
    bridge._departments = None  # D.01 helper falls through to global timeout
    if event_bus is None:
        bridge._autonomy = None
    else:
        bridge._autonomy = MagicMock()
        bridge._autonomy.event_bus = event_bus
    return bridge


async def _create_client(bridge: MagicMock) -> TestClient:
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
    state: ChiefSessionState,
    department: str = "engineering",
    idle_since_utc: datetime | None = None,
    session_id: str | None = None,
    work_order_id: str = "wo-1",
) -> ChiefSession:
    return ChiefSession(
        session_id=session_id or new_chief_session_id(),
        work_order_id=work_order_id,
        department=department,
        chief_name=f"{department}-chief",
        state=state,
        idle_since_utc=idle_since_utc,
    )


# ---------------------------------------------------------------------------
# /api/chief_sessions — idle_seconds field on AWAITING_EVALUATION rows
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestListIdleSecondsField:
    async def test_includes_idle_seconds_for_awaiting_evaluation(self) -> None:
        store = InMemoryChiefSessionStore()
        # idle_since_utc = 5 minutes ago, default global timeout = 14400s (4h).
        five_min_ago = datetime.now(timezone.utc) - timedelta(minutes=5)
        await store.create(_make_session(
            state=ChiefSessionState.AWAITING_EVALUATION,
            department="board",
            idle_since_utc=five_min_ago,
            session_id="cs-warm-board-01",
        ))
        bridge = _make_bridge(store=store, global_timeout=14400.0)
        client = await _create_client(bridge)
        try:
            resp = await client.get("/api/chief_sessions", headers=_auth())
            assert resp.status == 200
            data = await resp.json()
            row = data["sessions"][0]
            # 5 minutes ago — allow generous tolerance because the
            # handler captures ``now`` after the test sets it.
            assert row["idle_seconds"] == pytest.approx(300, abs=10)
            # 14400 - 300 = 14100 — same tolerance, derived from the
            # same ``now``.
            assert row["warm_window_remaining_seconds"] == pytest.approx(
                14100, abs=10
            )
        finally:
            await client.close()

    async def test_omits_idle_seconds_for_non_awaiting_evaluation(self) -> None:
        """EXECUTING / WARM / DONE rows must not carry the warm fields."""
        store = InMemoryChiefSessionStore()
        await store.create(_make_session(
            state=ChiefSessionState.EXECUTING,
            session_id="cs-exec-01",
        ))
        await store.create(_make_session(
            state=ChiefSessionState.WARM,
            session_id="cs-warm-01",
        ))
        await store.create(_make_session(
            state=ChiefSessionState.DONE,
            session_id="cs-done-01",
        ))
        bridge = _make_bridge(store=store)
        client = await _create_client(bridge)
        try:
            resp = await client.get("/api/chief_sessions", headers=_auth())
            assert resp.status == 200
            data = await resp.json()
            for row in data["sessions"]:
                assert "idle_seconds" not in row, row
                assert "warm_window_remaining_seconds" not in row, row
        finally:
            await client.close()

    async def test_window_clipped_to_zero_when_expired(self) -> None:
        """A session idle for longer than the timeout must show 0 remaining."""
        store = InMemoryChiefSessionStore()
        # 5h idle, 4h timeout → remaining should clip to 0, not go negative.
        five_hours_ago = datetime.now(timezone.utc) - timedelta(hours=5)
        await store.create(_make_session(
            state=ChiefSessionState.AWAITING_EVALUATION,
            idle_since_utc=five_hours_ago,
            session_id="cs-expired-01",
        ))
        bridge = _make_bridge(store=store, global_timeout=14400.0)
        client = await _create_client(bridge)
        try:
            resp = await client.get("/api/chief_sessions", headers=_auth())
            data = await resp.json()
            row = data["sessions"][0]
            assert row["warm_window_remaining_seconds"] == 0.0
            assert row["idle_seconds"] > 14400
        finally:
            await client.close()


# ---------------------------------------------------------------------------
# /api/chief_sessions/warmth_stats — aggregate endpoint
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestWarmthStatsEndpoint:
    async def test_aggregates_population_and_24h_events(self) -> None:
        store = InMemoryChiefSessionStore()
        now = datetime.now(timezone.utc)
        # Two AWAITING_EVALUATION sessions: ages 600s and 1200s.
        await store.create(_make_session(
            state=ChiefSessionState.AWAITING_EVALUATION,
            idle_since_utc=now - timedelta(seconds=600),
            session_id="cs-warm-1",
        ))
        await store.create(_make_session(
            state=ChiefSessionState.AWAITING_EVALUATION,
            idle_since_utc=now - timedelta(seconds=1200),
            session_id="cs-warm-2",
        ))
        # One EXECUTING — counted in by_state but not in age aggregation.
        await store.create(_make_session(
            state=ChiefSessionState.EXECUTING,
            session_id="cs-exec-1",
        ))

        # 7 warmth_reused vs 3 routed in the last 24h → reuse_rate = 0.7.
        fake_bus = _FakeEventBus({
            "chief_dispatcher.warmth_reused": [object() for _ in range(7)],
            "chief_dispatcher.routed": [object() for _ in range(3)],
        })

        bridge = _make_bridge(store=store, event_bus=fake_bus)
        client = await _create_client(bridge)
        try:
            resp = await client.get(
                "/api/chief_sessions/warmth_stats", headers=_auth()
            )
            assert resp.status == 200
            body = await resp.json()

            assert body["warm_session_count"] == 2
            assert body["warm_session_average_age_seconds"] == pytest.approx(
                900, abs=15
            )
            assert body["warm_session_oldest_age_seconds"] == pytest.approx(
                1200, abs=15
            )
            assert body["warmth_reused_events_24h"] == 7
            assert body["cold_start_events_24h"] == 3
            assert body["reuse_rate_24h"] == pytest.approx(0.7, abs=0.001)
            assert body["by_state"] == {
                "awaiting_evaluation": 2,
                "executing": 1,
            }
        finally:
            await client.close()

    async def test_handles_zero_dispatches_and_empty_store(self) -> None:
        store = InMemoryChiefSessionStore()
        fake_bus = _FakeEventBus({})
        bridge = _make_bridge(store=store, event_bus=fake_bus)
        client = await _create_client(bridge)
        try:
            resp = await client.get(
                "/api/chief_sessions/warmth_stats", headers=_auth()
            )
            assert resp.status == 200
            body = await resp.json()
            assert body["warm_session_count"] == 0
            assert body["warm_session_average_age_seconds"] == 0.0
            assert body["warm_session_oldest_age_seconds"] == 0.0
            assert body["warmth_reused_events_24h"] == 0
            assert body["cold_start_events_24h"] == 0
            # Zero-denominator case must surface 0.0, not NaN/None/crash.
            assert body["reuse_rate_24h"] == 0.0
            assert body["by_state"] == {}
        finally:
            await client.close()

    async def test_503_when_store_unwired(self) -> None:
        bridge = _make_bridge(store=None, event_bus=_FakeEventBus({}))
        client = await _create_client(bridge)
        try:
            resp = await client.get(
                "/api/chief_sessions/warmth_stats", headers=_auth()
            )
            assert resp.status == 503
        finally:
            await client.close()

    async def test_degrades_gracefully_when_event_bus_missing(self) -> None:
        """No autonomy / no event bus → 24h counts default to zero."""
        store = InMemoryChiefSessionStore()
        await store.create(_make_session(
            state=ChiefSessionState.AWAITING_EVALUATION,
            idle_since_utc=datetime.now(timezone.utc) - timedelta(seconds=60),
            session_id="cs-warm-degraded",
        ))
        bridge = _make_bridge(store=store, event_bus=None)
        client = await _create_client(bridge)
        try:
            resp = await client.get(
                "/api/chief_sessions/warmth_stats", headers=_auth()
            )
            assert resp.status == 200
            body = await resp.json()
            # Population stats still correct.
            assert body["warm_session_count"] == 1
            # 24h counts gracefully fall back to zero.
            assert body["warmth_reused_events_24h"] == 0
            assert body["cold_start_events_24h"] == 0
            assert body["reuse_rate_24h"] == 0.0
        finally:
            await client.close()


# ---------------------------------------------------------------------------
# Auth gate
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestWarmthStatsAuth:
    async def test_returns_401_without_bearer_token(self) -> None:
        bridge = _make_bridge(
            store=InMemoryChiefSessionStore(), event_bus=_FakeEventBus({})
        )
        client = await _create_client(bridge)
        try:
            # No Authorization header.
            resp = await client.get("/api/chief_sessions/warmth_stats")
            assert resp.status == 401
        finally:
            await client.close()

    async def test_returns_401_with_wrong_bearer_token(self) -> None:
        bridge = _make_bridge(
            store=InMemoryChiefSessionStore(), event_bus=_FakeEventBus({})
        )
        client = await _create_client(bridge)
        try:
            resp = await client.get(
                "/api/chief_sessions/warmth_stats",
                headers={"Authorization": "Bearer wrong-token"},
            )
            assert resp.status == 401
        finally:
            await client.close()


# ---------------------------------------------------------------------------
# Route-ordering regression — warmth_stats must NOT be swallowed by
# /api/chief_sessions/{session_id}
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestRouteOrdering:
    async def test_warmth_stats_path_is_not_treated_as_session_id(self) -> None:
        """Regression: aiohttp first-match dispatch must hit warmth_stats.

        If the dynamic ``{session_id}`` route is registered before the
        literal ``warmth_stats`` path, a GET would fall through to
        ``_handle_get_chief_session`` and return 404 (or 503) instead of
        the aggregate payload.
        """
        store = InMemoryChiefSessionStore()
        fake_bus = _FakeEventBus({})
        bridge = _make_bridge(store=store, event_bus=fake_bus)
        client = await _create_client(bridge)
        try:
            resp = await client.get(
                "/api/chief_sessions/warmth_stats", headers=_auth()
            )
            assert resp.status == 200
            body = await resp.json()
            # The literal-route handler returns the six documented keys;
            # the detail handler would return the single-session payload
            # shape (or a 404). Sentinel: ``by_state`` only ever appears
            # in the aggregate response.
            assert "by_state" in body
            assert "warm_session_count" in body
        finally:
            await client.close()
