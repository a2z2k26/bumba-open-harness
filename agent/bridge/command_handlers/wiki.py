"""Second-brain wiki command handlers (Sprint 05.10 / 05.11).

Verbs: wiki, promote, reject_wiki, shadow_report (+ _second_brain_enabled
helper).

`/promote` and `/reject_wiki` here are the second-brain operator-review
flow (Sprint 05.10 #1020); `_cmd_approve` / `_cmd_reject` (memory-edit
approval workflow) live in `AgentsAndMemoryMixin` — distinct verbs, same
underscore-prefixed shapes.

Mixed into `bridge.commands.CommandHandler` via multiple inheritance.

Demote-split tracked under issue #1305 (umbrella). Pattern: PR #1687.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


class WikiMixin:
    """Second-brain wiki + shadow-router command handlers."""

    def _second_brain_enabled(self) -> bool:
        """Return True iff ``second_brain_enabled`` is True on the live config.

        Defensive: if no live BridgeApp is wired (test bench, partial
        startup), assume disabled so the three handlers return a
        helpful hint rather than touching an unwired WikiRepo.
        """
        cfg = getattr(self._app, "config", None) if self._app is not None else None
        if cfg is None:
            return False
        return bool(getattr(cfg, "second_brain_enabled", False))

    async def _cmd_wiki(self, chat_id: str, args: str) -> str:
        """``/wiki <query>`` — query the second-brain.

        Sub-commands (per spec ref-audit-05-10):
        - ``/wiki``                  — list 10 most recently staged notes
        - ``/wiki list staging``     — list all pending staged notes
        - ``/wiki health``           — short health summary (counts only)
        - ``/wiki <free-form text>`` — route to ``second_brain.query.query``
                                       when the query module is shippable;
                                       graceful fallback when not.

        Returns a helpful message when ``second_brain_enabled`` is False
        or when the WikiRepo is not wired (no vault touched).
        """
        if not self._second_brain_enabled():
            return (
                "Second-brain is not enabled. Set "
                "`[second_brain] enabled = true` in `bridge.toml` and "
                "configure `vault_root`."
            )
        if self._wiki_repo is None:
            return "Second-brain WikiRepo not wired."

        text = (args or "").strip()
        if not text:
            staged = list(self._wiki_repo.list_staging())
            if not staged:
                return "No notes pending operator review."
            preview = staged[-10:]
            lines = [f"**{len(staged)} note(s) pending review** (showing last 10):"]
            for rel in preview:
                lines.append(f"- `{rel}`")
            return "\n".join(lines)

        lower = text.lower()
        if lower == "list staging":
            staged = list(self._wiki_repo.list_staging())
            if not staged:
                return "No notes pending operator review."
            lines = [f"**{len(staged)} note(s) pending review:**"]
            for rel in staged:
                lines.append(f"- `{rel}`")
            return "\n".join(lines)
        if lower == "health":
            staged = list(self._wiki_repo.list_staging())
            curated = list(self._wiki_repo.list_curated())
            return (
                "**Second-brain health**\n"
                f"  staged: {len(staged)}\n"
                f"  curated: {len(curated)}\n"
                f"  vault_root: `{self._wiki_repo.vault_root}`"
            )

        # Free-form query — try the query module if it has shipped.
        try:
            from ..second_brain import ingest as sb_ingest  # type: ignore
            from ..second_brain import query as sb_query_mod  # type: ignore
        except ImportError:
            return (
                "Second-brain query not yet shipped. "
                "Use `/wiki list staging` or `/wiki health` for now."
            )
        _cfg = getattr(self._app, "_config", None) if self._app is not None else None
        try:
            notes_tuple, _ = await sb_ingest.ingest_vault(
                self._wiki_repo.vault_root,
                summarize_canonical_only=False,
                dream_agent_runner=None,
            )
            response = await sb_query_mod.query(
                text,
                notes=notes_tuple,
                strategy=getattr(_cfg, "second_brain_query_strategy", "index_first"),
                k=getattr(_cfg, "second_brain_query_k", 10),
                fallthrough_threshold=getattr(_cfg, "second_brain_query_fallthrough_threshold", 3),
            )
        except Exception as e:  # noqa: BLE001 — surface query errors
            return f"Wiki query error: {e}"

        results = list(getattr(response, "results", []))[:5]
        if not results:
            return f"No matches for query: {text!r}"
        lines = [f"**Top {len(results)} results for** {text!r}:"]
        for r in results:
            title = getattr(r, "title", "") or "(no title)"
            snippet = (getattr(r, "snippet", "") or "").replace("\n", " ")
            rel = getattr(r, "relpath", "")
            if len(snippet) > 200:
                snippet = snippet[:200] + "..."
            lines.append(f"- **{title}** — `{rel}`\n  {snippet}")
        return "\n".join(lines)

    async def _cmd_promote(self, chat_id: str, args: str) -> str:
        """``/promote <staging_relpath> [destination_relpath]`` — promote staged note.

        Returns a helpful message when ``second_brain_enabled`` is False
        or when the WikiRepo is not wired.
        """
        if not self._second_brain_enabled():
            return (
                "Second-brain is not enabled. Set "
                "`[second_brain] enabled = true` in `bridge.toml` and "
                "configure `vault_root`."
            )
        if self._wiki_repo is None:
            return "Second-brain WikiRepo not wired."
        parts = (args or "").strip().split(None, 2)
        if not parts:
            return "Usage: /promote <staging_relpath> [destination_relpath]"
        source_relpath = parts[0]
        destination_relpath = parts[1] if len(parts) > 1 else None
        try:
            from ..second_brain.promote import promote_note
            result = promote_note(
                self._wiki_repo,
                source_relpath=source_relpath,
                destination_relpath=destination_relpath,
            )
        except FileNotFoundError as e:
            return f"File not found in staging/: {e}"
        except ValueError as e:
            return f"Promote rejected: {e}"
        except Exception as e:  # noqa: BLE001 — surface unknown errors
            return f"Promote error: {e}"
        # Sprint 05.11 (#1021) — correlate the operator's promote into
        # any matching shadow-router entry. Never block the primary
        # command on this best-effort observation hook.
        if self._shadow_router is not None:
            try:
                from datetime import datetime, timezone
                self._shadow_router.correlate_promotion(
                    result.source_relpath,
                    decided_at_iso=datetime.now(timezone.utc).strftime(
                        "%Y-%m-%dT%H:%M:%SZ"
                    ),
                )
            except Exception as e:  # noqa: BLE001 — non-fatal
                logger.debug(
                    "promote: shadow correlate failed (non-fatal): %s", e
                )
        if result.already_promoted:
            return (
                f"No-op: `{result.destination_relpath}` already at "
                "destination with identical content."
            )
        return (
            f"Promoted `{result.source_relpath}` -> "
            f"`{result.destination_relpath}` "
            f"({result.bytes_written} bytes)."
        )

    async def _cmd_reject_wiki(self, chat_id: str, args: str) -> str:
        """``/reject_wiki <staging_relpath> [reason]`` — remove staged note.

        Distinct from ``/reject`` (memory-edit approval workflow at line
        ~1190) — that command stays untouched. Returns a helpful message
        when ``second_brain_enabled`` is False.
        """
        if not self._second_brain_enabled():
            return (
                "Second-brain is not enabled. Set "
                "`[second_brain] enabled = true` in `bridge.toml` and "
                "configure `vault_root`."
            )
        if self._wiki_repo is None:
            return "Second-brain WikiRepo not wired."
        raw = (args or "").strip()
        if not raw:
            return "Usage: /reject_wiki <staging_relpath> [reason]"
        parts = raw.split(None, 1)
        source_relpath = parts[0]
        reason = parts[1] if len(parts) > 1 else None
        try:
            from ..second_brain.promote import reject_note
            result = reject_note(
                self._wiki_repo,
                source_relpath=source_relpath,
                reason=reason,
            )
        except ValueError as e:
            return f"Reject rejected: {e}"
        except Exception as e:  # noqa: BLE001 — surface unknown errors
            return f"Reject error: {e}"

        # Best-effort rejection signal — log a temporal-knowledge entry
        # so future contributors can learn what NOT to surface. Failures
        # here are non-fatal; rejection itself already succeeded.
        if self._temporal_kb is not None and reason:
            try:
                key = f"second-brain:rejected:{source_relpath}"
                self._temporal_kb.set(
                    key=key,
                    value=reason,
                    changed_by="operator",
                    reason="reject_wiki",
                )
            except Exception as e:  # noqa: BLE001 — non-fatal
                logger.debug(
                    "reject_wiki: temporal_kb signal failed (non-fatal): %s", e
                )

        # Sprint 05.11 (#1021) — correlate the operator's rejection
        # into any matching shadow-router entry. Best-effort.
        if self._shadow_router is not None:
            try:
                from datetime import datetime, timezone
                self._shadow_router.correlate_rejection(
                    result.source_relpath,
                    decided_at_iso=datetime.now(timezone.utc).strftime(
                        "%Y-%m-%dT%H:%M:%SZ"
                    ),
                )
            except Exception as e:  # noqa: BLE001 — non-fatal
                logger.debug(
                    "reject_wiki: shadow correlate failed (non-fatal): %s", e
                )
        if result.deleted:
            suffix = f" (reason: {result.reason})" if result.reason else ""
            return f"Rejected `{result.source_relpath}`{suffix}."
        suffix = f" (reason: {result.reason})" if result.reason else ""
        return f"No-op: `{result.source_relpath}` already absent{suffix}."

    async def _cmd_shadow_report(self, chat_id: str, args: str) -> str:
        """``/shadow_report`` — 14-day shadow-router rolling summary.

        Sprint 05.11 (#1021). Returns a helpful message when the
        shadow router is not enabled or not wired. Otherwise renders
        the rolling window via
        :func:`bridge.second_brain.shadow_router.format_shadow_report`.

        Optional argument: an integer ``days`` (e.g. ``/shadow_report 7``)
        to override the default window. Falls back to the config-driven
        default when omitted.
        """
        if self._shadow_router is None:
            return (
                "Shadow router is not enabled. Set "
                "`[second_brain] shadow_router_enabled = true` in "
                "`bridge.toml` to start observing consolidation outputs."
            )
        cfg = (
            getattr(self._app, "config", None) if self._app is not None else None
        )
        window_days = (
            getattr(cfg, "second_brain_shadow_router_window_days", 14)
            if cfg is not None
            else 14
        )
        promote_threshold = (
            getattr(
                cfg,
                "second_brain_shadow_router_promote_threshold",
                0.90,
            )
            if cfg is not None
            else 0.90
        )
        # Operator can override window via argument.
        text = (args or "").strip()
        if text:
            try:
                window_days = int(text.split()[0])
            except (ValueError, IndexError):
                pass

        try:
            from ..second_brain.shadow_router import (
                aggregate_shadow_window,
                format_shadow_report,
            )
            report = aggregate_shadow_window(
                days=window_days,
                log_dir=self._shadow_router.log_dir,
            )
            return format_shadow_report(
                report,
                promote_threshold=promote_threshold,
            )
        except Exception as e:  # noqa: BLE001 — surface unknown errors
            return f"Shadow report error: {e}"

