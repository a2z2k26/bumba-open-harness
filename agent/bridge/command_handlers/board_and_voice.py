"""Board of Directors, voice, and Z4 governance-surface command handlers.

Verbs: voice, tts, board (+ _board_help_text / _board_status_text /
_board_toggle_flag / _board_set_cap / _board_legacy helpers), goals,
tasks, trust, escalation, events, digest, proposals.

Mixed into `bridge.commands.CommandHandler` via multiple inheritance.

Demote-split tracked under issue #1305 (umbrella). Pattern: PR #1687.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


class BoardAndVoiceMixin:
    """Board, voice, and Z4 governance-surface command handlers."""

    async def _cmd_voice(self, chat_id: str, args: str) -> str:
        """VAPI voice system operator commands (D1.7c).

        Subcommands:
            /voice              — show status (enabled/disabled, configured, squad info)
            /voice on           — show activation instructions or current state
            /voice call <phone> — trigger outbound call to <phone> via VAPI
            /voice off          — guidance to disable via bridge.toml
        """
        app = self._app
        stripped = args.strip()
        sub = stripped.split()[0].lower() if stripped else ""

        # Determine whether voice is wired at all
        config = getattr(app, "_config", None)
        voice_enabled: bool = bool(getattr(config, "voice_enabled", False)) if config else False
        vapi = getattr(app, "_vapi", None)
        is_configured: bool = bool(getattr(vapi, "is_configured", False)) if vapi else False

        if sub == "off":
            return (
                "voice_enabled is set in bridge.toml — restart bridge after editing "
                "config to disable."
            )

        if sub == "on":
            if not voice_enabled:
                return "Enable voice_enabled in bridge.toml first."
            if is_configured:
                squad = getattr(app, "_vapi_squad", None)
                squad_id = squad.get("squad_id", "unknown") if squad else "not yet provisioned"
                return f"Voice is active. Squad provisioned: {squad_id}"
            return "voice_enabled=true but vapi_api_key missing from .secrets"

        if sub == "call":
            # /voice call <phone>
            parts = stripped.split(maxsplit=1)
            phone = parts[1].strip() if len(parts) > 1 else ""
            if not phone:
                return "Usage: /voice call <phone> (E.164 format, e.g. +15551234567)"
            if not voice_enabled:
                return "Voice is disabled. Enable voice_enabled in bridge.toml first."
            if not is_configured:
                return "voice_enabled=true but vapi_api_key missing from .secrets"
            try:
                call_id = await vapi.trigger_outbound_call(phone, "Operator-initiated call")
                return f"Outbound call triggered. Call ID: {call_id}"
            except Exception as exc:  # noqa: BLE001
                return f"Outbound call failed: {exc}"

        # Default: status
        if not voice_enabled:
            return "Voice: disabled (voice_enabled = false in bridge.toml)"
        if not is_configured:
            return "Voice: enabled but not configured (vapi_api_key missing from .secrets)"
        squad = getattr(app, "_vapi_squad", None)
        if squad:
            return (
                f"Voice: active — squad_id={squad.get('squad_id', '?')} "
                f"receptionist_id={squad.get('receptionist_id', '?')} "
                f"assistants={squad.get('assistant_count', '?')}"
            )
        return "Voice: active — squad not yet provisioned (startup pending?)"

    async def _cmd_tts(self, chat_id: str, args: str) -> str:
        """TTS operator commands (D1.7c).

        Subcommands:
            /tts <text>   — acknowledge synthesis (playback is post-1.0)
            /tts status   — show TTS engine configuration
        """
        app = self._app
        stripped = args.strip()

        if stripped.lower() == "status":
            config = getattr(app, "_config", None)
            voice_enabled: bool = bool(getattr(config, "voice_enabled", False)) if config else False
            tts_url = getattr(config, "voice_tts_url", "not configured") if config else "not configured"
            tts_voice = getattr(config, "voice_tts_voice", "not configured") if config else "not configured"
            tts = getattr(app, "_tts", None)
            tts_enabled = getattr(tts, "enabled", False) if tts else False
            status_str = "enabled" if (voice_enabled and tts_enabled) else "disabled"
            return f"TTS engine: {status_str} — url={tts_url} voice={tts_voice}"

        if not stripped:
            return "Usage: /tts <text> | /tts status"

        preview = stripped[:50]
        return (
            f"TTS synthesis queued: '{preview}' — voice playback requires Discord "
            "voice channel (post-1.0)"
        )

    async def _cmd_board(self, chat_id: str, args: str) -> str:
        """Invoke the Board of Directors or manage Board v2 runtime flags.

        Subcommands (Sprint 04.06 / spec ref-audit-04-06, issue #1007):
            /board                       — usage hint (no question)
            /board <question>            — legacy Board-of-Directors reasoning
                                           (preserved byte-for-byte)
            /board legacy <question>     — explicit legacy invocation
            /board status                — show flag state + registered caps
            /board anonymize on|off      — flip board_v2_enabled (in-process)
            /board cross-vendor on|off   — flip board_cross_vendor_enabled
            /board cap <feature> <usd>   — register/update per-feature daily cap
            /board help                  — print this help text

        The flag flips here are runtime-only (in-process). Restart resets
        flags to whatever bridge.toml + env-var loading produced. Per-feature
        caps registered via ``/board cap`` likewise live only on the
        ``CostTracker`` instance (Sprint 04.04 did not wire persistence).
        """
        stripped = args.strip()
        if not stripped:
            return self._board_help_text()

        # First token is the subcommand selector. Anything not in our known
        # set falls through to the legacy free-form question path so existing
        # ``/board <question>`` invocations stay byte-equivalent.
        first, _, rest = stripped.partition(" ")
        sub = first.lower()
        rest = rest.strip()

        if sub == "help":
            return self._board_help_text()
        if sub == "status":
            return self._board_status_text()
        if sub == "anonymize":
            return self._board_toggle_flag(
                "board_v2_enabled", rest, label="anonymize"
            )
        if sub in ("cross-vendor", "cross_vendor", "crossvendor"):
            return self._board_toggle_flag(
                "board_cross_vendor_enabled", rest, label="cross-vendor"
            )
        if sub == "cap":
            return self._board_set_cap(rest)
        if sub == "legacy":
            # Explicit legacy passthrough — strip the "legacy" token and
            # fall through to the unchanged reasoning path below.
            stripped = rest
            if not stripped:
                return "Usage: /board legacy <question for the board>"

        return await self._board_legacy(chat_id, stripped)

    def _board_help_text(self) -> str:
        """Help text for /board subcommands."""
        return (
            "**/board** — Board of Directors + v2 runtime controls\n"
            "Usage:\n"
            "  /board <question>           — convoke the board on a question\n"
            "  /board status               — show v2 flags + registered caps\n"
            "  /board anonymize on|off     — toggle anonymized A/B/C labels\n"
            "  /board cross-vendor on|off  — toggle OpenRouter adapter use\n"
            "  /board cap <feature> <usd>  — set per-feature daily cap (USD)\n"
            "  /board help                 — show this message\n"
            "\n"
            "Flag flips and cap registrations are in-process only — they "
            "do not persist across bridge restart."
        )

    def _board_status_text(self) -> str:
        """Render current Board v2 flag state and registered feature caps."""
        cfg = getattr(self._app, "config", None) if self._app is not None else None

        def _flag(name: str) -> str:
            val = getattr(cfg, name, None) if cfg is not None else None
            if val is True:
                return "ON"
            if val is False:
                return "OFF"
            return "?"

        lines = [
            "**Board v2 status**",
            f"  anonymize (board_v2_enabled): {_flag('board_v2_enabled')}",
            f"  cross-vendor (board_cross_vendor_enabled): {_flag('board_cross_vendor_enabled')}",
            f"  feature-caps gate (feature_cost_caps_enabled): {_flag('feature_cost_caps_enabled')}",
        ]

        # Registered caps live on the CostTracker; access defensively so
        # tests with a mocked tracker still get a clean string.
        caps: dict[str, float] | None = None
        tracker = self._cost_tracker
        if tracker is not None:
            raw = getattr(tracker, "_feature_caps", None)
            if isinstance(raw, dict):
                caps = {str(k): float(v) for k, v in raw.items()}

        if caps:
            lines.append("**Registered feature caps:**")
            for feature in sorted(caps):
                lines.append(f"  {feature}: ${caps[feature]:.2f}/day")
        else:
            lines.append("**Registered feature caps:** (none)")
        lines.append("")
        lines.append("(Runtime-only — restart resets to bridge.toml defaults.)")
        lines.append("")
        lines.append(
            "**Effective until next daemon restart.** Re-issue toggles "
            "after deploys."
        )
        return "\n".join(lines)

    def _board_toggle_flag(self, attr: str, value: str, *, label: str) -> str:
        """Flip a boolean flag on the live BridgeConfig (frozen dataclass).

        Uses ``object.__setattr__`` because BridgeConfig is ``frozen=True`` —
        the bypass is intentional and scoped to operator-driven runtime
        toggles. The change is in-process only; bridge.toml is not rewritten.
        """
        v = value.strip().lower()
        if v not in ("on", "off"):
            return f"Usage: /board {label} on|off"
        cfg = getattr(self._app, "config", None) if self._app is not None else None
        if cfg is None:
            return "BridgeConfig not wired (set_app not called)."
        new_val = v == "on"
        try:
            object.__setattr__(cfg, attr, new_val)
        except Exception as exc:
            return f"Failed to set {attr}: {exc}"
        state = "ON" if new_val else "OFF"
        return (
            f"Board {label} {state} (runtime-only; restart reverts to "
            f"bridge.toml).\n\n"
            "**Effective until next daemon restart.** Re-issue this command "
            "after deploys."
        )

    def _board_set_cap(self, args: str) -> str:
        """Register or update a per-feature daily USD cap on the CostTracker.

        ``register_feature_cap`` keeps caps in process memory only — Sprint
        04.04 did not wire persistence, so the registration is reset on
        bridge restart. The help text spells this out for the operator.
        """
        tokens = args.strip().split()
        if len(tokens) < 2:
            return (
                "Usage: /board cap <feature> <usd_per_day>\n"
                "Example: /board cap board 2.50  (in-process only — does "
                "not persist across restart.)"
            )
        feature = tokens[0]
        usd_raw = tokens[1]
        try:
            usd = float(usd_raw)
        except (TypeError, ValueError):
            return f"Invalid USD value: {usd_raw!r}. Expected a number (e.g. 2.50)."
        if usd < 0:
            return f"Daily cap must be >= 0 (got {usd})."
        if self._cost_tracker is None:
            return "CostTracker not wired."
        try:
            self._cost_tracker.register_feature_cap(feature, usd)
        except ValueError as exc:
            return f"Failed to register cap: {exc}"
        return (
            f"Feature cap registered: {feature} = ${usd:.2f}/day "
            f"(in-process; restart resets).\n\n"
            "**Effective until next daemon restart.** Re-issue this command "
            "after deploys."
        )

    async def _board_legacy(self, chat_id: str, question: str) -> str:
        """Original /board reasoning path — preserved for byte-equivalence.

        Prefers the Zone 4 DepartmentRegistry path when wired; falls back to
        the legacy AgentRouter when Zone 4 is not available.
        """
        if self._departments is not None:
            try:
                from teams._types import BridgeDeps
                # Sprint 04.09: route through BridgeDeps.from_app so future
                # field additions (e.g. sessions_dir) flow through automatically.
                # The factory derives memory_store, knowledge_search, event_bus,
                # trust_manager, cost_tracker, sessions_dir, and operator_id
                # from the live BridgeApp.
                deps = BridgeDeps.from_app(
                    self._app,
                    session_id=chat_id,
                    department="board",
                )
                # Board Phase 3 WS2 (#2392) — inject prior board-run outcomes
                # as context so the board deliberates in closed loop rather
                # than open loop. Best-effort: no summary -> unchanged question.
                routed_question = self._board_question_with_outcomes(question)
                result = await self._departments.route("board", routed_question, deps)
                footer = self._z4_session_output_footer(deps, "board")
                # Board Phase 2 WS4 (#2391) — persist the full synthesis so
                # /board-history and the CEO implementation-rate report can read
                # it. Best-effort: a store failure never breaks the board reply.
                self._persist_board_run(chat_id, question, result)
                if result.success:
                    return (
                        f"**Board** ({result.duration_seconds:.1f}s):\n\n"
                        f"{result.manager_output}{footer}"
                    )
                return f"**Board** FAILED: {result.error}{footer}"
            except Exception as exc:
                logger.warning("_cmd_board Z4 route failed, falling back: %s", exc)
        if self._agent_router is None:
            from ..agent_router import AgentRouter
            self._agent_router = AgentRouter()
        return self._agent_router.get_board_prompt(question)

    def _board_run_store(self):
        """Lazily build a BoardRunStore from the live config's data_dir.

        Returns ``None`` when config is unavailable (e.g. some test contexts),
        in which case board-run persistence is silently skipped.
        """
        from pathlib import Path
        app = getattr(self, "_app", None)
        config = getattr(app, "_config", None) if app is not None else None
        data_dir = getattr(config, "data_dir", None) if config is not None else None
        # Guard against a non-path data_dir (e.g. a MagicMock in test contexts):
        # only a real str/Path becomes a store. A truthy mock would otherwise
        # stringify into a junk directory rather than failing cleanly.
        if not isinstance(data_dir, (str, Path)) or not str(data_dir):
            return None
        from ..board_run_store import BoardRunStore
        return BoardRunStore(data_dir)

    def _board_question_with_outcomes(self, question: str) -> str:
        """Prepend prior board-run outcomes to the question (#2392 WS2).

        Returns the question unchanged when no store / no prior outcomes are
        available. Best-effort — never raises.
        """
        try:
            store = self._board_run_store()
            if store is None:
                return question
            summary = store.outcome_summary_for_prompt()
            if not summary:
                return question
            return f"{summary}\n\n---\n\n{question}"
        except Exception as exc:  # noqa: BLE001
            logger.warning("board outcome-context injection failed: %s", exc)
            return question

    def _persist_board_run(self, chat_id: str, question: str, result) -> None:
        """Best-effort persistence of a finished board deliberation (#2391 WS4)."""
        try:
            store = self._board_run_store()
            if store is None:
                return
            member_count = len(getattr(result, "employee_results", ()) or ())
            store.record_run(
                session_id=chat_id,
                question=question,
                synthesis=getattr(result, "manager_output", "") or "",
                success=bool(getattr(result, "success", False)),
                member_count=member_count,
                duration_seconds=float(getattr(result, "duration_seconds", 0.0) or 0.0),
                cost_usd=float(getattr(result, "total_cost_usd", 0.0) or 0.0),
            )
        except Exception as exc:  # noqa: BLE001 — persistence must never break the reply
            logger.warning("board-run persistence failed: %s", exc)

    async def _cmd_board_history(self, chat_id: str, args: str) -> str:
        """List recent board runs with phase, member count, and cost (#2391 WS4)."""
        store = self._board_run_store()
        if store is None:
            return "Board-run history unavailable (config not loaded)."
        records = store.list_recent(limit=10)
        if not records:
            return "No board runs recorded yet."
        lines = ["**Recent board runs:**"]
        for r in records:
            phase = r.phase or "—"
            linked = f", {len(r.linked_issues)} issues" if r.linked_issues else ""
            lines.append(
                f"  `{r.board_run_id}` [{phase}] {r.member_count} members, "
                f"${r.cost_usd:.4f}{linked}"
                f"\n    {r.question[:70]}"
            )
        return "\n".join(lines)

    async def _cmd_goals(self, chat_id: str, args: str) -> str:
        """List active goals."""
        rows = await self._db.fetchall(
            """SELECT key, value FROM knowledge
               WHERE key LIKE 'goal:%'
               AND (archived IS NULL OR archived = 0)
               ORDER BY updated_at DESC LIMIT 10"""
        )
        if not rows:
            return "No active goals."
        lines = ["**Active Goals:**"]
        for row in rows:
            try:
                data = json.loads(row[1])
                desc = data.get("description", row[0])
                deadline = data.get("deadline", "")
                if deadline:
                    lines.append(f"  - {desc} (due: {deadline[:10]})")
                else:
                    lines.append(f"  - {desc}")
            except Exception:
                lines.append(f"  - {row[0]}")
        return "\n".join(lines)

    async def _cmd_tasks(self, chat_id: str, args: str) -> str:
        """List pending HITL tasks."""
        rows = await self._db.fetchall(
            """SELECT id, status, pending_question, created_at FROM async_tasks
               WHERE chat_id = ? AND status IN ('pending', 'needs_input')
               ORDER BY created_at DESC LIMIT 10""",
            (chat_id,),
        )
        if not rows:
            return "No pending tasks."
        lines = ["**Pending Tasks:**"]
        for row in rows:
            lines.append(f"  #{row[0]} [{row[1]}]: {(row[2] or 'No question')[:60]}")
        return "\n".join(lines)

    # -- Autonomy commands --

    async def _cmd_trust(self, chat_id: str, args: str) -> str:
        """Display trust scores for all capability domains."""
        if self._autonomy is None:
            return "Autonomy layer not initialized."
        if args.strip():
            detail = self._autonomy.trust.format_capability_detail(args.strip())
            if detail:
                return detail
            return f"Unknown capability: {args.strip()}"
        return self._autonomy.trust.format_trust_table()

    async def _cmd_escalation(self, chat_id: str, args: str) -> str:
        """Display active escalation alerts."""
        if self._autonomy is None:
            return "Autonomy layer not initialized."
        active = self._autonomy.escalation._active_alerts
        if not active:
            return "No active alerts."
        lines = ["**Active Alerts:**"]
        for source, alert in active.items():
            formatted = self._autonomy.escalation.format_alert(alert)
            if formatted:
                lines.append(f"- **{source}**: {formatted}")
        return "\n".join(lines)

    async def _cmd_events(self, chat_id: str, args: str) -> str:
        """Display recent events from the event bus."""
        if self._autonomy is None:
            return "Autonomy layer not initialized."
        limit = 20
        if args.strip().isdigit():
            limit = min(int(args.strip()), 50)
        return self._autonomy.event_bus.format_recent_events(limit=limit)

    async def _cmd_digest(self, chat_id: str, args: str) -> str:
        """Generate and display the weekly operator digest."""
        if self._autonomy is None:
            return "Autonomy layer not initialized."
        return self._autonomy.build_weekly_digest()

    async def _cmd_proposals(self, chat_id: str, args: str) -> str:
        """Display pending feature proposals."""
        if self._autonomy is None:
            return "Autonomy layer not initialized."
        return self._autonomy.proposals.format_proposals_table()

    # -- Tmux agent commands --
