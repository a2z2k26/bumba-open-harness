"""Tests for the weekly review service."""

from __future__ import annotations

import json
import sqlite3
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest

from bridge.services.weekly_review import WeeklyReviewService


@pytest.fixture()
def tmp_dirs():
    with tempfile.TemporaryDirectory() as d:
        data_dir = Path(d) / "data"
        data_dir.mkdir()
        yield data_dir


@pytest.fixture()
def db_path(tmp_dirs):
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
    return WeeklyReviewService(
        data_dir=tmp_dirs,
        db_path=db_path,
        chat_id="test-channel",
        delivery_weekday=6,  # Sunday
        delivery_hour=18,
        delivery_minute=0,
    )


class TestWeeklyReviewShouldRun:
    def test_wrong_weekday_returns_false(self, service):
        # Monday = 0
        monday = datetime(2026, 3, 9, 18, 0, 0)  # known Monday
        with patch("bridge.services.weekly_review.datetime") as mock_dt:
            mock_dt.now.return_value = monday
            assert service.should_run() is False

    def test_right_day_wrong_time_returns_false(self, service):
        # Sunday at wrong time
        sunday = datetime(2026, 3, 15, 10, 0, 0)  # Sunday
        with patch("bridge.services.weekly_review.datetime") as mock_dt:
            mock_dt.now.return_value = sunday
            assert service.should_run() is False

    def test_right_day_right_time_first_run_returns_true(self, service):
        sunday_18 = datetime(2026, 3, 15, 18, 0, 0)  # Sunday 6pm
        with patch("bridge.services.weekly_review.datetime") as mock_dt:
            mock_dt.now.return_value = sunday_18
            mock_dt.fromisoformat = datetime.fromisoformat
            assert service.should_run() is True

    def test_already_ran_this_week_returns_false(self, service):
        sunday_18 = datetime(2026, 3, 15, 18, 0, 0)
        # Record the actual week string that this date produces
        state = service.load_state(filename="weekly-review-state.json")
        state["last_review_week"] = sunday_18.strftime("%Y-W%W")
        service.save_state(state, filename="weekly-review-state.json")

        with patch("bridge.services.weekly_review.datetime") as mock_dt:
            mock_dt.now.return_value = sunday_18
            mock_dt.fromisoformat = datetime.fromisoformat
            assert service.should_run() is False

    def test_different_week_returns_true(self, service):
        sunday_18 = datetime(2026, 3, 15, 18, 0, 0)
        prior_sunday = datetime(2026, 3, 8, 18, 0, 0)  # one week earlier

        state = service.load_state(filename="weekly-review-state.json")
        state["last_review_week"] = prior_sunday.strftime("%Y-W%W")
        service.save_state(state, filename="weekly-review-state.json")

        with patch("bridge.services.weekly_review.datetime") as mock_dt:
            mock_dt.now.return_value = sunday_18
            mock_dt.fromisoformat = datetime.fromisoformat
            assert service.should_run() is True


class TestWeeklyReviewCompile:
    def test_compile_empty_db(self, service):
        result = service.compile()
        assert "Weekly Review" in result
        assert isinstance(result, str)

    def test_compile_with_week_activity(self, service, db_path):
        conn = sqlite3.connect(str(db_path))
        # 3 days of conversations
        for days_ago in [1, 2, 4]:
            ts = (datetime.now() - timedelta(days=days_ago)).strftime("%Y-%m-%d %H:%M:%S")
            conn.execute(
                "INSERT INTO conversations (session_id, role, content, created_at) VALUES (?, ?, ?, ?)",
                (f"sess{days_ago}", "user", "message", ts),
            )
        conn.commit()
        conn.close()

        result = service.compile()
        assert "Week at a Glance" in result
        assert "3/7 active days" in result

    def test_compile_with_completed_goals(self, service, db_path):
        conn = sqlite3.connect(str(db_path))
        yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d %H:%M:%S")
        conn.execute(
            "INSERT INTO knowledge (key, value, archived, updated_at) VALUES (?, ?, 1, ?)",
            ("goal:done-goal", json.dumps({"description": "Finish sprint"}), yesterday),
        )
        conn.commit()
        conn.close()

        result = service.compile()
        assert "Goals This Week" in result
        assert "completed" in result

    def test_compile_with_knowledge_growth(self, service, db_path):
        conn = sqlite3.connect(str(db_path))
        yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d %H:%M:%S")
        for i in range(5):
            conn.execute(
                "INSERT INTO knowledge (key, value, created_at) VALUES (?, ?, ?)",
                (f"fact:{i}", f"value {i}", yesterday),
            )
        conn.commit()
        conn.close()

        result = service.compile()
        assert "Knowledge Base" in result
        assert "5 new" in result

    def test_compile_with_errors(self, service, db_path):
        conn = sqlite3.connect(str(db_path))
        yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d %H:%M:%S")
        for _ in range(3):
            conn.execute(
                "INSERT INTO audit_log (event_type, timestamp) VALUES (?, ?)",
                ("bridge_error", yesterday),
            )
        conn.commit()
        conn.close()

        result = service.compile()
        assert "System Reliability" in result
        assert "3 errors" in result

    def test_compile_no_errors_shows_clean(self, service):
        result = service.compile()
        assert "Zero errors" in result or "System Reliability" in result


class TestWeeklyReviewRun:
    def test_run_wrong_day_returns_false(self, service):
        monday = datetime(2026, 3, 9, 18, 0, 0)
        with patch("bridge.services.weekly_review.datetime") as mock_dt:
            mock_dt.now.return_value = monday
            result = service.run()
            assert result.ok is True
            assert result.skip_reason == "wrong_day_or_already_ran_this_week"

    def test_run_delivers_message(self, service):
        sunday_18 = datetime(2026, 3, 15, 18, 0, 0)
        with patch("bridge.services.weekly_review.datetime") as mock_dt:
            mock_dt.now.return_value = sunday_18
            mock_dt.strftime = datetime.strftime
            mock_dt.fromisoformat = datetime.fromisoformat
            result = service.run()

        assert result.ok is True
        messages = list((service.data_dir / "service_messages").glob("weekly_review_*.json"))
        assert len(messages) == 1
        content = json.loads(messages[0].read_text())
        assert content["source"] == "weekly_review"
        assert "Weekly Review" in content["text"]

    def test_run_updates_week_state(self, service):
        sunday_18 = datetime(2026, 3, 15, 18, 0, 0)
        with patch("bridge.services.weekly_review.datetime") as mock_dt:
            mock_dt.now.return_value = sunday_18
            mock_dt.strftime = datetime.strftime
            mock_dt.fromisoformat = datetime.fromisoformat
            service.run()

        state = service.load_state(filename="weekly-review-state.json")
        assert "last_review_week" in state
        assert state["last_review_week"] is not None


class TestWeeklyReviewSources:
    def test_sources_registered(self):
        names = WeeklyReviewService.get_sources()
        assert "Week at a Glance" in names
        assert "Goals This Week" in names
        assert "Knowledge Base Growth" in names
        assert "System Reliability" in names
        assert "Patterns & Observations" in names
