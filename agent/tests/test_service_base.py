"""Tests for ServiceBase — message delivery, state management, success/failure recording."""

from __future__ import annotations

import json
import tempfile
import shutil
from pathlib import Path


from bridge.services.base import (
    REQUIRED_STATE_FIELDS,
    ServiceBase,
    SkipClass,
    SkipReason,
)


class TestServiceBase:
    """Test the ServiceBase class."""

    def setup_method(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.svc = ServiceBase(data_dir=self.tmp_dir)

    def teardown_method(self):
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    # -- Message delivery --

    def test_deliver_message_creates_file(self):
        path = self.svc.deliver_message("chat-1", "Hello world", source="test")
        assert path.exists()
        data = json.loads(path.read_text())
        assert data["chat_id"] == "chat-1"
        assert data["text"] == "Hello world"
        assert data["source"] == "test"
        assert "timestamp" in data

    def test_deliver_message_with_buttons(self):
        buttons = [{"label": "OK", "value": "ok"}]
        path = self.svc.deliver_message("chat-1", "Choose:", buttons=buttons)
        data = json.loads(path.read_text())
        assert data["buttons"] == buttons

    def test_messages_dir_created(self):
        assert (Path(self.tmp_dir) / "service_messages").is_dir()

    # -- State management --

    def test_load_state_defaults(self):
        state = self.svc.load_state("test-state.json")
        for key, default in REQUIRED_STATE_FIELDS.items():
            assert key in state
            assert state[key] == default

    def test_save_and_load_state(self):
        state = {"custom_field": "value", "last_run": "2026-03-18T00:00:00"}
        self.svc.save_state(state, "test-state.json")

        loaded = self.svc.load_state("test-state.json")
        assert loaded["custom_field"] == "value"
        assert loaded["last_run"] == "2026-03-18T00:00:00"
        # Required fields are merged in
        assert "consecutive_failures" in loaded

    def test_save_state_atomic(self):
        """State file should exist after save (no temp files left)."""
        self.svc.save_state({"test": True}, "atomic-test.json")
        state_dir = Path(self.tmp_dir) / "service_state"
        assert (state_dir / "atomic-test.json").exists()
        # No .tmp files should remain
        tmp_files = list(state_dir.glob("*.tmp"))
        assert len(tmp_files) == 0

    def test_load_state_corrupt_json(self):
        """Corrupt JSON should return defaults, not crash."""
        state_dir = Path(self.tmp_dir) / "service_state"
        (state_dir / "bad-state.json").write_text("{corrupt")
        state = self.svc.load_state("bad-state.json")
        assert state["consecutive_failures"] == 0

    # -- Success/failure recording --

    def test_record_success(self):
        self.svc.record_success(150, filename="test-state.json")
        state = self.svc.load_state("test-state.json")
        assert state["last_run"] is not None
        assert state["consecutive_failures"] == 0
        assert state["total_runs"] == 1
        assert state["last_duration_ms"] == 150

    def test_record_failure(self):
        self.svc.record_failure("connection error", filename="test-state.json")
        state = self.svc.load_state("test-state.json")
        assert state["last_error"] == "connection error"
        assert state["consecutive_failures"] == 1
        assert state["total_failures"] == 1

    def test_consecutive_failures_reset_on_success(self):
        self.svc.record_failure("err1", filename="test-state.json")
        self.svc.record_failure("err2", filename="test-state.json")
        state = self.svc.load_state("test-state.json")
        assert state["consecutive_failures"] == 2

        self.svc.record_success(100, filename="test-state.json")
        state = self.svc.load_state("test-state.json")
        assert state["consecutive_failures"] == 0
        assert state["total_failures"] == 2  # Lifetime counter preserved

    def test_event_callback_on_success(self):
        events = []
        svc = ServiceBase(data_dir=self.tmp_dir, event_callback=lambda t, p: events.append((t, p)))
        svc.record_success(100, filename="test-state.json")
        assert len(events) == 1
        assert events[0][0] == "schedule.triggered"

    def test_event_callback_on_failure(self):
        events = []
        svc = ServiceBase(data_dir=self.tmp_dir, event_callback=lambda t, p: events.append((t, p)))
        svc.record_failure("oops", filename="test-state.json")
        assert len(events) == 1
        assert events[0][0] == "failure.detected"

    # -- Sprint 3.1: record_skipped (no-op runs are not failures) --

    def test_record_skipped_resets_consecutive_failures(self):
        """A skip MUST reset consecutive_failures so the monitor stops alerting.
        This is the bug Sprint 3.1 closes: knowledge_review's no-op path
        accumulated 9 consecutive_failures, triggering hourly false alerts.
        """
        # Build up some failures
        self.svc.record_failure("err1", filename="test-state.json")
        self.svc.record_failure("err2", filename="test-state.json")
        self.svc.record_failure("err3", filename="test-state.json")
        state = self.svc.load_state("test-state.json")
        assert state["consecutive_failures"] == 3

        # A skip should clear them
        self.svc.record_skipped("nothing to do", filename="test-state.json")
        state = self.svc.load_state("test-state.json")
        assert state["consecutive_failures"] == 0
        # Lifetime counters preserved
        assert state["total_failures"] == 3
        assert state["total_skipped"] == 1
        # last_skipped_* fields populated
        assert state["last_skipped_at"] is not None
        assert state["last_skipped_reason"] == "nothing to do"

    def test_record_skipped_does_not_increment_total_runs(self):
        """A skip is NOT a successful run — total_runs counts real work only."""
        self.svc.record_skipped("nothing to do", filename="test-state.json")
        self.svc.record_skipped("still nothing", filename="test-state.json")
        state = self.svc.load_state("test-state.json")
        assert state["total_runs"] == 0
        assert state["total_skipped"] == 2

    def test_record_skipped_truncates_long_reason(self):
        """A skip reason longer than 200 chars is truncated to fit the field."""
        long_reason = "x" * 500
        self.svc.record_skipped(long_reason, filename="test-state.json")
        state = self.svc.load_state("test-state.json")
        assert len(state["last_skipped_reason"]) == 200

    def test_event_callback_on_skipped(self):
        """Skips fire schedule.skipped event (distinct from .triggered and failure.detected)."""
        events = []
        svc = ServiceBase(
            data_dir=self.tmp_dir, event_callback=lambda t, p: events.append((t, p))
        )
        svc.record_skipped("test reason", filename="test-state.json")
        assert len(events) == 1
        assert events[0][0] == "schedule.skipped"
        assert events[0][1]["reason"] == "test reason"
        assert events[0][1]["total_skipped"] == 1
        # P4.2: plain-string back-compat path stores skip_class=None
        assert events[0][1]["skip_class"] is None

    # -- Sprint P4.2 (#1589): typed skip taxonomy --

    def test_skip_reason_render_parameterised(self):
        """SkipReason.render() emits ``<class>:<param>`` for parameterised classes."""
        r = SkipReason(SkipClass.MISSING_SECRET, "notion_api_token")
        assert r.render() == "missing_secret:notion_api_token"

        r = SkipReason(SkipClass.MISSING_CONFIG, "briefing.enabled")
        assert r.render() == "missing_config:briefing.enabled"

        r = SkipReason(SkipClass.DEPENDENCY_UNAVAILABLE, "vapi")
        assert r.render() == "dependency_unavailable:vapi"

    def test_skip_reason_render_terminal_no_detail(self):
        """Terminal classes with no detail render to the bare class value."""
        assert SkipReason(SkipClass.NOT_DUE).render() == "not_due"
        assert SkipReason(SkipClass.OPERATOR_DISABLED).render() == "operator_disabled"
        assert SkipReason(SkipClass.NOTHING_TO_DO).render() == "nothing_to_do"

    def test_skip_reason_render_terminal_with_detail(self):
        """Terminal classes append free-form detail in parentheses."""
        r = SkipReason(SkipClass.NOT_DUE, "outside 09:00-22:00 window")
        assert r.render() == "not_due (outside 09:00-22:00 window)"

        r = SkipReason(SkipClass.NOTHING_TO_DO, "no new mail since last digest")
        assert r.render() == "nothing_to_do (no new mail since last digest)"

    def test_record_skipped_typed_persists_class_and_reason(self):
        """A typed SkipReason populates last_skipped_class and last_skipped_reason."""
        self.svc.record_skipped(
            SkipReason(SkipClass.MISSING_SECRET, "notion_api_token"),
            filename="test-state.json",
        )
        state = self.svc.load_state("test-state.json")
        assert state["last_skipped_class"] == "missing_secret"
        assert state["last_skipped_reason"] == "missing_secret:notion_api_token"

    def test_record_skipped_typed_resets_consecutive_failures(self):
        """A typed skip resets consecutive_failures — same contract as the string path."""
        self.svc.record_failure("err1", filename="test-state.json")
        self.svc.record_failure("err2", filename="test-state.json")
        state = self.svc.load_state("test-state.json")
        assert state["consecutive_failures"] == 2

        self.svc.record_skipped(
            SkipReason(SkipClass.NOT_DUE),
            filename="test-state.json",
        )
        state = self.svc.load_state("test-state.json")
        assert state["consecutive_failures"] == 0
        assert state["total_failures"] == 2  # lifetime preserved

    def test_record_skipped_typed_does_not_increment_total_runs(self):
        """A typed skip is still a skip — total_runs MUST stay 0."""
        self.svc.record_skipped(
            SkipReason(SkipClass.NOTHING_TO_DO),
            filename="test-state.json",
        )
        state = self.svc.load_state("test-state.json")
        assert state["total_runs"] == 0
        assert state["total_skipped"] == 1

    def test_record_skipped_string_backcompat(self):
        """Plain string reason path still works (un-migrated services)."""
        self.svc.record_skipped("legacy free-form reason", filename="test-state.json")
        state = self.svc.load_state("test-state.json")
        assert state["last_skipped_reason"] == "legacy free-form reason"
        assert state["last_skipped_class"] is None

    def test_event_callback_carries_skip_class(self):
        """The typed skip event payload includes the skip_class value."""
        events = []
        svc = ServiceBase(
            data_dir=self.tmp_dir, event_callback=lambda t, p: events.append((t, p))
        )
        svc.record_skipped(
            SkipReason(SkipClass.OPERATOR_DISABLED, "feature flag off"),
            filename="test-state.json",
        )
        assert len(events) == 1
        assert events[0][0] == "schedule.skipped"
        assert events[0][1]["skip_class"] == "operator_disabled"
        assert events[0][1]["reason"] == "operator_disabled (feature flag off)"

    def test_skip_does_not_advance_escalation_counter(self):
        """Even a long run of typed skips MUST NOT trip an escalation threshold.

        EscalationEngine reads ``consecutive_failures`` (see bridge/escalation.py)
        and fires CASUAL at ==1, NUDGE at >=3, URGENT at >=5. A skip MUST leave
        that counter at 0 so the engine stays silent.
        """
        for _ in range(7):
            self.svc.record_skipped(
                SkipReason(SkipClass.NOT_DUE),
                filename="test-state.json",
            )
        state = self.svc.load_state("test-state.json")
        assert state["consecutive_failures"] == 0
        assert state["total_skipped"] == 7

    # -- #1806: last_status field (canonical schema for probe + health) --

    def test_record_success_sets_last_status_success(self):
        """record_success writes last_status='success' so probe/health can read it."""
        self.svc.record_success(150, filename="test-state.json")
        state = self.svc.load_state("test-state.json")
        assert state["last_status"] == "success"

    def test_record_failure_sets_last_status_failure(self):
        """record_failure writes last_status='failure'."""
        self.svc.record_failure("boom", filename="test-state.json")
        state = self.svc.load_state("test-state.json")
        assert state["last_status"] == "failure"

    def test_record_skipped_sets_last_status_skipped(self):
        """record_skipped writes last_status='skipped' (both string and typed paths)."""
        self.svc.record_skipped("nothing to do", filename="test-state.json")
        state = self.svc.load_state("test-state.json")
        assert state["last_status"] == "skipped"

        self.svc.record_skipped(
            SkipReason(SkipClass.NOT_DUE), filename="test-state.json"
        )
        state = self.svc.load_state("test-state.json")
        assert state["last_status"] == "skipped"

    def test_last_status_reflects_terminal_class_of_most_recent_run(self):
        """last_status follows the most recent record_* call, not lifetime totals."""
        self.svc.record_success(100, filename="test-state.json")
        assert self.svc.load_state("test-state.json")["last_status"] == "success"

        self.svc.record_failure("oops", filename="test-state.json")
        assert self.svc.load_state("test-state.json")["last_status"] == "failure"

        self.svc.record_skipped("done", filename="test-state.json")
        assert self.svc.load_state("test-state.json")["last_status"] == "skipped"

        self.svc.record_success(50, filename="test-state.json")
        assert self.svc.load_state("test-state.json")["last_status"] == "success"

    def test_last_status_default_is_none(self):
        """A fresh state file has last_status=None until any record_* fires."""
        state = self.svc.load_state("fresh-state.json")
        assert state["last_status"] is None

    def test_skip_taxonomy_covers_audit_plan_classes(self):
        """All five audit-plan-mandated classes plus nothing_to_do are present.

        The audit plan acceptance criterion is that the operator gets a
        deterministic class for every skip. This test pins the taxonomy so a
        future rename of any class value triggers a test failure rather than
        silently drifting the operator-facing contract.
        """
        assert {c.value for c in SkipClass} == {
            "missing_secret",
            "missing_config",
            "not_due",
            "dependency_unavailable",
            "operator_disabled",
            "nothing_to_do",
        }
