"""Tests for budget pressure signal generation."""

from __future__ import annotations

import pytest
import pytest_asyncio

from bridge.budget import BudgetGuard
from bridge.database import Database


@pytest_asyncio.fixture
async def budget_db(tmp_path):
    db = Database(tmp_path / "pressure_test.db")
    await db.connect()
    await db.migrate()
    yield db
    await db.close()


# ---------------------------------------------------------------------------
# get_pressure_signal()
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_no_pressure_below_50(budget_db):
    """No pressure signal when spending is below 50%."""
    guard = BudgetGuard(budget_db, daily_limit=10.0)
    await guard.record(4.0)  # 40%

    status = await guard.check()
    signal = guard.get_pressure_signal(status)
    assert signal is None


@pytest.mark.asyncio
async def test_caution_at_50(budget_db):
    """Caution signal at 50% spending."""
    guard = BudgetGuard(budget_db, daily_limit=10.0)
    await guard.record(5.0)  # 50%

    status = await guard.check()
    signal = guard.get_pressure_signal(status)
    assert signal is not None
    assert "[BUDGET:" in signal
    assert "Be mindful of cost" in signal
    assert "$5.00" in signal


@pytest.mark.asyncio
async def test_caution_at_60(budget_db):
    """Caution signal at 60% spending (between 50% and 75%)."""
    guard = BudgetGuard(budget_db, daily_limit=10.0)
    await guard.record(6.0)  # 60%

    status = await guard.check()
    signal = guard.get_pressure_signal(status)
    assert signal is not None
    assert "[BUDGET:" in signal
    assert "WARNING" not in signal


@pytest.mark.asyncio
async def test_warning_at_75(budget_db):
    """Warning signal at 75% spending."""
    guard = BudgetGuard(budget_db, daily_limit=10.0)
    await guard.record(7.5)  # 75%

    status = await guard.check()
    signal = guard.get_pressure_signal(status)
    assert signal is not None
    assert "[BUDGET WARNING:" in signal
    assert "Wrap up" in signal


@pytest.mark.asyncio
async def test_warning_at_90(budget_db):
    """Warning signal at 90% spending."""
    guard = BudgetGuard(budget_db, daily_limit=10.0)
    await guard.record(9.0)  # 90%

    status = await guard.check()
    signal = guard.get_pressure_signal(status)
    assert signal is not None
    assert "[BUDGET WARNING:" in signal
    assert "$1.00 remaining" in signal


@pytest.mark.asyncio
async def test_no_pressure_unlimited(budget_db):
    """No pressure signal when budget is unlimited (daily_limit=0)."""
    guard = BudgetGuard(budget_db, daily_limit=0.0)
    await guard.record(100.0)

    status = await guard.check()
    signal = guard.get_pressure_signal(status)
    assert signal is None


@pytest.mark.asyncio
async def test_pressure_includes_remaining(budget_db):
    """Pressure signal includes remaining dollar amount."""
    guard = BudgetGuard(budget_db, daily_limit=20.0)
    await guard.record(16.0)  # 80%

    status = await guard.check()
    signal = guard.get_pressure_signal(status)
    assert "$4.00 remaining" in signal
