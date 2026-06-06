"""TmuxExecutor — adapter that runs WorkOrders via TmuxAgentManager.

Thin wrapper: spawn → poll monitor_agents → collect terminal state.
Timeout enforced via wo.constraints.timeout_ms. Permission mode threaded
through from wo.constraints.permission_mode (S05, native Claude Code
--permission-mode flag — replaces hardcoded --dangerously-skip-permissions).
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bridge.claude_runner import ClaudeResult
    from bridge.tmux_agents import TmuxAgentManager
    from bridge.work_order import WorkOrder

log = logging.getLogger(__name__)

DEFAULT_POLL_INTERVAL_S = 2.0
_TERMINAL_STATUSES = frozenset({"completed", "failed", "killed"})


def _reap_process_tree(pid: int | None) -> None:
    """SIGTERM the process tree rooted at pid, then SIGKILL after grace period.

    S09 sub-bet 5: ensures no orphan processes after executor timeout.
    Gracefully handles cases where psutil is unavailable.
    """
    if pid is None:
        return
    try:
        import psutil
        try:
            parent = psutil.Process(pid)
        except psutil.NoSuchProcess:
            return
        children = parent.children(recursive=True)
        for child in children:
            try:
                child.terminate()
            except psutil.NoSuchProcess:
                pass
        try:
            parent.terminate()
        except psutil.NoSuchProcess:
            pass
        # Wait up to 3s then force-kill survivors
        _, alive = psutil.wait_procs([parent] + children, timeout=3)
        for p in alive:
            try:
                p.kill()
            except psutil.NoSuchProcess:
                pass
        log.debug("Reaped process tree rooted at PID %d", pid)
    except ImportError:
        # psutil not available — fall back to SIGTERM only via os.kill
        import os
        import signal
        try:
            os.kill(pid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            pass


class TmuxExecutor:
    """Executes a WorkOrder by spawning a tmux session via TmuxAgentManager.

    **Status: CONDITIONAL** — registered only when ``tmux_manager`` is
    wired into the dispatcher constructor. See
    ``docs/architecture/executor-roadmap.md`` for activation criteria.

    Behavior contract:
    - spawn_agent(wo.intent) → AgentState (success) or str (failure)
    - poll monitor_agents() every poll_interval_s until terminal status
    - if timeout_ms exceeded: kill_agent(agent_id), return error result
    """

    def __init__(
        self,
        *,
        tmux_mgr: "TmuxAgentManager | None",
        poll_interval_s: float = DEFAULT_POLL_INTERVAL_S,
        prewarm_pool: object | None = None,
    ) -> None:
        self._mgr = tmux_mgr
        self._poll = poll_interval_s
        self._pool = prewarm_pool  # TmuxPrewarmPool | None

    async def execute(self, wo: "WorkOrder") -> "ClaudeResult":
        """Spawn a tmux agent for the WorkOrder and wait for completion.

        Raises:
            RuntimeError: If no manager is configured or spawn returns an error string.
        """
        if self._mgr is None:
            raise RuntimeError(
                f"TmuxExecutor has no manager configured (WorkOrder {wo.id[:8]})"
            )

        from bridge.tracing import get_tracer
        from bridge.z3_metrics import Z3Spans
        tracer = get_tracer("z3.executor.tmux")

        # S08: spinup span
        with tracer.context_span(Z3Spans.EXECUTOR_SPINUP, attributes={"env": "tmux", "wo.id": wo.id[:8]}):
            # S14: try pre-warm pool first
            warm_slot = None
            if self._pool is not None:
                try:
                    warm_slot = await self._pool.acquire()  # type: ignore[attr-defined]
                except Exception:
                    log.warning("TmuxExecutor: pool.acquire() failed — falling back to cold spawn")

            # S05: thread wo.constraints.permission_mode through spawn_agent
            perm_mode = getattr(wo.constraints, "permission_mode", "bypassPermissions")

            if warm_slot is not None:
                log.info("TmuxExecutor: using pre-warm slot %s for WO %s", warm_slot.agent_id[:8], wo.id[:8])
                # Build a mock agent state from the warm slot
                agent = await self._mgr.spawn_agent(
                    wo.intent,
                    reuse_session=warm_slot.session_name,
                    permission_mode=perm_mode,
                )
                if isinstance(agent, str):
                    # Reuse failed — fall back to normal spawn
                    agent = await self._mgr.spawn_agent(wo.intent, permission_mode=perm_mode)
            else:
                agent = await self._mgr.spawn_agent(wo.intent, permission_mode=perm_mode)

            if isinstance(agent, str):
                raise RuntimeError(f"TmuxExecutor spawn failed: {agent}")

        timeout_s = wo.constraints.timeout_ms / 1000.0
        deadline = time.monotonic() + timeout_s
        t_start = time.monotonic()
        _agent_pid: int | None = getattr(agent, "pid", None)

        # S08: exec span
        with tracer.context_span(Z3Spans.EXECUTOR_EXEC, attributes={"env": "tmux", "wo.id": wo.id[:8]}):
            while agent.status not in _TERMINAL_STATUSES:
                await asyncio.sleep(self._poll)
                await self._mgr.monitor_agents()

                if time.monotonic() > deadline:
                    log.warning(
                        "TmuxExecutor: WO %s timed out after %.1fs — killing agent %s",
                        wo.id[:8], timeout_s, agent.agent_id,
                    )
                    await self._mgr.kill_agent(agent.agent_id)
                    # S09 sub-bet 5: reap process tree
                    _reap_process_tree(_agent_pid)
                    from bridge.claude_runner import ClaudeResult
                    return ClaudeResult(
                        response_text=agent.result_text or "",
                        session_id=f"tmux-{agent.agent_id}",
                        cost_usd=agent.cost_usd,
                        num_turns=agent.num_turns,
                        duration_ms=wo.constraints.timeout_ms,
                        is_error=True,
                        error_type="tmux_timeout",
                    )

        elapsed_ms = int((time.monotonic() - t_start) * 1000)
        is_err = agent.status != "completed"

        from bridge.claude_runner import ClaudeResult
        return ClaudeResult(
            response_text=agent.result_text or "",
            session_id=f"tmux-{agent.agent_id}",
            cost_usd=agent.cost_usd,
            num_turns=agent.num_turns,
            duration_ms=elapsed_ms,
            is_error=is_err,
            error_type=f"tmux_{agent.status}" if is_err else "",
        )
