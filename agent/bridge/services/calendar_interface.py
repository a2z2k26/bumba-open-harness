"""Google Calendar API interface for reading calendar events.

Uses same google-auth credentials as Gmail (with calendar.readonly scope added).
Returns typed dicts for consistent downstream use.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import TypedDict
from zoneinfo import ZoneInfo

log = logging.getLogger(__name__)

EST = ZoneInfo("America/New_York")


class CalendarEvent(TypedDict, total=False):
    id: str
    title: str
    start: str
    end: str
    location: str
    attendees: list[str]
    description: str
    calendar_name: str
    all_day: bool


def _get_service(account: str = "agent"):
    """Build Google Calendar API service."""
    try:
        from googleapiclient.discovery import build
        from .gmail_auth import get_gmail_credentials
    except ImportError:
        log.error("google-api-python-client not installed")
        return None

    creds = get_gmail_credentials(account)
    if not creds:
        return None

    return build("calendar", "v3", credentials=creds)


def _parse_event(event: dict, calendar_name: str = "") -> CalendarEvent:
    """Parse a Google Calendar API event into our typed dict."""
    start = event.get("start", {})
    end = event.get("end", {})
    all_day = "date" in start

    return CalendarEvent(
        id=event.get("id", ""),
        title=event.get("summary", "(no title)"),
        start=start.get("dateTime", start.get("date", "")),
        end=end.get("dateTime", end.get("date", "")),
        location=event.get("location", ""),
        attendees=[a.get("email", "") for a in event.get("attendees", [])],
        description=event.get("description", ""),
        calendar_name=calendar_name,
        all_day=all_day,
    )


def get_today_events(account: str = "agent") -> list[CalendarEvent]:
    """Get all events for today."""
    service = _get_service(account)
    if not service:
        return []

    now = datetime.now(EST)
    start_of_day = now.replace(hour=0, minute=0, second=0, microsecond=0)
    end_of_day = start_of_day + timedelta(days=1)

    try:
        # Get calendar list first
        cal_list = service.calendarList().list().execute()
        events: list[CalendarEvent] = []

        for cal in cal_list.get("items", []):
            cal_id = cal["id"]
            cal_name = cal.get("summary", cal_id)

            result = service.events().list(
                calendarId=cal_id,
                timeMin=start_of_day.isoformat(),
                timeMax=end_of_day.isoformat(),
                singleEvents=True,
                orderBy="startTime",
            ).execute()

            for event in result.get("items", []):
                events.append(_parse_event(event, calendar_name=cal_name))

        # Sort by start time
        events.sort(key=lambda e: e.get("start", ""))
        return events

    except Exception as e:
        log.error("Failed to get today's events for '%s': %s", account, e)
        return []


def get_upcoming_events(account: str = "agent", hours: int = 4) -> list[CalendarEvent]:
    """Get events in the next N hours."""
    service = _get_service(account)
    if not service:
        return []

    now = datetime.now(EST)
    end_time = now + timedelta(hours=hours)

    try:
        result = service.events().list(
            calendarId="primary",
            timeMin=now.isoformat(),
            timeMax=end_time.isoformat(),
            singleEvents=True,
            orderBy="startTime",
        ).execute()

        return [_parse_event(e) for e in result.get("items", [])]

    except Exception as e:
        log.error("Failed to get upcoming events: %s", e)
        return []


def get_week_overview(account: str = "agent") -> list[CalendarEvent]:
    """Get events for the current week (Mon-Sun)."""
    service = _get_service(account)
    if not service:
        return []

    now = datetime.now(EST)
    start_of_week = now - timedelta(days=now.weekday())
    start_of_week = start_of_week.replace(hour=0, minute=0, second=0, microsecond=0)
    end_of_week = start_of_week + timedelta(days=7)

    try:
        result = service.events().list(
            calendarId="primary",
            timeMin=start_of_week.isoformat(),
            timeMax=end_of_week.isoformat(),
            singleEvents=True,
            orderBy="startTime",
        ).execute()

        return [_parse_event(e) for e in result.get("items", [])]

    except Exception as e:
        log.error("Failed to get week overview: %s", e)
        return []
