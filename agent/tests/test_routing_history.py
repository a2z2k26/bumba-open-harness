"""Tests for the routing-history ring buffer (issue #1540)."""

from __future__ import annotations

import pytest

from bridge.routing_history import (
    RoutingDecisionRecord,
    RoutingHistory,
    get_history,
    record_routing_decision,
)
from bridge.status_render import (
    format_routing_section,
    format_status,
    format_status_compact,
)


@pytest.fixture(autouse=True)
def _clear_singleton():
    """Reset the process-wide singleton between cases."""
    get_history().clear()
    yield
    get_history().clear()


def _make(message_id: str, model: str) -> RoutingDecisionRecord:
    return RoutingDecisionRecord(
        message_id=message_id,
        router_used="model_router+command_router",
        intent="build",
        severity="3",
        model_selected=model,
        department_routed_to="engineering",
        timestamp_ms=1234567890_000,
    )


# ---------------------------------------------------------------------------
# RoutingHistory — ring buffer semantics
# ---------------------------------------------------------------------------


def test_ring_buffer_drops_oldest_returns_last_five_in_order():
    """Record 7 decisions; recent(5) must return the last 5 in insertion order."""
    history = RoutingHistory(maxlen=5)
    for i in range(7):
        history.record(_make(message_id=str(i), model="haiku"))

    recent = history.recent(5)
    assert len(recent) == 5
    ids = [r.message_id for r in recent]
    # After dropping 0 and 1, we expect 2,3,4,5,6 in order.
    assert ids == ["2", "3", "4", "5", "6"]


def test_recent_handles_n_larger_than_buffer():
    history = RoutingHistory(maxlen=5)
    for i in range(3):
        history.record(_make(message_id=str(i), model="sonnet"))

    out = history.recent(10)
    assert [r.message_id for r in out] == ["0", "1", "2"]


def test_recent_zero_or_negative_returns_empty():
    history = RoutingHistory(maxlen=5)
    history.record(_make("0", "haiku"))
    assert history.recent(0) == []
    assert history.recent(-1) == []


def test_module_level_record_uses_singleton():
    record_routing_decision(
        message_id="42",
        router_used="model_router+command_router",
        intent="analyze",
        severity="2",
        model_selected="sonnet",
        department_routed_to="research",
    )
    out = get_history().recent(5)
    assert len(out) == 1
    assert out[0].message_id == "42"
    assert out[0].model_selected == "sonnet"
    assert out[0].department_routed_to == "research"


def test_record_tolerates_none_fields():
    record_routing_decision(
        message_id=None,
        router_used="model_router+command_router",
        intent=None,
        severity=None,
        model_selected="haiku",
        department_routed_to=None,
    )
    rec = get_history().recent(5)[0]
    assert rec.message_id is None
    assert rec.intent is None
    assert rec.severity is None
    assert rec.department_routed_to is None
    assert rec.model_selected == "haiku"


def test_record_coerces_int_message_id_to_str():
    """Caller passes the QueuedMessage row id (int); we store it as str."""
    record_routing_decision(
        message_id=17,  # type: ignore[arg-type]
        router_used="model_router+command_router",
        model_selected="haiku",
    )
    rec = get_history().recent(5)[0]
    assert rec.message_id == "17"


# ---------------------------------------------------------------------------
# /status rendering integration
# ---------------------------------------------------------------------------


def test_format_routing_section_empty_returns_no_lines():
    assert format_routing_section(None) == []
    assert format_routing_section([]) == []


def test_format_routing_section_renders_header_and_rows():
    decisions = [_make("1", "haiku"), _make("2", "sonnet")]
    lines = format_routing_section(decisions)
    assert lines[0] == "Routing (last 5):"
    assert len(lines) == 3  # header + 2 rows
    assert "msg=1" in lines[1]
    assert "model=haiku" in lines[1]
    assert "msg=2" in lines[2]
    assert "model=sonnet" in lines[2]


def test_format_routing_section_caps_at_five_even_when_more_given():
    decisions = [_make(str(i), "haiku") for i in range(8)]
    lines = format_routing_section(decisions)
    # header + 5 rows
    assert len(lines) == 6
    # Last 5: 3..7
    assert "msg=3" in lines[1]
    assert "msg=7" in lines[5]


def test_format_status_compact_includes_routing_when_decisions_exist():
    decisions = [_make("99", "sonnet")]
    out = format_status_compact(
        health={"status": "healthy", "components": {}},
        queues={},
        failures=[],
        session={"uptime": "1h", "halted": False},
        cost=None,
        active_work=None,
        routing=decisions,
    )
    assert "Routing (last 5):" in out
    assert "msg=99" in out
    assert "model=sonnet" in out


def test_format_status_compact_omits_routing_section_when_no_decisions():
    out = format_status_compact(
        health={"status": "healthy", "components": {}},
        queues={},
        failures=[],
        session={"uptime": "1h", "halted": False},
        cost=None,
        active_work=None,
        routing=[],
    )
    assert "Routing (last 5):" not in out


def test_format_status_full_includes_routing_when_decisions_exist():
    decisions = [_make("7", "opus")]
    out = format_status(
        health={"status": "healthy", "components": {"discord": {"status": "up"}}},
        queues={"messages": 0},
        failures=[],
        session={"uptime": "2h"},
        routing=decisions,
    )
    assert "Routing (last 5):" in out
    assert "msg=7" in out
    assert "model=opus" in out


def test_format_status_full_backward_compatible_without_routing_kwarg():
    """Existing callers passing only the original 4 args still work."""
    out = format_status(
        health={"status": "healthy", "components": {}},
        queues={},
        failures=[],
        session={},
    )
    assert "Routing (last 5):" not in out
    assert "Overall:" in out


def test_format_routing_section_handles_missing_fields_via_dict():
    """Records can be dict-shaped duck-types; missing fields render as '?'."""
    rec = {
        "message_id": "5",
        "router_used": "model_router",
        # intent / severity / department / model intentionally absent
    }
    lines = format_routing_section([rec])
    assert lines[0] == "Routing (last 5):"
    assert "msg=5" in lines[1]
    assert "model=?" in lines[1]
    assert "dept=?" in lines[1]
    assert "intent=?" in lines[1]
    assert "sev=?" in lines[1]
