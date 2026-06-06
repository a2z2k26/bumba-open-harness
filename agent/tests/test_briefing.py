"""Tests for bridge.services.briefing."""

from __future__ import annotations

import json
from datetime import datetime, timedelta

import pytest

from bridge.services.briefing import BriefingService, _SOURCES


@pytest.fixture
def briefing_service(tmp_path, migrated_db):
    """Create a BriefingService with test paths."""
    data_dir = tmp_path / "data"
    data_dir.mkdir(exist_ok=True)
    return BriefingService(
        data_dir=data_dir,
        db_path=migrated_db.db_path,
        chat_id="test-chat-123",
        delivery_hour=datetime.now().hour,
        delivery_minute=datetime.now().minute,
    )


class TestBriefingSources:
    """Pluggable data source registry."""

    def test_sources_registered(self):
        names = [name for name, _ in _SOURCES]
        assert "Goals Summary" in names
        assert "Recent Activity" in names
        assert "Knowledge Updates" in names
        assert "System Health" in names

    def test_get_sources(self):
        sources = BriefingService.get_sources()
        assert len(sources) >= 4


class TestBriefingService:
    """Briefing compilation and delivery."""

    def test_should_run_within_window(self, briefing_service):
        assert briefing_service.should_run() is True

    def test_should_run_dedup(self, briefing_service):
        state = {"last_briefing_date": datetime.now().strftime("%Y-%m-%d")}
        briefing_service.save_state(state, filename="briefing-state.json")
        assert briefing_service.should_run() is False

    def test_should_run_outside_window(self, tmp_path, migrated_db):
        data_dir = tmp_path / "data2"
        data_dir.mkdir()
        svc = BriefingService(
            data_dir=data_dir,
            db_path=migrated_db.db_path,
            chat_id="test",
            delivery_hour=(datetime.now().hour + 12) % 24,
            delivery_minute=0,
        )
        assert svc.should_run() is False

    def test_compile_empty_db(self, briefing_service):
        result = briefing_service.compile()
        assert "Good morning" in result

    @pytest.mark.asyncio
    async def test_compile_with_goals(self, briefing_service, migrated_db):
        goal_data = json.dumps({
            "description": "Ship v2",
            "status": "active",
            "deadline": (datetime.now() + timedelta(days=2)).isoformat(),
        })
        await migrated_db.execute(
            "INSERT INTO knowledge (key, value, category) VALUES ('goal:ship-v2', ?, 'project')",
            (goal_data,),
        )
        await migrated_db.commit()

        result = briefing_service.compile()
        assert "Ship v2" in result
        assert "Goals" in result

    @pytest.mark.asyncio
    async def test_compile_with_activity(self, briefing_service, migrated_db):
        await migrated_db.execute(
            """INSERT INTO conversations (session_id, chat_id, role, content)
               VALUES ('s1', 'c1', 'user', 'hello')"""
        )
        await migrated_db.commit()

        result = briefing_service.compile()
        assert "Activity" in result

    def test_run_sends_message(self, briefing_service):
        result = briefing_service.run()
        assert result.ok is True
        msgs = list(briefing_service.messages_dir.glob("briefing_*.json"))
        assert len(msgs) == 1

    def test_run_dedup_prevents_double_send(self, briefing_service):
        briefing_service.run()
        result = briefing_service.run()
        assert result.ok is True
        assert result.skip_reason is not None

    @pytest.mark.asyncio
    async def test_compile_with_errors(self, briefing_service, migrated_db):
        # Insert error audit entry — must bypass the no-delete/no-update triggers
        await migrated_db.execute(
            """INSERT INTO audit_log (event_type, outcome)
               VALUES ('processing_error', 'failed')"""
        )
        await migrated_db.commit()

        result = briefing_service.compile()
        assert "System" in result

    @pytest.mark.asyncio
    async def test_compile_with_knowledge_updates(self, briefing_service, migrated_db):
        await migrated_db.execute(
            "INSERT INTO knowledge (key, value) VALUES ('test:brief', 'data')"
        )
        await migrated_db.commit()

        result = briefing_service.compile()
        assert "Knowledge" in result
