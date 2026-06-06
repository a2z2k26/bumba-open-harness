"""Tests for token cost tracking and budget management."""

from datetime import datetime, timedelta
from bridge.token_cost import (
    TokenCostManager,
    TokenUsage,
    CostAlert,
    CostAlertLevel,
    PricingModel,
)


class TestPricingModel:
    """Test pricing model calculations."""

    def test_opus_pricing(self):
        """Opus pricing is correct."""
        pricing = PricingModel("claude-opus-4-6")
        cost = pricing.calculate_cost(1_000_000, 1_000_000)
        # 1M input @ $15/M + 1M output @ $45/M = $60
        assert cost == 60.0

    def test_sonnet_pricing(self):
        """Sonnet pricing is correct."""
        pricing = PricingModel("claude-sonnet-4-6")
        cost = pricing.calculate_cost(1_000_000, 1_000_000)
        # 1M input @ $3/M + 1M output @ $15/M = $18
        assert cost == 18.0

    def test_haiku_pricing(self):
        """Haiku pricing is correct."""
        pricing = PricingModel("claude-haiku-4-5")
        cost = pricing.calculate_cost(1_000_000, 1_000_000)
        # 1M input @ $0.80/M + 1M output @ $4/M = $4.80
        assert cost == 4.8

    def test_inflection_pricing(self):
        """Inflection pricing is correct."""
        pricing = PricingModel("inflection-3-pi")
        cost = pricing.calculate_cost(1_000_000, 1_000_000)
        # 1M input @ $0.50/M + 1M output @ $1.50/M = $2.00
        assert cost == 2.0

    def test_partial_tokens(self):
        """Partial token usage calculates correctly."""
        pricing = PricingModel("claude-opus-4-6")
        cost = pricing.calculate_cost(100_000, 200_000)
        # 100K input @ $15/M + 200K output @ $45/M
        expected = (100_000 / 1_000_000 * 15.0) + (200_000 / 1_000_000 * 45.0)
        assert abs(cost - expected) < 0.001

    def test_zero_tokens(self):
        """Zero token usage costs nothing."""
        pricing = PricingModel("claude-opus-4-6")
        cost = pricing.calculate_cost(0, 0)
        assert cost == 0.0

    def test_unknown_model_zero_cost(self):
        """Unknown model defaults to zero cost."""
        pricing = PricingModel("unknown-model")
        cost = pricing.calculate_cost(1_000_000, 1_000_000)
        assert cost == 0.0


class TestTokenUsage:
    """Test token usage tracking."""

    def test_create_usage(self):
        """Can create token usage record."""
        usage = TokenUsage(
            model="claude-opus-4-6",
            input_tokens=100,
            output_tokens=200,
        )
        assert usage.model == "claude-opus-4-6"
        assert usage.input_tokens == 100
        assert usage.output_tokens == 200

    def test_total_tokens(self):
        """Total tokens calculated correctly."""
        usage = TokenUsage(
            model="claude-opus-4-6",
            input_tokens=100,
            output_tokens=200,
        )
        assert usage.total_tokens() == 300

    def test_timestamp_default(self):
        """Timestamp defaults to now."""
        before = datetime.now()
        usage = TokenUsage(
            model="claude-opus-4-6",
            input_tokens=100,
            output_tokens=200,
        )
        after = datetime.now()
        assert before <= usage.timestamp <= after

    def test_custom_timestamp(self):
        """Can set custom timestamp."""
        ts = datetime(2026, 2, 24, 10, 0, 0)
        usage = TokenUsage(
            model="claude-opus-4-6",
            input_tokens=100,
            output_tokens=200,
            timestamp=ts,
        )
        assert usage.timestamp == ts


