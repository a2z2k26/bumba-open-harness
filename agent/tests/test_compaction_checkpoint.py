"""Tests for compaction checkpoint capture and restore."""
from __future__ import annotations

import json
import time

from bridge.compaction_checkpoint import (
    CompactionCheckpoint,
    DEFAULT_KEEP_LAST_N,
    DEFAULT_RECENT_WINDOW_SECONDS,
    _select_externalization_payload,
    capture_checkpoint,
    externalize_before_compact,
    format_restored_context,
    load_precompact_externals,
    restore_checkpoint,
)


class TestCompactionCheckpoint:
    def test_frozen_dataclass(self):
        cp = CompactionCheckpoint(
            session_id="test-session",
            message_count_before=25,
            estimated_tokens_before=5000,
            active_tasks=("task-1", "task-2"),
            workflow_state={"current_step": "implement", "plan_id": "plan-123"},
            permission_summary=("Allowed: Bash(ls)", "Denied: Bash(rm)"),
            tool_usage={"Read": 15, "Edit": 8, "Bash": 3},
            created_at="2026-04-02T12:00:00Z",
        )
        assert cp.session_id == "test-session"
        assert len(cp.active_tasks) == 2

    def test_checkpoint_serializes_to_json(self):
        cp = CompactionCheckpoint(
            session_id="test-session",
            message_count_before=25,
            estimated_tokens_before=5000,
            active_tasks=("task-1",),
            workflow_state={},
            permission_summary=(),
            tool_usage={},
            created_at="2026-04-02T12:00:00Z",
        )
        data = json.loads(json.dumps({
            "session_id": cp.session_id,
            "message_count_before": cp.message_count_before,
            "active_tasks": list(cp.active_tasks),
        }))
        assert data["session_id"] == "test-session"

    def test_format_restored_context_includes_tasks(self):
        cp = CompactionCheckpoint(
            session_id="test",
            message_count_before=20,
            estimated_tokens_before=4000,
            active_tasks=("Implement verification hooks", "Review API security"),
            workflow_state={"current_step": "step-3"},
            permission_summary=(),
            tool_usage={"Read": 10, "Edit": 5},
            created_at="2026-04-02T12:00:00Z",
        )
        context = format_restored_context(cp)
        assert "Implement verification hooks" in context
        assert "Review API security" in context
        assert "step-3" in context


class TestCaptureAndRestore:
    def test_capture_returns_checkpoint(self):
        cp = capture_checkpoint(
            session_id="sess-1",
            message_count=10,
            estimated_tokens=2000,
            active_task_titles=["Do the thing"],
            workflow_state={"step": "1"},
        )
        assert cp.session_id == "sess-1"
        assert cp.message_count_before == 10
        assert "Do the thing" in cp.active_tasks

    def test_capture_persists_to_disk(self, tmp_path):
        cp = capture_checkpoint(
            session_id="sess-disk",
            message_count=5,
            estimated_tokens=1000,
            checkpoint_dir=str(tmp_path),
        )
        assert (tmp_path / "sess-disk.json").exists()

    def test_restore_returns_none_when_missing(self, tmp_path):
        result = restore_checkpoint("nonexistent", tmp_path)
        assert result is None

    def test_capture_then_restore_roundtrip(self, tmp_path):
        capture_checkpoint(
            session_id="sess-rt",
            message_count=15,
            estimated_tokens=3000,
            active_task_titles=["Task A", "Task B"],
            workflow_state={"phase": "2"},
            checkpoint_dir=str(tmp_path),
        )
        restored = restore_checkpoint("sess-rt", tmp_path)
        assert restored is not None
        assert restored.session_id == "sess-rt"
        assert restored.message_count_before == 15
        assert "Task A" in restored.active_tasks
        assert restored.workflow_state["phase"] == "2"


# -- Sprint 03.05 — PreCompact externalization (#995) ----------------------


