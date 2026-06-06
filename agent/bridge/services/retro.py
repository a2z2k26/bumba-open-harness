"""End-of-day retrospective service.

Runs at ~6:00 PM daily. Backward-looking: what happened today, what's open,
what needs attention tomorrow. Distinct from the morning briefing which is
forward-facing with schedule and goals.

Data sources (direct SQLite, no Claude needed):
- Conversations today (activity volume + decisions made)
- Goals touched vs. advanced vs. overdue
- Knowledge entries added/updated today
- Open loops (unanswered check-ins, pending queue items)
- Tomorrow preview (early deadline warning, next-day calendar events)

Z2-S3.2 (Pattern B PoC): when the feature flag
``ZONE2_RETRO_VIA_STRATEGY=true`` is set, the compiled raw blocks are
routed through the Strategy Z4 department via ServiceDispatchAdapter
and returned as a single composed narrative instead of the default
block-concatenation output.  The flag is off by default so production
behaviour is byte-identical to pre-sprint.

Cost cap: $1.50/run — if Strategy exceeds this, retro falls back to
direct-render for that run and logs a warning.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable

from .base import ServiceBase

log = logging.getLogger(__name__)

# Feature flag env-var name (S3.2)
_FLAG_ENV = "ZONE2_RETRO_VIA_STRATEGY"
# Per-run cost cap enforced before calling Strategy
_STRATEGY_COST_CAP_USD = 1.50

# Registry for retro data sources (ordered for consistent output)
_SOURCES: list[tuple[str, Callable]] = []


def register_source(name: str):
    """Decorator to register a retro data source."""
    def decorator(func: Callable):
        _SOURCES.append((name, func))
        return func
    return decorator


@register_source("Today's Activity")
def _todays_activity(conn: sqlite3.Connection) -> str | None:
    """Summarize what happened in conversations today."""
    row = conn.execute(
        """SELECT COUNT(*) FROM conversations
           WHERE created_at > date('now', 'localtime')"""
    ).fetchone()
    total = row[0] if row else 0

    if total == 0:
        return "**Activity**: No conversations today"

    row = conn.execute(
        """SELECT COUNT(*) FROM conversations
           WHERE created_at > date('now', 'localtime') AND role = 'user'"""
    ).fetchone()
    user_count = row[0] if row else 0

    row = conn.execute(
        """SELECT COUNT(DISTINCT session_id) FROM conversations
           WHERE created_at > date('now', 'localtime')"""
    ).fetchone()
    sessions = row[0] if row else 0

    return (
        f"**Today's Activity**: {user_count} messages across {sessions} session(s)"
    )


@register_source("Goals Progress")
def _goals_progress(conn: sqlite3.Connection) -> str | None:
    """Report goal status — completed, advanced, overdue."""
    rows = conn.execute(
        """SELECT key, value FROM knowledge
           WHERE key LIKE 'goal:%'
           AND (archived IS NULL OR archived = 0)"""
    ).fetchall()

    if not rows:
        return None

    now = datetime.now()
    overdue = []
    due_soon = []
    active = []

    for row in rows:
        try:
            data = json.loads(row[1])
            desc = data.get("description", row[0])
            deadline_str = data.get("deadline")
            if deadline_str:
                deadline = datetime.fromisoformat(deadline_str)
                if deadline < now:
                    overdue.append(f"  - OVERDUE: {desc} (was due {deadline.strftime('%b %d')})")
                elif (deadline - now) < timedelta(hours=24):
                    due_soon.append(f"  - DUE TOMORROW: {desc} ({deadline.strftime('%b %d %-I:%M %p')})")
                else:
                    active.append(f"  - {desc} (due {deadline.strftime('%b %d')})")
            else:
                active.append(f"  - {desc}")
        except (json.JSONDecodeError, ValueError):
            active.append(f"  - {row[0]}")

    if not overdue and not due_soon and not active:
        return None

    lines = [f"**Goals** ({len(active)} active, {len(due_soon)} due soon, {len(overdue)} overdue)"]
    lines.extend(overdue)
    lines.extend(due_soon)
    if active and len(active) <= 5:
        lines.extend(active)
    elif active:
        lines.append(f"  + {len(active)} more active goals")

    return "\n".join(lines)


@register_source("Knowledge Added Today")
def _knowledge_today(conn: sqlite3.Connection) -> str | None:
    """Report new knowledge entries created today."""
    row = conn.execute(
        """SELECT COUNT(*) FROM knowledge
           WHERE created_at > date('now', 'localtime')
           AND (archived IS NULL OR archived = 0)"""
    ).fetchone()
    new_count = row[0] if row else 0

    row = conn.execute(
        """SELECT COUNT(*) FROM knowledge
           WHERE updated_at > date('now', 'localtime')
           AND created_at <= date('now', 'localtime')
           AND (archived IS NULL OR archived = 0)"""
    ).fetchone()
    updated_count = row[0] if row else 0

    if new_count == 0 and updated_count == 0:
        return None

    parts = []
    if new_count:
        parts.append(f"{new_count} new")
    if updated_count:
        parts.append(f"{updated_count} updated")

    return f"**Knowledge**: {', '.join(parts)} entr{'y' if (new_count + updated_count) == 1 else 'ies'} today"


@register_source("Open Loops")
def _open_loops(conn: sqlite3.Connection) -> str | None:
    """Surface anything that started but wasn't resolved today."""
    lines = []

    # Pending messages stuck in queue
    row = conn.execute(
        "SELECT COUNT(*) FROM message_queue WHERE status = 'pending'"
    ).fetchone()
    pending = row[0] if row else 0
    if pending > 0:
        lines.append(f"  - {pending} message(s) pending in queue")

    # Sessions with errors today
    row = conn.execute(
        """SELECT COUNT(*) FROM audit_log
           WHERE event_type LIKE '%error%'
           AND timestamp > date('now', 'localtime')"""
    ).fetchone()
    errors_today = row[0] if row else 0
    if errors_today > 0:
        lines.append(f"  - {errors_today} error(s) logged today — review before tomorrow")

    if not lines:
        return "**Open Loops**: None — clean close today"

    return "**Open Loops**:\n" + "\n".join(lines)


