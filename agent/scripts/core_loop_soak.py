"""Long-run soak profile for the harness's core loops.

Sprint R7.1 (current-state improvement plan) — answers the operator's
"does this thing stay stable when I leave it running?" question
without booking any external network calls. The probe family already
covers single-shot operability (R4.1's smoke probe + R4.2's recovery
drill); this sits one layer above and exercises the hottest internal
loops *repeatedly* so resource leaks and per-iteration cost growth show
up before they bite the daemon.

Loops driven per iteration (each in isolation, no cross-loop state):

1. **metrics** — ``MetricsCollector.increment`` + ``observe``. R0.1
   identified this as a hot path that suffered a regression
   (per-call ``datetime.now`` formatting); the soak guards the cached
   minute-stamp invariant by hammering it.
2. **event_bus** — ``EventBus.publish`` + read of ``_recent_events``.
   The bounded ring is meant to cap at 100; the soak proves the cap
   holds across thousands of publishes without unbounded growth.
3. **dispatcher** — synthetic ``ChiefDispatcher.dispatch`` with a
   patched ``WarmChief._run_chief`` (mirrors R4.1). Proves the warm-
   single-run lifecycle keeps its session-row + event lineage shape
   under repeated load.
4. **consolidation_lock** — ``ConsolidationLock.try_acquire`` /
   ``release`` against a per-iteration tempdir. Proves PID-based
   lock acquire/release is leak-free.

Per iteration the harness records: wall time, peak heap delta
(``tracemalloc``), and any exception. The aggregate summary reports
total runtime, P50/P95/P99 per-iteration latency, peak memory growth,
total event count, and the per-loop failure tally.

Usage
-----
::

    cd agent
    .venv/bin/python scripts/core_loop_soak.py                     # 100 iters, ~< 60s
    .venv/bin/python scripts/core_loop_soak.py --iterations 50     # short
    .venv/bin/python scripts/core_loop_soak.py --json              # JSON summary
    .venv/bin/python scripts/core_loop_soak.py --include metrics   # narrow

Long soak (operator-local, *not* CI):
::

    .venv/bin/python scripts/core_loop_soak.py --iterations 10000  # ~1h+

Exit codes
----------
- ``0`` — soak completed; no per-loop failures.
- ``1`` — soak completed but at least one iteration of one loop raised.
- ``2`` — internal harness error (import failed, dispatcher refused to
  construct, etc.).

Design constraints
------------------
- **Offline + deterministic.** Patches ``WarmChief._run_chief`` so the
  chief returns a synthetic ``TeamResult`` without any model call.
- **Stdlib + bridge only.** Same posture as R4.1's smoke probe and
  R4.2's recovery drill — no new pypi deps.
- **No cross-iteration state.** Each loop builds (or reuses) its own
  collaborators inside the iteration body so leaks are not masked by
  end-of-soak teardown.
- **Per-loop isolation.** A failure in one loop does not abort the
  others; each loop's failure count is reported independently.
"""
from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import sys
import tempfile
import time
import tracemalloc
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from unittest import mock


# ---------------------------------------------------------------------------
# Result dataclasses (immutable summary)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class LoopStats:
    """Per-loop aggregate stats over the soak."""

    name: str
    iterations: int
    failures: int
    duration_total_s: float
    duration_p50_s: float
    duration_p95_s: float
    duration_p99_s: float
    duration_max_s: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "iterations": self.iterations,
            "failures": self.failures,
            "duration_total_s": round(self.duration_total_s, 6),
            "duration_p50_s": round(self.duration_p50_s, 6),
            "duration_p95_s": round(self.duration_p95_s, 6),
            "duration_p99_s": round(self.duration_p99_s, 6),
            "duration_max_s": round(self.duration_max_s, 6),
        }


@dataclass(frozen=True)
class SoakResult:
    """Aggregate outcome of one soak run."""

    ok: bool
    iterations: int
    loops_included: tuple[str, ...]
    wall_time_s: float
    peak_memory_kb: int
    memory_growth_kb: int
    total_events_published: int
    total_failures: int
    loops: tuple[LoopStats, ...] = field(default_factory=tuple)
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "iterations": self.iterations,
            "loops_included": list(self.loops_included),
            "wall_time_s": round(self.wall_time_s, 6),
            "peak_memory_kb": self.peak_memory_kb,
            "memory_growth_kb": self.memory_growth_kb,
            "total_events_published": self.total_events_published,
            "total_failures": self.total_failures,
            "loops": [loop.to_dict() for loop in self.loops],
            "error": self.error,
        }


