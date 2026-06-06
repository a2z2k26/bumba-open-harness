"""Cost, Zone 4 inspection, routing-feedback, and chief-session handlers.

Verbs: cost (+ _format_experiment_cost_report / _format_team_cost_report),
z4_cost, z4_metrics, z4_status, z3_status, routing, reflect,
chief_sessions (+ _format_chief_session_list / _format_chief_session_detail).

Mixed into `bridge.commands.CommandHandler` via multiple inheritance.

Demote-split tracked under issue #1305 (umbrella). Pattern: PR #1687.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


def _fmt_secs(seconds: int) -> str:
    """Format a non-negative integer second count as ``HhMmSs`` / ``MmSs`` / ``Ss``.

    zone4-warmth.D.02 (#2300) — used by ``/chief_sessions`` and
    ``/warmth_stats`` to render idle-age and warm-window-remaining in
    operator-friendly form. Negative inputs are clipped to zero so an
    EXPIRED window never renders as a negative duration.
    """
    if seconds < 0:
        seconds = 0
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}h{minutes:02d}m{secs:02d}s"
    if minutes:
        return f"{minutes}m{secs:02d}s"
    return f"{secs}s"


class CostAndZ4Mixin:
    """Cost, Z4 inspection, and chief-session command handlers."""

    async def _cmd_cost(self, chat_id: str, args: str) -> str:
        """Show cost breakdown by model tier.

        Subcommands:
            ``--experiments`` (or ``experiments``): list per-iteration spend
                (Sprint 02.09).
        """
        if not self._cost_tracker:
            return "Cost tracker not initialized."

        flag = (args or "").strip().lower().lstrip("-")
        if flag in ("experiments", "experiment", "exp"):
            return self._format_experiment_cost_report()
        if flag in ("by-team", "byteam", "team", "teams"):
            return self._format_team_cost_report()

        try:
            daily = self._cost_tracker.get_daily_summary()
            weekly = self._cost_tracker.get_weekly_summary()
            lines = ["**Cost Summary**\n"]
            lines.append(f"**Today** ({daily['date']}): ${daily['total_cost']:.4f} ({daily['request_count']} requests)")
            self._append_backend_breakdown(lines, daily.get("by_backend", {}))
            for m, d in daily.get("by_model", {}).items():
                lines.append(f"  • {m}: ${d['cost']:.4f} ({d['count']} req)")
            lines.append(f"\n**Last 7 days**: ${weekly['total_cost']:.4f} ({weekly['request_count']} requests)")
            self._append_backend_breakdown(lines, weekly.get("by_backend", {}))
            for m, d in weekly.get("by_model", {}).items():
                lines.append(f"  • {m}: ${d['cost']:.4f} ({d['count']} req)")
            return "\n".join(lines)
        except Exception as e:
            return f"Cost error: {e}"

    @staticmethod
    def _append_backend_breakdown(lines: list[str], by_backend: dict[str, dict]) -> None:
        """Codex-6 (#1840) — render the per-backend section under a window.

        Claude turns roll up to a dollar figure (Anthropic API is
        per-token billed). Codex turns are subscription-billed per the
        #1841 broadcast — we surface ``subscription-billed`` instead of
        a misleading ``$0.00`` even though ``estimated_cost`` is zero.
        Token counts are shown alongside in both cases.

        Output shape per backend (Discord-friendly markdown):
            • claude: $0.0123 (5 requests, 1,234 in / 567 out tokens)
            • codex: subscription-billed (3 turns, 456 in / 123 out tokens)

        No-op when ``by_backend`` is empty (e.g. no cost activity today)
        so callers don't have to special-case the empty window.
        """
        if not by_backend:
            return
        lines.append("Backend breakdown:")
        for name in sorted(by_backend):
            stats = by_backend[name]
            count = int(stats.get("count", 0))
            in_tok = int(stats.get("input_tokens", 0))
            out_tok = int(stats.get("output_tokens", 0))
            if name == "codex":
                # Subscription-billed (per the #1841 operator broadcast):
                # never surface a dollar figure for Codex — it would be
                # fake. ``turns`` reads more honestly than ``requests``
                # for the Codex CLI which runs one logical turn per
                # invocation.
                lines.append(
                    f"  • codex: subscription-billed "
                    f"({count} turns, {in_tok:,} in / {out_tok:,} out tokens)"
                )
            else:
                cost = float(stats.get("cost", 0.0))
                lines.append(
                    f"  • {name}: ${cost:.4f} "
                    f"({count} requests, {in_tok:,} in / {out_tok:,} out tokens)"
                )

    def _format_experiment_cost_report(self) -> str:
        """Render per-experiment cost attribution (Sprint 02.09).

        Pure-format helper — kept on the handler so tests can mock the
        cost tracker and exercise the command's output shape. Returns
        a Discord-friendly markdown block with one row per iteration.
        """
        try:
            iter_ids = self._cost_tracker.list_experiment_iters()
        except Exception as e:
            return f"Cost error: {e}"

        if not iter_ids:
            return "**Per-experiment Cost**\nNo experiment-attributed cost entries yet."

        lines = ["**Per-experiment Cost**"]
        total = 0.0
        for iid in iter_ids:
            try:
                summary = self._cost_tracker.get_experiment_summary(iid)
            except Exception as e:
                lines.append(f"  • {iid}: error ({e})")
                continue
            total += summary.total_usd
            models = ", ".join(
                f"{m}={d['count']}" for m, d in summary.model_breakdown.items()
            ) or "no calls"
            lines.append(
                f"  • `{iid}`: ${summary.total_usd:.4f} "
                f"({summary.call_count} calls; {models})"
            )
        lines.append(f"\n**Total**: ${total:.4f} across {len(iter_ids)} iteration(s)")
        return "\n".join(lines)

    def _format_team_cost_report(self) -> str:
        """Render per-team cost attribution (D2.5).

        Shows today's spend vs. configured daily limit per team, plus a
        totals/breach summary line. Teams with no entries today are omitted.
        """
        from datetime import datetime, timezone

        try:
            summary = self._cost_tracker.get_team_summary()
        except Exception as e:
            return f"Cost error: {e}"

        today = datetime.now(timezone.utc).date().isoformat()
        if not summary:
            return f"**Team Spend** (today, {today})\nNo team-attributed cost entries yet."

        lines = [f"**Team Spend** (today, {today})"]
        total = 0.0
        breaches = 0
        for team in sorted(summary):
            b = summary[team]
            total += b["cost"]
            if b["breach"]:
                breaches += 1
            if b["limit"] > 0:
                pct = 100.0 * b["cost"] / b["limit"]
                flag = " **[BREACH]**" if b["breach"] else ""
                lines.append(
                    f"  • `{team}`: ${b['cost']:.4f} / ${b['limit']:.2f} ({pct:.0f}%){flag}"
                )
            else:
                lines.append(f"  • `{team}`: ${b['cost']:.4f} (no cap configured)")
        lines.append(
            f"\n**Total**: ${total:.4f} across {len(summary)} team(s). "
            f"{breaches} breach(es)."
        )
        return "\n".join(lines)

    # -- Zone 4 cost attribution --

    async def _cmd_z4_cost(self, chat_id: str, args: str) -> str:
        """Show Zone 4 department cost attribution for today."""
        if not self._cost_attributor:
            return "Zone 4 cost attributor not initialized (feature flag off or ToolTracker unavailable)."
        try:
            from bridge.observability.metrics_aggregator import MetricsAggregator
            from datetime import date

            today = date.today().isoformat()

            # Use MetricsAggregator for daily cost if available, else scan sessions
            aggregator = MetricsAggregator(
                tracker=self._cost_attributor._tracker,
                sessions_dir=self._cost_attributor._sessions_dir,
            )
            daily_entries = aggregator.daily_cost(start_date=today, end_date=today)

            if not daily_entries:
                return f"**Zone 4 Cost** ({today})\nNo department sessions recorded today."

            entry = daily_entries[0]
            lines = [
                f"**Zone 4 Cost** ({today})",
                f"Total: ${entry.total_usd:.4f} ({entry.session_count} sessions, {entry.total_calls} tool calls)",
            ]

            # Top departments by cost via agent utilization
            utils = aggregator.agent_utilization()
            if utils:
                lines.append("\n**Top agents by cost:**")
                for u in utils[:5]:
                    lines.append(
                        f"  • {u.agent_name}: ${u.total_usd:.4f} "
                        f"({u.total_calls} calls, {u.session_count} sessions)"
                    )

            return "\n".join(lines)
        except Exception as e:
            return f"Zone 4 cost error: {e}"

    # -- Zone 4 metrics surfacing --

    async def _cmd_z4_metrics(self, chat_id: str, args: str) -> str:
        """Show Zone 4 per-department breakdown + 7-day trend."""
        if not self._metrics_aggregator:
            return "Zone 4 metrics aggregator not initialized (feature flag off or ToolTracker unavailable)."
        try:
            from datetime import date, timedelta

            today = date.today()
            week_ago = today - timedelta(days=6)

            # 7-day daily trend
            daily_entries = self._metrics_aggregator.daily_cost(
                start_date=week_ago.isoformat(),
                end_date=today.isoformat(),
            )

            lines = ["**Zone 4 Metrics — 7-Day Trend**"]

            if not daily_entries:
                lines.append("No department sessions in the last 7 days.")
            else:
                total_usd = sum(e.total_usd for e in daily_entries)
                total_sessions = sum(e.session_count for e in daily_entries)
                total_calls = sum(e.total_calls for e in daily_entries)
                lines.append(
                    f"7-day total: ${total_usd:.4f} "
                    f"({total_sessions} sessions, {total_calls} tool calls)"
                )
                lines.append("")
                for entry in daily_entries:
                    lines.append(
                        f"  {entry.date}: ${entry.total_usd:.4f} "
                        f"({entry.session_count} sess, {entry.total_calls} calls)"
                    )

            # Per-agent breakdown
            utils = self._metrics_aggregator.agent_utilization()
            if utils:
                lines.append("")
                lines.append("**Per-Agent Breakdown**")
                for u in utils[:10]:
                    lines.append(
                        f"  • {u.agent_name}: ${u.total_usd:.4f} "
                        f"({u.total_calls} calls, {u.session_count} sessions"
                        f"{f', {u.blocked_calls} blocked' if u.blocked_calls else ''})"
                    )

            return "\n".join(lines)
        except Exception as e:
            return f"Zone 4 metrics error: {e}"

    # -- Zone 4 status --

    async def _cmd_z4_status(self, chat_id: str, args: str) -> str:
        """Show active Zone 4 departments, recent run counts, and circuit states.

        Reads from:
        - DepartmentRegistry for registered departments and configs
        - CircuitBreakerRegistry for circuit state per department
        - MetricsAggregator for today's cost per department (if available)
        - CostTracker for daily budget summary (if available)
        """
        if self._departments is None:
            return "Zone 4 departments not wired."
        try:
            from datetime import date

            names = self._departments.department_names()
            if not names:
                return "No departments registered."

            today = date.today().isoformat()

            # Gather per-dept cost data if metrics_aggregator is available
            dept_cost: dict[str, float] = {}
            dept_sessions: dict[str, int] = {}
            if self._metrics_aggregator is not None:
                try:
                    utils = self._metrics_aggregator.agent_utilization()
                    for u in utils:
                        # agent_name format is typically "<dept>-<role>" — map by prefix
                        for dept in names:
                            if u.agent_name.startswith(dept):
                                dept_cost[dept] = dept_cost.get(dept, 0.0) + u.total_usd
                                dept_sessions[dept] = dept_sessions.get(dept, 0) + u.session_count
                except Exception:  # noqa: BLE001
                    pass

            # Gather budget info from cost_tracker for daily total
            daily_total: float | None = None
            daily_limit: float | None = None
            if self._cost_tracker is not None:
                try:
                    summary = self._cost_tracker.daily_summary()
                    daily_total = summary.get("total_usd", None)
                    daily_limit = summary.get("daily_limit_usd", None)
                except Exception:  # noqa: BLE001
                    pass

            sep = "\u2500" * 45
            lines = ["**Zone 4 Status**", sep]

            for name in names:
                circuit_state = "closed"
                if self._circuit_registry is not None:
                    circuit_state = self._circuit_registry.get(name).state.value

                cost_str = f"${dept_cost.get(name, 0.0):.2f}"
                sessions = dept_sessions.get(name, 0)
                runs_str = f"runs={sessions}"

                lines.append(
                    f"{name:<12} {runs_str:<10} cost={cost_str:<8} [{circuit_state}]"
                )

            lines.append(sep)
            if daily_total is not None and daily_limit is not None:
                lines.append(f"Daily total: ${daily_total:.2f} of ${daily_limit:.2f}")
            elif daily_total is not None:
                lines.append(f"Daily total: ${daily_total:.2f}")
            else:
                lines.append(f"Today: {today} (cost data unavailable)")

            return "\n".join(lines)
        except Exception as e:
            return f"Zone 4 status error: {e}"

    async def _cmd_z3_status(self, chat_id: str, args: str) -> str:
        """Show Z3 dispatcher wiring, per-env circuit breaker states, and soak log path."""
        sep = "─" * 45
        lines = ["**Z3 Dispatcher Status**", sep]

        # Flag state
        dispatcher = self._dispatcher
        if dispatcher is None:
            lines.append("Dispatcher: not wired (dispatcher_enabled=false)")
            lines.append("All traffic is routed via direct claude_runner.invoke")
            lines.append(sep)
            lines.append("Soak log: `data/z3-soak.jsonl`")
            return "\n".join(lines)

        lines.append("Dispatcher: wired")

        # Circuit breaker states
        breakers: dict = getattr(dispatcher, "_breakers", {})
        if breakers:
            lines.append("")
            lines.append("**Circuit Breakers:**")
            for env_val, breaker in breakers.items():
                state = getattr(breaker, "state", None)
                state_label = state.value if state is not None else "unknown"
                available = getattr(breaker, "is_available", True)
                icon = "CLOSED" if available else "OPEN"
                failures = getattr(breaker, "failure_count", 0)
                lines.append(f"  {env_val:<12} [{icon}] failures={failures} state={state_label}")
        else:
            lines.append("  (no circuit breaker data)")

        # Dispatch counters from Z3Counters
        try:
            from bridge.z3_metrics import Z3Counters, Z3CounterNames
            fallthrough_snap = Z3Counters.snapshot(Z3CounterNames.DISPATCH_FALLTHROUGH)
            if fallthrough_snap:
                lines.append("")
                lines.append("**Fallthrough reasons (this session):**")
                for label, count in sorted(fallthrough_snap.items()):
                    lines.append(f"  {label}: {count}")
        except Exception:  # noqa: BLE001
            pass

        # Sprint S3.2 (Backend Operability, #2283) — per-executor activation
        # + routability. Mirrors the /api/executors/status REST surface so
        # operators reading /z3_status see at a glance which lanes will
        # accept a WorkOrder right now (active / active_low_traffic /
        # conditional_active) vs which will reject it (stub /
        # conditional_unwired). The flag is the same predicate the
        # dispatcher uses at ``validate_for_dispatch`` (S2.3 #2280) — one
        # source of truth, one rendering.
        try:
            payload = dispatcher.get_executor_status_payload()
            if payload:
                lines.append("")
                lines.append("**Executor status:**")
                for name, info in sorted(payload.items()):
                    flag = "routable" if info.get("routable") else "blocked"
                    lines.append(
                        f"  {name:<12} status={info.get('status')!s:<22} "
                        f"[{flag}]"
                    )
        except Exception:  # noqa: BLE001
            pass

        lines.append(sep)
        lines.append("Soak log: `data/z3-soak.jsonl`")
        return "\n".join(lines)

    # -- Routing feedback --


    async def _cmd_routing(self, chat_id: str, args: str) -> str:
        """Show tool/model routing health and active escalations."""
        if not self._routing_feedback:
            return "Routing feedback engine not initialized."
        try:
            return self._routing_feedback.format_routing_report()
        except Exception as e:
            return f"Routing error: {e}"

    # -- Reflection --

    async def _cmd_reflect(self, chat_id: str, args: str) -> str:
        """Show recent weekly reflections."""
        if not self._reflection_store:
            return "Reflection store not initialized."
        try:
            recent = self._reflection_store.get_recent(limit=3)
            if not recent:
                return "No reflections recorded yet. Reflections are generated during weekly review."
            lines = []
            for r in recent:
                lines.append(self._reflection_store.format_reflection(r))
            return "\n---\n".join(lines)
        except Exception as e:
            return f"Reflection error: {e}"



    # -- Recall (Sprint D2.1 #1186) --


    async def _cmd_chief_sessions(self, chat_id: str, args: str) -> str:
        """List active chief sessions or inspect one by id (Z4-S13 #1388).

        Usage:
            /chief_sessions              — list active sessions (alias for `list`)
            /chief_sessions list         — list active sessions (excludes SHUTDOWN)
            /chief_sessions <sid>        — show full detail for one session
            /chief_sessions help         — usage hint

        The active list shows up to 10 most-recent sessions; when more
        exist, a tail line names how many were truncated. The detail
        view emits all timestamps, run_count, cost, and error (if FAILED).

        Phone-readable per the D7.11 late-night profile — no row wider
        than ~50 chars; session_id is truncated to 16 chars in the list
        view (full id surfaces in the detail view).
        """
        if self._chief_session_store is None:
            return "ChiefSessionStore not initialized."

        sub = args.strip()

        # ---- help ----
        if sub.lower() == "help":
            return (
                "Usage: /chief_sessions [list|<sid>|help]\n"
                "  /chief_sessions             — list active sessions\n"
                "  /chief_sessions list        — list active sessions\n"
                "  /chief_sessions <sid>       — show one session in detail\n"
                "  /chief_sessions help        — this message"
            )

        # ---- detail (a token that isn't `list`/`help`/empty is treated as a sid) ----
        if sub and sub.lower() != "list":
            return await self._format_chief_session_detail(sub)

        # ---- list (default) ----
        return await self._format_chief_session_list()

    async def _format_chief_session_list(self) -> str:
        """Render the active-sessions list. Excludes SHUTDOWN; cap to 10.

        Active = every state except SHUTDOWN (DONE/FAILED/TIMED_OUT are
        retained on the list until they archive to SHUTDOWN — the operator can
        still see why a session failed without a manual sid lookup).
        """
        from datetime import datetime, timezone

        from bridge.chief_session import ChiefSessionState

        store = self._chief_session_store
        active_states = [s for s in ChiefSessionState if s != ChiefSessionState.SHUTDOWN]
        sessions = []
        for state in active_states:
            try:
                sessions.extend(await store.list_by_state(state))
            except Exception as exc:  # noqa: BLE001
                logger.warning("chief_sessions list_by_state(%s) failed: %s", state, exc)

        if not sessions:
            return "**Active Chief Sessions** — none."

        # Newest first (most recent created_at_utc)
        sessions.sort(key=lambda s: s.created_at_utc, reverse=True)

        total = len(sessions)
        cap = 10
        truncated = max(0, total - cap)
        shown = sessions[:cap]

        # zone4-warmth.D.02 (#2300) — resolve per-team idle timeout for the
        # warm-window-remaining display on AWAITING_EVALUATION rows. Failure
        # to import or to read config falls through to None and the warm-age
        # line is suppressed rather than crashing the formatter.
        try:
            from bridge.background_loops import _resolve_team_idle_timeout
        except Exception:  # pragma: no cover — defensive only
            _resolve_team_idle_timeout = None  # type: ignore[assignment]

        app = getattr(self, "_app", None)
        bridge_config = getattr(app, "_config", None) if app is not None else None
        department_registry = getattr(app, "_departments", None) if app is not None else None
        global_timeout = float(getattr(
            bridge_config, "chief_dispatcher_idle_timeout_seconds", 14400.0
        )) if bridge_config is not None else 14400.0

        now = datetime.now(timezone.utc)
        lines = [f"**Active Chief Sessions** ({total})", "```"]
        for s in shown:
            age_seconds = int((now - s.created_at_utc).total_seconds())
            sid_short = s.session_id[:16]
            wo_short = (s.work_order_id or "-")[:12]
            # Two-line-per-session shape keeps every line ≤ 50 chars on a
            # phone (D7.11 late-night profile). Line 1 carries the
            # actionable id + state; line 2 carries provenance + age.
            lines.append(f"{sid_short}  {s.state.value}")
            lines.append(f"  {s.department[:14]:<14} wo={wo_short} age={age_seconds}s")
            # zone4-warmth.D.02 (#2300) — extra line for warm sessions
            # carrying idle-clock + window-remaining (or EXPIRED hint when
            # the reap is overdue). Only emitted for AWAITING_EVALUATION
            # rows; other states keep the two-line shape unchanged.
            if (
                s.state == ChiefSessionState.AWAITING_EVALUATION
                and s.idle_since_utc is not None
                and _resolve_team_idle_timeout is not None
            ):
                idle_secs = int((now - s.idle_since_utc).total_seconds())
                team_timeout = _resolve_team_idle_timeout(
                    s.department, global_timeout, department_registry
                )
                remaining = team_timeout - idle_secs
                idle_str = _fmt_secs(idle_secs)
                if remaining <= 0:
                    lines.append(
                        f"  idle={idle_str} (EXPIRED — reap pending)"
                    )
                else:
                    lines.append(
                        f"  idle={idle_str} ({_fmt_secs(int(remaining))} left)"
                    )
        lines.append("```")
        if truncated:
            lines.append(f"_+{truncated} more (use `/chief_sessions <sid>` to inspect)_")
        return "\n".join(lines)

    async def _format_chief_session_detail(self, session_id: str) -> str:
        """Render the detail block for one session by id."""
        from bridge.chief_session_store import ChiefSessionNotFoundError

        store = self._chief_session_store
        try:
            session = await store.get(session_id)
        except ChiefSessionNotFoundError:
            return f"Chief session not found: `{session_id}`"
        except Exception as exc:  # noqa: BLE001
            return f"Error reading chief session `{session_id}`: {exc}"

        def _ts(value) -> str:
            return value.isoformat() if value is not None else "—"

        lines = [
            f"**Chief Session** `{session.session_id}`",
            "```",
            f"work_order_id      {session.work_order_id}",
            f"department         {session.department}",
            f"chief_name         {session.chief_name}",
            f"state              {session.state.value}",
            f"run_count          {session.run_count}",
            f"cost_usd           ${session.cost_usd:.4f}",
            f"created_at_utc     {_ts(session.created_at_utc)}",
            f"warmed_at_utc      {_ts(session.warmed_at_utc)}",
            f"execution_started  {_ts(session.execution_started_at_utc)}",
            f"idle_since_utc     {_ts(session.idle_since_utc)}",
            f"completed_at_utc   {_ts(session.completed_at_utc)}",
        ]
        if session.error:
            lines.append(f"error              {session.error}")
        lines.append("```")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # zone4-warmth.D.02 (#2300) — warm-session population summary command
    # ------------------------------------------------------------------

    async def _cmd_warmth_stats(self, chat_id: str, args: str) -> str:
        """Render the warm-session population stats (Tier-3 power-user).

        Mirrors ``GET /api/chief_sessions/warmth_stats`` — same six fields,
        formatted for phone-readable Discord output. The handler walks the
        store and the EventBus directly rather than HTTP-looping back through
        the API server so it works even when the bridge's own REST surface
        is unreachable from the daemon process.
        """
        from datetime import datetime, timedelta, timezone

        from bridge.chief_session import ChiefSessionState

        if self._chief_session_store is None:
            return "ChiefSessionStore not initialized."

        # ---- population walk ----
        store = self._chief_session_store
        sessions: list = []
        for state in ChiefSessionState:
            if state == ChiefSessionState.SHUTDOWN:
                continue
            try:
                sessions.extend(await store.list_by_state(state))
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "warmth_stats list_by_state(%s) failed: %s", state, exc
                )

        from collections import Counter
        by_state = Counter(s.state.value for s in sessions)
        warm = [
            s for s in sessions
            if s.state == ChiefSessionState.AWAITING_EVALUATION
        ]
        now = datetime.now(timezone.utc)
        ages = [
            (now - s.idle_since_utc).total_seconds()
            for s in warm
            if s.idle_since_utc is not None
        ]
        avg_age = sum(ages) / len(ages) if ages else 0.0
        max_age = max(ages) if ages else 0.0

        # ---- event replay (best-effort) ----
        reused = 0
        routed = 0
        event_bus = (
            getattr(self._autonomy, "event_bus", None)
            if self._autonomy is not None
            else None
        )
        if event_bus is not None:
            try:
                cutoff_iso = (now - timedelta(hours=24)).isoformat()
                reused = len(event_bus.replay(
                    event_type="chief_dispatcher.warmth_reused",
                    since_timestamp=cutoff_iso,
                ))
                routed = len(event_bus.replay(
                    event_type="chief_dispatcher.routed",
                    since_timestamp=cutoff_iso,
                ))
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "warmth_stats event replay failed: %s", exc
                )

        total_dispatches = reused + routed
        reuse_rate = (
            (reused / total_dispatches) if total_dispatches > 0 else 0.0
        )

        # ---- render ----
        by_state_line = " ".join(
            f"{k}={v}" for k, v in sorted(by_state.items())
        ) or "—"
        avg_str = _fmt_secs(int(avg_age))
        max_str = _fmt_secs(int(max_age))

        return (
            "**Zone 4 Warmth Stats** (last 24h)\n"
            f"Warm sessions: {len(warm)} "
            f"(avg age {avg_str}; oldest {max_str})\n"
            f"Reuse rate: {reuse_rate:.1%} "
            f"({reused} reused / {routed} cold)\n"
            f"By state: {by_state_line}"
        )

