"""Tmux-based agent lifecycle management: spawn, monitor, collect, kill."""

from __future__ import annotations

import json
import logging
import os
import shlex
import shutil
import tempfile
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .autonomy import AutonomyLayer
    from .config import BridgeConfig
    from .tmux_manager import TmuxManager
    from .token_refresher import TokenRefresher

logger = logging.getLogger(__name__)


@dataclass
class AgentState:
    """State of a single spawned tmux agent."""
    agent_id: str = ""
    session_name: str = ""
    task: str = ""
    status: str = "spawning"       # spawning | running | completed | failed | killed
    started_at: float = 0.0
    completed_at: float = 0.0
    output_file: str = ""
    result_text: str = ""
    cost_usd: float = 0.0
    num_turns: int = 0
    exit_code: int = -1
    error: str = ""
    max_lifetime_s: int = 14400    # 4 hours
    # S05: per-agent wrapper script path. Owned by bumba-agent mode 0700,
    # contains `export CLAUDE_CODE_OAUTH_TOKEN=...` and the exec line. tmux
    # invokes this script directly (NOT via a shell with export in argv),
    # so ps -eww never sees the token. Removed by _collect_result.
    wrapper_script: str = ""

    def to_dict(self) -> dict:
        return {
            "agent_id": self.agent_id,
            "session_name": self.session_name,
            "task": self.task[:500],
            "status": self.status,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "output_file": self.output_file,
            "result_text": self.result_text[:2000],
            "cost_usd": self.cost_usd,
            "num_turns": self.num_turns,
            "exit_code": self.exit_code,
            "error": self.error,
            "max_lifetime_s": self.max_lifetime_s,
            "wrapper_script": self.wrapper_script,
        }

    @classmethod
    def from_dict(cls, d: dict) -> AgentState:
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


