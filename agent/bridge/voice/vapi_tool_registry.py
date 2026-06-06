"""Canonical registry of VAPI tools, routes, and their implementation state.

Sprint audit-2026-05-16.F.04 (issue #2077).

Purpose
-------

There are two distinct VAPI surfaces in this codebase:

1. **HTTP routes** — aiohttp endpoints registered by
   ``_VapiDepartmentsRoutesMixin._register_vapi_departments_routes`` in
   :mod:`bridge.api.routes_vapi_departments`. These are the URLs VAPI calls
   into the bridge.

2. **Function-call tools** — JSON tool definitions advertised by each
   assistant in :mod:`bridge.voice.vapi_squad`. VAPI invokes these from
   inside a voice session; the bridge routes them to handlers in
   :class:`bridge.voice.department_tools.DepartmentToolHandler`.

Until the audit-2026-05-15.E.01 sweep, the second surface returned
fabricated success payloads ("PRs approved", "582 tests passed"). E.01
made every handler return ``not_wired``. SW-1 / SW-3 / M-4 surfaced a
related discipline gap: there was no single map from "advertised tool" to
"actual handler" to "real route", so it was easy for the three to drift.

This module is that single map. The test
:mod:`tests.test_vapi_route_registry` asserts it stays in sync with the
code on every CI run.

Adding a new VAPI tool or route
-------------------------------

1. Register the HTTP route in
   :meth:`_VapiDepartmentsRoutesMixin._register_vapi_departments_routes`
   (for inbound URLs) or add the handler method on
   :class:`DepartmentToolHandler` (for in-call function-call tools).
2. Add a :class:`ToolSpec` entry to :data:`VAPI_TOOLS` below.
3. The drift test will fail until both halves are present. Failure mode
   is loud, not silent — which is the whole point of this file.

What ``implemented`` means
--------------------------

- ``implemented=True``: handler returns real data sourced from the rest
  of the bridge (health snapshots, MCP config/monitor state, gh, pytest,
  session_manager, etc.). The first read-only function-call tools are
  now wired; write/execution tools remain gated.
- ``implemented=False``: handler exists but returns the explicit
  ``not_wired`` payload from :mod:`bridge.voice.department_tools`,
  or no handler exists and the dispatcher returns an unknown-tool
  error. Operators must not interpret these as live operational signals.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class ToolKind(str, Enum):
    """What surface a VAPI tool is exposed through.

    - HTTP_ROUTE: an aiohttp route registered on the APIServer.
    - FUNCTION_CALL: an in-call function-call tool dispatched by
      :class:`DepartmentToolHandler`.
    """

    HTTP_ROUTE = "http_route"
    FUNCTION_CALL = "function_call"


@dataclass(frozen=True)
class ToolSpec:
    """A single VAPI tool entry in the canonical registry.

    Attributes
    ----------
    name:
        Stable identifier. For HTTP routes, the URL path. For
        function-call tools, the tool function name.
    kind:
        Whether this is an HTTP route or an in-call function tool.
    route:
        For HTTP routes: the aiohttp path (with ``{param}`` placeholders
        preserved). For function-call tools: an empty string — function
        tools have no URL.
    method:
        For HTTP routes: ``GET`` / ``POST``. For function-call tools:
        an empty string.
    implemented:
        ``True`` if the handler returns real data. ``False`` if it
        returns the explicit ``not_wired`` payload.
    owner_issue:
        Stable follow-up identifier for ``implemented=False`` tools.
        Empty string for ``implemented=True`` tools. Mirrors
        :data:`bridge.voice.department_tools.TOOL_CAPABILITIES`.
    backend:
        Backend the real handler will route through for
        ``implemented=False`` tools (e.g. ``github``, ``pytest``).
        Empty string for ``implemented=True`` tools and for
        function-call tools with no handler. Mirrors
        :data:`bridge.voice.department_tools.TOOL_CAPABILITIES`.
    notes:
        Free-form context for the operator and future maintainers.
    """

    name: str
    kind: ToolKind
    route: str
    method: str
    implemented: bool
    notes: str
    owner_issue: str = ""
    backend: str = ""


# Order: HTTP routes first (4), then function-call tools (5+1). The
# function-call entry for ``transfer_to_department`` is intentionally
# listed even though no handler exists in DepartmentToolHandler —
# vapi_squad.py advertises it on the receptionist, so the registry must
# carry it so the drift test can flag it. ``implemented=False`` is the
# correct state.
VAPI_TOOLS: dict[str, ToolSpec] = {
    # ------------------------------------------------------------------
    # HTTP routes registered by _register_vapi_departments_routes
    # ------------------------------------------------------------------
    "list_departments": ToolSpec(
        name="list_departments",
        kind=ToolKind.HTTP_ROUTE,
        route="/api/v1/departments",
        method="GET",
        implemented=True,
        notes=(
            "Lists departments from DepartmentRegistry. Returns an empty "
            "list when departments are not wired (no 5xx)."
        ),
    ),
    "get_department": ToolSpec(
        name="get_department",
        kind=ToolKind.HTTP_ROUTE,
        route="/api/v1/departments/{dept}",
        method="GET",
        implemented=True,
        notes=(
            "Per-department metadata. 503 when departments are not "
            "wired, 404 for unknown department."
        ),
    ),
    "department_chat_completions": ToolSpec(
        name="department_chat_completions",
        kind=ToolKind.HTTP_ROUTE,
        route="/api/v1/departments/{dept}/chat/completions",
        method="POST",
        implemented=True,
        notes=(
            "OpenAI-compatible SSE chat completion gated by "
            "cfg.vapi.enabled. 403 when VAPI is not enabled for the "
            "named department."
        ),
    ),
    "vapi_webhook": ToolSpec(
        name="vapi_webhook",
        kind=ToolKind.HTTP_ROUTE,
        route="/api/v1/voice/webhook",
        method="POST",
        implemented=True,
        notes=(
            "VAPI inbound webhook (D1.7b). 401s without a valid "
            "X-VAPI-SECRET header (P2.3, audit C8). Route is registered "
            "by _VapiDepartmentsRoutesMixin; handler body lives in "
            "_WebhooksRoutesMixin._handle_vapi_webhook."
        ),
    ),
    # ------------------------------------------------------------------
    # Function-call tools advertised by vapi_squad.py.
    #
    # Every one of these returns ``not_wired`` until its real provider
    # is wired (E.01). Implemented=False is the correct state today.
    # ------------------------------------------------------------------
    "get_pr_status": ToolSpec(
        name="get_pr_status",
        kind=ToolKind.FUNCTION_CALL,
        route="",
        method="",
        implemented=True,
        notes=(
            "Engineering/QA assistant tool. Implemented via fixed gh CLI "
            "read-only commands with timeout and unavailable-dependency "
            "error shaping."
        ),
    ),
    "run_tests": ToolSpec(
        name="run_tests",
        kind=ToolKind.FUNCTION_CALL,
        route="",
        method="",
        implemented=True,
        notes=(
            "Engineering/QA assistant tool. Implemented through approved "
            "test lanes only (fast/offline/socket/readiness); no arbitrary "
            "shell input is accepted."
        ),
    ),
    "check_mcp_health": ToolSpec(
        name="check_mcp_health",
        kind=ToolKind.FUNCTION_CALL,
        route="",
        method="",
        implemented=True,
        notes=(
            "Ops assistant read-only tool. Returns injected MCP monitor "
            "state when wired, with a static canonical warm-MCP config "
            "check fallback."
        ),
    ),
    "get_system_status": ToolSpec(
        name="get_system_status",
        kind=ToolKind.FUNCTION_CALL,
        route="",
        method="",
        implemented=True,
        notes=(
            "Receptionist/Ops assistant read-only tool. Returns an injected "
            "bridge.health snapshot."
        ),
    ),
    "list_active_sessions": ToolSpec(
        name="list_active_sessions",
        kind=ToolKind.FUNCTION_CALL,
        route="",
        method="",
        implemented=True,
        notes=(
            "Engineering/Ops assistant tool. Implemented through an "
            "injected chief-session-store provider; returns unavailable "
            "when the store is not wired."
        ),
    ),
    "transfer_to_department": ToolSpec(
        name="transfer_to_department",
        kind=ToolKind.FUNCTION_CALL,
        route="",
        method="",
        implemented=False,
        owner_issue="",
        backend="",
        notes=(
            "Receptionist assistant tool advertised in vapi_squad.py "
            "but has NO handler in DepartmentToolHandler. VAPI's "
            "native call-transfer mechanic may resolve this at the "
            "VAPI layer rather than via a bridge handler. The drift "
            "test flags this as the canonical 'advertised but "
            "unhandled' case — keep implemented=False until either a "
            "handler is added or the squad config drops the tool."
        ),
    ),
}


def http_route_specs() -> list[ToolSpec]:
    """Return the HTTP-route entries in registry order."""
    return [s for s in VAPI_TOOLS.values() if s.kind is ToolKind.HTTP_ROUTE]


def function_call_specs() -> list[ToolSpec]:
    """Return the function-call entries in registry order."""
    return [s for s in VAPI_TOOLS.values() if s.kind is ToolKind.FUNCTION_CALL]


__all__ = [
    "ToolKind",
    "ToolSpec",
    "VAPI_TOOLS",
    "http_route_specs",
    "function_call_specs",
]
