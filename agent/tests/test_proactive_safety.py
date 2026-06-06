"""Tests for proactive action safety rails."""
from __future__ import annotations

import time
from dataclasses import FrozenInstanceError

import pytest

from bridge.proactive_safety import (
    ProactiveBudget,
    ProactiveGuard,
    ActionVerdict,
    PROACTIVE_ALLOWED_ACTIONS,
    PROACTIVE_FORBIDDEN_ACTIONS,
)


# ── ProactiveBudget ───────────────────────────────────────────────────────────

def test_budget_is_frozen():
    b = ProactiveBudget()
    with pytest.raises((FrozenInstanceError, TypeError, AttributeError)):
        b.max_actions_per_hour = 99


def test_default_budget_values():
    b = ProactiveBudget()
    assert b.max_actions_per_hour == 10
    assert b.max_cost_per_hour_usd == 0.50
    assert b.max_consecutive_actions == 3


def test_custom_budget():
    b = ProactiveBudget(max_actions_per_hour=5, max_cost_per_hour_usd=0.25, max_consecutive_actions=2)
    assert b.max_actions_per_hour == 5


# ── ActionVerdict ─────────────────────────────────────────────────────────────

def test_action_verdict_allowed():
    v = ActionVerdict(allowed=True, reason="ok")
    assert v.allowed is True


def test_action_verdict_denied():
    v = ActionVerdict(allowed=False, reason="forbidden")
    assert v.allowed is False
    assert "forbidden" in v.reason


# ── ProactiveGuard ────────────────────────────────────────────────────────────

@pytest.fixture
def guard():
    return ProactiveGuard(budget=ProactiveBudget())


def test_allowed_action_passes(guard):
    verdict = guard.check_action("investigate_failure")
    assert verdict.allowed is True


def test_forbidden_action_blocked(guard):
    verdict = guard.check_action("deploy")
    assert verdict.allowed is False
    assert "forbidden" in verdict.reason.lower()


def test_unknown_action_requires_approval(guard):
    verdict = guard.check_action("some_unknown_action")
    assert verdict.allowed is False
    assert "not in allowed" in verdict.reason.lower() or "unknown" in verdict.reason.lower()


def test_hourly_action_limit(guard):
    # Exhaust the hourly limit
    for _ in range(10):
        guard.record_action("investigate_failure", cost_usd=0.01)

    verdict = guard.check_action("investigate_failure")
    assert verdict.allowed is False
    assert "limit" in verdict.reason.lower() or "budget" in verdict.reason.lower()


def test_consecutive_action_limit(guard):
    for _ in range(3):
        guard.record_action("investigate_failure", cost_usd=0.01)

    verdict = guard.check_action("investigate_failure")
    assert verdict.allowed is False
    assert "consecutive" in verdict.reason.lower() or "sleep" in verdict.reason.lower()


def test_cost_limit(guard):
    # Exhaust cost budget
    guard.record_action("investigate_failure", cost_usd=0.49)
    verdict = guard.check_action("investigate_failure")
    # Still within budget
    assert verdict.allowed is True

    guard.record_action("investigate_failure", cost_usd=0.02)
    verdict = guard.check_action("investigate_failure")
    assert verdict.allowed is False


def test_reset_after_sleep(guard):
    for _ in range(3):
        guard.record_action("investigate_failure", cost_usd=0.01)

    # Reset consecutive count (agent slept)
    guard.reset_consecutive()
    verdict = guard.check_action("investigate_failure")
    assert verdict.allowed is True


def test_hourly_window_resets(guard):
    """Actions older than 1 hour don't count toward the hourly limit."""
    old_time = time.time() - 3700  # > 1 hour ago
    for _ in range(10):
        guard._action_log.append({"action": "investigate_failure", "cost": 0.01, "timestamp": old_time})

    verdict = guard.check_action("investigate_failure")
    assert verdict.allowed is True


def test_get_status(guard):
    status = guard.get_status()
    assert "actions_this_hour" in status
    assert "cost_this_hour_usd" in status
    assert "consecutive_actions" in status
    assert "budget" in status


# ── Allowlist / blocklist constants ──────────────────────────────────────────

def test_allowed_actions_set():
    assert "investigate_failure" in PROACTIVE_ALLOWED_ACTIONS
    assert "update_knowledge" in PROACTIVE_ALLOWED_ACTIONS
    assert "check_ci_status" in PROACTIVE_ALLOWED_ACTIONS


def test_forbidden_actions_set():
    assert "deploy" in PROACTIVE_FORBIDDEN_ACTIONS
    assert "merge_pr" in PROACTIVE_FORBIDDEN_ACTIONS
    assert "delete_anything" in PROACTIVE_FORBIDDEN_ACTIONS
