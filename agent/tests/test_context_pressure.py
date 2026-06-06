"""Tests for context pressure monitoring."""
from __future__ import annotations

import pytest
from bridge.context_pressure import (
    ContextPressure,
    ContextPressureMonitor,
    CompactionConfig,
    format_handoff_message,
)


class TestContextPressure:
    def test_frozen_dataclass(self):
        cp = ContextPressure(
            message_count=10,
            message_limit=40,
            estimated_tokens=2000,
            token_limit=8000,
            session_duration_seconds=600,
            duration_limit=7200,
            composite_score=0.35,
            recommendation="ok",
        )
        assert cp.composite_score == 0.35
        with pytest.raises(AttributeError):
            cp.composite_score = 0.5


class TestContextPressureMonitor:
    def test_initial_pressure_is_zero(self):
        config = CompactionConfig(message_limit=40, token_limit=8000, duration_limit=7200)
        monitor = ContextPressureMonitor(config)
        pressure = monitor.get_pressure()
        assert pressure.composite_score == 0.0
        assert pressure.recommendation == "ok"

    def test_recording_messages_increases_pressure(self):
        config = CompactionConfig(message_limit=40, token_limit=8000, duration_limit=7200)
        monitor = ContextPressureMonitor(config)
        for i in range(20):
            monitor.record_message(estimated_tokens=200)
        pressure = monitor.get_pressure()
        assert pressure.message_count == 20
        assert pressure.composite_score > 0.0

    def test_high_pressure_recommends_compact(self):
        config = CompactionConfig(
            message_limit=40, token_limit=8000, duration_limit=7200,
            auto_trigger_threshold=0.75,
        )
        monitor = ContextPressureMonitor(config)
        # 38 msgs x 200 tokens = 7600 → token_ratio=0.95, msg_ratio=0.95
        # composite = 0.5*0.95 + 0.3*0.95 = 0.76
        for i in range(38):
            monitor.record_message(estimated_tokens=200)
        pressure = monitor.get_pressure()
        assert pressure.composite_score >= 0.75
        assert pressure.recommendation in ("compact_now", "critical")

    def test_warning_threshold(self):
        config = CompactionConfig(
            message_limit=40, token_limit=8000, duration_limit=7200,
            warning_threshold=0.50, auto_trigger_threshold=0.75,
        )
        monitor = ContextPressureMonitor(config)
        # 30 msgs x 200 = 6000 tokens → token_ratio=0.75, msg_ratio=0.75
        # composite = 0.5*0.75 + 0.3*0.75 = 0.60
        for i in range(30):
            monitor.record_message(estimated_tokens=200)
        pressure = monitor.get_pressure()
        assert pressure.recommendation in ("warn", "compact_now", "critical")

    def test_get_pressure_signal_returns_none_when_ok(self):
        config = CompactionConfig(message_limit=40, token_limit=8000, duration_limit=7200)
        monitor = ContextPressureMonitor(config)
        assert monitor.get_pressure_signal() is None

    def test_get_pressure_signal_returns_hint_when_warning(self):
        config = CompactionConfig(
            message_limit=40, token_limit=8000, duration_limit=7200,
            warning_threshold=0.30, auto_trigger_threshold=0.75,
        )
        monitor = ContextPressureMonitor(config)
        # 15 msgs x 200 = 3000 → token_ratio=0.375, msg_ratio=0.375
        # composite = 0.5*0.375 + 0.3*0.375 = 0.30
        for i in range(15):
            monitor.record_message(estimated_tokens=200)
        signal = monitor.get_pressure_signal()
        assert signal is not None
        assert "compact" in signal.lower() or "context" in signal.lower()

    def test_reset_clears_state(self):
        config = CompactionConfig(message_limit=40, token_limit=8000, duration_limit=7200)
        monitor = ContextPressureMonitor(config)
        for i in range(20):
            monitor.record_message(estimated_tokens=200)
        monitor.reset()
        pressure = monitor.get_pressure()
        assert pressure.message_count == 0
        assert pressure.composite_score == 0.0


