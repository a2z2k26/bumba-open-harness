"""Tests for bridge.services.checkin."""

from __future__ import annotations

import json
import time
from datetime import datetime, timedelta
from unittest.mock import patch

import pytest

from bridge.services.checkin import CheckinContext, CheckinService


@pytest.fixture
def checkin_service(tmp_path, migrated_db):
    """Create a CheckinService with test paths."""
    data_dir = tmp_path / "data"
    data_dir.mkdir(exist_ok=True)
    svc = CheckinService(
        data_dir=data_dir,
        db_path=migrated_db.db_path,
        chat_id="test-chat-123",
        active_hours_start=0,
        active_hours_end=24,
        minimum_gap=0,
    )
    return svc


class TestCheckinContext:
    """Context gathering from DB."""

    @pytest.mark.asyncio
    async def test_gather_empty_db(self, migrated_db):
        ctx = CheckinContext.gather(migrated_db.db_path)
        assert ctx.pending_queue_count == 0
        assert ctx.recent_error_count == 0
        assert ctx.overdue_goals == []

    @pytest.mark.asyncio
    async def test_gather_with_messages(self, migrated_db):
        await migrated_db.execute(
            """INSERT INTO conversations (session_id, chat_id, role, content)
               VALUES ('s1', 'c1', 'user', 'hello')"""
        )
        await migrated_db.commit()
        ctx = CheckinContext.gather(migrated_db.db_path)
        assert ctx.last_message_age_hours < 1

    @pytest.mark.asyncio
    async def test_gather_with_overdue_goal(self, migrated_db):
        past = (datetime.now() - timedelta(days=1)).isoformat()
        goal_data = json.dumps({"description": "Overdue task", "deadline": past, "status": "active"})
        await migrated_db.execute(
            """INSERT INTO knowledge (key, value, category)
               VALUES ('goal:overdue-task', ?, 'project')""",
            (goal_data,),
        )
        await migrated_db.commit()

        ctx = CheckinContext.gather(migrated_db.db_path)
        assert len(ctx.overdue_goals) == 1
        assert ctx.overdue_goals[0]["description"] == "Overdue task"

    def test_to_prompt_context(self):
        ctx = CheckinContext(
            last_message_age_hours=5.0,
            overdue_goals=[{"description": "Ship v2"}],
            recent_error_count=3,
        )
        text = ctx.to_prompt_context()
        assert "5.0" in text
        assert "Ship v2" in text


class TestCheckinService:
    """Check-in service logic."""

    def test_should_run_respects_active_hours(self, tmp_path, migrated_db):
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        svc = CheckinService(
            data_dir=data_dir,
            db_path=migrated_db.db_path,
            chat_id="test",
            active_hours_start=0,
            active_hours_end=1,  # Only 00:00-01:00
        )
        now = datetime.now()
        if now.hour >= 1:
            assert svc.should_run() is False

    def test_should_run_respects_snooze(self, checkin_service):
        state = {"snooze_until": time.time() + 3600}
        checkin_service.save_state(state, filename="checkin-state.json")
        assert checkin_service.should_run() is False

    def test_should_run_respects_minimum_gap(self, tmp_path, migrated_db):
        data_dir = tmp_path / "data2"
        data_dir.mkdir()
        svc = CheckinService(
            data_dir=data_dir,
            db_path=migrated_db.db_path,
            chat_id="test",
            active_hours_start=0,
            active_hours_end=24,
            minimum_gap=99999,
        )
        state = {"last_checkin_time": time.time()}
        svc.save_state(state, filename="checkin-state.json")
        assert svc.should_run() is False

    def test_decide_silence_when_recent_contact(self):
        ctx = CheckinContext(last_message_age_hours=1.0)
        svc = CheckinService.__new__(CheckinService)
        result = svc.decide(ctx)
        assert result is None

    def test_decide_casual_when_no_contact(self):
        ctx = CheckinContext(last_message_age_hours=5.0)
        svc = CheckinService.__new__(CheckinService)
        result = svc.decide(ctx)
        assert result is not None
        assert "URGENT" not in result

    def test_decide_urgent_when_overdue(self):
        ctx = CheckinContext(
            last_message_age_hours=5.0,
            overdue_goals=[{"description": "Ship v2"}],
        )
        svc = CheckinService.__new__(CheckinService)
        result = svc.decide(ctx)
        assert result is not None
        assert "URGENT" in result

    def test_decide_call_request_when_unanswered(self):
        ctx = CheckinContext(
            last_message_age_hours=10.0,
            overdue_goals=[{"description": "Critical deploy"}],
            unanswered_checkins=3,
        )
        svc = CheckinService.__new__(CheckinService)
        result = svc.decide(ctx)
        assert "CALL_REQUEST" in result

    def test_run_sends_message(self, checkin_service):
        # Inject old message time so check-in triggers
        with patch.object(CheckinContext, "gather", return_value=CheckinContext(last_message_age_hours=5.0)):
            result = checkin_service.run()

        assert result.ok is True
        msgs = list(checkin_service.messages_dir.glob("checkin_*.json"))
        assert len(msgs) == 1
        data = json.loads(msgs[0].read_text())
        assert data["chat_id"] == "test-chat-123"
        assert "buttons" in data

    def test_handle_snooze(self, checkin_service):
        checkin_service.handle_response("snooze_30")
        state = checkin_service.load_state(filename="checkin-state.json")
        assert state["snooze_until"] > time.time()

    def test_handle_dismiss(self, checkin_service):
        # Set unanswered count
        state = {"unanswered_checkins": 3}
        checkin_service.save_state(state, filename="checkin-state.json")

        checkin_service.handle_response("dismiss")
        state = checkin_service.load_state(filename="checkin-state.json")
        assert state["unanswered_checkins"] == 0
