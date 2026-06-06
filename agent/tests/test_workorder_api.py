"""Integration tests for WorkOrder Public API routes (Sprint 07.03).

Verifies the 4 WorkOrder route handlers in `bridge/api_server.py` operate
end-to-end with mocked-real `_workorder_store` / `_workorder_stream` setters
shipped by Plan 03 Sprint 03.06 (PR #890), and that the 503 fallback path
returns the structured `{error, hint}` body when the setters are None.

Routes covered:
  - POST /api/workorders            (_handle_create_workorder)
  - GET  /api/workorders/{wo_id}    (_handle_get_workorder)
  - GET  /ws/workorders/{wo_id}     (_handle_ws_workorder)
"""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from bridge.api_server import (
    APIServer,
    cors_middleware,
    create_auth_middleware,
)
from bridge.work_order import WorkOrder, WorkOrderStatus
from bridge.workorder_stream import WorkOrderStreamManager

pytestmark = pytest.mark.socket  # binds localhost sockets via aiohttp TestServer


API_TOKEN = "test-token-workorder-api"


def _make_bridge() -> MagicMock:
    """Build a MagicMock BridgeApp with the attributes touched by the
    WorkOrder route handlers and the unrelated routes that share the app.

    The mock starts with `_workorder_store` and `_workorder_stream` set to
    None (matching `BridgeApp.__init__` pre-Plan 03 ordering); individual
    tests overwrite them with mocks or real instances as needed.
    """
    bridge = MagicMock()
    bridge._config = MagicMock()
    bridge._config.data_dir = "/tmp/test-workorder-api"
    bridge._config.operator_discord_id = "test-op"
    # Z4-S23 (#1396) — default the chief dispatcher off so the existing
    # test suite's behavioural baseline is unchanged. Tests that exercise
    # the dispatch branch flip the flag and set ``_chief_dispatcher`` to
    # an AsyncMock (or real ChiefDispatcher) on the bridge stub.
    bridge._config.chief_dispatcher_enabled = False
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
    bridge._workorder_store = None
    bridge._workorder_stream = None
    bridge._chief_dispatcher = None
    return bridge


async def _create_client(bridge: MagicMock) -> TestClient:
    """Spin up a real aiohttp TestClient mounting the APIServer routes."""
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


def _make_stub_workorder(
    *,
    wo_id: str = "wo-stub-001",
    intent: str = "test intent",
    skill: str = "filesystem.read",
    project: str = "test",
) -> WorkOrder:
    """Build a real WorkOrder via WorkOrder.create() but pin the id for asserts."""
    wo = WorkOrder.create(intent=intent, skill=skill, project=project)
    # WorkOrder is a dataclass — use replace to keep immutability semantics.
    from dataclasses import replace as dc_replace
    return dc_replace(wo, id=wo_id, status=WorkOrderStatus.PENDING)


# ---------------------------------------------------------------------------
# POST /api/workorders — happy path returns ws_url
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestWorkOrderPost:
    async def test_workorder_post_returns_ws_url(self) -> None:
        """POST /api/workorders should respond with a ws_url field even
        when the store is unavailable (creation does not require persistence)."""
        bridge = _make_bridge()
        # Provide a mock store so the handler persists without erroring,
        # but the ws_url is constructed regardless.
        store = MagicMock()
        store.save = MagicMock(return_value=None)
        bridge._workorder_store = store

        client = await _create_client(bridge)
        try:
            resp = await client.post(
                "/api/workorders",
                json={
                    "intent": "smoke test",
                    "skill": "filesystem.read",
                    "project": "test-project",
                },
                headers=_auth(),
            )
            assert resp.status == 201
            data = await resp.json()
            assert "ws_url" in data
            assert data["ws_url"].startswith("/ws/workorders/")
            assert "workorder_id" in data
            assert data["ws_url"].endswith(data["workorder_id"])
            # Sanity: store.save was called with the new WorkOrder.
            assert store.save.call_count == 1
        finally:
            await client.close()


# ---------------------------------------------------------------------------
# GET /api/workorders/{wo_id} — happy path with mocked store
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestWorkOrderGet:
    async def test_workorder_get_with_mock_store(self) -> None:
        """GET /api/workorders/{wo_id} returns 200 + correct WO payload when
        `_workorder_store.get` returns a stub WorkOrder."""
        bridge = _make_bridge()
        wo = _make_stub_workorder(wo_id="wo-get-test-1", intent="payload check")

        store = MagicMock()
        store.get = MagicMock(return_value=wo)
        store.find_by_idempotency_key = MagicMock(return_value=None)
        bridge._workorder_store = store

        client = await _create_client(bridge)
        try:
            resp = await client.get(
                "/api/workorders/wo-get-test-1",
                headers=_auth(),
            )
            assert resp.status == 200
            data = await resp.json()
            assert data["id"] == "wo-get-test-1"
            assert data["intent"] == "payload check"
            assert data["skill"] == "filesystem.read"
            assert data["project"] == "test"
            assert data["status"] == "pending"
            store.get.assert_called_once_with("wo-get-test-1")
        finally:
            await client.close()


