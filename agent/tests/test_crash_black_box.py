"""Tests for crash black box event recording."""
from __future__ import annotations

import json
from bridge.event_bus import EventBus


class TestCrashBlackBox:
    def test_record_crash_creates_event(self, tmp_path):
        bus = EventBus(data_dir=tmp_path)
        try:
            raise ValueError("test crash")
        except ValueError as e:
            bus.record_crash(error=e, context={"session_duration_seconds": 3600})

        # Verify event was persisted
        event_files = list((tmp_path / "events").glob("*.jsonl"))
        assert len(event_files) == 1

        lines = event_files[0].read_text().strip().split("\n")
        last_event = json.loads(lines[-1])
        assert last_event["event_type"] == "crash.recorded"
        assert "ValueError" in last_event["payload"]["error_type"]
        assert "test crash" in last_event["payload"]["error_message"]
        assert last_event["payload"]["session_duration_seconds"] == 3600

    def test_record_crash_includes_active_chains(self, tmp_path):
        bus = EventBus(data_dir=tmp_path)
        cid = bus.start_chain()
        bus.publish("test.event", source="test", correlation_id=cid)

        try:
            raise RuntimeError("chain crash")
        except RuntimeError as e:
            bus.record_crash(error=e, context={})

        event_files = list((tmp_path / "events").glob("*.jsonl"))
        lines = event_files[0].read_text().strip().split("\n")
        last_event = json.loads(lines[-1])
        assert len(last_event["payload"]["active_chains"]) == 1

    def test_record_crash_is_safe_on_io_error(self, tmp_path):
        # Even if data_dir is None, record_crash should not raise
        bus = EventBus(data_dir=None)
        try:
            raise RuntimeError("test")
        except RuntimeError as e:
            bus.record_crash(error=e, context={})  # Should not raise

    def test_record_crash_includes_traceback_summary(self, tmp_path):
        bus = EventBus(data_dir=tmp_path)
        try:
            raise TypeError("bad type")
        except TypeError as e:
            bus.record_crash(error=e, context={})

        event_files = list((tmp_path / "events").glob("*.jsonl"))
        lines = event_files[0].read_text().strip().split("\n")
        last_event = json.loads(lines[-1])
        assert "traceback_summary" in last_event["payload"]
        assert "TypeError" in last_event["payload"]["traceback_summary"]

    def test_record_crash_includes_total_event_count(self, tmp_path):
        bus = EventBus(data_dir=tmp_path)
        bus.publish("message.received", source="test")
        bus.publish("message.processed", source="test")

        try:
            raise ValueError("count check")
        except ValueError as e:
            bus.record_crash(error=e, context={})

        event_files = list((tmp_path / "events").glob("*.jsonl"))
        lines = event_files[0].read_text().strip().split("\n")
        last_event = json.loads(lines[-1])
        # 2 published + crash event itself; total_events_this_session captured before crash publish
        assert "total_events_this_session" in last_event["payload"]
        assert last_event["payload"]["total_events_this_session"] >= 2

    def test_record_crash_error_type_is_class_name(self, tmp_path):
        bus = EventBus(data_dir=tmp_path)
        try:
            raise KeyError("missing key")
        except KeyError as e:
            bus.record_crash(error=e, context={})

        event_files = list((tmp_path / "events").glob("*.jsonl"))
        lines = event_files[0].read_text().strip().split("\n")
        last_event = json.loads(lines[-1])
        assert last_event["payload"]["error_type"] == "KeyError"

    def test_traceback_truncated_to_500_chars(self, tmp_path):
        bus = EventBus(data_dir=tmp_path)
        try:
            raise ValueError("x" * 1000)
        except ValueError as e:
            bus.record_crash(error=e, context={})

        event_files = list((tmp_path / "events").glob("*.jsonl"))
        lines = event_files[0].read_text().strip().split("\n")
        last_event = json.loads(lines[-1])
        tb = last_event["payload"]["traceback_summary"]
        assert len(tb) <= 515  # 500 + "... (truncated)"

    def test_crash_recorded_in_event_types(self):
        from bridge.event_bus import EVENT_TYPES
        assert "crash.recorded" in EVENT_TYPES
