"""Tests for bridge/observability/tool_tracker.py — Zone 4 Sprint 9"""

import json
import pytest
from bridge.observability.tool_tracker import (
    ToolCallRecord,
    ToolCallCost,
    ToolTracker,
    sanitize_args,
)


# ── ToolCallCost ──────────────────────────────────────────────────────────────

class TestToolCallCost:
    def test_defaults(self):
        c = ToolCallCost()
        assert c.input_tokens == 0
        assert c.output_tokens == 0
        assert c.estimated_usd == 0.0

    def test_frozen(self):
        c = ToolCallCost(input_tokens=10)
        with pytest.raises((AttributeError, TypeError)):
            c.input_tokens = 99  # type: ignore

    def test_with_values(self):
        c = ToolCallCost(input_tokens=100, output_tokens=50, estimated_usd=0.002)
        assert c.input_tokens == 100
        assert c.output_tokens == 50
        assert c.estimated_usd == 0.002


# ── ToolCallRecord ────────────────────────────────────────────────────────────

class TestToolCallRecord:
    def test_defaults(self):
        r = ToolCallRecord(agent_name="qa-chief", department="qa", session_id="abc")
        assert r.status == "completed"
        assert r.is_domain_violation is False
        assert r.violation_rule == ""
        assert r.args_summary == ""
        assert len(r.record_id) > 0

    def test_frozen(self):
        r = ToolCallRecord(agent_name="a", department="d", session_id="s")
        with pytest.raises((AttributeError, TypeError)):
            r.agent_name = "mutated"  # type: ignore

    def test_to_dict(self):
        r = ToolCallRecord(
            agent_name="qa-chief",
            department="qa",
            session_id="ses1",
            tool_name="Read",
            args_summary='{"path": "src/"}',
            cost=ToolCallCost(input_tokens=10, output_tokens=5, estimated_usd=0.001),
        )
        d = r.to_dict()
        assert d["agent_name"] == "qa-chief"
        assert d["tool_name"] == "Read"
        assert isinstance(d["cost"], dict)
        assert d["cost"]["input_tokens"] == 10

    def test_from_dict_roundtrip(self):
        original = ToolCallRecord(
            agent_name="qa-engineer",
            department="qa",
            session_id="ses1",
            tool_name="Bash",
            args_summary='{"command": "pytest"}',
            status="completed",
            cost=ToolCallCost(input_tokens=20, output_tokens=100, estimated_usd=0.005),
            duration_ms=250.0,
        )
        d = original.to_dict()
        restored = ToolCallRecord.from_dict(d)
        assert restored.agent_name == original.agent_name
        assert restored.tool_name == original.tool_name
        assert restored.cost.input_tokens == 20
        assert restored.duration_ms == 250.0

    def test_unique_record_ids(self):
        r1 = ToolCallRecord(agent_name="a", department="d", session_id="s")
        r2 = ToolCallRecord(agent_name="a", department="d", session_id="s")
        assert r1.record_id != r2.record_id

    def test_domain_violation_fields(self):
        r = ToolCallRecord(
            agent_name="a",
            department="d",
            session_id="s",
            is_domain_violation=True,
            violation_rule="write denied: bridge/security.py",
            status="blocked",
        )
        assert r.is_domain_violation is True
        assert "security.py" in r.violation_rule
        assert r.status == "blocked"


# ── sanitize_args ─────────────────────────────────────────────────────────────

class TestSanitizeArgs:
    def test_none_returns_empty_string(self):
        assert sanitize_args(None) == ""

    def test_empty_dict(self):
        result = sanitize_args({})
        assert result == "{}"

    def test_normal_dict_unchanged(self):
        result = sanitize_args({"path": "src/auth.py", "content": "hello"})
        assert "src/auth.py" in result
        assert "hello" in result

    def test_token_field_redacted(self):
        result = sanitize_args({"token": "abc123secret"})
        assert "abc123secret" not in result
        assert "[REDACTED]" in result

    def test_password_field_redacted(self):
        result = sanitize_args({"password": "hunter2"})
        assert "hunter2" not in result
        assert "[REDACTED]" in result

    def test_secret_field_redacted(self):
        result = sanitize_args({"secret": "my-secret-value"})
        assert "my-secret-value" not in result
        assert "[REDACTED]" in result

    def test_auth_field_redacted(self):
        result = sanitize_args({"auth": "Bearer xyz"})
        assert "Bearer xyz" not in result
        assert "[REDACTED]" in result

    def test_credential_field_redacted(self):
        result = sanitize_args({"credential": "my-cred"})
        assert "my-cred" not in result
        assert "[REDACTED]" in result

    def test_key_field_redacted(self):
        result = sanitize_args({"api_key": "sk-12345"})
        assert "sk-12345" not in result
        assert "[REDACTED]" in result

    def test_case_insensitive_redaction(self):
        result = sanitize_args({"TOKEN": "upper-case-token"})
        assert "upper-case-token" not in result

    def test_nested_dict_redacted(self):
        result = sanitize_args({"config": {"token": "nested-token", "host": "localhost"}})
        assert "nested-token" not in result
        assert "localhost" in result

    def test_non_secret_fields_preserved(self):
        result = sanitize_args({"file_path": "/src/main.py", "line": 42})
        data = json.loads(result)
        assert data["file_path"] == "/src/main.py"
        assert data["line"] == 42

    def test_string_input_shell_style(self):
        result = sanitize_args("token=abc123 path=/src/")
        assert "abc123" not in result
        assert "[REDACTED]" in result
        assert "/src/" in result

    def test_string_input_json_style(self):
        result = sanitize_args('"password": "hunter2"')
        assert "hunter2" not in result
        assert "[REDACTED]" in result

    def test_string_normal_content_unchanged(self):
        result = sanitize_args("pytest tests/ -q")
        assert result == "pytest tests/ -q"

    def test_list_of_dicts(self):
        result = sanitize_args([{"token": "t1"}, {"path": "p1"}])
        assert "t1" not in result
        assert "p1" in result