# ---------------------------------------------------------------------------
# GET /ws/workorders/{wo_id} — happy path delivers an event
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestWorkOrderWebSocket:
    async def test_workorder_ws_stream_delivers_event(self) -> None:
        """Connect to /ws/workorders/{wo_id}, fire one event into the real
        WorkOrderStreamManager, and assert the WebSocket client receives it."""
        bridge = _make_bridge()
        # Use a real WorkOrderStreamManager so the queue plumbing matches
        # production behavior. No store needed for this test.
        stream_mgr = WorkOrderStreamManager()
        bridge._workorder_stream = stream_mgr
        bridge._workorder_store = None  # Skip the "current state" send path.

        client = await _create_client(bridge)
        wo_id = "wo-ws-001"
        try:
            ws = await client.ws_connect(
                f"/ws/workorders/{wo_id}",
                headers=_auth(),
            )
            try:
                # Subscription happens inside the handler; give the event
                # loop one tick so subscribe() has registered the queue.
                await asyncio.sleep(0.05)

                # Fan an event out via the real manager's internal hook.
                stream_mgr._on_event(
                    "workorder.completed",
                    {"workorder_id": wo_id, "status": "complete"},
                )

                # Receive the event with a generous timeout.
                msg = await asyncio.wait_for(ws.receive(), timeout=2.0)
                assert msg.type.name in ("TEXT", "BINARY")
                payload = json.loads(msg.data)
                assert payload["event"] == "workorder.completed"
                assert payload["data"]["workorder_id"] == wo_id
                assert payload["data"]["status"] == "complete"
            finally:
                await ws.close()
        finally:
            await client.close()


# ---------------------------------------------------------------------------
# GET /api/workorders/{wo_id} — structured 503 when setters are None
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestWorkOrder503Fallback:
    async def test_workorder_get_returns_structured_503_when_unset(self) -> None:
        """If `_workorder_store` is None, the GET handler must return 503
        with the structured `{error, hint}` body documented in Sprint 07.03."""
        bridge = _make_bridge()
        bridge._workorder_store = None  # Explicit — Plan 03 didn't fire.

        client = await _create_client(bridge)
        try:
            resp = await client.get(
                "/api/workorders/any-id",
                headers=_auth(),
            )
            assert resp.status == 503
            data = await resp.json()
            assert data == {
                "error": "workorder_store_not_initialized",
                "hint": (
                    "Plan 03 dispatcher wiring is required; verify "
                    "_initialize() ran successfully"
                ),
            }
        finally:
            await client.close()


# ---------------------------------------------------------------------------
# Z4-S23 (#1396) — POST /api/workorders department-aware dispatch
# ---------------------------------------------------------------------------
#
# Behavioural matrix:
#   1. dept absent + dispatcher disabled  → existing behaviour (no chief_session_id)
#   2. dept present + dispatcher wired    → dispatch; response carries chief_session_id;
#                                            wo.department_target == dept
#   3. dept present + dispatcher disabled → 503 with chief_dispatcher_unavailable
#   4. dept absent + dispatcher enabled   → dispatch (router uses Tier-2/3/4);
#                                            wo.department_target derived/None
#   5. dept present + RoutingError raised → 422 with reason in body
#
# Tests live here next to the existing POST/GET/WS suite so the
# pre-Z4-S23 baseline and the Z4-S23 extension share one fixture surface.

def _make_chief_session_stub(
    *,
    session_id: str = "cs-test-0123456789ab",
    department: str = "engineering",
    work_order_id: str = "wo-z4s23-test",
    state: str = "awaiting_evaluation",
):
    """Build a real ChiefSession the dispatcher would have returned.

    Using a real ``ChiefSession`` (not a MagicMock) keeps the response
    serialisation honest — the handler reads ``session.state.value`` and
    ``session.department`` and we want a regression to surface as a
    JSON-serialisation failure, not as a MagicMock leak.
    """
    from bridge.chief_session import ChiefSession, ChiefSessionState

    return ChiefSession(
        session_id=session_id,
        work_order_id=work_order_id,
        department=department,
        chief_name="engineering-chief",
        state=ChiefSessionState(state),
    )


