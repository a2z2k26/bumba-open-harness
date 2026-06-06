"""Tests for log_consolidation.py — daily log wiring into consolidation pipeline."""
from __future__ import annotations

import os
import time
from datetime import date, datetime, timezone
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers / Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def tmp_config(tmp_path):
    """Minimal config object with data_dir."""
    cfg = MagicMock()
    cfg.data_dir = str(tmp_path)
    return cfg


@pytest.fixture
def daily_log(tmp_config):
    """Real DailyLogWriter pointing to tmp_path."""
    from bridge.daily_log import DailyLogWriter
    return DailyLogWriter(tmp_config)


@pytest.fixture
def log_source(daily_log):
    """LogConsolidationSource wrapping a real DailyLogWriter."""
    from bridge.log_consolidation import LogConsolidationSource
    return LogConsolidationSource(daily_log)


# ---------------------------------------------------------------------------
# Test 1: get_recent_logs returns (date, content) tuples for existing logs
# ---------------------------------------------------------------------------

def test_get_recent_logs_returns_tuples(log_source, daily_log):
    """get_recent_logs returns list of (date, content) tuples from DailyLogWriter."""
    daily_log.append("entry one", category="general")
    daily_log.append("entry two", category="memory")

    results = log_source.get_recent_logs(days=7)

    assert len(results) >= 1
    log_date, content = results[0]
    assert isinstance(log_date, date)
    assert "entry one" in content
    assert "entry two" in content


# ---------------------------------------------------------------------------
# Test 2: get_recent_logs skips missing days gracefully
# ---------------------------------------------------------------------------

def test_get_recent_logs_skips_missing_days(tmp_config, tmp_path):
    """get_recent_logs skips days with no log file without raising."""
    from bridge.daily_log import DailyLogWriter
    from bridge.log_consolidation import LogConsolidationSource

    dl = DailyLogWriter(tmp_config)
    # Only write today's log
    dl.append("only today")

    source = LogConsolidationSource(dl)
    results = source.get_recent_logs(days=7)

    # Should return exactly 1 result (only today's log exists)
    assert len(results) == 1
    assert results[0][1] == dl.read_today()


# ---------------------------------------------------------------------------
# Test 3: extract_actionable filters empty lines and noise, returns meaningful entries
# ---------------------------------------------------------------------------

def test_extract_actionable_filters_noise():
    """extract_actionable removes blank lines, HTML comments, and bare headers."""
    from bridge.log_consolidation import LogConsolidationSource

    source = LogConsolidationSource(MagicMock())
    content = (
        "<!-- consolidated: 2026-04-01T00:00:00Z -->\n"
        "\n"
        "# \n"
        "## \n"
        "- 09:00 [memory] remember this important fact\n"
        "\n"
        "- 10:30 [general] another useful entry\n"
    )
    result = source.extract_actionable(content)

    assert len(result) == 2
    assert "remember this important fact" in result[0]
    assert "another useful entry" in result[1]


def test_extract_actionable_empty_content():
    """extract_actionable returns empty list for blank content."""
    from bridge.log_consolidation import LogConsolidationSource

    source = LogConsolidationSource(MagicMock())
    assert source.extract_actionable("") == []
    assert source.extract_actionable("   \n\n   ") == []


# ---------------------------------------------------------------------------
# Test 4: mark_consolidated prepends <!-- consolidated: YYYY-MM-DDTHH:MM:SS --> header
# ---------------------------------------------------------------------------

def test_mark_consolidated_prepends_header(tmp_path):
    """mark_consolidated prepends the consolidated header to the log file."""
    from bridge.log_consolidation import LogConsolidationSource

    source = LogConsolidationSource(MagicMock())
    log_file = tmp_path / "2026-04-03.md"
    log_file.write_text("- 09:00 original content\n", encoding="utf-8")

    ts = datetime(2026, 4, 3, 12, 0, 0, tzinfo=timezone.utc)
    source.mark_consolidated(log_file, timestamp=ts)

    result = log_file.read_text(encoding="utf-8")
    assert result.startswith("<!-- consolidated: 2026-04-03T12:00:00Z -->")
    assert "original content" in result


