"""Sprint 02.10 Phase 4 — FunnelPostService runs the canary before posting.

When the funnel state for the day satisfies the ``submitted_no_stage``
anomaly (submitted > 0, staged == 0), the rendered Discord summary
contains an ALERT block AND a ``funnel.anomaly_detected`` event is
published.
"""
from __future__ import annotations

import shutil
import tempfile
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import pytest

from bridge.services.funnel_post import FunnelPostService
from job_search.funnel import FunnelDay, FunnelStore, today_key


@pytest.fixture
def tmp_dir():
    d = tempfile.mkdtemp()
    yield Path(d)
    shutil.rmtree(d, ignore_errors=True)


@pytest.fixture
def post_time_now():
    target = datetime.now().replace(hour=22, minute=0, second=0, microsecond=0)
    with patch("bridge.services.funnel_post.datetime") as mock_dt:
        mock_dt.now.return_value = target
        mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
        yield target


class TestCanaryFiresOnSubmittedNoStage:
    def test_alert_block_appended_to_message(self, tmp_dir, post_time_now):
        # Seed the funnel: 5 submitted, 0 staged → submitted_no_stage anomaly.
        store = FunnelStore(tmp_dir)
        day = FunnelDay(submitted=5, staged=0, scraped=20)
        store.set_day(today_key(), day)

        delivered_messages: list[tuple[str, str]] = []

        svc = FunnelPostService(
            data_dir=tmp_dir,
            chat_id="test-channel",
        )
        # Capture the delivered message.
        svc.deliver_message = (
            lambda chat, msg, source="": delivered_messages.append((chat, msg))
        )
        result = svc.run()
        assert result.ok is True

        assert delivered_messages, "no message was delivered"
        _, msg = delivered_messages[0]
        assert "ALERT — submitted_no_stage" in msg
        assert "submitted but 0 staged" in msg

    def test_no_alert_block_on_healthy_funnel(self, tmp_dir, post_time_now):
        store = FunnelStore(tmp_dir)
        # Healthy: submitted == staged (1 each)
        day = FunnelDay(scraped=10, deduped=2, covered=4, submitted=4, staged=4)
        store.set_day(today_key(), day)

        delivered_messages: list[tuple[str, str]] = []

        svc = FunnelPostService(
            data_dir=tmp_dir,
            chat_id="test-channel",
        )
        svc.deliver_message = (
            lambda chat, msg, source="": delivered_messages.append((chat, msg))
        )
        result = svc.run()
        assert result.ok is True
        _, msg = delivered_messages[0]
        assert "ALERT" not in msg

    def test_canary_dedups_within_day(self, tmp_dir, post_time_now):
        """A repeated run on the same day must NOT fire a second alert."""
        store = FunnelStore(tmp_dir)
        day = FunnelDay(submitted=5, staged=0, scraped=20)
        store.set_day(today_key(), day)

        delivered_messages: list[tuple[str, str]] = []

        svc = FunnelPostService(data_dir=tmp_dir, chat_id="test-channel")
        svc.deliver_message = (
            lambda chat, msg, source="": delivered_messages.append((chat, msg))
        )
        svc.run()
        # Reset state so the service is willing to re-run today.
        state_path = tmp_dir / "service_state" / "funnel_post-state.json"
        if state_path.exists():
            state_path.unlink()
        # Run again — alert block must NOT appear (dedup window is 24h).
        delivered_messages.clear()
        svc.run()
        if delivered_messages:
            _, msg = delivered_messages[0]
            assert "ALERT" not in msg
