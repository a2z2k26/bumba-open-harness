"""Pure render module for the /status operator command (D2.2 #1187).

Public API
----------
format_status(health, queues, failures, session) -> str

No I/O, no BridgeApp import, no side effects.
"""

from __future__ import annotations

__all__ = [
    "format_status",
    "format_status_compact",
    "format_routing_section",
    "format_mcp_section",
    "format_executor_section",
]

# Glyph map for component status values.
_GLYPHS: dict[str, str] = {
    "up": "✓",
    "degraded": "⚠",
    "down": "✗",
    "disabled": "—",
    "removed": "—",
    "unknown": "?",
}

# Components considered critical for the overall header verdict.
_CRITICAL = ("discord", "claude", "database", "token")

# Preferred display order for components.
_COMPONENT_ORDER = [
    "discord",
    "claude",
    "database",
    "token",
    "memory",
    "voice",
    "services",
    "knowledge_freshness",
    "daily_log",
    "consolidation_lock",
    "tick_loop",
    "memory_file",
    "embedding_backend",
    "primer",
    "experiment_loop",
]


def _glyph(status: str) -> str:
    return _GLYPHS.get(status, "?")


def _overall_label(health: dict) -> str:
    """Derive an overall status label from the health dict."""
    top = health.get("status", "unknown")
    if top == "healthy":
        return "HEALTHY"
    if top == "unhealthy":
        return "UNHEALTHY"
    if top == "degraded":
        return "DEGRADED"
    # Compute from components when top-level status is missing/unknown.
    components = health.get("components", {})
    if not components:
        return "UNKNOWN"
    critical_statuses = [
        components.get(c, {}).get("status", "unknown") for c in _CRITICAL
    ]
    if any(s == "down" for s in critical_statuses):
        return "UNHEALTHY"
    if any(s not in ("up", "disabled", "removed") for s in critical_statuses):
        return "DEGRADED"
    return "HEALTHY"


def _render_components(components: dict) -> list[str]:
    """Render the 14-component block, sorted by _COMPONENT_ORDER then alpha."""
    lines: list[str] = []
    seen: set[str] = set()

    # First pass: ordered components.
    for name in _COMPONENT_ORDER:
        if name in components:
            info = components[name]
            status = info.get("status", "unknown") if isinstance(info, dict) else "unknown"
            glyph = _glyph(status)
            # Append extra detail if present (latency, error, note).
            detail = ""
            if isinstance(info, dict):
                if "latency_ms" in info and info["latency_ms"] is not None:
                    detail = f" ({info['latency_ms']}ms)"
                elif "error" in info and info["error"]:
                    err = str(info["error"])[:50]
                    detail = f" ({err})"
            lines.append(f"  {glyph} {name}{detail}")
            seen.add(name)

    # Second pass: any components not in _COMPONENT_ORDER.
    for name, info in sorted(components.items()):
        if name in seen:
            continue
        status = info.get("status", "unknown") if isinstance(info, dict) else "unknown"
        glyph = _glyph(status)
        lines.append(f"  {glyph} {name}")

    return lines


def _render_queues(queues: dict) -> list[str]:
    """Render the 5-surface queue block."""
    labels = {
        "messages": "messages",
        "self_edits": "self-edits",
        "wiki_staging": "wiki-staging",
        "hitl": "hitl",
        "workorders": "work-orders",
    }
    lines: list[str] = []
    for key, label in labels.items():
        val = queues.get(key)
        if val is None:
            display = "?"
        else:
            display = str(int(val))
        lines.append(f"  {label}: {display}")
    return lines


def _render_failures(failures: list[str]) -> list[str]:
    """Render recent-failures block (≤5 lines)."""
    if not failures:
        return []
    lines = ["Recent failures (24h):"]
    for f in failures[:5]:
        # Trim long lines for readability.
        trimmed = f[:120] if len(f) > 120 else f
        lines.append(f"  {trimmed}")
    return lines


def _render_session(session: dict) -> list[str]:
    """Render the session subheading block."""
    if not session:
        return []
    lines: list[str] = []
    uptime = session.get("uptime")
    messages = session.get("messages")
    halted = session.get("halted", False)

    parts: list[str] = []
    if uptime:
        parts.append(f"uptime {uptime}")
    if messages is not None:
        parts.append(f"{messages} msg")
    if halted:
        parts.append("[HALTED]")

    if session.get("active") is False:
        lines.append("Session: No active session")
    elif parts:
        lines.append("Session: " + "  |  ".join(parts))
    context_lines = _render_context_budget(session)
    if context_lines:
        lines.extend(context_lines)
    return lines


