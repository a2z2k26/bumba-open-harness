"""Tests for bridge/observability/api_routes.py — Zone 4 Sprint 11

Tests the route handlers directly by creating an aiohttp TestServer manually,
without requiring pytest-aiohttp.
"""

import json
import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer, TestClient

from bridge.observability.api_routes import Zone4Routes, Z4_EVENT_TYPES
from bridge.observability.tool_tracker import ToolTracker, ToolCallCost
from bridge.observability.cost import CostAttributor
from bridge.observability.metrics_aggregator import MetricsAggregator

pytestmark = pytest.mark.socket  # binds localhost sockets via aiohttp TestServer


# ── Helpers ───────────────────────────────────────────────────────────────────

def _log(tracker, agent, dept, sid, tool, usd=0.01, status="completed",
         violation=False, rule=""):
    tracker.log_call(
        agent_name=agent,
        department=dept,
        session_id=sid,
        tool_name=tool,
        cost=ToolCallCost(input_tokens=100, output_tokens=50, estimated_usd=usd),
        status=status,
        is_domain_violation=violation,
        violation_rule=rule,
    )


def _write_meta(sessions_dir, sid, **kwargs):
    meta_dir = sessions_dir / sid
    meta_dir.mkdir(parents=True, exist_ok=True)
    meta = {"session_id": sid, "team": "qa", "status": "completed"}
    meta.update(kwargs)
    (meta_dir / "meta.json").write_text(json.dumps(meta))


def _write_conversation(sessions_dir, sid, dept, messages):
    conv_dir = sessions_dir / sid / dept
    conv_dir.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps(m) for m in messages]
    (conv_dir / "conversation.jsonl").write_text("\n".join(lines))


def _write_team_yaml(teams_dir, name):
    (teams_dir / f"{name}.yaml").write_text(f"name: {name}\nchief: {name}-chief\n")


def _write_expertise(expertise_dir, agent_name, content="# Expert"):
    (expertise_dir / f"{agent_name}.md").write_text(content)


def _write_board_file(sessions_dir, sid, kind, content):
    board_dir = sessions_dir / sid / "board"
    board_dir.mkdir(parents=True, exist_ok=True)
    (board_dir / f"board-{kind}.md").write_text(content)


@pytest.fixture
def dirs(tmp_path):
    sessions = tmp_path / "sessions"
    teams = tmp_path / "teams"
    expertise = tmp_path / "expertise"
    sessions.mkdir()
    teams.mkdir()
    expertise.mkdir()
    return sessions, teams, expertise


@pytest.fixture
def tracker(dirs):
    return ToolTracker(dirs[0])


@pytest.fixture
def attributor(tracker, dirs):
    return CostAttributor(tracker, dirs[0])


@pytest.fixture
def aggregator(tracker, dirs):
    return MetricsAggregator(tracker, dirs[0])


@pytest.fixture
def routes(dirs, tracker, attributor, aggregator):
    sessions, teams, expertise = dirs
    return Zone4Routes(
        sessions_dir=sessions,
        teams_dir=teams,
        expertise_dir=expertise,
        tracker=tracker,
        attributor=attributor,
        aggregator=aggregator,
    )


@pytest.fixture
async def client(routes):
    app = web.Application()
    routes.register(app)
    server = TestServer(app)
    c = TestClient(server)
    await c.start_server()
    yield c
    await c.close()


# ── Event types ───────────────────────────────────────────────────────────────

class TestZ4EventTypes:
    def test_event_types_defined(self):
        assert len(Z4_EVENT_TYPES) == 12

    def test_all_prefixed(self):
        for et in Z4_EVENT_TYPES:
            assert et.startswith("z4.")

    def test_key_events_present(self):
        assert "z4.session.created" in Z4_EVENT_TYPES
        assert "z4.domain_violation" in Z4_EVENT_TYPES
        assert "z4.budget.exceeded" in Z4_EVENT_TYPES


# ── Endpoint index ────────────────────────────────────────────────────────────

class TestEndpointIndex:
    def test_returns_14_endpoints(self):
        idx = Zone4Routes.endpoint_index()
        assert len(idx) == 14

    def test_all_paths_prefixed(self):
        for ep in Zone4Routes.endpoint_index():
            assert ep["path"].startswith("/api/z4/")


