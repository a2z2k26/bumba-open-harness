"""Tests for the RetroService (end-of-day retrospective)."""

from __future__ import annotations

import sqlite3
import tempfile
import shutil
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import pytest

from bridge.services.retro import RetroService


@pytest.fixture
def tmp_dir():
    d = tempfile.mkdtemp()
    yield Path(d)
    shutil.rmtree(d, ignore_errors=True)


@pytest.fixture
def test_db(tmp_dir):
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
        event_type TEXT, tool_name TEXT, arguments TEXT, outcome TEXT, details TEXT,
        session_id TEXT, chat_id TEXT
    )""")
    conn.execute("""CREATE TABLE message_queue (
        id INTEGER PRIMARY KEY, status TEXT DEFAULT 'pending',
        platform_message_id INTEGER, chat_id TEXT, text TEXT,
        received_at TEXT DEFAULT (datetime('now'))
    )""")
    conn.execute("""CREATE TABLE sessions (
        id INTEGER PRIMARY KEY, chat_id TEXT, claude_session_id TEXT,
        status TEXT DEFAULT 'active',
        created_at TEXT DEFAULT (datetime('now')),
        last_active_at TEXT DEFAULT (datetime('now')),
        message_count INTEGER DEFAULT 0,
        total_cost_usd REAL DEFAULT 0.0,
        expired_reason TEXT
    )""")
    conn.commit()
    conn.close()
    return db_path


class TestRetroService:
    def test_should_run_dedup(self, tmp_dir, test_db):
        """Second run on same day should return False."""
        svc = RetroService(
            data_dir=tmp_dir, db_path=test_db, chat_id="test",
            delivery_hour=datetime.now().hour,
            delivery_minute=datetime.now().minute,
        )
        state = svc.load_state("retro-state.json")
        state["last_retro_date"] = datetime.now().strftime("%Y-%m-%d")
        svc.save_state(state, "retro-state.json")
        assert svc.should_run() is False

    def test_compile_returns_string(self, tmp_dir, test_db):
        svc = RetroService(data_dir=tmp_dir, db_path=test_db, chat_id="test")
        result = svc.compile()
        assert isinstance(result, str)
        assert len(result) > 0

    def test_compile_with_activity(self, tmp_dir, test_db):
        """Retro should include activity data when messages exist."""
        conn = sqlite3.connect(str(test_db))
        conn.execute(
            "INSERT INTO conversations (session_id, chat_id, role, content) VALUES (?, ?, ?, ?)",
            ("s1", "c1", "user", "working on auth module"),
        )
        conn.execute(
            "INSERT INTO conversations (session_id, chat_id, role, content) VALUES (?, ?, ?, ?)",
            ("s1", "c1", "assistant", "implemented auth module"),
        )
        conn.commit()
        conn.close()

        svc = RetroService(data_dir=tmp_dir, db_path=test_db, chat_id="test")
        result = svc.compile()
        assert "2 messages" in result or "Activity" in result

    def test_run_sends_message(self, tmp_dir, test_db):
        svc = RetroService(
            data_dir=tmp_dir, db_path=test_db, chat_id="test",
            delivery_hour=datetime.now().hour,
            delivery_minute=datetime.now().minute,
        )
        with patch.object(svc, "should_run", return_value=True):
            result = svc.run()
            assert result.ok is True
            messages = list((tmp_dir / "service_messages").glob("retro_*.json"))
            assert len(messages) >= 1

    def test_run_skips_when_not_time(self, tmp_dir, test_db):
        svc = RetroService(data_dir=tmp_dir, db_path=test_db, chat_id="test")
        with patch.object(svc, "should_run", return_value=False):
            result = svc.run()
            assert result.ok is True
            assert result.skip_reason is not None

    def test_get_sources(self):
        sources = RetroService.get_sources()
        assert isinstance(sources, list)
        assert len(sources) >= 3