def _render_context_budget(session: dict) -> list[str]:
    """Render the active session context-pressure bar."""
    if not session.get("active"):
        return []
    message_count = session.get("message_count")
    max_messages = session.get("max_messages")
    pressure = session.get("pressure")
    if not isinstance(message_count, int) or not isinstance(max_messages, int):
        return []
    if max_messages <= 0:
        return []
    if not isinstance(pressure, (int, float)):
        pressure = message_count / max(max_messages, 1)
    pct = max(0, min(100, int(round(float(pressure) * 100))))
    filled = max(0, min(20, int(round(pct / 5))))
    bar = "#" * filled + "-" * (20 - filled)
    return [f"Messages: {message_count}/{max_messages} [{bar}] {pct}%"]


def format_mcp_section(mcp: dict | None) -> list[str]:
    """Render the MCP-health block for ``/status`` (issue #1543).

    ``mcp`` shape::

        {
            "running": int,
            "total": int,
            "crash_loop": int,        # optional
            "servers": [              # optional, one entry per known server
                {"name": str, "status": str, "memory_mb": float},
                ...
            ],
        }

    Returns an empty list when ``mcp`` is None / empty / lacks ``total``
    so the caller can omit the section. Output is at most 1 header line
    plus one line per server (capped to 12 to stay phone-readable).
    """
    if not isinstance(mcp, dict):
        return []
    total = mcp.get("total")
    if not isinstance(total, int) or total <= 0:
        return []

    running = mcp.get("running")
    running_n = int(running) if isinstance(running, int) else 0
    crash_n = mcp.get("crash_loop")

    header = f"MCP servers ({running_n}/{total} healthy)"
    if isinstance(crash_n, int) and crash_n > 0:
        header += f" — {crash_n} crash-loop"

    lines: list[str] = [header]

    servers = mcp.get("servers")
    if isinstance(servers, list) and servers:
        for entry in servers[:12]:
            if not isinstance(entry, dict):
                continue
            name = entry.get("name") or "?"
            status = entry.get("status") or "unknown"
            mem = entry.get("memory_mb")
            mem_str = ""
            if isinstance(mem, (int, float)) and mem > 0:
                mem_str = f" ({mem:.1f}MB)"
            glyph = {
                "running": "✓",
                "stopped": "✗",
                "unknown": "?",
            }.get(status, "?")
            lines.append(f"  {glyph} {name}: {status}{mem_str}")
        if len(servers) > 12:
            lines.append(f"  …{len(servers) - 12} more")

    return lines


def format_executor_section(snapshot: dict[str, str] | None) -> list[str]:
    """Render the per-executor availability block for /status (E.05 / #2012).

    ``snapshot`` is a mapping of executor name → availability string (e.g.
    ``{"WORKTREE": "available", "E2B": "blocked: #416 credentials"}``).
    Returns an empty list when ``snapshot`` is None or empty so the caller
    can omit the section entirely.

    Glyph rule: a value of exactly ``"available"`` renders the ✓ glyph;
    anything else (typically a ``"blocked: …"`` string) renders ⚠. This
    mirrors the up/degraded distinction in ``_GLYPHS`` without forcing
    callers to translate to those exact tokens.
    """
    if not isinstance(snapshot, dict) or not snapshot:
        return []

    lines: list[str] = ["Executors:"]
    for name in sorted(snapshot):
        availability = snapshot[name]
        if availability == "available":
            glyph = _GLYPHS["up"]
        else:
            glyph = _GLYPHS["degraded"]
        lines.append(f"  executor.{name}: {glyph} {availability}")
    return lines


