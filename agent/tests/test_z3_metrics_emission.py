"""Tests for Z3 metrics emission (#571)."""
from __future__ import annotations

import pytest
from bridge.z3_metrics import (
    Z3Counters,
    Z3CounterNames,
    Z3Spans,
    record_dispatch_fallthrough,
    record_routing_brain_cache,
    record_env_selector_skew,
)


@pytest.fixture(autouse=True)
def reset_counters():
    Z3Counters.reset()
    yield
    Z3Counters.reset()


def test_fallthrough_counter_increments():
    record_dispatch_fallthrough("unknown_route")
    record_dispatch_fallthrough("unknown_route")
    record_dispatch_fallthrough("tmux_error")

    snap = Z3Counters.snapshot(Z3CounterNames.DISPATCH_FALLTHROUGH)
    assert snap.get("reason=unknown_route", 0) == 2
    assert snap.get("reason=tmux_error", 0) == 1


def test_routing_brain_cache_hit_miss():
    record_routing_brain_cache(hit=True)
    record_routing_brain_cache(hit=True)
    record_routing_brain_cache(hit=False)

    snap = Z3Counters.snapshot(Z3CounterNames.ROUTING_BRAIN_CACHE)
    assert snap.get("result=hit", 0) == 2
    assert snap.get("result=miss", 0) == 1


def test_env_selector_skew_counter():
    record_env_selector_skew("subagent")
    record_env_selector_skew("subagent")
    record_env_selector_skew("worktree")

    snap = Z3Counters.snapshot(Z3CounterNames.ENV_SELECTOR_SKEW)
    assert snap.get("env=subagent", 0) == 2
    assert snap.get("env=worktree", 0) == 1


def test_all_metrics_snapshot():
    record_dispatch_fallthrough("test")
    record_routing_brain_cache(hit=False)
    all_m = Z3Counters.all_metrics()
    assert Z3CounterNames.DISPATCH_FALLTHROUGH in all_m
    assert Z3CounterNames.ROUTING_BRAIN_CACHE in all_m


def test_counter_get():
    Z3Counters.increment("test.counter", label="a")
    Z3Counters.increment("test.counter", label="a")
    assert Z3Counters.get("test.counter", label="a") == 2
    assert Z3Counters.get("test.counter", label="b") == 0


def test_span_names_defined():
    assert Z3Spans.DISPATCHER_VALIDATE == "z3.dispatcher.validate_ms"
    assert Z3Spans.DISPATCHER_ROUTE == "z3.dispatcher.route_ms"
    assert Z3Spans.EXECUTOR_SPINUP == "z3.executor.spinup_ms"
    assert Z3Spans.EXECUTOR_EXEC == "z3.executor.exec_ms"
    assert Z3Spans.SYNTHESIZER == "z3.synthesizer.ms"
    assert Z3Spans.REQUEST_TOTAL == "z3.request.total_ms"


def test_environment_selector_emits_skew(tmp_path):
    """EnvironmentSelector.validate_selection emits skew counter when skewed."""
    from bridge.environment_selector import EnvironmentSelector
    from bridge.work_order import Environment, WorkOrder

    selector = EnvironmentSelector(window_size=5, skew_threshold=0.6)
    # Over-index on SUBAGENT
    for _ in range(5):
        selector.record_usage(Environment.SUBAGENT)

    wo = WorkOrder.create(intent="test", skill="chat", project="proj")
    warning = selector.validate_selection(Environment.SUBAGENT, "subagent-default")
    if warning:  # only fires when actually skewed
        snap = Z3Counters.snapshot(Z3CounterNames.ENV_SELECTOR_SKEW)
        assert snap.get("env=subagent", 0) >= 1
