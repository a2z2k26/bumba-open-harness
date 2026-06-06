"""Tests for the GET /api/zone4/report endpoint (Z4-23 #2449).

Exercises the route registered by ``_Zone4ReportsRoutesMixin``: window
parsing, the report shape, the empty-data case, and a 400 on a bad window
spec. The report data-loader itself is unit-tested in
``test_zone4_reports.py``; here we test the HTTP seam.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from bridge.api_server import (
    APIServer,
    cors_middleware,
    create_auth_middleware,
)

pytestmark = pytest.mark.socket

API_TOKEN = "test-token-z4-report"


def _write_manifest(root: Path, run_id: str, department: str, completed_at: datetime):
    run_dir = root / run_id
    run_dir.mkdir(parents=True)
    payload = {
        "schema_version": 1,
        "run_id": run_id,
        "session_id": f"cs-{run_id}",
        "department": department,
        "directive_id": None,
        "started_at_utc": completed_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "completed_at_utc": completed_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "chief": f"{department}-chief",
        "status": "success",
        "artifacts": [
            {"path": "out.md", "kind": "result", "agent": "x",
             "bytes": 100, "sha256": "ab"},
        ],
        "surfaces": ["surface-0"],
        "telemetry": {
            "primary_model": "anthropic:claude-opus-4-6",
            "input_tokens": "100",
            "output_tokens": "50",
            "request_count": "3",
            "duration_seconds": "10.0",
        },
        "project_root": None,
    }
    (run_dir / "manifest.json").write_text(
        json.dumps(payload) + "\n", encoding="utf-8"
    )


def _make_bridge(artifact_root: str | None):
    bridge = MagicMock()
    bridge._config = MagicMock()
    bridge._config.data_dir = "/tmp/test-data"
    bridge._config.operator_discord_id = "test-op"
    bridge._config.zone4_artifact_root = artifact_root
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
    return bridge


async def _client(bridge):
    server = APIServer(bridge, api_token=API_TOKEN)
    app = web.Application(
        middlewares=[cors_middleware, create_auth_middleware(server._api_token)]
    )
    server._register_routes(app)
    client = TestClient(TestServer(app))
    await client.start_server()
    return client


def _auth():
    return {"Authorization": f"Bearer {API_TOKEN}"}


@pytest.mark.asyncio
class TestZone4ReportRoute:
    async def test_empty_when_no_root_configured(self):
        bridge = _make_bridge(artifact_root=None)
        client = await _client(bridge)
        try:
            resp = await client.get("/api/zone4/report", headers=_auth())
            assert resp.status == 200
            data = await resp.json()
            assert data["total_runs"] == 0
            assert data["departments"] == []
        finally:
            await client.close()

    async def test_report_with_runs(self, tmp_path):
        now = datetime.now(timezone.utc)
        _write_manifest(tmp_path, "run-a", "strategy", now - timedelta(hours=1))
        _write_manifest(tmp_path, "run-b", "qa", now - timedelta(hours=2))
        bridge = _make_bridge(artifact_root=str(tmp_path))
        client = await _client(bridge)
        try:
            resp = await client.get(
                "/api/zone4/report?window=24h", headers=_auth()
            )
            assert resp.status == 200
            data = await resp.json()
            assert data["window"] == "24h"
            assert data["total_runs"] == 2
            depts = {d["department"] for d in data["departments"]}
            assert depts == {"strategy", "qa"}
            strategy = next(
                d for d in data["departments"] if d["department"] == "strategy"
            )
            assert strategy["providers"]["anthropic"] == 1
            assert strategy["input_tokens"] == 100
            assert strategy["manifest_paths"]  # links back to manifests
        finally:
            await client.close()

    async def test_bad_window_returns_400(self, tmp_path):
        bridge = _make_bridge(artifact_root=str(tmp_path))
        client = await _client(bridge)
        try:
            resp = await client.get(
                "/api/zone4/report?window=99z", headers=_auth()
            )
            assert resp.status == 400
        finally:
            await client.close()

    async def test_explicit_since_until(self, tmp_path):
        now = datetime.now(timezone.utc)
        _write_manifest(tmp_path, "run-old", "ops", now - timedelta(days=10))
        bridge = _make_bridge(artifact_root=str(tmp_path))
        client = await _client(bridge)
        try:
            since = (now - timedelta(days=30)).strftime("%Y-%m-%dT%H:%M:%SZ")
            until = now.strftime("%Y-%m-%dT%H:%M:%SZ")
            resp = await client.get(
                f"/api/zone4/report?since={since}&until={until}",
                headers=_auth(),
            )
            assert resp.status == 200
            data = await resp.json()
            assert data["total_runs"] == 1
        finally:
            await client.close()
