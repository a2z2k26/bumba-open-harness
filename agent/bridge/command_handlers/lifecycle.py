"""Tier-1 lifecycle and health command handlers.

Verbs: ping, status (+ helpers _safe_collect_health / _safe_count /
_collect_mcp_status_block / _read_recent_failures / _legacy_session_block),
services, drift, determinism, health, uptime, queue, primer, reset, halt,
resume, cancel, restart, mcp, resources, diagnose, log, compact_status,
memory_writes, writes.

Mixed into `bridge.commands.CommandHandler` via multiple inheritance —
all methods rely on instance attributes (`self._db`, `self._queue`,
`self._app`, etc.) set up by the facade's `__init__`. No state lives
on this class itself; this is a behaviour-bundle.

Demote-split tracked under issue #1305 (umbrella). Pattern: PR #1687.
"""

from __future__ import annotations

import asyncio
import logging
import sys
import time
from pathlib import Path
from typing import TYPE_CHECKING

from ..memory_writes import tail as _memory_writes_tail

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


def _healthz_url(config: object | None) -> str:
    """Build the in-process ``/healthz`` URL from canonical API config.

    Sprint S1.1 (#2277) — the ``/health`` Discord command historically
    hardcoded a legacy port that drifted from the canonical ``[api]``
    section of ``bridge.toml`` (which listens on ``8200``). That drift
    caused operator health reports to mis-fire whenever the configured
    port was honoured by the actual server.

    The helper accepts an optional config-like object (anything that
    exposes ``api_host`` / ``api_port`` attributes — typically a live
    ``BridgeConfig``). Missing or falsy fields fall back to the
    canonical ``127.0.0.1:8200`` default so the call site stays
    crash-safe when the bridge boots before config is wired.
    """
    host = str(getattr(config, "api_host", None) or "127.0.0.1")
    port = int(getattr(config, "api_port", None) or 8200)
    return f"http://{host}:{port}/healthz"


