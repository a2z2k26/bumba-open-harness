"""Tests for append-only daily log writer."""
from __future__ import annotations

import threading
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock

import pytest

from bridge.daily_log import DailyLogWriter


@pytest.fixture
def tmp_config(tmp_path):
    """Minimal config-like object with data_dir."""
    cfg = MagicMock()
    cfg.data_dir = str(tmp_path)
    return cfg


@pytest.fixture
def writer(tmp_config):
    return DailyLogWriter(tmp_config)


def test_log_path_structure(writer, tmp_config):
    """Log path should be data/logs/YYYY/MM/YYYY-MM-DD.md."""
    now = datetime(2026, 4, 2, 14, 30, tzinfo=timezone.utc)
    path = writer._log_path(now)
    assert path.parts[-3] == "2026"
    assert path.parts[-2] == "04"
    assert path.name == "2026-04-02.md"
    assert str(path).startswith(str(tmp_config.data_dir))


def test_append_creates_file(writer):
    """Appending to a non-existent log creates it."""
    writer.append("hello world")
    path = writer._log_path()
    assert path.exists()


def test_append_bullet_format(writer):
    """Each entry is a timestamped bullet."""
    writer.append("test entry")
    content = writer.read_today()
    assert content.startswith("- ")
    assert "test entry" in content


def test_append_category_tag(writer):
    """Category is included as [tag] in the entry."""
    writer.append("some event", category="event")
    content = writer.read_today()
    assert "[event]" in content


def test_append_no_category_tag(writer):
    """General category produces no [tag]."""
    writer.append("no tag entry", category="general")
    content = writer.read_today()
    assert "[general]" not in content


def test_append_only_no_rewrite(writer):
    """Multiple appends accumulate; no line is ever removed."""
    writer.append("first")
    writer.append("second")
    writer.append("third")
    content = writer.read_today()
    assert "first" in content
    assert "second" in content
    assert "third" in content
    lines = [l for l in content.splitlines() if l.strip()]
    assert len(lines) == 3


def test_read_today_empty(writer):
    """read_today returns empty string when no log exists yet."""
    result = writer.read_today()
    assert result == ""


def test_read_date_missing(writer):
    """read_date returns empty string for a date with no log."""
    past = datetime(2020, 1, 1, tzinfo=timezone.utc)
    result = writer.read_date(past)
    assert result == ""


def test_read_date_specific(writer):
    """read_date returns content for a specific date."""
    specific = datetime(2026, 4, 2, 10, 0, tzinfo=timezone.utc)
    path = writer._log_path(specific)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("- 10:00 test entry\n", encoding="utf-8")
    result = writer.read_date(specific)
    assert "test entry" in result


def test_list_recent_returns_existing_files(writer):
    """list_recent returns paths for existing files, newest first."""
    now = datetime.now(timezone.utc).astimezone()
    # Create files for today and yesterday
    for delta in [0, 1]:
        d = now - timedelta(days=delta)
        p = writer._log_path(d)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(f"- log for day -{delta}\n", encoding="utf-8")

    recent = writer.list_recent(days=7)
    assert len(recent) == 2
    # Newest first
    assert recent[0] == writer._log_path(now)


def test_list_recent_skips_missing_days(writer):
    """list_recent skips days with no log file — no error."""
    now = datetime.now(timezone.utc).astimezone()
    # Only create today's log
    p = writer._log_path(now)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("- today\n", encoding="utf-8")

    recent = writer.list_recent(days=7)
    assert len(recent) == 1


def test_unicode_content(writer):
    """Unicode entries are stored and read correctly."""
    writer.append("emoji 🚀 and unicode: 日本語")
    content = writer.read_today()
    assert "🚀" in content
    assert "日本語" in content


def test_date_rollover_different_files(tmp_config):
    """Entries on different dates go to different files."""
    writer = DailyLogWriter(tmp_config)
    d1 = datetime(2026, 4, 1, 23, 59, tzinfo=timezone.utc)
    d2 = datetime(2026, 4, 2, 0, 1, tzinfo=timezone.utc)

    path1 = writer._log_path(d1)
    path2 = writer._log_path(d2)
    assert path1 != path2
    assert path1.name == "2026-04-01.md"
    assert path2.name == "2026-04-02.md"


