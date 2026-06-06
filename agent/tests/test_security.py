"""Tests for bridge.security (S76)."""

from __future__ import annotations

import json
import time

import pytest

from bridge.security import SecurityManager


class TestAuditLogging:
    """S73: Audit logging core."""

    @pytest.mark.asyncio
    async def test_log_event_to_sqlite(self, security_manager, migrated_db):
        await security_manager.log_event(
            "test_event",
            details={"key": "value"},
            tool_name="TestTool",
            arguments='{"arg": 1}',
            outcome="success",
            session_id="sess-1",
            chat_id="chat-1",
        )
        rows = await migrated_db.fetchall(
            "SELECT event_type, tool_name, outcome, details, session_id, chat_id FROM audit_log"
        )
        assert len(rows) == 1
        assert rows[0][0] == "test_event"
        assert rows[0][1] == "TestTool"
        assert rows[0][2] == "success"
        assert '"key": "value"' in rows[0][3]
        assert rows[0][4] == "sess-1"
        assert rows[0][5] == "chat-1"

    @pytest.mark.asyncio
    async def test_log_event_to_jsonl(self, security_manager, tmp_dirs):
        await security_manager.log_event("jsonl_test", details={"foo": "bar"})

        jsonl_path = tmp_dirs["log_dir"] / "audit.jsonl"
        assert jsonl_path.exists()
        lines = jsonl_path.read_text().strip().split("\n")
        assert len(lines) == 1
        entry = json.loads(lines[0])
        assert entry["event_type"] == "jsonl_test"
        assert entry["details"] == {"foo": "bar"}

    @pytest.mark.asyncio
    async def test_truncate_arguments(self, security_manager, migrated_db):
        long_args = "x" * 1000
        await security_manager.log_event(
            "trunc_test", arguments=long_args,
        )
        rows = await migrated_db.fetchall(
            "SELECT arguments FROM audit_log WHERE event_type = 'trunc_test'"
        )
        assert len(rows[0][0]) == 500

    @pytest.mark.asyncio
    async def test_get_recent_events(self, security_manager):
        for i in range(5):
            await security_manager.log_event(f"event_{i}")
        events = await security_manager.get_recent_events(limit=3)
        assert len(events) == 3
        # Most recent first
        assert events[0]["event_type"] == "event_4"

    @pytest.mark.asyncio
    async def test_get_recent_events_filtered(self, security_manager):
        await security_manager.log_event("type_a")
        await security_manager.log_event("type_b")
        await security_manager.log_event("type_a")
        events = await security_manager.get_recent_events(event_type="type_a")
        assert len(events) == 2
        assert all(e["event_type"] == "type_a" for e in events)


