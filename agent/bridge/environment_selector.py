"""Execution environment selection with anti-default-gravity tracking."""

from __future__ import annotations

import logging
from collections import deque
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from bridge.work_order import Environment

if TYPE_CHECKING:
    from bridge.work_order import WorkOrder

# ---------------------------------------------------------------------------
# Task-class × environment matrix (S02d).
#
# Task classes:
#   "readonly"   — chat, queries, searches, summaries (no filesystem writes)
#   "filesystem" — code changes, fixes, refactors (need isolated worktree)
#   "department" — multi-agent orchestration (QA, strategy, board, etc.)
#
# Defaults per class:
#   readonly   → SUBAGENT   (cheap, fast, no isolation needed)
#   filesystem → WORKTREE   (git-isolated write access)
#   department → DEPARTMENT (routes to Zone 4 team)
# ---------------------------------------------------------------------------

_CLASS_DEFAULT_ENV: dict[str, Environment] = {
    "readonly": Environment.SUBAGENT,
    "filesystem": Environment.WORKTREE,
    "department": Environment.DEPARTMENT,
}

# Sprint 03.07 — per-class fallback ordering used when force_alternative=True
# AND the default env triggers a skew warning. The first entry is the default
# (matches _CLASS_DEFAULT_ENV); subsequent entries are alternatives in
# preference order. ``select()`` walks this list to find the first env that
# is NOT itself in the current skew report; if none qualifies it falls back
# to the second-listed entry. Department has no useful alternative — the
# DEPARTMENT route is required by the multi-agent contract — so its list is
# a single entry and force_alternative becomes a no-op for that class.
_CLASS_FALLBACK_ORDER: dict[str, tuple[Environment, ...]] = {
    "readonly": (Environment.SUBAGENT, Environment.WORKTREE, Environment.TMUX),
    "filesystem": (Environment.WORKTREE, Environment.TMUX, Environment.E2B),
    "department": (Environment.DEPARTMENT,),
}

# Skill prefix/keyword → task class.
# First match wins; order matters (more-specific first).
_SKILL_CLASS_RULES: list[tuple[str, str]] = [
    # Department patterns
    ("board", "department"),
    ("qa-", "department"),
    ("qa_", "department"),
    ("strategy", "department"),
    ("design", "department"),
    ("ops-", "department"),
    ("dept", "department"),
    # Filesystem patterns (code modification)
    ("ship-feature", "filesystem"),
    ("ship_feature", "filesystem"),
    ("fix-test", "filesystem"),
    ("fix_test", "filesystem"),
    ("fix-", "filesystem"),
    ("refactor", "filesystem"),
    ("migrate", "filesystem"),
    ("implement", "filesystem"),
    ("scaffold", "filesystem"),
    # Readonly patterns
    ("chat", "readonly"),
    ("query", "readonly"),
    ("search", "readonly"),
    ("summarize", "readonly"),
    ("review", "readonly"),
    ("analyze", "readonly"),
    ("explain", "readonly"),
]


def _classify_skill(skill: str) -> str:
    """Return the task class for a skill name.

    Falls back to 'readonly' (→ SUBAGENT) for unknown skills.
    """
    s = skill.lower()
    for prefix, klass in _SKILL_CLASS_RULES:
        if s.startswith(prefix) or prefix in s:
            return klass
    return "readonly"


def _derive_department(skill: str) -> str | None:
    """Return the department name a department-class skill belongs to, or None.

    Sprint 03.04 — single source of truth for the
    skill→``WorkOrder.department_target`` mapping used at the 3 production
    creation sites (``app.py`` dispatcher, ``api_server.py`` ingestion,
    ``commands.py`` ``/dispatch``).  Reads the SAME ``_SKILL_CLASS_RULES``
    table that ``_classify_skill`` reads, so the two cannot drift: any
    skill classified as ``"department"`` is guaranteed to derive a
    non-None department name, and vice versa.

    The returned value is the prefix's category name normalised to a bare
    department identifier (``"board"``, ``"qa"``, ``"strategy"``,
    ``"design"``, ``"ops"``, ``"dept"``).  Department-classed rules in
    the table use the prefix itself as the department identifier — the
    Zone 4 registry is keyed on these same names — so we strip any
    trailing ``-`` or ``_`` separators that exist purely to match
    ``startswith`` patterns (e.g. ``"qa-"`` and ``"qa_"`` both → ``"qa"``,
    ``"ops-"`` → ``"ops"``).

    Returns None for filesystem-class, readonly-class, and unknown skills.
    """
    s = skill.lower()
    for prefix, klass in _SKILL_CLASS_RULES:
        if s.startswith(prefix) or prefix in s:
            if klass != "department":
                return None
            return prefix.rstrip("-_")
    return None

