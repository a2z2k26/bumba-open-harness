"""Tests for bridge/observability/cost.py and metrics_aggregator.py — Zone 4 Sprint 10"""

import json
import pytest
from bridge.observability.tool_tracker import ToolTracker, ToolCallCost
from bridge.observability.cost import (
    AgentCostSummary,
    DepartmentCostSummary,
    SessionCostSummary,
    CostAttributor,
)
from bridge.observability.metrics_aggregator import (
    DailyCostEntry,
    AgentUtilization,
    MetricsAggregator,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def sessions_dir(tmp_path):
    return tmp_path / "sessions"


@pytest.fixture
def tracker(sessions_dir):
    return ToolTracker(sessions_dir)


@pytest.fixture
def attributor(tracker, sessions_dir):
    return CostAttributor(tracker, sessions_dir)


def _log(tracker, agent, dept, sid, tool, usd=0.01, status="completed",
         in_tokens=100, out_tokens=50):
    """Helper to log a tool call with cost."""
    tracker.log_call(
        agent_name=agent,
        department=dept,
        session_id=sid,
        tool_name=tool,
        cost=ToolCallCost(input_tokens=in_tokens, output_tokens=out_tokens,
                          estimated_usd=usd),
        status=status,
    )


def _write_meta(sessions_dir, session_id, created_at):
    """Helper to write meta.json with a created_at timestamp."""
    meta_dir = sessions_dir / session_id
    meta_dir.mkdir(parents=True, exist_ok=True)
    meta = {"created_at": created_at, "team": "qa"}
    (meta_dir / "meta.json").write_text(json.dumps(meta))


# ── AgentCostSummary ──────────────────────────────────────────────────────────

class TestAgentCostSummary:
    def test_frozen(self):
        s = AgentCostSummary(agent_name="a", department="d", session_id="s")
        with pytest.raises((AttributeError, TypeError)):
            s.total_usd = 99.0  # type: ignore

    def test_to_dict(self):
        s = AgentCostSummary(agent_name="a", department="d", session_id="s",
                             total_usd=0.05, call_count=3)
        d = s.to_dict()
        assert d["agent_name"] == "a"
        assert d["total_usd"] == 0.05
        assert d["call_count"] == 3


# ── DepartmentCostSummary ────────────────────────────────────────────────────

class TestDepartmentCostSummary:
    def test_frozen(self):
        s = DepartmentCostSummary(department="qa", session_id="s")
        with pytest.raises((AttributeError, TypeError)):
            s.total_usd = 1.0  # type: ignore

    def test_to_dict_includes_agents(self):
        agent = AgentCostSummary(agent_name="a", department="qa", session_id="s",
                                  total_usd=0.02)
        s = DepartmentCostSummary(department="qa", session_id="s",
                                   agents=(agent,), total_usd=0.02)
        d = s.to_dict()
        assert len(d["agents"]) == 1
        assert d["agents"][0]["agent_name"] == "a"


# ── SessionCostSummary ───────────────────────────────────────────────────────

class TestSessionCostSummary:
    def test_frozen(self):
        s = SessionCostSummary(session_id="s")
        with pytest.raises((AttributeError, TypeError)):
            s.total_usd = 1.0  # type: ignore

    def test_to_dict_includes_computed_at(self):
        s = SessionCostSummary(session_id="s")
        d = s.to_dict()
        assert "computed_at" in d
        assert d["session_id"] == "s"


# ── CostAttributor: agent level ──────────────────────────────────────────────

class TestCostAttributorAgent:
    def test_single_agent_cost(self, tracker, attributor):
        _log(tracker, "qa-chief", "qa", "ses1", "Read", usd=0.01)
        _log(tracker, "qa-chief", "qa", "ses1", "Glob", usd=0.02)

        result = attributor.compute_agent_cost("ses1", "qa", "qa-chief")
        assert result.agent_name == "qa-chief"
        assert result.call_count == 2
        assert abs(result.total_usd - 0.03) < 1e-9
        assert result.total_input_tokens == 200
        assert result.total_output_tokens == 100

    def test_blocked_calls_counted(self, tracker, attributor):
        _log(tracker, "qa-chief", "qa", "ses1", "Write", status="blocked")
        _log(tracker, "qa-chief", "qa", "ses1", "Read")

        result = attributor.compute_agent_cost("ses1", "qa", "qa-chief")
        assert result.blocked_calls == 1
        assert result.call_count == 2

    def test_empty_agent(self, tracker, attributor):
        result = attributor.compute_agent_cost("ses1", "qa", "nonexistent")
        assert result.call_count == 0
        assert result.total_usd == 0.0


# ── CostAttributor: department level ─────────────────────────────────────────

class TestCostAttributorDepartment:
    def test_department_aggregates_agents(self, tracker, attributor):
        _log(tracker, "qa-chief", "qa", "ses1", "Read", usd=0.01)
        _log(tracker, "qa-engineer", "qa", "ses1", "Bash", usd=0.02)

        result = attributor.compute_department_cost("ses1", "qa")
        assert result.department == "qa"
        assert len(result.agents) == 2
        assert abs(result.total_usd - 0.03) < 1e-9
        assert result.call_count == 2

    def test_department_agent_names_sorted(self, tracker, attributor):
        _log(tracker, "z-agent", "qa", "ses1", "Read")
        _log(tracker, "a-agent", "qa", "ses1", "Read")

        result = attributor.compute_department_cost("ses1", "qa")
        assert result.agents[0].agent_name == "a-agent"
        assert result.agents[1].agent_name == "z-agent"

    def test_empty_department(self, tracker, attributor):
        result = attributor.compute_department_cost("ses1", "empty")
        assert result.call_count == 0
        assert len(result.agents) == 0


# ── CostAttributor: session level ────────────────────────────────────────────

class TestCostAttributorSession:
    def test_session_aggregates_departments(self, tracker, attributor):
        _log(tracker, "qa-chief", "qa", "ses1", "Read", usd=0.01)
        _log(tracker, "ops-chief", "ops", "ses1", "Bash", usd=0.03)

        result = attributor.compute_session_cost("ses1")
        assert len(result.departments) == 2
        assert abs(result.total_usd - 0.04) < 1e-9
        assert result.call_count == 2

    def test_session_departments_sorted(self, tracker, attributor):
        _log(tracker, "a", "zebra", "ses1", "Read")
        _log(tracker, "a", "alpha", "ses1", "Read")

        result = attributor.compute_session_cost("ses1")
        assert result.departments[0].department == "alpha"
        assert result.departments[1].department == "zebra"

    def test_empty_session(self, tracker, attributor):
        result = attributor.compute_session_cost("nonexistent")
        assert result.call_count == 0
        assert result.total_usd == 0.0

    def test_full_hierarchy(self, tracker, attributor):
        """3 agents, 2 departments, multiple calls."""
        _log(tracker, "qa-chief", "qa", "ses1", "Read", usd=0.01)
        _log(tracker, "qa-chief", "qa", "ses1", "Glob", usd=0.01)
        _log(tracker, "qa-engineer", "qa", "ses1", "Bash", usd=0.02)
        _log(tracker, "ops-chief", "ops", "ses1", "Read", usd=0.05)

        result = attributor.compute_session_cost("ses1")
        assert result.call_count == 4
        assert abs(result.total_usd - 0.09) < 1e-9
        assert len(result.departments) == 2

        qa = next(d for d in result.departments if d.department == "qa")
        assert qa.call_count == 3
        assert len(qa.agents) == 2


# ── CostAttributor: budget check ─────────────────────────────────────────────

class TestCostBudget:
    def test_within_budget(self, tracker, attributor):
        _log(tracker, "qa-chief", "qa", "ses1", "Read", usd=0.01)
        within, cost = attributor.check_budget("ses1", 1.00)
        assert within is True
        assert abs(cost - 0.01) < 1e-9

    def test_over_budget(self, tracker, attributor):
        _log(tracker, "qa-chief", "qa", "ses1", "Read", usd=5.00)
        within, cost = attributor.check_budget("ses1", 1.00)
        assert within is False
        assert abs(cost - 5.00) < 1e-9

    def test_exactly_at_budget(self, tracker, attributor):
        _log(tracker, "qa-chief", "qa", "ses1", "Read", usd=1.00)
        within, cost = attributor.check_budget("ses1", 1.00)
        assert within is True

    def test_empty_session_within_budget(self, tracker, attributor):
        within, cost = attributor.check_budget("empty", 1.00)
        assert within is True
        assert cost == 0.0


# ── CostAttributor: write_cost_json ──────────────────────────────────────────

class TestWriteCostJson:
    def test_creates_file(self, tracker, attributor, sessions_dir):
        _log(tracker, "qa-chief", "qa", "ses1", "Read", usd=0.01)
        path = attributor.write_cost_json("ses1")
        assert path.exists()
        assert path.name == "cost.json"

    def test_valid_json(self, tracker, attributor, sessions_dir):
        _log(tracker, "qa-chief", "qa", "ses1", "Read", usd=0.05)
        path = attributor.write_cost_json("ses1")
        data = json.loads(path.read_text())
        assert data["session_id"] == "ses1"
        assert abs(data["total_usd"] - 0.05) < 1e-9
        assert "departments" in data

    def test_overwrites_on_rewrite(self, tracker, attributor, sessions_dir):
        _log(tracker, "qa-chief", "qa", "ses1", "Read", usd=0.01)
        attributor.write_cost_json("ses1")
        _log(tracker, "qa-chief", "qa", "ses1", "Glob", usd=0.02)
        path = attributor.write_cost_json("ses1")
        data = json.loads(path.read_text())
        assert abs(data["total_usd"] - 0.03) < 1e-9


# ── MetricsAggregator: daily_cost ────────────────────────────────────────────

class TestDailyCost:
    def test_daily_cost_groups_by_date(self, tracker, sessions_dir):
        _write_meta(sessions_dir, "ses1", "2026-04-01T10:00:00+00:00")
        _write_meta(sessions_dir, "ses2", "2026-04-01T14:00:00+00:00")
        _write_meta(sessions_dir, "ses3", "2026-04-02T10:00:00+00:00")
        _log(tracker, "a", "qa", "ses1", "R", usd=0.01)
        _log(tracker, "a", "qa", "ses2", "R", usd=0.02)
        _log(tracker, "a", "qa", "ses3", "R", usd=0.05)

        agg = MetricsAggregator(tracker, sessions_dir)
        result = agg.daily_cost()
        assert len(result) == 2
        assert result[0].date == "2026-04-01"
        assert abs(result[0].total_usd - 0.03) < 1e-9
        assert result[0].session_count == 2
        assert result[1].date == "2026-04-02"

    def test_daily_cost_with_date_filter(self, tracker, sessions_dir):
        _write_meta(sessions_dir, "ses1", "2026-03-30T10:00:00+00:00")
        _write_meta(sessions_dir, "ses2", "2026-04-01T10:00:00+00:00")
        _write_meta(sessions_dir, "ses3", "2026-04-03T10:00:00+00:00")
        _log(tracker, "a", "qa", "ses1", "R", usd=0.01)
        _log(tracker, "a", "qa", "ses2", "R", usd=0.02)
        _log(tracker, "a", "qa", "ses3", "R", usd=0.03)

        agg = MetricsAggregator(tracker, sessions_dir)
        result = agg.daily_cost(start_date="2026-04-01", end_date="2026-04-02")
        assert len(result) == 1
        assert result[0].date == "2026-04-01"

    def test_daily_cost_empty(self, tracker, sessions_dir):
        agg = MetricsAggregator(tracker, sessions_dir)
        assert agg.daily_cost() == []

    def test_daily_cost_no_sessions_dir(self, tmp_path):
        tracker = ToolTracker(tmp_path / "nope")
        agg = MetricsAggregator(tracker, tmp_path / "nope")
        assert agg.daily_cost() == []

    def test_daily_cost_fallback_to_mtime(self, tracker, sessions_dir):
        """When meta.json has no created_at, fall back to directory mtime."""
        sid = "ses-no-meta"
        # Log a call to create the session directory
        _log(tracker, "a", "qa", sid, "R", usd=0.01)

        agg = MetricsAggregator(tracker, sessions_dir)
        result = agg.daily_cost()
        assert len(result) == 1  # Should find one day via mtime fallback


# ── MetricsAggregator: agent_utilization ──────────────────────────────────────

class TestAgentUtilization:
    def test_agent_utilization_basic(self, tracker, sessions_dir):
        _log(tracker, "qa-chief", "qa", "ses1", "Read", usd=0.10)
        _log(tracker, "qa-chief", "qa", "ses1", "Glob", usd=0.05)
        _log(tracker, "qa-engineer", "qa", "ses1", "Bash", usd=0.02)

        agg = MetricsAggregator(tracker, sessions_dir)
        result = agg.agent_utilization()
        assert len(result) == 2
        # Sorted by cost desc — qa-chief first
        assert result[0].agent_name == "qa-chief"
        assert result[0].total_calls == 2
        assert abs(result[0].total_usd - 0.15) < 1e-9

    def test_agent_utilization_across_sessions(self, tracker, sessions_dir):
        _log(tracker, "qa-chief", "qa", "ses1", "Read", usd=0.10)
        _log(tracker, "qa-chief", "qa", "ses2", "Read", usd=0.10)

        agg = MetricsAggregator(tracker, sessions_dir)
        result = agg.agent_utilization()
        assert len(result) == 1
        assert result[0].session_count == 2
        assert result[0].avg_cost_per_session == 0.1

    def test_blocked_calls_tracked(self, tracker, sessions_dir):
        _log(tracker, "qa-chief", "qa", "ses1", "Write", status="blocked")
        _log(tracker, "qa-chief", "qa", "ses1", "Read")

        agg = MetricsAggregator(tracker, sessions_dir)
        result = agg.agent_utilization()
        assert result[0].blocked_calls == 1
        assert result[0].total_calls == 2

    def test_empty_utilization(self, tracker, sessions_dir):
        agg = MetricsAggregator(tracker, sessions_dir)
        assert agg.agent_utilization() == []

    def test_sorted_by_cost_descending(self, tracker, sessions_dir):
        _log(tracker, "cheap", "qa", "ses1", "R", usd=0.01)
        _log(tracker, "expensive", "qa", "ses1", "R", usd=1.00)
        _log(tracker, "medium", "qa", "ses1", "R", usd=0.10)

        agg = MetricsAggregator(tracker, sessions_dir)
        result = agg.agent_utilization()
        costs = [r.total_usd for r in result]
        assert costs == sorted(costs, reverse=True)


# ── DailyCostEntry / AgentUtilization dataclass checks ────────────────────────

class TestDataModels:
    def test_daily_cost_entry_frozen(self):
        e = DailyCostEntry(date="2026-04-01", total_usd=0.05)
        with pytest.raises((AttributeError, TypeError)):
            e.total_usd = 1.0  # type: ignore

    def test_agent_utilization_frozen(self):
        a = AgentUtilization(agent_name="a")
        with pytest.raises((AttributeError, TypeError)):
            a.session_count = 99  # type: ignore

    def test_daily_cost_entry_to_dict(self):
        e = DailyCostEntry(date="2026-04-01", total_usd=0.05, session_count=2)
        d = e.to_dict()
        assert d["date"] == "2026-04-01"
        assert d["session_count"] == 2

    def test_agent_utilization_to_dict(self):
        a = AgentUtilization(agent_name="qa-chief", total_calls=5, total_usd=0.25)
        d = a.to_dict()
        assert d["agent_name"] == "qa-chief"
        assert d["total_usd"] == 0.25
