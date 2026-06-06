"""WorktreeExecutor — runs a WorkOrder in an isolated git worktree.

Creates a dedicated git worktree for the WorkOrder, runs the subagent
inside it, then cleans up the worktree and branch regardless of outcome.
Handles parallel-safe execution (unique branch per WorkOrder ID).
"""
from __future__ import annotations

import asyncio
import logging
import os
import shutil
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bridge.claude_runner import ClaudeResult, ClaudeRunner
    from bridge.work_order import WorkOrder

log = logging.getLogger(__name__)


class WorktreeExecutor:
    """Creates a git worktree, runs subagent inside it, cleans up on exit.

    **Status: ACTIVE (low-traffic)** — wired unconditionally in the
    dispatcher; usage depends on ``environment_selector`` choices. See
    ``docs/architecture/executor-roadmap.md`` for the activation policy
    to increase routing through this executor.

    Worktrees are created at: ``<repo_root>/.worktrees/z3-<wo.id[:8]>``
    Branch name: ``z3-<wo.id[:8]>``

    Parallel-safe: each WorkOrder gets a unique branch and directory.
    Cleanup is guaranteed via try/finally, even if the runner raises.
    """

    def __init__(
        self,
        *,
        claude_runner: "ClaudeRunner | None",
        repo_root: Path,
        toolshed: "object | None" = None,
    ) -> None:
        self._claude_runner = claude_runner
        self._repo_root = Path(repo_root)
        self._toolshed = toolshed  # ToolShed | None — used for mcp_config_path (#630)

    async def execute(self, wo: "WorkOrder") -> "ClaudeResult":
        """Execute a WorkOrder inside an isolated git worktree.

        Raises:
            RuntimeError: If no runner is configured.
            Any exception from claude_runner.invoke propagates after cleanup.
        """
        if self._claude_runner is None:
            raise RuntimeError(
                f"WorktreeExecutor has no runner configured "
                f"(WorkOrder {wo.id[:8]})"
            )

        from bridge.tracing import get_tracer
        from bridge.z3_metrics import Z3Spans
        tracer = get_tracer("z3.executor.worktree")

        branch = f"z3-{wo.id[:8]}"
        wt_path = self._repo_root / ".worktrees" / branch

        # S08: spinup span
        with tracer.context_span(Z3Spans.EXECUTOR_SPINUP, attributes={"env": "worktree", "wo.id": wo.id[:8]}):
            await self._git_worktree_add(wt_path, branch)

        try:
            # S08: exec span
            with tracer.context_span(Z3Spans.EXECUTOR_EXEC, attributes={"env": "worktree", "wo.id": wo.id[:8]}):
                # #630: write-jail — BUMBA_AGENT_DEPTH=1 blocks recursive spawning
                jail_env: dict[str, str] = {
                    **os.environ,
                    "BUMBA_AGENT_DEPTH": "1",
                    "BUMBA_AGENT_TOOL": "worktree",
                }
                # #630: thread mcp_config_path from toolshed if available
                mcp_cfg: str | None = None
                if self._toolshed is not None:
                    try:
                        mcp_cfg = self._toolshed.tools_for_agent(  # type: ignore[attr-defined]
                            getattr(wo, "skill", "") or ""
                        )
                    except Exception:
                        pass
                result = await self._claude_runner.invoke(
                    message=wo.intent,
                    session_id=f"worktree-{wo.id[:8]}",
                    working_dir=str(wt_path),
                    env_vars=jail_env,
                    mcp_config_path=mcp_cfg,
                    permission_mode=getattr(wo.constraints, "permission_mode", "bypassPermissions"),  # #630
                )
        finally:
            await self._git_worktree_cleanup(wt_path, branch)

        return result

    async def _git_worktree_add(self, wt_path: Path, branch: str) -> None:
        """Create a git worktree at wt_path on a new branch."""
        wt_path.parent.mkdir(parents=True, exist_ok=True)
        proc = await asyncio.create_subprocess_exec(
            "git", "worktree", "add", "-b", branch, str(wt_path),
            cwd=str(self._repo_root),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, err = await proc.communicate()
        if proc.returncode != 0:
            raise RuntimeError(
                f"git worktree add failed (rc={proc.returncode}): "
                f"{err.decode(errors='replace').strip()}"
            )
        log.info("WorktreeExecutor: created worktree %s (branch %s)", wt_path, branch)

    async def _git_worktree_cleanup(self, wt_path: Path, branch: str) -> None:
        """Remove the worktree directory and delete the branch. Best-effort."""
        # Remove the worktree registration
        proc = await asyncio.create_subprocess_exec(
            "git", "worktree", "remove", "--force", str(wt_path),
            cwd=str(self._repo_root),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await proc.communicate()

        # Fallback: if the dir still exists, nuke it
        if wt_path.exists():
            shutil.rmtree(wt_path, ignore_errors=True)

        # Delete the branch
        proc = await asyncio.create_subprocess_exec(
            "git", "branch", "-D", branch,
            cwd=str(self._repo_root),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await proc.communicate()

        log.info("WorktreeExecutor: cleaned up worktree %s", branch)