class TestPreCompactPayloadSelection:
    """Pure-function tests for _select_externalization_payload."""

    def test_keeps_last_n_when_below_default(self):
        # Five messages, no timestamps, no important tag → all five kept
        # because total < DEFAULT_KEEP_LAST_N.
        transcript = [{"content": f"msg-{i}"} for i in range(5)]
        selected = _select_externalization_payload(transcript)
        assert len(selected) == 5
        assert [m["content"] for m in selected] == [f"msg-{i}" for i in range(5)]

    def test_drops_old_messages_beyond_keep_last_n(self):
        # 10 messages, keep_last_n=3, no timestamps, no tags → tail of 3.
        transcript = [{"content": f"msg-{i}"} for i in range(10)]
        selected = _select_externalization_payload(transcript, keep_last_n=3)
        assert [m["content"] for m in selected] == ["msg-7", "msg-8", "msg-9"]

    def test_keeps_important_tagged_message_outside_tail(self):
        # 30 generic messages + an important one near the head.
        now = 10_000.0
        transcript = (
            [{"content": "<important>load-bearing decision</important>"}]
            + [{"content": f"msg-{i}"} for i in range(29)]
        )
        selected = _select_externalization_payload(
            transcript, keep_last_n=5, now=now,
        )
        # 5 tail messages plus the important head → 6 total.
        assert len(selected) == 6
        assert any("load-bearing" in m["content"] for m in selected)

    def test_keeps_recent_message_outside_tail(self):
        now = 10_000.0
        # Old head message timestamped just inside the recent window.
        head = {"content": "fresh question", "timestamp": now - 60.0}
        # Pad with 30 stale messages with old timestamps.
        stale = [
            {"content": f"old-{i}", "timestamp": now - 3600.0}
            for i in range(30)
        ]
        transcript = [head] + stale
        selected = _select_externalization_payload(
            transcript, keep_last_n=5, now=now,
        )
        contents = [m["content"] for m in selected]
        assert "fresh question" in contents
        assert len(selected) == 6  # tail of 5 + recent head

    def test_strips_private_spans_from_payload(self):
        transcript = [
            {"content": "public text <private>SECRET</private> more public"},
            {"content": "<important>keep me</important>"},
        ]
        selected = _select_externalization_payload(transcript)
        joined = " ".join(m["content"] for m in selected)
        assert "SECRET" not in joined
        assert "keep me" in joined

    def test_does_not_mutate_input(self):
        original = [{"content": "x <private>y</private>"}]
        snapshot = json.dumps(original)
        _select_externalization_payload(original)
        assert json.dumps(original) == snapshot

    def test_empty_transcript_returns_empty(self):
        assert _select_externalization_payload([]) == []


class TestExternalizeBeforeCompact:
    def test_disabled_returns_none_and_writes_nothing(self, tmp_path):
        result = externalize_before_compact(
            transcript=[{"content": "hello"}],
            session_id="s1",
            data_dir=str(tmp_path),
            enabled=False,
        )
        assert result is None
        assert not (tmp_path / "precompact").exists()

    def test_enabled_writes_atomic_side_file(self, tmp_path):
        path = externalize_before_compact(
            transcript=[{"content": "hello"}, {"content": "world"}],
            session_id="sess-write",
            data_dir=str(tmp_path),
            enabled=True,
            reason="compound_pressure=high",
        )
        assert path is not None
        assert path.exists()
        # No leftover .tmp file from the atomic rename.
        leftovers = list(path.parent.glob("*.tmp"))
        assert leftovers == []
        # Payload structure round-trips.
        payload = json.loads(path.read_text())
        assert payload["session_id"] == "sess-write"
        assert payload["reason"] == "compound_pressure=high"
        assert payload["selection"]["input_count"] == 2
        assert payload["selection"]["kept_count"] == 2

    def test_empty_transcript_writes_nothing(self, tmp_path):
        result = externalize_before_compact(
            transcript=[],
            session_id="empty",
            data_dir=str(tmp_path),
            enabled=True,
        )
        assert result is None

    def test_private_spans_never_in_externalized_payload(self, tmp_path):
        path = externalize_before_compact(
            transcript=[
                {"content": "intro <private>API_KEY=abc123</private> end"},
                {"content": "<PRIVATE>UPPER SECRET</PRIVATE>"},
            ],
            session_id="redact",
            data_dir=str(tmp_path),
            enabled=True,
        )
        assert path is not None
        raw = path.read_text()
        assert "API_KEY" not in raw
        assert "UPPER SECRET" not in raw
        assert "abc123" not in raw

    def test_round_trip_via_load(self, tmp_path):
        externalize_before_compact(
            transcript=[
                {"content": "first"},
                {"content": "second"},
            ],
            session_id="rt",
            data_dir=str(tmp_path),
            enabled=True,
        )
        # Sleep a microsecond and write a second batch so we exercise the
        # chronological merge.
        time.sleep(0.001)
        externalize_before_compact(
            transcript=[{"content": "third"}],
            session_id="rt",
            data_dir=str(tmp_path),
            enabled=True,
        )
        loaded = load_precompact_externals("rt", str(tmp_path))
        contents = [m["content"] for m in loaded]
        assert contents == ["first", "second", "third"]

    def test_load_returns_empty_for_unknown_session(self, tmp_path):
        assert load_precompact_externals("nope", str(tmp_path)) == []

    def test_load_skips_corrupt_file(self, tmp_path):
        path = externalize_before_compact(
            transcript=[{"content": "good"}],
            session_id="mixed",
            data_dir=str(tmp_path),
            enabled=True,
        )
        assert path is not None
        # Drop a corrupt sibling into the same dir.
        (path.parent / "20990101T000000000000Z.json").write_text("not json{")
        loaded = load_precompact_externals("mixed", str(tmp_path))
        assert [m["content"] for m in loaded] == ["good"]

    def test_defaults_match_documented_constants(self):
        # Guard against silent drift in the documented selection rule.
        assert DEFAULT_KEEP_LAST_N == 20
        assert DEFAULT_RECENT_WINDOW_SECONDS == 300.0