# ── ToolTracker: recording ────────────────────────────────────────────────────

class TestToolTrackerRecord:
    def test_record_creates_file(self, tmp_path):
        tracker = ToolTracker(tmp_path / "sessions")
        record = ToolCallRecord(
            agent_name="qa-chief",
            department="qa",
            session_id="ses1",
            tool_name="Read",
        )
        tracker.record(record)
        log_path = tmp_path / "sessions" / "ses1" / "qa" / "tools" / "qa-chief.jsonl"
        assert log_path.exists()

    def test_record_writes_valid_json(self, tmp_path):
        tracker = ToolTracker(tmp_path / "sessions")
        record = ToolCallRecord(
            agent_name="qa-chief",
            department="qa",
            session_id="ses1",
            tool_name="Glob",
            args_summary='{"pattern": "*.py"}',
        )
        tracker.record(record)
        log_path = tmp_path / "sessions" / "ses1" / "qa" / "tools" / "qa-chief.jsonl"
        lines = log_path.read_text().strip().split("\n")
        assert len(lines) == 1
        data = json.loads(lines[0])
        assert data["tool_name"] == "Glob"

    def test_multiple_records_appended(self, tmp_path):
        tracker = ToolTracker(tmp_path / "sessions")
        for i in range(3):
            tracker.record(ToolCallRecord(
                agent_name="qa-chief",
                department="qa",
                session_id="ses1",
                tool_name=f"tool-{i}",
            ))
        log_path = tmp_path / "sessions" / "ses1" / "qa" / "tools" / "qa-chief.jsonl"
        lines = [l for l in log_path.read_text().strip().split("\n") if l]
        assert len(lines) == 3

    def test_different_agents_separate_files(self, tmp_path):
        tracker = ToolTracker(tmp_path / "sessions")
        for agent in ("qa-chief", "qa-engineer"):
            tracker.record(ToolCallRecord(
                agent_name=agent,
                department="qa",
                session_id="ses1",
                tool_name="Read",
            ))
        tools_dir = tmp_path / "sessions" / "ses1" / "qa" / "tools"
        assert (tools_dir / "qa-chief.jsonl").exists()
        assert (tools_dir / "qa-engineer.jsonl").exists()

    def test_log_call_convenience(self, tmp_path):
        tracker = ToolTracker(tmp_path / "sessions")
        record = tracker.log_call(
            agent_name="qa-chief",
            department="qa",
            session_id="ses1",
            tool_name="Bash",
            args={"command": "pytest tests/"},
            result="3 passed",
            duration_ms=120.5,
        )
        assert record.tool_name == "Bash"
        assert record.duration_ms == 120.5
        # Verify written to disk
        log_path = tmp_path / "sessions" / "ses1" / "qa" / "tools" / "qa-chief.jsonl"
        assert log_path.exists()

    def test_log_call_redacts_secrets(self, tmp_path):
        tracker = ToolTracker(tmp_path / "sessions")
        record = tracker.log_call(
            agent_name="qa-chief",
            department="qa",
            session_id="ses1",
            tool_name="Fetch",
            args={"url": "https://api.example.com", "token": "secret-token-123"},
        )
        assert "secret-token-123" not in record.args_summary
        assert "[REDACTED]" in record.args_summary

    def test_result_truncated_to_500(self, tmp_path):
        tracker = ToolTracker(tmp_path / "sessions")
        long_result = "x" * 1000
        record = tracker.log_call(
            agent_name="a",
            department="d",
            session_id="s",
            tool_name="t",
            result=long_result,
        )
        assert len(record.result_summary) == 500

    def test_domain_violation_recorded(self, tmp_path):
        tracker = ToolTracker(tmp_path / "sessions")
        record = tracker.log_call(
            agent_name="qa-chief",
            department="qa",
            session_id="ses1",
            tool_name="Write",
            args={"file_path": "bridge/security.py"},
            status="blocked",
            is_domain_violation=True,
            violation_rule="write denied: bridge/security.py",
        )
        assert record.is_domain_violation is True
        assert record.status == "blocked"