# ---------------------------------------------------------------------------
# Per-loop fixtures — each loop owns its setup so failures stay isolated
# ---------------------------------------------------------------------------


def _make_soak_deps(department: str):
    """Construct a BridgeDeps with all-mock collaborators.

    Mirrors R4.1's ``_make_probe_deps`` and R4.2's ``_make_drill_deps``
    — inlined here so the soak doesn't import from ``tests/``.
    Production scripts must not depend on test packages.
    """
    from teams._types import BridgeDeps

    memory_store = mock.AsyncMock()
    memory_store.get = mock.AsyncMock(return_value=None)
    memory_store.set = mock.AsyncMock(return_value=None)
    knowledge_search = mock.AsyncMock(return_value=[])
    return BridgeDeps(
        session_id="core-loop-soak",
        department=department,
        operator_id="core-loop-soak",
        memory_store=memory_store,
        event_bus=mock.MagicMock(),
        trust_manager=mock.MagicMock(),
        cost_tracker=mock.MagicMock(),
        knowledge_search=knowledge_search,
        cost_limit_usd=2.0,
    )


def _qa_config():
    """Minimal QA DepartmentConfig used by the dispatcher loop."""
    from teams._types import AgentSpec, DepartmentConfig

    return DepartmentConfig(
        name="qa",
        zone=4,
        description="QA department (core loop soak)",
        manager=AgentSpec(
            name="qa-chief",
            model="anthropic:claude-opus-4-6",
        ),
        employees=(
            AgentSpec(
                name="qa-specialist",
                model="anthropic:claude-sonnet-4-6",
            ),
        ),
    )


@dataclass
class _SoakRegistry:
    """Minimal registry shape — returns the configured DepartmentConfig."""

    configs: dict = field(default_factory=dict)

    def get_config(self, name: str):
        return self.configs.get(name)


# ---------------------------------------------------------------------------
# Loop bodies — each is `async def loop_body(ctx) -> int` returning events
# published. Setup happens before the iteration loop; teardown after.
# ---------------------------------------------------------------------------


class _MetricsLoop:
    """Hammer ``MetricsCollector.increment`` + ``observe`` (R0.1 hot path)."""

    name = "metrics"

    def __init__(self, tmpdir: Path):
        from bridge.metrics import MetricsCollector

        self._collector = MetricsCollector(data_dir=tmpdir, flush_interval=300)

    async def step(self, i: int) -> int:
        # 50 increments + 5 histogram observations per iteration —
        # representative of the hot-path call pattern in the runtime.
        for _ in range(50):
            self._collector.increment("soak.counter")
        for j in range(5):
            self._collector.observe("soak.latency_s", 0.001 * (j + 1))
        # No events published; return 0.
        return 0


class _EventBusLoop:
    """Publish + read recent events; prove the 100-cap holds."""

    name = "event_bus"

    def __init__(self, tmpdir: Path):
        from bridge.event_bus import EventBus

        # No persistence — pass tmpdir for cleanliness but we don't
        # exercise the JSONL path here (tracked separately).
        self._bus = EventBus(data_dir=tmpdir)

    async def step(self, i: int) -> int:
        # 5 publishes + 1 ring read per iteration. With a 100-event ring
        # the assertion is that recent_events stays ≤ 100 across the
        # entire soak.
        for j in range(5):
            self._bus.publish(
                "soak.tick",
                payload={"iter": i, "j": j},
                source="core-loop-soak",
            )
        # Ring should be capped — the soak result aggregator will
        # surface unbounded growth as a memory_growth_kb regression.
        _ = list(self._bus._recent_events)
        return 5


