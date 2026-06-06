"""Unit tests for bridge.status_render (D2.2 #1187)."""

from __future__ import annotations

import pytest

from bridge.status_render import (
    format_status,
    format_status_compact,
    format_mcp_section,
    format_executor_section,
    _glyph,
    _overall_label,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_ALL_COMPONENT_NAMES = [
    "discord", "claude", "database", "token", "memory", "voice",
    "services", "knowledge_freshness", "daily_log", "consolidation_lock",
    "tick_loop", "memory_file", "embedding_backend", "primer",
    "experiment_loop",
]


def _all_up_health() -> dict:
    return {
        "status": "healthy",
        "components": {name: {"status": "up"} for name in _ALL_COMPONENT_NAMES},
    }


def _empty_queues() -> dict:
    return {
        "messages": 0,
        "self_edits": 0,
        "wiki_staging": 0,
        "hitl": 0,
        "workorders": 0,
    }


# ---------------------------------------------------------------------------
# Spec tests (matching sprint requirements verbatim)
# ---------------------------------------------------------------------------


def test_render_all_up():
    out = format_status(_all_up_health(), _empty_queues(), [], {})
    assert "✓ discord" in out
    assert "Overall" in out


def test_degraded_critical():
    health = {
        "status": "degraded",
        "components": {
            "token": {"status": "degraded"},
            "discord": {"status": "up"},
            "claude": {"status": "up"},
            "database": {"status": "up"},
        },
    }
    out = format_status(health, {}, [], {})
    assert "degraded" in out.lower() or "DEGRADED" in out


def test_safe_count_none_renders_question():
    out = format_status({"status": "unknown", "components": {}}, {"messages": None}, [], {})
    assert "?" in out


def test_failures_block():
    out = format_status(
        {"status": "healthy", "components": {}},
        {},
        ["[error] disk full", "[alert] high mem"],
        {},
    )
    assert "disk full" in out


def test_output_not_empty():
    out = format_status({}, {}, [], {})
    assert len(out) > 0


# ---------------------------------------------------------------------------
# Glyph mapping
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("status,expected", [
    ("up", "✓"),
    ("degraded", "⚠"),
    ("down", "✗"),
    ("disabled", "—"),
    ("removed", "—"),
    ("unknown", "?"),
    ("bogus", "?"),
])
def test_glyph_mapping(status, expected):
    assert _glyph(status) == expected


# ---------------------------------------------------------------------------
# Overall label derivation
# ---------------------------------------------------------------------------


def test_overall_label_healthy():
    assert _overall_label({"status": "healthy"}) == "HEALTHY"


def test_overall_label_unhealthy():
    assert _overall_label({"status": "unhealthy"}) == "UNHEALTHY"


def test_overall_label_degraded():
    assert _overall_label({"status": "degraded"}) == "DEGRADED"


def test_overall_label_unknown_empty():
    assert _overall_label({"status": "unknown", "components": {}}) == "UNKNOWN"


def test_overall_label_derived_from_components_down():
    health = {
        "components": {
            "discord": {"status": "down"},
            "claude": {"status": "up"},
            "database": {"status": "up"},
            "token": {"status": "up"},
        }
    }
    label = _overall_label(health)
    assert label == "UNHEALTHY"


def test_overall_label_derived_all_up():
    health = {
        "components": {
            "discord": {"status": "up"},
            "claude": {"status": "up"},
            "database": {"status": "up"},
            "token": {"status": "up"},
        }
    }
    assert _overall_label(health) == "HEALTHY"


# ---------------------------------------------------------------------------
# Sections present in output
# ---------------------------------------------------------------------------


def test_sections_overall_components_queues():
    out = format_status(_all_up_health(), _empty_queues(), [], {})
    assert "Overall:" in out
    assert "Components:" in out
    assert "Queues:" in out


def test_all_critical_components_present():
    out = format_status(_all_up_health(), _empty_queues(), [], {})
    for name in ("discord", "claude", "database", "token"):
        assert name in out


def test_all_queue_labels_present():
    out = format_status(_all_up_health(), _empty_queues(), [], {})
    for label in ("messages", "self-edits", "wiki-staging", "hitl", "work-orders"):
        assert label in out


def test_queue_none_shows_question_mark():
    queues = {
        "messages": None,
        "self_edits": None,
        "wiki_staging": None,
        "hitl": None,
        "workorders": None,
    }
    out = format_status(_all_up_health(), queues, [], {})
    assert "?" in out


def test_queue_values_shown():
    queues = {
        "messages": 3,
        "self_edits": 1,
        "wiki_staging": 0,
        "hitl": 2,
        "workorders": 5,
    }
    out = format_status(_all_up_health(), queues, [], {})
    assert "3" in out
    assert "5" in out


# ---------------------------------------------------------------------------
# Failures block
# ---------------------------------------------------------------------------


def test_failures_capped_at_five():
    # format_status renders failures[:5] — first 5 of whatever is passed.
    # The caller (_read_recent_failures) is responsible for pre-capping to 5.
    many = [f"[error] problem {i}" for i in range(10)]
    out = format_status(_all_up_health(), _empty_queues(), many, {})
    # First 5 entries (0-4) should appear; entries 5-9 should not.
    assert "problem 0" in out
    assert "problem 4" in out
    # Entry 5 onwards should be absent (capped at 5).
    assert "problem 5" not in out


def test_failures_header_present():
    out = format_status(_all_up_health(), _empty_queues(), ["[error] x"], {})
    assert "Recent failures" in out


def test_no_failures_no_header():
    out = format_status(_all_up_health(), _empty_queues(), [], {})
    assert "Recent failures" not in out


# ---------------------------------------------------------------------------
# Session block
# ---------------------------------------------------------------------------


def test_session_block_rendered():
    session = {"uptime": "2h 15m", "messages": 42, "halted": False}
    out = format_status(_all_up_health(), _empty_queues(), [], session)
    assert "2h 15m" in out
    assert "42" in out


def test_session_halted_flag():
    session = {"uptime": "1h", "messages": 0, "halted": True}
    out = format_status(_all_up_health(), _empty_queues(), [], session)
    assert "HALTED" in out


def test_empty_session_no_crash():
    out = format_status(_all_up_health(), _empty_queues(), [], {})
    assert len(out) > 0


# ---------------------------------------------------------------------------
# Component detail extras
# ---------------------------------------------------------------------------


def test_latency_shown_for_discord():
    health = {
        "status": "healthy",
        "components": {
            "discord": {"status": "up", "latency_ms": 47},
        },
    }
    out = format_status(health, {}, [], {})
    assert "47ms" in out


def test_error_shown_for_down_component():
    health = {
        "status": "unhealthy",
        "components": {
            "database": {"status": "down", "error": "disk full"},
        },
    }
    out = format_status(health, {}, [], {})
    assert "disk full" in out


# ---------------------------------------------------------------------------
# Length cap
# ---------------------------------------------------------------------------


def test_output_length_under_1800_typical():
    out = format_status(_all_up_health(), _empty_queues(), [], {})
    assert len(out) <= 1800


def test_output_length_under_1800_with_failures():
    many = [f"[error] something went wrong in module_{i} at line {i*10}" for i in range(5)]
    out = format_status(_all_up_health(), _empty_queues(), many, {})
    assert len(out) <= 1800


def test_trimmed_failures_when_long():
    """When initial render would overflow, failures trim to 3."""
    # Manufacture a case that's too long by making component names very long
    # (inject many extra components).
    big_health = {
        "status": "healthy",
        "components": {f"component_{i:03d}": {"status": "up"} for i in range(60)},
    }
    long_failures = ["[error] " + "x" * 200 for _ in range(5)]
    out = format_status(big_health, _empty_queues(), long_failures, {})
    # Should not crash and should return a non-empty string.
    assert len(out) > 0


# ---------------------------------------------------------------------------
# Robustness — bad inputs
# ---------------------------------------------------------------------------


def test_none_health_does_not_crash():
    out = format_status(None, {}, [], {})  # type: ignore[arg-type]
    assert len(out) > 0


def test_none_queues_does_not_crash():
    out = format_status({}, None, [], {})  # type: ignore[arg-type]
    assert len(out) > 0


def test_none_failures_does_not_crash():
    out = format_status({}, {}, None, {})  # type: ignore[arg-type]
    assert len(out) > 0


# ---------------------------------------------------------------------------
# Issue #1543: MCP-health summary section
# ---------------------------------------------------------------------------


def test_format_mcp_section_none_returns_empty():
    assert format_mcp_section(None) == []


def test_format_mcp_section_empty_dict_returns_empty():
    assert format_mcp_section({}) == []


def test_format_mcp_section_zero_total_returns_empty():
    """Total = 0 means MCPMonitor hasn't completed a check yet — omit."""
    assert format_mcp_section({"total": 0, "running": 0}) == []


def test_format_mcp_section_renders_header():
    out = format_mcp_section({"total": 3, "running": 2})
    assert out
    assert "MCP servers (2/3 healthy)" in out[0]


def test_format_mcp_section_renders_crash_loop_warning():
    out = format_mcp_section({"total": 4, "running": 1, "crash_loop": 2})
    assert "2 crash-loop" in out[0]


def test_format_mcp_section_renders_per_server_lines():
    block = {
        "total": 2,
        "running": 1,
        "servers": [
            {"name": "memory", "status": "running", "memory_mb": 42.5},
            {"name": "github", "status": "stopped", "memory_mb": 0.0},
        ],
    }
    out = format_mcp_section(block)
    flat = "\n".join(out)
    assert "memory: running" in flat
    assert "42.5MB" in flat
    assert "github: stopped" in flat


def test_format_mcp_section_caps_server_list_at_12():
    servers = [
        {"name": f"srv{i}", "status": "running", "memory_mb": 1.0}
        for i in range(20)
    ]
    block = {"total": 20, "running": 20, "servers": servers}
    out = format_mcp_section(block)
    # Header + 12 server lines + 1 "…N more" line = 14 lines max.
    assert len(out) == 14
    assert "8 more" in out[-1]


def test_format_status_includes_mcp_block():
    """Issue #1543: ``/status --full`` includes the MCP section when
    monitor data is supplied."""
    mcp = {"total": 3, "running": 2, "crash_loop": 0,
           "servers": [{"name": "memory", "status": "running"}]}
    out = format_status({}, {}, [], {}, mcp=mcp)
    assert "MCP servers (2/3 healthy)" in out


def test_format_status_compact_includes_mcp_block():
    """Issue #1543: the late-night compact ``/status`` includes MCP too."""
    mcp = {"total": 3, "running": 3, "crash_loop": 0}
    out = format_status_compact({}, {}, [], {}, mcp=mcp)
    assert "MCP servers (3/3 healthy)" in out


def test_format_status_omits_mcp_block_when_absent():
    """No regression: when ``mcp`` is None, the section is invisible."""
    out = format_status({}, {}, [], {}, mcp=None)
    assert "MCP servers" not in out


def test_none_session_does_not_crash():
    out = format_status({}, {}, [], None)  # type: ignore[arg-type]
    assert len(out) > 0


# ---------------------------------------------------------------------------
# Sprint E.05 (#2012): per-executor availability section
# ---------------------------------------------------------------------------


def test_format_executor_section_none_returns_empty():
    assert format_executor_section(None) == []


def test_format_executor_section_empty_dict_returns_empty():
    assert format_executor_section({}) == []


def test_format_executor_section_renders_header_and_lines():
    out = format_executor_section({
        "WORKTREE": "available",
        "SUBAGENT": "available",
        "E2B": "blocked: #416 credentials",
    })
    flat = "\n".join(out)
    assert "Executors:" in flat
    assert "executor.WORKTREE" in flat
    assert "executor.SUBAGENT" in flat
    assert "executor.E2B" in flat
    assert "blocked: #416 credentials" in flat


def test_format_status_omits_executor_block_when_absent():
    """No regression: when ``executors`` is None, the section is invisible."""
    out = format_status({}, {}, [], {}, executors=None)
    assert "Executors:" not in out
    assert "executor." not in out


def test_format_status_includes_executor_section_with_e2b_blocked():
    """Sprint E.05 / #2012: ``/status --full`` surfaces per-executor
    availability — all three names render and the E2B blocker note carries
    through verbatim so the operator sees the #416 credentials reference."""
    snapshot = {
        "WORKTREE": "available",
        "SUBAGENT": "available",
        "E2B": "blocked: #416 credentials",
    }
    out = format_status(
        _all_up_health(), _empty_queues(), [], {}, executors=snapshot
    )
    assert "WORKTREE" in out
    assert "SUBAGENT" in out
    assert "E2B" in out
    assert "#416 credentials" in out