# ── Sessions ──────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_list_sessions_empty(client):
    resp = await client.get("/api/z4/sessions")
    assert resp.status == 200
    data = await resp.json()
    assert data["total"] == 0


@pytest.mark.asyncio
async def test_list_sessions_with_data(client, dirs):
    sessions_dir = dirs[0]
    _write_meta(sessions_dir, "ses1", status="completed")
    _write_meta(sessions_dir, "ses2", status="active")
    resp = await client.get("/api/z4/sessions")
    data = await resp.json()
    assert data["total"] == 2


@pytest.mark.asyncio
async def test_list_sessions_pagination(client, dirs):
    sessions_dir = dirs[0]
    for i in range(5):
        _write_meta(sessions_dir, f"ses{i}")
    resp = await client.get("/api/z4/sessions?offset=2&limit=2")
    data = await resp.json()
    assert data["total"] == 5
    assert len(data["sessions"]) == 2
    assert data["offset"] == 2


@pytest.mark.asyncio
async def test_list_sessions_filter_status(client, dirs):
    sessions_dir = dirs[0]
    _write_meta(sessions_dir, "ses1", status="completed")
    _write_meta(sessions_dir, "ses2", status="active")
    resp = await client.get("/api/z4/sessions?status=completed")
    data = await resp.json()
    assert data["total"] == 1


@pytest.mark.asyncio
async def test_session_detail(client, dirs):
    sessions_dir = dirs[0]
    _write_meta(sessions_dir, "ses1", team="qa")
    resp = await client.get("/api/z4/sessions/ses1")
    assert resp.status == 200
    data = await resp.json()
    assert data["session_id"] == "ses1"


@pytest.mark.asyncio
async def test_session_detail_not_found(client):
    resp = await client.get("/api/z4/sessions/nonexistent")
    assert resp.status == 404


@pytest.mark.asyncio
async def test_session_cost(client, dirs, tracker):
    sessions_dir = dirs[0]
    _write_meta(sessions_dir, "ses1")
    _log(tracker, "qa-chief", "qa", "ses1", "Read", usd=0.05)
    resp = await client.get("/api/z4/sessions/ses1/cost")
    assert resp.status == 200
    data = await resp.json()
    assert abs(data["total_usd"] - 0.05) < 1e-9


@pytest.mark.asyncio
async def test_session_cost_not_found(client):
    resp = await client.get("/api/z4/sessions/nope/cost")
    assert resp.status == 404


# ── Conversation ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_conversation_returns_messages(client, dirs):
    sessions_dir = dirs[0]
    msgs = [
        {"type": "delegation", "from": "qa-chief", "content": "review X"},
        {"type": "result", "from": "qa-engineer", "content": "passed"},
    ]
    _write_conversation(sessions_dir, "ses1", "qa", msgs)
    resp = await client.get(
        "/api/z4/sessions/ses1/departments/qa/conversation"
    )
    assert resp.status == 200
    data = await resp.json()
    assert len(data["messages"]) == 2


@pytest.mark.asyncio
async def test_conversation_not_found(client):
    resp = await client.get(
        "/api/z4/sessions/ses1/departments/qa/conversation"
    )
    assert resp.status == 404


# ── Agent tools ───────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_agent_tools(client, tracker):
    _log(tracker, "qa-chief", "qa", "ses1", "Read")
    _log(tracker, "qa-chief", "qa", "ses1", "Glob")
    resp = await client.get(
        "/api/z4/sessions/ses1/departments/qa/tools/qa-chief"
    )
    assert resp.status == 200
    data = await resp.json()
    assert data["count"] == 2
    assert data["agent"] == "qa-chief"


@pytest.mark.asyncio
async def test_agent_tools_empty(client):
    resp = await client.get(
        "/api/z4/sessions/ses1/departments/qa/tools/nobody"
    )
    assert resp.status == 200
    data = await resp.json()
    assert data["count"] == 0


# ── Departments ───────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_list_departments(client, dirs):
    teams_dir = dirs[1]
    _write_team_yaml(teams_dir, "qa")
    _write_team_yaml(teams_dir, "ops")
    resp = await client.get("/api/z4/departments")
    data = await resp.json()
    assert data["count"] == 2