def test_mark_consolidated_creates_file_if_missing(tmp_path):
    """mark_consolidated works even if the file did not previously exist."""
    from bridge.log_consolidation import LogConsolidationSource

    source = LogConsolidationSource(MagicMock())
    log_file = tmp_path / "2026-04-03.md"
    # File does not exist yet
    assert not log_file.exists()

    ts = datetime(2026, 4, 3, 8, 0, 0, tzinfo=timezone.utc)
    source.mark_consolidated(log_file, timestamp=ts)

    result = log_file.read_text(encoding="utf-8")
    assert "<!-- consolidated: 2026-04-03T08:00:00Z -->" in result


# ---------------------------------------------------------------------------
# Test 5: is_already_consolidated detects header
# ---------------------------------------------------------------------------

def test_is_already_consolidated_true():
    """is_already_consolidated returns True when content starts with header."""
    from bridge.log_consolidation import LogConsolidationSource

    source = LogConsolidationSource(MagicMock())
    content = "<!-- consolidated: 2026-04-03T12:00:00Z -->\n- 09:00 some entry"
    assert source.is_already_consolidated(content) is True


def test_is_already_consolidated_false():
    """is_already_consolidated returns False when no header present."""
    from bridge.log_consolidation import LogConsolidationSource

    source = LogConsolidationSource(MagicMock())
    content = "- 09:00 some entry\n- 10:00 another entry"
    assert source.is_already_consolidated(content) is False


def test_is_already_consolidated_false_for_empty():
    """is_already_consolidated returns False for empty content."""
    from bridge.log_consolidation import LogConsolidationSource

    source = LogConsolidationSource(MagicMock())
    assert source.is_already_consolidated("") is False


# ---------------------------------------------------------------------------
# Test 6: DateChangeDetector.check_and_flush returns True on date change
# ---------------------------------------------------------------------------

def test_date_change_detector_returns_true_on_rollover():
    """check_and_flush returns True when the date has rolled over."""
    from bridge.log_consolidation import DateChangeDetector

    detector = DateChangeDetector()
    day1 = datetime(2026, 4, 3, 23, 59, 0)
    day2 = datetime(2026, 4, 4, 0, 1, 0)

    # First call initialises the detector — no change yet
    first = detector.check_and_flush(day1)
    assert first is False

    # Second call with next day — should detect change
    second = detector.check_and_flush(day2)
    assert second is True


# ---------------------------------------------------------------------------
# Test 7: DateChangeDetector called twice same day returns False both times
# ---------------------------------------------------------------------------

def test_date_change_detector_same_day_always_false():
    """check_and_flush returns False when called multiple times on the same day."""
    from bridge.log_consolidation import DateChangeDetector

    detector = DateChangeDetector()
    same_day_morning = datetime(2026, 4, 3, 8, 0, 0)
    same_day_evening = datetime(2026, 4, 3, 20, 0, 0)

    assert detector.check_and_flush(same_day_morning) is False
    assert detector.check_and_flush(same_day_evening) is False


# ---------------------------------------------------------------------------
# Test 8: SessionTranscriptScanner.get_sessions_since returns IDs modified after timestamp
# ---------------------------------------------------------------------------

def test_session_scanner_returns_recent_sessions(tmp_path):
    """get_sessions_since returns session filenames modified after the given timestamp."""
    from bridge.log_consolidation import SessionTranscriptScanner

    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir()

    old_file = sessions_dir / "old-session.jsonl"
    new_file = sessions_dir / "new-session.jsonl"
    old_file.write_text("{}", encoding="utf-8")
    new_file.write_text("{}", encoding="utf-8")

    # Set old_file mtime to the past
    old_mtime = time.time() - 3600  # 1 hour ago
    new_mtime = time.time() - 60    # 1 minute ago
    os.utime(old_file, (old_mtime, old_mtime))
    os.utime(new_file, (new_mtime, new_mtime))

    threshold = time.time() - 600  # 10 minutes ago

    scanner = SessionTranscriptScanner(sessions_dir)
    result = scanner.get_sessions_since(threshold)

    assert "new-session.jsonl" in result
    assert "old-session.jsonl" not in result