def format_routing_section(routing: list | None) -> list[str]:
    """Render the "Recent Routing" section for /status (issue #1540).

    ``routing`` is a list of ``RoutingDecisionRecord`` (or dict-shaped
    duck-types — anything supporting attribute or key access for the six
    fields). When the list is empty or None, returns ``[]`` so the caller can
    decide whether to render a "(none)" placeholder.
    """
    if not routing:
        return []

    def _f(rec: object, name: str) -> str:
        # Support both dataclass attribute access and dict-shaped records.
        if hasattr(rec, name):
            val = getattr(rec, name)
        elif isinstance(rec, dict):
            val = rec.get(name)
        else:
            val = None
        return "?" if val is None else str(val)

    lines: list[str] = ["Routing (last 5):"]
    for rec in routing[-5:]:
        msg_id = _f(rec, "message_id")
        router = _f(rec, "router_used")
        intent = _f(rec, "intent")
        severity = _f(rec, "severity")
        model = _f(rec, "model_selected")
        dept = _f(rec, "department_routed_to")
        # Compact one-line format: msg=<id> via <router> → model=<m> dept=<d> intent=<i> sev=<s>
        lines.append(
            f"  msg={msg_id} via {router} → model={model} dept={dept} intent={intent} sev={severity}"
        )
    return lines


def format_status_compact(
    health: dict,
    queues: dict,
    failures: list[str],
    session: dict,
    cost: dict | None = None,
    active_work: dict | None = None,
    routing: list | None = None,
    mcp: dict | None = None,
) -> str:
    """Render the late-night /status profile (D7.11 / #1423).

    Phone-readable, ≤25 lines. Sorted by 11pm-operator priority:
    escalations first, then pending approvals, active work, health,
    cost. The full 14-component dump moves to ``/status --full``
    (rendered by :func:`format_status`).

    Parameters mirror :func:`format_status` plus two optional shapes
    (``cost`` and ``active_work``); both default to None when the
    caller can't gather them.
    """
    if not isinstance(health, dict):
        health = {}
    if not isinstance(queues, dict):
        queues = {}
    if not isinstance(failures, list):
        failures = []
    if not isinstance(session, dict):
        session = {}

    lines: list[str] = []
    lines.append("Agent online")

    # --- 1. Escalations / failures (highest priority) ---
    if failures:
        # Trim to 2 most-recent for screen-fit
        recent = failures[-2:]
        lines.append(f"⚠ Recent failures ({len(failures)}):")
        for fl in recent:
            # Strip leading "- HH:MM " noise; keep the meat
            trimmed = fl.lstrip("- ").strip()
            if len(trimmed) > 90:
                trimmed = trimmed[:87] + "…"
            lines.append(f"  {trimmed}")
        lines.append("")

    # --- 2. Pending approvals ---
    pending_total = 0
    for key in ("hitl", "self_edits", "wiki_staging"):
        v = queues.get(key)
        if isinstance(v, int):
            pending_total += v
    approvals_str = ""
    if pending_total > 0:
        breakdown = []
        for key, label in (("hitl", "HITL"), ("self_edits", "edits"), ("wiki_staging", "wiki")):
            v = queues.get(key)
            if isinstance(v, int) and v > 0:
                breakdown.append(f"{v} {label}")
        approvals_str = f"📋 Pending: {', '.join(breakdown)}"
    else:
        approvals_str = "📋 Pending: none"
    lines.append(approvals_str)
    messages = queues.get("messages")
    if isinstance(messages, int):
        lines.append(f"Queue: {messages} pending")

    # --- 3. Active work ---
    msg_count = queues.get("messages")
    wo_count = queues.get("workorders")
    work_parts = []
    if isinstance(msg_count, int) and msg_count > 0:
        work_parts.append(f"{msg_count} msg in queue")
    if isinstance(wo_count, int) and wo_count > 0:
        work_parts.append(f"{wo_count} workorders in flight")
    if active_work:
        sprint = active_work.get("active_sprint", "")
        if sprint:
            work_parts.append(f"sprint {sprint}")
        prs = active_work.get("in_flight_prs", 0)
        if isinstance(prs, int) and prs > 0:
            work_parts.append(f"{prs} PRs open")
    if work_parts:
        lines.append("🔧 Active: " + ", ".join(work_parts))
    else:
        lines.append("🔧 Active: idle")

    # --- 4. Health (one line) ---
    label = _overall_label(health)
    uptime = session.get("uptime") or "?"
    halted = session.get("halted")
    halted_marker = " (HALTED)" if halted else ""
    lines.append(f"❤️ Health: {label} · uptime {uptime}{halted_marker}")

    session_lines = _render_session(session)
    if session_lines:
        lines.extend(session_lines)

    # --- 5. Cost (one line) ---
    if isinstance(cost, dict):
        today = cost.get("today_usd")
        weekly = cost.get("weekly_usd")
        cost_parts = []
        if isinstance(today, (int, float)):
            cost_parts.append(f"today ${today:.2f}")
        if isinstance(weekly, (int, float)):
            cost_parts.append(f"7-day ${weekly:.2f}")
        if cost_parts:
            lines.append("💰 Cost: " + ", ".join(cost_parts))

    # --- 6. Recent Routing (issue #1540) — only render when decisions exist
    routing_lines = format_routing_section(routing if isinstance(routing, list) else None)
    if routing_lines:
        lines.append("")
        lines.extend(routing_lines)

    # --- 7. MCP servers (issue #1543) — only render when monitor wired
    mcp_lines = format_mcp_section(mcp if isinstance(mcp, dict) else None)
    if mcp_lines:
        lines.append("")
        lines.extend(mcp_lines)

    # --- Footer hint ---
    lines.append("")
    lines.append("`/status --full` for the 14-component dashboard.")

    return "\n".join(lines)