@pytest.mark.asyncio
class TestWorkOrderDispatchExtension:
    """Z4-S23 (#1396) coverage for the department-aware dispatch branch."""

    async def test_post_without_department_dispatcher_disabled_preserves_behaviour(
        self,
    ) -> None:
        """Baseline: with no department field and no dispatcher, the
        response shape must match the pre-Z4-S23 contract — no
        ``chief_session_id`` key, no ``chief_session_state`` key."""
        bridge = _make_bridge()
        bridge._chief_dispatcher = None
        bridge._config.chief_dispatcher_enabled = False
        store = MagicMock()
        store.save = MagicMock(return_value=None)
        bridge._workorder_store = store

        client = await _create_client(bridge)
        try:
            resp = await client.post(
                "/api/workorders",
                json={
                    "intent": "back-compat smoke",
                    "skill": "filesystem.read",
                    "project": "test",
                },
                headers=_auth(),
            )
            assert resp.status == 201
            data = await resp.json()
            assert "workorder_id" in data
            assert "ws_url" in data
            assert "chief_session_id" not in data
            assert "chief_session_state" not in data
        finally:
            await client.close()

    async def test_post_with_department_and_dispatcher_returns_chief_session_id(
        self,
    ) -> None:
        """When ``department`` is set AND the dispatcher is wired, the
        handler must call ``dispatcher.dispatch`` with a WorkOrder whose
        ``department_target`` matches the request, and the response
        carries the resulting ``chief_session_id``."""
        bridge = _make_bridge()
        bridge._config.chief_dispatcher_enabled = True

        # Capture the WorkOrder the dispatcher receives so we can assert
        # the department_target was propagated.
        captured: dict[str, Any] = {}
        session_stub = _make_chief_session_stub(
            session_id="cs-engfromdept-001",
            department="engineering",
        )

        async def _fake_dispatch(work_order, deps):  # type: ignore[no-untyped-def]
            captured["work_order"] = work_order
            captured["deps"] = deps
            return session_stub

        dispatcher = MagicMock()
        dispatcher.dispatch = _fake_dispatch
        bridge._chief_dispatcher = dispatcher

        store = MagicMock()
        store.save = MagicMock(return_value=None)
        bridge._workorder_store = store

        client = await _create_client(bridge)
        try:
            resp = await client.post(
                "/api/workorders",
                json={
                    "intent": "explicit dispatch",
                    "skill": "filesystem.read",
                    "project": "test",
                    "department": "engineering",
                },
                headers=_auth(),
            )
            assert resp.status == 201
            data = await resp.json()
            assert data["chief_session_id"] == "cs-engfromdept-001"
            assert data["chief_session_state"] == "awaiting_evaluation"
            assert data["department"] == "engineering"
            # WorkOrder.department_target must have been set from the
            # request body, not the skill-derived default.
            wo_passed = captured["work_order"]
            assert wo_passed.department_target == "engineering"
        finally:
            await client.close()

    async def test_post_with_department_hint_alias_also_dispatches(self) -> None:
        """The legacy issue-spec field name ``department_hint`` is
        accepted as an alias for ``department`` — neither caller should
        be left behind."""
        bridge = _make_bridge()
        bridge._config.chief_dispatcher_enabled = True

        captured: dict[str, Any] = {}
        session_stub = _make_chief_session_stub(department="qa")

        async def _fake_dispatch(work_order, deps):  # type: ignore[no-untyped-def]
            captured["work_order"] = work_order
            return session_stub

        dispatcher = MagicMock()
        dispatcher.dispatch = _fake_dispatch
        bridge._chief_dispatcher = dispatcher
        bridge._workorder_store = None

        client = await _create_client(bridge)
        try:
            resp = await client.post(
                "/api/workorders",
                json={
                    "intent": "alias check",
                    "skill": "filesystem.read",
                    "project": "test",
                    "department_hint": "qa",
                },
                headers=_auth(),
            )
            assert resp.status == 201
            data = await resp.json()
            assert "chief_session_id" in data
            assert captured["work_order"].department_target == "qa"
        finally:
            await client.close()

    async def test_post_with_department_dispatcher_disabled_returns_503(
        self,
    ) -> None:
        """Caller asked for dispatch but the dispatcher is unwired or
        the flag is false — return 503 so the caller knows their hint
        was not honoured (silently ignoring would be a hidden contract
        break)."""
        bridge = _make_bridge()
        bridge._chief_dispatcher = None
        bridge._config.chief_dispatcher_enabled = False
        bridge._workorder_store = None

        client = await _create_client(bridge)
        try:
            resp = await client.post(
                "/api/workorders",
                json={
                    "intent": "should fail loudly",
                    "skill": "filesystem.read",
                    "project": "test",
                    "department": "engineering",
                },
                headers=_auth(),
            )
            assert resp.status == 503
            data = await resp.json()
            assert data["error"] == "chief_dispatcher_unavailable"
            assert "hint" in data
        finally:
            await client.close()

    async def test_post_without_department_with_dispatcher_enabled_dispatches(
        self,
    ) -> None:
        """Even without an explicit department, when the flag is on and
        the dispatcher is wired, every new WorkOrder is dispatched. The
        rule-based router will fall back to Tier 2/3/4 (keyword,
        heuristic, default). The dispatch call MUST happen and the
        response MUST include ``chief_session_id``."""
        bridge = _make_bridge()
        bridge._config.chief_dispatcher_enabled = True

        captured: dict[str, Any] = {}
        session_stub = _make_chief_session_stub(department="ops")

        async def _fake_dispatch(work_order, deps):  # type: ignore[no-untyped-def]
            captured["work_order"] = work_order
            return session_stub

        dispatcher = MagicMock()
        dispatcher.dispatch = _fake_dispatch
        bridge._chief_dispatcher = dispatcher
        bridge._workorder_store = None

        client = await _create_client(bridge)
        try:
            resp = await client.post(
                "/api/workorders",
                json={
                    "intent": "no hint, dispatcher takes over",
                    "skill": "filesystem.read",
                    "project": "test",
                },
                headers=_auth(),
            )
            assert resp.status == 201
            data = await resp.json()
            assert data["chief_session_id"]
            assert data["department"] == "ops"
            # No explicit department_target was set on the WO via the
            # body — the skill ``filesystem.read`` does not derive one
            # either, so the dispatcher's router gets a WO with
            # ``department_target=None`` and uses Tier 2/3/4.
            assert captured["work_order"].department_target is None
        finally:
            await client.close()

    async def test_post_with_bad_department_raises_routing_error_returns_422(
        self,
    ) -> None:
        """If the dispatcher raises ``RoutingError`` (unknown department,
        no eligible chief, etc.), the handler must surface 422 with the
        reason in the body — never a 500 — so callers can branch on
        routing-vs-system failure cleanly."""
        from bridge.work_order_router import RoutingError

        bridge = _make_bridge()
        bridge._config.chief_dispatcher_enabled = True

        async def _failing_dispatch(work_order, deps):  # type: ignore[no-untyped-def]
            raise RoutingError(work_order.id, "unknown department: nope")

        dispatcher = MagicMock()
        dispatcher.dispatch = _failing_dispatch
        bridge._chief_dispatcher = dispatcher
        bridge._workorder_store = None

        client = await _create_client(bridge)
        try:
            resp = await client.post(
                "/api/workorders",
                json={
                    "intent": "bad dept",
                    "skill": "filesystem.read",
                    "project": "test",
                    "department": "nope",
                },
                headers=_auth(),
            )
            assert resp.status == 422
            data = await resp.json()
            assert data["error"] == "routing_error"
            assert "unknown department: nope" in data["reason"]
            assert "workorder_id" in data
        finally:
            await client.close()