# -- Sprint E1.2 — Structured JSON task state capsule (#1234) --------------


from bridge.compaction_checkpoint import (
    CAPSULE_VERSION,
    format_capsule_json,
)


class TestFormatCapsuleJson:
    """Unit tests for format_capsule_json() and the v1 capsule schema."""

    def test_capsule_version_is_1(self):
        cp = CompactionCheckpoint(
            session_id="s1",
            message_count_before=10,
            estimated_tokens_before=100,
        )
        payload = format_capsule_json(cp)
        assert payload["capsule_version"] == CAPSULE_VERSION == 1

    def test_all_schema_fields_present(self):
        cp = CompactionCheckpoint(
            session_id="s1",
            message_count_before=10,
            estimated_tokens_before=100,
            active_sprint="E1.2",
            active_pr=1162,
            files_in_flight=["agent/bridge/compaction_checkpoint.py"],
            recent_decisions=["decision:hard-stop:wired"],
            open_questions=["Should v2 deprecate v0 fields?"],
            last_handoff_reason="context_pressure_hard_stop",
        )
        payload = format_capsule_json(cp)
        required_keys = (
            "capsule_version",
            "session_id",
            "created_at",
            "active_sprint",
            "active_pr",
            "active_tasks",
            "files_in_flight",
            "workflow_state",
            "recent_decisions",
            "open_questions",
            "tool_usage",
            "permission_summary",
            "last_handoff_reason",
            "message_count_before",
            "estimated_tokens_before",
        )
        for key in required_keys:
            assert key in payload, f"missing key: {key}"

    def test_new_v1_fields_round_trip(self):
        cp = CompactionCheckpoint(
            session_id="s2",
            message_count_before=5,
            estimated_tokens_before=500,
            active_sprint="E1.2",
            active_pr=1234,
            files_in_flight=["file_a.py", "file_b.py"],
            recent_decisions=["dec1", "dec2"],
            open_questions=["q1"],
            last_handoff_reason="context_pressure_compact_now",
        )
        payload = format_capsule_json(cp)
        assert payload["active_sprint"] == "E1.2"
        assert payload["active_pr"] == 1234
        assert payload["files_in_flight"] == ["file_a.py", "file_b.py"]
        assert payload["recent_decisions"] == ["dec1", "dec2"]
        assert payload["open_questions"] == ["q1"]
        assert payload["last_handoff_reason"] == "context_pressure_compact_now"

    def test_defaults_for_omitted_v1_fields(self):
        cp = CompactionCheckpoint(
            session_id="s3",
            message_count_before=1,
            estimated_tokens_before=10,
        )
        payload = format_capsule_json(cp)
        assert payload["active_sprint"] == ""
        assert payload["active_pr"] == 0
        assert payload["files_in_flight"] == []
        assert payload["recent_decisions"] == []
        assert payload["open_questions"] == []
        assert payload["last_handoff_reason"] == ""

    def test_tuples_serialized_as_lists(self):
        """Tuples in the dataclass must become lists for JSON-serializability."""
        cp = CompactionCheckpoint(
            session_id="s4",
            message_count_before=1,
            estimated_tokens_before=10,
            active_tasks=("task-a", "task-b"),
            files_in_flight=("f.py",),
        )
        payload = format_capsule_json(cp)
        assert isinstance(payload["active_tasks"], list)
        assert isinstance(payload["files_in_flight"], list)
        assert isinstance(payload["permission_summary"], list)
        assert isinstance(payload["recent_decisions"], list)
        assert isinstance(payload["open_questions"], list)

    def test_json_serializable(self):
        """The returned dict must round-trip through json.dumps without error."""
        cp = CompactionCheckpoint(
            session_id="s5",
            message_count_before=20,
            estimated_tokens_before=2000,
            active_tasks=("t1",),
            workflow_state={"step": "impl"},
            tool_usage={"Read": 5, "Edit": 3},
            active_sprint="E1.2",
            recent_decisions=["d1"],
        )
        payload = format_capsule_json(cp)
        serialized = json.dumps(payload)
        reloaded = json.loads(serialized)
        assert reloaded["capsule_version"] == 1
        assert reloaded["active_sprint"] == "E1.2"

    def test_extra_state_merged_into_workflow_state(self):
        """extra_state is shallow-merged; extra wins on collision."""
        cp = CompactionCheckpoint(
            session_id="s6",
            message_count_before=1,
            estimated_tokens_before=10,
            workflow_state={"a": 1, "b": 2},
        )
        payload = format_capsule_json(cp, extra_state={"b": 99, "c": 3})
        assert payload["workflow_state"]["a"] == 1
        assert payload["workflow_state"]["b"] == 99  # extra wins
        assert payload["workflow_state"]["c"] == 3

    def test_extra_state_none_does_not_mutate(self):
        cp = CompactionCheckpoint(
            session_id="s7",
            message_count_before=1,
            estimated_tokens_before=10,
            workflow_state={"x": 42},
        )
        payload = format_capsule_json(cp, extra_state=None)
        assert payload["workflow_state"] == {"x": 42}

    def test_pure_function_does_not_mutate_checkpoint(self):
        """format_capsule_json must not mutate the input checkpoint."""
        cp = CompactionCheckpoint(
            session_id="s8",
            message_count_before=1,
            estimated_tokens_before=10,
            active_tasks=("t",),
        )
        before_tasks = cp.active_tasks
        format_capsule_json(cp)
        assert cp.active_tasks == before_tasks


