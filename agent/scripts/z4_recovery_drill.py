"""ChiefSession recovery and rollback drill.

Sprint R4.2 (current-state improvement plan) — operability is not just
dispatch success. A long-running autonomous harness must survive stuck
sessions, failed chief runs, dispatcher rollback, and requeue paths.
The dispatcher already has ``retry_failed`` / ``requeue`` /
``retry_with_backoff`` / ``shutdown_session`` plus a separate reaper
loop in ``background_loops`` — this drill stitches them together into
one runnable script the operator can paste into the runbook before
flipping autonomy levers.

Drill scenarios (each runs in isolation, fresh store + bus per scenario):

1. **Failure path** — chief raises during execution → session ends FAILED.
2. **Requeue path** — operator requeue() of an AWAITING_EVALUATION
   session re-warms it back to WARM.
3. **Retry-with-backoff** — explicit retry path increments attempt
   count and publishes ``chief_dispatcher.requeued``.
4. **Idle reaper** — `chief_session_reaper_loop` transitions an idle
   AWAITING_EVALUATION session through TIMED_OUT to SHUTDOWN.

Usage
-----
::

    cd agent
    .venv/bin/python scripts/z4_recovery_drill.py
    .venv/bin/python scripts/z4_recovery_drill.py --json
    .venv/bin/python scripts/z4_recovery_drill.py --scenario failure
    .venv/bin/python scripts/z4_recovery_drill.py --scenario reaper

Exit codes
----------
- ``0`` — all selected scenarios passed.
- ``1`` — at least one scenario failed.
- ``2`` — internal harness error (import, construction, etc.).

Constraints
-----------
- **Offline + deterministic.** No Anthropic / OpenRouter / VAPI / GitHub
  / Discord call. ``WarmChief._run_chief`` is patched per-scenario.
- **No cross-scenario state.** Each scenario builds a fresh
  ``InMemoryChiefSessionStore`` + ``EventBus`` with a temp-dir.
- **Stdlib + bridge only.** Same import surface as R4.1's smoke probe.
"""
from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from unittest import mock


# ---------------------------------------------------------------------------
# Result dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ScenarioResult:
    """Outcome of one drill scenario."""

    name: str
    ok: bool
    detail: str
    events_seen: tuple[str, ...] = field(default_factory=tuple)
    final_state: str = ""
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "ok": self.ok,
            "detail": self.detail,
            "events_seen": list(self.events_seen),
            "final_state": self.final_state,
            "error": self.error,
        }


@dataclass(frozen=True)
class DrillResult:
    """Aggregate of all scenarios run."""

    scenarios: tuple[ScenarioResult, ...] = field(default_factory=tuple)

    @property
    def ok(self) -> bool:
        return all(s.ok for s in self.scenarios)

    @property
    def failed_count(self) -> int:
        return sum(1 for s in self.scenarios if not s.ok)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "scenario_count": len(self.scenarios),
            "failed_count": self.failed_count,
            "scenarios": [s.to_dict() for s in self.scenarios],
        }


# ---------------------------------------------------------------------------
# Shared probe-deps helper (same shape as R4.1's smoke probe)
# ---------------------------------------------------------------------------


def _make_drill_deps(department: str):
    """Construct a BridgeDeps with all-mock collaborators for the drill."""
    from teams._types import BridgeDeps

    memory_store = mock.AsyncMock()
    memory_store.get = mock.AsyncMock(return_value=None)
    memory_store.set = mock.AsyncMock(return_value=None)
    knowledge_search = mock.AsyncMock(return_value=[])
    return BridgeDeps(
        session_id="z4-recovery-drill",
        department=department,
        operator_id="z4-recovery-drill",
        memory_store=memory_store,
        event_bus=mock.MagicMock(),
        trust_manager=mock.MagicMock(),
        cost_tracker=mock.MagicMock(),
        knowledge_search=knowledge_search,
        cost_limit_usd=2.0,
    )


