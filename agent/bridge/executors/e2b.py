"""E2BExecutor — runs a WorkOrder in an isolated E2B cloud sandbox.

Integration path (#416, S4.2 #2345): rather than re-implement the E2B SDK
lifecycle in Python, this executor reuses the existing, proven primitive —
``claude_runner`` invoked against a filtered MCP config that exposes ONLY the
``bumba-sandbox`` MCP server. That server (``bumba-sandbox-mcp``, already
registered in the runtime ``.mcp.json``) owns the E2B SDK and the full sandbox
lifecycle (init / file ops / command exec / kill). The invoked agent drives
those tools to spin up a sandbox, run the WorkOrder inside it, and tear it down
— exactly the "model is the orchestrator" shape the MCP was built for.

This mirrors ``SubagentExecutor`` (filtered MCP config + write-jail env +
``try/finally`` cleanup) and adds the E2B credential into the subprocess
environment so the ``bumba-sandbox`` server can authenticate.

Gate: the executor is only routable when the operator has set
``e2b_executor_enabled = true``, provisioned ``e2b_api_key``, AND a
``claude_runner`` is wired. Absent any of those, ``get_status()`` reports
``conditional_unwired`` and ``execute()`` raises so the gap is loud.

Security note: the fail-closed config validator (config.py Invariant 5) refuses
to boot when the flag is true with an empty key. Until E2B is enabled, use
WORKTREE for untrusted execution.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import TYPE_CHECKING

from bridge.tool_isolation import IsolatedToolRegistry, IsolationConfig

if TYPE_CHECKING:
    from bridge.claude_runner import ClaudeResult, ClaudeRunner

    from bridge.work_order import WorkOrder

log = logging.getLogger(__name__)

# The single MCP server the E2B agent is allowed to reach. The bumba-sandbox
# server owns the E2B SDK + sandbox lifecycle; nothing else is exposed.
E2B_MCP_SERVER = "bumba-sandbox"

# The bumba-sandbox tools the E2B agent needs to drive a sandbox run, named by
# their real registered identifiers (see
# mcp-servers/bumba-sandbox/src/mcp-servers/bumba-sandbox.ts). Recent Claude
# Code defers MCP tools behind the ToolSearch surface — they never appear in
# the init `tools` list — so naming them here in `--allowedTools` pre-authorizes
# the calls. The agent still discovers them via ToolSearch (per e2b.md), but
# once surfaced they are immediately callable instead of hitting a permission
# gate. Tools are surfaced to the agent as ``mcp__<server>__<tool>``.
_E2B_SANDBOX_TOOLS = (
    "sandbox_init",
    "sandbox_create",
    "sandbox_connect",
    "sandbox_kill",
    "sandbox_status",
    "files_read",
    "files_write",
    "files_list",
    "file_exists",
    "execute_command",
)
E2B_ALLOWED_TOOLS = [
    f"mcp__{E2B_MCP_SERVER}__{tool}" for tool in _E2B_SANDBOX_TOOLS
]

E2B_GATE_MESSAGE = (
    "E2B executor is not routable: it requires e2b_executor_enabled = true, a "
    "non-empty e2b_api_key, and a wired claude_runner. Use WORKTREE for "
    "untrusted execution until E2B is provisioned. "
    "See docs/architecture/executor-roadmap.md for the activation checklist "
    "(#416)."
)


def _e2b_system_prompt_path() -> Path:
    """Resolve the E2B sandbox system-prompt file."""
    agent_root = Path(__file__).resolve().parent.parent.parent
    return agent_root / "config" / "system-prompts" / "e2b.md"


class E2BExecutor:
    """Runs a WorkOrder inside an E2B cloud sandbox via the bumba-sandbox MCP.

    **Status: CONDITIONAL** — see ``docs/architecture/executor-roadmap.md``.

    Default-off and non-routable. When the operator sets
    ``e2b_executor_enabled = true``, provisions ``e2b_api_key``, AND a
    ``claude_runner`` is wired, the executor becomes routable
    (``conditional_active``) and ``execute()`` drives a real E2B sandbox run
    by invoking ``claude_runner`` with a filtered MCP config exposing only the
    ``bumba-sandbox`` server.

    Write-jail contract (mirrors SubagentExecutor):
    - Builds an IsolatedEnv from master_mcp_config filtered to [bumba-sandbox]
    - Sets BUMBA_AGENT_DEPTH=1 / BUMBA_AGENT_TOOL=e2b to block recursion
    - Injects E2B_API_KEY into the subprocess env so bumba-sandbox can auth
    - Cleans up the temp config in a finally block (success or exception)
    """

    def __init__(
        self,
        *,
        enabled: bool = False,
        api_key: str = "",
        claude_runner: "ClaudeRunner | None" = None,
        master_mcp_config: dict | None = None,
    ) -> None:
        self._enabled = enabled
        self._api_key = api_key
        self._claude_runner = claude_runner
        self._registry = IsolatedToolRegistry(master_config=master_mcp_config or {})

    def _is_routable(self) -> bool:
        """True only when flag + credential + runner are all present."""
        return bool(
            self._enabled
            and self._api_key.strip()
            and self._claude_runner is not None
        )

    def get_status(self) -> str:
        """Return dispatcher-facing routability status for E2B.

        ``conditional_unwired`` (non-routable) when the operator has not
        enabled E2B, the credential is absent, or no ``claude_runner`` was
        wired into the dispatcher. ``conditional_active`` (routable) when all
        three are present and ``execute()`` will drive a real sandbox run.
        """
        if not self._is_routable():
            return "conditional_unwired"
        return "conditional_active"

    async def execute(self, wo: "WorkOrder") -> "ClaudeResult":
        """Run the WorkOrder inside an E2B sandbox via the bumba-sandbox MCP.

        Invokes ``claude_runner`` with a filtered MCP config (bumba-sandbox
        only) and an E2B system prompt instructing the agent to spin up a
        sandbox, run the work inside it, and tear it down. The E2B credential
        is injected into the subprocess env so the MCP server can authenticate.

        Raises:
            RuntimeError: If the executor is not routable (gate active) — the
                flag, credential, or runner is missing. The message points at
                the activation checklist; the exception propagates to the
                dispatcher (no silent fallthrough).
            Any exception from claude_runner.invoke propagates after cleanup.
        """
        if not self._is_routable():
            log.warning(
                "E2BExecutor: WorkOrder %s requested E2B — gate active "
                "(enabled=%s key=%s runner=%s)",
                wo.id[:8],
                self._enabled,
                bool(self._api_key.strip()),
                self._claude_runner is not None,
            )
            raise RuntimeError(E2B_GATE_MESSAGE)

        assert self._claude_runner is not None  # narrowed by _is_routable

        # An E2B sandbox run is one-shot: there is no prior Claude session to
        # resume. The synthetic ``e2b-<hash>`` string below is a LOG LABEL only
        # — it MUST NOT be passed to claude_runner.invoke as ``session_id``.
        # claude's ``--resume`` requires a real UUID / existing session title;
        # feeding it a synthetic ``e2b-<hash>`` makes ``claude -p --resume
        # e2b-<hash>`` fail with "not a UUID and does not match any session"
        # (exit 1, num_turns 0). Pass session_id=None → no ``--resume`` flag →
        # claude starts a fresh session (backend build_command guards on
        # ``if session_id``).
        log_label = f"e2b-{wo.id[:8]}"
        system_prompt_path = _e2b_system_prompt_path()

        iso_config = IsolationConfig(
            tool_name="e2b",
            allowed_mcp_servers=[E2B_MCP_SERVER],
        )
        iso_env = self._registry.create_isolated_env(iso_config)

        # Inject the E2B credential so the bumba-sandbox MCP server can auth.
        # Start from the write-jail env (BUMBA_AGENT_DEPTH=1, etc.), layer the
        # current process env underneath so node/PATH resolve, then set the key.
        env_vars: dict[str, str] = {
            **os.environ,
            **iso_env.env_vars,
            "E2B_API_KEY": self._api_key,
        }

        log.info(
            "E2BExecutor: WO %s → fresh session (label %s, sandbox via %s MCP)",
            wo.id[:8],
            log_label,
            E2B_MCP_SERVER,
        )

        try:
            result = await self._claude_runner.invoke(
                message=wo.intent,
                # Fresh session — see comment above. NEVER a synthetic id.
                session_id=None,
                system_prompt_file=(
                    str(system_prompt_path) if system_prompt_path.exists() else None
                ),
                mcp_config_path=iso_env.filtered_config_path,
                env_vars=env_vars,
                permission_mode=getattr(
                    wo.constraints, "permission_mode", "bypassPermissions"
                ),
                allowed_tools=E2B_ALLOWED_TOOLS,
            )
            return result
        finally:
            iso_env.cleanup()