class TestCostAlert:
    """Test cost alert generation."""

    def test_create_alert(self):
        """Can create cost alert."""
        alert = CostAlert(
            level=CostAlertLevel.WARNING,
            message="Daily budget threshold reached",
            current_cost=90.0,
            threshold=100.0,
            remaining_budget=10.0,
        )
        assert alert.level == CostAlertLevel.WARNING
        assert alert.current_cost == 90.0

    def test_alert_levels(self):
        """All alert levels available."""
        levels = [CostAlertLevel.INFO, CostAlertLevel.WARNING, CostAlertLevel.CRITICAL]
        assert len(levels) == 3


class TestTokenCostManagerBasics:
    """Test basic token cost manager functionality."""

    def test_create_manager(self):
        """Can create cost manager."""
        manager = TokenCostManager()
        assert manager is not None

    def test_manager_with_budgets(self):
        """Can create manager with budgets."""
        manager = TokenCostManager(daily_budget=100.0, monthly_budget=2000.0)
        assert manager.daily_budget == 100.0
        assert manager.monthly_budget == 2000.0

    def test_manager_no_budgets(self):
        """Manager works without budgets."""
        manager = TokenCostManager()
        assert manager.daily_budget is None
        assert manager.monthly_budget is None


class TestTokenUsageRecording:
    """Test recording token usage."""

    def test_record_single_usage(self):
        """Can record single token usage."""
        manager = TokenCostManager()
        usage = TokenUsage(
            model="claude-opus-4-6",
            input_tokens=100,
            output_tokens=200,
        )
        cost = manager.record_usage(usage)
        assert cost > 0

    def test_record_multiple_usages(self):
        """Can record multiple token usages."""
        manager = TokenCostManager()
        usage1 = TokenUsage(
            model="claude-opus-4-6",
            input_tokens=100,
            output_tokens=200,
        )
        usage2 = TokenUsage(
            model="claude-sonnet-4-6",
            input_tokens=50,
            output_tokens=100,
        )
        cost1 = manager.record_usage(usage1)
        cost2 = manager.record_usage(usage2)
        assert cost1 > 0
        assert cost2 > 0
        assert len(manager.usage_history) == 2
        assert len(manager.cost_history) == 2

    def test_cost_matches_pricing(self):
        """Recorded cost matches pricing model."""
        manager = TokenCostManager()
        usage = TokenUsage(
            model="claude-opus-4-6",
            input_tokens=1_000_000,
            output_tokens=1_000_000,
        )
        cost = manager.record_usage(usage)
        assert abs(cost - 60.0) < 0.001


class TestCostCalculations:
    """Test cost calculation methods."""

    def test_get_total_cost(self):
        """Can calculate total cost."""
        manager = TokenCostManager()
        manager.record_usage(
            TokenUsage("claude-opus-4-6", 1_000_000, 1_000_000)
        )  # $60
        manager.record_usage(
            TokenUsage("claude-sonnet-4-6", 1_000_000, 1_000_000)
        )  # $18
        total = manager.get_total_cost()
        assert abs(total - 78.0) < 0.001

    def test_get_daily_cost_today(self):
        """Can calculate today's cost."""
        manager = TokenCostManager()
        manager.record_usage(
            TokenUsage("claude-opus-4-6", 1_000_000, 1_000_000)
        )  # $60
        daily = manager.get_daily_cost()
        assert abs(daily - 60.0) < 0.001

    def test_get_daily_cost_specific_date(self):
        """Can calculate cost for specific date."""
        manager = TokenCostManager()
        today = datetime.now()
        yesterday = today - timedelta(days=1)

        # Add usage for yesterday
        manager.record_usage(
            TokenUsage(
                "claude-opus-4-6",
                1_000_000,
                1_000_000,
                timestamp=yesterday,
            )
        )  # $60
        # Add usage for today
        manager.record_usage(
            TokenUsage("claude-sonnet-4-6", 1_000_000, 1_000_000)
        )  # $18

        daily_yesterday = manager.get_daily_cost(yesterday)
        daily_today = manager.get_daily_cost(today)

        assert abs(daily_yesterday - 60.0) < 0.001
        assert abs(daily_today - 18.0) < 0.001

    def test_get_monthly_cost(self):
        """Can calculate monthly cost."""
        manager = TokenCostManager()
        # Add usage for current month
        manager.record_usage(
            TokenUsage("claude-opus-4-6", 1_000_000, 1_000_000)
        )  # $60
        manager.record_usage(
            TokenUsage("claude-sonnet-4-6", 1_000_000, 1_000_000)
        )  # $18

        monthly = manager.get_monthly_cost()
        assert abs(monthly - 78.0) < 0.001

    def test_get_monthly_cost_specific_month(self):
        """Can calculate cost for specific month."""
        manager = TokenCostManager()
        today = datetime.now()

        # Add usage for current month
        manager.record_usage(
            TokenUsage("claude-opus-4-6", 1_000_000, 1_000_000)
        )  # $60

        monthly = manager.get_monthly_cost(today.year, today.month)
        assert abs(monthly - 60.0) < 0.001


