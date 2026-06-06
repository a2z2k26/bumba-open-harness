"""Tests for the operator dashboard endpoint (Board Phase 2 WS1, #2391).

Verifies the JSON aggregation across service states (with cumulative cost),
escalation alerts, halt status, wiring summary, and cost totals; plus the
HTML page served at /dashboard. Seam audited against the producer surfaces:
service-state schema (services/base.py REQUIRED_STATE_FIELDS), EscalationEngine
alert shape, SecurityManager halt API, WiringReport fields, CostTracker
summaries.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from bridge.api.routes_dashboard import _aggregate_service_runs, _wiring_summary
from bridge.api_server import (
    APIServer,
    cors_middleware,
    create_auth_middleware,
)
from bridge.wiring import WiringReport

pytestmark = pytest.mark.socket

API_TOKEN = "test-token-dash"


def _make_bridge(data_dir: str):
    bridge = MagicMock()
    bridge._config = MagicMock()
    bridge._config.data_dir = data_dir
    bridge._config.operator_discord_id = "test-op"
    bridge._db = AsyncMock()
    bridge._health_server = None
    bridge._tmux_agents = None
    bridge._session_mgr = None
    bridge._cost_tracker = None
    bridge._autonomy = None
    bridge._security = None
    bridge._wiring_report = None
    bridge._memory = None
    bridge._commands = None
    bridge._metrics = None
    bridge._tracer = None
    bridge._task_queue = None
    bridge._task_pipeline = None
    bridge._quality_gate = None
    bridge._webhook_receiver = None
    bridge._workorder_store = None
    return bridge


async def _create_client(bridge):
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


def _auth():
    return {"Authorization": f"Bearer {API_TOKEN}"}


def _write_state(data_dir: Path, name: str, payload: dict) -> None:
    sdir = data_dir / "service_state"
    sdir.mkdir(parents=True, exist_ok=True)
    (sdir / f"{name}-state.json").write_text(json.dumps(payload))


# ----------------------------------------------------------------------
# Pure-function unit tests (no socket)
# ----------------------------------------------------------------------

class TestAggregateServiceRuns:
    def test_empty_dir(self, tmp_path):
        rows = _aggregate_service_runs(tmp_path / "service_state")
        assert rows == []

    def test_reads_cost_and_sorts_recent_first(self, tmp_path):
        _write_state(tmp_path, "briefing", {
            "last_run": "2026-05-30T07:30:00+00:00",
            "last_status": "success",
            "total_cost_usd": 1.25,
            "total_runs": 10,
        })
        _write_state(tmp_path, "retro", {
            "last_run": "2026-05-31T18:00:00+00:00",
            "last_status": "success",
            "total_cost_usd": 0.5,
            "total_runs": 3,
        })
        rows = _aggregate_service_runs(tmp_path / "service_state")
        names = [r["service"] for r in rows]
        # retro ran more recently -> first
        assert names.index("retro") < names.index("briefing")
        briefing = next(r for r in rows if r["service"] == "briefing")
        assert briefing["total_cost_usd"] == 1.25
        assert briefing["total_runs"] == 10

    def test_corrupt_file_does_not_crash(self, tmp_path):
        sdir = tmp_path / "service_state"
        sdir.mkdir(parents=True)
        (sdir / "briefing-state.json").write_text("{not json")
        rows = _aggregate_service_runs(sdir)
        assert len(rows) == 1
        assert rows[0]["last_status"] == "error"


class TestWiringSummary:
    def test_none_report(self):
        s = _wiring_summary(None)
        assert s["available"] is False
        assert s["active"] == 0

    def test_populated_report(self):
        report = WiringReport()
        report.active = 12
        report.pending = [("set_x", "deferred")]
        report.failed = [("set_y", "crashed")]
        s = _wiring_summary(report)
        assert s["available"] is True
        assert s["active"] == 12
        assert s["pending"] == 1
        assert s["failed"] == 1
        assert s["failed_setters"] == ["set_y"]


# ----------------------------------------------------------------------
# Endpoint integration tests
# ----------------------------------------------------------------------

@pytest.mark.asyncio
class TestDashboardEndpoint:
    async def test_minimal_payload(self, tmp_path):
        bridge = _make_bridge(str(tmp_path))
        client = await _create_client(bridge)
        try:
            resp = await client.get("/api/v1/dashboard", headers=_auth())
            assert resp.status == 200
            data = await resp.json()
            assert data["halt"] == {"halted": False, "reason": None}
            assert data["wiring"]["available"] is False
            assert data["active_escalations"] == []
            assert data["service_runs"] == []
            assert "cost" in data
            assert "generated_at" in data
        finally:
            await client.close()

    async def test_requires_auth(self, tmp_path):
        bridge = _make_bridge(str(tmp_path))
        client = await _create_client(bridge)
        try:
            resp = await client.get("/api/v1/dashboard")
            assert resp.status == 401
        finally:
            await client.close()

    async def test_full_aggregation(self, tmp_path):
        bridge = _make_bridge(str(tmp_path))
        _write_state(tmp_path, "briefing", {
            "last_run": "2026-05-31T07:30:00+00:00",
            "last_status": "success",
            "total_cost_usd": 2.0,
            "total_runs": 5,
        })

        # Halt source.
        security = MagicMock()
        security.is_halted.return_value = True
        security.check_halt_flag.return_value = "operator halt"
        bridge._security = security

        # Wiring report.
        report = WiringReport()
        report.active = 7
        report.failed = [("set_z", "boom")]
        bridge._wiring_report = report

        # Escalation alert.
        autonomy = MagicMock()
        alert = MagicMock()
        alert.level = 2
        alert.message = "email failed"
        alert.triggered_at = "2026-05-31T08:00:00+00:00"
        alert.deferred = False
        autonomy.escalation._active_alerts = {"email": alert}
        bridge._autonomy = autonomy

        # Cost tracker.
        tracker = MagicMock()
        tracker.get_daily_summary.return_value = {"total_cost": 3.0, "request_count": 9}
        tracker.get_weekly_summary.return_value = {"total_cost": 20.0}
        # WS3.6: by_workflow is now part of the cost block — stub it so the
        # dashboard payload stays JSON-serializable (mirrors WS3.3's stub need).
        tracker.get_cost_by_workflow.return_value = {}
        bridge._cost_tracker = tracker

        client = await _create_client(bridge)
        try:
            resp = await client.get("/api/v1/dashboard", headers=_auth())
            assert resp.status == 200
            data = await resp.json()
            assert data["halt"]["halted"] is True
            assert data["halt"]["reason"] == "operator halt"
            assert data["wiring"]["active"] == 7
            assert data["wiring"]["failed_setters"] == ["set_z"]
            assert data["escalation_count"] == 1
            assert data["active_escalations"][0]["source"] == "email"
            runs = data["service_runs"]
            assert any(r["service"] == "briefing" and r["total_cost_usd"] == 2.0 for r in runs)
            assert data["cost"]["daily"]["total_cost"] == 3.0
            assert data["cost"]["weekly"]["total_cost"] == 20.0
        finally:
            await client.close()

    async def test_dashboard_includes_workflow_cost(self, tmp_path):
        """WS3.6 (#2570) — dashboard surfaces by_workflow cost + recent
        workflow runs alongside the existing cost totals."""
        bridge = _make_bridge(str(tmp_path))

        tracker = MagicMock()
        tracker.get_daily_summary.return_value = {"total_cost": 3.0, "request_count": 9}
        tracker.get_weekly_summary.return_value = {"total_cost": 20.0}
        tracker.get_cost_by_workflow.return_value = {
            "onboarding": {"cost": 1.5, "count": 2, "input_tokens": 100, "output_tokens": 50}
        }
        bridge._cost_tracker = tracker

        run = MagicMock()
        run.id = "run-1"
        run.workflow_name = "onboarding"
        run.status = "completed"
        run.current_step = 3
        run.context = {}
        run.cost_usd = 1.5
        run.created_at = "2026-06-03T10:00:00+00:00"
        run.completed_at = "2026-06-03T10:05:00+00:00"
        store = MagicMock()
        store.list_all_runs.return_value = [run]
        bridge._workorder_store = store

        client = await _create_client(bridge)
        try:
            resp = await client.get("/api/v1/dashboard", headers=_auth())
            assert resp.status == 200
            data = await resp.json()
            assert data["cost"]["by_workflow"]["onboarding"]["cost"] == 1.5
            wf_runs = data["workflow_runs"]
            assert len(wf_runs) == 1
            assert wf_runs[0]["workflow_name"] == "onboarding"
            assert wf_runs[0]["cost_usd"] == 1.5
            store.list_all_runs.assert_called_once_with(limit=10)
        finally:
            await client.close()

    async def test_dashboard_no_workorder_store(self, tmp_path):
        """When the durable store is absent, workflow_runs is empty and the
        cost block still carries a by_workflow key — never 500s."""
        bridge = _make_bridge(str(tmp_path))
        tracker = MagicMock()
        tracker.get_daily_summary.return_value = {"total_cost": 0.0}
        tracker.get_weekly_summary.return_value = {"total_cost": 0.0}
        tracker.get_cost_by_workflow.return_value = {}
        bridge._cost_tracker = tracker
        bridge._workorder_store = None

        client = await _create_client(bridge)
        try:
            resp = await client.get("/api/v1/dashboard", headers=_auth())
            assert resp.status == 200
            data = await resp.json()
            assert data["workflow_runs"] == []
            assert data["cost"]["by_workflow"] == {}
        finally:
            await client.close()

    async def test_html_page_served(self, tmp_path):
        bridge = _make_bridge(str(tmp_path))
        client = await _create_client(bridge)
        try:
            resp = await client.get("/dashboard", headers=_auth())
            assert resp.status == 200
            assert resp.content_type == "text/html"
            body = await resp.text()
            assert "BUMBA OPERATOR DASHBOARD" in body
            assert "/api/v1/dashboard" in body
        finally:
            await client.close()
