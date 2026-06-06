"""Tests for structured session knowledge capture."""

from __future__ import annotations

import sqlite3
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from bridge.services.session_capture import (
    _build_session_summary,
    _slugify,
    extract_entries,
    get_recent_messages,
    run_capture,
    upsert_knowledge,
)


@pytest.fixture()
def db_path():
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "memory.db"
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
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                tags TEXT,
                created_at TEXT DEFAULT (datetime('now')),
                updated_at TEXT DEFAULT (datetime('now')),
                expires_at TEXT,
                source TEXT NOT NULL DEFAULT 'agent',
                category TEXT DEFAULT 'reference',
                archived INTEGER DEFAULT 0,
                salience REAL NOT NULL DEFAULT 1.0,
                accessed_at TEXT,
                access_count INTEGER NOT NULL DEFAULT 0,
                embedding BLOB
            );
        """)
        conn.commit()
        conn.close()
        yield path


@pytest.fixture()
def conn(db_path):
    c = sqlite3.connect(str(db_path))
    c.row_factory = sqlite3.Row
    yield c
    c.close()


def insert_messages(conn, session_id, messages):
    """Helper to insert conversation messages."""
    now = datetime.now()
    for i, (role, content) in enumerate(messages):
        ts = (now - timedelta(minutes=len(messages) - i)).strftime("%Y-%m-%d %H:%M:%S")
        conn.execute(
            "INSERT INTO conversations (session_id, role, content, created_at) VALUES (?, ?, ?, ?)",
            (session_id, role, content, ts),
        )
    conn.commit()


# ---------------------------------------------------------------------------
# _slugify
# ---------------------------------------------------------------------------

class TestSlugify:
    def test_basic(self):
        assert _slugify("Hello World") == "hello-world"

    def test_special_chars(self):
        assert _slugify("Use Python 3.13!") == "use-python-313"

    def test_max_len(self):
        long = "a" * 100
        assert len(_slugify(long)) <= 40

    def test_empty(self):
        assert _slugify("") == ""


# ---------------------------------------------------------------------------
# upsert_knowledge
# ---------------------------------------------------------------------------

class TestUpsertKnowledge:
    def test_insert(self, conn):
        upsert_knowledge(conn, "test:key", "test value", category="reference", salience=1.5)
        conn.commit()
        row = conn.execute("SELECT value, category, salience FROM knowledge WHERE key = 'test:key'").fetchone()
        assert row["value"] == "test value"
        assert row["category"] == "reference"
        assert row["salience"] == 1.5

    def test_upsert_updates_value(self, conn):
        upsert_knowledge(conn, "test:key", "original", salience=1.0)
        conn.commit()
        upsert_knowledge(conn, "test:key", "updated", salience=1.0)
        conn.commit()
        row = conn.execute("SELECT value FROM knowledge WHERE key = 'test:key'").fetchone()
        assert row["value"] == "updated"

    def test_upsert_keeps_higher_salience(self, conn):
        upsert_knowledge(conn, "test:key", "v1", salience=3.0)
        conn.commit()
        upsert_knowledge(conn, "test:key", "v2", salience=1.0)
        conn.commit()
        row = conn.execute("SELECT salience FROM knowledge WHERE key = 'test:key'").fetchone()
        assert row["salience"] == 3.0  # MAX kept

    def test_truncates_long_value(self, conn):
        long_val = "x" * 3000
        upsert_knowledge(conn, "test:long", long_val)
        conn.commit()
        row = conn.execute("SELECT value FROM knowledge WHERE key = 'test:long'").fetchone()
        assert len(row["value"]) <= 2000

    def test_tags_stored(self, conn):
        upsert_knowledge(conn, "test:tagged", "val", tags="a,b,c")
        conn.commit()
        row = conn.execute("SELECT tags FROM knowledge WHERE key = 'test:tagged'").fetchone()
        assert row["tags"] == "a,b,c"


# ---------------------------------------------------------------------------
# get_recent_messages
# ---------------------------------------------------------------------------

class TestGetRecentMessages:
    def test_by_session_id(self, conn):
        insert_messages(conn, "sess-abc", [("user", "hello"), ("assistant", "hi")])
        insert_messages(conn, "sess-xyz", [("user", "other")])
        msgs = get_recent_messages(conn, session_id="sess-abc")
        assert len(msgs) == 2
        assert all(m["role"] in ("user", "assistant") for m in msgs)

    def test_recent_only_by_hours(self, conn):
        from datetime import timezone
        # Use UTC timestamps to match SQLite's datetime('now') which is UTC
        now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        old_utc = (datetime.now(timezone.utc) - timedelta(hours=5)).strftime("%Y-%m-%d %H:%M:%S")
        conn.execute(
            "INSERT INTO conversations (session_id, role, content, created_at) VALUES (?, ?, ?, ?)",
            ("s1", "user", "recent", now_utc),
        )
        conn.execute(
            "INSERT INTO conversations (session_id, role, content, created_at) VALUES (?, ?, ?, ?)",
            ("s1", "user", "old", old_utc),
        )
        conn.commit()
        msgs = get_recent_messages(conn, session_id=None, hours=2)
        contents = [m["content"] for m in msgs]
        assert "recent" in contents
        assert "old" not in contents

    def test_empty_db_returns_empty(self, conn):
        msgs = get_recent_messages(conn, session_id="nonexistent")
        assert msgs == []


# ---------------------------------------------------------------------------
# _build_session_summary
# ---------------------------------------------------------------------------

class TestBuildSessionSummary:
    def test_empty_messages(self):
        assert _build_session_summary([]) == ""

    def test_no_user_messages(self):
        msgs = [{"role": "assistant", "content": "hello", "created_at": "2026-01-01"}]
        assert _build_session_summary(msgs) == ""

    def test_basic_summary_has_topic(self):
        msgs = [
            {"role": "user", "content": "Help me fix the auth bug", "created_at": "2026-01-01 10:00"},
            {"role": "assistant", "content": "I fixed the auth bug. Done.", "created_at": "2026-01-01 10:01"},
        ]
        result = _build_session_summary(msgs)
        assert "Help me fix the auth bug" in result or "Topic:" in result

    def test_summary_includes_turn_count(self):
        msgs = [
            {"role": "user", "content": "msg 1", "created_at": "2026-01-01 10:00"},
            {"role": "assistant", "content": "resp 1", "created_at": "2026-01-01 10:01"},
            {"role": "user", "content": "msg 2", "created_at": "2026-01-01 10:02"},
            {"role": "assistant", "content": "resp 2", "created_at": "2026-01-01 10:03"},
        ]
        result = _build_session_summary(msgs)
        assert "2" in result  # 2 user turns


# ---------------------------------------------------------------------------
# extract_entries
# ---------------------------------------------------------------------------

class TestExtractEntries:
    def test_empty_messages_returns_empty(self):
        assert extract_entries([], session_id=None) == []

    def test_session_summary_written_with_session_id(self):
        msgs = [
            {"role": "user", "content": "Build me a retro service", "created_at": "2026-01-01 10:00"},
            {"role": "assistant", "content": "Done. Built retro service.", "created_at": "2026-01-01 10:01"},
        ]
        entries = extract_entries(msgs, session_id="sess-123")
        keys = [e["key"] for e in entries]
        assert "session:summary:sess-123" in keys

    def test_no_session_summary_without_session_id(self):
        msgs = [
            {"role": "user", "content": "Build me a retro service", "created_at": "2026-01-01 10:00"},
            {"role": "assistant", "content": "Done.", "created_at": "2026-01-01 10:01"},
        ]
        entries = extract_entries(msgs, session_id=None)
        keys = [e["key"] for e in entries]
        assert not any(k.startswith("session:summary:") for k in keys)

    def test_decision_extracted(self):
        msgs = [
            {"role": "user", "content": "should we use postgres?", "created_at": "2026-01-01"},
            {"role": "assistant", "content": "Decided to use SQLite for local persistence.", "created_at": "2026-01-01"},
        ]
        entries = extract_entries(msgs, session_id=None)
        decision_entries = [e for e in entries if e["key"].startswith("decision:")]
        assert len(decision_entries) > 0
        assert all(e["category"] == "decision" for e in decision_entries)

    def test_goal_extracted(self):
        msgs = [
            {"role": "user", "content": "Goal: build the auth system by end of week", "created_at": "2026-01-01"},
            {"role": "assistant", "content": "Understood.", "created_at": "2026-01-01"},
        ]
        entries = extract_entries(msgs, session_id=None)
        goal_entries = [e for e in entries if e["key"].startswith("goal:")]
        assert len(goal_entries) > 0

    def test_no_duplicate_keys(self):
        msgs = [
            {"role": "user", "content": "Decided to use Python. Decided to use Python.", "created_at": "2026-01-01"},
            {"role": "assistant", "content": "Decided to use Python for scripts.", "created_at": "2026-01-01"},
        ]
        entries = extract_entries(msgs, session_id="s1")
        keys = [e["key"] for e in entries]
        assert len(keys) == len(set(keys))

    def test_salience_assigned(self):
        msgs = [
            {"role": "user", "content": "msg", "created_at": "2026-01-01"},
            {"role": "assistant", "content": "Decided to use postgres.", "created_at": "2026-01-01"},
        ]
        entries = extract_entries(msgs, session_id="s1")
        for e in entries:
            assert e["salience"] > 0


# ---------------------------------------------------------------------------
# run_capture (integration)
# ---------------------------------------------------------------------------

class TestRunCapture:
    def test_no_messages_returns_zero(self, db_path):
        count = run_capture(db_path, session_id="empty-session")
        assert count == 0

    def test_writes_entries_to_db(self, db_path):
        conn = sqlite3.connect(str(db_path))
        insert_messages(conn, "sess-test", [
            ("user", "I want to build a notification system"),
            ("assistant", "Done. Built the notification service. Decided to use WebSockets."),
        ])
        conn.close()

        count = run_capture(db_path, session_id="sess-test")
        assert count >= 1

        conn = sqlite3.connect(str(db_path))
        rows = conn.execute("SELECT key FROM knowledge").fetchall()
        conn.close()
        assert len(rows) >= 1

    def test_dry_run_writes_nothing(self, db_path, capsys):
        conn = sqlite3.connect(str(db_path))
        insert_messages(conn, "sess-dry", [
            ("user", "Build something"),
            ("assistant", "Decided to use Python. Done."),
        ])
        conn.close()

        count = run_capture(db_path, session_id="sess-dry", dry_run=True)
        # Nothing written to DB
        conn = sqlite3.connect(str(db_path))
        rows = conn.execute("SELECT key FROM knowledge").fetchall()
        conn.close()
        assert len(rows) == 0

    def test_missing_db_returns_zero(self):
        count = run_capture(Path("/nonexistent/memory.db"), session_id="s1")
        assert count == 0
