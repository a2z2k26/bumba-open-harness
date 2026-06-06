"""Determinism Spectrum observability per Sprint #1113 ADR (#1115).

This module exports per-tier counters for the 5-tier Determinism Spectrum
defined in ``docs/architecture/determinism-spectrum.md``. Modules annotate
themselves with a tier (0=Pure, 1=Table-driven, 2=Constrained-LLM,
3=Judged-LLM, 4=Full-autonomy) and call :func:`increment_module_counter`
on each invocation. The headline ratio
``z4.dispatch.deterministic_total / z4.dispatch.judged_total`` measures
how often we exercise deterministic vs judged paths.

The module is a thin wrapper over an in-process counter store. It is
designed to be safe to import from any tier (no I/O at import; counters
are O(1) increments under a single lock). The store is process-local
and not flushed to disk by this module — the existing ``bridge.metrics``
JSONL/SQLite infrastructure can read the snapshot when needed.

Two annotation styles are supported:

  - Direct call: ``increment_module_counter(module, tier=N, ...)`` at
    the top of a function. Use this when the function decides at runtime
    whether to record cost / parse_error / escalation.
  - Decorator: ``@record_invocation(module, tier=N)`` wraps a function
    so each call records once. For Tier 2/3/4 functions returning an
    object with ``.cost_usd``, the decorator auto-extracts cost.
    ``TypeError`` / ``ValueError`` raised inside the wrapped call
    increments the parse-error counter and re-raises.
"""
from __future__ import annotations

import threading
from collections import defaultdict
from dataclasses import dataclass, field
from functools import wraps
from typing import Any, Callable, Literal, Optional, TypeVar

# ── Tier vocabulary ──────────────────────────────────────────────────────

DeterminismTier = Literal[0, 1, 2, 3, 4]

DETERMINISTIC_TIERS: frozenset[int] = frozenset({0, 1})
JUDGED_TIERS: frozenset[int] = frozenset({2, 3, 4})

# ── Counter names (match ADR §7) ─────────────────────────────────────────

COUNTER_INVOCATION = "bridge.module.invocation_total"
COUNTER_DETERMINISTIC = "z4.dispatch.deterministic_total"
COUNTER_JUDGED = "z4.dispatch.judged_total"
COUNTER_COST = "bridge.module.cost_usd"
COUNTER_PARSE_ERROR = "bridge.module.parse_error_total"
COUNTER_TRUST = "bridge.module.trust_score"
COUNTER_ESCALATION = "bridge.module.escalation_total"


# ── In-process store ────────────────────────────────────────────────────