log = logging.getLogger(__name__)

DEFAULT_WINDOW_SIZE = 20
DEFAULT_SKEW_THRESHOLD = 0.6


# Sprint S2.3 (Backend Operability, issue #2280) — route-selection guard.
#
# A central predicate that answers: is an executor route currently safe to
# auto-select for dispatch? Read by both the dispatcher (to reject explicit
# assignments) and the environment selector (to skip non-routable fallbacks).
#
# An executor status of ``stub`` means the class is registered but its
# ``execute()`` raises ``NotImplementedError``; ``unknown`` (used as the
# defensive default when a status lookup misses) is also non-routable.
# ``conditional_unwired`` means the executor's optional dependency
# (e.g. tmux_manager) was not provided at construction — also non-routable.
_ROUTABLE_STATUSES: frozenset[str] = frozenset(
    {"active", "active_low_traffic", "conditional_active"}
)


def is_environment_routable(status: str) -> bool:
    """Return True when ``status`` permits automatic dispatch.

    See ``Dispatcher.get_executor_statuses`` for the status taxonomy. The
    canonical roadmap lives at ``docs/architecture/executor-roadmap.md``.
    """
    return status in _ROUTABLE_STATUSES


@dataclass(frozen=True)
class EnvironmentUsageStats:
    total: int = 0
    distribution: dict[Environment, int] = field(default_factory=dict)