# ── ToolTracker: queries ──────────────────────────────────────────────────────

class TestToolTrackerQueries:
    def _setup(self, tmp_path) -> ToolTracker:
        tracker = ToolTracker(tmp_path / "sessions")
        # qa-chief: 2 normal + 1 violation
        for i in range(2):
            tracker.log_call(agent_name="qa-chief", department="qa", session_id="ses1",
                             tool_name=f"Read-{i}")
        tracker.log_call(agent_name="qa-chief", department="qa", session_id="ses1",
                         tool_name="Write", status="blocked",
                         is_domain_violation=True, violation_rule="denied")
        # qa-engineer: 2 normal
        for i in range(2):
            tracker.log_call(agent_name="qa-engineer", department="qa", session_id="ses1",
                             tool_name=f"Glob-{i}")
        # ops department, same session
        tracker.log_call(agent_name="ops-chief", department="ops", session_id="ses1",
                         tool_name="Bash")
        # different session
        tracker.log_call(agent_name="qa-chief", department="qa", session_id="ses2",
                         tool_name="Read")
        return tracker

    def test_get_agent_calls_returns_only_that_agent(self, tmp_path):
        tracker = self._setup(tmp_path)
        calls = tracker.get_agent_calls("ses1", "qa", "qa-chief")
        assert len(calls) == 3
        assert all(c.agent_name == "qa-chief" for c in calls)

    def test_get_agent_calls_empty_for_missing_agent(self, tmp_path):
        tracker = self._setup(tmp_path)
        calls = tracker.get_agent_calls("ses1", "qa", "nonexistent")
        assert calls == []

    def test_get_department_calls_includes_all_agents(self, tmp_path):
        tracker = self._setup(tmp_path)
        calls = tracker.get_department_calls("ses1", "qa")
        agent_names = {c.agent_name for c in calls}
        assert "qa-chief" in agent_names
        assert "qa-engineer" in agent_names
        assert len(calls) == 5  # 3 chief + 2 engineer

    def test_get_department_calls_excludes_other_departments(self, tmp_path):
        tracker = self._setup(tmp_path)
        calls = tracker.get_department_calls("ses1", "qa")
        assert all(c.department == "qa" for c in calls)

    def test_get_session_calls_returns_all_departments(self, tmp_path):
        tracker = self._setup(tmp_path)
        calls = tracker.get_session_calls("ses1")
        depts = {c.department for c in calls}
        assert "qa" in depts
        assert "ops" in depts
        assert len(calls) == 6

    def test_get_session_calls_excludes_other_sessions(self, tmp_path):
        tracker = self._setup(tmp_path)
        calls = tracker.get_session_calls("ses1")
        assert all(c.session_id == "ses1" for c in calls)

    def test_get_domain_violations_session_scope(self, tmp_path):
        tracker = self._setup(tmp_path)
        violations = tracker.get_domain_violations("ses1")
        assert len(violations) == 1
        assert violations[0].is_domain_violation is True

    def test_get_domain_violations_department_scope(self, tmp_path):
        tracker = self._setup(tmp_path)
        violations = tracker.get_domain_violations("ses1", department="qa")
        assert len(violations) == 1

    def test_get_domain_violations_agent_scope(self, tmp_path):
        tracker = self._setup(tmp_path)
        violations = tracker.get_domain_violations("ses1", department="qa",
                                                    agent_name="qa-chief")
        assert len(violations) == 1
        assert violations[0].agent_name == "qa-chief"

    def test_get_domain_violations_empty_when_none(self, tmp_path):
        tracker = self._setup(tmp_path)
        violations = tracker.get_domain_violations("ses1", department="qa",
                                                    agent_name="qa-engineer")
        assert violations == []

    def test_get_session_calls_empty_for_missing_session(self, tmp_path):
        tracker = self._setup(tmp_path)
        calls = tracker.get_session_calls("nonexistent")
        assert calls == []

    def test_results_sorted_by_timestamp(self, tmp_path):
        tracker = self._setup(tmp_path)
        calls = tracker.get_department_calls("ses1", "qa")
        timestamps = [c.timestamp for c in calls]
        assert timestamps == sorted(timestamps)
