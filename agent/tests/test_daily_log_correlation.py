"""Tests for daily log correlation ID support."""
from __future__ import annotations

from types import SimpleNamespace
from bridge.daily_log import DailyLogWriter


class TestDailyLogCorrelation:
    def test_append_without_correlation_id(self, tmp_path):
        config = SimpleNamespace(data_dir=str(tmp_path))
        writer = DailyLogWriter(config)
        writer.append("Test entry", category="session")

        log_text = writer.read_today()
        assert "Test entry" in log_text
        assert "[corr:" not in log_text

    def test_append_with_correlation_id(self, tmp_path):
        config = SimpleNamespace(data_dir=str(tmp_path))
        writer = DailyLogWriter(config)
        writer.append("Correlated entry", category="event", correlation_id="abc123def")

        log_text = writer.read_today()
        assert "[corr:abc123de]" in log_text  # truncated to 8 chars
        assert "Correlated entry" in log_text

    def test_correlation_id_truncated_to_8_chars(self, tmp_path):
        config = SimpleNamespace(data_dir=str(tmp_path))
        writer = DailyLogWriter(config)
        writer.append("Entry", correlation_id="a1b2c3d4e5f6g7h8")

        log_text = writer.read_today()
        assert "[corr:a1b2c3d4]" in log_text
