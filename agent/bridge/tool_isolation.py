"""MS5.6 — Isolated Tool Registries.

Enforce strict tool access boundaries per sub-agent. Each agent-tool
gets a filtered MCP config, bash allowlists, recursion prevention,
and resource limits.
"""

from __future__ import annotations

import json
import logging
import os
import re
import tempfile
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MAX_AGENT_DEPTH = 1
DAILY_TOKEN_BUDGET = 500_000
BUDGET_ALERT_THRESHOLD = 0.80

DEFAULT_DENIED_PATTERNS = [
    r"rm\s+-rf",
    r"\bsudo\b",
    r"curl.*POST",
    r"eval\s*\(",
    r"exec\s*\(",
    r"__import__",
    r"os\.system",
    r"subprocess\.call",
    r"--no-verify",
    r"--force",
]


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class IsolationConfig:
    """Per-agent-tool isolation configuration."""

    tool_name: str = ""
    allowed_mcp_servers: list[str] = field(default_factory=list)
    allowed_bash_patterns: list[str] = field(default_factory=list)
    denied_operations: list[str] = field(default_factory=list)
    max_tokens: int = 50_000
    max_duration: int = 120
    max_tool_calls: int = 20
    max_output_size: int = 100_000


@dataclass
class IsolatedEnv:
    """An isolated environment for a sub-agent invocation."""

    filtered_config_path: str = ""
    env_vars: dict[str, str] = field(default_factory=dict)
    cleanup_done: bool = False

    def cleanup(self) -> None:
        """Remove temporary files."""
        if self.filtered_config_path and os.path.exists(self.filtered_config_path):
            try:
                os.unlink(self.filtered_config_path)
            except OSError:
                pass
        self.cleanup_done = True


@dataclass
class BoundaryViolation:
    """A detected boundary violation."""

    violation_type: str = ""  # bash_denied, mcp_unauthorized, sensitive_data, recursion
    details: str = ""
    timestamp: str = ""


@dataclass
class InvocationAudit:
    """Audit record for an agent-tool invocation."""

    invocation_id: str = ""
    agent_tool: str = ""
    timestamp: str = ""
    mcp_servers_available: list[str] = field(default_factory=list)
    tokens_used: int = 0
    duration_seconds: float = 0.0
    boundary_violations: list[BoundaryViolation] = field(default_factory=list)
    result_valid: bool = False
    output_size_bytes: int = 0


# ---------------------------------------------------------------------------
# MCP Config Filtering
# ---------------------------------------------------------------------------


def filter_mcp_config(
    master_config: dict, allowed_servers: list[str]
) -> dict:
    """Filter a master MCP config to only include allowed servers.

    Args:
        master_config: Full .mcp.json contents
        allowed_servers: List of server names to include

    Returns:
        Filtered config dict. The top-level ``mcpServers`` key is ALWAYS
        present (an empty object when no allowed server matched the master
        config). ``claude -p --mcp-config <file>`` validates the file against
        the MCP schema and rejects a bare ``{}`` with "mcpServers: Does not
        adhere to MCP server configuration schema" — so emitting the key
        unconditionally keeps the produced file schema-valid even in the
        zero-match case. See the E2B seam bug (#2345): a single-server
        allowlist (``bumba-sandbox``) that misses the master config used to
        degrade to ``{}`` and crash the subprocess before it ran.
    """
    # Seed the contract key so the written file is always schema-valid.
    filtered: dict = {"mcpServers": {}}
    allowed_set = set(allowed_servers)

    # Handle both mcpServers and _mcpServers_disabled keys
    for key in ("mcpServers", "_mcpServers_disabled"):
        servers = master_config.get(key, {})
        if servers:
            for name, config in servers.items():
                if name in allowed_set:
                    filtered["mcpServers"][name] = config

    return filtered


