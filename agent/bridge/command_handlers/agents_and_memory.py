"""Multi-agent + memory-inspection command handlers.

Verbs: spawn, agents, kill_agent, fewshot, edits, approve, reject,
knowledge, trace, recall, find.

Mixed into `bridge.commands.CommandHandler` via multiple inheritance.

Demote-split tracked under issue #1305 (umbrella). Pattern: PR #1687.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


class AgentsAndMemoryMixin:
    """Multi-agent lifecycle + memory-inspection command handlers."""

    async def _cmd_spawn(self, chat_id: str, args: str) -> str:
        """Spawn a Claude agent in a tmux session."""
        if self._tmux_agents is None:
            return "Tmux agents not available (tmux not installed?)."
        if not args.strip():
            return "Usage: /spawn <task description>"
        result = await self._tmux_agents.spawn_agent(args.strip())
        if isinstance(result, str):
            return result  # Error message
        return f"Agent **{result.agent_id}** spawned. Task: {result.task[:100]}"

    async def _cmd_agents(self, chat_id: str, args: str) -> str:
        """List agents or show detail for a specific agent."""
        if self._tmux_agents is None:
            return "Tmux agents not available."
        if args.strip():
            detail = self._tmux_agents.format_agent_detail(args.strip())
            return detail or f"Agent {args.strip()} not found."
        return self._tmux_agents.format_agents_table()

    async def _cmd_kill_agent(self, chat_id: str, args: str) -> str:
        """Kill a running tmux agent."""
        if self._tmux_agents is None:
            return "Tmux agents not available."
        if not args.strip():
            return "Usage: /kill-agent <agent-id>"
        killed = await self._tmux_agents.kill_agent(args.strip())
        if killed:
            return f"Agent {args.strip()} killed."
        return f"Agent {args.strip()} not found or not running."

    # -- Patch D: Few-shot examples --

    async def _cmd_fewshot(self, chat_id: str, args: str) -> str:
        """Show few-shot example store stats and top examples."""
        if not self._few_shot_store:
            return "Few-shot store not initialized."
        try:
            count = self._few_shot_store.count()
            if count == 0:
                return "No few-shot examples stored yet. Examples accumulate from successful interactions."
            all_examples = self._few_shot_store.list_all(limit=5)
            lines = [f"**Few-Shot Examples** — {count} stored\n"]
            for ex in all_examples:
                lines.append(
                    f"• [{ex.task_type}] {ex.input_text[:60]}... "
                    f"(quality: {ex.quality_score:.2f}, used: {ex.use_count}x)"
                )
            return "\n".join(lines)
        except Exception as e:
            return f"Few-shot error: {e}"

    # -- Patch E: Self-edit memory --

    async def _cmd_edits(self, chat_id: str, args: str) -> str:
        """Show pending memory edit requests awaiting operator approval."""
        if not self._self_edit:
            return "Self-edit memory not initialized."
        try:
            pending = self._self_edit.get_pending_edits()
            if not pending:
                return "No pending memory edits."
            lines = [f"**Pending Memory Edits** — {len(pending)} awaiting approval\n"]
            for edit in pending[:10]:
                lines.append(
                    f"• [#{edit['id']}] [{edit['tier']}] {edit['category']}: "
                    f"{str(edit.get('proposed_value', ''))[:80]}"
                )
            lines.append("\nUse `/approve <id>` or `/reject <id>` to action.")
            return "\n".join(lines)
        except Exception as e:
            return f"Edits error: {e}"

    async def _cmd_approve(self, chat_id: str, args: str) -> str:
        """Approve a pending memory edit by ID."""
        if not self._self_edit:
            return "Self-edit memory not initialized."
        try:
            edit_id = int(args.strip())
            success = self._self_edit.approve_pending(edit_id)
            return f"Edit #{edit_id} approved." if success else f"Edit #{edit_id} not found."
        except (ValueError, TypeError):
            return "Usage: /approve <id>"
        except Exception as e:
            return f"Approve error: {e}"

    async def _cmd_reject(self, chat_id: str, args: str) -> str:
        """Reject a pending memory edit by ID."""
        if not self._self_edit:
            return "Self-edit memory not initialized."
        try:
            parts = args.strip().split(None, 1)
            edit_id = int(parts[0])
            reason = parts[1] if len(parts) > 1 else ""
            success = self._self_edit.reject_pending(edit_id, reason)
            return f"Edit #{edit_id} rejected." if success else f"Edit #{edit_id} not found."
        except (ValueError, TypeError):
            return "Usage: /reject <id> [reason]"
        except Exception as e:
            return f"Reject error: {e}"

    # -- Patch F: Temporal knowledge --

    async def _cmd_knowledge(self, chat_id: str, args: str) -> str:
        """Query temporal knowledge store.

        /knowledge              — list all keys
        /knowledge <key>        — show current value + version
        /knowledge history <key> — show version history
        /knowledge expired      — list expired keys
        """
        if not self._temporal_kb:
            return "Temporal knowledge store not initialized."
        try:
            parts = args.strip().split(None, 1)
            subcommand = parts[0].lower() if parts and parts[0] else ""

            if not subcommand:
                count = self._temporal_kb.count()
                keys = self._temporal_kb.list_keys()
                key_preview = ", ".join(keys[:10])
                if len(keys) > 10:
                    key_preview += f" (+{len(keys) - 10} more)"
                return f"**Temporal KB** — {count} entries\nKeys: {key_preview or 'none'}"

            if subcommand == "history" and len(parts) > 1:
                return self._temporal_kb.format_timeline(parts[1].strip())

            if subcommand == "expired":
                expired = self._temporal_kb.get_expired()
                if not expired:
                    return "No expired knowledge entries."
                return f"**Expired keys** ({len(expired)}):\n" + "\n".join(f"• {k}" for k in expired)

            entry = self._temporal_kb.get(subcommand)
            if not entry:
                return f"Key `{subcommand}` not found."
            return (
                f"**{subcommand}** (v{entry.version})\n"
                f"Value: {entry.value[:300]}\n"
                f"Updated: {entry.valid_from} by {entry.changed_by}\n"
                f"Reason: {entry.reason or 'none'}"
            )
        except Exception as e:
            return f"Knowledge error: {e}"

    # -- Patch G: Request tracing --

    async def _cmd_trace(self, chat_id: str, args: str) -> str:
        """Show recent trace span timing breakdown."""
        if not self._tracer:
            return "Tracer not initialized."
        try:
            recent = self._tracer.get_recent_spans(limit=10)
            if not recent:
                return "No traces recorded yet."
            lines = [f"**Recent Traces** — last {len(recent)} spans\n"]
            for span in recent:
                lines.append(
                    f"• [{span.name}] {span.duration_ms:.0f}ms"
                    + (f" — trace {span.trace_id[:8]}" if span.trace_id else "")
                )
            return "\n".join(lines)
        except Exception as e:
            return f"Trace error: {e}"

    # -- Cost tracking --


    async def _cmd_recall(self, chat_id: str, args: str) -> str:
        r"""`/recall <query> [--limit N]` -- fan-out search across 9 memory stores.

        Searches: conversation memory, knowledge store, temporal KB,
        few-shot examples, reflections, daily logs, memory edits,
        second-brain wiki.  The bumba-memory MCP is excluded (not
        reachable from the bridge; query via Claude Code instead).

        Options:
            --limit N   Return up to N results per source (1..10, default 3).

        Alias: /find <query>
        """
        import shlex

        from bridge.recall import recall as _recall_fanout
        from bridge.recall import render_recall

        try:
            tokens = shlex.split(args or "")
        except ValueError:
            return "Usage: /recall <query> [--limit N]"

        limit = 3
        rest: list[str] = []
        i = 0
        while i < len(tokens):
            if tokens[i] == "--limit" and i + 1 < len(tokens):
                try:
                    limit = max(1, min(10, int(tokens[i + 1])))
                except ValueError:
                    return "Usage: /recall <query> [--limit N]  (N must be 1..10)"
                i += 2
            else:
                rest.append(tokens[i])
                i += 1

        query = " ".join(rest).strip()
        if not query:
            return (
                "Usage: /recall <query> [--limit N]\n"
                "Searches 9 memory stores (conversations, knowledge, temporal KB, "
                "few-shot examples, reflections, daily logs, edits, wiki)."
            )

        try:
            results = await _recall_fanout(self._app, query, limit_per_source=limit)
            return render_recall(results, query=query)
        except Exception as exc:
            logger.warning("recall error: %s", exc)
            return f"Recall error: {exc}"

    async def _cmd_find(self, chat_id: str, args: str) -> str:
        """`/find <query>` -- alias for ``/recall``."""
        return await self._cmd_recall(chat_id, args)

    # -- MCP monitor --

