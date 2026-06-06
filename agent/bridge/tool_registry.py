"""Structured tool registry with metadata and runtime queries.

Unifies tool metadata from YAML config, MCP health from mcp_monitor,
and risk tiers from tool_risk_registry into a single queryable registry.

Integration:
    - Loaded at startup from config/tool-registry.yaml
    - mcp_monitor.py provides health status for MCP tools
    - IsolatedToolRegistry.create_isolated_env() consults for metadata
    - commands.py: /tools operator command
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ToolEntry:
    """Metadata for a single tool.

    Attributes:
        name: Tool identifier (e.g. "Read", "mcp__github")
        category: Tool category — builtin | mcp | skill | command
        description: Human-readable description
        capabilities: Tuple of capability strings (read, write, execute, network, infrastructure)
        source: Origin — anthropic | plugin | user-defined
        health_check: Health check provider name, if any (e.g. "mcp_monitor")
    """

    name: str
    category: str
    description: str
    capabilities: tuple[str, ...]
    source: str
    health_check: str | None = None

    def __init__(
        self,
        name: str,
        category: str,
        description: str,
        capabilities: tuple[str, ...] | list[str] = (),
        source: str = "anthropic",
        health_check: str | None = None,
    ) -> None:
        object.__setattr__(self, "name", name)
        object.__setattr__(self, "category", category)
        object.__setattr__(self, "description", description)
        object.__setattr__(self, "capabilities", tuple(capabilities))
        object.__setattr__(self, "source", source)
        object.__setattr__(self, "health_check", health_check)


class ToolRegistry:
    """Queryable registry of tool metadata.

    Supports filtering by category, capability, and health status.
    Can be augmented with an MCPMonitor instance to provide live health checks.
    """

    def __init__(self, entries: list[ToolEntry]) -> None:
        self._entries: dict[str, ToolEntry] = {e.name: e for e in entries}
        self._mcp_monitor: Any = None

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------

    @classmethod
    def from_yaml(cls, path: str) -> ToolRegistry:
        """Load registry from a YAML config file.

        Args:
            path: Absolute path to YAML file with a top-level ``tools`` list.

        Returns:
            Populated ToolRegistry instance.

        Raises:
            FileNotFoundError: If the YAML file does not exist.
        """
        try:
            import yaml  # type: ignore[import-untyped]
        except ImportError as exc:
            raise ImportError(
                "PyYAML is required for ToolRegistry.from_yaml(). "
                "Install it with: pip install pyyaml"
            ) from exc

        with open(path) as fh:
            data = yaml.safe_load(fh)

        entries: list[ToolEntry] = []
        for tool_data in data.get("tools", []):
            entries.append(
                ToolEntry(
                    name=tool_data["name"],
                    category=tool_data.get("category", "builtin"),
                    description=tool_data.get("description", ""),
                    capabilities=tool_data.get("capabilities", []),
                    source=tool_data.get("source", "anthropic"),
                    health_check=tool_data.get("health_check"),
                )
            )

        logger.debug("Loaded %d tools from %s", len(entries), path)
        return cls(entries)

    # ------------------------------------------------------------------
    # Configuration
    # ------------------------------------------------------------------

    def set_mcp_monitor(self, monitor: Any) -> None:
        """Attach an MCPMonitor instance for health-aware queries.

        Args:
            monitor: An object with a ``_server_states`` dict mapping
                server names to objects with a ``status`` attribute.
        """
        self._mcp_monitor = monitor

    # ------------------------------------------------------------------
    # Single-tool lookups
    # ------------------------------------------------------------------

    def get(self, name: str) -> ToolEntry | None:
        """Get a tool by exact name.

        Args:
            name: Tool name (e.g. "Read", "mcp__github").

        Returns:
            ToolEntry if found, None otherwise.
        """
        return self._entries.get(name)

    def tool_exists(self, name: str) -> bool:
        """Return True if a tool with this name is registered."""
        return name in self._entries

    # ------------------------------------------------------------------
    # Filtered queries
    # ------------------------------------------------------------------

    def list_tools(
        self,
        category: str | None = None,
        capability: str | None = None,
    ) -> list[ToolEntry]:
        """List tools with optional filters.

        Args:
            category: Filter by category string (e.g. "builtin", "mcp").
            capability: Filter to tools that include this capability string.

        Returns:
            List of matching ToolEntry objects (insertion order preserved).
        """
        results = list(self._entries.values())

        if category is not None:
            results = [t for t in results if t.category == category]

        if capability is not None:
            results = [t for t in results if capability in t.capabilities]

        return results

    def get_healthy_tools(self) -> list[ToolEntry]:
        """Return tools whose health check passes.

        For MCP tools, checks mcp_monitor status (running = healthy).
        Non-MCP tools are always considered healthy.
        If no MCP monitor is attached, all tools are returned.

        Returns:
            List of healthy ToolEntry objects.
        """
        if self._mcp_monitor is None:
            return list(self._entries.values())

        healthy: list[ToolEntry] = []
        server_states: dict[str, Any] = getattr(
            self._mcp_monitor, "_server_states", {}
        )

        for entry in self._entries.values():
            if entry.category != "mcp":
                healthy.append(entry)
                continue

            # Derive server name: "mcp__github" → "github"
            server_name = entry.name.replace("mcp__", "", 1)
            server_info = server_states.get(server_name)

            if server_info is None or getattr(server_info, "status", None) == "running":
                healthy.append(entry)
            # else: stopped / crashed / unknown — exclude

        return healthy

    def get_tools_for_agent(
        self,
        allowed_mcp_servers: list[str] | None = None,
    ) -> list[ToolEntry]:
        """Return tools available to a specific agent.

        Built-in (non-MCP) tools are always included.
        MCP tools are filtered to ``allowed_mcp_servers`` if provided.

        Args:
            allowed_mcp_servers: List of server names without the ``mcp__``
                prefix (e.g. ["github", "notion"]). If None, all MCP tools
                are included.

        Returns:
            List of ToolEntry objects available to the agent.
        """
        allowed_set: set[str] | None = set(allowed_mcp_servers) if allowed_mcp_servers is not None else None
        results: list[ToolEntry] = []

        for entry in self._entries.values():
            if entry.category != "mcp":
                results.append(entry)
                continue

            if allowed_set is None:
                results.append(entry)
            else:
                server_name = entry.name.replace("mcp__", "", 1)
                if server_name in allowed_set:
                    results.append(entry)

        return results

    # ------------------------------------------------------------------
    # Formatting
    # ------------------------------------------------------------------

    def format_tools_list(self, tools: list[ToolEntry] | None = None) -> str:
        """Format tools as markdown for operator display.

        Args:
            tools: Subset of tools to format. Defaults to all registered tools.

        Returns:
            Markdown-formatted string grouped by category.
        """
        tools = tools if tools is not None else list(self._entries.values())
        lines = [f"## Tool Registry ({len(tools)} tools)", ""]

        by_category: dict[str, list[ToolEntry]] = {}
        for t in tools:
            by_category.setdefault(t.category, []).append(t)

        for cat in ("builtin", "mcp", "skill", "command"):
            cat_tools = by_category.get(cat, [])
            if not cat_tools:
                continue
            lines.append(f"### {cat.upper()} ({len(cat_tools)})")
            for t in sorted(cat_tools, key=lambda x: x.name):
                caps = ", ".join(t.capabilities) if t.capabilities else "none"
                lines.append(f"- **{t.name}** — {t.description} [{caps}]")
            lines.append("")

        return "\n".join(lines)