def filter_mcp_config_with_health(
    master_config: dict,
    allowed_servers: list[str],
    server_health: dict,
) -> tuple[dict, list[BoundaryViolation]]:
    """Filter MCP config, excluding unhealthy servers.

    Servers with status 'stopped' or 'crashed' are excluded and reported as
    BoundaryViolation entries with violation_type='mcp_unhealthy'.

    Fail-open: servers with no health data (missing from server_health) or
    with status 'unknown' are included in the filtered config.

    Args:
        master_config: Full .mcp.json contents
        allowed_servers: List of server names to include
        server_health: Dict mapping server name -> MCPServerInfo

    Returns:
        (filtered_config, excluded_violations)
    """
    filtered: dict = {}
    excluded: list[BoundaryViolation] = []
    allowed_set = set(allowed_servers)
    now = datetime.now(timezone.utc).isoformat()

    for key in ("mcpServers", "_mcpServers_disabled"):
        servers = master_config.get(key, {})
        for name, config in servers.items():
            if name not in allowed_set:
                continue

            # Check health — fail-open if no health data or status unknown
            health_info = server_health.get(name)
            if health_info is not None:
                status = getattr(health_info, "status", "unknown")
                if status in ("stopped", "crashed"):
                    excluded.append(BoundaryViolation(
                        violation_type="mcp_unhealthy",
                        details=(
                            f"MCP server '{name}' is {status} — excluded from tool pool"
                        ),
                        timestamp=now,
                    ))
                    continue

            filtered.setdefault("mcpServers", {})[name] = config

    return filtered, excluded


# ---------------------------------------------------------------------------
# Bash Command Validation
# ---------------------------------------------------------------------------


def check_bash_command(
    command: str,
    allowed_patterns: list[str] | None = None,
    denied_patterns: list[str] | None = None,
) -> tuple[bool, str]:
    """Check if a bash command is allowed.

    Returns (allowed, reason).
    """
    if denied_patterns is None:
        denied_patterns = DEFAULT_DENIED_PATTERNS

    # Check denied patterns first
    for pattern in denied_patterns:
        if re.search(pattern, command, re.IGNORECASE):
            return False, f"Matches denied pattern: {pattern}"

    # If allowlist provided, command must match at least one
    if allowed_patterns:
        for pattern in allowed_patterns:
            if re.search(pattern, command):
                return True, ""
        return False, "Does not match any allowed pattern"

    return True, ""


# ---------------------------------------------------------------------------
# Recursion Prevention
# ---------------------------------------------------------------------------


def check_recursion(env_vars: dict[str, str]) -> tuple[bool, str]:
    """Check if agent depth allows invocation.

    Returns (allowed, reason).
    """
    depth_str = env_vars.get("BUMBA_AGENT_DEPTH", "0")
    try:
        depth = int(depth_str)
    except ValueError:
        depth = 0

    if depth >= MAX_AGENT_DEPTH:
        return False, f"Agent depth {depth} >= max {MAX_AGENT_DEPTH} — recursion blocked"

    return True, ""


# ---------------------------------------------------------------------------
# Budget Tracking
# ---------------------------------------------------------------------------


class BudgetTracker:
    """Track daily token budget across all agent-tool invocations."""

    def __init__(self) -> None:
        self._daily_usage: dict[str, int] = {}  # date -> tokens
        self._per_tool: dict[str, int] = {}  # tool_name -> tokens

    def record_usage(self, tool_name: str, tokens: int) -> None:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        self._daily_usage[today] = self._daily_usage.get(today, 0) + tokens
        self._per_tool[tool_name] = self._per_tool.get(tool_name, 0) + tokens

    def get_daily_usage(self) -> int:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        return self._daily_usage.get(today, 0)

    def get_tool_usage(self, tool_name: str) -> int:
        return self._per_tool.get(tool_name, 0)

    def is_over_budget(self) -> bool:
        return self.get_daily_usage() >= DAILY_TOKEN_BUDGET

    def should_alert(self) -> bool:
        return self.get_daily_usage() >= DAILY_TOKEN_BUDGET * BUDGET_ALERT_THRESHOLD

    def get_remaining(self) -> int:
        return max(0, DAILY_TOKEN_BUDGET - self.get_daily_usage())


# ---------------------------------------------------------------------------
# Output Scanning
# ---------------------------------------------------------------------------

