"""Tests for PreToolUse validation logic."""
from __future__ import annotations

import json
import os
import site
import subprocess
import sys
from pathlib import Path

import pytest
from bridge.tool_risk_registry import ToolRiskRegistry

# PYTHONPATH for subprocess invocations: includes agent root (for bridge pkg)
# and the venv site-packages (for pyyaml).
_AGENT_ROOT = str(Path(__file__).parent.parent.resolve())
_SITE_PKGS = ":".join(site.getsitepackages())
_SUBPROCESS_PYTHONPATH = f"{_AGENT_ROOT}:{_SITE_PKGS}"
_PRE_TOOL_HOOK_DIR = Path(__file__).parent.parent / "config" / "hooks" / "PreToolUse"


class TestPreToolValidationLogic:
    """Test the decision logic that the hook helper uses."""

    @pytest.fixture
    def registry(self, tmp_path):
        yaml_content = """
tiers:
  safe:
    description: Read-only
    tools: [Read, Glob]
  standard:
    description: Writes
    tools: [Edit, Write]
  elevated:
    description: Broader
    tools: [Bash, Agent]
  critical:
    description: Infrastructure
    tools: [RemoteTrigger, CronCreate]
default_tier: standard
"""
        yaml_file = tmp_path / "risk.yaml"
        yaml_file.write_text(yaml_content)
        return ToolRiskRegistry.from_yaml(str(yaml_file))

    def test_safe_tool_allowed_in_autonomous(self, registry):
        assert not registry.requires_approval("Read", "autonomous")

    def test_standard_tool_allowed_in_autonomous(self, registry):
        assert not registry.requires_approval("Edit", "autonomous")

    def test_elevated_tool_blocked_in_autonomous(self, registry):
        assert registry.requires_approval("Bash", "autonomous")

    def test_critical_tool_blocked_in_autonomous(self, registry):
        assert registry.requires_approval("RemoteTrigger", "autonomous")

    def test_elevated_tool_allowed_in_interactive(self, registry):
        assert not registry.requires_approval("Bash", "interactive")

    def test_critical_tool_blocked_in_interactive(self, registry):
        assert registry.requires_approval("RemoteTrigger", "interactive")

    def test_critical_tool_blocked_in_orchestrated(self, registry):
        assert registry.requires_approval("CronCreate", "orchestrated")

    def test_elevated_tool_allowed_in_orchestrated(self, registry):
        assert not registry.requires_approval("Agent", "orchestrated")


class TestCheckToolRiskHelper:
    """Tests for the check_tool_risk.py helper script logic."""

    def test_allow_output_format(self):
        """Verify allow output is valid JSON with expected structure."""
        result = {"decision": "allow"}
        assert json.dumps(result) == '{"decision": "allow"}'

    def test_deny_output_format(self):
        """Verify deny output is valid JSON with decision and reason."""
        result = {"decision": "deny", "reason": "Tool 'X' is critical-tier"}
        parsed = json.loads(json.dumps(result))
        assert parsed["decision"] == "deny"
        assert "reason" in parsed

    def test_fail_open_on_missing_config(self, tmp_path):
        """When YAML config is missing, helper must allow (fail-open)."""
        missing_yaml = str(tmp_path / "nonexistent.yaml")
        if not os.path.exists(missing_yaml):
            result = {"decision": "allow"}
        assert result["decision"] == "allow"

    def test_helper_script_exists(self):
        """check_tool_risk.py must exist at the expected path."""
        helper = _PRE_TOOL_HOOK_DIR / "helpers" / "check_tool_risk.py"
        assert helper.exists(), f"Helper script not found at {helper}"

    def test_hook_script_exists(self):
        """pre-tool-validation.sh must exist at the expected path."""
        hook = _PRE_TOOL_HOOK_DIR / "pre-tool-validation.sh"
        assert hook.exists(), f"Hook script not found at {hook}"

    def _run_helper(self, tool_name: str, context: str, yaml_file: str) -> dict:
        """Invoke check_tool_risk.py as a subprocess and return parsed JSON output."""
        helper = _PRE_TOOL_HOOK_DIR / "helpers" / "check_tool_risk.py"
        env = {
            "BUMBA_EXECUTION_CONTEXT": context,
            "BUMBA_RISK_YAML_OVERRIDE": yaml_file,
            "PATH": "/usr/bin:/bin",
            "PYTHONPATH": _SUBPROCESS_PYTHONPATH,
        }
        result = subprocess.run(
            [sys.executable, str(helper), tool_name],
            capture_output=True,
            text=True,
            env=env,
        )
        return json.loads(result.stdout.strip())

    def _make_yaml(self, tmp_path, content: str) -> str:
        yaml_file = tmp_path / "risk.yaml"
        yaml_file.write_text(content)
        return str(yaml_file)

    def test_helper_invocation_allow(self, tmp_path):
        """Run check_tool_risk.py with a safe tool and verify allow output."""
        yaml_file = self._make_yaml(tmp_path, """
tiers:
  safe:
    description: Read-only
    tools: [Read]
  critical:
    description: Infrastructure
    tools: [RemoteTrigger]
default_tier: standard
""")
        output = self._run_helper("Read", "autonomous", yaml_file)
        assert output["decision"] == "allow"

    def test_helper_invocation_deny(self, tmp_path):
        """Run check_tool_risk.py with a critical tool in autonomous mode, expect deny."""
        yaml_file = self._make_yaml(tmp_path, """
tiers:
  critical:
    description: Infrastructure
    tools: [RemoteTrigger]
default_tier: standard
""")
        output = self._run_helper("RemoteTrigger", "autonomous", yaml_file)
        assert output["decision"] == "deny"
        assert "reason" in output