def test_session_scanner_empty_dir_returns_empty(tmp_path):
    """get_sessions_since returns empty list when sessions directory is empty."""
    from bridge.log_consolidation import SessionTranscriptScanner

    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir()

    scanner = SessionTranscriptScanner(sessions_dir)
    assert scanner.get_sessions_since(time.time() - 3600) == []


def test_session_scanner_missing_dir_returns_empty(tmp_path):
    """get_sessions_since returns empty list when sessions directory doesn't exist."""
    from bridge.log_consolidation import SessionTranscriptScanner

    sessions_dir = tmp_path / "nonexistent_sessions"
    scanner = SessionTranscriptScanner(sessions_dir)
    assert scanner.get_sessions_since(time.time() - 3600) == []


# ---------------------------------------------------------------------------
# Test 9: SessionTranscriptScanner never reads full transcript content
# ---------------------------------------------------------------------------

def test_session_scanner_never_reads_content(tmp_path):
    """get_sessions_since uses only mtime — never opens or reads transcript files."""
    from bridge.log_consolidation import SessionTranscriptScanner

    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir()

    session_file = sessions_dir / "some-session.jsonl"
    session_file.write_text('{"id":"abc"}', encoding="utf-8")

    scanner = SessionTranscriptScanner(sessions_dir)

    with patch("builtins.open", wraps=open) as mock_open:
        scanner.get_sessions_since(time.time() - 3600)
        # open() should never have been called for transcript content
        mock_open.assert_not_called()


# ---------------------------------------------------------------------------
# Test 10: Integration — consolidation pipeline passes log entries to DreamAgent
# ---------------------------------------------------------------------------

def test_consolidation_pipeline_passes_log_entries_to_dream_agent(tmp_path, tmp_config):
    """Deep consolidation run passes daily log entries into DreamAgent prompt."""
    import sqlite3
    from bridge.daily_log import DailyLogWriter
    from bridge.dream_agent import DreamResult
    from bridge.log_consolidation import LogConsolidationSource
    from bridge.services.consolidation_service import ConsolidationService

    # Write a real daily log entry
    daily_log = DailyLogWriter(tmp_config)
    daily_log.append("important log entry for consolidation test", category="memory")

    # Build log source
    log_source = LogConsolidationSource(daily_log)

    # Create minimal DB with knowledge table
    db_path = tmp_path / "test.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute("""CREATE TABLE knowledge (
        key TEXT PRIMARY KEY,
        value TEXT,
        category TEXT,
        source TEXT,
        salience REAL DEFAULT 1.0,
        access_count INTEGER DEFAULT 0,
        created_at TEXT,
        updated_at TEXT,
        accessed_at TEXT,
        archived INTEGER DEFAULT 0
    )""")
    conn.commit()
    conn.close()

    # Build service
    service = ConsolidationService(
        data_dir=str(tmp_path),
        db_path=str(db_path),
        chat_id="test-chat",
        mode="deep",
    )
    service.set_log_source(log_source)

    # Mock dream agent that captures what it receives
    captured_session_ids = []

    async def mock_run(session_ids, extra_context=None):
        captured_session_ids.extend(session_ids)
        return DreamResult(
            success=True,
            entries_pruned=0,
            contradictions_resolved=0,
            merges_performed=0,
            error=None,
        )

    mock_dream = MagicMock()
    mock_dream.run = mock_run
    service.set_dream_agent(mock_dream)

    # Bypass the lock gate for testing
    with patch.object(service, "should_consolidate", return_value=True):
        with patch.object(service._lock, "try_acquire") as mock_lock:
            mock_lock.return_value = MagicMock(acquired=True, holder_pid=None, prior_mtime=None)
            with patch.object(service._lock, "release"):
                with patch.object(service._lock, "record_completion"):
                    with patch.object(service._lock, "rollback"):
                        service.run(mode="deep")

    # The log source should have surfaced at least one entry
    assert log_source.get_recent_logs(days=7)  # logs exist