class TestCaptureCheckpointV1:
    """Tests for the extended capture_checkpoint() with v1 kwargs."""

    def test_accepts_v1_kwargs(self, tmp_path):
        cp = capture_checkpoint(
            session_id="sess-v1",
            message_count=10,
            estimated_tokens=1000,
            checkpoint_dir=str(tmp_path),
            active_sprint="E1.2",
            active_pr=1234,
            files_in_flight=["agent/bridge/compaction_checkpoint.py"],
            recent_decisions=["decided to add capsule schema"],
            open_questions=["cap tool_usage at top-10?"],
            last_handoff_reason="context_pressure_compact_now",
        )
        assert cp.active_sprint == "E1.2"
        assert cp.active_pr == 1234
        assert "agent/bridge/compaction_checkpoint.py" in cp.files_in_flight
        assert cp.last_handoff_reason == "context_pressure_compact_now"

    def test_persists_v1_shape_to_disk(self, tmp_path):
        """The on-disk file must include capsule_version=1 and v1 fields."""
        capture_checkpoint(
            session_id="s-disk",
            message_count=5,
            estimated_tokens=500,
            checkpoint_dir=str(tmp_path),
            active_sprint="E1.2",
            last_handoff_reason="context_pressure_hard_stop",
        )
        raw = json.loads((tmp_path / "s-disk.json").read_text())
        assert raw["capsule_version"] == 1
        assert raw["active_sprint"] == "E1.2"
        assert raw["last_handoff_reason"] == "context_pressure_hard_stop"

    def test_omitted_v1_kwargs_default_in_persisted_file(self, tmp_path):
        capture_checkpoint(
            session_id="s-defaults",
            message_count=3,
            estimated_tokens=300,
            checkpoint_dir=str(tmp_path),
        )
        raw = json.loads((tmp_path / "s-defaults.json").read_text())
        assert raw["active_sprint"] == ""
        assert raw["active_pr"] == 0
        assert raw["files_in_flight"] == []
        assert raw["recent_decisions"] == []
        assert raw["open_questions"] == []
        assert raw["last_handoff_reason"] == ""

    def test_v1_roundtrip_via_restore(self, tmp_path):
        """Write via capture_checkpoint, read via restore_checkpoint, compare."""
        capture_checkpoint(
            session_id="s-rt",
            message_count=15,
            estimated_tokens=1500,
            active_task_titles=["Implement E1.2"],
            checkpoint_dir=str(tmp_path),
            active_sprint="E1.2",
            active_pr=1234,
            files_in_flight=["compaction_checkpoint.py"],
            recent_decisions=["use capsule_version field"],
            open_questions=["cap tool_usage?"],
            last_handoff_reason="context_pressure_compact_now",
        )
        cp = restore_checkpoint("s-rt", tmp_path)
        assert cp is not None
        assert cp.active_sprint == "E1.2"
        assert cp.active_pr == 1234
        assert "compaction_checkpoint.py" in cp.files_in_flight
        assert "use capsule_version field" in cp.recent_decisions
        assert cp.last_handoff_reason == "context_pressure_compact_now"