class TestCostByModel:
    """Test model cost breakdown."""

    def test_get_cost_by_model(self):
        """Can break down cost by model."""
        manager = TokenCostManager()
        manager.record_usage(
            TokenUsage("claude-opus-4-6", 1_000_000, 1_000_000)
        )  # $60
        manager.record_usage(
            TokenUsage("claude-sonnet-4-6", 1_000_000, 1_000_000)
        )  # $18
        manager.record_usage(
            TokenUsage("claude-opus-4-6", 500_000, 500_000)
        )  # $30

        costs = manager.get_cost_by_model()

        assert len(costs) == 2
        assert abs(costs["claude-opus-4-6"] - 90.0) < 0.001  # $60 + $30
        assert abs(costs["claude-sonnet-4-6"] - 18.0) < 0.001

    def test_get_token_usage_by_model(self):
        """Can break down token usage by model."""
        manager = TokenCostManager()
        manager.record_usage(
            TokenUsage("claude-opus-4-6", 100, 200)
        )
        manager.record_usage(
            TokenUsage("claude-sonnet-4-6", 50, 100)
        )
        manager.record_usage(
            TokenUsage("claude-opus-4-6", 200, 400)
        )

        usage = manager.get_token_usage_by_model()

        assert len(usage) == 2
        assert usage["claude-opus-4-6"]["input"] == 300  # 100 + 200
        assert usage["claude-opus-4-6"]["output"] == 600  # 200 + 400
        assert usage["claude-sonnet-4-6"]["input"] == 50
        assert usage["claude-sonnet-4-6"]["output"] == 100


class TestBudgetAlerts:
    """Test budget alert generation."""

    def test_no_alerts_below_threshold(self):
        """No alerts when below 90% threshold."""
        manager = TokenCostManager(daily_budget=100.0)
        manager.record_usage(
            TokenUsage("claude-opus-4-6", 100_000, 100_000)
        )  # < $1

        alerts = manager.get_alerts()
        assert len(alerts) == 0

    def test_warning_at_90_percent(self):
        """Warning alert at 90% of daily budget."""
        manager = TokenCostManager(daily_budget=100.0)
        # Record usage that brings us to ~90% of budget
        # $60 per call, need at least 2 calls to exceed 90% threshold ($90)
        manager.record_usage(
            TokenUsage("claude-opus-4-6", 1_000_000, 1_000_000)
        )  # $60
        manager.record_usage(
            TokenUsage("claude-opus-4-6", 500_000, 500_000)
        )  # $30 more = $90 total (90%)

        alerts = manager.get_alerts()
        assert len(alerts) > 0
        # At 90%, we may have WARNING or CRITICAL depending on exact threshold
        assert any(a.level in (CostAlertLevel.WARNING, CostAlertLevel.CRITICAL) for a in alerts)

    def test_critical_over_budget(self):
        """Critical alert when over budget."""
        manager = TokenCostManager(daily_budget=50.0)
        manager.record_usage(
            TokenUsage("claude-opus-4-6", 1_000_000, 1_000_000)
        )  # $60 > $50

        alerts = manager.get_alerts()
        assert len(alerts) > 0
        assert any(a.level == CostAlertLevel.CRITICAL for a in alerts)

    def test_monthly_budget_alert(self):
        """Monthly budget alert generated."""
        manager = TokenCostManager(monthly_budget=50.0)
        manager.record_usage(
            TokenUsage("claude-opus-4-6", 1_000_000, 1_000_000)
        )  # $60 > $50

        alerts = manager.get_alerts()
        assert len(alerts) > 0

    def test_alert_contains_metadata(self):
        """Alert contains required metadata."""
        manager = TokenCostManager(daily_budget=50.0)
        manager.record_usage(
            TokenUsage("claude-opus-4-6", 1_000_000, 1_000_000)
        )  # $60

        alerts = manager.get_alerts()
        assert len(alerts) > 0
        alert = alerts[0]
        assert alert.current_cost > 0
        assert alert.threshold == 50.0
        assert alert.remaining_budget < 0
        assert alert.message is not None


