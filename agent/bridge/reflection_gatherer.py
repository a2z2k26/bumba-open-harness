"""Sprint 05.07 — real-metric gatherer for the weekly reflection loop.

Replaces the hardcoded placeholder achievements (
"Weekly reflection cycle started — system is learning") that the previous
``reflection_loop`` wrote every cycle with values aggregated from live data
sources: cost_tracker, routing_feedback, memory (knowledge/conversation
counts pre-resolved by the async caller), few_shot, and event_bus.

Each source read is wrapped in try/except — a single failing source records
"<name> unavailable" in ``WeekData.notes`` and never crashes the loop.
Empty sources produce explicit "no data" markers, never the old placeholder.

Design notes
------------
* ``gather_week_data`` is intentionally synchronous so the async
  ``reflection_loop`` can call it directly. Async-only sources (Memory's
  knowledge/conversation counts) are pre-resolved by the caller and passed
  in via ``GatherDeps.knowledge_count`` / ``conversation_count``.
* ``WeekData`` is a frozen dataclass; ``achievements``/``notes`` are tuples
  rather than lists so the result is immutable end-to-end.
* The shape is decoupled from ``reflection.WeekData`` (which models
  in-context inputs to the LLM-driven reflection generator). This module
  only models the values we surface in the weekly reflection record.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Model tiers we attempt to summarize. We sample one task_type per tier
# because routing_feedback's public surface only exposes per-(tier,task)
# performance — there is no aggregate accessor. "general" is the fallback
# task_type used by classify_task_type when no other category matches.
_KNOWN_MODEL_TIERS = ("haiku", "sonnet", "opus")
_DEFAULT_TASK_TYPE = "general"

# Event types whose names contain one of these substrings count as
# "error events" for the weekly summary. event_bus.Event has no severity
# field; the convention across the codebase is to encode severity in the
# event_type (e.g. "department.task.failed", "security.error").
_ERROR_EVENT_MARKERS = ("error", "fail", "crash")


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class GatherDeps:
    """Optional handles into live data sources.

    Every field is optional so unit tests (and an early-startup loop tick)
    can pass only the sources they care about.
    """

    cost_tracker: Any = None
    routing_feedback: Any = None
    few_shot_store: Any = None
    event_bus: Any = None
    knowledge_count: int | None = None
    conversation_count: int | None = None


@dataclass(frozen=True)
class WeekData:
    """Aggregated weekly metrics surfaced in the reflection record."""

    weekly_cost_usd: float | None = None
    # Tuple-of-tuples to remain immutable; convertible to dict at the call site.
    model_success_rates: tuple[tuple[str, float], ...] = ()
    knowledge_count: int = 0
    conversation_count: int = 0
    few_shot_example_count: int = 0
    few_shot_avg_quality: float | None = None
    error_event_count: int = 0
    achievements: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def gather_week_data(deps: GatherDeps) -> WeekData:
    """Build a WeekData from live sources, isolating each source's failures.

    Returns a frozen ``WeekData`` whose ``achievements`` reflect what was
    actually observed, and whose ``notes`` records which sources were
    unavailable or raised on read.
    """
    achievements: list[str] = []
    notes: list[str] = []

    weekly_cost_usd = _read_weekly_cost(deps, achievements, notes)
    model_success_rates = _read_model_rates(deps, achievements, notes)
    knowledge_count, conversation_count = _read_memory_counts(
        deps, achievements, notes
    )
    few_shot_count, few_shot_quality = _read_few_shot(deps, achievements, notes)
    error_count = _read_error_event_count(deps, achievements, notes)

    return WeekData(
        weekly_cost_usd=weekly_cost_usd,
        model_success_rates=tuple(model_success_rates),
        knowledge_count=knowledge_count,
        conversation_count=conversation_count,
        few_shot_example_count=few_shot_count,
        few_shot_avg_quality=few_shot_quality,
        error_event_count=error_count,
        achievements=tuple(achievements),
        notes=tuple(notes),
    )


# ---------------------------------------------------------------------------
# Per-source readers — each isolates its own failures
# ---------------------------------------------------------------------------


def _read_weekly_cost(
    deps: GatherDeps, achievements: list[str], notes: list[str]
) -> float | None:
    if deps.cost_tracker is None:
        notes.append("cost_tracker unavailable (not wired)")
        achievements.append("Cost tracking: no data this week")
        return None
    try:
        summary = deps.cost_tracker.get_weekly_summary()
        total = float(summary.get("total_cost", 0.0))
    except Exception as exc:
        logger.warning("reflection_gatherer: cost_tracker read failed: %s", exc)
        notes.append(f"cost_tracker unavailable ({type(exc).__name__})")
        achievements.append("Cost tracking: read error")
        return None

    if total <= 0.0:
        achievements.append("Cost tracking: no data this week ($0.00)")
        return total
    achievements.append(f"Weekly spend: ${total:.2f}")
    return total


def _read_model_rates(
    deps: GatherDeps, achievements: list[str], notes: list[str]
) -> list[tuple[str, float]]:
    if deps.routing_feedback is None:
        notes.append("routing_feedback unavailable (not wired)")
        return []
    rates: list[tuple[str, float]] = []
    sampled = 0
    try:
        for tier in _KNOWN_MODEL_TIERS:
            perf = deps.routing_feedback.get_model_performance(
                tier, _DEFAULT_TASK_TYPE
            )
            attempts = int(getattr(perf, "attempts", 0))
            success_rate = float(getattr(perf, "success_rate", 1.0))
            if attempts <= 0:
                continue
            rates.append((tier, success_rate))
            sampled += 1
    except Exception as exc:
        logger.warning(
            "reflection_gatherer: routing_feedback read failed: %s", exc
        )
        notes.append(f"routing_feedback unavailable ({type(exc).__name__})")
        return []

    if not rates:
        achievements.append("Routing health: no model attempts this week")
        return []
    pretty = ", ".join(f"{tier}={rate:.0%}" for tier, rate in rates)
    achievements.append(f"Model success rates ({sampled} tier{'s' if sampled != 1 else ''}): {pretty}")
    return rates


def _read_memory_counts(
    deps: GatherDeps, achievements: list[str], notes: list[str]
) -> tuple[int, int]:
    knowledge_count = deps.knowledge_count if deps.knowledge_count is not None else 0
    conversation_count = (
        deps.conversation_count if deps.conversation_count is not None else 0
    )
    if deps.knowledge_count is None and deps.conversation_count is None:
        notes.append("memory counts unavailable (not pre-resolved)")
    if knowledge_count <= 0:
        achievements.append("Memory: no data — 0 knowledge entries this week")
    else:
        achievements.append(f"Memory: {knowledge_count} knowledge entries on file")
    if conversation_count > 0:
        achievements.append(
            f"Memory: {conversation_count} conversation messages logged"
        )
    return knowledge_count, conversation_count


def _read_few_shot(
    deps: GatherDeps, achievements: list[str], notes: list[str]
) -> tuple[int, float | None]:
    if deps.few_shot_store is None:
        notes.append("few_shot_store unavailable (not wired)")
        achievements.append("Few-shot examples: no data")
        return 0, None
    try:
        count = int(deps.few_shot_store.count())
    except Exception as exc:
        logger.warning("reflection_gatherer: few_shot count failed: %s", exc)
        notes.append(f"few_shot_store unavailable ({type(exc).__name__})")
        return 0, None

    avg_quality: float | None = None
    if count > 0:
        try:
            examples = deps.few_shot_store.list_all(limit=count)
            scores = [
                float(getattr(e, "quality_score", 0.0))
                for e in examples
                if getattr(e, "quality_score", None) is not None
            ]
            if scores:
                avg_quality = sum(scores) / len(scores)
        except Exception as exc:
            logger.warning(
                "reflection_gatherer: few_shot list_all failed: %s", exc
            )
            notes.append(
                f"few_shot_store quality read failed ({type(exc).__name__})"
            )

    if count <= 0:
        achievements.append("Few-shot examples: no data this week")
    elif avg_quality is None:
        achievements.append(f"Few-shot examples: {count} stored (quality unknown)")
    else:
        achievements.append(
            f"Few-shot examples: {count} stored, avg quality {avg_quality:.2f}"
        )
    return count, avg_quality


def _read_error_event_count(
    deps: GatherDeps, achievements: list[str], notes: list[str]
) -> int:
    if deps.event_bus is None:
        notes.append("event_bus unavailable (not wired)")
        return 0
    try:
        data_dir = getattr(deps.event_bus, "_data_dir", None)
        if data_dir is None:
            notes.append("event_bus has no _data_dir; skipping events.jsonl scan")
            return 0
        events_dir = Path(data_dir) / "events"
        if not events_dir.exists():
            return 0  # no events written yet — not a failure
        cutoff = datetime.now(timezone.utc) - timedelta(days=7)
        count = 0
        for jsonl_path in sorted(events_dir.glob("*.jsonl")):
            for line in jsonl_path.read_text().splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                event_type = str(record.get("event_type", "")).lower()
                if not any(marker in event_type for marker in _ERROR_EVENT_MARKERS):
                    continue
                ts_raw = record.get("timestamp", "")
                try:
                    ts = datetime.fromisoformat(ts_raw)
                except (TypeError, ValueError):
                    continue
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
                if ts >= cutoff:
                    count += 1
    except Exception as exc:
        logger.warning(
            "reflection_gatherer: event_bus scan failed: %s", exc
        )
        notes.append(f"event_bus unavailable ({type(exc).__name__})")
        return 0

    if count > 0:
        achievements.append(f"Error events (7d): {count}")
    return count