def test_thread_safety(writer):
    """Concurrent appends from multiple threads produce no corruption."""
    errors = []

    def append_many():
        try:
            for i in range(10):
                writer.append(f"entry-{threading.current_thread().name}-{i}")
        except Exception as e:
            errors.append(e)

    threads = [threading.Thread(target=append_many) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors
    content = writer.read_today()
    lines = [l for l in content.splitlines() if l.strip()]
    assert len(lines) == 50  # 5 threads * 10 entries each


# ---------------------------------------------------------------------------
# Sprint E.4 — correlation_id cross-file tracing (#210)
# ---------------------------------------------------------------------------

def test_append_correlation_id_included(writer):
    """correlation_id is embedded as [corr:<first8>] in the log entry."""
    cid = "abcdef1234567890"
    writer.append("traced event", correlation_id=cid)
    content = writer.read_today()
    assert "[corr:abcdef12]" in content


def test_append_no_correlation_id(writer):
    """When correlation_id is None, no [corr:...] tag appears."""
    writer.append("untraced event", correlation_id=None)
    content = writer.read_today()
    assert "[corr:" not in content


def test_append_correlation_id_short(writer):
    """Short correlation IDs are not truncated beyond their length."""
    writer.append("short corr", correlation_id="abc")
    content = writer.read_today()
    assert "[corr:abc]" in content


def test_append_correlation_id_with_category(writer):
    """correlation_id and category can appear together."""
    writer.append("combined", category="deploy", correlation_id="xyz-999")
    content = writer.read_today()
    assert "[deploy]" in content
    assert "[corr:xyz-999]" in content


def test_append_multiple_corr_ids(writer):
    """Different correlation_ids produce different corr tags."""
    writer.append("first chain", correlation_id="aaa111")
    writer.append("second chain", correlation_id="bbb222")
    content = writer.read_today()
    assert "[corr:aaa111]" in content
    assert "[corr:bbb222]" in content


# ---------------------------------------------------------------------------
# Z2.4 — log_service_completion tests
# ---------------------------------------------------------------------------

def test_log_service_completion_ok(tmp_path):
    """OK status writes [SERVICE][OK] line with duration."""
    cfg = MagicMock()
    cfg.data_dir = str(tmp_path)
    writer = DailyLogWriter(cfg)
    writer.log_service_completion("briefing", "OK", duration_ms=2340)
    content = writer.read_today()
    assert "[SERVICE][OK] briefing (2340ms)" in content


def test_log_service_completion_fail(tmp_path):
    """FAIL status writes [SERVICE][FAIL: reason] line."""
    cfg = MagicMock()
    cfg.data_dir = str(tmp_path)
    writer = DailyLogWriter(cfg)
    writer.log_service_completion("email", "FAIL", reason="TimeoutError: read timeout")
    content = writer.read_today()
    assert "[SERVICE][FAIL: TimeoutError: read timeout] email" in content


def test_log_service_completion_skip(tmp_path):
    """SKIP status writes [SERVICE][SKIP: reason] line."""
    cfg = MagicMock()
    cfg.data_dir = str(tmp_path)
    writer = DailyLogWriter(cfg)
    writer.log_service_completion("email", "SKIP", reason="no new mail")
    content = writer.read_today()
    assert "[SERVICE][SKIP: no new mail] email" in content


def test_log_service_completion_event_bus_wiring(tmp_path):
    """Event bus subscribers write correct lines on schedule.triggered and failure.detected."""
    from bridge.event_bus import EventBus
    cfg = MagicMock()
    cfg.data_dir = str(tmp_path)
    writer = DailyLogWriter(cfg)
    bus = EventBus(data_dir=tmp_path)

    def _on_success(event):
        p = event.payload if hasattr(event, "payload") else event
        writer.log_service_completion(
            p.get("service", "unknown"), "OK",
            duration_ms=p.get("duration_ms", 0)
        )

    def _on_failure(event):
        p = event.payload if hasattr(event, "payload") else event
        writer.log_service_completion(
            p.get("service", "unknown"), "FAIL",
            reason=p.get("error", "")
        )

    bus.subscribe("schedule.triggered", _on_success)
    bus.subscribe("failure.detected", _on_failure)

    bus.publish("schedule.triggered", {"service": "briefing", "duration_ms": 1500}, source="test")
    bus.publish("failure.detected", {"service": "email", "error": "SMTP timeout"}, source="test")

    log_content = writer.read_today()
    assert "[SERVICE][OK] briefing (1500ms)" in log_content
    assert "[SERVICE][FAIL: SMTP timeout] email" in log_content