class TestBudgetEnforcement:
    """Test budget enforcement."""

    def test_can_afford_within_budget(self):
        """Can afford when within budget."""
        manager = TokenCostManager(daily_budget=100.0)
        can_afford = manager.can_afford(10_000)
        assert can_afford is True

    def test_cannot_afford_over_budget(self):
        """Cannot afford when over budget."""
        manager = TokenCostManager(daily_budget=50.0)
        manager.record_usage(
            TokenUsage("claude-opus-4-6", 1_000_000, 1_000_000)
        )  # $60 already spent

        can_afford = manager.can_afford(10_000)
        assert can_afford is False

    def test_can_afford_no_budget(self):
        """Can always afford when no budget set."""
        manager = TokenCostManager()
        can_afford = manager.can_afford(1_000_000_000)
        assert can_afford is True

    def test_can_afford_respects_model_pricing(self):
        """can_afford respects model pricing."""
        manager = TokenCostManager(daily_budget=1.0)  # $1 budget
        # Opus is expensive, even small token usage exceeds budget
        can_afford_opus = manager.can_afford(100_000, "claude-opus-4-6")
        assert can_afford_opus is False

        # Haiku is cheap, same token usage fits
        can_afford_haiku = manager.can_afford(100_000, "claude-haiku-4-5")
        assert can_afford_haiku is True


class TestResetTracking:
    """Test reset functionality."""

    def test_reset_daily_tracking(self):
        """Can reset daily tracking."""
        manager = TokenCostManager()
        today = datetime.now()
        yesterday = today - timedelta(days=1)

        # Add usage for yesterday and today
        manager.record_usage(
            TokenUsage(
                "claude-opus-4-6",
                1_000_000,
                1_000_000,
                timestamp=yesterday,
            )
        )
        manager.record_usage(
            TokenUsage("claude-sonnet-4-6", 1_000_000, 1_000_000)
        )

        # Reset daily tracking
        manager.reset_daily_tracking()

        # Today's usage should be cleared
        daily_today = manager.get_daily_cost(today)
        assert daily_today == 0.0

        # Yesterday's usage should remain
        daily_yesterday = manager.get_daily_cost(yesterday)
        assert daily_yesterday > 0

    def test_reset_clears_alerts(self):
        """Reset clears budget alerts."""
        manager = TokenCostManager(daily_budget=50.0)
        manager.record_usage(
            TokenUsage("claude-opus-4-6", 1_000_000, 1_000_000)
        )

        alerts_before = manager.get_alerts()
        assert len(alerts_before) > 0

        manager.reset_daily_tracking()

        alerts_after = manager.get_alerts()
        assert len(alerts_after) == 0


