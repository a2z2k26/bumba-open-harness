"""Async wrapper around tmux CLI for managing isolated agent sessions."""

from __future__ import annotations

import asyncio
import logging
import shlex
import shutil

logger = logging.getLogger(__name__)


class TmuxManager:
    """Low-level tmux CLI wrapper using a dedicated socket for agent isolation."""

    def __init__(self, socket_name: str = "bumba-agents") -> None:
        self._socket = socket_name

    async def is_available(self) -> bool:
        """Check if the tmux binary exists on PATH."""
        return shutil.which("tmux") is not None

    async def _run_tmux(self, *args: str) -> tuple[int, str, str]:
        """Run a tmux command and return (returncode, stdout, stderr)."""
        cmd = ["tmux", "-L", self._socket, *args]
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout_bytes, stderr_bytes = await proc.communicate()
        return (
            proc.returncode or 0,
            stdout_bytes.decode("utf-8", errors="replace").strip(),
            stderr_bytes.decode("utf-8", errors="replace").strip(),
        )

    async def create_session(
        self,
        name: str,
        command: str,
        working_dir: str | None = None,
        env: dict[str, str] | None = None,
    ) -> tuple[int, str, str]:
        """Create a new detached tmux session running *command*.

        Environment variables are injected via a bash wrapper.
        """
        # Build the shell command with env vars (shlex.quote to prevent injection)
        if env:
            exports = " && ".join(
                f'export {k}={shlex.quote(v)}' for k, v in env.items()
            )
            shell_cmd = f"bash -c '{exports} && exec {command}'"
        else:
            shell_cmd = f"bash -c '{command}'"

        args = ["new-session", "-d", "-s", name, shell_cmd]
        if working_dir:
            # Insert -c <dir> before the shell command
            args = ["new-session", "-d", "-s", name, "-c", working_dir, shell_cmd]

        return await self._run_tmux(*args)

    async def kill_session(self, name: str) -> bool:
        """Kill a tmux session by name. Returns True if killed."""
        rc, _, _ = await self._run_tmux("kill-session", "-t", name)
        return rc == 0

    async def session_exists(self, name: str) -> bool:
        """Check whether a session with the given name exists."""
        rc, _, _ = await self._run_tmux("has-session", "-t", name)
        return rc == 0

    async def list_sessions(self) -> list[dict[str, str]]:
        """List all sessions on this socket. Returns list of dicts with name/state/created."""
        rc, stdout, _ = await self._run_tmux(
            "list-sessions",
            "-F", "#{session_name}|#{session_windows}|#{session_created}",
        )
        if rc != 0 or not stdout:
            return []
        sessions = []
        for line in stdout.splitlines():
            parts = line.split("|", 2)
            if len(parts) >= 3:
                sessions.append({
                    "name": parts[0],
                    "windows": parts[1],
                    "created": parts[2],
                })
        return sessions

    async def capture_pane(self, name: str, lines: int = 50) -> str:
        """Capture the last N lines from a session's pane."""
        rc, stdout, _ = await self._run_tmux(
            "capture-pane", "-t", name, "-p", "-S", f"-{lines}",
        )
        if rc != 0:
            return ""
        return stdout

    async def send_keys(self, name: str, keys: str) -> bool:
        """Send keys to a tmux session (e.g. 'C-c' to interrupt)."""
        rc, _, _ = await self._run_tmux("send-keys", "-t", name, keys)
        return rc == 0

    async def kill_all_sessions(self) -> int:
        """Kill all sessions on this socket. Returns count killed."""
        sessions = await self.list_sessions()
        killed = 0
        for s in sessions:
            if await self.kill_session(s["name"]):
                killed += 1
        return killed