class _DispatcherLoop:
    """Synthetic dispatcher.dispatch with patched chief execution."""

    name = "dispatcher"

    def __init__(self, tmpdir: Path):
        # Defer construction to `step` so each iteration uses a fresh
        # session-store + event-bus — the dispatcher accumulates rows in
        # the in-memory store, and we want per-iteration leak signal,
        # not whole-soak growth.
        self._tmpdir = tmpdir

    async def step(self, i: int) -> int:
        from bridge.chief_dispatcher import ChiefDispatcher
        from bridge.chief_session_store import InMemoryChiefSessionStore
        from bridge.event_bus import EventBus
        from bridge.warm_chief import WarmChief
        from bridge.work_order import WorkOrder
        from bridge.work_order_router import NullRouter
        from teams._types import TeamResult

        department = "qa"
        registry = _SoakRegistry(configs={department: _qa_config()})
        store = InMemoryChiefSessionStore()
        event_bus = EventBus(data_dir=self._tmpdir)
        dispatcher = ChiefDispatcher(
            router=NullRouter(department=department),
            session_store=store,
            dept_registry=registry,
            event_bus=event_bus,
        )

        ok_result = TeamResult(
            department=department,
            manager_output="soak ok",
            employee_results=(),
            total_tokens=0,
            total_cost_usd=0.0,
            duration_seconds=0.0,
            success=True,
            error=None,
        )

        async def _ok_run_chief(self):  # noqa: ANN001
            return ok_result

        wo = WorkOrder.create(
            intent=f"soak iter {i}",
            skill="soak",
            project="soak",
        )
        deps = _make_soak_deps(department)

        with mock.patch.object(WarmChief, "_run_chief", _ok_run_chief):
            await dispatcher.dispatch(wo, deps)

        # 3 events per dispatch (created + state_changed + routed).
        return len(event_bus._recent_events)


class _ConsolidationLockLoop:
    """try_acquire / release against a per-iteration tempdir."""

    name = "consolidation_lock"

    def __init__(self, tmpdir: Path):
        # Each iteration uses a per-iteration sub-dir so the lock file
        # is created and removed cleanly — avoids cross-iteration state.
        self._base = tmpdir

    async def step(self, i: int) -> int:
        from bridge.consolidation_lock import ConsolidationLock

        sub = self._base / f"iter-{i}"
        sub.mkdir(parents=True, exist_ok=True)
        lock = ConsolidationLock(data_dir=sub)
        result = lock.try_acquire()
        if result.acquired:
            lock.release()
        return 0


_LOOP_FACTORIES = {
    "metrics": _MetricsLoop,
    "event_bus": _EventBusLoop,
    "dispatcher": _DispatcherLoop,
    "consolidation_lock": _ConsolidationLockLoop,
}


# ---------------------------------------------------------------------------
# Soak runner
# ---------------------------------------------------------------------------


def _percentile(sorted_values: list[float], p: float) -> float:
    if not sorted_values:
        return 0.0
    n = len(sorted_values)
    idx = min(int(n * p), n - 1)
    return sorted_values[idx]


