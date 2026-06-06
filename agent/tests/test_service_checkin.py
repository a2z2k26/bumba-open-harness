"""Tests for the CheckinService (proactive check-in engine)."""

from __future__ import annotations

import sqlite3
import tempfile
import shutil
from datetime import datetime
from pathlib import Path

import pytest

from bridge.services.checkin import CheckinService


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
    conn.commit()
    conn.close()
    return db_path


class TestCheckinService:
    def test_outside_active_hours(self, tmp_dir, test_db):
        """Check-in should not fire outside active hours."""
        svc = CheckinService(
            data_dir=tmp_dir, db_path=test_db, chat_id="test",
            active_hours_start=3, active_hours_end=4,  # 3-4 AM
        )
        # Unless it's actually 3-4 AM, this should decide SILENCE
        now = datetime.now()
        if not (3 <= now.hour < 4):
            result = svc.run()
            assert result.ok is True
            assert result.skip_reason is not None

    def test_instantiation(self, tmp_dir, test_db):
        """CheckinService should instantiate without errors."""
        svc = CheckinService(
            data_dir=tmp_dir, db_path=test_db, chat_id="test",
        )
        assert svc.chat_id == "test"
        assert svc.db_path == test_db

    def test_gather(self, tmp_dir, test_db):
        """Context gathering should not crash on empty DB."""
        svc = CheckinService(
            data_dir=tmp_dir, db_path=test_db, chat_id="test",
        )
        ctx = svc.gather()
        assert ctx is not None

    def test_minimum_gap_respected(self, tmp_dir, test_db):
        """Check-in should respect minimum gap between runs."""
        svc = CheckinService(
            data_dir=tmp_dir, db_path=test_db, chat_id="test",
            minimum_gap=999999,  # Very large gap
        )
        # Save state with recent last_run
        state = svc.load_state("checkin-state.json")
        state["last_run"] = datetime.now().isoformat()
        svc.save_state(state, "checkin-state.json")

        result = svc.run()
        assert result.ok is True
        assert result.skip_reason is not None

    def test_run_with_recent_message(self, tmp_dir, test_db):
        """Recent message should suppress check-in (quiet_after_message)."""
        conn = sqlite3.connect(str(test_db))
        conn.execute(
            "INSERT INTO conversations (session_id, chat_id, role, content) VALUES (?, ?, ?, ?)",
            ("s1", "test", "user", "just chatting"),
        )
        conn.commit()
        conn.close()

        svc = CheckinService(
            data_dir=tmp_dir, db_path=test_db, chat_id="test",
            quiet_after_message=999999,  # Large quiet period
        )
        result = svc.run()
        assert result.ok is True
        assert result.skip_reason is not None

    def test_run_skips_when_disabled(self, tmp_dir, test_db):
        """checkin_enabled=False must short-circuit before should_run()."""
        svc = CheckinService(
            data_dir=tmp_dir, db_path=test_db, chat_id="test",
            enabled=False,
        )
        result = svc.run()
        assert result.ok is True
        assert result.skip_reason == "checkin_enabled=False"
        assert result.work_items == 0

    def test_enabled_default_is_true(self, tmp_dir, test_db):
        svc = CheckinService(data_dir=tmp_dir, db_path=test_db, chat_id="test")
        assert svc.enabled is True

    def test_config_fields_threaded(self, tmp_dir, test_db):
        svc = CheckinService(
            data_dir=tmp_dir, db_path=test_db, chat_id="test",
            enabled=True,
            active_hours_start=9,
            active_hours_end=21,
            minimum_gap=3600,
            quiet_after_message=900,
        )
        assert svc.active_hours_start == 9
        assert svc.active_hours_end == 21
        assert svc.minimum_gap == 3600
        assert svc.quiet_after_message == 900
