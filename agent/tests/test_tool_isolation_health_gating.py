"""Tests for MCP health gating in tool isolation (Sprint E.5)."""
from __future__ import annotations

from bridge.tool_isolation import (
    filter_mcp_config_with_health,
)
from bridge.mcp_monitor import MCPServerInfo


class TestHealthGating:
    def test_healthy_servers_included(self):
        master = {"mcpServers": {
            "github": {"command": "npx github-mcp"},
            "mongodb": {"command": "npx mongodb-mcp"},
        }}
        health = {
            "github": MCPServerInfo(name="github", command="", status="running"),
            "mongodb": MCPServerInfo(name="mongodb", command="", status="running"),
        }
        filtered, excluded = filter_mcp_config_with_health(
            master, ["github", "mongodb"], health
        )
        assert "github" in filtered.get("mcpServers", {})
        assert "mongodb" in filtered.get("mcpServers", {})
        assert len(excluded) == 0

    def test_stopped_server_excluded(self):
        master = {"mcpServers": {
            "github": {"command": "npx github-mcp"},
            "mongodb": {"command": "npx mongodb-mcp"},
        }}
        health = {
            "github": MCPServerInfo(name="github", command="", status="running"),
            "mongodb": MCPServerInfo(name="mongodb", command="", status="stopped"),
        }
        filtered, excluded = filter_mcp_config_with_health(
            master, ["github", "mongodb"], health
        )
        assert "github" in filtered.get("mcpServers", {})
        assert "mongodb" not in filtered.get("mcpServers", {})
        assert len(excluded) == 1
        assert excluded[0].violation_type == "mcp_unhealthy"

    def test_crashed_server_excluded(self):
        master = {"mcpServers": {
            "github": {"command": "npx github-mcp"},
        }}
        health = {
            "github": MCPServerInfo(name="github", command="", status="crashed"),
        }
        filtered, excluded = filter_mcp_config_with_health(
            master, ["github"], health
        )
        assert "github" not in filtered.get("mcpServers", {})
        assert len(excluded) == 1
        assert excluded[0].violation_type == "mcp_unhealthy"

    def test_unknown_health_included_failopen(self):
        """If health data is missing, include the server (fail-open)."""
        master = {"mcpServers": {
            "github": {"command": "npx github-mcp"},
        }}
        # No health data for github
        filtered, excluded = filter_mcp_config_with_health(
            master, ["github"], {}
        )
        assert "github" in filtered.get("mcpServers", {})
        assert len(excluded) == 0

    def test_unknown_status_included_failopen(self):
        """Servers with status='unknown' are included (fail-open)."""
        master = {"mcpServers": {
            "github": {"command": "npx github-mcp"},
        }}
        health = {
            "github": MCPServerInfo(name="github", command="", status="unknown"),
        }
        filtered, excluded = filter_mcp_config_with_health(
            master, ["github"], health
        )
        assert "github" in filtered.get("mcpServers", {})
        assert len(excluded) == 0

    def test_server_not_in_allowed_list_excluded(self):
        """Servers not in the allowed list are never included regardless of health."""
        master = {"mcpServers": {
            "github": {"command": "npx github-mcp"},
            "mongodb": {"command": "npx mongodb-mcp"},
        }}
        health = {
            "github": MCPServerInfo(name="github", command="", status="running"),
            "mongodb": MCPServerInfo(name="mongodb", command="", status="running"),
        }
        filtered, excluded = filter_mcp_config_with_health(
            master, ["github"], health
        )
        assert "github" in filtered.get("mcpServers", {})
        assert "mongodb" not in filtered.get("mcpServers", {})
        # Not a violation — not an allowed server in the first place
        assert len(excluded) == 0

    def test_all_servers_unhealthy_returns_empty(self):
        master = {"mcpServers": {
            "github": {"command": "npx github-mcp"},
            "mongodb": {"command": "npx mongodb-mcp"},
        }}
        health = {
            "github": MCPServerInfo(name="github", command="", status="crashed"),
            "mongodb": MCPServerInfo(name="mongodb", command="", status="stopped"),
        }
        filtered, excluded = filter_mcp_config_with_health(
            master, ["github", "mongodb"], health
        )
        assert filtered.get("mcpServers", {}) == {}
        assert len(excluded) == 2

    def test_violation_details_contain_server_name(self):
        master = {"mcpServers": {
            "mongodb": {"command": "npx mongodb-mcp"},
        }}
        health = {
            "mongodb": MCPServerInfo(name="mongodb", command="", status="stopped"),
        }
        filtered, excluded = filter_mcp_config_with_health(
            master, ["mongodb"], health
        )
        assert len(excluded) == 1
        assert "mongodb" in excluded[0].details

    def test_violation_has_timestamp(self):
        master = {"mcpServers": {
            "github": {"command": "npx github-mcp"},
        }}
        health = {
            "github": MCPServerInfo(name="github", command="", status="crashed"),
        }
        filtered, excluded = filter_mcp_config_with_health(
            master, ["github"], health
        )
        assert excluded[0].timestamp != ""

    def test_empty_master_config(self):
        filtered, excluded = filter_mcp_config_with_health({}, ["github"], {})
        assert filtered == {}
        assert excluded == []

    def test_disabled_servers_key_respected(self):
        """Servers in _mcpServers_disabled are also health-gated."""
        master = {
            "mcpServers": {"github": {"command": "npx github-mcp"}},
            "_mcpServers_disabled": {"mongodb": {"command": "npx mongodb-mcp"}},
        }
        health = {
            "github": MCPServerInfo(name="github", command="", status="running"),
            "mongodb": MCPServerInfo(name="mongodb", command="", status="running"),
        }
        filtered, excluded = filter_mcp_config_with_health(
            master, ["github", "mongodb"], health
        )
        assert "github" in filtered.get("mcpServers", {})
        # mongodb was in _mcpServers_disabled in master — it should appear in mcpServers of filtered
        assert "mongodb" in filtered.get("mcpServers", {})
        assert len(excluded) == 0
