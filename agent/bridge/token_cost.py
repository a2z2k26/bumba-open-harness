"""
Token Cost Manager — per-provider cost calculation and budget tracking.

Tracks input/output tokens and calculates costs based on model pricing.
Provides budget alerts and daily/monthly limit enforcement.
"""

from dataclasses import dataclass, field
from typing import Dict, Optional, List
from datetime import datetime, timedelta
from enum import Enum

from bridge import model_defaults  # P0.01 canonical default-model constants


class CostAlertLevel(str, Enum):
    """Cost alert severity levels."""
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


@dataclass
class TokenUsage:
    """Token usage for a single invocation."""
    model: str
    input_tokens: int
    output_tokens: int
    timestamp: datetime = field(default_factory=datetime.now)

    def total_tokens(self) -> int:
        """Total tokens (input + output)."""
        return self.input_tokens + self.output_tokens


@dataclass
class CostAlert:
    """Cost budget alert."""
    level: CostAlertLevel
    message: str
    current_cost: float
    threshold: float
    remaining_budget: float


class PricingModel:
    """Pricing for a specific model."""

    # Pricing as of 2026-02-24 (per million tokens).
    # This table is documented real cost data, NOT a de-hardcode target — keep
    # the literal model keys. The canonical default *model* used for affordability
    # estimation lives in bridge.model_defaults.DEFAULT_PRICING_MODEL (P0.01),
    # which must always have an entry here (see test_token_cost_drift.py).
    PRICES = {
        "claude-opus-4-6": {
            "input_per_mtok": 15.0,
            "output_per_mtok": 45.0,
        },
        "claude-sonnet-4-6": {
            "input_per_mtok": 3.0,
            "output_per_mtok": 15.0,
        },
        "claude-haiku-4-5": {
            "input_per_mtok": 0.80,
            "output_per_mtok": 4.0,
        },
        "inflection-3-pi": {
            "input_per_mtok": 0.50,
            "output_per_mtok": 1.50,
        },
    }

    def __init__(self, model: str):
        """Initialize pricing for a model."""
        self.model = model
        self.prices = self.PRICES.get(model, {"input_per_mtok": 0.0, "output_per_mtok": 0.0})

    def calculate_cost(self, input_tokens: int, output_tokens: int) -> float:
        """
        Calculate cost for token usage.

        Args:
            input_tokens: Number of input tokens
            output_tokens: Number of output tokens

        Returns:
            Cost in USD
        """
        input_cost = (input_tokens / 1_000_000) * self.prices["input_per_mtok"]
        output_cost = (output_tokens / 1_000_000) * self.prices["output_per_mtok"]
        return input_cost + output_cost


