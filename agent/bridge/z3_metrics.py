"""Z3 metric counters and span name constants.

Sprint S08 — 9 missing metrics + tracing spans.

Usage:
    from bridge.z3_metrics import Z3Counters, Z3Spans
    from bridge.tracing import get_tracer

    tracer = get_tracer("z3.dispatcher")

    # Span wrapping
    with tracer.context_span(Z3Spans.DISPATCHER_VALIDATE) as span:
        result = dispatcher.validate_for_dispatch(wo)

    # Counter increment
    Z3Counters.increment("z3.dispatch.fallthrough_total", reason="unknown_route")
"""
from __future__ import annotations

import threading
from collections import defaultdict


# ---------------------------------------------------------------------------
# Span name constants
# ---------------------------------------------------------------------------

class Z3Spans:
    """Canonical span names for Z3 instrumentation."""

    DISPATCHER_VALIDATE = "z3.dispatcher.validate_ms"
    DISPATCHER_ROUTE = "z3.dispatcher.route_ms"
    EXECUTOR_SPINUP = "z3.executor.spinup_ms"
    EXECUTOR_EXEC = "z3.executor.exec_ms"
    SYNTHESIZER = "z3.synthesizer.ms"
    CLASSIFIER = "z3.classifier.ms"
    REQUEST_TOTAL = "z3.request.total_ms"


# ---------------------------------------------------------------------------
# Counter registry
# ---------------------------------------------------------------------------

class _CounterRegistry:
    """Thread-safe labeled counter registry.

    Counters are keyed by (metric_name, label_tuple) pairs.

    Usage:
        registry.increment("z3.dispatch.fallthrough_total", reason="unknown_route")
        snapshot = registry.snapshot("z3.dispatch.fallthrough_total")
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        # metric_name -> {label_dict_key -> int}
        self._counters: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))

    def increment(self, metric: str, **labels: str) -> None:
        """Increment a labeled counter by 1."""
        key = ",".join(f"{k}={v}" for k, v in sorted(labels.items())) if labels else "_total"
        with self._lock:
            self._counters[metric][key] += 1

    def get(self, metric: str, **labels: str) -> int:
        """Return the current value of a labeled counter."""
        key = ",".join(f"{k}={v}" for k, v in sorted(labels.items())) if labels else "_total"
        with self._lock:
            return self._counters[metric].get(key, 0)

    def snapshot(self, metric: str) -> dict[str, int]:
        """Return a copy of all label buckets for a metric."""
        with self._lock:
            return dict(self._counters.get(metric, {}))

    def all_metrics(self) -> dict[str, dict[str, int]]:
        """Return a full snapshot of all counters."""
        with self._lock:
            return {k: dict(v) for k, v in self._counters.items()}

    def reset(self) -> None:
        """Reset all counters (for testing)."""
        with self._lock:
            self._counters.clear()


# Module-level singleton
Z3Counters = _CounterRegistry()


# ---------------------------------------------------------------------------
# Pre-defined counter names (documentation)
# ---------------------------------------------------------------------------

class Z3CounterNames:
    """Canonical counter names for Z3 instrumentation."""

    # LRU cache hit/miss in routing_brain
    ROUTING_BRAIN_CACHE = "z3.routing_brain.cache"

    # EnvironmentSelector skew detection: labels: env=<env_value>
    ENV_SELECTOR_SKEW = "z3.env_selector.skew"

    # Dispatcher fallthrough (handled=False): labels: reason=<reason>
    DISPATCH_FALLTHROUGH = "z3.dispatch.fallthrough_total"

    # Sprint D-R3 (#1933) — SubagentExecutor lifecycle counters
    # WorkOrder execution timed out in SubagentExecutor: labels:
    # intent=<intent>, env=<env>
    SUBAGENT_TIMEOUT = "dispatcher.subagent.timeout"
    # WorkOrder completed successfully in SubagentExecutor: labels:
    # intent=<intent>, env=<env>
    SUBAGENT_SUCCESS = "dispatcher.subagent.success"
    # WorkOrder failed with non-timeout error in SubagentExecutor: labels:
    # intent=<intent>, env=<env>, error_type=<type>
    SUBAGENT_ERROR = "dispatcher.subagent.error"


# ---------------------------------------------------------------------------
# Helper: emit fallthrough counter
# ---------------------------------------------------------------------------

def record_dispatch_fallthrough(reason: str) -> None:
    """Increment the dispatcher fallthrough counter with a reason label."""
    Z3Counters.increment(Z3CounterNames.DISPATCH_FALLTHROUGH, reason=reason)


def record_routing_brain_cache(hit: bool) -> None:
    """Increment routing brain cache counter."""
    Z3Counters.increment(Z3CounterNames.ROUTING_BRAIN_CACHE, result="hit" if hit else "miss")


def record_env_selector_skew(env: str) -> None:
    """Increment environment selector skew counter."""
    Z3Counters.increment(Z3CounterNames.ENV_SELECTOR_SKEW, env=env)


# Sprint D-R3 (#1933) — SubagentExecutor lifecycle helpers


def record_subagent_timeout(intent: str, env: str) -> None:
    """Increment the SubagentExecutor timeout counter."""
    Z3Counters.increment(Z3CounterNames.SUBAGENT_TIMEOUT, intent=intent, env=env)


def record_subagent_success(intent: str, env: str) -> None:
    """Increment the SubagentExecutor success counter."""
    Z3Counters.increment(Z3CounterNames.SUBAGENT_SUCCESS, intent=intent, env=env)


def record_subagent_error(intent: str, env: str, error_type: str) -> None:
    """Increment the SubagentExecutor error (non-timeout) counter."""
    Z3Counters.increment(
        Z3CounterNames.SUBAGENT_ERROR,
        intent=intent,
        env=env,
        error_type=error_type,
    )
