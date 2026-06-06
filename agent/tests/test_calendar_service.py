"""Tests for bridge.services.calendar."""

from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest

from bridge.services.calendar import CalendarService

EST = ZoneInfo("America/New_York")


@pytest.fixture
def calendar_service(tmp_path):
    """Create a CalendarService with test paths."""
    data_dir = tmp_path / "data"
    data_dir.mkdir(exist_ok=True)
    return CalendarService(
        data_dir=data_dir,
        chat_id="test-chat-123",
        morning_hour=datetime.now(EST).hour,
        morning_minute=datetime.now(EST).minute,
    )


class TestCalendarMorningDigest:
    """Morning digest compilation."""

    def test_should_run_morning_within_window(self, calendar_service):
        assert calendar_service.should_run_morning() is True

    def test_should_run_morning_dedup(self, calendar_service):
        state = {"last_morning_date": datetime.now(EST).strftime("%Y-%m-%d")}
        calendar_service.save_state(state, filename="calendar-state.json")
        assert calendar_service.should_run_morning() is False

    def test_compile_with_events(self, calendar_service):
        mock_events = [
            {
                "id": "1",
                "title": "Team standup",
                "start": (datetime.now(EST) + timedelta(hours=1)).isoformat(),
                "end": (datetime.now(EST) + timedelta(hours=2)).isoformat(),
                "location": "Zoom",
                "all_day": False,
            },
        ]
        with patch("bridge.services.calendar_interface.get_today_events", return_value=mock_events), \
             patch("bridge.services.calcom_interface.get_upcoming_bookings", return_value=[]):
            result = calendar_service.compile_morning_digest()
            assert result is not None
            assert "Team standup" in result
            assert "Zoom" in result

    def test_compile_empty_calendar(self, calendar_service):
        with patch("bridge.services.calendar_interface.get_today_events", return_value=[]), \
             patch("bridge.services.calcom_interface.get_upcoming_bookings", return_value=[]):
            result = calendar_service.compile_morning_digest()
            assert result is None

    def test_compile_with_calcom_bookings(self, calendar_service):
        bookings = [{
            "id": 42,
            "title": "Discovery call",
            "start": (datetime.now(EST) + timedelta(hours=3)).isoformat(),
            "end": (datetime.now(EST) + timedelta(hours=4)).isoformat(),
            "attendee_name": "Jane Doe",
            "attendee_email": "jane@example.com",
            "status": "accepted",
            "meeting_url": "",
        }]
        with patch("bridge.services.calendar_interface.get_today_events", return_value=[]), \
             patch("bridge.services.calcom_interface.get_upcoming_bookings", return_value=bookings):
            result = calendar_service.compile_morning_digest()
            assert result is not None
            assert "Discovery call" in result
            assert "Jane Doe" in result


class TestConflictDetection:
    """Overlapping event detection."""

    def test_detects_overlap(self, calendar_service):
        now = datetime.now(EST)
        events = [
            {"id": "1", "title": "Meeting A", "start": now.isoformat(), "end": (now + timedelta(hours=2)).isoformat(), "all_day": False},
            {"id": "2", "title": "Meeting B", "start": (now + timedelta(hours=1)).isoformat(), "end": (now + timedelta(hours=3)).isoformat(), "all_day": False},
        ]
        conflicts = calendar_service._detect_conflicts(events)
        assert len(conflicts) == 1

    def test_no_conflict(self, calendar_service):
        now = datetime.now(EST)
        events = [
            {"id": "1", "title": "A", "start": now.isoformat(), "end": (now + timedelta(hours=1)).isoformat(), "all_day": False},
            {"id": "2", "title": "B", "start": (now + timedelta(hours=2)).isoformat(), "end": (now + timedelta(hours=3)).isoformat(), "all_day": False},
        ]
        conflicts = calendar_service._detect_conflicts(events)
        assert len(conflicts) == 0

    def test_ignores_all_day(self, calendar_service):
        now = datetime.now(EST)
        events = [
            {"id": "1", "title": "Holiday", "start": now.isoformat(), "end": (now + timedelta(days=1)).isoformat(), "all_day": True},
            {"id": "2", "title": "Meeting", "start": now.isoformat(), "end": (now + timedelta(hours=1)).isoformat(), "all_day": False},
        ]
        conflicts = calendar_service._detect_conflicts(events)
        assert len(conflicts) == 0


class TestUpcomingAlerts:
    """Event alerting logic."""

    def test_alerts_upcoming_event(self, calendar_service):
        now = datetime.now(EST)
        upcoming = [{
            "id": "alert-1",
            "title": "Standup",
            "start": (now + timedelta(minutes=15)).isoformat(),
            "end": (now + timedelta(minutes=30)).isoformat(),
            "location": "",
        }]
        with patch("bridge.services.calendar_interface.get_upcoming_events", return_value=upcoming):
            alerts = calendar_service.check_upcoming_alerts()
            assert len(alerts) == 1
            assert "Standup" in alerts[0]

    def test_no_duplicate_alerts(self, calendar_service):
        now = datetime.now(EST)
        upcoming = [{
            "id": "alert-2",
            "title": "Meeting",
            "start": (now + timedelta(minutes=10)).isoformat(),
            "end": (now + timedelta(minutes=40)).isoformat(),
            "location": "",
        }]
        with patch("bridge.services.calendar_interface.get_upcoming_events", return_value=upcoming):
            calendar_service.check_upcoming_alerts()
            # Second check should not alert again
            alerts = calendar_service.check_upcoming_alerts()
            assert len(alerts) == 0

    def test_state_persistence(self, calendar_service):
        state = calendar_service.load_state(filename="calendar-state.json")
        # Empty state now includes REQUIRED_STATE_FIELDS defaults
        assert state.get("last_alert_check") is None
        with patch("bridge.services.calendar_interface.get_upcoming_events", return_value=[]):
            calendar_service.check_upcoming_alerts()
        state = calendar_service.load_state(filename="calendar-state.json")
        assert "last_alert_check" in state