class TokenCostManager:
    """
    Manages token costs and budget tracking.

    Tracks input/output tokens per model, calculates costs,
    and enforces budget limits.
    """

    def __init__(
        self,
        daily_budget: Optional[float] = None,
        monthly_budget: Optional[float] = None,
    ):
        """
        Initialize cost manager.

        Args:
            daily_budget: Daily spend limit in USD (None = unlimited)
            monthly_budget: Monthly spend limit in USD (None = unlimited)
        """
        self.daily_budget = daily_budget
        self.monthly_budget = monthly_budget
        self.usage_history: List[TokenUsage] = []
        self.cost_history: List[Dict] = []
        self.alerts: List[CostAlert] = []

    def record_usage(self, usage: TokenUsage) -> float:
        """
        Record token usage and calculate cost.

        Args:
            usage: TokenUsage instance

        Returns:
            Cost for this usage in USD
        """
        self.usage_history.append(usage)

        # Calculate cost
        pricing = PricingModel(usage.model)
        cost = pricing.calculate_cost(usage.input_tokens, usage.output_tokens)

        # Track cost
        self.cost_history.append({
            "model": usage.model,
            "input_tokens": usage.input_tokens,
            "output_tokens": usage.output_tokens,
            "cost": cost,
            "timestamp": usage.timestamp,
        })

        # Check budget constraints
        self._check_budget_alerts()

        return cost

    def get_total_cost(self) -> float:
        """Get total cost across all usage."""
        return sum(item["cost"] for item in self.cost_history)

    def get_daily_cost(self, date: Optional[datetime] = None) -> float:
        """
        Get cost for a specific day.

        Args:
            date: Day to calculate (defaults to today)

        Returns:
            Total cost for that day
        """
        if date is None:
            date = datetime.now()

        day_start = date.replace(hour=0, minute=0, second=0, microsecond=0)
        day_end = day_start + timedelta(days=1)

        daily_total = 0.0
        for item in self.cost_history:
            if day_start <= item["timestamp"] < day_end:
                daily_total += item["cost"]

        return daily_total

    def get_monthly_cost(self, year: Optional[int] = None, month: Optional[int] = None) -> float:
        """
        Get cost for a specific month.

        Args:
            year: Year (defaults to current)
            month: Month (defaults to current)

        Returns:
            Total cost for that month
        """
        now = datetime.now()
        year = year or now.year
        month = month or now.month

        month_start = datetime(year, month, 1)
        if month == 12:
            month_end = datetime(year + 1, 1, 1)
        else:
            month_end = datetime(year, month + 1, 1)

        monthly_total = 0.0
        for item in self.cost_history:
            if month_start <= item["timestamp"] < month_end:
                monthly_total += item["cost"]

        return monthly_total

    def get_cost_by_model(self) -> Dict[str, float]:
        """
        Get cost breakdown by model.

        Returns:
            Dictionary mapping model names to total cost
        """
        costs = {}
        for item in self.cost_history:
            model = item["model"]
            costs[model] = costs.get(model, 0.0) + item["cost"]
        return costs

    def get_token_usage_by_model(self) -> Dict[str, Dict[str, int]]:
        """
        Get token usage breakdown by model.

        Returns:
            Dictionary with input/output token counts per model
        """
        usage = {}
        for u in self.usage_history:
            if u.model not in usage:
                usage[u.model] = {"input": 0, "output": 0}
            usage[u.model]["input"] += u.input_tokens
            usage[u.model]["output"] += u.output_tokens
        return usage

    def _check_budget_alerts(self) -> None:
        """Check daily/monthly budgets and generate alerts."""
        self.alerts = []

        today_cost = self.get_daily_cost()

        # Daily budget check
        if self.daily_budget:
            if today_cost >= self.daily_budget * 0.9:
                remaining = self.daily_budget - today_cost
                level = CostAlertLevel.CRITICAL if remaining <= 0 else CostAlertLevel.WARNING
                self.alerts.append(CostAlert(
                    level=level,
                    message=f"Daily budget threshold reached: ${today_cost:.2f}/${self.daily_budget:.2f}",
                    current_cost=today_cost,
                    threshold=self.daily_budget,
                    remaining_budget=remaining,
                ))

        # Monthly budget check
        if self.monthly_budget:
            month_cost = self.get_monthly_cost()
            if month_cost >= self.monthly_budget * 0.9:
                remaining = self.monthly_budget - month_cost
                level = CostAlertLevel.CRITICAL if remaining <= 0 else CostAlertLevel.WARNING
                self.alerts.append(CostAlert(
                    level=level,
                    message=f"Monthly budget threshold reached: ${month_cost:.2f}/${self.monthly_budget:.2f}",
                    current_cost=month_cost,
                    threshold=self.monthly_budget,
                    remaining_budget=remaining,
                ))

    def can_afford(
        self,
        estimated_tokens: int,
        model: str = model_defaults.DEFAULT_PRICING_MODEL,
    ) -> bool:
        """
        Check if estimated usage fits in daily budget.

        Args:
            estimated_tokens: Total tokens (input + output)
            model: Model to use for pricing. Defaults to the canonical
                DEFAULT_PRICING_MODEL (P0.01) — current value
                "claude-opus-4-6" preserved as the documented default.

        Returns:
            True if budget allows this usage
        """
        if not self.daily_budget:
            return True

        pricing = PricingModel(model)
        # Assume 1/3 input, 2/3 output for estimation
        input_est = estimated_tokens // 3
        output_est = (estimated_tokens * 2) // 3
        estimated_cost = pricing.calculate_cost(input_est, output_est)

        today_cost = self.get_daily_cost()
        return (today_cost + estimated_cost) <= self.daily_budget

    def get_alerts(self) -> List[CostAlert]:
        """Get all active cost alerts."""
        return self.alerts

    def reset_daily_tracking(self) -> None:
        """Reset daily cost tracking (for new day)."""
        today = datetime.now()
        self.cost_history = [
            item for item in self.cost_history
            if item["timestamp"].date() != today.date()
        ]
        self._check_budget_alerts()

    def to_dict(self) -> Dict:
        """
        Serialize to dictionary.

        Returns:
            Dictionary representation of costs and budgets
        """
        return {
            "total_cost": self.get_total_cost(),
            "daily_cost": self.get_daily_cost(),
            "monthly_cost": self.get_monthly_cost(),
            "daily_budget": self.daily_budget,
            "monthly_budget": self.monthly_budget,
            "cost_by_model": self.get_cost_by_model(),
            "usage_by_model": self.get_token_usage_by_model(),
            "alerts": [
                {
                    "level": alert.level.value,
                    "message": alert.message,
                    "current_cost": alert.current_cost,
                    "threshold": alert.threshold,
                    "remaining_budget": alert.remaining_budget,
                }
                for alert in self.alerts
            ],
        }


    # ------------------------------------------------------------------
    # Alias methods for Plan 2 orchestration API compatibility
    # ------------------------------------------------------------------

    def get_daily_spend(self, date=None) -> float:
        """Alias for get_daily_cost() — Plan 2 orchestration API."""
        return self.get_daily_cost(date)

    def get_monthly_spend(self, year: int = None, month: int = None) -> float:
        """Alias for get_monthly_cost() — Plan 2 orchestration API."""
        return self.get_monthly_cost()