class TmuxAgentManager:
    """Manages spawning, monitoring, and collecting results from tmux-based Claude agents."""

    def __init__(
        self,
        tmux: TmuxManager,
        config: BridgeConfig,
        token_provider: TokenRefresher | None = None,
        autonomy: AutonomyLayer | None = None,
        max_concurrent: int = 3,
        max_lifetime_s: int = 14400,
    ) -> None:
        self._tmux = tmux
        self._config = config
        self._token_provider = token_provider
        self._autonomy = autonomy
        self._max_concurrent = max_concurrent
        self._max_lifetime_s = max_lifetime_s
        self._agents: dict[str, AgentState] = {}
        self._data_dir = Path(config.data_dir)
        self._agents_dir = self._data_dir / "agents"
        self._agents_dir.mkdir(parents=True, exist_ok=True)
        self._registry_path = self._agents_dir / "registry.json"
        self._messages_dir = self._data_dir / "service_messages"
        self._messages_dir.mkdir(parents=True, exist_ok=True)

    def _active_count(self) -> int:
        """Count agents in spawning or running status."""
        return sum(
            1 for a in self._agents.values()
            if a.status in ("spawning", "running")
        )

    def _get_oauth_token(self) -> str:
        """Get the current OAuth token from the token provider or config."""
        if self._token_provider and hasattr(self._token_provider, "access_token"):
            token = self._token_provider.access_token
            if token:
                return token
        return self._config.claude_oauth_token or ""

    async def spawn_agent(
        self,
        task: str,
        working_dir: str | None = None,
        max_turns: int = 25,
        permission_mode: str = "bypassPermissions",
    ) -> AgentState | str:
        """Spawn a new Claude agent in a tmux session.

        Returns AgentState on success, error string on failure.

        Args:
            permission_mode: Claude Code native --permission-mode value.
                One of: "acceptEdits", "auto", "bypassPermissions", "default",
                "dontAsk", "plan". Defaults to "bypassPermissions" to preserve
                pre-S05 behaviour; callers should pass wo.constraints.permission_mode.
        """
        if self._active_count() >= self._max_concurrent:
            return f"Max concurrent agents ({self._max_concurrent}) reached. Kill one first."

        if not task.strip():
            return "Task description cannot be empty."

        if not await self._tmux.is_available():
            return "tmux is not installed. Run: brew install tmux"

        agent_id = uuid.uuid4().hex[:8]
        session_name = f"bumba-{agent_id}"
        agent_dir = self._agents_dir / agent_id
        agent_dir.mkdir(parents=True, exist_ok=True)

        # Write task file
        task_file = agent_dir / "task.txt"
        task_file.write_text(task)

        output_file = agent_dir / "output.jsonl"

        # Snapshot OAuth token at spawn time. token_refresher rotates every
        # ~8h; if rotation happens mid-session, that agent's re-auth fails.
        # Acceptable given typical WO runtime of minutes.
        oauth_token = self._get_oauth_token()
        if not oauth_token:
            return "No OAuth token available. Cannot spawn agent."

        # Resolve Claude binary
        claude_binary = shutil.which("claude")
        if self._config.claude_binary:
            claude_binary = self._config.claude_binary
        if not claude_binary:
            for candidate in (
                Path.home() / ".local" / "bin" / "claude",
                Path("/usr/local/bin/claude"),
            ):
                if candidate.is_file():
                    claude_binary = str(candidate)
                    break
        if not claude_binary:
            return "Claude binary not found."

        # S05 security: write a per-agent wrapper script that carries the
        # OAuth token in its FILE BODY (mode 0700) rather than in argv.
        # tmux invokes the script directly, so `ps -eww` sees only the
        # script path, never the token string. The old pattern (env=
        # kwarg on tmux_manager.create_session) builds a shell command
        # with `export TOK=value && exec claude -p ...` — that string
        # lands in argv and leaks via ps. See issue #567.
        try:
            wrapper_path = self._write_wrapper_script(
                agent_id=agent_id,
                oauth_token=oauth_token,
                claude_binary=claude_binary,
                task_file=task_file,
                output_file=output_file,
                max_turns=max_turns,
                permission_mode=permission_mode,
            )
        except OSError as exc:
            return f"Failed to write wrapper script: {exc}"

        cwd = working_dir or self._config.claude_working_dir

        # Pass the script path as the command. NO env dict — the wrapper
        # script exports the token internally from its file body.
        rc, stdout, stderr = await self._tmux.create_session(
            name=session_name,
            command=wrapper_path,
            working_dir=cwd,
            env=None,
        )

        if rc != 0:
            self._cleanup_wrapper(wrapper_path)
            return f"Failed to create tmux session: {stderr}"

        # Create agent state
        agent = AgentState(
            agent_id=agent_id,
            session_name=session_name,
            task=task[:500],
            status="running",
            started_at=time.time(),
            output_file=str(output_file),
            max_lifetime_s=self._max_lifetime_s,
            wrapper_script=wrapper_path,
        )
        self._agents[agent_id] = agent
        self._save_registry()

        # Publish event
        if self._autonomy:
            try:
                self._autonomy.event_bus.publish("agent.spawned", {
                    "agent_id": agent_id,
                    "task": task[:200],
                })
            except Exception:
                pass

        logger.info("Spawned agent %s: %s", agent_id, task[:100])
        return agent

    def _write_wrapper_script(
        self,
        *,
        agent_id: str,
        oauth_token: str,
        claude_binary: str,
        task_file: Path,
        output_file: Path,
        max_turns: int,
        permission_mode: str,
    ) -> str:
        """Write a per-agent wrapper shell script and return its path.

        The script body contains `export CLAUDE_CODE_OAUTH_TOKEN='...'` and
        `exec cat <task> | claude -p ... > <output>`. File mode is 0700,
        owner bumba-agent, under tempfile.gettempdir(). tmux invokes the
        script directly, so `ps -eww` sees only the script path — not the token.

        Security notes:
        - Token lives only inside the file body, which is mode 0600/0700
          and owned by the bridge user.
        - Path itself carries no secrets and is safe to appear in ps output.
        - File is deleted on session end (see _collect_result). A startup
          reaper (reap_orphan_wrapper_scripts) handles orphans from crashes.
        """
        fd, path = tempfile.mkstemp(
            prefix=f"bumba-tmux-wrap-{agent_id}-",
            suffix=".sh",
            dir=tempfile.gettempdir(),
        )
        # Build the inner exec line. shlex.quote() every user-derived path
        # so a malicious task filename cannot break out of the shell.
        quoted_task = shlex.quote(str(task_file))
        quoted_output = shlex.quote(str(output_file))
        quoted_claude = shlex.quote(claude_binary)
        quoted_token = shlex.quote(oauth_token)
        quoted_mode = shlex.quote(permission_mode)

        body = (
            "#!/bin/bash\n"
            "# bumba-agent tmux wrapper — carries OAuth token in file body\n"
            "# instead of argv (issue #567). Deleted after session ends.\n"
            f"export CLAUDE_CODE_OAUTH_TOKEN={quoted_token}\n"
            f"cat {quoted_task} | {quoted_claude} -p"
            f" --output-format stream-json --verbose"
            f" --max-turns {int(max_turns)}"
            f" --permission-mode {quoted_mode}"
            f" > {quoted_output} 2>&1\n"
            f'echo "EXIT_CODE:$?" >> {quoted_output}\n'
        )

        try:
            with os.fdopen(fd, "w") as f:
                f.write(body)
        except Exception:
            try:
                os.unlink(path)
            except OSError:
                pass
            raise

        # 0700: readable + executable by owner only. Defense against umask
        # giving us 0644 (world-readable) by default.
        os.chmod(path, 0o700)
        return path

    @staticmethod
    def _cleanup_wrapper(wrapper_path: str) -> None:
        """Best-effort delete of a per-agent wrapper script."""
        if not wrapper_path:
            return
        try:
            os.unlink(wrapper_path)
        except OSError:
            logger.debug("Failed to remove wrapper script %s", wrapper_path, exc_info=True)

    def reap_orphan_wrapper_scripts(self) -> int:
        """Clean up orphaned bumba-tmux-wrap-* scripts from prior crashes.

        Called on bridge startup. A script is orphaned if its agent_id is
        not in the current registry. Returns the count removed.
        """
        tmp_parent = Path(tempfile.gettempdir())
        if not tmp_parent.exists():
            return 0

        known_agents = set(self._agents.keys())
        removed = 0
        prefix = "bumba-tmux-wrap-"
        for path in tmp_parent.glob(f"{prefix}*.sh"):
            if not path.is_file():
                continue
            # Name format: bumba-tmux-wrap-<agent_id>-<tmp-suffix>.sh
            rest = path.name[len(prefix):]
            agent_id = rest.split("-", 1)[0]
            if agent_id in known_agents:
                continue
            try:
                path.unlink()
                removed += 1
            except OSError:
                logger.debug("Failed to reap orphan %s", path, exc_info=True)

        if removed:
            logger.info("Reaped %d orphan tmux wrapper scripts", removed)
        return removed

    async def monitor_agents(self) -> list[str]:
        """Check all active agents, collect results for completed ones.

        Called from the heartbeat loop. Returns list of status change messages.
        """
        messages = []
        now = time.time()

        for agent_id in list(self._agents.keys()):
            agent = self._agents[agent_id]
            if agent.status not in ("spawning", "running"):
                continue

            # Check if session still exists
            alive = await self._tmux.session_exists(agent.session_name)

            if not alive:
                # Session ended — collect results
                await self._collect_result(agent)
                msg = (
                    f"Agent {agent_id} {agent.status}: "
                    f"{agent.task[:80]}... "
                    f"(cost=${agent.cost_usd:.4f}, turns={agent.num_turns})"
                )
                messages.append(msg)
                self._save_registry()

            elif (now - agent.started_at) > agent.max_lifetime_s:
                # Exceeded max lifetime — kill it
                await self._tmux.kill_session(agent.session_name)
                agent.status = "killed"
                agent.completed_at = now
                agent.error = "Exceeded max lifetime"
                await self._collect_result(agent)
                msg = f"Agent {agent_id} killed: exceeded {agent.max_lifetime_s}s lifetime"
                messages.append(msg)
                self._save_registry()

        return messages

    async def _collect_result(self, agent: AgentState) -> None:
        """Parse the output file and update agent state."""
        output_path = Path(agent.output_file)
        if not output_path.exists():
            agent.status = "failed"
            agent.error = "Output file not found"
            agent.completed_at = time.time()
            # S05: still delete the wrapper script on early-return failure
            if agent.wrapper_script:
                self._cleanup_wrapper(agent.wrapper_script)
                agent.wrapper_script = ""
            return

        text_parts: list[str] = []
        exit_code = -1

        try:
            content = output_path.read_text(errors="replace")
            for line in content.splitlines():
                line = line.strip()
                if not line:
                    continue

                # Check for exit code marker
                if line.startswith("EXIT_CODE:"):
                    try:
                        exit_code = int(line.split(":", 1)[1])
                    except (ValueError, IndexError):
                        pass
                    continue

                # Try to parse as JSON (stream-json output)
                try:
                    data = json.loads(line)
                except json.JSONDecodeError:
                    continue

                event_type = data.get("type", "")

                if event_type == "assistant":
                    message = data.get("message", {})
                    if isinstance(message, dict):
                        for block in message.get("content", []):
                            if isinstance(block, dict) and block.get("type") == "text":
                                text_parts.append(block.get("text", ""))

                elif event_type == "result":
                    agent.cost_usd = data.get("cost_usd", 0.0)
                    agent.num_turns = data.get("num_turns", 0)
                    result_text = data.get("result", "")
                    if isinstance(result_text, str) and result_text:
                        text_parts.append(result_text)
                    if data.get("is_error"):
                        agent.status = "failed"
                        agent.error = data.get("subtype", "unknown_error")

        except Exception as e:
            agent.status = "failed"
            agent.error = f"Failed to parse output: {e}"
            agent.completed_at = time.time()
            # S05: cleanup on parse failure
            if agent.wrapper_script:
                self._cleanup_wrapper(agent.wrapper_script)
                agent.wrapper_script = ""
            return

        agent.exit_code = exit_code
        agent.result_text = text_parts[-1][:2000] if text_parts else ""
        agent.completed_at = time.time()

        if agent.status not in ("failed", "killed"):
            agent.status = "completed" if exit_code == 0 else "failed"
            if exit_code != 0 and not agent.error:
                agent.error = f"Exit code {exit_code}"

        # Deliver result to Discord via service message
        if agent.result_text:
            self._deliver_result(agent)

        # S05: delete the per-agent wrapper script (contains OAuth token in
        # its file body). Best-effort — a leak would still be bounded by
        # token rotation (~8h) and the mode-0700 + bumba-agent ownership.
        if agent.wrapper_script:
            self._cleanup_wrapper(agent.wrapper_script)
            agent.wrapper_script = ""

        # Publish event
        if self._autonomy:
            try:
                self._autonomy.event_bus.publish(f"agent.{agent.status}", {
                    "agent_id": agent.agent_id,
                    "cost_usd": agent.cost_usd,
                    "num_turns": agent.num_turns,
                    "exit_code": agent.exit_code,
                })
            except Exception:
                pass

    def _deliver_result(self, agent: AgentState) -> None:
        """Write agent result as a service message for bridge pickup."""
        chat_id = self._config.operator_discord_id
        result_preview = agent.result_text[:1500]
        status_emoji = {"completed": "done", "failed": "FAILED", "killed": "KILLED"}
        label = status_emoji.get(agent.status, agent.status)

        text = (
            f"**Agent {agent.agent_id} [{label}]**\n"
            f"Task: {agent.task[:200]}\n"
            f"Cost: ${agent.cost_usd:.4f} | Turns: {agent.num_turns}\n\n"
            f"{result_preview}"
        )

        msg = {
            "chat_id": chat_id,
            "text": text,
            "source": "tmux-agent",
            "timestamp": time.time(),
        }
        filename = f"tmux-agent_{int(time.time() * 1000)}_{agent.agent_id}.json"
        path = self._messages_dir / filename
        path.write_text(json.dumps(msg, indent=2))
        logger.info("Agent result delivered: %s", filename)

    def list_agents(self) -> list[AgentState]:
        """Return all known agents (active and completed)."""
        return list(self._agents.values())

    def format_agents_table(self) -> str:
        """Format agents as a status table."""
        if not self._agents:
            return "No agents."

        lines = ["**Agents:**", "```"]
        lines.append(f"{'ID':<10} {'Status':<12} {'Age':<8} {'Cost':<10} {'Task'}")
        lines.append("-" * 70)

        for agent in sorted(self._agents.values(), key=lambda a: a.started_at, reverse=True):
            elapsed = time.time() - agent.started_at
            if elapsed < 60:
                age = f"{int(elapsed)}s"
            elif elapsed < 3600:
                age = f"{int(elapsed / 60)}m"
            else:
                age = f"{elapsed / 3600:.1f}h"

            cost = f"${agent.cost_usd:.4f}" if agent.cost_usd else "-"
            task_preview = agent.task[:35]
            lines.append(f"{agent.agent_id:<10} {agent.status:<12} {age:<8} {cost:<10} {task_preview}")

        lines.append("```")
        return "\n".join(lines)

    def format_agent_detail(self, agent_id: str) -> str | None:
        """Format detailed info for a single agent."""
        agent = self._agents.get(agent_id)
        if not agent:
            return None

        elapsed = time.time() - agent.started_at
        lines = [
            f"**Agent {agent.agent_id}**",
            f"Status: {agent.status}",
            f"Task: {agent.task}",
            f"Age: {elapsed:.0f}s",
            f"Cost: ${agent.cost_usd:.4f}",
            f"Turns: {agent.num_turns}",
            f"Exit code: {agent.exit_code}",
        ]
        if agent.error:
            lines.append(f"Error: {agent.error}")
        if agent.result_text:
            lines.append(f"\n**Result:**\n{agent.result_text[:1000]}")
        return "\n".join(lines)

    async def get_agent_output(self, agent_id: str) -> str | None:
        """Get the live pane output for a running agent."""
        agent = self._agents.get(agent_id)
        if not agent:
            return None
        if agent.status in ("spawning", "running"):
            return await self._tmux.capture_pane(agent.session_name, lines=30)
        # For completed agents, return result text
        return agent.result_text or "(no output)"

    async def kill_agent(self, agent_id: str) -> bool:
        """Kill a running agent."""
        agent = self._agents.get(agent_id)
        if not agent:
            return False
        if agent.status not in ("spawning", "running"):
            return False

        killed = await self._tmux.kill_session(agent.session_name)
        if killed:
            agent.status = "killed"
            agent.completed_at = time.time()
            agent.error = "Killed by operator"
            await self._collect_result(agent)
            self._save_registry()
        return killed

    async def shutdown(self) -> None:
        """Persist registry on bridge shutdown. Tmux agents keep running independently."""
        active = sum(
            1 for a in self._agents.values()
            if a.status in ("spawning", "running")
        )
        self._save_registry()
        if active:
            logger.info("Shutdown: %d agents still running in tmux (will recover on restart)", active)

    async def recover_from_restart(self) -> int:
        """Load registry and reconcile with live tmux sessions."""
        self._load_registry()
        reconciled = 0

        for agent_id in list(self._agents.keys()):
            agent = self._agents[agent_id]
            if agent.status not in ("spawning", "running"):
                continue

            alive = await self._tmux.session_exists(agent.session_name)
            if not alive:
                await self._collect_result(agent)
                reconciled += 1

        if reconciled:
            self._save_registry()
            logger.info("Recovered %d agents from restart", reconciled)

        return reconciled

    def _save_registry(self) -> None:
        """Atomic write of all agent states to registry.json."""
        data = {
            agent_id: agent.to_dict()
            for agent_id, agent in self._agents.items()
        }
        fd, tmp_path = tempfile.mkstemp(
            dir=self._agents_dir, suffix=".tmp"
        )
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(data, f, indent=2)
            os.replace(tmp_path, self._registry_path)
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

    def _load_registry(self) -> None:
        """Load agent states from registry.json."""
        if not self._registry_path.exists():
            return
        try:
            data = json.loads(self._registry_path.read_text())
            for agent_id, agent_dict in data.items():
                self._agents[agent_id] = AgentState.from_dict(agent_dict)
            logger.info("Loaded %d agents from registry", len(self._agents))
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("Failed to load agent registry: %s", e)
