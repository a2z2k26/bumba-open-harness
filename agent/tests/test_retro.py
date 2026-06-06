"""Tests for the EOD retro service."""

from __future__ import annotations

import json
import sqlite3
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest

from bridge.services.retro import RetroService


@pytest.fixture()
def tmp_dirs():
    with tempfile.TemporaryDirectory() as d:
        data_dir = Path(d) / "data"
        data_dir.mkdir()
        yield data_dir


@pytest.fixture()
def db_path(tmp_dirs):
    """In-memory-style SQLite DB with schema matching production."""
    path = tmp_dirs / "memory.db"
    conn = sqlite3.connect(str(path))
    conn.executescript("""
        CREATE TABLE conversations (
            id INTEGER PRIMARY KEY,
            session_id TEXT,
            role TEXT,
            content TEXT,
            created_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE knowledge (
            id INTEGER PRIMARY KEY,
            key TEXT UNIQUE,
            value TEXT,
            archived INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE message_queue (
            id INTEGER PRIMARY KEY,
            status TEXT DEFAULT 'pending'
        );
        CREATE TABLE audit_log (
            id INTEGER PRIMARY KEY,
            event_type TEXT,
            timestamp TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE sessions (
            id INTEGER PRIMARY KEY,
            session_id TEXT,
            error_count INTEGER DEFAULT 0,
            started_at TEXT DEFAULT (datetime('now'))
        );
    """)
    conn.commit()
    conn.close()
    return path


@pytest.fixture()
def service(tmp_dirs, db_path):
    return RetroService(
        data_dir=tmp_dirs,
        db_path=db_path,
        chat_id="test-channel",
        delivery_hour=18,
        delivery_minute=0,
    )


class TestRetroShouldRun:
    def test_outside_time_window_returns_false(self, service):
        """Not in the 30-min window around 18:00."""
        with patch("bridge.services.retro.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 3, 14, 10, 0, 0)
            assert service.should_run() is False

    def test_in_time_window_first_run_returns_true(self, service):
        with patch("bridge.services.retro.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 3, 14, 18, 0, 0)
            mock_dt.fromisoformat = datetime.fromisoformat
            assert service.should_run() is True

    def test_already_ran_today_returns_false(self, service):
        # Record today's retro in state
        state = service.load_state(filename="retro-state.json")
        state["last_retro_date"] = "2026-03-14"
        service.save_state(state, filename="retro-state.json")

        with patch("bridge.services.retro.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 3, 14, 18, 5, 0)
            mock_dt.fromisoformat = datetime.fromisoformat
            assert service.should_run() is False

    def test_different_day_returns_true(self, service):
        state = service.load_state(filename="retro-state.json")
        state["last_retro_date"] = "2026-03-13"
        service.save_state(state, filename="retro-state.json")

        with patch("bridge.services.retro.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 3, 14, 18, 0, 0)
            mock_dt.fromisoformat = datetime.fromisoformat
            assert service.should_run() is True


class TestRetroCompile:
    def test_compile_empty_db(self, service):
        result = service.compile()
        assert "EOD Retro" in result
        assert isinstance(result, str)

    def test_compile_with_conversations(self, service, db_path):
        conn = sqlite3.connect(str(db_path))
        today = datetime.now().strftime("%Y-%m-%d")
        conn.execute(
            "INSERT INTO conversations (session_id, role, content, created_at) VALUES (?, ?, ?, ?)",
            ("sess1", "user", "hello", today + " 10:00:00"),
        )
        conn.execute(
            "INSERT INTO conversations (session_id, role, content, created_at) VALUES (?, ?, ?, ?)",
            ("sess1", "assistant", "hi", today + " 10:00:01"),
        )
        conn.commit()
        conn.close()

        result = service.compile()
        assert "Activity" in result
        assert "1 messages" in result

    def test_compile_with_overdue_goal(self, service, db_path):
        conn = sqlite3.connect(str(db_path))
        yesterday = (datetime.now() - timedelta(days=1)).isoformat()
        goal_data = json.dumps({"description": "Ship feature X", "deadline": yesterday})
        conn.execute(
            "INSERT INTO knowledge (key, value, archived) VALUES (?, ?, 0)",
            ("goal:feature-x", goal_data),
        )
        conn.commit()
        conn.close()

        result = service.compile()
        assert "OVERDUE" in result
        assert "Ship feature X" in result

    def test_compile_with_pending_queue(self, service, db_path):
        conn = sqlite3.connect(str(db_path))
        conn.execute("INSERT INTO message_queue (status) VALUES ('pending')")
        conn.execute("INSERT INTO message_queue (status) VALUES ('pending')")
        conn.commit()
        conn.close()

        result = service.compile()
        assert "pending" in result

    def test_compile_with_tomorrow_deadline(self, service, db_path):
        conn = sqlite3.connect(str(db_path))
        tomorrow = (datetime.now() + timedelta(hours=20)).isoformat()
        goal_data = json.dumps({"description": "Review PR", "deadline": tomorrow})
        conn.execute(
            "INSERT INTO knowledge (key, value, archived) VALUES (?, ?, 0)",
            ("goal:review-pr", goal_data),
        )
        conn.commit()
        conn.close()

        result = service.compile()
        assert "Tomorrow" in result or "DUE TOMORROW" in result


class TestRetroRun:
    def test_run_outside_window_returns_false(self, service):
        with patch("bridge.services.retro.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 3, 14, 10, 0, 0)
            result = service.run()
            assert result.ok is True
            assert result.skip_reason == "outside_window_or_already_sent"

    def test_run_delivers_message(self, service):
        with patch("bridge.services.retro.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 3, 14, 18, 0, 0)
            mock_dt.strftime = datetime.strftime
            mock_dt.fromisoformat = datetime.fromisoformat
            result = service.run()

        assert result.ok is True
        # Message file should be written
        messages = list((service.data_dir / "service_messages").glob("retro_*.json"))
        assert len(messages) == 1
        content = json.loads(messages[0].read_text())
        assert content["source"] == "retro"
        assert "EOD Retro" in content["text"]

    def test_run_updates_state(self, service):
        with patch("bridge.services.retro.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 3, 14, 18, 0, 0)
            mock_dt.strftime = datetime.strftime
            mock_dt.fromisoformat = datetime.fromisoformat
            service.run()

        state = service.load_state(filename="retro-state.json")
        assert state["last_retro_date"] == "2026-03-14"

    def test_run_idempotent_same_day(self, service):
        with patch("bridge.services.retro.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 3, 14, 18, 0, 0)
            mock_dt.strftime = datetime.strftime
            mock_dt.fromisoformat = datetime.fromisoformat
            service.run()
            result = service.run()  # second call same day

        # Second run should be skipped (state already set to today's date)
        # But mock means datetime.now() always returns same time — so state was set
        # and second should_run() returns False
        messages = list((service.data_dir / "service_messages").glob("retro_*.json"))
        assert len(messages) == 1  # only one delivered


class TestRetroSources:
    def test_sources_registered(self):
        names = RetroService.get_sources()
        assert "Today's Activity" in names
        assert "Goals Progress" in names
        assert "Knowledge Added Today" in names
        assert "Open Loops" in names
        assert "Tomorrow Preview" in names
