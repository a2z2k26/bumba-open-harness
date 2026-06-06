# tests/test_harness_verifier.py
"""Tests for harness config verification."""
from __future__ import annotations

from bridge.harness_verifier import (
    HarnessVerifier,
    VerificationResult,
    VerificationFailure,
    validate_bridge_toml,
    validate_claude_settings,
    validate_hook_script,
)


class TestVerificationResult:
    def test_passed_result_has_no_failures(self):
        result = VerificationResult(
            passed=True,
            checks_run=("toml_parse", "required_keys"),
            failures=(),
            duration_ms=12,
        )
        assert result.passed is True
        assert len(result.failures) == 0

    def test_failed_result_contains_failures(self):
        failure = VerificationFailure(
            check_name="required_keys",
            severity="critical",
            message="Missing [claude] section",
            file_path="config/bridge.toml",
            suggestion="Add [claude] section with timeout, max_turns",
        )
        result = VerificationResult(
            passed=False,
            checks_run=("toml_parse", "required_keys"),
            failures=(failure,),
            duration_ms=15,
        )
        assert result.passed is False
        assert result.failures[0].severity == "critical"


class TestBridgeTomlValidation:
    def test_valid_toml_passes(self, tmp_path):
        toml_content = """
[bridge]
data_dir = "/tmp/test"
log_dir = "/tmp/logs"
heartbeat_interval = 60

[claude]
timeout = 300
hard_timeout = 600
absolute_timeout = 1800
max_turns = 25

[session]
idle_timeout = 1800
max_errors = 3

[security]
disallowed_tools = []
tool_failure_threshold = 5
tool_failure_window = 600
"""
        toml_file = tmp_path / "bridge.toml"
        toml_file.write_text(toml_content)
        result = validate_bridge_toml(str(toml_file))
        assert result.passed is True

    def test_missing_claude_section_fails(self, tmp_path):
        toml_content = """
[bridge]
data_dir = "/tmp/test"
"""
        toml_file = tmp_path / "bridge.toml"
        toml_file.write_text(toml_content)
        result = validate_bridge_toml(str(toml_file))
        assert result.passed is False
        assert any(f.check_name == "required_sections" for f in result.failures)

    def test_invalid_toml_syntax_fails(self, tmp_path):
        toml_file = tmp_path / "bridge.toml"
        toml_file.write_text("this is not = valid [ toml")
        result = validate_bridge_toml(str(toml_file))
        assert result.passed is False
        assert any(f.check_name == "toml_parse" for f in result.failures)

    def test_timeout_ordering_violation(self, tmp_path):
        toml_content = """
[bridge]
data_dir = "/tmp/test"
log_dir = "/tmp/logs"

[claude]
timeout = 600
hard_timeout = 300
absolute_timeout = 100
max_turns = 25

[session]
idle_timeout = 1800
max_errors = 3

[security]
disallowed_tools = []
"""
        toml_file = tmp_path / "bridge.toml"
        toml_file.write_text(toml_content)
        result = validate_bridge_toml(str(toml_file))
        assert result.passed is False
        assert any("timeout ordering" in f.message.lower() for f in result.failures)


class TestClaudeSettingsValidation:
    def test_valid_settings_pass(self, tmp_path):
        import json
        settings = {
            "hooks": {
                "SessionStart": [{"type": "command", "command": "bash test.sh", "matcher": "*"}],
                "Stop": [{"type": "command", "command": "bash stop.sh", "matcher": "*"}],
            }
        }
        path = tmp_path / "claude-settings.json"
        path.write_text(json.dumps(settings))
        result = validate_claude_settings(str(path))
        assert result.passed is True

    def test_invalid_json_fails(self, tmp_path):
        path = tmp_path / "claude-settings.json"
        path.write_text("{not valid json")
        result = validate_claude_settings(str(path))
        assert result.passed is False

    def test_unknown_hook_event_warns(self, tmp_path):
        import json
        settings = {
            "hooks": {
                "InvalidEvent": [{"type": "command", "command": "bash test.sh", "matcher": "*"}],
            }
        }
        path = tmp_path / "claude-settings.json"
        path.write_text(json.dumps(settings))
        result = validate_claude_settings(str(path))
        # Unknown events should produce a warning, not a critical failure
        assert any(f.severity == "warning" for f in result.failures)


class TestHookScriptValidation:
    def test_valid_bash_script_passes(self, tmp_path):
        script = tmp_path / "test-hook.sh"
        script.write_text("#!/bin/bash\necho 'hello'\n")
        script.chmod(0o755)
        result = validate_hook_script(str(script))
        assert result.passed is True

    def test_syntax_error_fails(self, tmp_path):
        script = tmp_path / "bad-hook.sh"
        script.write_text("#!/bin/bash\nif [ then\n")
        script.chmod(0o755)
        result = validate_hook_script(str(script))
        assert result.passed is False
        assert any(f.check_name == "bash_syntax" for f in result.failures)


class TestHarnessVerifier:
    def test_full_verification_passes_with_valid_config(self, tmp_path):
        import json
        toml_content = """
[bridge]
data_dir = "/tmp/test"
log_dir = "/tmp/logs"
heartbeat_interval = 60

[claude]
timeout = 300
hard_timeout = 600
absolute_timeout = 1800
max_turns = 25

[session]
idle_timeout = 1800
max_errors = 3

[security]
disallowed_tools = []
tool_failure_threshold = 5
tool_failure_window = 600
"""
        (tmp_path / "bridge.toml").write_text(toml_content)
        settings = {"hooks": {}}
        (tmp_path / "claude-settings.json").write_text(json.dumps(settings))

        verifier = HarnessVerifier(config_dir=str(tmp_path))
        result = verifier.verify_all()
        assert result.passed is True
