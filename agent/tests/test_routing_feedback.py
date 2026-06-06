"""Tests for MS4.4: Negative-Feedback Routing."""

from __future__ import annotations

import threading

import pytest

from bridge.routing_feedback import (
    RoutingFeedbackEngine,
    WEIGHT_HEALTHY,
    WEIGHT_DEGRADED,
    WEIGHT_UNHEALTHY,
    RECOVERY_CONSECUTIVE,
)


@pytest.fixture
def engine(tmp_path):
    return RoutingFeedbackEngine(tmp_path / "routing.db")


# ── Tool Tracking ──

class TestToolTracking:
    def test_record_success(self, engine):
        engine.record_tool_use("brave-search", success=True, latency_ms=100)
        th = engine.get_tool_health("brave-search")
        assert th.invocations == 1
        assert th.success_rate == 1.0

    def test_record_failure(self, engine):
        engine.record_tool_use("brave-search", success=False, latency_ms=5000)
        th = engine.get_tool_health("brave-search")
        assert th.invocations == 1
        assert th.success_rate == 0.0

    def test_mixed_results(self, engine):
        for i in range(8):
            engine.record_tool_use("tool", success=True, latency_ms=50)
        for i in range(2):
            engine.record_tool_use("tool", success=False, latency_ms=50)
        th = engine.get_tool_health("tool")
        assert th.invocations == 10
        assert abs(th.success_rate - 0.8) < 0.01

    def test_avg_latency(self, engine):
        engine.record_tool_use("tool", success=True, latency_ms=100)
        engine.record_tool_use("tool", success=True, latency_ms=200)
        th = engine.get_tool_health("tool")
        assert abs(th.avg_latency_ms - 150.0) < 0.01

    def test_unknown_tool_default(self, engine):
        th = engine.get_tool_health("nonexistent")
        assert th.invocations == 0
        assert th.status == "healthy"
        assert th.weight == WEIGHT_HEALTHY


# ── Tool Health Status ──

class TestToolHealth:
    def test_healthy(self, engine):
        for _ in range(10):
            engine.record_tool_use("tool", success=True)
        assert engine.get_tool_health("tool").status == "healthy"

    def test_degraded(self, engine):
        for _ in range(5):
            engine.record_tool_use("tool", success=True)
        for _ in range(5):
            engine.record_tool_use("tool", success=False)
        th = engine.get_tool_health("tool")
        assert th.status == "degraded"
        assert th.weight == WEIGHT_DEGRADED

    def test_unhealthy(self, engine):
        for _ in range(2):
            engine.record_tool_use("tool", success=True)
        for _ in range(8):
            engine.record_tool_use("tool", success=False)
        th = engine.get_tool_health("tool")
        assert th.status == "unhealthy"
        assert th.weight == WEIGHT_UNHEALTHY


# ── Tool Weight ──

class TestToolWeight:
    def test_weight_healthy(self, engine):
        for _ in range(10):
            engine.record_tool_use("tool", success=True)
        assert engine.get_tool_weight("tool") == WEIGHT_HEALTHY

    def test_weight_unhealthy(self, engine):
        for _ in range(10):
            engine.record_tool_use("tool", success=False)
        assert engine.get_tool_weight("tool") == WEIGHT_UNHEALTHY


# ── Recovery Detection ──

class TestRecovery:
    def test_recovery_after_consecutive_successes(self, engine):
        # Make tool unhealthy
        for _ in range(10):
            engine.record_tool_use("tool", success=False)
        assert engine.get_tool_health("tool").status == "unhealthy"
        # Recover
        for _ in range(RECOVERY_CONSECUTIVE):
            engine.record_tool_use("tool", success=True)
        assert engine.is_recovered("tool") is True

    def test_no_recovery_insufficient(self, engine):
        for _ in range(10):
            engine.record_tool_use("tool", success=False)
        for _ in range(RECOVERY_CONSECUTIVE - 1):
            engine.record_tool_use("tool", success=True)
        assert engine.is_recovered("tool") is False

    def test_consecutive_reset_on_failure(self, engine):
        for _ in range(4):
            engine.record_tool_use("tool", success=True)
        engine.record_tool_use("tool", success=False)
        th = engine.get_tool_health("tool")
        assert th.consecutive_successes == 0


# ── Model Tracking ──

class TestModelTracking:
    def test_record_model_success(self, engine):
        engine.record_model_use("haiku", "search", success=True)
        perf = engine.get_model_performance("haiku", "search")
        assert perf.attempts == 1
        assert perf.successes == 1

    def test_record_model_failure(self, engine):
        engine.record_model_use("haiku", "search", success=False, retry_needed=True)
        perf = engine.get_model_performance("haiku", "search")
        assert perf.attempts == 1
        assert perf.successes == 0
        assert perf.retries == 1

    def test_unknown_model_default(self, engine):
        perf = engine.get_model_performance("haiku", "unknown")
        assert perf.attempts == 0
        assert perf.success_rate == 1.0


# ── Model Escalation ──

class TestModelEscalation:
    def test_escalation_trigger(self, engine):
        # Record 75% failure rate (> 20% threshold)
        for i in range(8):
            engine.record_model_use("haiku", "code_review", success=(i < 2))
        result = engine.check_escalation("haiku", "code_review")
        assert result == "sonnet"

    def test_no_escalation_below_threshold(self, engine):
        # 10% failure rate (< 20%)
        for i in range(10):
            engine.record_model_use("haiku", "search", success=(i < 9))
        result = engine.check_escalation("haiku", "search")
        assert result is None

    def test_no_escalation_insufficient_data(self, engine):
        engine.record_model_use("haiku", "search", success=False)
        result = engine.check_escalation("haiku", "search")
        assert result is None

    def test_opus_cannot_escalate(self, engine):
        for i in range(10):
            engine.record_model_use("opus", "search", success=False)
        result = engine.check_escalation("opus", "search")
        assert result is None

    def test_escalation_cooldown(self, engine):
        for i in range(10):
            engine.record_model_use("haiku", "search", success=(i < 2))
        engine.check_escalation("haiku", "search")
        # Second check within cooldown returns cached escalation
        result = engine.check_escalation("haiku", "search")
        assert result == "sonnet"


# ── Routing Report ──

class TestRoutingReport:
    def test_report_format(self, engine):
        engine.record_tool_use("brave-search", success=True, latency_ms=100)
        engine.record_tool_use("playwright", success=False, latency_ms=5000)
        report = engine.format_routing_report()
        assert "Tool Health" in report
        assert "brave-search" in report
        assert "playwright" in report
        assert "Active Escalations" in report

    def test_report_no_escalations(self, engine):
        report = engine.format_routing_report()
        assert "No active escalations" in report


# ── All Tools ──

class TestAllToolHealth:
    def test_list_all_tools(self, engine):
        engine.record_tool_use("alpha", success=True)
        engine.record_tool_use("beta", success=False)
        all_health = engine.get_all_tool_health()
        names = [h.name for h in all_health]
        assert "alpha" in names
        assert "beta" in names


# ── Concurrent Access ──

class TestConcurrentTracking:
    def test_concurrent_tool_tracking(self, engine):
        errors = []

        def worker(tid: int):
            try:
                for i in range(20):
                    engine.record_tool_use("shared-tool", success=(i % 2 == 0), latency_ms=10)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker, args=(t,)) for t in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
        th = engine.get_tool_health("shared-tool")
        assert th.invocations == 100  # 5 threads * 20 each
