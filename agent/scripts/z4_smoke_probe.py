"""Synthetic Zone 4 WorkOrder smoke probe.

Sprint R4.1 (current-state improvement plan) — answers the operator's
proof-of-life question for Zone 4: "Can the harness route a synthetic
WorkOrder to a department chief, create a ChiefSession, publish
observable events, and return a final state without touching live
model/network services?"

The probe drives the **real** :class:`bridge.chief_dispatcher.ChiefDispatcher`
+ **real** :class:`bridge.event_bus.EventBus`, fakes only the chief
execution (so no Anthropic / OpenRouter / VAPI / GitHub / Discord call),
and emits a compact summary suitable for operator consumption or CI
gating.

This sits one layer above R1.4's readiness probe: the readiness check
guards event-lineage publication; this probe captures the operability
end-to-end (route → run → terminal state → summary).

Usage
-----
::

    cd agent
    .venv/bin/python scripts/z4_smoke_probe.py --department qa
    .venv/bin/python scripts/z4_smoke_probe.py --department qa --json
    .venv/bin/python scripts/z4_smoke_probe.py --department qa --intent "review the auth module"

Exit codes
----------
- ``0`` — probe completed; session reached AWAITING_EVALUATION; expected
  events present.
- ``1`` — probe completed but the result is degenerate: missing event,
  unexpected terminal state, or correlation broken.
- ``2`` — internal harness error (import failed, dispatcher refused to
  construct, etc.).

Design constraints
------------------
- **Offline + deterministic.** Patches ``WarmChief._run_chief`` so the
  chief returns a synthetic ``TeamResult`` without calling any model.
- **No mutation of dispatcher state across runs.** Each invocation
  builds a fresh ``InMemoryChiefSessionStore`` and a fresh ``EventBus``
  with a temp-dir.
- **No external dependencies introduced.** Only stdlib + the bridge
  packages already imported by the runtime. Same posture as R1.4's
  readiness probe.
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
# Probe-side data classes (immutable summary)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ProbeResult:
    """Outcome of one smoke probe run."""

    ok: bool
    department: str
    session_id: str
    work_order_id: str
    final_state: str
    events_present: tuple[str, ...]
    events_missing: tuple[str, ...]
    correlation_ok: bool
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "department": self.department,
            "session_id": self.session_id,
            "work_order_id": self.work_order_id,
            "final_state": self.final_state,
            "events_present": list(self.events_present),
            "events_missing": list(self.events_missing),
            "correlation_ok": self.correlation_ok,
            "error": self.error,
        }


# ---------------------------------------------------------------------------
# Probe runner
# ---------------------------------------------------------------------------


_REQUIRED_EVENTS = (
    "chief_session.created",
    "chief_session.state_changed",
    "chief_dispatcher.routed",
)


@dataclass
class _ProbeRegistry:
    """Minimal registry shape — returns the configured DepartmentConfig."""

    configs: dict = field(default_factory=dict)

    def get_config(self, name: str):
        return self.configs.get(name)


async def _run_probe_async(department: str, intent: str) -> ProbeResult:
    """Inner async driver — returns a ProbeResult.

    Raises only on import / construction failure (caller maps to
    exit-2). All other failure modes are surfaced via ``ProbeResult.ok``.
    """
    # Imports are inside the async fn so an import failure surfaces
    # cleanly through the caller's exception handling and exits 2.
    from bridge.chief_dispatcher import ChiefDispatcher
    from bridge.chief_session import ChiefSessionState
    from bridge.chief_session_store import InMemoryChiefSessionStore
    from bridge.event_bus import EventBus
    from bridge.warm_chief import WarmChief
    from bridge.work_order import WorkOrder
    from bridge.work_order_router import NullRouter
    from teams._types import (
        AgentSpec,
        BridgeDeps,
        DepartmentConfig,
        TeamResult,
    )
    from unittest.mock import AsyncMock, MagicMock

    def _make_probe_deps(department_name: str) -> BridgeDeps:
        """Construct a BridgeDeps with all-mock collaborators.

        Mirrors the test fixture in ``tests/test_teams/conftest.py::make_deps``
        but inlined here so the probe doesn't import from ``tests/`` —
        production scripts must not depend on test packages.
        """
        memory_store = AsyncMock()
        memory_store.get = AsyncMock(return_value=None)
        memory_store.set = AsyncMock(return_value=None)
        knowledge_search = AsyncMock(return_value=[])
        return BridgeDeps(
            session_id="z4-smoke-probe",
            department=department_name,
            operator_id="z4-smoke-probe",
            memory_store=memory_store,
            event_bus=MagicMock(),
            trust_manager=MagicMock(),
            cost_tracker=MagicMock(),
            knowledge_search=knowledge_search,
            cost_limit_usd=2.0,
        )

    config = DepartmentConfig(
        name=department,
        zone=4,
        description=f"{department} department (z4 smoke probe)",
        manager=AgentSpec(
            name=f"{department}-chief",
            model="anthropic:claude-opus-4-6",
        ),
        employees=(
            AgentSpec(
                name=f"{department}-specialist",
                model="anthropic:claude-sonnet-4-6",
            ),
        ),
    )
    registry = _ProbeRegistry(configs={department: config})
    store = InMemoryChiefSessionStore()

    with tempfile.TemporaryDirectory() as tmpdir:
        event_bus = EventBus(data_dir=Path(tmpdir))
        dispatcher = ChiefDispatcher(
            router=NullRouter(department=department),
            session_store=store,
            dept_registry=registry,
            event_bus=event_bus,
        )

        fake_result = TeamResult(
            department=department,
            manager_output="z4 smoke probe ok",
            employee_results=(),
            total_tokens=0,
            total_cost_usd=0.0,
            duration_seconds=0.0,
            success=True,
            error=None,
        )

        async def _fake_run_chief(self):  # noqa: ANN001
            return fake_result

        work_order = WorkOrder.create(
            intent=intent,
            skill="z4-smoke-probe",
            project="z4-smoke-probe",
        )
        deps = _make_probe_deps(department)

        with mock.patch.object(WarmChief, "_run_chief", _fake_run_chief):
            try:
                session = await dispatcher.dispatch(work_order, deps)
            except Exception as exc:  # noqa: BLE001 — probe-time catch
                return ProbeResult(
                    ok=False,
                    department=department,
                    session_id="",
                    work_order_id=work_order.id,
                    final_state="",
                    events_present=(),
                    events_missing=_REQUIRED_EVENTS,
                    correlation_ok=False,
                    error=f"dispatch raised: {type(exc).__name__}: {exc}",
                )

        # Inspect the event ring for required events + correlation.
        emitted_types = tuple(
            e.event_type for e in event_bus._recent_events
        )
        events_present = tuple(t for t in _REQUIRED_EVENTS if t in emitted_types)
        events_missing = tuple(
            t for t in _REQUIRED_EVENTS if t not in emitted_types
        )

        correlation_ok = True
        if not events_missing:
            for event_type in _REQUIRED_EVENTS:
                ev = next(
                    e for e in event_bus._recent_events
                    if e.event_type == event_type
                )
                if ev.payload.get("session_id") != session.session_id:
                    correlation_ok = False
                    break
                # `chief_session.state_changed` omits `department` by
                # schema design — guard the others.
                if event_type != "chief_session.state_changed":
                    if ev.payload.get("department") != department:
                        correlation_ok = False
                        break
                if ev.payload.get("work_order_id") != work_order.id:
                    correlation_ok = False
                    break

        terminal_ok = session.state == ChiefSessionState.AWAITING_EVALUATION

        ok = bool(not events_missing and correlation_ok and terminal_ok)
        error: str | None = None
        if not ok:
            reasons: list[str] = []
            if events_missing:
                reasons.append(f"missing events: {list(events_missing)}")
            if not correlation_ok:
                reasons.append("event correlation broken")
            if not terminal_ok:
                reasons.append(
                    f"unexpected terminal state: {session.state.value}"
                )
            error = "; ".join(reasons)

        return ProbeResult(
            ok=ok,
            department=department,
            session_id=session.session_id,
            work_order_id=work_order.id,
            final_state=session.state.value,
            events_present=events_present,
            events_missing=events_missing,
            correlation_ok=correlation_ok,
            error=error,
        )


def run_probe(department: str, intent: str) -> ProbeResult:
    """Synchronous wrapper around the async driver for CLI consumption."""
    return asyncio.run(_run_probe_async(department, intent))


# ---------------------------------------------------------------------------
# Renderers
# ---------------------------------------------------------------------------


def render_text(result: ProbeResult) -> str:
    lines = [
        f"Z4 smoke probe — department={result.department}",
        f"  ok:              {result.ok}",
        f"  session_id:      {result.session_id or '(none)'}",
        f"  work_order_id:   {result.work_order_id}",
        f"  final_state:     {result.final_state or '(none)'}",
        f"  events_present:  {list(result.events_present)}",
        f"  events_missing:  {list(result.events_missing)}",
        f"  correlation_ok:  {result.correlation_ok}",
    ]
    if result.error:
        lines.append(f"  error:           {result.error}")
    return "\n".join(lines) + "\n"


def render_json(result: ProbeResult) -> str:
    return json.dumps(result.to_dict(), indent=2, sort_keys=True) + "\n"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Drive a synthetic WorkOrder through the real ChiefDispatcher "
            "+ EventBus, fake the chief execution, and emit a summary "
            "of the route/run/terminal-state path. Offline + deterministic."
        )
    )
    parser.add_argument(
        "--department",
        default="qa",
        help="Department to route the synthetic WorkOrder to (default: qa).",
    )
    parser.add_argument(
        "--intent",
        default="z4 smoke probe — verify route → run → terminal state",
        help="Synthetic WorkOrder intent string.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit a JSON summary instead of human-readable text.",
    )
    args = parser.parse_args(argv)

    try:
        result = run_probe(args.department, args.intent)
    except Exception as exc:  # noqa: BLE001 — CLI boundary
        print(
            f"z4_smoke_probe: internal harness error: "
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