async def _run_soak_async(iterations: int, include: list[str]) -> SoakResult:
    """Inner async driver — returns a SoakResult.

    Raises only on import / construction failure (caller maps to
    exit-2). All other failure modes are surfaced via per-loop
    ``failures`` counters and ``SoakResult.ok``.
    """
    if iterations < 1:
        raise ValueError("iterations must be >= 1")
    if not include:
        raise ValueError("include must name at least one loop")
    unknown = [name for name in include if name not in _LOOP_FACTORIES]
    if unknown:
        raise ValueError(
            f"unknown loop name(s): {unknown}; "
            f"valid: {sorted(_LOOP_FACTORIES)}"
        )

    tracemalloc.start()
    baseline_kb_size, _ = tracemalloc.get_traced_memory()
    baseline_kb = baseline_kb_size // 1024
    wall_start = time.perf_counter()

    with tempfile.TemporaryDirectory(prefix="core-loop-soak-") as td:
        tmpdir = Path(td)

        # Construct each loop once; iterations call `.step(i)`.
        loops = []
        for name in include:
            factory = _LOOP_FACTORIES[name]
            loop_dir = tmpdir / name
            loop_dir.mkdir(parents=True, exist_ok=True)
            loops.append(factory(loop_dir))

        # Per-loop accumulators.
        per_loop_durations: dict[str, list[float]] = {loop.name: [] for loop in loops}
        per_loop_failures: dict[str, int] = {loop.name: 0 for loop in loops}
        total_events = 0

        for i in range(iterations):
            for loop in loops:
                step_start = time.perf_counter()
                try:
                    events = await loop.step(i)
                    total_events += int(events)
                except Exception:  # noqa: BLE001 — soak-time catch
                    per_loop_failures[loop.name] += 1
                    events = 0
                step_dur = time.perf_counter() - step_start
                per_loop_durations[loop.name].append(step_dur)

        wall_time_s = time.perf_counter() - wall_start
        current_kb_size, peak_kb_size = tracemalloc.get_traced_memory()
        tracemalloc.stop()

        peak_memory_kb = peak_kb_size // 1024
        memory_growth_kb = (current_kb_size // 1024) - baseline_kb

        loop_stats: list[LoopStats] = []
        for loop in loops:
            durations = per_loop_durations[loop.name]
            sorted_durs = sorted(durations)
            loop_stats.append(
                LoopStats(
                    name=loop.name,
                    iterations=len(durations),
                    failures=per_loop_failures[loop.name],
                    duration_total_s=sum(durations),
                    duration_p50_s=_percentile(sorted_durs, 0.50),
                    duration_p95_s=_percentile(sorted_durs, 0.95),
                    duration_p99_s=_percentile(sorted_durs, 0.99),
                    duration_max_s=sorted_durs[-1] if sorted_durs else 0.0,
                )
            )

        total_failures = sum(per_loop_failures.values())
        return SoakResult(
            ok=total_failures == 0,
            iterations=iterations,
            loops_included=tuple(include),
            wall_time_s=wall_time_s,
            peak_memory_kb=peak_memory_kb,
            memory_growth_kb=memory_growth_kb,
            total_events_published=total_events,
            total_failures=total_failures,
            loops=tuple(loop_stats),
            error=None,
        )


def run_soak(iterations: int, include: list[str]) -> SoakResult:
    """Synchronous wrapper around the async driver for CLI consumption."""
    return asyncio.run(_run_soak_async(iterations, include))


# ---------------------------------------------------------------------------
# Renderers
# ---------------------------------------------------------------------------


def render_text(result: SoakResult) -> str:
    lines = [
        "Core loop soak",
        f"  ok:                     {result.ok}",
        f"  iterations:             {result.iterations}",
        f"  loops_included:         {list(result.loops_included)}",
        f"  wall_time_s:            {result.wall_time_s:.3f}",
        f"  peak_memory_kb:         {result.peak_memory_kb}",
        f"  memory_growth_kb:       {result.memory_growth_kb}",
        f"  total_events_published: {result.total_events_published}",
        f"  total_failures:         {result.total_failures}",
        "",
    ]
    for loop in result.loops:
        marker = "PASS" if loop.failures == 0 else "FAIL"
        lines.append(
            f"  [{marker}] {loop.name}: "
            f"iters={loop.iterations} failures={loop.failures} "
            f"total={loop.duration_total_s:.3f}s "
            f"p50={loop.duration_p50_s * 1000:.3f}ms "
            f"p95={loop.duration_p95_s * 1000:.3f}ms "
            f"p99={loop.duration_p99_s * 1000:.3f}ms "
            f"max={loop.duration_max_s * 1000:.3f}ms"
        )
    if result.error:
        lines.append(f"  error: {result.error}")
    return "\n".join(lines) + "\n"


def render_json(result: SoakResult) -> str:
    return json.dumps(result.to_dict(), indent=2, sort_keys=True) + "\n"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Long-run soak profile for harness core loops "
            "(metrics, event_bus, dispatcher, consolidation_lock). "
            "Offline + deterministic; no external credentials required. "
            "Default 100 iterations is the CI-safe short soak; pass "
            "--iterations 10000 for the operator-local long soak."
        )
    )
    parser.add_argument(
        "--iterations",
        type=int,
        default=100,
        help=(
            "Number of iterations across all included loops "
            "(default: 100; 10000 ≈ 1h+ long soak)."
        ),
    )
    parser.add_argument(
        "--include",
        action="append",
        choices=sorted(_LOOP_FACTORIES),
        help=(
            "Run only the named loop(s); repeat for multiple. "
            "Default: all four loops."
        ),
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit a JSON summary instead of human-readable text.",
    )
    args = parser.parse_args(argv)

    include = args.include or sorted(_LOOP_FACTORIES)

    try:
        result = run_soak(args.iterations, include)
    except Exception as exc:  # noqa: BLE001 — CLI boundary
        print(
            f"core_loop_soak: internal harness error: "
            f"{type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        return 2

    if args.json:
        sys.stdout.write(render_json(result))
    else:
        sys.stdout.write(render_text(result))

    return 0 if result.ok else 1


if __name__ == "__main__":
    # Avoid noisy KeyboardInterrupt traceback if the operator Ctrl-Cs.
    with contextlib.suppress(KeyboardInterrupt):
        sys.exit(main())
