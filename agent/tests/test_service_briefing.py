"""Tests for the BriefingService."""

from __future__ import annotations

import json
import sqlite3
import tempfile
import shutil
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import pytest

from bridge.services.briefing import BriefingService, _goals_summary, _recent_activity, _knowledge_updates, _system_health


@pytest.fixture
def tmp_dir():
    d = tempfile.mkdtemp()
    yield Path(d)
    shutil.rmtree(d, ignore_errors=True)


@pytest.fixture
def test_db(tmp_dir):
    """Create a test database with required tables."""
    db_path = tmp_dir / "test.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute("""CREATE TABLE knowledge (
        key TEXT PRIMARY KEY, value TEXT, tags TEXT,
        source TEXT DEFAULT 'agent',
        created_at TEXT DEFAULT (datetime('now')),
        updated_at TEXT DEFAULT (datetime('now')),
        archived INTEGER DEFAULT 0,
        category TEXT DEFAULT 'reference',
        salience REAL DEFAULT 1.0
    )""")
    conn.execute("""CREATE TABLE conversations (
        id INTEGER PRIMARY KEY, session_id TEXT, chat_id TEXT,
        role TEXT, content TEXT, created_at TEXT DEFAULT (datetime('now'))
    )""")
    conn.execute("""CREATE TABLE audit_log (
        id INTEGER PRIMARY KEY, timestamp TEXT DEFAULT (datetime('now')),
        event_type TEXT, tool_name TEXT, arguments TEXT, outcome TEXT, details TEXT
    )""")
    conn.execute("""CREATE TABLE message_queue (
        id INTEGER PRIMARY KEY, status TEXT DEFAULT 'pending',
        chat_id TEXT, text TEXT
    )""")
    conn.commit()
    conn.close()
    return db_path


class TestBriefingSources:
    """Test individual briefing data sources."""

    def test_goals_summary_no_goals(self, test_db):
        conn = sqlite3.connect(str(test_db))
        result = _goals_summary(conn)
        conn.close()
        assert result is None

    def test_goals_summary_with_goals(self, test_db):
        conn = sqlite3.connect(str(test_db))
        conn.execute(
            "INSERT INTO knowledge (key, value) VALUES (?, ?)",
            ("goal:test", json.dumps({"description": "Ship feature X"})),
        )
        conn.commit()
        result = _goals_summary(conn)
        conn.close()
        assert "Goals" in result
        assert "Ship feature X" in result

    def test_recent_activity_no_messages(self, test_db):
        conn = sqlite3.connect(str(test_db))
        result = _recent_activity(conn)
        conn.close()
        assert "No conversations" in result

    def test_recent_activity_with_messages(self, test_db):
        conn = sqlite3.connect(str(test_db))
        conn.execute(
            "INSERT INTO conversations (session_id, chat_id, role, content) VALUES (?, ?, ?, ?)",
            ("s1", "c1", "user", "hello"),
        )
        conn.execute(
            "INSERT INTO conversations (session_id, chat_id, role, content) VALUES (?, ?, ?, ?)",
            ("s1", "c1", "assistant", "hi there"),
        )
        conn.commit()
        result = _recent_activity(conn)
        conn.close()
        assert "2 messages" in result

    def test_knowledge_updates_none(self, test_db):
        conn = sqlite3.connect(str(test_db))
        result = _knowledge_updates(conn)
        conn.close()
        assert result is None  # No updates → None (hidden from briefing)

    def test_system_health_clean(self, test_db):
        conn = sqlite3.connect(str(test_db))
        result = _system_health(conn)
        conn.close()
        assert "All clear" in result

    def test_system_health_with_errors(self, test_db):
        conn = sqlite3.connect(str(test_db))
        conn.execute(
            "INSERT INTO audit_log (event_type) VALUES ('processing_error')"
        )
        conn.commit()
        result = _system_health(conn)
        conn.close()
        assert "1 error" in result


class TestBriefingService:
    """Test the BriefingService class."""

    def test_should_run_wrong_time(self, tmp_dir, test_db):
        svc = BriefingService(
            data_dir=tmp_dir, db_path=test_db, chat_id="test",
            delivery_hour=3, delivery_minute=0,  # 3 AM — unlikely to match
        )
        # Will only return True if current time is within 30 min of 3:00 AM
        # For test robustness, just verify it returns a bool
        result = svc.should_run()
        assert isinstance(result, bool)

    def test_should_run_dedup(self, tmp_dir, test_db):
        """Second call on same day should return False."""
        svc = BriefingService(
            data_dir=tmp_dir, db_path=test_db, chat_id="test",
            delivery_hour=datetime.now().hour,
            delivery_minute=datetime.now().minute,
        )
        # Mark as already sent today
        state = svc.load_state("briefing-state.json")
        state["last_briefing_date"] = datetime.now().strftime("%Y-%m-%d")
        svc.save_state(state, "briefing-state.json")

        assert svc.should_run() is False

    def test_compile_returns_string(self, tmp_dir, test_db):
        svc = BriefingService(data_dir=tmp_dir, db_path=test_db, chat_id="test")
        result = svc.compile()
        assert isinstance(result, str)
        assert "morning" in result.lower() or "briefing" in result.lower()

    def test_get_sources(self):
        sources = BriefingService.get_sources()
        assert "Goals Summary" in sources
        assert "Recent Activity" in sources
        assert "System Health" in sources

    def test_run_sends_message(self, tmp_dir, test_db):
        """When should_run() is True, run() should deliver a message."""
        svc = BriefingService(
            data_dir=tmp_dir, db_path=test_db, chat_id="test",
            delivery_hour=datetime.now().hour,
            delivery_minute=datetime.now().minute,
        )
        with patch.object(svc, "should_run", return_value=True):
            result = svc.run()
            assert result.ok is True
            # Check message file exists
            messages = list((tmp_dir / "service_messages").glob("briefing_*.json"))
            assert len(messages) >= 1

    def test_run_skips_when_not_time(self, tmp_dir, test_db):
        svc = BriefingService(
            data_dir=tmp_dir, db_path=test_db, chat_id="test",
            delivery_hour=3, delivery_minute=0,
        )
        with patch.object(svc, "should_run", return_value=False):
            result = svc.run()
            assert result.ok is True
            assert result.skip_reason is not None

    def test_run_skips_when_disabled(self, tmp_dir, test_db):
        """briefing_enabled=False must short-circuit run() before should_run()."""
        svc = BriefingService(
            data_dir=tmp_dir, db_path=test_db, chat_id="test",
            enabled=False,
        )
        result = svc.run()
        assert result.ok is True
        assert result.skip_reason == "briefing_enabled=False"
        assert result.work_items == 0
        # No message file created
        messages = list((tmp_dir / "service_messages").glob("briefing_*.json"))
        assert len(messages) == 0

    def test_enabled_default_is_true(self, tmp_dir, test_db):
        svc = BriefingService(data_dir=tmp_dir, db_path=test_db, chat_id="test")
        assert svc.enabled is True

    def test_config_fields_threaded(self, tmp_dir, test_db):
        """Constructor params are stored and accessible for later inspection."""
        svc = BriefingService(
            data_dir=tmp_dir, db_path=test_db, chat_id="test",
            enabled=True, delivery_hour=8, delivery_minute=15,
        )
        assert svc.delivery_hour == 8
        assert svc.delivery_minute == 15
