"""Tests for budget.py: BudgetGuard daily spending limits."""

from __future__ import annotations

import pytest
import pytest_asyncio

from bridge.budget import BudgetGuard
from bridge.database import Database


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def budget_db(tmp_path):
    """Return a connected + migrated Database for budget tests."""
    db = Database(tmp_path / "budget_test.db")
    await db.connect()
    await db.migrate()
    yield db
    await db.close()


# ---------------------------------------------------------------------------
# record()
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_record_positive_cost(budget_db):
    """Positive cost is recorded in budget_log."""
    guard = BudgetGuard(budget_db, daily_limit=10.0)
    await guard.record(0.05, session_id="s1", chat_id="c1")

    row = await budget_db.fetchone(
        "SELECT cost_usd, session_id, chat_id FROM budget_log LIMIT 1"
    )
    assert row is not None
    assert row[0] == pytest.approx(0.05)
    assert row[1] == "s1"
    assert row[2] == "c1"


@pytest.mark.asyncio
async def test_record_zero_cost_ignored(budget_db):
    """Zero cost is not recorded."""
    guard = BudgetGuard(budget_db, daily_limit=10.0)
    await guard.record(0.0)

    row = await budget_db.fetchone("SELECT COUNT(*) FROM budget_log")
    assert row[0] == 0


@pytest.mark.asyncio
async def test_record_negative_cost_ignored(budget_db):
    """Negative cost is not recorded."""
    guard = BudgetGuard(budget_db, daily_limit=10.0)
    await guard.record(-1.0)

    row = await budget_db.fetchone("SELECT COUNT(*) FROM budget_log")
    assert row[0] == 0


# ---------------------------------------------------------------------------
# check()
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_check_unlimited_budget(budget_db):
    """daily_limit=0 means unlimited — always allowed."""
    guard = BudgetGuard(budget_db, daily_limit=0.0)
    await guard.record(100.0)

    status = await guard.check()
    assert status["allowed"] is True
    assert status["remaining"] == float("inf")
    assert status["alert_level"] == "ok"
    assert status["daily_limit"] == 0.0


@pytest.mark.asyncio
async def test_check_within_budget(budget_db):
    """Spending under the limit is allowed."""
    guard = BudgetGuard(budget_db, daily_limit=10.0)
    await guard.record(2.0)

    status = await guard.check()
    assert status["allowed"] is True
    assert status["remaining"] == pytest.approx(8.0)
    assert status["spent_today"] == pytest.approx(2.0)


@pytest.mark.asyncio
async def test_check_exceeded_budget(budget_db):
    """Spending at or over the limit is not allowed."""
    guard = BudgetGuard(budget_db, daily_limit=5.0)
    await guard.record(5.0)

    status = await guard.check()
    assert status["allowed"] is False
    assert status["remaining"] == 0
    assert status["alert_level"] == "exceeded"


# ---------------------------------------------------------------------------
# alert_level thresholds
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_alert_level_ok(budget_db):
    """Below 50% of budget is 'ok'."""
    guard = BudgetGuard(budget_db, daily_limit=10.0)
    await guard.record(4.0)  # 40%

    status = await guard.check()
    assert status["alert_level"] == "ok"


@pytest.mark.asyncio
async def test_alert_level_warning(budget_db):
    """50-75% of budget is 'warning'."""
    guard = BudgetGuard(budget_db, daily_limit=10.0)
    await guard.record(6.0)  # 60%

    status = await guard.check()
    assert status["alert_level"] == "warning"


@pytest.mark.asyncio
async def test_alert_level_critical(budget_db):
    """75-100% of budget is 'critical'."""
    guard = BudgetGuard(budget_db, daily_limit=10.0)
    await guard.record(8.0)  # 80%

    status = await guard.check()
    assert status["alert_level"] == "critical"


@pytest.mark.asyncio
async def test_alert_level_exceeded(budget_db):
    """>=100% of budget is 'exceeded'."""
    guard = BudgetGuard(budget_db, daily_limit=10.0)
    await guard.record(10.0)  # 100%

    status = await guard.check()
    assert status["alert_level"] == "exceeded"


# ---------------------------------------------------------------------------
# should_alert() — transition detection
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_should_alert_transition(budget_db):
    """Alert fires on level transition (ok -> warning), not on repeat."""
    guard = BudgetGuard(budget_db, daily_limit=10.0)

    # Start at ok — no alert
    msg = await guard.should_alert()
    assert msg is None

    # Move to warning (60%)
    await guard.record(6.0)
    msg = await guard.should_alert()
    assert msg is not None
    assert "warning" in msg

    # Same level again — no duplicate alert
    msg = await guard.should_alert()
    assert msg is None


# ---------------------------------------------------------------------------
# get_status()
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_status(budget_db):
    """get_status returns formatted budget info."""
    guard = BudgetGuard(budget_db, daily_limit=10.0)
    await guard.record(3.0)

    status = await guard.get_status()
    assert status["daily_limit"] == 10.0
    assert status["spent_today"] == pytest.approx(3.0)
    assert status["remaining"] == pytest.approx(7.0)
    assert status["alert_level"] == "ok"


@pytest.mark.asyncio
async def test_get_status_unlimited(budget_db):
    """get_status with unlimited budget returns 'unlimited' string."""
    guard = BudgetGuard(budget_db, daily_limit=0.0)

    status = await guard.get_status()
    assert status["remaining"] == "unlimited"
