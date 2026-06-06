"""Tests for the context object builder."""

import json
import sqlite3
import pytest
from unittest.mock import patch


@pytest.fixture
def tmp_db(tmp_path):
    """Create a minimal SQLite database for testing."""
    db_path = tmp_path / "memory.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute("""CREATE TABLE conversations (
        id INTEGER PRIMARY KEY, role TEXT, created_at TEXT
    )""")
    conn.execute("""CREATE TABLE knowledge (
        key TEXT, value TEXT, category TEXT, salience REAL,
        archived INTEGER DEFAULT 0, updated_at TEXT
    )""")
    conn.execute("""CREATE TABLE audit_log (
        id INTEGER PRIMARY KEY, event_type TEXT, timestamp TEXT
    )""")
    conn.execute("""CREATE TABLE message_queue (
        id INTEGER PRIMARY KEY, status TEXT
    )""")
    conn.commit()
    conn.close()
    return db_path


@pytest.fixture
def tmp_data(tmp_path, tmp_db):
    """Set up a complete data directory structure."""
    (tmp_path / "service_state").mkdir()
    (tmp_path / "service_messages").mkdir()
    return tmp_path


class TestBuildContext:
    def test_builds_with_empty_db(self, tmp_data, tmp_db):
        from bridge.services.context_builder import build_context
        with patch("bridge.services.context_builder.DATA_DIR", tmp_data), \
             patch("bridge.services.context_builder.CONTEXT_PATH", tmp_data / "service_state" / "context.json"):
            ctx = build_context(db_path=tmp_db)

        assert "built_at" in ctx
        assert "operator" in ctx
        assert "goals" in ctx
        assert "system" in ctx
        assert "knowledge" in ctx
        assert "escalation" in ctx
        assert ctx["goals"]["active"] == []
        assert ctx["goals"]["overdue"] == []

    def test_finds_last_contact(self, tmp_data, tmp_db):
        from datetime import datetime, timedelta
        two_hours_ago = (datetime.now() - timedelta(hours=2)).isoformat()
        conn = sqlite3.connect(str(tmp_db))
        conn.execute(
            "INSERT INTO conversations (role, created_at) VALUES ('user', ?)",
            (two_hours_ago,),
        )
        conn.commit()
        conn.close()

        from bridge.services.context_builder import build_context
        with patch("bridge.services.context_builder.DATA_DIR", tmp_data), \
             patch("bridge.services.context_builder.CONTEXT_PATH", tmp_data / "service_state" / "context.json"):
            ctx = build_context(db_path=tmp_db)

        assert ctx["operator"]["last_contact"] is not None
        assert 1.5 < ctx["operator"]["last_contact_hours_ago"] < 2.5

    def test_detects_overdue_goals(self, tmp_data, tmp_db):
        conn = sqlite3.connect(str(tmp_db))
        conn.execute(
            "INSERT INTO knowledge (key, value, category) VALUES (?, ?, ?)",
            ("goal:test", json.dumps({"deadline": "2020-01-01", "description": "Old goal"}), "goal"),
        )
        conn.commit()
        conn.close()

        from bridge.services.context_builder import build_context
        with patch("bridge.services.context_builder.DATA_DIR", tmp_data), \
             patch("bridge.services.context_builder.CONTEXT_PATH", tmp_data / "service_state" / "context.json"):
            ctx = build_context(db_path=tmp_db)

        assert len(ctx["goals"]["overdue"]) == 1
        assert ctx["goals"]["overdue"][0]["key"] == "goal:test"

    def test_counts_knowledge_stats(self, tmp_data, tmp_db):
        conn = sqlite3.connect(str(tmp_db))
        for i in range(5):
            conn.execute(
                "INSERT INTO knowledge (key, value, salience, updated_at) VALUES (?, ?, ?, datetime('now'))",
                (f"key:{i}", "{}", 1.0 if i < 3 else 0.2),
            )
        conn.commit()
        conn.close()

        from bridge.services.context_builder import build_context
        with patch("bridge.services.context_builder.DATA_DIR", tmp_data), \
             patch("bridge.services.context_builder.CONTEXT_PATH", tmp_data / "service_state" / "context.json"):
            ctx = build_context(db_path=tmp_db)

        assert ctx["knowledge"]["entries_active"] == 5
        assert ctx["knowledge"]["entries_updated_24h"] == 5
        assert ctx["knowledge"]["entries_low_salience"] == 2


class TestLoadContext:
    def test_loads_written_context(self, tmp_data):
        ctx_path = tmp_data / "service_state" / "context.json"
        ctx_path.write_text(json.dumps({"test": True}))

        from bridge.services.context_builder import load_context
        with patch("bridge.services.context_builder.CONTEXT_PATH", ctx_path):
            result = load_context()
        assert result == {"test": True}

    def test_returns_none_when_missing(self, tmp_data):
        from bridge.services.context_builder import load_context
        with patch("bridge.services.context_builder.CONTEXT_PATH", tmp_data / "nonexistent.json"):
            result = load_context()
        assert result is None


class TestUpdateSection:
    def test_updates_single_section(self, tmp_data):
        ctx_path = tmp_data / "service_state" / "context.json"
        ctx_path.write_text(json.dumps({"inbox": {"old": True}, "goals": {"active": []}}))

        from bridge.services.context_builder import update_section
        with patch("bridge.services.context_builder.CONTEXT_PATH", ctx_path):
            update_section("inbox", {"unread_total": 5, "last_check": "now"})

        result = json.loads(ctx_path.read_text())
        assert result["inbox"]["unread_total"] == 5
        assert result["goals"]["active"] == []  # preserved


class TestSummarizeForVoice:
    def test_summary_with_data(self, tmp_data):
        ctx_path = tmp_data / "service_state" / "context.json"
        ctx_path.write_text(json.dumps({
            "schedule": {"today_count": 3, "next_event": {"title": "Standup", "minutes_until": 15}},
            "inbox": {"unread_total": 8, "unread_urgent": 1},
            "goals": {"active": [{"key": "g1"}], "overdue": []},
            "system": {"uptime_hours": 24.0, "error_count_1h": 0, "halt_flag": False},
        }))

        from bridge.services.context_builder import summarize_for_voice
        with patch("bridge.services.context_builder.CONTEXT_PATH", ctx_path):
            summary = summarize_for_voice()

        assert "3 meetings" in summary
        assert "Standup" in summary
        assert "8 unread" in summary
        assert "1 urgent" in summary
        assert "1 active goals" in summary

    def test_summary_when_empty(self, tmp_data):
        from bridge.services.context_builder import summarize_for_voice
        with patch("bridge.services.context_builder.CONTEXT_PATH", tmp_data / "nonexistent.json"):
            summary = summarize_for_voice()
        assert summary == ""