# Module-level MetricsAggregator reference for the retro source function.
# Set via RetroService.set_metrics_aggregator() during wiring.
_metrics_aggregator = None


@register_source("Zone 4 Activity")
def _zone4_activity(conn: sqlite3.Connection) -> str | None:
    """Summarize Zone 4 department activity from MetricsAggregator."""
    if _metrics_aggregator is None:
        return None

    try:
        from datetime import date as _date

        today = _date.today().isoformat()
        daily_entries = _metrics_aggregator.daily_cost(start_date=today, end_date=today)

        if not daily_entries:
            return "**Zone 4 Activity**: No department activity today"

        entry = daily_entries[0]
        lines = [
            f"**Zone 4 Activity**: {entry.session_count} session(s), "
            f"{entry.total_calls} tool calls, ${entry.total_usd:.4f}",
        ]

        utils = _metrics_aggregator.agent_utilization()
        # Show top 3 agents by cost for the retro summary
        if utils:
            top = utils[:3]
            dept_parts = [f"{u.agent_name} (${u.total_usd:.4f})" for u in top]
            lines.append(f"  Top: {', '.join(dept_parts)}")

        return "\n".join(lines)
    except Exception as e:
        log.warning("Zone 4 activity retro source failed: %s", e)
        return None


@register_source("Tomorrow Preview")
def _tomorrow_preview(conn: sqlite3.Connection) -> str | None:
    """Highlight goals due tomorrow and early warning items."""
    now = datetime.now()
    tomorrow_end = now + timedelta(hours=36)

    rows = conn.execute(
        """SELECT key, value FROM knowledge
           WHERE key LIKE 'goal:%'
           AND (archived IS NULL OR archived = 0)"""
    ).fetchall()

    due_tomorrow = []
    for row in rows:
        try:
            data = json.loads(row[1])
            desc = data.get("description", row[0])
            deadline_str = data.get("deadline")
            if deadline_str:
                deadline = datetime.fromisoformat(deadline_str)
                if now < deadline <= tomorrow_end:
                    due_tomorrow.append(f"  - {desc} (due {deadline.strftime('%b %d %-I:%M %p')})")
        except (json.JSONDecodeError, ValueError):
            pass

    if not due_tomorrow:
        return None

    lines = [f"**Tomorrow's Deadlines** ({len(due_tomorrow)})"]
    lines.extend(due_tomorrow)
    return "\n".join(lines)