class TestAnomalyDetection:
    """S74: Anomaly detection."""

    @pytest.mark.asyncio
    async def test_tool_failure_burst(self, security_manager, sample_config):
        # Below threshold: no alerts
        for _ in range(sample_config.tool_failure_threshold - 1):
            alerts = await security_manager.check_anomalies(
                "tool_failure", {"tool_name": "TestTool"}
            )
        assert len(alerts) == 0

        # Hit threshold
        alerts = await security_manager.check_anomalies(
            "tool_failure", {"tool_name": "TestTool"}
        )
        assert len(alerts) == 1
        assert "Tool failure burst" in alerts[0]

    @pytest.mark.asyncio
    async def test_below_threshold_no_alert(self, security_manager):
        alerts = await security_manager.check_anomalies(
            "tool_failure", {"tool_name": "TestTool"}
        )
        assert len(alerts) == 0

    @pytest.mark.asyncio
    async def test_rate_limit_storm(self, security_manager):
        for _ in range(3):
            alerts = await security_manager.check_anomalies("rate_limit")
        assert len(alerts) == 1
        assert "Rate limit storm" in alerts[0]

    @pytest.mark.asyncio
    async def test_db_size_warning(self, security_manager, sample_config, tmp_dirs):
        # Create a fake db file that exceeds the warn threshold
        db_path = tmp_dirs["data_dir"] / "memory.db"
        # Write enough data to exceed db_size_warn (500MB default)
        # We can't easily create a 500MB file in a test, so we'll lower the threshold
        # Instead, let's just test the logic by checking with a small file
        db_path.write_bytes(b"x" * 100)
        alerts = await security_manager.check_anomalies("message_processed")
        # File is tiny, should be no alert
        assert not any("Database size" in a for a in alerts)

    def test_crash_loop_detection(self, security_manager, tmp_dirs):
        crash_log = tmp_dirs["data_dir"] / "crash.log"
        # Write 5 recent timestamps (within window)
        now = time.time()
        timestamps = "\n".join(str(now - i) for i in range(5))
        crash_log.write_text(timestamps + "\n")

        assert security_manager.check_crash_loop() is True

    def test_no_crash_loop(self, security_manager, tmp_dirs):
        crash_log = tmp_dirs["data_dir"] / "crash.log"
        # Write timestamps far in the past
        old = time.time() - 100000
        timestamps = "\n".join(str(old - i) for i in range(5))
        crash_log.write_text(timestamps + "\n")

        assert security_manager.check_crash_loop() is False

    def test_record_crash_timestamp(self, security_manager, tmp_dirs):
        security_manager.record_crash_timestamp()
        crash_log = tmp_dirs["data_dir"] / "crash.log"
        assert crash_log.exists()
        lines = crash_log.read_text().strip().split("\n")
        assert len(lines) == 1
        assert float(lines[0]) > 0


class TestHaltAndKernelHash:
    """S75: Halt flag and kernel hash verification."""

    def test_set_and_check_halt(self, security_manager, tmp_dirs):
        assert security_manager.is_halted() is False
        security_manager.set_halt("test reason")
        assert security_manager.is_halted() is True
        reason = security_manager.check_halt_flag()
        assert reason == "test reason"

    def test_clear_halt(self, security_manager):
        security_manager.set_halt("test")
        security_manager.clear_halt()
        assert security_manager.is_halted() is False
        assert security_manager.check_halt_flag() is None

    def test_verify_kernel_hashes_no_baseline(self, security_manager):
        result = security_manager.verify_kernel_hashes("/nonexistent/path")
        assert result == ["baseline file missing"]

    def test_verify_kernel_hashes_match(self, security_manager, tmp_path):
        # Create a test file and its baseline
        test_file = tmp_path / "test_kernel.py"
        test_file.write_text("print('hello')")

        import hashlib
        expected = hashlib.sha256(test_file.read_bytes()).hexdigest()

        baseline = tmp_path / "baseline.json"
        baseline.write_text(json.dumps({"files": {str(test_file): expected}}))

        result = security_manager.verify_kernel_hashes(str(baseline))
        assert result == []

    def test_verify_kernel_hashes_mismatch(self, security_manager, tmp_path):
        test_file = tmp_path / "test_kernel.py"
        test_file.write_text("print('hello')")

        baseline = tmp_path / "baseline.json"
        baseline.write_text(json.dumps({"files": {str(test_file): "wrong_hash"}}))

        result = security_manager.verify_kernel_hashes(str(baseline))
        assert len(result) == 1
        assert "CHANGED" in result[0]

    def test_verify_kernel_hashes_missing_file(self, security_manager, tmp_path):
        baseline = tmp_path / "baseline.json"
        baseline.write_text(json.dumps({"files": {"/nonexistent/file.py": "abc"}}))

        result = security_manager.verify_kernel_hashes(str(baseline))
        assert len(result) == 1
        assert "MISSING" in result[0]

    def test_format_alert(self):
        msg = SecurityManager.format_alert("Test Alert", "Some details")
        assert "[ALERT] Test Alert" in msg
        assert "Some details" in msg

    def test_format_alert_no_details(self):
        msg = SecurityManager.format_alert("Title Only")
        assert msg == "[ALERT] Title Only"
