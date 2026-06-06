"""Tests for MS1.6: Self-Diagnosis Runbooks."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
import yaml

from bridge.diagnosis import RunbookEngine, DiagnosisStep, DiagnosisResult

RUNBOOK_DIR = Path(__file__).resolve().parent.parent / "config" / "runbooks"


class TestRunbookLoading:
    """Load and validate runbook YAML files."""

    def test_runbook_directory_exists(self):
        assert RUNBOOK_DIR.exists(), f"Runbook directory missing: {RUNBOOK_DIR}"

    def test_load_all_runbooks(self):
        engine = RunbookEngine(str(RUNBOOK_DIR))
        count = engine.load_runbooks()
        assert count >= 10, f"Expected 10+ runbooks, got {count}"

    def test_each_runbook_has_required_fields(self):
        engine = RunbookEngine(str(RUNBOOK_DIR))
        engine.load_runbooks()
        for rb_id, rb in engine.runbooks.items():
            assert "id" in rb, f"Runbook {rb_id} missing 'id'"
            assert "name" in rb, f"Runbook {rb_id} missing 'name'"
            assert "steps" in rb, f"Runbook {rb_id} missing 'steps'"
            assert len(rb["steps"]) >= 2, f"Runbook {rb_id} has fewer than 2 steps"

    def test_each_step_has_check_and_command(self):
        engine = RunbookEngine(str(RUNBOOK_DIR))
        engine.load_runbooks()
        for rb_id, rb in engine.runbooks.items():
            for step in rb.get("steps", []):
                assert "id" in step, f"Step in {rb_id} missing 'id'"
                assert "check" in step, f"Step {step.get('id', '?')} in {rb_id} missing 'check'"
                assert "command" in step, f"Step {step.get('id', '?')} in {rb_id} missing 'command'"

    def test_load_invalid_yaml_skipped(self):
        """Malformed YAML should be skipped with warning."""
        with tempfile.TemporaryDirectory() as tmpdir:
            bad = Path(tmpdir) / "bad.yaml"
            bad.write_text("{{invalid yaml")
            good = Path(tmpdir) / "good.yaml"
            good.write_text(yaml.dump({"id": "test", "name": "Test", "steps": []}))

            engine = RunbookEngine(tmpdir)
            count = engine.load_runbooks()
            assert count == 1

    def test_load_nonexistent_dir(self):
        engine = RunbookEngine("/nonexistent/path")
        count = engine.load_runbooks()
        assert count == 0


class TestTriggerMatching:
    """Trigger evaluation against health state."""

    def test_match_condition_equality(self):
        engine = RunbookEngine(str(RUNBOOK_DIR))
        engine.load_runbooks()

        # Simulate discord down
        state = {
            "status": "unhealthy",
            "components": {
                "discord": {"status": "down"},
                "claude": {"status": "up"},
                "database": {"status": "up"},
                "token": {"status": "up"},
            },
        }
        matched = engine.match_triggers(state)
        ids = [rb["id"] for rb in matched]
        assert "discord-disconnected" in ids

    def test_no_match_healthy(self):
        engine = RunbookEngine(str(RUNBOOK_DIR))
        engine.load_runbooks()

        state = {
            "status": "healthy",
            "components": {
                "discord": {"status": "up"},
                "claude": {"status": "up"},
                "database": {"status": "up"},
                "token": {"status": "up", "expires_in_seconds": 7200},
                "voice": {"status": "up"},
                "memory": {"search_functional": True},
            },
        }
        matched = engine.match_triggers(state)
        # Some runbooks may match on healthy (like kernel which checks "status == unhealthy")
        # but core ones should not
        ids = [rb["id"] for rb in matched]
        assert "discord-disconnected" not in ids
        assert "database-locked" not in ids
        assert "voice-backend-unreachable" not in ids

    def test_match_or_condition(self):
        engine = RunbookEngine(str(RUNBOOK_DIR))
        engine.load_runbooks()

        state = {
            "status": "unhealthy",
            "components": {
                "token": {"status": "down", "expires_in_seconds": 0},
            },
        }
        matched = engine.match_triggers(state)
        ids = [rb["id"] for rb in matched]
        assert "oauth-token-expired" in ids


class TestRunbookExecution:
    """Execute runbook steps."""

    @pytest.mark.asyncio
    async def test_execute_all_pass(self):
        runbook = {
            "id": "test-pass",
            "name": "Test All Pass",
            "steps": [
                {"id": "s1", "check": "Echo test", "command": "echo OK"},
                {"id": "s2", "check": "True", "command": "true"},
            ],
            "resolution": "n/a",
            "escalation": "none",
        }
        engine = RunbookEngine("/nonexistent")
        result = await engine.execute_runbook(runbook)
        assert result.overall_passed
        assert len(result.steps) == 2

    @pytest.mark.asyncio
    async def test_execute_step_fails(self):
        runbook = {
            "id": "test-fail",
            "name": "Test Failure",
            "steps": [
                {"id": "s1", "check": "This fails", "command": "false", "fix": "Do X"},
            ],
            "resolution": "Fix it",
            "escalation": "L3",
        }
        engine = RunbookEngine("/nonexistent")
        result = await engine.execute_runbook(runbook)
        assert not result.overall_passed
        assert result.steps[0].fix == "Do X"

    @pytest.mark.asyncio
    async def test_execute_timeout(self):
        runbook = {
            "id": "test-timeout",
            "name": "Test Timeout",
            "steps": [
                {"id": "s1", "check": "This times out", "command": "sleep 10"},
            ],
            "resolution": "",
            "escalation": "",
        }
        engine = RunbookEngine("/nonexistent")
        result = await engine.execute_runbook(runbook, timeout=1)
        assert not result.overall_passed
        assert result.steps[0].output == "TIMEOUT"


class TestDiagnosisResult:
    """DiagnosisResult formatting."""

    def test_format_summary_pass(self):
        result = DiagnosisResult(
            runbook_id="test",
            runbook_name="Test Runbook",
            steps=[DiagnosisStep("s1", "Check OK", True, "all good")],
            resolution="",
            escalation="",
            overall_passed=True,
        )
        summary = result.format_summary()
        assert "[PASS]" in summary
        assert "Check OK" in summary

    def test_format_summary_fail_includes_fix(self):
        result = DiagnosisResult(
            runbook_id="test",
            runbook_name="Test Runbook",
            steps=[DiagnosisStep("s1", "Check Failed", False, "error", fix="run fix.sh")],
            resolution="Do X",
            escalation="L3",
            overall_passed=False,
        )
        summary = result.format_summary()
        assert "[FAIL]" in summary
        assert "run fix.sh" in summary
        assert "Do X" in summary
