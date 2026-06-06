"""Tests for structured tool registry."""
from __future__ import annotations

import pytest
from bridge.tool_registry import ToolEntry, ToolRegistry


class TestToolEntry:
    def test_frozen_dataclass(self):
        entry = ToolEntry(
            name="Read",
            category="builtin",
            description="Read file contents",
            capabilities=("read",),
            source="anthropic",
        )
        assert entry.name == "Read"
        with pytest.raises(AttributeError):
            entry.name = "Write"  # type: ignore[misc]

    def test_capabilities_coerced_to_tuple(self):
        entry = ToolEntry(
            name="Bash",
            category="builtin",
            description="Execute shell commands",
            capabilities=["execute", "read", "write"],
            source="anthropic",
        )
        assert isinstance(entry.capabilities, tuple)
        assert "execute" in entry.capabilities

    def test_health_check_defaults_none(self):
        entry = ToolEntry(
            name="Read",
            category="builtin",
            description="Read files",
            capabilities=("read",),
            source="anthropic",
        )
        assert entry.health_check is None


class TestToolRegistry:
    @pytest.fixture
    def registry(self, tmp_path):
        yaml_content = """
tools:
  - name: Read
    category: builtin
    description: "Read files"
    capabilities: [read]
    source: anthropic
  - name: Edit
    category: builtin
    description: "Edit files"
    capabilities: [write]
    source: anthropic
  - name: mcp__github
    category: mcp
    description: "GitHub API"
    capabilities: [read, write, network]
    source: plugin
    health_check: mcp_monitor
  - name: mcp__cloudflare
    category: mcp
    description: "Cloudflare"
    capabilities: [infrastructure]
    source: plugin
    health_check: mcp_monitor
"""
        yaml_file = tmp_path / "tools.yaml"
        yaml_file.write_text(yaml_content)
        return ToolRegistry.from_yaml(str(yaml_file))

    def test_list_all_tools(self, registry):
        tools = registry.list_tools()
        assert len(tools) == 4

    def test_filter_by_category(self, registry):
        builtins = registry.list_tools(category="builtin")
        assert len(builtins) == 2
        assert all(t.category == "builtin" for t in builtins)

    def test_filter_by_capability(self, registry):
        writers = registry.list_tools(capability="write")
        names = [t.name for t in writers]
        assert "Edit" in names
        assert "mcp__github" in names
        assert "Read" not in names

    def test_tool_exists(self, registry):
        assert registry.tool_exists("Read")
        assert not registry.tool_exists("NonexistentTool")

    def test_get_tool(self, registry):
        entry = registry.get("Read")
        assert entry is not None
        assert entry.description == "Read files"

    def test_get_tool_returns_none_for_missing(self, registry):
        assert registry.get("FakeTool") is None

    def test_get_healthy_tools_without_monitor(self, registry):
        # Without MCP monitor, all tools are considered healthy
        healthy = registry.get_healthy_tools()
        assert len(healthy) == 4

    def test_get_tools_for_agent(self, registry):
        # Simulates what tool_isolation would provide
        tools = registry.get_tools_for_agent(
            allowed_mcp_servers=["github"]
        )
        names = [t.name for t in tools]
        assert "Read" in names  # builtins always included
        assert "mcp__github" in names
        assert "mcp__cloudflare" not in names

    def test_get_tools_for_agent_no_filter(self, registry):
        # No allowlist = all tools included
        tools = registry.get_tools_for_agent(allowed_mcp_servers=None)
        assert len(tools) == 4

    def test_get_healthy_tools_with_monitor_running(self, registry):
        class FakeServerInfo:
            def __init__(self, status):
                self.status = status

        class FakeMonitor:
            _server_states = {
                "github": FakeServerInfo("running"),
                "cloudflare": FakeServerInfo("running"),
            }

        registry.set_mcp_monitor(FakeMonitor())
        healthy = registry.get_healthy_tools()
        names = [t.name for t in healthy]
        assert "Read" in names
        assert "mcp__github" in names
        assert "mcp__cloudflare" in names

    def test_get_healthy_tools_with_monitor_crashed(self, registry):
        class FakeServerInfo:
            def __init__(self, status):
                self.status = status

        class FakeMonitor:
            _server_states = {
                "github": FakeServerInfo("running"),
                "cloudflare": FakeServerInfo("crashed"),
            }

        registry.set_mcp_monitor(FakeMonitor())
        healthy = registry.get_healthy_tools()
        names = [t.name for t in healthy]
        assert "Read" in names
        assert "mcp__github" in names
        assert "mcp__cloudflare" not in names

    def test_format_tools_list(self, registry):
        output = registry.format_tools_list()
        assert "Tool Registry" in output
        assert "BUILTIN" in output
        assert "MCP" in output
        assert "Read" in output
        assert "mcp__github" in output

    def test_from_yaml_real_file_structure(self, tmp_path):
        yaml_content = """
tools:
  - name: Bash
    category: builtin
    description: "Execute shell commands with sandboxing"
    capabilities: [execute, read, write]
    source: anthropic
  - name: mcp__notion
    category: mcp
    description: "Notion workspace"
    capabilities: [read, write, network]
    source: plugin
    health_check: mcp_monitor
"""
        yaml_file = tmp_path / "tool-registry.yaml"
        yaml_file.write_text(yaml_content)
        reg = ToolRegistry.from_yaml(str(yaml_file))
        assert reg.tool_exists("Bash")
        assert reg.tool_exists("mcp__notion")
        bash = reg.get("Bash")
        assert bash.category == "builtin"
        assert "execute" in bash.capabilities
