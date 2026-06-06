"""OpenRouter route classification helpers for Zone 4 validation.

This module is intentionally policy-only. It does not change runtime routing;
VAL-15 owns enforcement after VAL-14 publishes the operator-facing matrix.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from teams._types import AgentSpec, DepartmentConfig

CapabilityName = Literal[
    "tool_calling",
    "mcp_config",
    "system_prompt",
    "tool_preauth",
]
RouteClassification = Literal["safe", "blocked", "hybrid"]

_OPENROUTER_PREFIX = "openrouter:"
_OPENROUTER_UNSUPPORTED_CAPABILITIES: frozenset[CapabilityName] = frozenset(
    {
        "tool_calling",
        "mcp_config",
        "system_prompt",
        "tool_preauth",
    }
)


@dataclass(frozen=True)
class Zone4OpenRouterRouteVerdict:
    """Classification result for one Zone 4 route under OpenRouter policy."""

    route: str
    backend: str
    classification: RouteClassification
    required_capabilities: tuple[CapabilityName, ...]
    missing_capabilities: tuple[CapabilityName, ...]
    reason: str


def classify_openrouter_zone4_route(
    config: DepartmentConfig,
) -> Zone4OpenRouterRouteVerdict:
    """Classify whether a Zone 4 config may route through OpenRouter.

    The campaign's OpenRouter backend is text-only: it can produce prose, but
    it has no validated tool-calling, MCP config, system-prompt-file, or
    tool-preauthorization surface. A Zone 4 route is therefore safe only when
    the config itself declares no delegation, no team tools, and no inherited
    MCP surface.
    """

    route = f"zone{config.zone}:{config.name}"
    if config.zone != 4:
        return Zone4OpenRouterRouteVerdict(
            route=route,
            backend="openrouter",
            classification="blocked",
            required_capabilities=(),
            missing_capabilities=(),
            reason="OpenRouter Zone 4 policy only applies to zone=4 routes.",
        )

    openrouter_agents = _openrouter_agent_names(config)
    if not openrouter_agents:
        return Zone4OpenRouterRouteVerdict(
            route=route,
            backend="openrouter",
            classification="blocked",
            required_capabilities=(),
            missing_capabilities=(),
            reason="No Zone 4 manager or specialist is configured for OpenRouter.",
        )

    required, reasons = _required_capabilities_for_zone4_route(config)
    missing = tuple(
        capability
        for capability in required
        if capability in _OPENROUTER_UNSUPPORTED_CAPABILITIES
    )
    if missing:
        return Zone4OpenRouterRouteVerdict(
            route=route,
            backend="openrouter",
            classification="blocked",
            required_capabilities=required,
            missing_capabilities=missing,
            reason=(
                "OpenRouter is text-only for this campaign; "
                + "; ".join(reasons)
            ),
        )

    if _uses_openrouter(config.manager):
        return Zone4OpenRouterRouteVerdict(
            route=route,
            backend="openrouter",
            classification="hybrid",
            required_capabilities=("tool_calling",),
            missing_capabilities=("tool_calling",),
            reason=(
                "OpenRouter can handle the text generation portion, but the "
                "current Zone 4 chief factory still exposes runtime chief "
                "tools. Use a hybrid/tool-free enforcement seam before a live "
                "OpenRouter Zone 4 route."
            ),
        )

    return Zone4OpenRouterRouteVerdict(
        route=route,
        backend="openrouter",
        classification="safe",
        required_capabilities=(),
        missing_capabilities=(),
        reason=(
            "OpenRouter text-only route: no delegation, no team tools, "
            "and MCP inheritance is disabled."
        ),
    )


def _openrouter_agent_names(config: DepartmentConfig) -> tuple[str, ...]:
    specs = (config.manager, *config.employees)
    return tuple(spec.name for spec in specs if _uses_openrouter(spec))


def _uses_openrouter(spec: AgentSpec) -> bool:
    return spec.model.startswith(_OPENROUTER_PREFIX)


def _required_capabilities_for_zone4_route(
    config: DepartmentConfig,
) -> tuple[tuple[CapabilityName, ...], tuple[str, ...]]:
    required: list[CapabilityName] = []
    reasons: list[str] = []

    if config.employees or config.constraints.expected_min_specialists > 0:
        required.append("tool_calling")
        reasons.append("delegate/list_specialists team workflow requires tool_calling")

    if (
        config.common_tools
        or config.department_tools
        or config.allowed_tools
        or config.manager.tools
    ):
        required.append("tool_calling")
        reasons.append("configured manager/team tools require tool_calling")

    if config.per_employee_tools or any(employee.tools for employee in config.employees):
        required.append("tool_calling")
        reasons.append("configured specialist tools require tool_calling")

    if config.mcp_mode != "deny_by_default" or config.mcp_allowed_servers:
        required.append("mcp_config")
        reasons.append("MCP inheritance or allowlist requires mcp_config")

    return _dedupe_capabilities(required), tuple(reasons)


def _dedupe_capabilities(
    capabilities: list[CapabilityName],
) -> tuple[CapabilityName, ...]:
    seen: set[CapabilityName] = set()
    deduped: list[CapabilityName] = []
    for capability in capabilities:
        if capability not in seen:
            seen.add(capability)
            deduped.append(capability)
    return tuple(deduped)


__all__ = [
    "Zone4OpenRouterRouteVerdict",
    "classify_openrouter_zone4_route",
]
