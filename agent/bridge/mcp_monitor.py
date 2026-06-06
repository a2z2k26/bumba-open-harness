"""MCP server health monitor -- observe and report MCP process status.

Reads .mcp.json to discover expected servers, then uses pgrep/ps to check
whether each server process is running and how much memory it consumes.

This module does NOT start or stop MCP servers.  Claude's subprocess
lifecycle manages that.  We only observe and report.

D7.7 fix (issue #1232):
- ``_derive_pgrep_pattern`` extracts a reliable match string from each
  server's config rather than pgrep-ing for the bare server key, which
  does not appear in the actual process command line for mcp-remote entries.
  For cloudflare the spawned process contains ``bindings.mcp.cloudflare.com``
  not the bare key ``cloudflare``.
- Crash tracking is gated by ``_last_seen_running``: on-demand MCPs that
  are legitimately stopped for more than ``RECENT_RUN_WINDOW`` seconds no
  longer accumulate crash-loop entries.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

# A server that crashes more than this many times within the window
# is considered to be in a crash loop.
CRASH_LOOP_THRESHOLD = 3
CRASH_LOOP_WINDOW = 3600  # seconds (1 hour)

# Only crash-track if the server was last seen running within this window.
# On-demand MCPs (bumba-memory, bumba-sandbox, cloudflare) are legitimately
# stopped for long periods; without this gate they would accumulate crash
# entries on every health-check tick.
RECENT_RUN_WINDOW = 600  # 10 minutes


def _derive_pgrep_pattern(name: str, cfg: dict) -> str:
    """Return a pgrep -f pattern that reliably matches the spawned process.

    The process command line for mcp-remote entries looks like:
        node /path/to/mcp-remote https://bindings.mcp.cloudflare.com/mcp

    The bare server key (e.g. ``cloudflare``) does not appear in that
    command line.  Using the URL host (e.g. ``bindings.mcp.cloudflare.com``)
    or the npx package name produces a far more reliable match.

    For servers that don't fit either pattern we fall back to the server key.
    """
    args = cfg.get("args", [])

    # mcp-remote case: first arg is the URL -- extract the host.
    for arg in args:
        if isinstance(arg, str) and (arg.startswith("https://") or arg.startswith("http://")):
            host = urlparse(arg).hostname
            if host:
                return host

    # npx package case: find the last non-flag arg that looks like a package name.
    for arg in reversed(args):
        if not isinstance(arg, str):
            continue
        if arg.startswith("@") or (not arg.startswith("-") and "/" in arg):
            return arg
        if not arg.startswith("-") and arg and arg not in ("-y",):
            return arg

    return name


@dataclass
class MCPServerInfo:
    """Snapshot of a single MCP server's health."""

    name: str
    command: str
    pid: int | None = None
    status: str = "unknown"  # running | stopped | crashed | unknown
    memory_mb: float = 0.0
    last_seen: str = ""


