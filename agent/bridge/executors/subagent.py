"""SubagentExecutor — runs a WorkOrder as a subagent `claude -p` invocation.

S03: Hardened with write jail — every invocation runs against a filtered
MCP config (pre-approved subset only), with BUMBA_AGENT_DEPTH=1 set to
block recursion, and temp artifacts cleaned up even on exception.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from bridge.tool_isolation import IsolatedToolRegistry, IsolationConfig

if TYPE_CHECKING:
    from bridge.claude_runner import ClaudeResult, ClaudeRunner
    from bridge.work_order import WorkOrder

log = logging.getLogger(__name__)


def _is_safe_agent_id(agent_id: str) -> bool:
    """Return True when ``agent_id`` is safe to map to a prompt filename."""
    if not agent_id:
        return False
    return all(c.isalnum() or c in {"-", "_"} for c in agent_id)


def _resolve_system_prompt_path(wo: "WorkOrder") -> Path:
    """Resolve the Claude prompt file for a subagent WorkOrder.

    Generic WorkOrders keep the original subagent prompt. Named Zone 3
    assignments can opt into a concrete agent prompt under
    ``config/claude-files/agents`` without touching the Zone 4 PydanticAI
    team registry.
    """
    agent_root = Path(__file__).resolve().parent.parent.parent
    default_path = agent_root / "config" / "system-prompts" / "subagent.md"
    assignment = getattr(wo, "assignment", None)
    agent_id = getattr(assignment, "agent_id", "") if assignment else ""
    agent_type = getattr(assignment, "agent_type", "") if assignment else ""
    if agent_type == "engineering" and _is_safe_agent_id(agent_id):
        prompt_path = agent_root / "config" / "claude-files" / "agents" / f"{agent_id}.md"
        if prompt_path.exists():
            return prompt_path
        log.warning(
            "SubagentExecutor: assigned prompt missing agent_id=%s path=%s",
            agent_id,
            prompt_path,
        )
    return default_path


class SubagentExecutor:
    """Executes a WorkOrder by invoking claude_runner with a filtered MCP config.

    **Status: ACTIVE** (production primary) — see
    ``docs/architecture/executor-roadmap.md``.

    S03 write jail contract:
    - Builds an IsolatedEnv from master_mcp_config + allowed_mcp_servers
    - Passes env_vars (BUMBA_AGENT_DEPTH=1, BUMBA_AGENT_TOOL=subagent) to invoke
    - Passes mcp_config_path (filtered, mode 0600) to invoke
    - Cleans up the temp config in a finally block (success or exception)

    Backwards compatible: if master_mcp_config and allowed_mcp_servers are
    omitted, an empty master config is used (no MCP servers reach the subagent).
    """

    def __init__(
        self,
        *,
        claude_runner: "ClaudeRunner | None",
        master_mcp_config: dict | None = None,
        allowed_mcp_servers: list[str] | None = None,
    ) -> None:
        self._claude_runner = claude_runner
        self._registry = IsolatedToolRegistry(master_config=master_mcp_config or {})
        self._allowed = allowed_mcp_servers or []

    async def execute(self, wo: "WorkOrder") -> "ClaudeResult":
        """Invoke the claude runner with a write-jailed environment.

        Creates a filtered MCP config file (allowed_mcp_servers only),
        sets BUMBA_AGENT_DEPTH=1 to prevent recursion, and cleans up
        the temp file regardless of success or failure.

        Raises:
            RuntimeError: If no runner is configured.
            Any exception from claude_runner.invoke propagates after cleanup.
        """
        if self._claude_runner is None:
            raise RuntimeError(
                f"SubagentExecutor has no runner configured "
                f"(WorkOrder {wo.id[:8]})"
            )

        # Log label only — NOT passed to invoke(). A subagent dispatch is a
        # one-shot run with no prior Claude session to resume; passing a
        # synthetic non-UUID id reaches `claude -p --resume` and is rejected
        # ("not a UUID", exit 1). Pass session_id=None so claude starts fresh.
        # (#2345 — same root cause fixed in e2b.py; subagent had the latent twin.)
        log_label = f"subagent-{wo.id[:8]}"
        system_prompt_path = _resolve_system_prompt_path(wo)

        iso_config = IsolationConfig(
            tool_name="subagent",
            allowed_mcp_servers=self._allowed,
        )
        iso_env = self._registry.create_isolated_env(iso_config)

        log.info(
            "SubagentExecutor: WO %s → session %s (mcp servers: %s)",
            wo.id[:8],
            log_label,
            ", ".join(self._allowed) or "<none>",
        )

        try:
            result = await self._claude_runner.invoke(
                message=wo.intent,
                session_id=None,
                system_prompt_file=str(system_prompt_path) if system_prompt_path.exists() else None,
                mcp_config_path=iso_env.filtered_config_path,
                env_vars=iso_env.env_vars,
                permission_mode=getattr(wo.constraints, "permission_mode", "bypassPermissions"),  # #630
            )
            return result
        finally:
            iso_env.cleanup()