# ---------------------------------------------------------------------------
# Sprint S3.2 (Backend Operability, #2283) —
#   GET /api/executors/status — per-executor activation + routability surface
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestExecutorStatusRoute:
    async def test_executor_status_returns_payload_with_routable_flag(
        self,
    ) -> None:
        """The route returns one entry per executor with ``status`` and
        ``routable``. E2B is visibly stub + non-routable; subagent/department
        active + routable; the response shape is the contract the operator
        UI reads."""
        bridge = _make_bridge()
        dispatcher = MagicMock()
        dispatcher.get_executor_status_payload = MagicMock(
            return_value={
                "subagent": {"status": "active", "routable": True},
                "department": {"status": "active", "routable": True},
                "worktree": {"status": "active_low_traffic", "routable": True},
                "tmux": {"status": "conditional_unwired", "routable": False},
                "e2b": {"status": "stub", "routable": False},
            }
        )
        bridge._dispatcher = dispatcher

        client = await _create_client(bridge)
        try:
            resp = await client.get(
                "/api/executors/status",
                headers=_auth(),
            )
            assert resp.status == 200
            data = await resp.json()
            assert "executors" in data
            executors = data["executors"]
            assert executors["subagent"] == {"status": "active", "routable": True}
            assert executors["e2b"] == {"status": "stub", "routable": False}
            assert executors["tmux"] == {
                "status": "conditional_unwired",
                "routable": False,
            }
            # All five canonical lanes present.
            assert set(executors.keys()) == {
                "subagent", "department", "worktree", "tmux", "e2b",
            }
        finally:
            await client.close()

    async def test_executor_status_returns_503_when_dispatcher_unwired(
        self,
    ) -> None:
        """When the dispatcher hasn't been constructed (zone-3 disabled),
        the route returns 503 with a structured error body the operator UI
        can show — never a 500."""
        bridge = _make_bridge()
        bridge._dispatcher = None

        client = await _create_client(bridge)
        try:
            resp = await client.get(
                "/api/executors/status",
                headers=_auth(),
            )
            assert resp.status == 503
            data = await resp.json()
            assert data["error"] == "dispatcher_not_wired"
            assert "hint" in data
        finally:
            await client.close()