class LifecycleMixin:
    """Lifecycle and health command handlers (Tier-1 essentials + misc system ops)."""

    async def _cmd_ping(self, chat_id: str, args: str) -> str:
        """Liveness check."""
        latency = int((time.monotonic() - self._start_time) * 1000) % 1000
        return f"pong (latency: {latency}ms)"

    async def _cmd_status(self, chat_id: str, args: str) -> str:
        """Report agent status (D2.2 #1187, D7.11 #1423).

        Default: late-night profile — phone-readable, ≤25 lines, sorted by
        11pm-operator priority (escalations > approvals > active > health > cost).

        ``--full``: original 14-component dashboard.

        D7.5 finding F-7 — what the operator wants on the phone at 11pm is:
        any escalations? what's pending approval? what's the agent doing?
        is it healthy? what did today cost? In that order, in one screen.
        """
        from bridge.status_render import format_status, format_status_compact

        # Issue #1540 — pull the last 5 routing decisions for the
        # "Recent Routing" section. Best-effort: any failure yields [] and
        # the renderer simply omits the block.
        try:
            from bridge.routing_history import get_history as _get_routing_history
            routing_recent = _get_routing_history().recent(5)
        except Exception:
            routing_recent = []

        # Sprint E.05 (#2012) — per-executor availability snapshot for the
        # ``Executors:`` block. Best-effort: if the helper raises (shouldn't,
        # it's a constant return today), we omit the block instead of failing
        # the whole /status response.
        try:
            from bridge.executors import availability_snapshot as _availability_snapshot
            executor_block = _availability_snapshot()
        except Exception:
            executor_block = None

        health = await self._safe_collect_health()

        # --- Async queue count (message_queue is async-only) ---
        msg_count: int | None = None
        try:
            q = self._queue
            if q is not None:
                qs = await q.get_queue_status()
                msg_count = int(qs.get("counts", {}).get("pending", 0))
        except Exception:
            msg_count = None

        queues = {
            "messages": msg_count,
            "self_edits": self._safe_count(
                lambda: len(self._self_edit.get_pending_edits())  # type: ignore[union-attr]
            ) if self._self_edit is not None else None,
            "wiki_staging": self._safe_count(
                lambda: len(self._app._wiki_repo.list_staging())  # type: ignore[union-attr]
            ) if self._app is not None and getattr(self._app, "_wiki_repo", None) else None,
            "hitl": self._safe_count(
                lambda: len(self._app._task_queue.list_pending())  # type: ignore[union-attr]
            ) if self._app is not None and getattr(self._app, "_task_queue", None) else None,
            "workorders": self._safe_count(
                lambda: self._app._workorder_store.count_in_flight()  # type: ignore[union-attr]
            ) if self._app is not None and getattr(self._app, "_workorder_store", None) else None,
        }
        failures = self._read_recent_failures(window_hours=24, cap=5)
        session = await self._session_status_block(chat_id)

        # Issue #1543 — gather MCP health summary, best-effort.
        # When the monitor isn't wired or hasn't yet completed a check,
        # the renderer simply omits the section.
        mcp_block = self._collect_mcp_status_block()

        # --full → existing dashboard
        if args.strip() == "--full":
            out = format_status(
                health, queues, failures, session,
                routing=routing_recent, mcp=mcp_block,
                executors=executor_block,
            )
            # Sprint D-R3 (#1933) — append per-executor circuit-breaker
            # state when dispatcher is wired. Best-effort; if dispatcher
            # is missing or get_circuit_breaker_states raises, the block
            # is simply omitted so /status --full keeps working.
            #
            # Sprint D-R5 (#1935) — same pattern adds the executor
            # activation-status block (ACTIVE/CONDITIONAL/STUB). Mirrors
            # docs/architecture/executor-roadmap.md so the operator can
            # see at a glance which executor lanes are routable.
            try:
                _dispatcher = (
                    getattr(self._app, "_dispatcher", None)
                    if self._app is not None
                    else None
                )
                if _dispatcher is not None:
                    _breakers = _dispatcher.get_circuit_breaker_states()
                    if _breakers:
                        _line = ", ".join(
                            f"{name}={state}"
                            for name, state in sorted(_breakers.items())
                        )
                        out += f"\n\n**Dispatcher circuit breakers:** {_line}"
                    # D-R5 — executor status block.
                    _statuses = _dispatcher.get_executor_statuses()
                    if _statuses:
                        _line = ", ".join(
                            f"{name}={status}"
                            for name, status in sorted(_statuses.items())
                        )
                        out += f"\n**Executor status:** {_line}"
            except Exception as _br_exc:
                logger.debug(
                    "/status --full: dispatcher breaker block omitted: %s",
                    _br_exc,
                )
            if len(out) > 1800:
                from bridge.formatting import split_message
                chunks = split_message(out)
                return chunks[0] + ("\n…(truncated, /status --full continues)" if len(chunks) > 1 else "")
            return out

        # Default → late-night compact profile.
        # Cost block is best-effort: if cost_tracker isn't wired or its
        # API differs from the expected shape, the renderer just omits
        # the line.
        cost_block: dict | None = None
        try:
            if self._cost_tracker is not None:
                today = getattr(
                    self._cost_tracker.daily_summary(), "total_cost_usd", None
                )
                weekly = getattr(
                    self._cost_tracker.weekly_summary(), "total_cost_usd", None
                )
                if isinstance(today, (int, float)) or isinstance(weekly, (int, float)):
                    cost_block = {"today_usd": today, "weekly_usd": weekly}
        except Exception:
            cost_block = None

        return format_status_compact(
            health, queues, failures, session,
            cost=cost_block,
            active_work=None,  # TODO: wire when active_sprint surface stabilises
            routing=routing_recent,
            mcp=mcp_block,
        )

    async def _safe_collect_health(self) -> dict:
        """Collect health data from HealthServer, fail-safe."""
        try:
            hs = None
            if self._app is not None:
                hs = getattr(self._app, "_health_server", None) or getattr(
                    self._app, "health_server", None
                )
            if hs is None:
                return {"status": "unknown", "components": {}}
            return await hs.collect_health()
        except Exception as e:
            logger.warning("/status: collect_health failed: %s", e)
            return {"status": "unknown", "components": {}}

    def _safe_count(self, fn) -> int | None:
        """Call fn(), coerce result to int, return None on any exception."""
        try:
            result = fn()
            return int(result)
        except Exception:
            return None

    def _collect_mcp_status_block(self) -> dict | None:
        """Best-effort MCP-health snapshot for /status (issue #1543).

        Returns None when the monitor isn't wired or the snapshot raises.
        Uses the monitor's *cached* server-states (the last
        ``check_server_health`` result the heartbeat loop wrote) so
        ``/status`` doesn't spawn its own pgrep wave per invocation.
        """
        monitor = self._mcp_monitor
        if monitor is None:
            return None

        try:
            summary = monitor.get_status_summary()
            states = getattr(monitor, "_server_states", {}) or {}

            servers_block: list[dict] = []
            for name in sorted(states):
                info = states[name]
                # info is an MCPServerInfo dataclass — read defensively.
                status = getattr(info, "status", "unknown")
                memory = getattr(info, "memory_mb", 0.0)
                servers_block.append({
                    "name": name,
                    "status": status,
                    "memory_mb": memory,
                })

            return {
                "total": int(summary.get("total", 0)),
                "running": int(summary.get("running", 0)),
                "crash_loop": int(summary.get("crash_loop", 0)),
                "servers": servers_block,
            }
        except Exception:
            return None

    def _read_recent_failures(self, window_hours: int = 24, cap: int = 5) -> list[str]:
        """Read recent [error]/[alert] lines from today's daily log."""
        import datetime

        try:
            now = datetime.datetime.now()
            data_dir = Path(self._db.db_path).parent
            log_path = data_dir / "logs" / now.strftime("%Y/%m/%Y-%m-%d.md")
            if not log_path.exists():
                return []
            lines = log_path.read_text().splitlines()
            failures = [ln for ln in lines if "[error]" in ln.lower() or "[alert]" in ln.lower()]
            return failures[-cap:]
        except Exception:
            return []

    async def _session_status_block(self, chat_id: str) -> dict:
        """Build the session subheading dict for status renderers."""
        try:
            context_status = None
            if self._session_mgr is not None and hasattr(
                self._session_mgr, "get_context_status"
            ):
                context_status = await self._session_mgr.get_context_status(chat_id)

            uptime = self._format_uptime()
            block = {
                "uptime": uptime,
                "messages": self._message_count,
                "halted": self._halted,
            }
            if context_status:
                block.update({
                    "active": True,
                    "session_id": context_status.get("session_id"),
                    "message_count": context_status.get("message_count", 0),
                    "max_messages": context_status.get("max_messages", 0),
                    "pressure": context_status.get("pressure", 0.0),
                })
            else:
                block["active"] = False
            return block
        except Exception:
            return self._legacy_session_block()

    def _legacy_session_block(self) -> dict:
        """Build the legacy status block if richer session lookup fails."""
        try:
            return {
                "uptime": self._format_uptime(),
                "messages": self._message_count,
                "halted": self._halted,
            }
        except Exception:
            return {}


    async def _cmd_services(self, chat_id: str, args: str) -> str:
        """Render service status (Z2-S0.1) or single-service detail (Z2-S2.4).

        Usage:
            /services                — aggregate table of all services
            /services <name>         — detail block for a single service

        Reads ``data/service_state/last_run.json`` written by the runner.
        """
        from bridge.services.result import render_service_detail, render_services_table

        data_dir = Path(self._db.db_path).parent
        name = args.strip().lower().replace("-", "_")
        if name:
            return render_service_detail(data_dir, name)
        return render_services_table(data_dir)


    async def _cmd_drift(self, chat_id: str, args: str) -> str:
        """Compute source↔runtime drift report on demand (issue #832).

        Compares the configured SOURCE_ROOT (`BUMBA_SOURCE_ROOT`, default
        `/opt/bumba-harness/agent`) with the production RUNTIME_ROOT. Returns
        a one-line summary; in dev environments where either root is missing
        the command short-circuits with an explanatory message rather than
        running a meaningless check.
        """
        from ..runtime_drift import RUNTIME_ROOT, SOURCE_ROOT, compute_drift_report

        if not (SOURCE_ROOT.exists() and RUNTIME_ROOT.exists()):
            return (
                "Drift check requires production runtime paths; not available "
                "in dev. (source missing or runtime missing)"
            )

        try:
            report = await asyncio.to_thread(
                compute_drift_report, SOURCE_ROOT, RUNTIME_ROOT
            )
        except Exception as exc:  # pragma: no cover — defensive
            return f"drift check failed: {exc}"

        return report.summary()


    async def _cmd_determinism(self, chat_id: str, args: str) -> str:
        """Render the Determinism Spectrum counter snapshot (Sprint #1115).

        Shows the deterministic / judged ratio plus per-module breakdown
        for the top-N most-invoked modules. The counters wrap
        ``bridge.dispatch_metrics``; modules increment them via the
        ``increment_module_counter`` / ``record_invocation`` helpers per
        the ADR at ``docs/architecture/determinism-spectrum.md``.
        """
        from ..dispatch_metrics import format_snapshot_for_discord, snapshot

        try:
            snap = snapshot()
        except Exception as exc:  # pragma: no cover — defensive
            return f"determinism snapshot failed: {exc}"

        return format_snapshot_for_discord(snap)

    async def _cmd_health(self, chat_id: str, args: str) -> str:
        """Display system health status from /healthz endpoint.

        Usage:
            /health          — compact view (≤20 lines, per-service emoji + staleness)
            /health verbose  — full detail including last_error, counters, duration
            /health -v       — same as verbose
        """
        import aiohttp
        from datetime import datetime, timezone

        verbose = args.strip().lower() in ("verbose", "-v", "--verbose")

        def _relative_time(iso: str | None) -> str:
            if not iso:
                return "never"
            try:
                dt = datetime.fromisoformat(iso)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                secs = int((datetime.now(timezone.utc) - dt).total_seconds())
                if secs < 60:
                    return f"{secs}s ago"
                if secs < 3600:
                    return f"{secs // 60}m ago"
                if secs < 86400:
                    return f"{secs // 3600}h ago"
                return f"{secs // 86400}d ago"
            except Exception:
                return "?"

        def _svc_emoji(svc: dict) -> str:
            if svc.get("stale"):
                return "\U0001f7e1"  # yellow — stale
            cf = svc.get("consecutive_failures", 0)
            if cf >= 3:
                return "\U0001f534"  # red — failing
            if cf > 0:
                return "\U0001f7e0"  # orange — degraded
            status = svc.get("last_status", "unknown")
            if status == "ok":
                return "\U0001f7e2"  # green — healthy
            return "\u26aa"  # grey — unknown

        # Sprint S1.1 (#2277) — derive the healthz endpoint from the live
        # BridgeConfig (canonical ``[api]`` section) instead of the legacy
        # 8199 hardcode. The live config rides on ``self._app._config``;
        # falling back to the canonical 8200 default keeps the command
        # crash-safe when the bridge is mid-boot.
        config = getattr(self._app, "_config", None) if self._app is not None else None
        health_url = _healthz_url(config)

        try:
            timeout = aiohttp.ClientTimeout(total=5)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(health_url) as resp:
                    data = await resp.json()

            overall_emoji = {
                "healthy": "\u2705",
                "degraded": "\u26a0\ufe0f",
                "unhealthy": "\u274c",
            }
            comp_emoji = {"up": "\U0001f7e2", "down": "\U0001f534", "degraded": "\U0001f7e1"}

            lines = [f"**System Health: {overall_emoji.get(data['status'], '?')} {data['status'].upper()}**"]
            uptime_s = data.get("uptime_seconds", 0)
            lines.append(f"Uptime: {uptime_s // 3600}h {(uptime_s % 3600) // 60}m")
            lines.append("")

            for name, comp in data.get("components", {}).items():
                if isinstance(comp, dict) and "status" in comp:
                    emoji = comp_emoji.get(comp["status"], "\u26aa")
                    detail = ""
                    if "latency_ms" in comp and comp["latency_ms"] is not None:
                        detail = f" ({comp['latency_ms']}ms)"
                    elif "size_mb" in comp:
                        detail = f" ({comp['size_mb']}MB)"
                    elif "expires_in_seconds" in comp:
                        hrs = comp["expires_in_seconds"] // 3600
                        detail = f" (expires in {hrs}h)"
                    lines.append(f"{emoji} **{name}**: {comp['status']}{detail}")
                    # Sprint 02.13 (#988) \u2014 render experiment loop in
                    # operator-friendly form. Compact view: status +
                    # last-iter age + pid; verbose adds fitness + iter id.
                    if name == "experiment_loop":
                        loop_status = comp.get("experiment_loop_status", "unknown")
                        age = comp.get("experiment_loop_last_iter_age_seconds")
                        pid = comp.get("experiment_loop_pid")
                        iter_id = comp.get("experiment_loop_last_iter_id")
                        fitness = comp.get("experiment_loop_fitness_value")
                        prefix = "[STALE] " if loop_status == "stale" else ""
                        if loop_status == "unknown":
                            lines.append("    Experiment loop: not detected")
                        else:
                            age_str = (
                                f"{int(age // 60)}m {int(age % 60)}s"
                                if age is not None and age >= 60
                                else (f"{int(age)}s" if age is not None else "?")
                            )
                            pid_str = f", pid {pid}" if pid is not None else ""
                            lines.append(
                                f"    {prefix}Status: {loop_status} (last iter {age_str} ago{pid_str})"
                            )
                            if iter_id and (verbose or loop_status == "stale"):
                                fitness_str = (
                                    f" fitness {fitness:.1f}s"
                                    if isinstance(fitness, (int, float))
                                    else ""
                                )
                                lines.append(
                                    f"    Last iter: {iter_id}{fitness_str}"
                                )
                elif isinstance(comp, dict):
                    # services sub-dict
                    for svc_name, svc in sorted(comp.items()):
                        if not isinstance(svc, dict):
                            continue
                        emoji = _svc_emoji(svc)
                        last_run = _relative_time(svc.get("last_run"))
                        cf = svc.get("consecutive_failures", 0)
                        status = svc.get("last_status", "unknown")
                        cf_tag = f" ⚠ {cf} fails" if cf > 0 else ""
                        stale_tag = " [STALE]" if svc.get("stale") else ""
                        lines.append(
                            f"  {emoji} **{svc_name}**: {status} · {last_run}{cf_tag}{stale_tag}"
                        )
                        if verbose:
                            if svc.get("last_error"):
                                lines.append(f"    error: {svc['last_error'][:120]}")
                            total_runs = svc.get("total_runs", 0)
                            total_failures = svc.get("total_failures", 0)
                            dur = svc.get("last_duration_ms", 0)
                            lines.append(
                                f"    runs={total_runs} failures={total_failures} last_dur={dur}ms"
                            )
                            if svc.get("last_skipped_reason"):
                                lines.append(f"    skipped: {svc['last_skipped_reason'][:80]}")

            return "\n".join(lines)
        except Exception as e:
            return f"\u274c Health check failed: {e}"

    async def _cmd_uptime(self, chat_id: str, args: str) -> str:
        """Show uptime and stats."""
        uptime = self._format_uptime()
        return (
            f"Uptime: {uptime}. "
            f"Messages processed: {self._message_count}. "
            f"Errors: {self._error_count}. "
            f"Rate limits: {self._rate_limit_count}."
        )

    async def _cmd_queue(self, chat_id: str, args: str) -> str:
        """Show pending messages."""
        status = await self._queue.get_queue_status()
        pending = status["pending"]
        if not pending:
            return "Queue: empty."

        lines = [f"Queue: {len(pending)} messages pending."]
        for i, msg in enumerate(pending):
            lines.append(f"  {i + 1}. '{msg['text'][:50]}...' ({msg['received_at']})")
        return "\n".join(lines)

    async def _cmd_primer(self, chat_id: str, args: str) -> str:
        """Inspect the latest session primer.json (#488).

        Usage:
          /primer         — show full primer JSON
          /primer summary — show just session_summary + age
        """
        try:
            from bridge.primer_writer import read_primer, get_primer_health
        except Exception as e:
            return f"Primer module unavailable: {e}"

        health = get_primer_health()
        primer = read_primer()

        if primer is None:
            return (
                "No primer.json has been written yet. "
                "It will be written on the next session expire or /reset."
            )

        age = health.get("primer_last_write_age_minutes")
        age_str = f"{age:.1f}min ago" if age is not None else "unknown age"

        mode = (args or "").strip().lower()
        if mode in ("summary", "short", "s"):
            return (
                f"**Primer** ({age_str}, trigger={primer.trigger_source}):\n"
                f"{primer.session_summary or '(no summary — degraded write)'}\n"
                f"\n_active projects: {len(primer.active_projects)}, "
                f"decisions: {len(primer.recent_decisions)}, "
                f"blockers: {len(primer.open_blockers)}, "
                f"tasks: {len(primer.pending_tasks)}_"
            )

        # Full JSON (truncate if huge for Discord 2000-char limit)
        body = primer.to_json()
        if len(body) > 1900:
            body = body[:1900] + "\n... (truncated, full at /opt/bumba-harness/data/primer.json)"
        return f"**Primer** ({age_str}):\n```json\n{body}\n```"

    async def _cmd_reset(self, chat_id: str, args: str) -> str:
        """Expire current session, cycle warm process, create new."""
        new_id = await self._session_mgr.handle_reset(chat_id)
        warm_status = ""
        if self._warm_claude:
            ok = await self._warm_claude.cycle()
            warm_status = " Warm process recycled." if ok else " Warm process recycle failed — falling back to one-shot."
        return f"Session reset. New session: {new_id[:8]}...{warm_status}"

    async def _cmd_halt(self, chat_id: str, args: str) -> str:
        """Stop processing, enter halted state."""
        self._halted = True
        if self._security is not None:
            await asyncio.to_thread(self._security.set_halt, "operator_halt")
        if self._claude_runner:
            await self._claude_runner.kill_current()
        return "Agent halted. Claude Code stopped. Send /resume to restart."

    async def _cmd_resume(self, chat_id: str, args: str) -> str:
        """Exit halted state (no args), or resume a checkpointed run.

        Two forms, disambiguated by the presence of an argument — the same
        single-verb pattern as ``/handoff``:

        - ``/resume`` (no args) — clear the halt flag and resume processing
          (legacy Tier-1 behaviour, preserved exactly).
        - ``/resume <run_id>`` — re-dispatch the checkpointed run named by
          ``run_id`` through ``DepartmentRegistry.route`` with
          ``resume_from=<run_id>`` (WS2.6 #2570). Delegates to
          ``DepartmentsMixin._resume_run``.
        """
        run_id = args.strip()
        if run_id:
            return await self._resume_run(chat_id, run_id)
        self._halted = False
        return "Agent resumed. Processing queue..."

    async def _cmd_cancel(self, chat_id: str, args: str) -> str:
        """Kill current Claude subprocess."""
        if self._claude_runner:
            killed = await self._claude_runner.kill_current()
            if killed:
                return "Current task cancelled. Moving to next queued message."
        return "No active task to cancel."

    async def _cmd_restart(self, chat_id: str, args: str) -> str:
        """Graceful bridge restart via shutdown event (launchd restarts)."""
        logger.info("Restart requested by operator")
        if self._shutdown_callback:
            async def _delayed_shutdown():
                await asyncio.sleep(2)
                self._shutdown_callback()
            asyncio.create_task(_delayed_shutdown())
            return "Restarting bridge (graceful shutdown)..."
        else:
            async def _delayed_exit():
                await asyncio.sleep(2)
                sys.exit(1)
            asyncio.create_task(_delayed_exit())
            return "Restarting bridge..."


    async def _cmd_mcp(self, chat_id: str, args: str) -> str:
        """Show MCP server health status."""
        if not self._mcp_monitor:
            return "MCP monitor not initialized."
        try:
            health = await self._mcp_monitor.check_server_health()
            if not health:
                return "No MCP servers found in config."
            summary = self._mcp_monitor.get_status_summary()
            lines = [
                f"**MCP Servers** — {summary['running']}/{summary['total']} running"
                + (f", {summary['crash_loop']} in crash loop" if summary.get('crash_loop') else "")
                + "\n"
            ]
            for name, info in sorted(health.items()):
                status_icon = {"running": "+", "stopped": "-", "unknown": "?"}.get(info.status, "?")
                mem = f" ({info.memory_mb:.1f}MB)" if info.memory_mb else ""
                lines.append(f"[{status_icon}] **{name}**: {info.status}{mem}")
            return "\n".join(lines)
        except Exception as e:
            return f"MCP error: {e}"

    # -- Resources --

    async def _cmd_resources(self, chat_id: str, args: str) -> str:
        """Show disk usage and log file sizes."""
        from ..resource_manager import check_disk_usage
        lines = ["**Resource Status**\n"]
        disk = check_disk_usage("/")
        bar_filled = int(disk["used_pct"] / 10)
        bar = "=" * bar_filled + "-" * (10 - bar_filled)
        warn = " WARNING" if disk["used_pct"] >= 90 else ""
        lines.append(
            f"**Disk** [{bar}] {disk['used_pct']:.1f}%{warn}\n"
            f"  {disk['used_gb']:.1f}GB used / {disk['total_gb']:.1f}GB total "
            f"({disk['free_gb']:.1f}GB free)"
        )
        log_dir = self._log_dir or Path("/opt/bumba-harness/logs")
        if log_dir.is_dir():
            lines.append("\n**Log Files:**")
            log_files = sorted(log_dir.glob("*.log"))
            if log_files:
                for lf in log_files:
                    try:
                        size_mb = lf.stat().st_size / 1024 / 1024
                        lines.append(f"  - {lf.name}: {size_mb:.1f}MB")
                    except OSError:
                        pass
            else:
                lines.append("  (no .log files found)")
        return "\n".join(lines)

    # -- Departments --


    async def _cmd_diagnose(self, chat_id: str, args: str) -> str:
        """Run diagnostic runbooks. Usage: /diagnose [service]"""
        if not self._runbook_engine:
            return "Runbook engine not initialized."
        runbooks = self._runbook_engine.runbooks
        if not runbooks:
            return "No runbooks loaded."

        target = args.strip().lower() if args.strip() else None
        if not target:
            lines = [f"**Runbooks** — {len(runbooks)} loaded\n"]
            for rb_id, rb in sorted(runbooks.items()):
                lines.append(f"- `{rb_id}` — {rb.get('name', rb_id)}")
            lines.append("\nUsage: `/diagnose <service>` to run a specific runbook")
            return "\n".join(lines)

        to_run = []
        for rb in runbooks.values():
            rb_id = rb.get("id", "").lower()
            if target in rb_id or target in rb_id.replace("-", " "):
                to_run.append(rb)

        if not to_run:
            ids = ", ".join(sorted(runbooks.keys()))
            return f"No runbook found matching `{target}`.\nAvailable: {ids}"

        results = []
        for rb in to_run[:3]:
            try:
                result = await self._runbook_engine.execute_runbook(rb)
                results.append(result.format_summary())
            except Exception as e:
                results.append(f"Runbook {rb.get('id', '?')} error: {e}")
        return "\n\n---\n\n".join(results)

    # -- Skill evolution --


    async def _cmd_log(self, chat_id: str, args: str) -> str:
        """Append a manual entry to today's daily log, or read recent entries.

        Usage:
            /log <entry text>        — append entry (general category)
            /log [category] <text>   — append with category tag
            /log today               — show today's log
            /log read                — show today's log (alias)

        Recognised categories: memory, event, error, decision, message,
        response, session, service, dream, alert, search, proactive
        """
        CATEGORIES = {
            "memory", "event", "error", "decision", "message",
            "response", "session", "service", "dream", "alert",
            "search", "proactive",
        }

        if not self._daily_log:
            return "Daily log writer not initialized."

        stripped = args.strip()

        # Read-only sub-commands
        if stripped.lower() in ("today", "read", ""):
            content = self._daily_log.read_today()
            if not content:
                return "No entries logged today yet."
            lines = [l for l in content.splitlines() if l.strip()]
            header = f"**Today's log ({len(lines)} entries)**"
            return header + "\n" + content.strip()

        # Optional leading [category] or bare category keyword
        category = "general"
        parts = stripped.split(None, 1)
        if parts and parts[0].lower() in CATEGORIES:
            category = parts[0].lower()
            stripped = parts[1] if len(parts) > 1 else ""

        if not stripped:
            return "Nothing to log — provide entry text after the category."

        self._daily_log.append(stripped, category=category)
        tag = f" [{category}]" if category != "general" else ""
        return f"Logged{tag}: {stripped}"

    async def _cmd_compact_status(self, chat_id: str, args: str) -> str:
        """Return the most-recent context-compaction event (D7.8 / #1420).

        Reads ``data/checkpoints/last_compaction.json`` written by
        ``compaction_checkpoint.capture_checkpoint``. Surfaces:
          - When the last compaction fired (age in minutes/hours)
          - Which session it belonged to
          - Pre-compaction message count + estimated token total
          - Active sprint context at fire time (when present)

        Returns a friendly "no compactions yet" if the file doesn't exist.
        """
        import json as _json
        from datetime import datetime, timezone

        # Resolve data_dir via the claude_runner's config (canonical source).
        # Falls through to the runtime default if anything is unwired.
        runner = self._claude_runner
        try:
            from bridge.paths import data_root
            data_dir = Path(getattr(getattr(runner, "config", None), "data_dir", str(data_root())))
        except Exception:
            from bridge.paths import data_root
            data_dir = data_root()
        last_path = data_dir / "checkpoints" / "last_compaction.json"

        if not last_path.exists():
            return (
                "No compaction events recorded yet. "
                "When the bridge auto-compacts at the configured pressure "
                "threshold, the event lands here."
            )

        try:
            payload = _json.loads(last_path.read_text(encoding="utf-8"))
        except Exception as exc:
            return f"Could not read {last_path}: {exc}"

        fired_at_raw = payload.get("fired_at_utc", "")
        try:
            fired_at = datetime.fromisoformat(fired_at_raw.replace("Z", "+00:00"))
            age_seconds = (datetime.now(timezone.utc) - fired_at).total_seconds()
            if age_seconds < 60:
                age_str = f"{int(age_seconds)}s ago"
            elif age_seconds < 3600:
                age_str = f"{int(age_seconds // 60)}m ago"
            elif age_seconds < 86400:
                age_str = f"{age_seconds / 3600:.1f}h ago"
            else:
                age_str = f"{age_seconds / 86400:.1f}d ago"
        except Exception:
            age_str = "unknown"

        lines = ["**Last compaction**"]
        lines.append(f"- Fired:    {fired_at_raw} ({age_str})")
        lines.append(f"- Session:  {payload.get('session_id', '?')[:12]}")
        lines.append(f"- Messages before: {payload.get('message_count_before', 0)}")
        lines.append(f"- Tokens before:   {payload.get('estimated_tokens_before', 0):,}")
        sprint = payload.get("active_sprint", "")
        if sprint:
            lines.append(f"- Active sprint:   {sprint}")
        reason = payload.get("last_handoff_reason", "")
        if reason:
            lines.append(f"- Reason:    {reason[:120]}")
        return "\n".join(lines)



    async def _cmd_memory_writes(self, chat_id: str, args: str) -> str:
        """`/memory_writes [N] [--subsystem foo]` — tail recent memory write receipts.

        Shows the last N receipts (default 20, max 200) across all instrumented
        memory subsystems. Use --subsystem to filter to one store.

        Subsystems: conversation, knowledge, temporal_knowledge,
                    bumba_memory_mcp, memory_file, z4_conversation_log
        """
        import shlex
        _VALID_SUBS = {
            "conversation", "knowledge", "temporal_knowledge",
            "bumba_memory_mcp", "memory_file", "z4_conversation_log",
        }
        n = 20
        sub: str | None = None
        try:
            tokens = shlex.split(args or "")
        except ValueError:
            return "Usage: /memory_writes [N] [--subsystem <name>]"

        i = 0
        while i < len(tokens):
            t = tokens[i]
            if t == "--subsystem" and i + 1 < len(tokens):
                sub = tokens[i + 1]
                if sub not in _VALID_SUBS:
                    return f"Unknown subsystem `{sub}`. Valid: {sorted(_VALID_SUBS)}"
                i += 2
            elif t.lstrip("-").isdigit() and not t.startswith("-"):
                requested = int(t)
                if requested > 200:
                    return "Cap is 200; showing 200."
                n = max(1, min(200, requested))
                i += 1
            else:
                return "Usage: /memory_writes [N] [--subsystem <name>]"

        receipts = _memory_writes_tail(n=n, subsystem=sub)
        if not receipts:
            label = f" (subsystem={sub})" if sub else ""
            return f"No memory write receipts{label}."

        header = f"Last {len(receipts)} memory writes" + (f" — {sub}" if sub else "") + ":"
        lines = [header]
        for r in receipts:
            lines.append(
                f"  {r.timestamp[:19]}Z [{r.subsystem}/{r.op}] {r.key} "
                f"({r.bytes}B, by {r.actor})"
            )
        result = "\n".join(lines)
        # Discord 2000-char limit — truncate with notice if needed
        if len(result) > 1900:
            result = result[:1897] + "..."
        return result

    async def _cmd_writes(self, chat_id: str, args: str) -> str:
        """Alias for /memory_writes."""
        return await self._cmd_memory_writes(chat_id, args)