class TestRestoreCheckpointBackCompat:
    """Regression tests: v0 on-disk files load cleanly with v1 defaults."""

    def test_v0_file_loads_with_v1_defaults(self, tmp_path):
        # Simulate a pre-E1.2 file (no capsule_version, no v1 fields).
        (tmp_path / "s-v0.json").write_text(json.dumps({
            "session_id": "s-v0",
            "message_count_before": 10,
            "estimated_tokens_before": 100,
            "active_tasks": ["legacy task"],
            "workflow_state": {},
            "permission_summary": [],
            "tool_usage": {},
            "created_at": "2026-05-02T00:00:00+00:00",
        }))
        cp = restore_checkpoint("s-v0", tmp_path)
        assert cp is not None
        assert cp.active_sprint == ""
        assert cp.active_pr == 0
        assert cp.files_in_flight == ()
        assert cp.recent_decisions == ()
        assert cp.open_questions == ()
        assert cp.last_handoff_reason == ""
        # Legacy field preserved
        assert "legacy task" in cp.active_tasks

    def test_unknown_extra_keys_ignored(self, tmp_path):
        """A future v2 file with extra keys should not break v1 loader."""
        (tmp_path / "s-future.json").write_text(json.dumps({
            "session_id": "s-future",
            "message_count_before": 5,
            "estimated_tokens_before": 50,
            "active_tasks": [],
            "workflow_state": {},
            "permission_summary": [],
            "tool_usage": {},
            "created_at": "2026-05-02T00:00:00+00:00",
            "capsule_version": 2,
            "unknown_future_field": "ignored",
        }))
        cp = restore_checkpoint("s-future", tmp_path)
        assert cp is not None
        assert cp.session_id == "s-future"


class TestFormatRestoredContextUnchanged:
    """Regression: prose formatter output is byte-stable for v0 checkpoints."""

    def test_format_restored_context_contains_required_markers(self):
        cp = CompactionCheckpoint(
            session_id="s-prose",
            message_count_before=20,
            estimated_tokens_before=4000,
            active_tasks=("task A", "task B"),
            workflow_state={"current_step": "step-3"},
            permission_summary=(),
            tool_usage={"Read": 10, "Edit": 5},
            created_at="2026-04-02T12:00:00Z",
        )
        from bridge.compaction_checkpoint import format_restored_context
        text = format_restored_context(cp)
        assert "POST-COMPACTION CONTEXT RESTORE:" in text
        assert "task A" in text
        assert "task B" in text
        assert "step-3" in text
        assert "Read" in text

    def test_format_restored_context_unchanged_for_v1_checkpoint(self):
        """Adding v1 fields must not break the prose formatter output."""
        cp = CompactionCheckpoint(
            session_id="s-v1-prose",
            message_count_before=10,
            estimated_tokens_before=1000,
            active_tasks=("in-flight task",),
            active_sprint="E1.2",
            last_handoff_reason="context_pressure_compact_now",
        )
        from bridge.compaction_checkpoint import format_restored_context
        text = format_restored_context(cp)
        assert "POST-COMPACTION CONTEXT RESTORE:" in text
        assert "in-flight task" in text