_SENSITIVE_PATTERNS = [
    re.compile(r"(?:sk|pk)[-_](?:live|test)[-_][a-zA-Z0-9]{20,}"),
    re.compile(r"(?:ghp|gho|ghu|ghs|ghr)_[a-zA-Z0-9]{36,}"),
    re.compile(r"xoxb-[0-9]{10,}-[a-zA-Z0-9]{20,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
]


def scan_output_for_violations(
    output: str,
    denied_patterns: list[str] | None = None,
) -> list[BoundaryViolation]:
    """Scan sub-agent output for boundary violations."""
    violations: list[BoundaryViolation] = []
    now = datetime.now(timezone.utc).isoformat()

    # Check for sensitive data patterns
    for pattern in _SENSITIVE_PATTERNS:
        if pattern.search(output):
            violations.append(BoundaryViolation(
                violation_type="sensitive_data",
                details=f"Sensitive data pattern detected: {pattern.pattern[:30]}",
                timestamp=now,
            ))

    # Check for denied bash patterns in output
    if denied_patterns is None:
        denied_patterns = DEFAULT_DENIED_PATTERNS
    for dp in denied_patterns:
        if re.search(dp, output, re.IGNORECASE):
            violations.append(BoundaryViolation(
                violation_type="bash_denied",
                details=f"Denied operation in output: {dp}",
                timestamp=now,
            ))

    return violations


# ---------------------------------------------------------------------------
# IsolatedToolRegistry
# ---------------------------------------------------------------------------


class IsolatedToolRegistry:
    """Creates and manages isolated environments for sub-agent invocations."""

    def __init__(
        self, master_config: dict | None = None, *, tool_shed: object | None = None
    ) -> None:
        self._master_config = master_config or {}
        self._budget = BudgetTracker()
        self._audits: list[InvocationAudit] = []
        self._tool_shed = tool_shed

    def create_isolated_env(self, config: IsolationConfig) -> IsolatedEnv:
        """Create an isolated environment for a sub-agent.

        Returns IsolatedEnv with filtered MCP config and env vars.
        """
        # If no explicit allowed_mcp_servers but ToolShed is available,
        # use the Tool Shed's per-agent loadout
        if not config.allowed_mcp_servers and self._tool_shed is not None:
            from dataclasses import replace as dc_replace
            config = dc_replace(
                config,
                allowed_mcp_servers=self._tool_shed.tools_for_agent(config.tool_name),
            )

        # Filter MCP config
        filtered = filter_mcp_config(self._master_config, config.allowed_mcp_servers)

        # Write to temp file
        temp_dir = Path(tempfile.gettempdir()) / "bumba-agent-tools"
        temp_dir.mkdir(exist_ok=True)
        temp_path = temp_dir / f"mcp-{uuid.uuid4().hex[:8]}.json"
        temp_path.write_text(json.dumps(filtered, indent=2))
        try:
            os.chmod(str(temp_path), 0o600)
        except OSError:
            pass

        env_vars = {
            "BUMBA_AGENT_DEPTH": "1",
            "BUMBA_AGENT_TOOL": config.tool_name,
            "MCP_CONFIG_PATH": str(temp_path),
        }

        return IsolatedEnv(
            filtered_config_path=str(temp_path),
            env_vars=env_vars,
        )

    def validate_invocation(
        self,
        config: IsolationConfig,
        env_vars: dict[str, str] | None = None,
    ) -> tuple[bool, str]:
        """Validate that an invocation is allowed.

        Checks recursion depth and budget.
        """
        # Check recursion
        if env_vars:
            ok, reason = check_recursion(env_vars)
            if not ok:
                return False, reason

        # Check budget
        if self._budget.is_over_budget():
            return False, f"Daily token budget exhausted ({DAILY_TOKEN_BUDGET:,} tokens)"

        return True, ""

    def record_invocation(self, audit: InvocationAudit) -> None:
        """Record an invocation audit."""
        self._audits.append(audit)
        self._budget.record_usage(audit.agent_tool, audit.tokens_used)

    def get_audits(self, tool_name: str | None = None, limit: int = 50) -> list[InvocationAudit]:
        """Get recent audit records."""
        audits = self._audits
        if tool_name:
            audits = [a for a in audits if a.agent_tool == tool_name]
        return audits[-limit:]

    def get_budget(self) -> BudgetTracker:
        return self._budget

    def count_violations(self) -> int:
        """Count total boundary violations across all audits."""
        return sum(len(a.boundary_violations) for a in self._audits)
