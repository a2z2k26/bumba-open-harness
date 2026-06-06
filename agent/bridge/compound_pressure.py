"""Compound pressure detection — triggers auto-compact when both
budget and context pressure are elevated simultaneously.

D7.5 finding F-1c: operator wants the auto-compact trigger at 75% context
fill (today's threshold is more conservative). D7.8 (#1420) retunes the
threshold + adds a daily-log entry + Discord one-line notify on every
auto-compact firing so the operator can correlate compaction with quality
shifts.

Integration:
    - app.py Stage 1: call should_auto_compact() with both signals
    - EventBus: publish 'compaction.recommended' when triggered
"""
from __future__ import annotations

# Pressure levels that count as "stressed"
_BUDGET_STRESSED = frozenset({"warning", "critical", "exceeded"})
_CONTEXT_STRESSED = frozenset({"warn", "compact_now", "critical"})


def should_auto_compact(
    budget_level: str,
    context_recommendation: str,
) -> bool:
    """Return True if both budget and context pressure are elevated.

    Both signals must be stressed — either alone is not sufficient.
    This prevents unnecessary compaction when only one dimension is high.
    """
    return (
        budget_level in _BUDGET_STRESSED
        and context_recommendation in _CONTEXT_STRESSED
    )