class EnvironmentSelector:
    def __init__(
        self,
        *,
        window_size: int = DEFAULT_WINDOW_SIZE,
        skew_threshold: float = DEFAULT_SKEW_THRESHOLD,
        force_alternative: bool = False,
    ) -> None:
        self._window_size = window_size
        self._skew_threshold = skew_threshold
        # Sprint 03.07 — opt-in auto-rebalancing. When True, select() will
        # pick the second-highest-scoring env instead of the default whenever
        # the default would trigger a skew warning. Default False preserves
        # historical behaviour: skew is observable but never auto-corrected.
        self._force_alternative = force_alternative
        self._history: deque[Environment] = deque(maxlen=window_size)

    def record_usage(self, env: Environment) -> None:
        self._history.append(env)

    def get_stats(self) -> EnvironmentUsageStats:
        dist: dict[Environment, int] = {}
        for env in self._history:
            dist[env] = dist.get(env, 0) + 1
        return EnvironmentUsageStats(total=len(self._history), distribution=dist)

    def is_skewed(self) -> bool:
        if len(self._history) < 5:
            return False
        total = len(self._history)
        for env in Environment:
            count = sum(1 for e in self._history if e == env)
            if count / total > self._skew_threshold:
                return True
        return False

    def get_skew_report(self) -> dict[Environment, float]:
        if len(self._history) < 5:
            return {}
        total = len(self._history)
        report: dict[Environment, float] = {}
        for env in Environment:
            count = sum(1 for e in self._history if e == env)
            pct = count / total
            if pct > self._skew_threshold:
                report[env] = pct
        return report

    def select(
        self,
        wo: "WorkOrder",
        *,
        executor_statuses: dict[str, str] | None = None,
    ) -> tuple[Environment, str]:
        """Select execution environment for a WorkOrder.

        Uses the task-class × environment matrix to choose the default
        environment for the WorkOrder's skill.  Does NOT call
        ``record_usage`` — the caller is responsible for recording after
        dispatch so that the usage history reflects actual dispatch outcomes.

        Sprint 03.07 — when ``force_alternative=True`` was passed at
        construction AND the default env triggers a skew warning, this
        method returns the second-highest-scoring env from
        ``_CLASS_FALLBACK_ORDER`` instead, with a rationale flagging the
        rebalance. When ``force_alternative=False`` (the default) the
        behaviour is unchanged from today: the class default is always
        returned regardless of skew.

        Sprint S2.3 (#2280) — ``executor_statuses`` is an optional
        ``{route_value: status}`` map (see ``Dispatcher.get_executor_statuses``).
        When provided, any non-routable env (status not in
        ``_ROUTABLE_STATUSES``) is skipped when walking the fallback order
        so automatic selection never returns a stubbed executor. The
        per-class default is itself bypassed if it is non-routable. When
        ``executor_statuses`` is None the historical behaviour is
        preserved exactly.

        Returns:
            (env, rationale) — the chosen environment and a short string
            explaining why.
        """
        klass = _classify_skill(wo.skill)
        default = _CLASS_DEFAULT_ENV[klass]
        rationale = f"{klass}-default: {default.value}"

        # Sprint S2.3 — if a status map was supplied AND the per-class
        # default is non-routable, jump straight to the fallback walk so
        # we never return a stubbed env. We still report the substitution
        # in the rationale so observers see why the default was bypassed.
        default_unroutable = (
            executor_statuses is not None
            and not is_environment_routable(
                executor_statuses.get(default.value, "unknown")
            )
        )

        if default_unroutable:
            fallback_order = _CLASS_FALLBACK_ORDER.get(klass, (default,))
            for candidate in fallback_order:
                if candidate is default:
                    continue
                status = executor_statuses.get(candidate.value, "unknown")
                if not is_environment_routable(status):
                    continue
                routable_rationale = (
                    f"{klass}-default ({default.value}) not routable "
                    f"(status={executor_statuses.get(default.value, 'unknown')}); "
                    f"falling back to {candidate.value}"
                )
                return candidate, routable_rationale
            # No routable alternative; surface the default plus a note so
            # the caller can decide whether to reject downstream. We never
            # silently return a routable env that the caller didn't pick.
            unroutable_rationale = (
                f"{klass}-default ({default.value}) not routable "
                f"(status={executor_statuses.get(default.value, 'unknown')}) "
                f"and no routable alternative; returning default"
            )
            return default, unroutable_rationale

        if not self._force_alternative:
            return default, rationale

        # force_alternative=True — only rebalance if the default is in the
        # current skew report. validate_selection returns None when there
        # is no skew (or when this env is not the over-indexed one), in
        # which case we keep the default.
        warning = self.validate_selection(default, rationale)
        if warning is None:
            return default, rationale

        # Walk the per-class fallback order, skipping the default, any env
        # that itself appears in the current skew report, and (S2.3) any
        # env whose status is non-routable. Fall back to the second listed
        # env if every alternative is also skewed (e.g. the report flags
        # multiple envs simultaneously) or to the default if the class
        # has no usable alternative (department).
        skew = self.get_skew_report()
        fallback_order = _CLASS_FALLBACK_ORDER.get(klass, (default,))
        if len(fallback_order) <= 1:
            return default, rationale

        chosen: Environment | None = None
        for candidate in fallback_order:
            if candidate is default:
                continue
            if candidate in skew:
                continue
            if executor_statuses is not None:
                status = executor_statuses.get(candidate.value, "unknown")
                if not is_environment_routable(status):
                    continue
            chosen = candidate
            break
        if chosen is None:
            chosen = fallback_order[1]

        forced_rationale = (
            f"force_alternative triggered: original was skewed "
            f"({default.value} → {chosen.value}); class={klass}"
        )
        return chosen, forced_rationale

    def validate_selection(self, env: Environment, rationale: str) -> str | None:
        if not self.is_skewed():
            return None
        skew = self.get_skew_report()
        if env in skew:
            pct = skew[env]
            # S08: emit skew counter
            try:
                from bridge.z3_metrics import record_env_selector_skew
                record_env_selector_skew(env.value)
            except ImportError:
                pass
            return (
                f"Over-indexing on {env.value}: {pct:.0%} of recent {len(self._history)} "
                f"selections. Consider whether {env.value} is truly the best fit, "
                f"or if another environment would serve this task better."
            )
        return None
