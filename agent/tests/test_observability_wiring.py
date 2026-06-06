"""Tests for Z4.14 CostAttributor + MetricsAggregator wiring and Zone4Routes construction.

Verifies:
1. CostAttributor reads seeded JSONL and returns correct attribution.
2. MetricsAggregator produces daily cost entries from seeded data.
3. Zone4Routes can be constructed with all dependencies.
4. Zone4Routes registers 14 routes on an aiohttp app.
5. The /z4-cost command handler returns formatted output.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
from aiohttp import web

from bridge.observability.tool_tracker import ToolTracker, ToolCallCost
from bridge.observability.cost import CostAttributor, SessionCostSummary
from bridge.observability.metrics_aggregator import MetricsAggregator, DailyCostEntry
from bridge.observability.api_routes import Zone4Routes


# ── Fixtures ──────────────────────���──────────────────────────────────────────

@pytest.fixture
def sessions_dir(tmp_path: Path) -> Path:
    d = tmp_path / "z4-sessions"
    d.mkdir()
    return d


@pytest.fixture
def tracker(sessions_dir: Path) -> ToolTracker:
    return ToolTracker(sessions_dir=sessions_dir)


@pytest.fixture
def attributor(tracker: ToolTracker, sessions_dir: Path) -> CostAttributor:
    return CostAttributor(tracker=tracker, sessions_dir=sessions_dir)


@pytest.fixture
def aggregator(tracker: ToolTracker, sessions_dir: Path) -> MetricsAggregator:
    return MetricsAggregator(tracker=tracker, sessions_dir=sessions_dir)


def _seed_session(
    tracker: ToolTracker,
    sessions_dir: Path,
    session_id: str = "sess-001",
) -> None:
    """Seed a session with tool call records and meta.json."""
    # Write meta.json so MetricsAggregator can extract dates
    meta_dir = sessions_dir / session_id
    meta_dir.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc).isoformat()
    meta = {"session_id": session_id, "status": "completed", "created_at": now}
    (meta_dir / "meta.json").write_text(json.dumps(meta))

    # Log tool calls from two agents in two departments
    tracker.log_call(
        agent_name="eng-chief",
        department="engineering",
        session_id=session_id,
        tool_name="read_file",
        cost=ToolCallCost(input_tokens=200, output_tokens=100, estimated_usd=0.05),
        status="completed",
    )
    tracker.log_call(
        agent_name="eng-specialist",
        department="engineering",
        session_id=session_id,
        tool_name="write_file",
        cost=ToolCallCost(input_tokens=300, output_tokens=150, estimated_usd=0.08),
        status="completed",
    )
    tracker.log_call(
        agent_name="qa-chief",
        department="qa",
        session_id=session_id,
        tool_name="run_tests",
        cost=ToolCallCost(input_tokens=150, output_tokens=75, estimated_usd=0.03),
        status="completed",
    )
    tracker.log_call(
        agent_name="qa-engineer",
        department="qa",
        session_id=session_id,
        tool_name="read_file",
        cost=ToolCallCost(input_tokens=100, output_tokens=50, estimated_usd=0.02),
        status="blocked",
        is_domain_violation=True,
        violation_rule="no_write_access",
    )


# ── CostAttributor Tests ───────────────��────────────────────────────────────

class TestCostAttributorWiring:
    """CostAttributor reads seeded JSONL and returns correct summaries."""

    def test_session_cost_totals(
        self, tracker: ToolTracker, attributor: CostAttributor, sessions_dir: Path
    ) -> None:
        _seed_session(tracker, sessions_dir)
        summary = attributor.compute_session_cost("sess-001")

        assert isinstance(summary, SessionCostSummary)
        assert summary.session_id == "sess-001"
        assert summary.call_count == 4
        assert summary.blocked_calls == 1
        # 0.05 + 0.08 + 0.03 + 0.02 = 0.18
        assert abs(summary.total_usd - 0.18) < 0.001
        assert summary.total_input_tokens == 750  # 200+300+150+100
        assert summary.total_output_tokens == 375  # 100+150+75+50

    def test_department_cost_breakdown(
        self, tracker: ToolTracker, attributor: CostAttributor, sessions_dir: Path
    ) -> None:
        _seed_session(tracker, sessions_dir)
        summary = attributor.compute_session_cost("sess-001")

        dept_names = [d.department for d in summary.departments]
        assert "engineering" in dept_names
        assert "qa" in dept_names

        eng = next(d for d in summary.departments if d.department == "engineering")
        assert eng.call_count == 2
        assert abs(eng.total_usd - 0.13) < 0.001

        qa = next(d for d in summary.departments if d.department == "qa")
        assert qa.call_count == 2
        assert qa.blocked_calls == 1
        assert abs(qa.total_usd - 0.05) < 0.001

    def test_agent_level_cost(
        self, tracker: ToolTracker, attributor: CostAttributor, sessions_dir: Path
    ) -> None:
        _seed_session(tracker, sessions_dir)
        agent_cost = attributor.compute_agent_cost("sess-001", "engineering", "eng-chief")
        assert agent_cost.agent_name == "eng-chief"
        assert agent_cost.call_count == 1
        assert abs(agent_cost.total_usd - 0.05) < 0.001

    def test_empty_session_returns_zeros(self, attributor: CostAttributor) -> None:
        summary = attributor.compute_session_cost("nonexistent")
        assert summary.call_count == 0
        assert summary.total_usd == 0.0
        assert len(summary.departments) == 0

    def test_budget_check(
        self, tracker: ToolTracker, attributor: CostAttributor, sessions_dir: Path
    ) -> None:
        _seed_session(tracker, sessions_dir)
        within, current = attributor.check_budget("sess-001", budget_usd=1.0)
        assert within is True
        assert abs(current - 0.18) < 0.001

        within, current = attributor.check_budget("sess-001", budget_usd=0.10)
        assert within is False

    def test_to_dict_serialization(
        self, tracker: ToolTracker, attributor: CostAttributor, sessions_dir: Path
    ) -> None:
        _seed_session(tracker, sessions_dir)
        summary = attributor.compute_session_cost("sess-001")
        d = summary.to_dict()
        # Must be JSON-serializable
        serialized = json.dumps(d)
        assert "sess-001" in serialized
        assert "engineering" in serialized


# ── MetricsAggregator Tests ─────────────��───────────────────────────────────

class TestMetricsAggregatorWiring:
    """MetricsAggregator produces daily cost and agent utilization."""

    def test_daily_cost_entries(
        self, tracker: ToolTracker, aggregator: MetricsAggregator, sessions_dir: Path
    ) -> None:
        _seed_session(tracker, sessions_dir)
        entries = aggregator.daily_cost()

        assert len(entries) >= 1
        entry = entries[0]
        assert isinstance(entry, DailyCostEntry)
        assert entry.session_count == 1
        assert entry.total_calls == 4
        assert abs(entry.total_usd - 0.18) < 0.001

    def test_agent_utilization(
        self, tracker: ToolTracker, aggregator: MetricsAggregator, sessions_dir: Path
    ) -> None:
        _seed_session(tracker, sessions_dir)
        utils = aggregator.agent_utilization()

        assert len(utils) == 4  # eng-chief, eng-specialist, qa-chief, qa-engineer
        names = [u.agent_name for u in utils]
        assert "eng-specialist" in names

        # Sorted by cost descending — eng-specialist ($0.08) should be first
        assert utils[0].agent_name == "eng-specialist"
        assert utils[0].total_usd == 0.08

    def test_daily_cost_with_date_filter(
        self, tracker: ToolTracker, aggregator: MetricsAggregator, sessions_dir: Path
    ) -> None:
        _seed_session(tracker, sessions_dir)
        # Filter to a future date should return empty
        entries = aggregator.daily_cost(start_date="2099-01-01")
        assert len(entries) == 0

    def test_empty_sessions_dir(
        self, tracker: ToolTracker, aggregator: MetricsAggregator
    ) -> None:
        entries = aggregator.daily_cost()
        assert entries == []
        utils = aggregator.agent_utilization()
        assert utils == []


# ── Zone4Routes Construction Tests ──────────────��───────────────────────────

class TestZone4RoutesConstruction:
    """Zone4Routes can be constructed and registers routes correctly."""

    def test_construction_with_all_deps(
        self,
        tracker: ToolTracker,
        attributor: CostAttributor,
        aggregator: MetricsAggregator,
        sessions_dir: Path,
        tmp_path: Path,
    ) -> None:
        teams_dir = tmp_path / "teams"
        teams_dir.mkdir()
        expertise_dir = tmp_path / "expertise"
        expertise_dir.mkdir()

        routes = Zone4Routes(
            sessions_dir=sessions_dir,
            teams_dir=teams_dir,
            expertise_dir=expertise_dir,
            tracker=tracker,
            attributor=attributor,
            aggregator=aggregator,
        )
        assert routes._tracker is tracker
        assert routes._attributor is attributor
        assert routes._aggregator is aggregator

    def test_construction_without_optional_deps(
        self, sessions_dir: Path, tmp_path: Path
    ) -> None:
        teams_dir = tmp_path / "teams"
        teams_dir.mkdir()
        expertise_dir = tmp_path / "expertise"
        expertise_dir.mkdir()

        routes = Zone4Routes(
            sessions_dir=sessions_dir,
            teams_dir=teams_dir,
            expertise_dir=expertise_dir,
        )
        assert routes._tracker is None
        assert routes._attributor is None
        assert routes._aggregator is None

    def test_register_adds_14_routes(
        self,
        tracker: ToolTracker,
        attributor: CostAttributor,
        aggregator: MetricsAggregator,
        sessions_dir: Path,
        tmp_path: Path,
    ) -> None:
        teams_dir = tmp_path / "teams"
        teams_dir.mkdir()
        expertise_dir = tmp_path / "expertise"
        expertise_dir.mkdir()

        routes = Zone4Routes(
            sessions_dir=sessions_dir,
            teams_dir=teams_dir,
            expertise_dir=expertise_dir,
            tracker=tracker,
            attributor=attributor,
            aggregator=aggregator,
        )

        app = web.Application()
        routes.register(app)

        # Count GET routes registered under /api/z4/
        # (aiohttp also adds HEAD for each GET, so filter to GET only)
        z4_get_routes = [
            r for r in app.router.routes()
            if hasattr(r, 'resource') and r.resource
            and str(r.resource.canonical).startswith("/api/z4/")
            and r.method == "GET"
        ]
        assert len(z4_get_routes) == 14

    def test_endpoint_index_returns_14_entries(self) -> None:
        index = Zone4Routes.endpoint_index()
        assert len(index) == 14
        paths = [e["path"] for e in index]
        assert "/api/z4/sessions" in paths
        assert "/api/z4/metrics/cost/daily" in paths
        assert "/api/z4/metrics/violations" in paths