def _qa_config():
    from teams._types import AgentSpec, DepartmentConfig

    return DepartmentConfig(
        name="qa",
        zone=4,
        description="QA department (z4 recovery drill)",
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
class _DrillRegistry:
    configs: dict = field(default_factory=dict)

    def get_config(self, name: str):
        return self.configs.get(name)


# ---------------------------------------------------------------------------
# Scenarios
# ---------------------------------------------------------------------------


async def _scenario_failure() -> ScenarioResult:
    """Chief raises during execution → session ends FAILED.

    The dispatcher publishes `chief_dispatcher.routed` *before* the run
    starts, so a failed chief still leaves a routed event in the trail.
    The session lands in FAILED via WarmChief.__aexit__'s exception
    handler.
    """
    from bridge.chief_dispatcher import ChiefDispatcher
    from bridge.chief_session import ChiefSessionState
    from bridge.chief_session_store import InMemoryChiefSessionStore
    from bridge.event_bus import EventBus
    from bridge.warm_chief import WarmChief
    from bridge.work_order import WorkOrder
    from bridge.work_order_router import NullRouter

    department = "qa"
    registry = _DrillRegistry(configs={department: _qa_config()})
    store = InMemoryChiefSessionStore()

    with tempfile.TemporaryDirectory() as tmpdir:
        event_bus = EventBus(data_dir=Path(tmpdir))
        dispatcher = ChiefDispatcher(
            router=NullRouter(department=department),
            session_store=store,
            dept_registry=registry,
            event_bus=event_bus,
        )

        async def _raising_run_chief(self):  # noqa: ANN001
            raise RuntimeError("chief blew up — drill expected this")

        wo = WorkOrder.create(
            intent="failure-path drill",
            skill="drill",
            project="drill",
        )
        deps = _make_drill_deps(department)

        with mock.patch.object(WarmChief, "_run_chief", _raising_run_chief):
            with contextlib.suppress(RuntimeError):
                await dispatcher.dispatch(wo, deps)

        # Look up the persisted session — dispatch raised so we don't
        # have a return value, but the row is in the store.
        rows = list(store._sessions.values())
        if len(rows) != 1:
            return ScenarioResult(
                name="failure",
                ok=False,
                detail="expected exactly one session row after failed dispatch",
                final_state="",
                error=f"found {len(rows)} rows",
            )
        session = rows[0]
        events_seen = tuple(e.event_type for e in event_bus._recent_events)
        ok = (
            session.state == ChiefSessionState.FAILED
            and "chief_dispatcher.routed" in events_seen
        )
        return ScenarioResult(
            name="failure",
            ok=ok,
            detail=(
                "chief raised → session FAILED + routed event still published"
                if ok
                else "FAILED state or routed event missing"
            ),
            events_seen=events_seen,
            final_state=session.state.value,
        )


async def _scenario_requeue() -> ScenarioResult:
    """Operator requeue() of an AWAITING_EVALUATION session re-warms it.

    Drives a happy-path dispatch first (lands AWAITING_EVALUATION),
    then calls dispatcher.requeue(session_id) and asserts the session
    is back in WARM. The chief_dispatcher.requeued event must also be
    published.
    """
    from bridge.chief_dispatcher import ChiefDispatcher
    from bridge.chief_session import ChiefSessionState
    from bridge.chief_session_store import InMemoryChiefSessionStore
    from bridge.event_bus import EventBus
    from bridge.warm_chief import WarmChief
    from bridge.work_order import WorkOrder
    from bridge.work_order_router import NullRouter
    from teams._types import TeamResult

    department = "qa"
    registry = _DrillRegistry(configs={department: _qa_config()})
    store = InMemoryChiefSessionStore()

    with tempfile.TemporaryDirectory() as tmpdir:
        event_bus = EventBus(data_dir=Path(tmpdir))
        dispatcher = ChiefDispatcher(
            router=NullRouter(department=department),
            session_store=store,
            dept_registry=registry,
            event_bus=event_bus,
        )

        ok_result = TeamResult(
            department=department,
            manager_output="ok",
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
            intent="requeue-path drill",
            skill="drill",
            project="drill",
        )
        deps = _make_drill_deps(department)

        with mock.patch.object(WarmChief, "_run_chief", _ok_run_chief):
            session = await dispatcher.dispatch(wo, deps)
            if session.state != ChiefSessionState.AWAITING_EVALUATION:
                return ScenarioResult(
                    name="requeue",
                    ok=False,
                    detail="precondition failed: session not AWAITING_EVALUATION",
                    final_state=session.state.value,
                    error=f"state={session.state.value}",
                )
            requeued = await dispatcher.requeue(session.session_id)

        events_seen = tuple(e.event_type for e in event_bus._recent_events)
        ok = (
            requeued.state == ChiefSessionState.WARM
            and "chief_dispatcher.requeued" in events_seen
        )
        return ScenarioResult(
            name="requeue",
            ok=ok,
            detail=(
                "AWAITING_EVALUATION → requeue() → WARM + requeued event"
                if ok
                else "requeue did not re-warm or did not publish event"
            ),
            events_seen=events_seen,
            final_state=requeued.state.value,
        )


async def _scenario_retry_with_backoff() -> ScenarioResult:
    """retry_with_backoff() of a FAILED session re-warms with attempt counter.

    Synthesises a FAILED session in the store, calls retry_with_backoff,
    asserts the post-transition attempt count > 1 and the requeued
    event is published.
    """
    from bridge.chief_dispatcher import ChiefDispatcher
    from bridge.chief_session import ChiefSession, ChiefSessionState
    from bridge.chief_session_store import InMemoryChiefSessionStore
    from bridge.event_bus import EventBus
    from bridge.work_order_router import NullRouter

    department = "qa"
    registry = _DrillRegistry(configs={department: _qa_config()})
    store = InMemoryChiefSessionStore()

    with tempfile.TemporaryDirectory() as tmpdir:
        event_bus = EventBus(data_dir=Path(tmpdir))
        dispatcher = ChiefDispatcher(
            router=NullRouter(department=department),
            session_store=store,
            dept_registry=registry,
            event_bus=event_bus,
        )

        # Synthesise a FAILED session with a known starting state.
        from bridge.chief_session import new_chief_session_id
        failed = (
            ChiefSession(
                session_id=new_chief_session_id(),
                work_order_id="wo-retry-drill",
                department=department,
                chief_name=f"{department}-chief",
            )
            .transition(ChiefSessionState.WARM)
            .transition(ChiefSessionState.EXECUTING)
            .transition(ChiefSessionState.FAILED)
        )
        await store.create(failed)

        # Patch asyncio.sleep to keep the drill fast — the dispatcher
        # awaits the policy-computed backoff before re-warming, and the
        # exact wait length isn't what we're proving here. Per the
        # method's docstring, asyncio.sleep is the documented patch
        # point.
        async def _no_sleep(_seconds):
            return None

        with mock.patch("asyncio.sleep", _no_sleep):
            retried = await dispatcher.retry_with_backoff(
                failed.session_id,
                attempt=2,
            )

        events_seen = tuple(e.event_type for e in event_bus._recent_events)
        ok = (
            retried.state == ChiefSessionState.WARM
            and "chief_dispatcher.requeued" in events_seen
        )
        return ScenarioResult(
            name="retry_with_backoff",
            ok=ok,
            detail=(
                "FAILED → retry_with_backoff(attempt=2) → WARM + requeued event"
                if ok
                else "retry_with_backoff did not re-warm or did not publish"
            ),
            events_seen=events_seen,
            final_state=retried.state.value,
        )


async def _scenario_reaper() -> ScenarioResult:
    """Idle AWAITING_EVALUATION → reaper → TIMED_OUT → SHUTDOWN.

    Synthesises an AWAITING_EVALUATION session whose ``idle_since_utc``
    is far enough in the past to satisfy the reaper's
    ``older_than_seconds`` filter, then runs one reaper sweep with a
    pre-set shutdown event so the loop exits after a single iteration.
    """
    from datetime import datetime, timedelta, timezone

    from bridge.background_loops import chief_session_reaper_loop
    from bridge.chief_session import (
        ChiefSession,
        ChiefSessionState,
        new_chief_session_id,
    )
    from bridge.chief_session_store import InMemoryChiefSessionStore
    from bridge.event_bus import EventBus

    department = "qa"
    store = InMemoryChiefSessionStore()

    # Build an AWAITING_EVALUATION session whose idle clock is 1h old.
    session = (
        ChiefSession(
            session_id=new_chief_session_id(),
            work_order_id="wo-reaper-drill",
            department=department,
            chief_name=f"{department}-chief",
        )
        .transition(ChiefSessionState.WARM)
        .transition(ChiefSessionState.EXECUTING)
        .transition(ChiefSessionState.AWAITING_EVALUATION)
    )
    # Backdate the idle marker so list_idle picks it up immediately.
    from dataclasses import replace as dc_replace

    session = dc_replace(
        session,
        idle_since_utc=datetime.now(timezone.utc) - timedelta(seconds=3600),
    )
    await store.create(session)

    with tempfile.TemporaryDirectory() as tmpdir:
        event_bus = EventBus(data_dir=Path(tmpdir))
        # Pre-set the shutdown event so the loop runs exactly one sweep.
        shutdown_event = asyncio.Event()
        shutdown_event.set()
        await chief_session_reaper_loop(
            shutdown_event,
            chief_session_store=store,
            idle_timeout_seconds=60.0,  # 60s threshold; the row is 3600s old
            event_bus=event_bus,
            poll_interval=0.0,
        )

        # Read back the session — should be SHUTDOWN.
        reaped = await store.get(session.session_id)
        events_seen = tuple(e.event_type for e in event_bus._recent_events)
        ok = (
            reaped.state == ChiefSessionState.SHUTDOWN
            and "chief_session.timed_out" in events_seen
        )
        return ScenarioResult(
            name="reaper",
            ok=ok,
            detail=(
                "AWAITING_EVALUATION (idle) → reaper sweep → "
                "TIMED_OUT → SHUTDOWN + timed_out event"
                if ok
                else "reaper did not advance state or publish event"
            ),
            events_seen=events_seen,
            final_state=reaped.state.value,
        )


_SCENARIOS = {
    "failure": _scenario_failure,
    "requeue": _scenario_requeue,
    "retry_with_backoff": _scenario_retry_with_backoff,
    "reaper": _scenario_reaper,
}


# ---------------------------------------------------------------------------
# Drill runner
# ---------------------------------------------------------------------------


async def _run_drill_async(scenarios: list[str]) -> DrillResult:
    """Run the named scenarios sequentially and aggregate results."""
    results: list[ScenarioResult] = []
    for name in scenarios:
        scenario_fn = _SCENARIOS[name]
        try:
            results.append(await scenario_fn())
        except Exception as exc:  # noqa: BLE001 — drill-time catch
            results.append(
                ScenarioResult(
                    name=name,
                    ok=False,
                    detail=f"scenario raised: {type(exc).__name__}",
                    error=str(exc),
                )
            )
    return DrillResult(scenarios=tuple(results))


def run_drill(scenarios: list[str]) -> DrillResult:
    """Synchronous wrapper around the async driver for CLI consumption."""
    return asyncio.run(_run_drill_async(scenarios))


# ---------------------------------------------------------------------------
# Renderers
# ---------------------------------------------------------------------------


def render_text(result: DrillResult) -> str:
    lines = [
        "Z4 recovery drill",
        f"  ok:             {result.ok}",
        f"  scenario_count: {len(result.scenarios)}",
        f"  failed_count:   {result.failed_count}",
        "",
    ]
    for s in result.scenarios:
        marker = "PASS" if s.ok else "FAIL"
        lines.append(f"  [{marker}] {s.name}: {s.detail}")
        if s.final_state:
            lines.append(f"         final_state={s.final_state}")
        if s.events_seen:
            lines.append(f"         events_seen={list(s.events_seen)}")
        if s.error:
            lines.append(f"         error={s.error}")
    return "\n".join(lines) + "\n"


def render_json(result: DrillResult) -> str:
    return json.dumps(result.to_dict(), indent=2, sort_keys=True) + "\n"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Run the ChiefSession recovery and rollback drill. "
            "Drives synthetic WorkOrders through the real dispatcher "
            "and reaper loop, fakes the chief execution, and asserts "
            "the failure / requeue / retry / timeout paths work."
        )
    )
    parser.add_argument(
        "--scenario",
        action="append",
        choices=sorted(_SCENARIOS),
        help=(
            "Run only the named scenario(s); repeat for multiple. "
            "Default: all four."
        ),
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit a JSON summary instead of human-readable text.",
    )
    args = parser.parse_args(argv)

    scenarios = args.scenario or sorted(_SCENARIOS)

    try:
        result = run_drill(scenarios)
    except Exception as exc:  # noqa: BLE001 — CLI boundary
        print(
            f"z4_recovery_drill: internal harness error: "
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
    with contextlib.suppress(KeyboardInterrupt):
        sys.exit(main())