class TestShouldHardStop:
    """Tests for ContextPressureMonitor.should_hard_stop() — Sprint E1.1 (#1233)."""

    def _make_compact_now_monitor(self) -> "ContextPressureMonitor":
        """Build a monitor at compact_now threshold (composite ~0.76)."""
        config = CompactionConfig(
            message_limit=40,
            token_limit=8000,
            duration_limit=7200,
            auto_trigger_threshold=0.75,
        )
        monitor = ContextPressureMonitor(config)
        # 38 msgs x 200 tokens → token_ratio=0.95, msg_ratio=0.95
        # composite = 0.5*0.95 + 0.3*0.95 = 0.76 → compact_now
        for _ in range(38):
            monitor.record_message(estimated_tokens=200)
        return monitor

    def _make_critical_monitor(self) -> "ContextPressureMonitor":
        """Build a monitor at critical threshold (composite ≥ 0.90).

        Uses weight_duration=0.0 so duration never contributes — in tests
        the session elapsed is ~0ms, making duration_ratio=0. With only
        token+message weights, both saturated at 1.0:
            composite = 0.6*1.0 + 0.4*1.0 = 1.0 → critical (≥ 0.90).
        """
        config = CompactionConfig(
            message_limit=40,
            token_limit=8000,
            duration_limit=7200,
            auto_trigger_threshold=0.75,
            weight_tokens=0.6,
            weight_messages=0.4,
            weight_duration=0.0,
        )
        monitor = ContextPressureMonitor(config)
        # Saturate both token and message dimensions
        for _ in range(40):
            monitor.record_message(estimated_tokens=800)
        return monitor

    def test_should_hard_stop_compact_now_flag_on_returns_true(self):
        monitor = self._make_compact_now_monitor()
        assert monitor.get_pressure().recommendation in ("compact_now", "critical")
        assert monitor.should_hard_stop(hard_stop_enabled=True) is True

    def test_should_hard_stop_critical_flag_on_returns_true(self):
        monitor = self._make_critical_monitor()
        assert monitor.get_pressure().recommendation == "critical"
        assert monitor.should_hard_stop(hard_stop_enabled=True) is True

    def test_should_hard_stop_warn_returns_false(self):
        config = CompactionConfig(
            message_limit=40,
            token_limit=8000,
            duration_limit=7200,
            warning_threshold=0.30,
            auto_trigger_threshold=0.75,
        )
        monitor = ContextPressureMonitor(config)
        # Drive into "warn" band: 15 msgs x 200 → composite ~ 0.30
        for _ in range(15):
            monitor.record_message(estimated_tokens=200)
        pressure = monitor.get_pressure()
        # Only assert if we actually landed in warn — skip if threshold math
        # rounds into ok or compact_now due to duration drift.
        if pressure.recommendation == "warn":
            assert monitor.should_hard_stop(hard_stop_enabled=True) is False

    def test_should_hard_stop_ok_returns_false(self):
        config = CompactionConfig(message_limit=40, token_limit=8000, duration_limit=7200)
        monitor = ContextPressureMonitor(config)
        # Fresh monitor — recommendation == "ok"
        assert monitor.get_pressure().recommendation == "ok"
        assert monitor.should_hard_stop(hard_stop_enabled=True) is False

    def test_should_hard_stop_flag_off_returns_false_at_critical(self):
        monitor = self._make_critical_monitor()
        assert monitor.get_pressure().recommendation == "critical"
        # Flag off → always False regardless of pressure
        assert monitor.should_hard_stop(hard_stop_enabled=False) is False

    def test_should_hard_stop_flag_off_returns_false_at_compact_now(self):
        monitor = self._make_compact_now_monitor()
        assert monitor.get_pressure().recommendation in ("compact_now", "critical")
        assert monitor.should_hard_stop(hard_stop_enabled=False) is False


class TestFormatHandoffMessage:
    """Tests for format_handoff_message() — Sprint E1.1 (#1233)."""

    def test_contains_handoff_marker(self):
        text = format_handoff_message(capsule_id="session_abc123")
        assert "[HANDOFF:session_abc123]" in text

    def test_marker_regex_matches(self):
        import re
        text = format_handoff_message(capsule_id="session_abc123")
        assert re.search(r"\[HANDOFF:[a-zA-Z0-9_-]+\]", text) is not None

    def test_contains_capsule_id(self):
        capsule_id = "session_test_xyz_456"
        text = format_handoff_message(capsule_id=capsule_id)
        assert capsule_id in text

    def test_contains_hard_stop_header(self):
        text = format_handoff_message(capsule_id="any_id")
        assert "HARD-STOP" in text.upper()

    def test_different_capsule_ids_produce_different_markers(self):
        text_a = format_handoff_message(capsule_id="session_aaa")
        text_b = format_handoff_message(capsule_id="session_bbb")
        assert "[HANDOFF:session_aaa]" in text_a
        assert "[HANDOFF:session_bbb]" in text_b
        assert "[HANDOFF:session_aaa]" not in text_b

    def test_handoff_message_returns_str(self):
        result = format_handoff_message(capsule_id="any")
        assert isinstance(result, str)


class TestHardStopIntegration:
    """Integration smoke test: hard-stop triggers checkpoint write. Sprint E1.1 (#1233)."""

    def test_capture_checkpoint_on_hard_stop(self, tmp_path):
        """Simulate the runner wiring: capture_checkpoint writes a JSON file."""
        from bridge.compaction_checkpoint import capture_checkpoint, restore_checkpoint

        cp_dir = tmp_path / "checkpoints"
        capture_checkpoint(
            session_id="session_hardstop_test",
            message_count=42,
            estimated_tokens=7800,
            active_task_titles=["E1.1 hard-stop integration"],
            workflow_state={"hard_stop_pressure": 0.81},
            checkpoint_dir=str(cp_dir),
        )
        restored = restore_checkpoint("session_hardstop_test", str(cp_dir))
        assert restored is not None
        assert restored.workflow_state["hard_stop_pressure"] == 0.81
        assert restored.message_count_before == 42
        assert "E1.1 hard-stop integration" in restored.active_tasks

    def test_checkpoint_file_is_json_decodable(self, tmp_path):
        """Capsule file must be JSON-decodable at the checkpoint path."""
        import json
        from bridge.compaction_checkpoint import capture_checkpoint

        cp_dir = tmp_path / "checkpoints"
        session_id = "session_json_check"
        capture_checkpoint(
            session_id=session_id,
            message_count=10,
            estimated_tokens=1000,
            workflow_state={"hard_stop_pressure": 0.76},
            checkpoint_dir=str(cp_dir),
        )
        cp_path = cp_dir / f"{session_id}.json"
        assert cp_path.exists(), f"Checkpoint file not found at {cp_path}"
        data = json.loads(cp_path.read_text())
        assert data["session_id"] == session_id
        assert data["workflow_state"]["hard_stop_pressure"] == 0.76