def _strategy_flag_enabled() -> bool:
    """Return True when ZONE2_RETRO_VIA_STRATEGY env-var is truthy."""
    val = os.environ.get(_FLAG_ENV, "").strip().lower()
    return val in {"1", "true", "yes", "on"}


class RetroService(ServiceBase):
    """End-of-day retrospective service."""

    def __init__(
        self,
        data_dir: str | Path,
        db_path: str | Path,
        chat_id: str,
        *,
        event_callback=None,
        delivery_hour: int = 18,
        delivery_minute: int = 0,
        dispatch_adapter=None,
    ) -> None:
        super().__init__(data_dir, event_callback=event_callback)
        self.db_path = Path(db_path)
        self.chat_id = chat_id
        self.delivery_hour = delivery_hour
        self.delivery_minute = delivery_minute
        # Optional ServiceDispatchAdapter (S3.2). If None, Strategy routing
        # is never attempted even when the flag is on.
        self._dispatch_adapter = dispatch_adapter

    def should_run(self) -> bool:
        """Check if retro should be sent (time window + once-per-day dedup)."""
        now = datetime.now()

        target_minutes = self.delivery_hour * 60 + self.delivery_minute
        current_minutes = now.hour * 60 + now.minute
        if abs(current_minutes - target_minutes) > 30:
            return False

        state = self.load_state(filename="retro-state.json")
        last_retro = state.get("last_retro_date")
        today = now.strftime("%Y-%m-%d")
        if last_retro == today:
            return False

        return True

    def compile(self) -> str:
        """Compile the retro from all registered sources."""
        sections = []

        try:
            conn = sqlite3.connect(str(self.db_path))
            conn.row_factory = sqlite3.Row

            for name, source_fn in _SOURCES:
                try:
                    result = source_fn(conn)
                    if result:
                        sections.append(result)
                except Exception as e:
                    log.warning("Retro source '%s' failed: %s", name, e)

            conn.close()
        except Exception as e:
            log.error("Failed to compile retro: %s", e)
            return "EOD retro: couldn't compile data."

        if not sections:
            return f"EOD wrap for {datetime.now().strftime('%A, %B %d')} — nothing notable to report."

        header = f"**EOD Retro — {datetime.now().strftime('%A, %B %d')}**\n"
        return header + "\n\n".join(sections)

    async def _compose_via_strategy(
        self,
        raw_blocks: str,
        deps,
    ) -> tuple[str, float]:
        """Route compiled blocks through Strategy Z4 department.

        Returns (narrative_text, cost_usd). Falls back to raw_blocks on any
        error or if cost cap is exceeded.
        """
        if self._dispatch_adapter is None:
            return raw_blocks, 0.0

        date_str = datetime.now().strftime("%A, %B %d")
        task = (
            f"You are composing the end-of-day retrospective memo for {date_str}. "
            "Transform the following data blocks into a single cohesive narrative memo "
            "suitable for a Discord message. Be concise, specific, and actionable. "
            "Do not exceed 1500 characters.\n\n"
            f"--- RAW DATA ---\n{raw_blocks}\n--- END ---"
        )

        result = await self._dispatch_adapter.synthesize(
            department="strategy",
            task=task,
            deps=deps,
        )

        if not result.success:
            log.warning(
                "retro.strategy_synthesis_failed error=%s cost=%.4f",
                result.error, result.cost_usd,
            )
            return raw_blocks, result.cost_usd

        if result.cost_usd > _STRATEGY_COST_CAP_USD:
            log.warning(
                "retro.strategy_cost_cap_exceeded cost=%.4f cap=%.2f — falling back",
                result.cost_usd, _STRATEGY_COST_CAP_USD,
            )
            return raw_blocks, result.cost_usd

        return result.manager_output or raw_blocks, result.cost_usd

    def run(self) -> "ServiceResult":
        """Execute the retro (Z2-S0.1 + S3.2).

        When ZONE2_RETRO_VIA_STRATEGY=true AND a dispatch_adapter is wired,
        the compiled blocks are synthesised by the Strategy department.
        Otherwise falls back to the pre-sprint direct-render path.
        """
        import asyncio
        import time as _time

        from bridge.services.result import ServiceResult

        _start = _time.monotonic()

        if not self.should_run():
            return ServiceResult(
                service="retro",
                ok=True,
                work_items=0,
                duration_ms=int((_time.monotonic() - _start) * 1000),
                cost_usd=0.0,
                skip_reason="outside_window_or_already_sent",
            )

        try:
            raw_message = self.compile()
            cost_usd = 0.0
            strategy_used = False

            # S3.2 Pattern B — optional Strategy synthesis
            if _strategy_flag_enabled() and self._dispatch_adapter is not None:
                try:
                    # Build minimal BridgeDeps stub for standalone service run
                    from teams._types import BridgeDeps
                    import uuid as _uuid

                    deps = BridgeDeps(
                        session_id=_uuid.uuid4().hex[:16],
                        department="strategy",
                        operator_id="",
                        memory_store=None,
                        event_bus=None,
                        trust_manager=None,
                        cost_tracker=None,
                        knowledge_search=None,
                        cost_limit_usd=_STRATEGY_COST_CAP_USD,
                    )
                    message, cost_usd = asyncio.run(
                        self._compose_via_strategy(raw_message, deps)
                    )
                    strategy_used = message != raw_message
                except Exception as exc:
                    log.warning("retro.strategy_path_error: %s — using direct render", exc)
                    message = raw_message
            else:
                message = raw_message

            self.deliver_message(self.chat_id, message, source="retro")

            state = self.load_state(filename="retro-state.json")
            state["last_retro_date"] = datetime.now().strftime("%Y-%m-%d")
            self.save_state(state, filename="retro-state.json")

            duration_ms = int((_time.monotonic() - _start) * 1000)
            self.record_success(duration_ms, filename="retro-state.json")

            log.info(
                "EOD retro sent chars=%d duration_ms=%d strategy=%s cost=%.4f",
                len(message), duration_ms, strategy_used, cost_usd,
            )

            # Narration for S4.3 narration contract
            date_label = datetime.now().strftime("%b %d")
            narration = (
                f"EOD retro for {date_label} — "
                + ("Strategy-synthesised narrative" if strategy_used else "direct render")
                + f", {len(message)} chars"
                + (f", ${cost_usd:.4f}" if cost_usd else "")
            )

            return ServiceResult(
                service="retro",
                ok=True,
                work_items=1,
                duration_ms=duration_ms,
                cost_usd=cost_usd,
                narration=narration,
            )

        except Exception as e:
            duration_ms = int((_time.monotonic() - _start) * 1000)
            self.record_failure(str(e)[:500], filename="retro-state.json")
            log.error("EOD retro failed after %dms: %s", duration_ms, e)
            raise

    @staticmethod
    def set_metrics_aggregator(aggregator) -> None:
        """Wire a MetricsAggregator into the module-level reference for the retro source."""
        global _metrics_aggregator
        _metrics_aggregator = aggregator

    @staticmethod
    def get_sources() -> list[str]:
        return [name for name, _ in _SOURCES]