class MCPMonitor:
    """Observe MCP server processes and report their health."""

    # Filename used when emitting an EscalationEngine-readable state file.
    # Matches the ``<source>-state.json`` convention so
    # ``EscalationEngine.scan_service_states`` picks it up automatically.
    # Issue #1543.
    STATE_FILENAME = "mcp_monitor-state.json"

    def __init__(
        self,
        mcp_config_path: str | Path,
        state_dir: str | Path | None = None,
    ) -> None:
        self._config_path = Path(mcp_config_path)
        # Optional state directory for EscalationEngine tie-in (issue #1543).
        # When set, ``record_health_state()`` writes a state file shaped like
        # a scheduled-service state file so the existing escalation trigger
        # matrix (CASUAL@1, NUDGE@3, URGENT@5 consecutive failures) fires
        # without needing a parallel mechanism. None preserves legacy
        # behaviour for callers that haven't opted in.
        self._state_dir = Path(state_dir) if state_dir else None
        self._crash_history: dict[str, list[float]] = {}
        self._server_states: dict[str, MCPServerInfo] = {}
        self._ever_seen_running: set[str] = set()
        # Track when each server was last observed running (epoch seconds).
        self._last_seen_running: dict[str, float] = {}

    # ------------------------------------------------------------------
    # Config parsing
    # ------------------------------------------------------------------

    def load_expected_servers(self) -> list[str]:
        """Parse .mcp.json and return names of enabled servers.

        Servers listed under ``mcpServers`` are enabled.  Entries under
        keys prefixed with ``_`` (e.g. ``_mcpServers_disabled``) are
        treated as disabled and skipped.
        """
        try:
            data = json.loads(self._config_path.read_text())
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("Failed to read MCP config %s: %s", self._config_path, exc)
            return []

        servers: dict = data.get("mcpServers", {})
        return list(servers.keys())

    # ------------------------------------------------------------------
    # Health checks
    # ------------------------------------------------------------------

    async def check_server_health(self) -> dict[str, MCPServerInfo]:
        """Check all expected servers and return a name->info mapping."""
        try:
            data = json.loads(self._config_path.read_text())
        except (OSError, json.JSONDecodeError):
            return {}

        servers: dict = data.get("mcpServers", {})
        results: dict[str, MCPServerInfo] = {}

        for name, cfg in servers.items():
            info = await self._check_server(name, cfg)
            results[name] = info

        self._server_states = results
        return results

    async def _check_server(self, name: str, cfg: dict | str) -> MCPServerInfo:
        """Use ``pgrep -f`` to locate an MCP server process by its config pattern.

        The pgrep pattern is derived from the server's args rather than the
        bare server key, so mcp-remote entries (whose process command line
        contains the target URL) are matched reliably.
        """
        # Accept either a config dict (new call site) or a bare command string
        # (kept for backward compatibility with any external callers).
        if isinstance(cfg, dict):
            command = cfg.get("command", "")
            pattern = _derive_pgrep_pattern(name, cfg)
        else:
            command = cfg
            pattern = name

        info = MCPServerInfo(name=name, command=command)

        try:
            proc = await asyncio.create_subprocess_exec(
                "pgrep", "-f", pattern,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await proc.communicate()

            if proc.returncode == 0 and stdout.strip():
                # Take the first PID returned.
                pid = int(stdout.strip().split()[0])
                info.pid = pid
                info.status = "running"
                info.memory_mb = await self._get_process_memory(pid)
                info.last_seen = datetime.now(timezone.utc).isoformat()
                self._ever_seen_running.add(name)
                self._last_seen_running[name] = time.time()
            else:
                info.status = "stopped"
                # Only track as crash if:
                # (a) we've seen it running before, AND
                # (b) it was last seen within RECENT_RUN_WINDOW seconds.
                # On-demand MCPs (cloudflare, bumba-memory) that are
                # legitimately stopped for hours should not accumulate
                # crash entries on every health-check tick.
                if name in self._ever_seen_running:
                    last_seen = self._last_seen_running.get(name, 0)
                    if (time.time() - last_seen) < RECENT_RUN_WINDOW:
                        self._track_crash(name)
        except Exception as exc:
            logger.debug("Error checking server %s: %s", name, exc)
            info.status = "unknown"

        return info

    async def _get_process_memory(self, pid: int) -> float:
        """Return RSS in MB for *pid*, or 0.0 if the process is gone."""
        try:
            proc = await asyncio.create_subprocess_exec(
                "ps", "-o", "rss=", "-p", str(pid),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await proc.communicate()

            if proc.returncode == 0 and stdout.strip():
                rss_kb = int(stdout.strip())
                return round(rss_kb / 1024, 2)
        except Exception as exc:
            logger.debug("Error reading memory for PID %d: %s", pid, exc)

        return 0.0

    # ------------------------------------------------------------------
    # Status summary
    # ------------------------------------------------------------------

    def get_unhealthy_servers(self) -> list[str]:
        """Return names of servers currently in crash-loop state."""
        return [
            name
            for name in self._server_states
            if self._is_crash_loop(name)
        ]

    def get_status_summary(self) -> dict:
        """Return an aggregate summary suitable for a health endpoint."""
        total = len(self._server_states)
        running = sum(
            1 for s in self._server_states.values() if s.status == "running"
        )
        crashed = sum(
            1 for name in self._server_states
            if self._is_crash_loop(name)
        )
        stopped = total - running

        return {
            "total": total,
            "running": running,
            "stopped": stopped,
            "crash_loop": crashed,
        }

    # ------------------------------------------------------------------
    # Crash tracking
    # ------------------------------------------------------------------

    def _track_crash(self, name: str) -> None:
        """Record a crash timestamp for *name*."""
        now = time.time()
        history = self._crash_history.setdefault(name, [])
        history.append(now)

        # Prune entries older than the crash-loop window.
        cutoff = now - CRASH_LOOP_WINDOW
        self._crash_history[name] = [t for t in history if t >= cutoff]

    def _is_crash_loop(self, name: str) -> bool:
        """Return ``True`` if *name* has crashed more than the threshold
        within the configured time window."""
        now = time.time()
        cutoff = now - CRASH_LOOP_WINDOW
        recent = [t for t in self._crash_history.get(name, []) if t >= cutoff]
        return len(recent) > CRASH_LOOP_THRESHOLD

    # ------------------------------------------------------------------
    # EscalationEngine tie-in (issue #1543)
    # ------------------------------------------------------------------

    def record_health_state(self) -> None:
        """Emit an EscalationEngine-readable state file.

        Writes ``<state_dir>/mcp_monitor-state.json`` mirroring the shape
        scheduled services use (``services/base.py``). The escalation
        engine's ``scan_service_states`` reads every ``*-state.json`` in
        the directory and applies the consecutive-failure progression:
        ``consecutive_failures == 1`` → CASUAL, ``>= 3`` → NUDGE,
        ``>= 5`` → URGENT.

        A "failure" for the MCP monitor is one health-check tick where at
        least one configured server is in crash-loop state. On any tick
        with zero crash-looped servers, ``consecutive_failures`` resets
        to 0 (matching the success-resets-counter contract that
        ``EscalationEngine.check_de_escalation`` relies on).

        No-op when the monitor was constructed without a ``state_dir``.
        Best-effort: I/O errors are logged at WARNING and swallowed so
        the heartbeat loop is never broken by a state-write failure.
        """
        if self._state_dir is None:
            return

        try:
            self._state_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            logger.warning(
                "MCPMonitor state_dir unavailable (%s): %s",
                self._state_dir,
                exc,
            )
            return

        path = self._state_dir / self.STATE_FILENAME

        # Load prior state (counter persistence across ticks).
        prior: dict = {}
        if path.exists():
            try:
                prior = json.loads(path.read_text())
                if not isinstance(prior, dict):
                    prior = {}
            except (OSError, json.JSONDecodeError):
                prior = {}

        prev_failures = int(prior.get("consecutive_failures", 0) or 0)
        unhealthy = self.get_unhealthy_servers()
        now_iso = datetime.now(timezone.utc).isoformat()

        if unhealthy:
            consecutive = prev_failures + 1
            last_error = (
                f"MCP crash loop: {len(unhealthy)} server(s) — "
                f"{', '.join(sorted(unhealthy))}"
            )
            new_state = {
                "last_run": prior.get("last_run"),
                "last_error": last_error[:500],
                "last_error_time": now_iso,
                "consecutive_failures": consecutive,
                "total_runs": int(prior.get("total_runs", 0) or 0),
                "total_failures": int(prior.get("total_failures", 0) or 0) + 1,
                "total_skipped": int(prior.get("total_skipped", 0) or 0),
                "last_skipped_at": prior.get("last_skipped_at"),
                "last_skipped_reason": prior.get("last_skipped_reason"),
                "last_skipped_class": prior.get("last_skipped_class"),
                "last_duration_ms": 0,
                "unhealthy_servers": sorted(unhealthy),
            }
        else:
            new_state = {
                "last_run": now_iso,
                "last_error": None,
                "last_error_time": prior.get("last_error_time"),
                # Success resets the counter so EscalationEngine
                # de-escalation can clear the active alert.
                "consecutive_failures": 0,
                "total_runs": int(prior.get("total_runs", 0) or 0) + 1,
                "total_failures": int(prior.get("total_failures", 0) or 0),
                "total_skipped": int(prior.get("total_skipped", 0) or 0),
                "last_skipped_at": prior.get("last_skipped_at"),
                "last_skipped_reason": prior.get("last_skipped_reason"),
                "last_skipped_class": prior.get("last_skipped_class"),
                "last_duration_ms": 0,
                "unhealthy_servers": [],
            }

        # Atomic write — same pattern services/base.py uses to avoid
        # leaving a corrupt half-written state file if the process is
        # killed mid-write.
        try:
            fd, tmp_path = tempfile.mkstemp(dir=self._state_dir, suffix=".tmp")
            try:
                with os.fdopen(fd, "w") as f:
                    json.dump(new_state, f, indent=2)
                os.replace(tmp_path, path)
            except Exception:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
                raise
        except OSError as exc:
            logger.warning("MCPMonitor state write failed: %s", exc)
