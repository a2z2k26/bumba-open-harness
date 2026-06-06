"""Tests for teams._types module."""

from __future__ import annotations

import pytest

from tests.test_teams.conftest import make_deps
from teams._types import (
    TeamResult,
    DepartmentConfig,
    AgentSpec,
    Budget,
    Constraints,
)


class TestBridgeDeps:
    def test_frozen(self):
        deps = make_deps(session_id="test-123", department="qa")
        with pytest.raises((AttributeError, Exception)):
            deps.session_id = "mutated"

    def test_cost_limit_default(self):
        """cost_limit_usd retains its 2.0 default when not overridden."""
        deps = make_deps(session_id="s", department="qa")
        assert deps.cost_limit_usd == 2.0
        assert deps.operator_id == "op-test"  # make_deps default


class TestTeamResult:
    def test_success_default(self):
        result = TeamResult(
            department="qa",
            manager_output="done",
        )
        assert result.success is True
        assert result.error is None
        assert result.employee_results == ()

    def test_failure(self):
        result = TeamResult(
            department="qa",
            manager_output="",
            success=False,
            error="timeout",
        )
        assert result.success is False
        assert result.error == "timeout"


class TestConstraints:
    def test_defaults(self):
        c = Constraints()
        assert c.cost_limit_usd == 2.0
        assert c.timeout_seconds == 600
        assert c.concurrency_limit == 4


class TestBudget:
    def test_defaults(self):
        b = Budget()
        assert b.daily_limit_usd == 5.0
        assert b.alert_thresholds == (0.5, 0.75, 0.9)


class TestAgentSpec:
    def test_frozen(self):
        spec = AgentSpec(
            name="qa-chief",
            model="anthropic:claude-opus-4-6",
            role="QA team orchestrator",
            system_prompt_path="config/agents/zone4/qa/qa-chief.md",
        )
        assert spec.name == "qa-chief"
        assert spec.retries == 1


class TestDepartmentConfig:
    def test_minimal(self):
        cfg = DepartmentConfig(
            name="qa",
            zone=4,
            description="QA department",
            manager=AgentSpec(name="qa-chief", model="anthropic:claude-opus-4-6"),
            employees=(),
        )
        assert cfg.name == "qa"
        assert len(cfg.employees) == 0