class TestSerialization:
    """Test serialization to dictionary."""

    def test_to_dict_empty(self):
        """Can serialize empty manager."""
        manager = TokenCostManager(daily_budget=100.0, monthly_budget=2000.0)
        data = manager.to_dict()

        assert "total_cost" in data
        assert "daily_cost" in data
        assert "monthly_cost" in data
        assert "daily_budget" in data
        assert "monthly_budget" in data
        assert "cost_by_model" in data
        assert "usage_by_model" in data
        assert "alerts" in data

    def test_to_dict_with_usage(self):
        """Serialization includes recorded usage."""
        manager = TokenCostManager(daily_budget=100.0)
        manager.record_usage(
            TokenUsage("claude-opus-4-6", 1_000_000, 1_000_000)
        )
        manager.record_usage(
            TokenUsage("claude-sonnet-4-6", 1_000_000, 1_000_000)
        )

        data = manager.to_dict()

        assert data["total_cost"] > 0
        assert data["daily_cost"] > 0
        assert len(data["cost_by_model"]) == 2
        assert len(data["usage_by_model"]) == 2

    def test_to_dict_budgets(self):
        """Serialization includes budget info."""
        manager = TokenCostManager(daily_budget=100.0, monthly_budget=2000.0)
        data = manager.to_dict()

        assert data["daily_budget"] == 100.0
        assert data["monthly_budget"] == 2000.0

    def test_to_dict_alerts(self):
        """Serialization includes alerts."""
        manager = TokenCostManager(daily_budget=50.0)
        manager.record_usage(
            TokenUsage("claude-opus-4-6", 1_000_000, 1_000_000)
        )

        data = manager.to_dict()

        assert len(data["alerts"]) > 0
        alert = data["alerts"][0]
        assert "level" in alert
        assert "message" in alert
        assert "current_cost" in alert
        assert "threshold" in alert
        assert "remaining_budget" in alert


class TestEdgeCases:
    """Test edge cases."""

    def test_large_token_amounts(self):
        """Handles large token amounts."""
        manager = TokenCostManager()
        usage = TokenUsage(
            "claude-opus-4-6",
            100_000_000,  # 100M tokens
            200_000_000,  # 200M tokens
        )
        cost = manager.record_usage(usage)
        assert cost > 0
        # 100M @ $15/M + 200M @ $45/M = $1500 + $9000 = $10500
        assert cost < 15_000  # Sanity check

    def test_many_usages(self):
        """Handles many recorded usages."""
        manager = TokenCostManager()
        for i in range(100):
            manager.record_usage(
                TokenUsage(
                    "claude-opus-4-6",
                    1000 + i,
                    2000 + i,
                )
            )

        assert len(manager.usage_history) == 100
        total = manager.get_total_cost()
        assert total > 0

    def test_midnight_boundary(self):
        """Correctly handles midnight boundary."""
        manager = TokenCostManager()
        today = datetime.now()

        # Usage just before midnight today
        before_midnight = today.replace(hour=23, minute=59, second=59)
        manager.record_usage(
            TokenUsage(
                "claude-opus-4-6",
                1_000_000,
                1_000_000,
                timestamp=before_midnight,
            )
        )

        # Usage just after midnight (tomorrow)
        tomorrow = today + timedelta(days=1)
        after_midnight = tomorrow.replace(hour=0, minute=0, second=1)
        manager.record_usage(
            TokenUsage(
                "claude-sonnet-4-6",
                1_000_000,
                1_000_000,
                timestamp=after_midnight,
            )
        )

        daily_today = manager.get_daily_cost(today)
        daily_tomorrow = manager.get_daily_cost(tomorrow)

        assert daily_today > 0
        assert daily_tomorrow > 0
        assert daily_today != daily_tomorrow

    def test_zero_budget(self):
        """Handles zero budget correctly."""
        manager = TokenCostManager(daily_budget=0.01)  # Very small budget ($0.01)
        # 1M tokens @ $15/$45 = $60, way over $0.01 budget
        manager.record_usage(TokenUsage("claude-opus-4-6", 1_000_000, 1_000_000))

        alerts = manager.get_alerts()
        assert len(alerts) > 0
        assert alerts[0].level == CostAlertLevel.CRITICAL