@pytest.mark.asyncio
async def test_department_health(client, dirs, tracker):
    sessions_dir, teams_dir, _ = dirs
    _write_team_yaml(teams_dir, "qa")
    _write_meta(sessions_dir, "ses1")
    _log(tracker, "qa-chief", "qa", "ses1", "Read")
    _log(tracker, "qa-chief", "qa", "ses1", "Write", violation=True,
         rule="denied", status="blocked")
    resp = await client.get("/api/z4/departments/qa/health")
    data = await resp.json()
    assert data["configured"] is True
    assert data["total_calls"] == 2
    assert data["domain_violations"] == 1


@pytest.mark.asyncio
async def test_department_health_not_found(client):
    resp = await client.get("/api/z4/departments/fake/health")
    assert resp.status == 404


# ── Agents ────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_list_agents(client, dirs):
    expertise_dir = dirs[2]
    _write_expertise(expertise_dir, "qa-chief")
    _write_expertise(expertise_dir, "qa-engineer")
    resp = await client.get("/api/z4/agents")
    data = await resp.json()
    assert data["count"] == 2


@pytest.mark.asyncio
async def test_agent_expertise(client, dirs):
    expertise_dir = dirs[2]
    _write_expertise(expertise_dir, "qa-chief", content="# QA Chief Expertise")
    resp = await client.get("/api/z4/agents/qa-chief/expertise")
    assert resp.status == 200
    data = await resp.json()
    assert "QA Chief" in data["content"]


@pytest.mark.asyncio
async def test_agent_expertise_not_found(client):
    resp = await client.get("/api/z4/agents/nobody/expertise")
    assert resp.status == 404


# ── Board ─────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_board_briefs(client, dirs):
    sessions_dir = dirs[0]
    _write_board_file(sessions_dir, "ses1", "brief", "## Situation\nTest")
    resp = await client.get("/api/z4/board/briefs")
    data = await resp.json()
    assert data["total"] == 1
    assert "Situation" in data["briefs"][0]["content"]


@pytest.mark.asyncio
async def test_board_memos(client, dirs):
    sessions_dir = dirs[0]
    _write_board_file(sessions_dir, "ses1", "memo", "## Decision\nApproved")
    resp = await client.get("/api/z4/board/memos")
    data = await resp.json()
    assert data["total"] == 1


@pytest.mark.asyncio
async def test_board_briefs_empty(client):
    resp = await client.get("/api/z4/board/briefs")
    data = await resp.json()
    assert data["total"] == 0


# ── Metrics ───────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_daily_cost(client, dirs, tracker):
    sessions_dir = dirs[0]
    _write_meta(sessions_dir, "ses1", created_at="2026-04-01T10:00:00+00:00")
    _log(tracker, "a", "qa", "ses1", "R", usd=0.05)
    resp = await client.get("/api/z4/metrics/cost/daily")
    data = await resp.json()
    assert data["count"] == 1
    assert data["entries"][0]["date"] == "2026-04-01"


@pytest.mark.asyncio
async def test_agent_metrics(client, tracker):
    _log(tracker, "qa-chief", "qa", "ses1", "Read", usd=0.10)
    _log(tracker, "qa-engineer", "qa", "ses1", "Bash", usd=0.02)
    resp = await client.get("/api/z4/metrics/agents")
    data = await resp.json()
    assert data["count"] == 2


@pytest.mark.asyncio
async def test_violations_all_sessions(client, tracker):
    _log(tracker, "qa-chief", "qa", "ses1", "Write",
         violation=True, rule="denied", status="blocked")
    _log(tracker, "qa-chief", "qa", "ses1", "Read")
    resp = await client.get("/api/z4/metrics/violations")
    data = await resp.json()
    assert data["count"] == 1


@pytest.mark.asyncio
async def test_violations_filtered(client, tracker):
    _log(tracker, "qa-chief", "qa", "ses1", "Write",
         violation=True, rule="denied", status="blocked")
    resp = await client.get("/api/z4/metrics/violations?session_id=ses1")
    data = await resp.json()
    assert data["count"] == 1


@pytest.mark.asyncio
async def test_violations_empty(client, tracker):
    _log(tracker, "qa-chief", "qa", "ses1", "Read")
    resp = await client.get("/api/z4/metrics/violations")
    data = await resp.json()
    assert data["count"] == 0
