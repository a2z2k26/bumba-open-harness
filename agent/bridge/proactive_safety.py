"""Proactive action safety rails.

Enforces budgets, allowlists, and blocklists for autonomous proactive actions.
All proactive tool uses must pass through ProactiveGuard.check_action() first.

Enforces safety rails for all proactive autonomous actions.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any


# Actions the agent is allowed to take proactively
PROACTIVE_ALLOWED_ACTIONS: frozenset[str] = frozenset({
    "investigate_failure",    # Read logs, check status
    "update_knowledge",       # Write to memory
    "prepare_briefing",       # Pre-gather data
    "check_ci_status",        # Read-only CI checks
    "review_stale_pr",        # Read-only PR review
    "consolidate_memory",     # Trigger dream
})

# Actions the agent is NEVER allowed to take proactively
PROACTIVE_FORBIDDEN_ACTIONS: frozenset[str] = frozenset({
    "deploy",                 # Never auto-deploy
    "merge_pr",               # Never auto-merge
    "delete_anything",        # Never auto-delete
    "send_external_message",  # Never auto-message externally
    "modify_config",          # Never auto-modify config
})


@dataclass(frozen=True)
class ProactiveBudget:
    """Budget constraints for proactive actions."""

    max_actions_per_hour: int = 10
    max_cost_per_hour_usd: float = 0.50
    max_consecutive_actions: int = 3  # Must sleep after this many actions


@dataclass(frozen=True)
class ActionVerdict:
    """Result of a ProactiveGuard.check_action() call."""

    allowed: bool
    reason: str


class ProactiveGuard:
    """Enforces safety rails for all proactive agent actions.

    Checks:
    1. Action is in PROACTIVE_ALLOWED_ACTIONS (not unknown, not forbidden)
    2. Hourly action count within budget
    3. Hourly cost within budget
    4. Consecutive action count within budget (must sleep between bursts)
    """

    def __init__(self, budget: ProactiveBudget | None = None) -> None:
        """Initialize with an optional custom budget."""
        self._budget = budget or ProactiveBudget()
        self._action_log: list[dict[str, Any]] = []  # {action, cost, timestamp}
        self._consecutive_count: int = 0

    def check_action(self, action_type: str) -> ActionVerdict:
        """Check whether a proactive action is permitted.

        Args:
            action_type: The action identifier (e.g., 'investigate_failure').

        Returns:
            ActionVerdict with allowed=True/False and a reason string.
        """
        # 1. Forbidden actions — hard block
        if action_type in PROACTIVE_FORBIDDEN_ACTIONS:
            return ActionVerdict(allowed=False, reason=f"forbidden action: {action_type}")

        # 2. Must be in allowlist
        if action_type not in PROACTIVE_ALLOWED_ACTIONS:
            return ActionVerdict(
                allowed=False,
                reason=f"not in allowed actions list: {action_type}",
            )

        # 3. Consecutive limit — must sleep between bursts
        if self._consecutive_count >= self._budget.max_consecutive_actions:
            return ActionVerdict(
                allowed=False,
                reason=(
                    f"consecutive action limit reached ({self._consecutive_count}/"
                    f"{self._budget.max_consecutive_actions}) — must sleep first"
                ),
            )

        # 4. Hourly window checks
        now = time.time()
        recent = [e for e in self._action_log if now - e["timestamp"] < 3600]

        if len(recent) >= self._budget.max_actions_per_hour:
            return ActionVerdict(
                allowed=False,
                reason=(
                    f"hourly action limit reached ({len(recent)}/"
                    f"{self._budget.max_actions_per_hour})"
                ),
            )

        hourly_cost = sum(e["cost"] for e in recent)
        # Check if adding a minimal action would exceed cost budget
        if hourly_cost >= self._budget.max_cost_per_hour_usd:
            return ActionVerdict(
                allowed=False,
                reason=(
                    f"hourly cost budget exceeded (${hourly_cost:.3f}/"
                    f"${self._budget.max_cost_per_hour_usd:.2f})"
                ),
            )

        return ActionVerdict(allowed=True, reason="ok")

    def record_action(self, action_type: str, cost_usd: float = 0.0) -> None:
        """Record that an action was taken.

        Args:
            action_type: The action identifier.
            cost_usd: Estimated cost of this action in USD.
        """
        self._action_log.append({
            "action": action_type,
            "cost": cost_usd,
            "timestamp": time.time(),
        })
        self._consecutive_count += 1

        # Trim old entries (keep last 200)
        if len(self._action_log) > 200:
            self._action_log = self._action_log[-200:]

    def reset_consecutive(self) -> None:
        """Reset the consecutive action counter (called when agent sleeps)."""
        self._consecutive_count = 0

    def get_status(self) -> dict[str, Any]:
        """Return current safety rail status for /proactive status command."""
        now = time.time()
        recent = [e for e in self._action_log if now - e["timestamp"] < 3600]
        hourly_cost = sum(e["cost"] for e in recent)

        return {
            "actions_this_hour": len(recent),
            "cost_this_hour_usd": round(hourly_cost, 4),
            "consecutive_actions": self._consecutive_count,
            "budget": {
                "max_actions_per_hour": self._budget.max_actions_per_hour,
                "max_cost_per_hour_usd": self._budget.max_cost_per_hour_usd,
                "max_consecutive_actions": self._budget.max_consecutive_actions,
            },
        }
