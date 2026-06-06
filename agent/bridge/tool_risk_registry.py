"""Tool risk classification registry.

Loads risk tiers from YAML config and provides runtime queries.
Supports glob patterns for MCP tools (e.g., mcp__github__*).

Integration:
    - permission_audit.py: includes risk tier in decision logging
    - tool_isolation.py: consults tier for autonomous mode gating
    - pre-tool-validation hook: queries requires_approval()
"""
from __future__ import annotations

import enum
import fnmatch
import logging
from bridge.dispatch_metrics import increment_module_counter

logger = logging.getLogger(__name__)


class RiskTier(enum.Enum):
    """Tool risk tiers, ordered by severity."""
    SAFE = "safe"
    STANDARD = "standard"
    ELEVATED = "elevated"
    CRITICAL = "critical"

    @property
    def severity(self) -> int:
        return {"safe": 0, "standard": 1, "elevated": 2, "critical": 3}[self.value]


class ToolRiskRegistry:
    """Registry mapping tool names to risk tiers.

    Supports exact matches and glob patterns (for MCP tools like mcp__github__*).
    """

    def __init__(
        self,
        exact_mappings: dict[str, RiskTier],
        glob_patterns: list[tuple[str, RiskTier]],
        default_tier: RiskTier = RiskTier.STANDARD,
    ) -> None:
        self._exact = exact_mappings
        self._globs = glob_patterns  # ordered: more specific first
        self._default = default_tier

    @classmethod
    def from_yaml(cls, path: str) -> "ToolRiskRegistry":
        """Load from YAML config file."""
        import yaml  # type: ignore[import-untyped]

        with open(path) as f:
            data = yaml.safe_load(f)

        exact: dict[str, RiskTier] = {}
        globs: list[tuple[str, RiskTier]] = []

        for tier_name, tier_data in data.get("tiers", {}).items():
            tier = RiskTier(tier_name)
            for tool_name in tier_data.get("tools", []):
                if "*" in tool_name or "?" in tool_name:
                    globs.append((tool_name, tier))
                else:
                    exact[tool_name] = tier

        default = RiskTier(data.get("default_tier", "standard"))
        return cls(exact, globs, default)

    def get_tier(self, tool_name: str) -> RiskTier:
        increment_module_counter("tool_risk_registry.get_tier", tier=1)
        """Get the risk tier for a tool. Falls back to glob patterns, then default."""
        # Exact match first
        if tool_name in self._exact:
            return self._exact[tool_name]

        # Glob pattern match
        for pattern, tier in self._globs:
            if fnmatch.fnmatch(tool_name, pattern):
                return tier

        return self._default

    def list_by_tier(self, tier: RiskTier) -> list[str]:
        """List all explicitly registered tools at a given tier."""
        return [name for name, t in self._exact.items() if t == tier]

    def requires_approval(self, tool_name: str, context: str = "interactive") -> bool:
        """Check if a tool requires operator approval in the given context.

        Rules:
        - interactive: only critical tools require approval
        - autonomous: elevated + critical require approval
        - orchestrated: critical requires approval
        """
        tier = self.get_tier(tool_name)

        if context == "autonomous":
            return tier.severity >= RiskTier.ELEVATED.severity
        elif context == "orchestrated":
            return tier.severity >= RiskTier.CRITICAL.severity
        else:  # interactive
            return tier.severity >= RiskTier.CRITICAL.severity
