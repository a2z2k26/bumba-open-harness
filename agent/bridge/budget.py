"""Daily budget guard with SQLite persistence.

Tracks per-invocation costs and enforces daily spending limits.
Pre-flight check prevents new requests when budget is exhausted.
"""

from __future__ import annotations

import logging

from .database import Database

logger = logging.getLogger(__name__)


class BudgetGuard:
    """Track daily costs in SQLite and enforce budget limits."""

    def __init__(self, db: Database, daily_limit: float = 0.0) -> None:
        self._db = db
        self._daily_limit = daily_limit
        self._last_alert_level = "ok"

    async def record(self, cost_usd: float, session_id: str = "", chat_id: str = "") -> None:
        """Record a cost entry."""
        if cost_usd <= 0:
            return
        await self._db.execute(
            """INSERT INTO budget_log (cost_usd, session_id, chat_id)
               VALUES (?, ?, ?)""",
            (cost_usd, session_id, chat_id),
        )
        await self._db.commit()

    async def check(self) -> dict:
        """Pre-flight budget check. Returns dict with allowed, spent, remaining, alert_level."""
        spent = await self._get_today_spend()

        if self._daily_limit <= 0:
            return {
                "allowed": True,
                "spent_today": spent,
                "remaining": float("inf"),
                "daily_limit": 0.0,
                "alert_level": "ok",
            }

        remaining = self._daily_limit - spent
        ratio = spent / self._daily_limit

        if ratio >= 1.0:
            level = "exceeded"
        elif ratio >= 0.75:
            level = "critical"
        elif ratio >= 0.50:
            level = "warning"
        else:
            level = "ok"

        return {
            "allowed": remaining > 0,
            "spent_today": spent,
            "remaining": max(remaining, 0),
            "daily_limit": self._daily_limit,
            "alert_level": level,
        }

    async def can_afford(self, projected_cost: float) -> bool:
        """Return True if the daily budget has headroom for *projected_cost*.

        When no daily limit is configured (daily_limit <= 0), always returns True.
        """
        status = await self.check()
        remaining = status["remaining"]
        if remaining == float("inf"):
            return True
        return remaining >= projected_cost

    async def should_alert(self) -> str | None:
        """Check if a new alert threshold was crossed. Returns message or None."""
        status = await self.check()
        level = status["alert_level"]
        if level != self._last_alert_level and level != "ok":
            self._last_alert_level = level
            return (
                f"Budget {level}: ${status['spent_today']:.2f} / "
                f"${status['daily_limit']:.2f}"
            )
        if level == "ok":
            self._last_alert_level = "ok"
        return None

    def get_pressure_signal(self, budget_status: dict) -> str | None:
        """Return a budget pressure string for Claude's context, or None.

        Two-tier system:
          - Caution (50%): nudge to be concise
          - Warning (75%): urgent, wrap up now
        """
        if self._daily_limit <= 0:
            return None

        ratio = budget_status["spent_today"] / self._daily_limit
        remaining = budget_status["remaining"]

        if ratio >= 0.75:
            return (
                f"[BUDGET WARNING: ${budget_status['spent_today']:.2f} / "
                f"${self._daily_limit:.2f} spent today. "
                f"Only ${remaining:.2f} remaining. "
                "Be concise. Avoid unnecessary tool calls. "
                "Wrap up the current task efficiently.]"
            )
        if ratio >= 0.50:
            return (
                f"[BUDGET: ${budget_status['spent_today']:.2f} / "
                f"${self._daily_limit:.2f} spent today. "
                f"${remaining:.2f} remaining. Be mindful of cost.]"
            )
        return None

    async def _get_today_spend(self) -> float:
        row = await self._db.fetchone(
            """SELECT COALESCE(SUM(cost_usd), 0) FROM budget_log
               WHERE timestamp > datetime('now', '-1 day')""",
        )
        return row[0] if row else 0.0

    async def get_status(self) -> dict:
        """Get budget status for /status command."""
        status = await self.check()
        remaining = status["remaining"]
        return {
            "daily_limit": status["daily_limit"],
            "spent_today": round(status["spent_today"], 4),
            "remaining": round(remaining, 4) if remaining != float("inf") else "unlimited",
            "alert_level": status["alert_level"],
        }


# ---------------------------------------------------------------------------
# Token Budget Pre-Turn Projection (Sprint E.1)
# ---------------------------------------------------------------------------

# Typical output-to-input ratios by model tier
_OUTPUT_RATIOS: dict[str, float] = {
    "haiku": 1.5,
    "sonnet": 2.0,
    "opus": 3.0,
}

# Import pricing from cost_tracker
from .cost_tracker import PRICING as _PRICING  # noqa: E402


def project_turn_cost(model: str, estimated_input_tokens: int) -> float:
    """Estimate the cost of the next turn before it happens.

    Uses model-specific output ratios to project total token usage,
    then applies the pricing table from cost_tracker.

    Args:
        model: Model tier name (haiku/sonnet/opus).
        estimated_input_tokens: Approximate input tokens for this turn.

    Returns:
        Projected cost in USD.
    """
    if estimated_input_tokens <= 0:
        return 0.0

    key = model.lower()
    if key not in _PRICING:
        key = "sonnet"  # Default to sonnet pricing

    output_ratio = _OUTPUT_RATIOS.get(key, 2.0)
    estimated_output = int(estimated_input_tokens * output_ratio)

    input_price, output_price = _PRICING[key]
    return (estimated_input_tokens * input_price + estimated_output * output_price) / 1_000_000
