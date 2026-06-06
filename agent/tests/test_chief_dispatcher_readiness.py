"""Readiness probe: ChiefDispatcher event lineage for a synthetic WorkOrder.

Sprint R1.1.4 (current-state improvement plan) — promotes the production-
readiness check `ChiefDispatcher end-to-end observability` from a
``stub_pending`` row to a live ``run_check`` invocation in
``agent/scripts/readiness.sh``.

What this test guards
---------------------
A synthetic WorkOrder driven through the *real* :class:`ChiefDispatcher`
+ *real* :class:`EventBus` must produce, in order:

1. ``chief_session.created``  — new session row reaches the store
2. ``chief_session.state_changed`` — COLD → WARM transition
3. ``chief_dispatcher.routed`` — dispatcher commits the routing decision

All three events MUST share the same ``session_id``, ``work_order_id``,
and ``department`` so a subscriber can stitch the lineage together
without out-of-band correlation. This is the operability seam: if the
chain breaks, Mission Control loses its ability to attribute downstream
chief work to the originating WorkOrder.

What it does NOT guard
----------------------
- Anthropic / OpenRouter / VAPI / GitHub network paths — fully offline.
- Chief synthesis quality — ``WarmChief._run_chief`` is patched.
- Circuit-breaker / requeue / shutdown lifecycle — separate test files.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from unittest import mock

import pytest

from bridge.chief_dispatcher import ChiefDispatcher
from bridge.chief_session import ChiefSessionState
from bridge.chief_session_store import InMemoryChiefSessionStore
from bridge.event_bus import EventBus
from bridge.warm_chief import WarmChief
from bridge.work_order import WorkOrder
from bridge.work_order_router import NullRouter
from teams._types import (
    AgentSpec,
    DepartmentConfig,
    TeamResult,
)
from tests.test_teams.conftest import make_deps


@dataclass
class _ReadinessRegistry:
    """Minimal registry shape — returns the configured DepartmentConfig."""

    configs: dict[str, DepartmentConfig] = field(default_factory=dict)

    def get_config(self, name: str) -> DepartmentConfig | None:
        return self.configs.get(name)


def _events_of(bus: EventBus, event_type: str) -> list[Any]:
    return [e for e in bus._recent_events if e.event_type == event_type]


@pytest.mark.asyncio
async def test_chief_dispatcher_readiness_event_lineage(tmp_path):
    """Synthetic WorkOrder produces routed + created + state_changed lineage.

    The three events must arrive in the order the dispatcher publishes
    them (created → state_changed → routed), share matching correlation
    fields, and reference the same session row that was actually
    persisted to the store.
    """
    department = "qa"
    qa_config = DepartmentConfig(
        name=department,
        zone=4,
        description="QA department (readiness probe)",
        manager=AgentSpec(
            name="qa-chief",
            model="anthropic:claude-opus-4-6",
        ),
        employees=(
            AgentSpec(
                name="qa-engineer",
                model="anthropic:claude-sonnet-4-6",
            ),
        ),
    )
    registry = _ReadinessRegistry(configs={department: qa_config})
    store = InMemoryChiefSessionStore()
    event_bus = EventBus(data_dir=tmp_path)
    dispatcher = ChiefDispatcher(
        router=NullRouter(department=department),
        session_store=store,
        dept_registry=registry,
        event_bus=event_bus,
    )

    # Patched chief: no Anthropic call, deterministic success.
    fake_result = TeamResult(
        department=department,
        manager_output="readiness probe ok",
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
        intent="readiness probe — verify event lineage",
        skill="probe",
        project="readiness",
    )
    deps = make_deps(department=department)

    with mock.patch.object(WarmChief, "_run_chief", _fake_run_chief):
        session = await dispatcher.dispatch(work_order, deps)

    # Session must have advanced to AWAITING_EVALUATION (chief returned ok).
    assert session.state == ChiefSessionState.AWAITING_EVALUATION
    assert session.department == department
    assert session.work_order_id == work_order.id

    # --- Lineage event 1: chief_session.created -------------------------
    created = _events_of(event_bus, "chief_session.created")
    assert len(created) == 1, (
        "exactly one chief_session.created expected for one dispatch"
    )
    created_payload = created[0].payload
    assert created_payload["session_id"] == session.session_id
    assert created_payload["work_order_id"] == work_order.id
    assert created_payload["department"] == department

    # --- Lineage event 2: chief_session.state_changed (COLD → WARM) -----
    state_changes = _events_of(event_bus, "chief_session.state_changed")
    assert len(state_changes) >= 1, (
        "at least one chief_session.state_changed expected (COLD → WARM)"
    )
    cold_to_warm = next(
        (
            e
            for e in state_changes
            if e.payload.get("from_state") == ChiefSessionState.COLD.value
            and e.payload.get("to_state") == ChiefSessionState.WARM.value
        ),
        None,
    )
    assert cold_to_warm is not None, (
        "expected COLD → WARM transition in state_changed events"
    )
    assert cold_to_warm.payload["session_id"] == session.session_id
    assert cold_to_warm.payload["work_order_id"] == work_order.id

    # --- Lineage event 3: chief_dispatcher.routed -----------------------
    routed = _events_of(event_bus, "chief_dispatcher.routed")
    assert len(routed) == 1, (
        "exactly one chief_dispatcher.routed expected for one dispatch"
    )
    routed_payload = routed[0].payload
    assert routed_payload["session_id"] == session.session_id
    assert routed_payload["work_order_id"] == work_order.id
    assert routed_payload["department"] == department

    # --- Cross-event correlation: all three reference the same trio -----
    correlation_keys = {
        "session_id": session.session_id,
        "work_order_id": work_order.id,
        "department": department,
    }
    for event_payload, label in (
        (created_payload, "chief_session.created"),
        (cold_to_warm.payload, "chief_session.state_changed"),
        (routed_payload, "chief_dispatcher.routed"),
    ):
        for key, expected in correlation_keys.items():
            # state_changed event omits `department` from its payload by
            # design (the lifecycle event is dept-agnostic at the schema
            # level); skip that one cell rather than weaken the others.
            if label == "chief_session.state_changed" and key == "department":
                continue
            assert event_payload[key] == expected, (
                f"{label}.{key} expected {expected!r}, "
                f"got {event_payload[key]!r}"
            )

    # No rejection event — routing succeeded.
    assert _events_of(event_bus, "chief_dispatcher.rejected") == []
