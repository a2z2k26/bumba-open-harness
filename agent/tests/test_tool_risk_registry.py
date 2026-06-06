"""Tests for tool risk classification registry."""
from __future__ import annotations

import pytest
from bridge.tool_risk_registry import ToolRiskRegistry, RiskTier


class TestRiskTier:
    def test_tier_ordering(self):
        assert RiskTier.SAFE.severity < RiskTier.STANDARD.severity
        assert RiskTier.STANDARD.severity < RiskTier.ELEVATED.severity
        assert RiskTier.ELEVATED.severity < RiskTier.CRITICAL.severity


class TestToolRiskRegistry:
    @pytest.fixture
    def registry(self, tmp_path):
        yaml_content = """
tiers:
  safe:
    description: "Read-only"
    tools: [Read, Glob, Grep]
  standard:
    description: "Write operations"
    tools: [Edit, Write]
  elevated:
    description: "Broader impact"
    tools: [Bash, Agent, "mcp__github__*"]
  critical:
    description: "Infrastructure mutation"
    tools: ["mcp__cloudflare__*", RemoteTrigger]
default_tier: standard
"""
        yaml_file = tmp_path / "tool-risk.yaml"
        yaml_file.write_text(yaml_content)
        return ToolRiskRegistry.from_yaml(str(yaml_file))

    def test_safe_tool_returns_safe(self, registry):
        assert registry.get_tier("Read") == RiskTier.SAFE
        assert registry.get_tier("Glob") == RiskTier.SAFE

    def test_elevated_tool_returns_elevated(self, registry):
        assert registry.get_tier("Bash") == RiskTier.ELEVATED
        assert registry.get_tier("Agent") == RiskTier.ELEVATED

    def test_critical_tool_returns_critical(self, registry):
        assert registry.get_tier("RemoteTrigger") == RiskTier.CRITICAL

    def test_unknown_tool_returns_default(self, registry):
        assert registry.get_tier("SomeNewTool") == RiskTier.STANDARD

    def test_glob_pattern_matching_for_mcp(self, registry):
        # "mcp__github__*" should match mcp__github__create_issue
        assert registry.get_tier("mcp__github__create_issue") == RiskTier.ELEVATED
        assert registry.get_tier("mcp__cloudflare__deploy") == RiskTier.CRITICAL

    def test_list_tools_by_tier(self, registry):
        safe_tools = registry.list_by_tier(RiskTier.SAFE)
        assert "Read" in safe_tools
        assert "Edit" not in safe_tools

    def test_requires_approval_in_autonomous(self, registry):
        assert not registry.requires_approval("Read", context="autonomous")
        assert not registry.requires_approval("Edit", context="autonomous")
        assert registry.requires_approval("RemoteTrigger", context="autonomous")

    def test_elevated_does_not_require_approval_in_interactive(self, registry):
        assert not registry.requires_approval("Bash", context="interactive")

    def test_elevated_requires_approval_in_autonomous(self, registry):
        assert registry.requires_approval("mcp__github__create_issue", context="autonomous")