class _DispatchStore:
    """Thread-safe in-memory counter store for the determinism spectrum.

    Counters are keyed by ``(name, module)`` for per-module breakdown plus
    a separate ``(name, None)`` slot for unscoped totals. Cost is a float
    accumulator; trust_score is the most-recent gauge.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        # invocation, deterministic, judged, parse_error, escalation
        self._counts: dict[tuple[str, str], int] = defaultdict(int)
        # cost_usd accumulator
        self._cost: dict[str, float] = defaultdict(float)
        # trust_score is a gauge, latest-wins
        self._trust: dict[str, float] = {}
        # tier per module (last write wins; modules SHOULD be tier-stable)
        self._tier: dict[str, int] = {}

    def record(
        self,
        module: str,
        *,
        tier: int,
        cost_usd: float = 0.0,
        parse_error: bool = False,
        trust_score: Optional[float] = None,
        escalation: bool = False,
    ) -> None:
        if tier not in DETERMINISTIC_TIERS and tier not in JUDGED_TIERS:
            raise ValueError(
                f"determinism tier must be in 0..4, got {tier!r}"
            )
        with self._lock:
            self._tier[module] = tier
            self._counts[(COUNTER_INVOCATION, module)] += 1
            if tier in DETERMINISTIC_TIERS:
                self._counts[(COUNTER_DETERMINISTIC, module)] += 1
            else:
                self._counts[(COUNTER_JUDGED, module)] += 1
            if cost_usd:
                self._cost[module] += float(cost_usd)
            if parse_error:
                self._counts[(COUNTER_PARSE_ERROR, module)] += 1
            if trust_score is not None:
                self._trust[module] = float(trust_score)
            if escalation:
                self._counts[(COUNTER_ESCALATION, module)] += 1

    def snapshot(self) -> "DispatchSnapshot":
        with self._lock:
            modules = sorted(self._tier.keys())
            by_module: dict[str, dict[str, Any]] = {}
            deterministic_total = 0
            judged_total = 0
            for module in modules:
                tier = self._tier[module]
                invocations = self._counts.get((COUNTER_INVOCATION, module), 0)
                if tier in DETERMINISTIC_TIERS:
                    deterministic_total += invocations
                else:
                    judged_total += invocations
                by_module[module] = {
                    "tier": tier,
                    "invocations": invocations,
                    "cost_usd": round(self._cost.get(module, 0.0), 6),
                    "parse_errors": self._counts.get(
                        (COUNTER_PARSE_ERROR, module), 0
                    ),
                    "trust_score": self._trust.get(module),
                    "escalations": self._counts.get(
                        (COUNTER_ESCALATION, module), 0
                    ),
                }
            denom = deterministic_total + judged_total
            ratio = (deterministic_total / denom) if denom else 0.0
            return DispatchSnapshot(
                deterministic_total=deterministic_total,
                judged_total=judged_total,
                by_module=by_module,
                deterministic_ratio=ratio,
            )

    def reset(self) -> None:
        """Clear all counters. Test-only — production never resets."""
        with self._lock:
            self._counts.clear()
            self._cost.clear()
            self._trust.clear()
            self._tier.clear()


_STORE = _DispatchStore()


# ── Public snapshot dataclass ────────────────────────────────────────────


@dataclass(frozen=True)
class DispatchSnapshot:
    """Aggregate snapshot of determinism counters at a point in time."""

    deterministic_total: int
    judged_total: int
    by_module: dict[str, dict[str, Any]] = field(default_factory=dict)
    deterministic_ratio: float = 0.0


# ── Public API ──────────────────────────────────────────────────────────


def increment_module_counter(
    module: str,
    *,
    tier: DeterminismTier,
    cost_usd: float = 0.0,
    parse_error: bool = False,
    trust_score: Optional[float] = None,
    escalation: bool = False,
) -> None:
    """Record one module invocation.

    Always increments ``bridge.module.invocation_total`` and one of
    ``z4.dispatch.deterministic_total`` (tier 0/1) or
    ``z4.dispatch.judged_total`` (tier 2/3/4). Optional counters fire
    only when their kwargs are truthy.
    """
    _STORE.record(
        module,
        tier=int(tier),
        cost_usd=cost_usd,
        parse_error=parse_error,
        trust_score=trust_score,
        escalation=escalation,
    )


T = TypeVar("T")


def record_invocation(
    module: str,
    *,
    tier: DeterminismTier,
) -> Callable[[Callable[..., T]], Callable[..., T]]:
    """Decorator that records one invocation per call.

    For Tier 2/3/4 wrapped functions returning an object with a
    ``cost_usd`` attribute, the decorator auto-extracts the cost.
    ``TypeError`` / ``ValueError`` raised inside the wrapped call
    increments the parse-error counter and re-raises (the original
    exception propagates unchanged so callers see the same stack trace).

    Works on both sync and async functions.
    """
    tier_int = int(tier)
    is_judged = tier_int in JUDGED_TIERS

    def _decorator(fn: Callable[..., T]) -> Callable[..., T]:
        # Async path
        if _is_coroutine_function(fn):
            @wraps(fn)
            async def _async_wrapper(*args: Any, **kwargs: Any) -> Any:
                try:
                    result = await fn(*args, **kwargs)
                except (TypeError, ValueError):
                    increment_module_counter(
                        module, tier=tier, parse_error=True,
                    )
                    raise
                cost = _extract_cost(result) if is_judged else 0.0
                increment_module_counter(
                    module, tier=tier, cost_usd=cost,
                )
                return result
            return _async_wrapper  # type: ignore[return-value]

        # Sync path
        @wraps(fn)
        def _sync_wrapper(*args: Any, **kwargs: Any) -> Any:
            try:
                result = fn(*args, **kwargs)
            except (TypeError, ValueError):
                increment_module_counter(
                    module, tier=tier, parse_error=True,
                )
                raise
            cost = _extract_cost(result) if is_judged else 0.0
            increment_module_counter(
                module, tier=tier, cost_usd=cost,
            )
            return result
        return _sync_wrapper  # type: ignore[return-value]

    return _decorator


def snapshot() -> DispatchSnapshot:
    """Return a read-only snapshot of current counter state."""
    return _STORE.snapshot()


def reset_for_tests() -> None:
    """Clear all counters. Tests only — never call in production."""
    _STORE.reset()


def format_snapshot_for_discord(snap: DispatchSnapshot, *, top_n: int = 10) -> str:
    """Render a snapshot as a Discord-ready markdown block.

    Output sections: headline ratio, totals, top-N modules by invocation,
    aggregate escalation count.
    """
    lines: list[str] = ["**Determinism Spectrum — current counters**"]
    total = snap.deterministic_total + snap.judged_total
    if total == 0:
        lines.append("_No module invocations recorded yet._")
        return "\n".join(lines)

    pct = snap.deterministic_ratio * 100
    lines.append(
        f"Deterministic ratio: **{pct:.1f}%** "
        f"(deterministic={snap.deterministic_total}, "
        f"judged={snap.judged_total}, total={total})"
    )

    # Top N by invocation count
    top = sorted(
        snap.by_module.items(),
        key=lambda kv: kv[1].get("invocations", 0),
        reverse=True,
    )[:top_n]
    lines.append("")
    lines.append(f"**Top {len(top)} modules by invocation:**")
    lines.append("```")
    lines.append(f"{'tier':<5} {'invocations':>12} {'cost_usd':>10} {'errs':>5}  module")
    for module, data in top:
        lines.append(
            f"{data['tier']:<5} {data['invocations']:>12} "
            f"{data['cost_usd']:>10.4f} {data['parse_errors']:>5}  {module}"
        )
    lines.append("```")

    # Aggregate escalation count
    total_escalations = sum(
        d.get("escalations", 0) for d in snap.by_module.values()
    )
    lines.append(f"Escalations recorded: **{total_escalations}**")
    return "\n".join(lines)


# ── Helpers ──────────────────────────────────────────────────────────────


def _is_coroutine_function(fn: Callable[..., Any]) -> bool:
    import asyncio
    return asyncio.iscoroutinefunction(fn)


def _extract_cost(result: Any) -> float:
    """Best-effort extraction of ``cost_usd`` from a result object.

    Looks for ``cost_usd`` then ``total_cost_usd``. Returns 0.0 if
    neither is present or the value is not numeric.
    """
    for attr in ("cost_usd", "total_cost_usd"):
        v = getattr(result, attr, None)
        if v is None:
            continue
        try:
            return float(v)
        except (TypeError, ValueError):
            return 0.0
    return 0.0


__all__ = [
    "COUNTER_COST",
    "COUNTER_DETERMINISTIC",
    "COUNTER_ESCALATION",
    "COUNTER_INVOCATION",
    "COUNTER_JUDGED",
    "COUNTER_PARSE_ERROR",
    "COUNTER_TRUST",
    "DETERMINISTIC_TIERS",
    "DispatchSnapshot",
    "DeterminismTier",
    "JUDGED_TIERS",
    "format_snapshot_for_discord",
    "increment_module_counter",
    "record_invocation",
    "reset_for_tests",
    "snapshot",
]
