"""Department, routing, handoff, directives, and Z4-tasks command handlers.

Verbs: departments, route, handoff, directives, direct, z4_tasks,
surfaces, ack.

Mixed into `bridge.commands.CommandHandler` via multiple inheritance.

Demote-split tracked under issue #1305 (umbrella). Pattern: PR #1687.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


class DepartmentsMixin:
    """Department routing, directives, Z4-tasks, surfaces, and ack handlers."""

    async def _cmd_departments(self, chat_id: str, args: str) -> str:
        """List registered Zone 4 departments. Subcommand: reset <name>."""
        if self._departments is None:
            return "Zone 4 departments not wired."

        # Handle /departments reset <name>
        stripped = args.strip()
        if stripped.startswith("reset"):
            parts = stripped.split(None, 1)
            if len(parts) < 2 or not parts[1].strip():
                return "Usage: /departments reset <department-name>"
            dept_name = parts[1].strip()
            if self._circuit_registry is None:
                return "Circuit breaker registry not wired."
            available = self._departments.department_names()
            if dept_name not in available:
                return f"Unknown department: {dept_name}. Available: {', '.join(available)}"
            self._circuit_registry.get(dept_name).reset()
            return f"Circuit for **{dept_name}** reset to CLOSED."

        names = self._departments.department_names()
        if not names:
            return "No departments registered."
        lines = [f"**Departments** ({len(names)}):"]
        for name in names:
            cfg = self._departments.get_config(name)
            vapi_status = "voice enabled" if (cfg.vapi and cfg.vapi.enabled) else "voice disabled"
            circuit_label = "CLOSED"
            if self._circuit_registry is not None:
                circuit_label = self._circuit_registry.get(name).state.value.upper()
            lines.append(
                f"  - **{name}** [{circuit_label}] (zone {cfg.zone}) — {len(cfg.employees)} employees — {vapi_status}"
            )
        return "\n".join(lines)

    async def _cmd_route(self, chat_id: str, args: str) -> str:
        """Manually route a task to a department. Usage: /route <department> <task>"""
        if self._departments is None:
            return "Zone 4 departments not wired."
        parts = args.strip().split(None, 1)
        if len(parts) < 2:
            return "Usage: /route <department> <task>"
        dept, task = parts[0], parts[1]
        available = self._departments.department_names()
        if dept not in available:
            return f"Unknown department: {dept}. Available: {', '.join(available)}"
        try:
            from teams._types import BridgeDeps
            # Sprint 04.10: route through BridgeDeps.from_app so future field
            # additions (e.g. sessions_dir) flow through automatically. The
            # factory derives memory_store, knowledge_search, event_bus,
            # trust_manager, cost_tracker, sessions_dir, and operator_id from
            # the live BridgeApp. operator_id used to be set to chat_id here;
            # from_app derives it from app.config.operator.chat_id which is
            # the canonical operator identifier.
            deps = BridgeDeps.from_app(
                self._app,
                session_id=chat_id,
                department=dept,
            )
            result = await self._departments.route(dept, task, deps)
            footer = self._z4_session_output_footer(deps, dept)
            if result.success:
                return (
                    f"**{dept}** ({result.duration_seconds:.1f}s):\n\n"
                    f"{result.manager_output}{footer}"
                )
            return f"**{dept}** FAILED: {result.error}{footer}"
        except Exception as e:  # noqa: BLE001
            return f"Error routing to {dept}: {e}"

    # -- Checkpoints / resume (WS2.6 #2570) --

    def _artifact_root(self):
        """Resolve the configured Zone 4 artifact root, or ``None``.

        Reads ``zone4_artifact_root`` off the live BridgeApp config — the
        same source ``BridgeDeps.from_app`` derives ``artifact_root`` from
        (teams/_types.py). Returns an expanded ``Path`` or ``None`` when the
        app or config field is absent.
        """
        from pathlib import Path

        cfg = getattr(self._app, "config", None) if self._app else None
        configured = getattr(cfg, "zone4_artifact_root", None) if cfg else None
        if not configured:
            return None
        return Path(configured).expanduser()

    async def _cmd_checkpoints(self, chat_id: str, args: str) -> str:
        """List resumable run checkpoints, newest first. Usage: /checkpoints

        WS2.6 (#2570). Scans ``artifact_root`` for ``<run_id>/checkpoint.json``
        records, keeps only those with ``resumable == True``, and renders one
        line per record (run_id, department, failure_class, checkpoint age),
        freshest first. Resume any of them with ``/resume <run_id>``.
        """
        from bridge.run_artifacts import load_checkpoint

        root = self._artifact_root()
        if root is None:
            return (
                "No artifact root configured — set `zone4_artifact_root` in "
                "bridge.toml to enable run checkpoints."
            )
        if not root.exists():
            return "No resumable checkpoints found."

        records = []
        for run_dir in root.iterdir():
            if not run_dir.is_dir():
                continue
            record = load_checkpoint(run_dir)
            if record is not None and record.resumable:
                records.append(record)

        if not records:
            return "No resumable checkpoints found."

        # Newest first by checkpoint timestamp (ISO-8601 strings sort
        # lexicographically in chronological order; fall back to run_id when
        # the timestamp is malformed so the listing never crashes).
        records.sort(
            key=lambda r: (r.checkpoint_at_utc or "", r.run_id),
            reverse=True,
        )

        lines = [f"**Resumable checkpoints** ({len(records)}):", ""]
        for r in records:
            fc = r.failure_class or "unknown"
            age = self._checkpoint_age(r.checkpoint_at_utc)
            attempt = f" attempt={r.attempt}" if r.attempt > 1 else ""
            lines.append(
                f"- `{r.run_id}` **{r.department}** [{fc}] {age}{attempt}"
            )
            lines.append(f"   resume: `/resume {r.run_id}`")
        return "\n".join(lines)

    @staticmethod
    def _checkpoint_age(checkpoint_at_utc: str | None) -> str:
        """Render a human-readable age for a checkpoint ISO-8601 timestamp."""
        if not checkpoint_at_utc:
            return "age unknown"
        from datetime import datetime, timezone

        try:
            ts = datetime.fromisoformat(checkpoint_at_utc)
        except ValueError:
            return "age unknown"
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        delta = datetime.now(timezone.utc) - ts
        seconds = int(delta.total_seconds())
        if seconds < 0:
            return "just now"
        if seconds < 3600:
            return f"{seconds // 60}m ago"
        if seconds < 86400:
            return f"{seconds // 3600}h ago"
        return f"{seconds // 86400}d ago"

    async def _resume_run(self, chat_id: str, run_id: str) -> str:
        """Re-dispatch a checkpointed run. Usage: /resume <run_id>

        WS2.6 (#2570). Loads the checkpoint at ``artifact_root/<run_id>`` to
        recover its department + task, then routes through the SAME
        ``DepartmentRegistry.route`` path /route uses with
        ``resume_from=<run_id>``. Publishes ``z4.run.resumed`` (best-effort)
        and reports the new run_id. Called by ``_cmd_resume`` when the
        operator supplies a run_id argument.
        """
        if self._departments is None:
            return "Zone 4 departments not wired."

        from bridge.run_artifacts import load_checkpoint

        root = self._artifact_root()
        if root is None:
            return (
                "No artifact root configured — set `zone4_artifact_root` in "
                "bridge.toml to enable run checkpoints."
            )
        record = load_checkpoint(root / run_id)
        if record is None:
            return (
                f"No resumable checkpoint found for run_id `{run_id}`. "
                f"List resumable runs with `/checkpoints`."
            )
        if not record.resumable:
            return (
                f"Checkpoint `{run_id}` is not resumable "
                f"(failure_class={record.failure_class!r})."
            )

        dept = record.department
        available = self._departments.department_names()
        if dept not in available:
            return (
                f"Checkpoint department `{dept}` is not registered. "
                f"Available: {', '.join(available)}"
            )

        try:
            from teams._types import BridgeDeps

            deps = BridgeDeps.from_app(
                self._app,
                session_id=chat_id,
                department=dept,
            )
            result = await self._departments.route(
                dept, record.task, deps, resume_from=run_id
            )
        except Exception as e:  # noqa: BLE001
            return f"Error resuming {run_id}: {e}"

        # Best-effort lifecycle event — never blocks the operator reply.
        try:
            from bridge.event_bus import EventBus
            EventBus.get_instance().publish("z4.run.resumed", {
                "department": dept,
                "resumed_from": run_id,
                "new_run_id": getattr(result, "run_id", None),
                "attempt": record.attempt,
                "success": result.success,
            })
        except Exception:  # noqa: BLE001
            pass

        new_run_id = getattr(result, "run_id", None) or "(unknown)"
        if result.success:
            return (
                f"**{dept}** resumed `{run_id}` → `{new_run_id}` "
                f"({result.duration_seconds:.1f}s):\n\n{result.manager_output}"
            )
        return (
            f"**{dept}** resume of `{run_id}` → `{new_run_id}` "
            f"FAILED: {result.error}"
        )

    async def _cmd_handoff(self, chat_id: str, args: str) -> str:
        """Operator-mediated cross-harness handoff + legacy Zone 4 continuation.

        Two forms are recognised:

        - ``/handoff continue <correlation_id>`` — the original Zone 4
          cross-department continuation path. Wired in Sprint 04.11; left
          intact here.
        - ``/handoff <to-harness> <topic>`` — Sprint 1112.1.02 (#2139)
          operator-facing composer. Synthesises a ``HandoffDraft`` from the
          recent chat conversation, saves the transcript as a GitHub gist,
          and stashes the draft under ``self._pending_handoffs[chat_id]``
          for the fire path that lands in Sprint 1.04 (#2141).

        The two forms are disambiguated by the first positional arg:
        ``continue`` routes to the legacy path; anything else routes to the
        composer. This keeps both call sites stable while the new feature
        ships incrementally — the alternative (a new ``/handoff_compose``
        verb) would fragment the surface.
        """
        parts = args.strip().split(None, 1)
        if parts and parts[0] == "continue":
            return await self._cmd_handoff_continue(chat_id, args)
        # Sprint 1.04 (#2141) — fire-path continuation verbs.
        # Operator replies with `/handoff go|edit|abort` against a draft
        # stashed by `_cmd_handoff_compose` in `_pending_handoffs[chat_id]`.
        if parts and parts[0] in ("go", "edit", "abort"):
            return await self._cmd_handoff_fire_continue(chat_id, parts[0])
        if parts and parts[0] == "resolve":
            return await self._cmd_handoff_resolve(chat_id, args[len("resolve"):].strip())
        return await self._cmd_handoff_compose(chat_id, args)

    async def _cmd_handoff_compose(self, chat_id: str, args: str) -> str:
        """Compose a cross-harness handoff draft. Usage: /handoff <to-harness> <topic>

        Implements Sprint 1112.1.02 (#2139). Saves the recent conversation
        as a gist for durability, then composes a ``HandoffDraft`` and
        renders it back to the operator for review. No fire-path side
        effects — the operator must reply ``go`` (wired in Sprint 1.04)
        for the draft to actually travel.
        """
        from bridge.handoff import (
            compose_handoff,
            format_draft_for_operator,
            save_conversation_gist,
        )

        parts = args.strip().split(None, 1)
        if len(parts) != 2 or not parts[0] or not parts[1]:
            return "Usage: /handoff <to-harness> <topic>"
        to_harness, topic = parts[0], parts[1]

        # Pull config from the live BridgeApp. Falls back to a friendly
        # error rather than AttributeError when the app reference is
        # absent — defends against unit tests that wire the handler
        # without an app.
        cfg = getattr(self._app, "config", None) if self._app else None
        if cfg is None:
            return "Handoff config unavailable (BridgeApp not wired)."

        peers = tuple(getattr(cfg, "peer_harness_ids", ()) or ())
        if to_harness not in peers:
            peer_list = ", ".join(peers) if peers else "(none)"
            return (
                f"Unknown harness `{to_harness}`. "
                f"Configured peers: {peer_list}"
            )

        # Pull recent conversation as composer context. Memory is duck-typed
        # against ``ConversationMixin.get_recent_messages`` to match the
        # canonical bridge ``Memory`` API (memory/conversation.py:83).
        conversation = ""
        if self._memory is not None:
            try:
                recent = await self._memory.get_recent_messages(chat_id, limit=50)
            except Exception:  # noqa: BLE001
                recent = []
            conversation = "\n".join(
                f"{m.get('role', '?')}: {m.get('content', '')}"
                for m in recent
            )

        # Save gist first — if it fails, fail before composing the draft so
        # the operator never sees a draft that has no durable artifact.
        try:
            gist_url = save_conversation_gist(
                conversation=conversation,
                from_harness=getattr(cfg, "harness_id", "local-1"),
                to_harness=to_harness,
                topic=topic,
            )
        except Exception as e:  # noqa: BLE001
            return f"Failed to save conversation gist: {e}"

        draft = compose_handoff(
            conversation_ctx=conversation,
            from_harness=getattr(cfg, "harness_id", "local-1"),
            to_harness=to_harness,
            topic=topic,
        )

        # Stash the pending draft under chat_id so the fire path (Sprint
        # 1.04 #2141) can look it up when the operator replies ``go``.
        # ``_pending_handoffs`` is initialised in CommandHandler.__init__;
        # tests that bypass __init__ via ``__new__`` set it explicitly.
        if not hasattr(self, "_pending_handoffs"):
            self._pending_handoffs = {}
        self._pending_handoffs[chat_id] = (draft, gist_url)

        return format_draft_for_operator(draft, gist_url)

    async def _cmd_handoff_continue(self, chat_id: str, args: str) -> str:
        """Continue a Zone 4 cross-department handoff.

        Original Sprint 04.11 path — preserved as a separate helper so the
        new operator-facing /handoff path can be unit-tested without
        dragging in DepartmentRegistry + load_handoff. Usage:
        ``/handoff continue <correlation_id>``.
        """
        if self._departments is None:
            return "Zone 4 departments not wired."

        parts = args.strip().split(None, 2)
        if len(parts) < 2 or parts[0] != "continue":
            return "Usage: /handoff continue <correlation_id>"
        correlation_id = parts[1]

        try:
            from teams._handoff import load_handoff
            from teams._types import BridgeDeps
            from bridge.memory import MemoryKVAdapter

            # load_handoff still needs a memory_store to read the envelope —
            # construct one locally for that call only.
            memory_store = MemoryKVAdapter(self._memory) if self._memory else None
            envelope = await load_handoff(correlation_id, memory_store)
            if envelope is None:
                return f"No handoff found for correlation_id={correlation_id}"

            target = envelope.to_department
            available = self._departments.department_names()
            if target not in available:
                return (
                    f"Target department '{target}' not registered. "
                    f"Available: {', '.join(available)}"
                )

            # Sprint 04.11: route through BridgeDeps.from_app so future field
            # additions (e.g. sessions_dir) flow through automatically. The
            # factory derives memory_store, knowledge_search, event_bus,
            # trust_manager, cost_tracker, sessions_dir, and operator_id from
            # the live BridgeApp.
            deps = BridgeDeps.from_app(
                self._app,
                session_id=chat_id,
                department=target,
            )
            handoff_context = (
                f"Handoff from {envelope.from_department}: {envelope.task}\n"
                f"Findings: {envelope.findings}"
            )
            result = await self._departments.route(target, handoff_context, deps)
            if result.success:
                return (
                    f"**Handoff {envelope.from_department} -> {target}** "
                    f"({result.duration_seconds:.1f}s):\n\n{result.manager_output}"
                )
            return f"**Handoff to {target}** FAILED: {result.error}"
        except Exception as e:  # noqa: BLE001
            return f"Error processing handoff: {e}"

    async def _cmd_handoff_fire_continue(self, chat_id: str, verb: str) -> str:
        """Fire-path continuation for a pending /handoff draft (Sprint 1.04 #2141).

        ``verb`` is one of ``go`` / ``edit`` / ``abort``:
        - ``go``: invoke ``fire_handoff`` against the stashed (draft, gist_url);
          replace the pending entry with the resulting HandoffPacket so
          ``/handoff resolve`` can find it later.
        - ``edit``: keep the draft stashed; surface a hint that the operator
          should re-compose via ``/handoff <to-harness> <topic>``. Editing a
          composed draft in-place is deferred; re-compose is simpler.
        - ``abort``: clear the pending draft + acknowledge.
        """
        if not hasattr(self, "_pending_handoffs"):
            self._pending_handoffs = {}
        pending = self._pending_handoffs.get(chat_id)
        if pending is None:
            return (
                "No pending handoff draft for this chat. "
                "Compose one via `/handoff <to-harness> <topic>` first."
            )

        if verb == "abort":
            del self._pending_handoffs[chat_id]
            return "Pending handoff aborted."

        if verb == "edit":
            return (
                "Re-compose by running `/handoff <to-harness> <topic>` again. "
                "The current pending draft will be replaced."
            )

        # verb == "go"
        draft, gist_url = pending
        # Resolve peer channel id from operator config — required for cross-harness fire.
        cfg = getattr(self._app, "config", None) if self._app else None
        if cfg is None:
            return "Handoff config unavailable (BridgeApp not wired)."
        peer_channels = getattr(cfg, "peer_harness_channel_ids", None) or {}
        target_channel_id = peer_channels.get(draft.to_harness)
        if target_channel_id is None:
            return (
                f"No peer channel id configured for `{draft.to_harness}`. "
                f"Set `peer_harness_channel_ids` in bridge.toml and restart."
            )

        # Resolve Discord client — duck-typed off BridgeApp's discord_bot.
        discord_bot = getattr(self._app, "_discord_bot", None) or getattr(self._app, "discord_bot", None)
        if discord_bot is None or not hasattr(discord_bot, "get_channel"):
            return "Discord client not wired; cannot fire handoff."

        from bridge.handoff import fire_handoff
        try:
            packet = await fire_handoff(
                draft=draft,
                gist_url=gist_url,
                target_channel_id=int(target_channel_id),
                discord_client=discord_bot,
            )
        except Exception as e:  # noqa: BLE001
            return f"Failed to fire handoff: {e}"

        # Replace pending entry with the fired packet so `/handoff resolve`
        # can find it. Keyed by gist_url to align with the packet-id surface.
        self._pending_handoffs[chat_id] = packet

        return (
            f"Fired handoff `{draft.to_harness}` ← `{draft.from_harness}` "
            f"(topic: {draft.topic}).\n"
            f"Gist: {packet.artifact_url}\n"
            f"Fired at: {packet.fired_at}\n\n"
            f"Resolve when complete: `/handoff resolve <topic-slug>`"
        )

    async def _cmd_handoff_resolve(self, chat_id: str, args: str) -> str:
        """Mark a fired handoff as resolved; migrate gist to handoffs/promoted/.

        Sprint 1.04 (#2141). Usage: ``/handoff resolve <topic-slug>``

        Looks up the fired packet stashed under this chat_id; calls
        ``mark_handoff_resolved`` to migrate the gist content to
        ``handoffs/promoted/<date>-<from>-to-<to>-<topic-slug>.md``.
        Operator-triggered; never automatic.
        """
        if not hasattr(self, "_pending_handoffs"):
            self._pending_handoffs = {}
        packet = self._pending_handoffs.get(chat_id)
        if packet is None:
            return (
                "No fired handoff found for this chat. "
                "Fire one via `/handoff <to-harness> <topic>` then `/handoff go` first."
            )
        # Must be a HandoffPacket (i.e. /handoff go has run), not a (draft, url) tuple
        from bridge.handoff import HandoffPacket, mark_handoff_resolved
        if not isinstance(packet, HandoffPacket):
            return (
                "Pending entry is a draft, not a fired packet. "
                "Run `/handoff go` first, then `/handoff resolve <topic-slug>`."
            )
        topic_slug = args.strip() or packet.one_line_summary
        # Repo root: walk up from this module until we find a .git directory.
        from pathlib import Path
        repo_root = Path(__file__).resolve().parent
        while repo_root != repo_root.parent and not (repo_root / ".git").exists():
            repo_root = repo_root.parent
        if not (repo_root / ".git").exists():
            return "Could not locate repo root; refusing to write promoted handoff."
        try:
            rel_path = mark_handoff_resolved(
                packet=packet,
                topic_slug=topic_slug,
                repo_root=repo_root,
            )
        except Exception as e:  # noqa: BLE001
            return f"Failed to promote handoff: {e}"
        # Clear the pending entry — handoff lifecycle complete from this side.
        del self._pending_handoffs[chat_id]
        return (
            f"Handoff resolved. Promoted to `{rel_path}`.\n"
            f"Original gist: {packet.artifact_url} (preserved)."
        )

    # -- Directives (Sprint 20, Phase 5B) --

    async def _cmd_directives(self, chat_id: str, args: str) -> str:
        """Show Phase 5 directives. Usage: /directives [active|all|chief <name>]

        Defaults to ``active`` (non-terminal directives, freshest first).
        ``all`` returns the most recent 50 regardless of status.
        ``chief <name>`` filters by the addressed chief; pass an unknown
        chief name to get a list of recent ``to_chief`` values.
        """
        from bridge import directive_store

        parts = args.strip().split(None, 1)
        mode = (parts[0].lower() if parts else "active") or "active"

        try:
            if mode == "active":
                directives = await directive_store.list_active(self._db)
                header = f"**Active directives** ({len(directives)})"
            elif mode == "all":
                directives = await directive_store.list_all(self._db, limit=50)
                header = f"**All directives** (most recent {len(directives)})"
            elif mode == "chief":
                if len(parts) < 2:
                    return "Usage: /directives chief <chief-name>"
                chief = parts[1].strip()
                directives = await directive_store.list_by_chief(
                    self._db, chief, include_terminal=True
                )
                header = (
                    f"**Directives addressed to {chief}** ({len(directives)})"
                )
            else:
                return (
                    "Usage: /directives [active|all|chief <name>]"
                )
        except Exception as e:  # noqa: BLE001
            return f"Error reading directives: {e}"

        if not directives:
            return f"{header}\n\n_No directives found._"

        lines = [header, ""]
        for d in directives:
            status = await directive_store.get_status(self._db, d.directive_id)
            status_label = status.value if status else "unknown"
            issued = d.issued_at_utc.strftime("%Y-%m-%d %H:%M")
            deadline_marker = (
                f" deadline={d.deadline_utc.strftime('%Y-%m-%d %H:%M')}"
                if d.deadline_utc
                else ""
            )
            intent_preview = (
                d.intent if len(d.intent) <= 80 else d.intent[:77] + "..."
            )
            lines.append(
                f"- `{d.directive_id}` [{status_label}] {d.priority} "
                f"→ **{d.to_chief}** — {intent_preview}"
            )
            lines.append(
                f"   issued={issued}{deadline_marker} from={d.from_agent}"
            )
        return "\n".join(lines)

    async def _cmd_direct(self, chat_id: str, args: str) -> str:
        """Issue a directive to a chief and route the work. Usage:
        /direct <chief> <intent>

        Sprint 20 (Phase 5B): operator-issued directive — slot earmarked for
        the future Main Agent ``direct()`` tool. Persists a Directive,
        prepends ``[directive_id: dir-xxx]`` to the chief's task, and
        records lifecycle transitions (IN_PROGRESS → DONE on success;
        BLOCKED on timeout / exception). The chief should call
        ``acknowledge_directive`` as its first action.
        """
        if self._departments is None:
            return "Zone 4 departments not wired."

        parts = args.strip().split(None, 1)
        if len(parts) < 2:
            return "Usage: /direct <chief> <intent>"
        chief, intent = parts[0], parts[1]

        # Use the chief name as the department identifier for now — the
        # registry routes by department name and the chief lives 1:1 with
        # its department. Validate against the registered set.
        available = self._departments.department_names()
        if chief not in available:
            return (
                f"Unknown chief/department: {chief}. "
                f"Available: {', '.join(available)}"
            )

        try:
            from datetime import datetime, timezone
            from bridge import directive_store
            from teams._types import BridgeDeps, Directive

            directive = Directive(
                directive_id=directive_store.new_directive_id(),
                from_agent="operator",
                to_chief=chief,
                intent=intent,
                constraints=(),
                deadline_utc=None,
                priority="p1",
                issued_at_utc=datetime.now(timezone.utc),
                context={"chat_id": chat_id},
                operator_id=chat_id,
            )
            await directive_store.insert_directive(self._db, directive)

            deps = BridgeDeps.from_app(
                self._app,
                session_id=chat_id,
                department=chief,
            )
            result = await self._departments.route(
                chief, intent, deps,
                directive_id=directive.directive_id,
            )

            status = await directive_store.get_status(
                self._db, directive.directive_id
            )
            status_label = status.value if status else "unknown"
            if result.success:
                return (
                    f"**{chief}** [`{directive.directive_id}` → {status_label}] "
                    f"({result.duration_seconds:.1f}s):\n\n{result.manager_output}"
                )
            return (
                f"**{chief}** [`{directive.directive_id}` → {status_label}] "
                f"FAILED: {result.error}"
            )
        except Exception as e:  # noqa: BLE001
            return f"Error issuing directive to {chief}: {e}"

    async def _cmd_z4_tasks(self, chat_id: str, args: str) -> str:
        """Show Phase 5 chief→specialist tasks. Usage:
        /z4_tasks [active|directive <id>|chief <name>|all]

        Sprint 21 (Phase 5B): inspects the tasks table populated by chief
        delegations. Disambiguated as ``z4_tasks`` to avoid collision with
        the existing /tasks (goal/task management) command.

        Defaults to ``active`` (non-terminal tasks, freshest first).
        ``directive <id>`` shows tasks tied to one Directive in
        chronological order — useful for reading a directive's call graph.
        ``chief <name>`` filters by issuing chief.
        ``all`` returns the most recent 50 regardless of status.
        """
        from bridge import task_store

        parts = args.strip().split(None, 1)
        mode = (parts[0].lower() if parts else "active") or "active"

        try:
            if mode == "active":
                tasks = await task_store.list_active(self._db)
                header = f"**Active tasks** ({len(tasks)})"
            elif mode == "all":
                tasks = await task_store.list_all(self._db, limit=50)
                header = f"**All tasks** (most recent {len(tasks)})"
            elif mode == "directive":
                if len(parts) < 2:
                    return "Usage: /z4_tasks directive <directive-id>"
                did = parts[1].strip()
                tasks = await task_store.list_by_directive(self._db, did)
                header = f"**Tasks under directive {did}** ({len(tasks)})"
            elif mode == "chief":
                if len(parts) < 2:
                    return "Usage: /z4_tasks chief <chief-name>"
                chief = parts[1].strip()
                tasks = await task_store.list_by_chief(
                    self._db, chief, include_terminal=True
                )
                header = (
                    f"**Tasks issued by {chief}** ({len(tasks)})"
                )
            else:
                return (
                    "Usage: /z4_tasks [active|directive <id>|chief <name>|all]"
                )
        except Exception as e:  # noqa: BLE001
            return f"Error reading tasks: {e}"

        if not tasks:
            return f"{header}\n\n_No tasks found._"

        lines = [header, ""]
        for t in tasks:
            status = await task_store.get_status(self._db, t.task_id)
            status_label = status.value if status else "unknown"
            issued = t.issued_at_utc.strftime("%Y-%m-%d %H:%M")
            description_preview = (
                t.description if len(t.description) <= 80
                else t.description[:77] + "..."
            )
            directive_marker = (
                f" parent={t.directive_id}" if t.directive_id else ""
            )
            lines.append(
                f"- `{t.task_id}` [{status_label}] "
                f"**{t.from_chief}** → **{t.to_specialist}** — {description_preview}"
            )
            lines.append(
                f"   issued={issued}{directive_marker}"
            )
        return "\n".join(lines)

    # -- Surfaces (Sprint 22, Phase 5C) --

    async def _cmd_surfaces(self, chat_id: str, args: str) -> str:
        """Show Phase 5 upward surfaces. Usage:
        /surfaces [active|unread|directive <id>|kind <name>|all]

        Sprint 22 (Phase 5C): inspects the surfaces table populated by
        specialist→chief and chief→main upward events.

        Defaults to ``active`` (unread surfaces, freshest first).
        ``unread`` shows surfaces addressed to ``main`` (the operator's
        inbox) that haven't been /ack'd.
        ``directive <id>`` shows the full surface trail under one Directive
        in chronological order — the call graph view.
        ``kind <name>`` filters by surface kind (result, flag, blocker,
        scope_request, cross_team, policy_q).
        ``all`` returns the most recent 50 regardless of state.
        """
        from bridge import surface_store

        parts = args.strip().split(None, 1)
        mode = (parts[0].lower() if parts else "active") or "active"

        try:
            if mode == "active":
                surfaces = await surface_store.list_active(self._db, limit=50)
                header = f"**Active surfaces** ({len(surfaces)})"
            elif mode == "unread":
                surfaces = await surface_store.list_unread_for_agent(
                    self._db, "main"
                )
                header = f"**Unread surfaces to main** ({len(surfaces)})"
            elif mode == "all":
                surfaces = await surface_store.list_all(self._db, limit=50)
                header = f"**All surfaces** (most recent {len(surfaces)})"
            elif mode == "directive":
                if len(parts) < 2:
                    return "Usage: /surfaces directive <directive-id>"
                did = parts[1].strip()
                surfaces = await surface_store.list_by_correlation(self._db, did)
                header = (
                    f"**Surfaces under directive {did}** ({len(surfaces)})"
                )
            elif mode == "kind":
                if len(parts) < 2:
                    return (
                        "Usage: /surfaces kind <result|flag|blocker|"
                        "scope_request|cross_team|policy_q>"
                    )
                kind = parts[1].strip()
                try:
                    surfaces = await surface_store.list_by_kind(
                        self._db, kind, limit=50
                    )
                except ValueError as e:
                    return f"Invalid kind: {e}"
                header = f"**Surfaces of kind {kind}** ({len(surfaces)})"
            else:
                return (
                    "Usage: /surfaces [active|unread|directive <id>|"
                    "kind <name>|all]"
                )
        except Exception as e:  # noqa: BLE001
            return f"Error reading surfaces: {e}"

        if not surfaces:
            return f"{header}\n\n_No surfaces found._"

        lines = [header, ""]
        for s in surfaces:
            created = s.created_at_utc.strftime("%Y-%m-%d %H:%M")
            summary = s.payload.get("summary") or s.payload.get("answer") or ""
            preview = (
                summary if len(summary) <= 80 else summary[:77] + "..."
            )
            corr = (
                f" correlation={s.correlation_id}" if s.correlation_id else ""
            )
            kind_v = s.kind.value if hasattr(s.kind, "value") else s.kind
            urgency_v = (
                s.urgency.value if hasattr(s.urgency, "value") else s.urgency
            )
            lines.append(
                f"- `{s.surface_id}` [{kind_v}/{urgency_v}] "
                f"**{s.from_agent}** → **{s.to_agent}** — {preview}"
            )
            lines.append(f"   created={created}{corr}")
        return "\n".join(lines)

    async def _cmd_ack(self, chat_id: str, args: str) -> str:
        """Acknowledge a surface. Usage: /ack <surface_id>

        Sprint 22 (Phase 5C): marks a surface as read by setting
        ``read_at_utc=now()``. Idempotent — re-acking returns "already
        acknowledged" rather than churning the timestamp.
        """
        from bridge import surface_store

        surface_id = args.strip()
        if not surface_id:
            return "Usage: /ack <surface_id>"

        try:
            updated = await surface_store.mark_read(self._db, surface_id)
        except ValueError as e:
            return f"Error: {e}"
        except Exception as e:  # noqa: BLE001
            return f"Error acknowledging surface: {e}"

        if updated:
            return f"Acknowledged `{surface_id}`."
        return f"`{surface_id}` was already acknowledged."

    # -- Roster registry (RR.4 / #2593) --
    #
    # Self-serve runtime roster overlay: register/unregister a specialist into
    # a department without a YAML edit or redeploy, and list the overlay. The
    # store (``RosterRegistryStore``, wired via ``set_roster_registry``) owns
    # validation AND the load-bearing cache-invalidation seam — its
    # ``on_change(department)`` callback (wired to ``AgentCache.invalidate``)
    # fires after a successful write so the next chief build for that team
    # picks up the overlay. These handlers are a thin operator shell: surface
    # the store's validation error verbatim, never a stack trace.

    async def _cmd_register_specialist(self, chat_id: str, args: str) -> str:
        """Register a runtime specialist into a department roster.

        Usage: /register-specialist <department> <name> <agent_ref>

        ``agent_ref`` must name an existing employee agent in that department
        (it reuses that agent's config — it is not a new agent definition).
        Validation failures (unknown dept, unresolvable agent_ref, duplicate,
        shadowed built-in) come back as the store's clear error message.
        """
        store = getattr(self, "_roster_registry", None)
        if store is None:
            return "Roster registry not wired."

        parts = args.split()
        if len(parts) != 3:
            return (
                "Usage: /register-specialist <department> <name> <agent_ref>"
            )
        department, name, agent_ref = parts

        result = store.register(department, name, agent_ref)
        if not result.ok:
            return f"Could not register: {result.error}"

        self._emit_roster_registered(result.specialist)
        return (
            f"Registered specialist **{name}** in **{department}** "
            f"(agent_ref `{agent_ref}`). The chief for that team will pick it "
            f"up on its next build."
        )

    async def _cmd_unregister_specialist(
        self, chat_id: str, args: str
    ) -> str:
        """Remove a runtime specialist from a department roster.

        Usage: /unregister-specialist <department> <name>
        """
        store = getattr(self, "_roster_registry", None)
        if store is None:
            return "Roster registry not wired."

        parts = args.split()
        if len(parts) != 2:
            return "Usage: /unregister-specialist <department> <name>"
        department, name = parts

        removed = store.unregister(department, name)
        if not removed:
            return (
                f"Specialist **{name}** is not registered in "
                f"**{department}** — nothing to remove."
            )
        return f"Unregistered specialist **{name}** from **{department}**."

    async def _cmd_roster(self, chat_id: str, args: str) -> str:
        """List registered runtime specialists.

        Usage: /roster [department]  — all departments, or one when named.
        """
        store = getattr(self, "_roster_registry", None)
        if store is None:
            return "Roster registry not wired."

        department = args.strip()
        if department:
            specialists = store.list_for_department(department)
            if not specialists:
                return (
                    f"No registered specialists in **{department}** "
                    f"(YAML built-ins are not listed here)."
                )
            lines = [
                f"**Registered specialists — {department}** "
                f"({len(specialists)}):"
            ]
            lines.extend(
                f"  - **{s.name}** → `{s.agent_ref}` "
                f"(by {s.registered_by} @ {s.registered_at})"
                for s in specialists
            )
            return "\n".join(lines)

        specialists = store.list_all()
        if not specialists:
            return (
                "No registered specialists. Add one with "
                "`/register-specialist <department> <name> <agent_ref>`."
            )
        lines = [f"**Registered specialists** ({len(specialists)}):"]
        lines.extend(
            f"  - **{s.department}** / **{s.name}** → `{s.agent_ref}` "
            f"(by {s.registered_by})"
            for s in specialists
        )
        return "\n".join(lines)

    def _emit_roster_registered(self, spec) -> None:
        """Publish ``z4.roster.specialist_registered`` best-effort.

        Mirrors the REST surface (RR.3 ``routes_roster._emit_registered_event``)
        — same event type and payload shape, resolved via the autonomy layer's
        event bus. Never lets an event-publish failure break the command.
        """
        if spec is None:
            return
        autonomy = getattr(self, "_autonomy", None)
        bus = getattr(autonomy, "event_bus", None) if autonomy else None
        if bus is None:
            return
        try:
            bus.publish(
                "z4.roster.specialist_registered",
                {
                    "department": spec.department,
                    "name": spec.name,
                    "agent_ref": spec.agent_ref,
                    "registered_by": spec.registered_by,
                },
                source="command_handlers.departments",
            )
        except Exception:  # noqa: BLE001 — event publish never blocks the reply
            logger.debug("roster register event publish failed", exc_info=True)

    # -- Diagnosis --
