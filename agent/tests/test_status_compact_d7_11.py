"""Tests for D7.11 — /status late-night profile (#1423)."""
from __future__ import annotations

from bridge.status_render import format_status_compact


# ---------------------------------------------------------------------------
# format_status_compact — surface
# ---------------------------------------------------------------------------

def test_compact_status_returns_string() -> None:
    out = format_status_compact({}, {}, [], {})
    assert isinstance(out, str)


def test_compact_status_under_25_lines_when_idle() -> None:
    """Idle-system render fits on one phone screen."""
    out = format_status_compact(
        health={"status": "healthy"},
        queues={"messages": 0, "self_edits": 0, "wiki_staging": 0,
                "hitl": 0, "workorders": 0},
        failures=[],
        session={"uptime": "2h 14m", "halted": False},
    )
    assert len(out.splitlines()) <= 25


def test_compact_status_orders_escalations_first() -> None:
    """When failures present, they appear before approvals/work/health."""
    out = format_status_compact(
        health={"status": "healthy"},
        queues={"messages": 0, "hitl": 5},
        failures=["- 14:30 [error] something broke"],
        session={"uptime": "1h"},
    )
    # Escalation header appears before the approvals line
    failures_idx = out.find("Recent failures")
    approvals_idx = out.find("Pending")
    assert failures_idx >= 0
    assert approvals_idx > failures_idx


def test_compact_status_omits_failures_when_empty() -> None:
    """No failures → no escalation section."""
    out = format_status_compact(
        health={"status": "healthy"},
        queues={"messages": 0, "hitl": 0},
        failures=[],
        session={"uptime": "1h"},
    )
    assert "Recent failures" not in out


def test_compact_status_renders_pending_breakdown() -> None:
    """Approvals line lists breakdown when items exist."""
    out = format_status_compact(
        health={"status": "healthy"},
        queues={"messages": 0, "hitl": 3, "self_edits": 2, "wiki_staging": 1},
        failures=[],
        session={"uptime": "1h"},
    )
    assert "3 HITL" in out
    assert "2 edits" in out
    assert "1 wiki" in out


def test_compact_status_pending_none_when_zero() -> None:
    """No pending items → 'Pending: none' (visual reassurance)."""
    out = format_status_compact(
        health={"status": "healthy"},
        queues={"hitl": 0, "self_edits": 0, "wiki_staging": 0},
        failures=[],
        session={"uptime": "1h"},
    )
    assert "Pending: none" in out


def test_compact_status_active_idle_when_no_work() -> None:
    """Empty queues + no active_work → 'Active: idle'."""
    out = format_status_compact(
        health={"status": "healthy"},
        queues={"messages": 0, "workorders": 0},
        failures=[],
        session={"uptime": "1h"},
    )
    assert "Active: idle" in out


def test_compact_status_active_lists_work_when_busy() -> None:
    """Messages in queue + workorders in flight → both render."""
    out = format_status_compact(
        health={"status": "healthy"},
        queues={"messages": 7, "workorders": 3},
        failures=[],
        session={"uptime": "1h"},
        active_work={"active_sprint": "D7.11", "in_flight_prs": 2},
    )
    assert "7 msg" in out
    assert "3 workorders" in out
    assert "D7.11" in out
    assert "2 PRs" in out


def test_compact_status_marks_halted() -> None:
    """halted=True → (HALTED) marker on the health line."""
    out = format_status_compact(
        health={"status": "healthy"},
        queues={},
        failures=[],
        session={"uptime": "1h", "halted": True},
    )
    assert "HALTED" in out


def test_compact_status_includes_cost_when_provided() -> None:
    """Cost block → today + weekly amounts render."""
    out = format_status_compact(
        health={"status": "healthy"},
        queues={},
        failures=[],
        session={"uptime": "1h"},
        cost={"today_usd": 1.42, "weekly_usd": 8.30},
    )
    assert "today $1.42" in out
    assert "7-day $8.30" in out


def test_compact_status_omits_cost_when_none() -> None:
    """cost=None → no cost line (graceful degrade)."""
    out = format_status_compact(
        health={"status": "healthy"},
        queues={},
        failures=[],
        session={"uptime": "1h"},
        cost=None,
    )
    assert "Cost:" not in out


def test_compact_status_includes_full_hint_footer() -> None:
    """Footer points to /status --full for the deep view."""
    out = format_status_compact({}, {}, [], {})
    assert "/status --full" in out


def test_compact_status_handles_non_dict_inputs_gracefully() -> None:
    """Defensive: non-dict args don't crash."""
    out = format_status_compact(None, None, None, None)  # type: ignore[arg-type]
    assert isinstance(out, str)
    assert len(out) > 0
