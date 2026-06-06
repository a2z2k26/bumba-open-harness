"""Tests for MS1.4: Staleness Detection."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from bridge.staleness import (
    EXEMPT_CATEGORIES,
    KNOWLEDGE_FRESHNESS_THRESHOLDS,
    SERVICE_INTERVALS,
    is_service_stale,
)


class _FakeRow:
    """Minimal row object supporting both index and key access (like aiosqlite.Row)."""

    def __init__(self, category: str, last_update: str):
        self._data = (category, last_update)
        self._map = {"category": category, "last_update": last_update}

    def __getitem__(self, key):
        if isinstance(key, int):
            return self._data[key]
        return self._map[key]


class TestServiceStaleness:
    """Tests for is_service_stale()."""

    def test_stale_when_2x_interval_passed(self):
        """Service is stale when last run was more than 2x interval ago."""
        # briefing interval is 86400s (24h), so 3 days ago is well past 2x
        three_days_ago = (
            datetime.now(timezone.utc) - timedelta(days=3)
        ).isoformat()
        assert is_service_stale(three_days_ago, "briefing") is True

    def test_not_stale_within_interval(self):
        """Service is not stale when last run was within the interval."""
        # briefing interval is 86400s (24h), 12 hours ago is within 1x
        twelve_hours_ago = (
            datetime.now(timezone.utc) - timedelta(hours=12)
        ).isoformat()
        assert is_service_stale(twelve_hours_ago, "briefing") is False

    def test_not_stale_just_inside_2x(self):
        """Service is not stale when last run was just inside 2x interval."""
        # calendar interval is 900s (15 min), 25 min ago is within 2x (30 min)
        twenty_five_min_ago = (
            datetime.now(timezone.utc) - timedelta(minutes=25)
        ).isoformat()
        assert is_service_stale(twenty_five_min_ago, "calendar") is False

    def test_stale_just_outside_2x(self):
        """Service is stale when last run was just outside 2x interval."""
        # calendar interval is 900s (15 min), 31 min ago is past 2x (30 min)
        thirty_one_min_ago = (
            datetime.now(timezone.utc) - timedelta(minutes=31)
        ).isoformat()
        assert is_service_stale(thirty_one_min_ago, "calendar") is True

    def test_no_last_run_is_stale(self):
        """Service with no last_run should be considered stale."""
        assert is_service_stale(None, "briefing") is True
        assert is_service_stale(None, "email") is True
        assert is_service_stale(None, "calendar") is True

    def test_no_last_run_unknown_service_not_stale(self):
        """Unknown service with no last_run should not be considered stale."""
        assert is_service_stale(None, "nonexistent_service") is False

    def test_unknown_service_never_stale(self):
        """A service not in SERVICE_INTERVALS is never considered stale."""
        ancient = (
            datetime.now(timezone.utc) - timedelta(days=365)
        ).isoformat()
        assert is_service_stale(ancient, "nonexistent_service") is False

    def test_all_known_services_have_intervals(self):
        """All defined services must have positive intervals."""
        expected = {
            "briefing", "email", "calendar", "knowledge_review",
            "job_search", "job_search_execute", "checkin",
        }
        assert set(SERVICE_INTERVALS.keys()) == expected
        for name, interval in SERVICE_INTERVALS.items():
            assert interval > 0, f"{name} has non-positive interval"

    def test_invalid_iso_string_is_stale(self):
        """Invalid ISO date string should be treated as stale."""
        assert is_service_stale("not-a-date", "briefing") is True

    def test_naive_timestamp_treated_as_utc(self):
        """Naive timestamp (no timezone) should be treated as UTC."""
        one_hour_ago = (
            datetime.now(timezone.utc) - timedelta(hours=1)
        ).strftime("%Y-%m-%dT%H:%M:%S")  # naive format
        # calendar interval is 900s, 1 hour is past 2x (30 min)
        assert is_service_stale(one_hour_ago, "calendar") is True
        # briefing interval is 86400s, 1 hour is within 1x
        assert is_service_stale(one_hour_ago, "briefing") is False


class TestKnowledgeFreshness:
    """Tests for knowledge freshness checking in HealthServer."""

    @pytest.mark.asyncio
    async def test_stale_category_detected(self):
        """A category with old data should appear in stale_categories."""
        from bridge.health import HealthServer

        app = MagicMock()
        db = AsyncMock()
        old_date = (
            datetime.now(timezone.utc) - timedelta(days=14)
        ).isoformat()

        db.fetchall = AsyncMock(return_value=[_FakeRow("project", old_date)])
        app._db = db

        server = HealthServer(app)
        result = await server._check_knowledge_freshness()

        assert "project" in result["stale_categories"]
        assert result["total_categories"] == 1

    @pytest.mark.asyncio
    async def test_ok_category_not_stale(self):
        """A category with recent data should not appear in stale_categories."""
        from bridge.health import HealthServer

        app = MagicMock()
        db = AsyncMock()
        recent_date = (
            datetime.now(timezone.utc) - timedelta(days=1)
        ).isoformat()

        db.fetchall = AsyncMock(return_value=[_FakeRow("project", recent_date)])
        app._db = db

        server = HealthServer(app)
        result = await server._check_knowledge_freshness()

        assert result["stale_categories"] == []
        assert result["total_categories"] == 1

    @pytest.mark.asyncio
    async def test_exempt_categories_skipped(self):
        """Exempt categories (preference, person) should not be checked."""
        from bridge.health import HealthServer

        app = MagicMock()
        db = AsyncMock()
        ancient_date = (
            datetime.now(timezone.utc) - timedelta(days=365)
        ).isoformat()

        rows = [_FakeRow(cat, ancient_date) for cat in EXEMPT_CATEGORIES]
        db.fetchall = AsyncMock(return_value=rows)
        app._db = db

        server = HealthServer(app)
        result = await server._check_knowledge_freshness()

        # Exempt categories should not appear in stale list nor count toward total
        assert result["stale_categories"] == []
        assert result["total_categories"] == 0

    @pytest.mark.asyncio
    async def test_mixed_categories(self):
        """Mix of stale, fresh, and exempt categories."""
        from bridge.health import HealthServer

        app = MagicMock()
        db = AsyncMock()

        now = datetime.now(timezone.utc)
        stale_date = (now - timedelta(days=40)).isoformat()   # stale for process (30d)
        fresh_date = (now - timedelta(days=2)).isoformat()     # fresh for project (7d)
        exempt_date = (now - timedelta(days=500)).isoformat()  # exempt (preference)

        db.fetchall = AsyncMock(return_value=[
            _FakeRow("process", stale_date),
            _FakeRow("project", fresh_date),
            _FakeRow("preference", exempt_date),
        ])
        app._db = db

        server = HealthServer(app)
        result = await server._check_knowledge_freshness()

        assert "process" in result["stale_categories"]
        assert "project" not in result["stale_categories"]
        assert "preference" not in result["stale_categories"]
        assert result["total_categories"] == 2  # process + project (not preference)

    @pytest.mark.asyncio
    async def test_no_db_returns_unknown(self):
        """When database is not initialized, return unknown status."""
        from bridge.health import HealthServer

        app = MagicMock()
        app._db = None

        server = HealthServer(app)
        result = await server._check_knowledge_freshness()

        assert result["status"] == "unknown"

    @pytest.mark.asyncio
    async def test_freshness_thresholds_complete(self):
        """All non-exempt categories should have freshness thresholds."""
        # Verify the threshold dict covers expected categories
        expected = {"project", "decision", "process", "learning", "tool", "reference"}
        assert set(KNOWLEDGE_FRESHNESS_THRESHOLDS.keys()) == expected

        # Verify exempt categories are not in thresholds
        for cat in EXEMPT_CATEGORIES:
            assert cat not in KNOWLEDGE_FRESHNESS_THRESHOLDS
