"""Tests for FunnelPostService (Z2-S2.1 FR-005)."""

from __future__ import annotations

import json
import shutil
import tempfile
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import pytest

from bridge.services.funnel_post import FunnelPostService
from bridge.services.result import (
    SERVICE_NARRATIONS,
    SERVICE_SCHEDULES,
    ServiceResult,
)
from job_search.funnel import FunnelDay, FunnelStore


@pytest.fixture
def tmp_dir():
    d = tempfile.mkdtemp()
    yield Path(d)
    shutil.rmtree(d, ignore_errors=True)


@pytest.fixture
def post_time_now():
    """Freeze time inside the FunnelPostService should_run() window (22:00)."""
    target = datetime.now().replace(hour=22, minute=0, second=0, microsecond=0)
    with patch("bridge.services.funnel_post.datetime") as mock_dt:
        mock_dt.now.return_value = target
        mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
        yield target


class TestFunnelPostServiceSchedule:
    """should_run() gating — only fires inside the 22:00 ± 30min window, once per day."""

    def test_runs_inside_window(self, tmp_dir, post_time_now):
        svc = FunnelPostService(tmp_dir, chat_id="123")
        assert svc.should_run() is True

    def test_skips_outside_window(self, tmp_dir):
        svc = FunnelPostService(tmp_dir, chat_id="123")
        off_window = datetime.now().replace(hour=10, minute=0, second=0, microsecond=0)
        with patch("bridge.services.funnel_post.datetime") as mock_dt:
            mock_dt.now.return_value = off_window
            assert svc.should_run() is False

    def test_skips_when_already_posted_today(self, tmp_dir, post_time_now):
        svc = FunnelPostService(tmp_dir, chat_id="123")
        # Mark today as already posted
        state = svc.load_state(filename="funnel_post-state.json")
        state["last_post_date"] = post_time_now.strftime("%Y-%m-%d")
        svc.save_state(state, filename="funnel_post-state.json")

        assert svc.should_run() is False


class TestFunnelPostServiceRun:
    """run() path — OK with work_items=1, SKIP with skip_reason, FAIL."""

    def test_skip_outside_window_returns_skip_result(self, tmp_dir):
        svc = FunnelPostService(tmp_dir, chat_id="123")
        off_window = datetime.now().replace(hour=10, minute=0, second=0, microsecond=0)
        with patch("bridge.services.funnel_post.datetime") as mock_dt:
            mock_dt.now.return_value = off_window

            result = svc.run()

        assert isinstance(result, ServiceResult)
        assert result.ok is True
        assert result.work_items == 0
        assert result.skip_reason == "outside_window_or_already_ran"

    def test_empty_day_returns_no_activity_skip(self, tmp_dir, post_time_now):
        svc = FunnelPostService(tmp_dir, chat_id="123")
        # No FunnelStore data — store.get() returns zeroed FunnelDay
        result = svc.run()

        assert result.ok is True
        assert result.work_items == 0
        assert result.skip_reason == "no_activity"
        # No-activity day still delivers a message (so the operator knows
        # the service ran) but marks work_items=0.
        messages = list((tmp_dir / "service_messages").glob("funnel-post_*.json"))
        assert len(messages) == 1
        msg = json.loads(messages[0].read_text())
        assert "no_activity" in msg["text"].lower() or "No activity" in msg["text"]

    def test_non_empty_day_posts_summary(self, tmp_dir, post_time_now):
        # Seed a non-zero day
        store = FunnelStore(tmp_dir)
        today_key = post_time_now.strftime("%Y-%m-%d")
        day = FunnelDay(scraped=120, deduped=98, covered=15, submitted=12, staged=10,
                        approved=4, sent=3, replied=1)
        store.set_day(today_key, day)

        svc = FunnelPostService(tmp_dir, chat_id="123")
        result = svc.run()

        assert result.ok is True
        assert result.work_items == 1
        assert result.skip_reason is None
        assert result.narration is not None
        assert "scraped=120" in result.narration

        messages = list((tmp_dir / "service_messages").glob("funnel-post_*.json"))
        assert len(messages) == 1
        msg = json.loads(messages[0].read_text())
        assert "Job Search Funnel" in msg["text"]
        assert "120" in msg["text"]
        assert "  3 " in msg["text"] or "3" in msg["text"]  # sent

    def test_second_run_same_day_skips(self, tmp_dir, post_time_now):
        svc = FunnelPostService(tmp_dir, chat_id="123")
        first = svc.run()
        second = svc.run()

        assert first.skip_reason in (None, "no_activity")
        assert second.skip_reason == "outside_window_or_already_ran"


class TestFunnelPostRegistration:
    """FunnelPostService must be registered with the runner + narration maps."""

    def test_registered_in_service_map(self):
        from bridge.services.runner import SERVICE_MAP, SERVICE_TIMEOUTS, SERVICE_ALIASES

        assert "funnel_post" in SERVICE_MAP
        module_path, class_name = SERVICE_MAP["funnel_post"]
        assert module_path == "bridge.services.funnel_post"
        assert class_name == "FunnelPostService"
        assert SERVICE_TIMEOUTS["funnel_post"] > 0
        assert SERVICE_ALIASES["funnel-post"] == "funnel_post"

    def test_has_narration_and_schedule(self):
        assert "funnel_post" in SERVICE_NARRATIONS
        assert "funnel_post" in SERVICE_SCHEDULES
        assert "22:00" in SERVICE_SCHEDULES["funnel_post"]

    def test_plist_exists(self):
        plist = Path(__file__).parent.parent / "scripts" / "com.bumba.agent-funnel-post.plist"
        assert plist.exists(), f"Expected plist at {plist}"
        content = plist.read_text()
        assert "<string>funnel_post</string>" in content
        assert "<integer>22</integer>" in content