def format_status(
    health: dict,
    queues: dict,
    failures: list[str],
    session: dict,
    routing: list | None = None,
    mcp: dict | None = None,
    executors: dict[str, str] | None = None,
) -> str:
    """Render the full /status dashboard.

    Parameters
    ----------
    health:
        Dict from ``HealthServer.collect_health()``, shape:
        ``{"status": str, "components": {name: {"status": str, ...}}, ...}``
    queues:
        Dict with keys ``messages``, ``self_edits``, ``wiki_staging``,
        ``hitl``, ``workorders`` — each an ``int | None``.
    failures:
        List of raw log-line strings (max 5) from the last 24 h.
    session:
        Dict with keys ``uptime``, ``messages``, ``halted``.
    routing:
        Optional list of routing decision records (issue #1540).
    mcp:
        Optional MCP-health snapshot dict (issue #1543).
    executors:
        Optional per-executor availability map (E.05 / #2012) — e.g.
        ``{"WORKTREE": "available", "E2B": "blocked: #416 credentials"}``.

    Returns
    -------
    str
        Discord-friendly multi-line string, ≤ 1800 chars (caller enforces).
    """
    if not isinstance(health, dict):
        health = {}
    if not isinstance(queues, dict):
        queues = {}
    if not isinstance(failures, list):
        failures = []
    if not isinstance(session, dict):
        session = {}

    label = _overall_label(health)
    components = health.get("components", {}) or {}

    sections: list[str] = []

    # --- Overall header ---
    sections.append(f"Overall: {label}")

    # --- Components block ---
    comp_lines = _render_components(components)
    if comp_lines:
        sections.append("Components:")
        sections.extend(comp_lines)
    else:
        sections.append("Components: (none)")

    # --- Queues block ---
    sections.append("Queues:")
    sections.extend(_render_queues(queues))

    # --- Failures block ---
    failure_lines = _render_failures(failures)
    if failure_lines:
        sections.extend(failure_lines)

    # --- Session block ---
    session_lines = _render_session(session)
    if session_lines:
        sections.extend(session_lines)

    # --- Executor availability block (E.05 / #2012) ---
    executor_lines = format_executor_section(
        executors if isinstance(executors, dict) else None
    )
    if executor_lines:
        sections.extend(executor_lines)

    # --- Recent Routing block (issue #1540) ---
    routing_lines = format_routing_section(routing if isinstance(routing, list) else None)
    if routing_lines:
        sections.extend(routing_lines)

    # --- MCP-health block (issue #1543) ---
    mcp_lines = format_mcp_section(mcp if isinstance(mcp, dict) else None)
    if mcp_lines:
        sections.extend(mcp_lines)

    out = "\n".join(sections)

    # Cap at 1800 chars; trim failures first, then hard truncate.
    if len(out) > 1800 and failures:
        trimmed_failures = failures[:3]
        failure_lines_trim = _render_failures(trimmed_failures)
        sections2: list[str] = []
        sections2.append(f"Overall: {label}")
        comp_lines2 = _render_components(components)
        if comp_lines2:
            sections2.append("Components:")
            sections2.extend(comp_lines2)
        else:
            sections2.append("Components: (none)")
        sections2.append("Queues:")
        sections2.extend(_render_queues(queues))
        if failure_lines_trim:
            sections2.extend(failure_lines_trim)
        if session_lines:
            sections2.extend(session_lines)
        if executor_lines:
            sections2.extend(executor_lines)
        if routing_lines:
            sections2.extend(routing_lines)
        if mcp_lines:
            sections2.extend(mcp_lines)
        out = "\n".join(sections2)

    return out
