"""Drift tests for the VAPI tool/route registry (sprint audit-2026-05-16.F.04).

The registry at :mod:`bridge.voice.vapi_tool_registry` is the canonical
map from VAPI tool → route → implementation state. These tests fail
loudly if any of the three drift apart:

1. Every ``implemented=True`` HTTP route in the registry is actually
   registered on the aiohttp router.
2. Every VAPI route registered by
   ``_VapiDepartmentsRoutesMixin._register_vapi_departments_routes`` has
   a matching registry entry.
3. ``implemented=False`` function-call tools fail loud — their handlers
   return the ``not_wired`` payload, never silently 200 with fabricated
   data.

Premise check (2026-05-16): the audit's SW-1 / M-4 / SW-3 cluster called
out three drift seams — fabricated success payloads from stubbed VAPI
tools (E.01 already fixed), stale voice/VAPI docs vs current code, and
no canonical registry tying advertised tools to handlers. This file is
the drift gate. If any of these tests fail in CI, the registry, code, or
docs have diverged.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from aiohttp import web

from bridge.api.routes_vapi_departments import _VapiDepartmentsRoutesMixin
from bridge.voice.department_tools import DepartmentToolHandler
from bridge.voice.vapi_squad import build_bumba_squad
from bridge.voice.vapi_tool_registry import (
    VAPI_TOOLS,
    ToolKind,
    function_call_specs,
    http_route_specs,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _StubMixinHost(_VapiDepartmentsRoutesMixin):
    """Minimal host class for the routes mixin so it can register routes.

    The real APIServer class composes many mixins; for route-registration
    drift checking we only need ``_register_vapi_departments_routes`` and
    its dependencies (``_handle_vapi_webhook`` etc.) to be callable. The
    routes registration only references method handlers by attribute
    name, never invokes them at registration time, so we can stub them.
    """

    def __init__(self) -> None:
        self._departments = None
        self._bridge = None

    async def _handle_vapi_webhook(  # type: ignore[override]
        self, request: web.Request
    ) -> web.Response:
        return web.json_response({})


def _registered_routes(app: web.Application) -> set[tuple[str, str]]:
    """Return the set of (METHOD, path) tuples registered on the app.

    aiohttp's ``add_get`` synthesises a matching ``HEAD`` route on the
    same resource. We treat HEAD as a free freebie from the framework
    (no handler logic of its own) and exclude it from the drift surface
    — the registry only catalogues the methods we explicitly mount.
    """
    out: set[tuple[str, str]] = set()
    for resource in app.router.resources():
        # ``resource.get_info()`` returns ``{"path": ...}`` for plain
        # paths and ``{"formatter": "/.../{param}"}`` for dynamic
        # resources. We want the *formatter* shape because that's what
        # the registry encodes.
        info = resource.get_info()
        path = info.get("formatter") or info.get("path")
        if path is None:
            continue
        for route in resource:
            if route.method == "HEAD":
                continue
            out.add((route.method, path))
    return out


def _vapi_paths_from_app(app: web.Application) -> set[tuple[str, str]]:
    """Only the (METHOD, path) tuples under the VAPI surface."""
    return {
        (method, path)
        for (method, path) in _registered_routes(app)
        if path.startswith("/api/v1/departments")
        or path == "/api/v1/voice/webhook"
    }


# ---------------------------------------------------------------------------
# 1. Every implemented HTTP route in the registry is registered on the app
# ---------------------------------------------------------------------------


def test_every_implemented_http_route_is_registered_on_the_app() -> None:
    """Registry says implemented → aiohttp router has the route."""
    host = _StubMixinHost()
    app = web.Application()
    host._register_vapi_departments_routes(app)

    registered = _registered_routes(app)
    missing: list[str] = []
    for spec in http_route_specs():
        if not spec.implemented:
            continue
        if (spec.method, spec.route) not in registered:
            missing.append(f"{spec.method} {spec.route} ({spec.name})")

    assert not missing, (
        "Registry lists these as implemented HTTP routes but they are "
        "NOT registered on the aiohttp app: "
        + ", ".join(missing)
        + ". Either register them in "
        "_VapiDepartmentsRoutesMixin._register_vapi_departments_routes "
        "or update bridge.voice.vapi_tool_registry.VAPI_TOOLS."
    )


# ---------------------------------------------------------------------------
# 2. Every registered VAPI route has a matching registry entry
# ---------------------------------------------------------------------------


def test_no_registered_vapi_route_lacks_a_registry_entry() -> None:
    """aiohttp router has a VAPI route → registry has the entry."""
    host = _StubMixinHost()
    app = web.Application()
    host._register_vapi_departments_routes(app)

    registered_vapi = _vapi_paths_from_app(app)
    declared = {
        (s.method, s.route)
        for s in http_route_specs()
    }

    undeclared = registered_vapi - declared
    assert not undeclared, (
        "VAPI routes registered by "
        "_register_vapi_departments_routes but missing from "
        "bridge.voice.vapi_tool_registry.VAPI_TOOLS: "
        + ", ".join(sorted(f"{m} {p}" for (m, p) in undeclared))
        + ". Add a ToolSpec entry to keep docs and code in sync."
    )


# ---------------------------------------------------------------------------
# 3. Unimplemented function-call tools fail loud (no fabricated success)
# ---------------------------------------------------------------------------


def test_unimplemented_function_call_tools_return_not_wired() -> None:
    """Registry says NOT implemented → handler returns the not_wired
    payload, never silently 200 with fabricated data.

    Iterates every ``implemented=False`` function-call entry. For each,
    invokes the matching ``DepartmentToolHandler._handle_<name>`` method
    and asserts the response has ``success=False`` and the
    ``status='not_wired'`` marker. This is the discipline E.01
    installed; the test prevents regression.

    ``transfer_to_department`` is the one ``implemented=False`` entry
    with no handler at all; for that case the dispatcher's "Unknown
    tool" branch is the loud failure mode and is asserted here.
    """
    handler = DepartmentToolHandler()
    loop = asyncio.new_event_loop()
    try:
        for spec in function_call_specs():
            if spec.implemented:
                continue
            result: dict[str, Any] = loop.run_until_complete(
                handler.handle_tool_call("engineering", spec.name, {})
            )
            assert result.get("success") is False, (
                f"VAPI tool {spec.name!r} is registered as "
                f"implemented=False but returned success={result.get('success')!r}; "
                "stub handlers must fail loud (success=False)."
            )
            # Two acceptable failure shapes:
            # 1. The dispatcher's "Unknown tool" branch (no handler).
            # 2. The _not_wired payload from a handler that exists.
            assert (
                result.get("status") == "not_wired"
                or "Unknown tool" in str(result.get("error", ""))
            ), (
                f"VAPI tool {spec.name!r} returned success=False but "
                f"without the not_wired marker or Unknown-tool error: "
                f"{result!r}. Operators must be able to distinguish "
                "stub responses from real failures."
            )
    finally:
        loop.close()


# ---------------------------------------------------------------------------
# 4. Squad-advertised tools are all in the registry (drift between
#    vapi_squad.py and the registry)
# ---------------------------------------------------------------------------


def test_every_squad_advertised_tool_has_a_registry_entry() -> None:
    """vapi_squad.py advertises tool name → registry has the entry.

    Reads ``build_bumba_squad()`` and collects every tool name on every
    assistant. Asserts each name is present in
    :data:`VAPI_TOOLS`. If an assistant advertises a tool that the
    registry doesn't know about, this test fails — that's the
    advertised-but-unhandled drift the audit called out
    (``transfer_to_department`` was the original instance).
    """
    squad = build_bumba_squad()
    advertised: set[str] = set()
    for assistant in squad.assistants:
        advertised.update(assistant.tools)

    missing = advertised - set(VAPI_TOOLS.keys())
    assert not missing, (
        "VAPI squad advertises these tools but they are missing from "
        "bridge.voice.vapi_tool_registry.VAPI_TOOLS: "
        + ", ".join(sorted(missing))
        + ". Add a ToolSpec entry (implemented=False is fine for stubs)."
    )


# ---------------------------------------------------------------------------
# 5. Registry contains only the documented kinds
# ---------------------------------------------------------------------------


def test_registry_entries_have_consistent_shape() -> None:
    """Each ToolSpec is internally consistent — HTTP routes have a
    route + method, function-call tools do not.
    """
    for spec in VAPI_TOOLS.values():
        if spec.kind is ToolKind.HTTP_ROUTE:
            assert spec.route, f"HTTP route {spec.name!r} missing route"
            assert spec.method, f"HTTP route {spec.name!r} missing method"
            assert spec.route.startswith("/"), (
                f"HTTP route {spec.name!r} route must be a path: {spec.route!r}"
            )
        elif spec.kind is ToolKind.FUNCTION_CALL:
            assert spec.route == "", (
                f"Function-call tool {spec.name!r} must not have a route"
            )
            assert spec.method == "", (
                f"Function-call tool {spec.name!r} must not have a method"
            )
        else:
            pytest.fail(f"Unknown ToolKind on {spec.name!r}: {spec.kind!r}")


# ---------------------------------------------------------------------------
# 6. Implemented-handler sanity: every implemented=False function-call
#    name maps to an existing handler method OR is intentionally
#    unhandled (caught by test 4 already). Implemented=True function
#    tools must have a handler.
# ---------------------------------------------------------------------------


def test_implemented_function_call_tools_have_handlers() -> None:
    """If we ever flip a function-call tool to implemented=True, the
    handler MUST exist on DepartmentToolHandler. This catches the case
    where someone updates the registry but forgets to wire the handler.
    """
    handler = DepartmentToolHandler()
    for spec in function_call_specs():
        if not spec.implemented:
            continue
        method = getattr(handler, f"_handle_{spec.name}", None)
        assert method is not None and callable(method), (
            f"VAPI tool {spec.name!r} is registered as "
            "implemented=True but DepartmentToolHandler has no "
            f"_handle_{spec.name} method. Wire the handler or set "
            "implemented=False."
        )
