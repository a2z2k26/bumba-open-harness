"""Pydantic AI agent factory for department teams."""

from __future__ import annotations

import logging
import os
import time
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any, Optional

from anthropic import AsyncAnthropic
from pydantic_ai import Agent, ModelRetry, RunContext
from pydantic_ai.models import Model
from pydantic_ai.models.anthropic import AnthropicModel
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.anthropic import AnthropicProvider
from pydantic_ai.providers.openai import OpenAIProvider

from bridge.capability_manifest import (
    CapabilityManifest,
    CapabilityManifestError,
    CapabilityReport,
    CapabilityRole,
    capability_grant_for_agent,
    compare_capabilities,
    filter_tools_for_manifest,
    load_capability_manifest,
)
from teams._agent_cache import GLOBAL_AGENT_CACHE, AgentCache
from teams._governance import load_governance_bundle
from teams._tool_registry import resolve_tools
from teams._types import (
    AgentSpec,
    BridgeDeps,
    DepartmentConfig,
    EmployeeResult,
    Roster,
    SpecialistSpec,
    Task,
    TeamOutput,
)

log = logging.getLogger(__name__)


ROSTER_PLACEHOLDER = "{{ROSTER}}"
DELEGATION_TASK_MAX_CHARS = 24_000
TEXT_ARTIFACT_MAX_BYTES = 200_000
_MANAGER_FALLBACK_COLLECTOR_ATTR = "_bumba_employee_results_collector"
_CAPABILITY_MANIFEST_ROOT = (
    Path(__file__).resolve().parents[1] / "config" / "capabilities" / "zone4"
)
_CAPABILITY_REPORT_ATTR = "_bumba_capability_report"
_CAPABILITY_TELEMETRY_ATTR = "_bumba_capability_telemetry"
_SPECIALIST_RUNTIME_TOOL_NAMES = ("surface", "write_artifact")
_MANAGER_RUNTIME_TOOL_NAMES = (
    "list_specialists",
    "delegate",
    "acknowledge_directive",
    "surface",
    "write_artifact",
)
_PLACEHOLDER_SPECIALIST_NAMES = frozenset(
    {
        "...",
        "<specialist>",
        "<specialist_name>",
        "agent",
        "name",
        "specialist",
        "specialist name",
        "specialist_name",
        "string",
    }
)

ROSTER_BLOCK_TEMPLATE = """## Your Team

You are the {chief_name}. You have {n} specialist{plural} available. Delegate
using the `delegate(specialist, task, constraints, deadline_seconds)` tool.
Use `list_specialists()` to introspect your roster at any time.

{specialist_lines}

Delegation doctrine:
{delegation_doctrine}
- Synthesize specialist outputs into a single coherent answer; never paste raw.
- Carry the directive's correlation_id into every delegation."""


def _format_specialist_line(spec: SpecialistSpec) -> str:
    """Render one specialist as a roster bullet for the chief's prompt."""
    when = spec.when_to_call.strip() or spec.role.strip() or spec.name
    return f"- **{spec.name}** — {when}"


def _format_delegation_doctrine(expected_min_specialists: int) -> str:
    if expected_min_specialists > 0:
        plural = "s" if expected_min_specialists != 1 else ""
        return (
            f"- You MUST delegate to at least {expected_min_specialists} "
            f"specialist{plural} before final synthesis.\n"
            "- Do not answer directly until that delegation floor is satisfied.\n"
            "- If no specialist fits, surface a scope_request instead of a direct answer."
        )
    return (
        "- Do not fire a specialist unless the task genuinely requires their expertise.\n"
        "- If no specialist fits, answer directly or surface a scope_request."
    )


def _safe_artifact_relpath(agent_name: str, kind: str, filename: str) -> Path:
    agent_segment = _artifact_segment(agent_name, label="agent name")
    kind_segment = _artifact_segment(kind, label="artifact kind")
    clean_filename = filename.strip().replace("\\", "/")
    filename_path = Path(clean_filename)
    if (
        not clean_filename
        or filename_path.is_absolute()
        or ".." in filename_path.parts
    ):
        raise ValueError("artifact filename must stay inside the run workspace")
    rel = Path(agent_segment) / kind_segment / filename_path
    if rel.is_absolute() or ".." in rel.parts:
        raise ValueError("artifact filename must stay inside the run workspace")
    return rel


def _artifact_segment(value: str, *, label: str) -> str:
    clean = value.strip().replace("\\", "/")
    if not clean or "/" in clean or ".." in Path(clean).parts:
        raise ValueError(f"{label} must stay inside the run workspace")
    chars: list[str] = []
    for char in clean.lower():
        if char.isalnum():
            chars.append(char)
        elif char in {"-", "_", "."}:
            chars.append(char)
        elif char.isspace():
            chars.append("-")
    segment = "".join(chars).strip("-_.")
    if not segment:
        raise ValueError(f"{label} must stay inside the run workspace")
    return segment


def _load_capability_manifest_for_config(
    config: DepartmentConfig,
) -> CapabilityManifest | None:
    if config.zone != 4:
        return None
    if not config.capability_manifest_enforced:
        return None

    path = _CAPABILITY_MANIFEST_ROOT / f"{config.name}.yaml"
    if not path.exists():
        return None

    try:
        manifest = load_capability_manifest(path)
    except (CapabilityManifestError, OSError) as exc:
        log.warning(
            "capability.manifest_load_failed department=%s path=%s error=%s",
            config.name,
            path,
            exc,
        )
        return None

    if manifest.department != config.name:
        log.warning(
            "capability.manifest_department_mismatch config=%s manifest=%s path=%s",
            config.name,
            manifest.department,
            path,
        )
        return None
    return manifest


def _registered_tool_names(agent: Agent[BridgeDeps, Any]) -> tuple[str, ...]:
    toolset = getattr(agent, "_function_toolset", None)
    tools = getattr(toolset, "tools", {})
    if not isinstance(tools, dict):
        return ()
    return tuple(str(name) for name in tools)


def _effective_mcp_servers(config: DepartmentConfig) -> tuple[str, ...]:
    if config.mcp_allowed_servers:
        return config.mcp_allowed_servers
    if config.mcp_mode == "deny_by_default":
        return ()
    return ("<permissive:inherit-default>",)


def _capability_manifest_applies_to_agent(
    manifest: CapabilityManifest,
    *,
    agent_name: str,
    role: CapabilityRole,
) -> bool:
    if manifest.mode != "strict":
        return True
    if role == "chief":
        return agent_name in manifest.chief
    return agent_name in manifest.specialists


def _filter_tool_names_for_capability_manifest(
    *,
    config: DepartmentConfig,
    spec: AgentSpec,
    role: CapabilityRole,
    actual_tools: tuple[str, ...],
    manifest: CapabilityManifest | None,
) -> tuple[str, ...]:
    if manifest is None:
        return actual_tools
    if not _capability_manifest_applies_to_agent(
        manifest,
        agent_name=spec.name,
        role=role,
    ):
        return actual_tools

    grant = capability_grant_for_agent(
        manifest,
        agent_name=spec.name,
        role=role,
    )
    filtered = filter_tools_for_manifest(
        actual_tools=actual_tools,
        grant=grant,
        mode=manifest.mode,
    )
    if manifest.mode == "strict" and filtered != actual_tools:
        removed = tuple(tool for tool in actual_tools if tool not in set(filtered))
        log.info(
            "capability.strict_filtered department=%s agent=%s role=%s removed=%s",
            config.name,
            spec.name,
            role,
            list(removed),
        )
    return filtered


def _attach_capability_report(
    agent: Agent[BridgeDeps, Any],
    *,
    config: DepartmentConfig,
    spec: AgentSpec,
    role: CapabilityRole,
    manifest: CapabilityManifest | None,
) -> CapabilityReport | None:
    if manifest is None:
        return None
    if not _capability_manifest_applies_to_agent(
        manifest,
        agent_name=spec.name,
        role=role,
    ):
        return None

    report = compare_capabilities(
        department=config.name,
        agent_name=spec.name,
        role=role,
        actual_tools=_registered_tool_names(agent),
        actual_skills=spec.skills,
        actual_mcp_servers=_effective_mcp_servers(config),
        manifest=manifest,
    )
    telemetry = report.telemetry_fields()
    setattr(agent, _CAPABILITY_REPORT_ATTR, report)
    setattr(agent, _CAPABILITY_TELEMETRY_ATTR, telemetry)

    if report.mode == "strict" and report.missing_tools:
        missing = ", ".join(report.missing_tools)
        raise CapabilityManifestError(
            f"{report.department}/{report.agent}: strict capability manifest "
            f"missing required tools: {missing}"
        )

    if report.mode == "report_only" and report.has_violation:
        log.info(
            "capability.report_only_violation department=%s agent=%s role=%s "
            "extra_tools=%s missing_tools=%s extra_skills=%s missing_skills=%s "
            "extra_mcp_servers=%s missing_mcp_servers=%s",
            report.department,
            report.agent,
            report.role,
            list(report.extra_tools),
            list(report.missing_tools),
            list(report.extra_skills),
            list(report.missing_skills),
            list(report.extra_mcp_servers),
            list(report.missing_mcp_servers),
        )
    return report


def capability_telemetry_fields(
    agents: Iterable[Agent[BridgeDeps, Any]],
) -> tuple[tuple[str, str], ...]:
    fields: list[tuple[str, str]] = []
    for agent in agents:
        telemetry = getattr(agent, _CAPABILITY_TELEMETRY_ATTR, ())
        fields.extend(
            (str(key), str(value))
            for key, value in telemetry
            if key and value
        )
    return tuple(fields)


def _is_placeholder_specialist_name(value: str) -> bool:
    """Return True for schema/example placeholders that are never roster names."""
    normalized = " ".join(str(value).strip().lower().split())
    return normalized in _PLACEHOLDER_SPECIALIST_NAMES


def _truncate_middle(text: str, *, max_chars: int, marker: str) -> str:
    """Bound a string while preserving the leading and trailing context."""
    if len(text) <= max_chars:
        return text
    if max_chars <= len(marker):
        return text[:max_chars]

    keep_chars = max_chars - len(marker)
    head_chars = keep_chars // 2
    tail_chars = keep_chars - head_chars
    return f"{text[:head_chars]}{marker}{text[-tail_chars:]}"


def _cap_delegation_task(text: str) -> str:
    """Prevent a chief from forwarding unbounded context to a specialist."""
    marker = (
        "\n\n"
        f"[...delegation task truncated to {DELEGATION_TASK_MAX_CHARS} "
        f"chars from {len(text)} chars; preserved head and tail...]\n\n"
    )
    return _truncate_middle(
        text,
        max_chars=DELEGATION_TASK_MAX_CHARS,
        marker=marker,
    )


def _format_roster_block(
    roster: Roster,
    *,
    expected_min_specialists: int = 0,
) -> str:
    """Render a Roster as the deterministic markdown block the chief reads."""
    n = len(roster.specialists)
    plural = "s" if n != 1 else ""
    lines = "\n".join(_format_specialist_line(s) for s in roster.specialists)
    return ROSTER_BLOCK_TEMPLATE.format(
        chief_name=roster.chief_name,
        n=n,
        plural=plural,
        specialist_lines=lines or "(no specialists configured)",
        delegation_doctrine=_format_delegation_doctrine(expected_min_specialists),
    )


def _inject_roster_into_prompt(
    prompt: str,
    roster: Roster,
    *,
    expected_min_specialists: int = 0,
) -> str:
    """Substitute {{ROSTER}} in prompt; append with warning if placeholder absent.

    Sprint 19 (Phase 5A): the spec requires both code paths to keep the chief
    operational even if a department's prompt file forgot the placeholder.
    The warning makes the omission visible; behavior degrades gracefully.
    """
    block = _format_roster_block(
        roster,
        expected_min_specialists=expected_min_specialists,
    )
    if ROSTER_PLACEHOLDER in prompt:
        return prompt.replace(ROSTER_PLACEHOLDER, block)
    log.warning(
        "roster.placeholder_missing chief=%s — appending roster at end of prompt",
        roster.chief_name,
    )
    sep = "\n\n---\n\n" if prompt.strip() else ""
    return f"{prompt}{sep}{block}"


def _filter_cross_vendor_employees(
    config: DepartmentConfig, cross_vendor_enabled: bool
) -> tuple[AgentSpec, ...]:
    """Return ``config.employees`` with cross-vendor seats optionally stripped.

    Sprint P3.3 / issue #1724 — wires ``BridgeConfig.board_cross_vendor_enabled``
    into the factory. When the flag is OFF (default), the 3 ``adapter:
    openrouter`` seats on the Strategy Board (`board-cross-vendor-strategist`,
    `board-openrouter-generalist`, `board-systems-thinker`) are omitted from
    both the chief's roster and the employee agent map. When ON, every
    YAML-declared worker is materialised.

    Scope is intentionally narrow:

    - The filter only fires for the ``board`` department. Other departments
      pass through unchanged regardless of flag state — no department other
      than ``board`` currently ships cross-vendor seats, and gating them
      department-wide would surprise callers.
    - The filter is keyed on ``AgentSpec.adapter == "openrouter"``, not on
      worker name. New cross-vendor seats added to board.yaml inherit the
      gate automatically.

    Returns a fresh tuple — callers receive new collection identities so
    the immutability discipline of frozen ``DepartmentConfig`` is preserved.
    """
    if cross_vendor_enabled or config.name != "board":
        return config.employees
    return tuple(emp for emp in config.employees if emp.adapter != "openrouter")


def _specialist_spec_from_employee(emp: Any) -> SpecialistSpec:
    """Build one SpecialistSpec from an employee AgentSpec.

    Shared by the YAML-base path and the RR.2 registry overlay so a
    registered specialist is field-identical to a YAML built-in (same
    ``when_to_call`` → ``role`` → ``name`` fallback chain).
    """
    return SpecialistSpec(
        name=emp.name,
        role=emp.role,
        expertise_summary=emp.expertise_summary or emp.role,
        when_to_call=emp.when_to_call or emp.role or emp.name,
        domain_write_paths=tuple(emp.deny_write_paths),
    )


def roster_from_department_config(
    config: DepartmentConfig,
    *,
    cross_vendor_enabled: bool = True,
    registered: tuple[Any, ...] = (),
) -> Roster:
    """Build a Roster from a DepartmentConfig in YAML order.

    Sprint 19 (Phase 5A): each employee becomes a SpecialistSpec; the chief
    name comes from ``config.manager.name``. Falls back from
    ``when_to_call`` → ``role`` → ``name`` so an unpopulated YAML still
    produces a usable (if degraded) roster.

    Sprint P3.3 (issue #1724): ``cross_vendor_enabled`` mirrors
    ``BridgeConfig.board_cross_vendor_enabled``. Default ``True`` preserves
    pre-#1724 behaviour for ad-hoc callers (tests, scripts) — production
    wiring in ``teams/_team.py::_build`` consults the BridgeConfig and
    passes the runtime value. Only the ``board`` department is affected;
    see ``_filter_cross_vendor_employees`` for the policy details.

    Sprint RR.2 (issue #2593): ``registered`` is the operator's runtime
    overlay — a tuple of ``RegisteredSpecialist`` (each carrying an
    ``agent_ref`` naming an existing employee in this department). Each is
    resolved to a SpecialistSpec via the SAME employee config the YAML path
    uses and APPENDED after the YAML-derived specialists (YAML order
    preserved, built-ins first). Empty (the default) is byte-identical to the
    pre-RR.2 behaviour. A registered name that collides with a built-in is
    skipped (registration already rejects this at write time — belt-and-
    suspenders so a built-in always wins). An ``agent_ref`` that no longer
    resolves (e.g. the YAML employee was removed after registration) is
    skipped with a WARNING rather than producing a broken roster entry.
    """
    employees = _filter_cross_vendor_employees(config, cross_vendor_enabled)
    specialists = tuple(
        _specialist_spec_from_employee(emp) for emp in employees
    )

    if registered:
        # Resolve each registry overlay row against this department's employee
        # configs. Index by name once; append resolved, non-colliding entries.
        by_name = {emp.name: emp for emp in config.employees}
        builtin_names = {s.name for s in specialists}
        overlay: list[SpecialistSpec] = []
        for reg in registered:
            if reg.name in builtin_names:
                # Built-in wins; registration should have rejected this.
                continue
            emp = by_name.get(reg.agent_ref)
            if emp is None:
                log.warning(
                    "roster_overlay.unresolvable_agent_ref department=%s "
                    "name=%s agent_ref=%s — skipping",
                    config.name, reg.name, reg.agent_ref,
                )
                continue
            # The registered specialist takes the operator-chosen ``name`` but
            # inherits role/expertise/when_to_call/write-paths from the
            # referenced employee config.
            spec = _specialist_spec_from_employee(emp)
            overlay.append(
                SpecialistSpec(
                    name=reg.name,
                    role=spec.role,
                    expertise_summary=spec.expertise_summary,
                    when_to_call=spec.when_to_call,
                    domain_write_paths=spec.domain_write_paths,
                )
            )
        specialists = specialists + tuple(overlay)

    return Roster(
        department=config.name,
        chief_name=config.manager.name,
        specialists=specialists,
    )


def _dedupe(names: tuple[str, ...]) -> tuple[str, ...]:
    """Remove duplicate tool names while preserving order."""
    seen: set[str] = set()
    result: list[str] = []
    for n in names:
        if n not in seen:
            seen.add(n)
            result.append(n)
    return tuple(result)


_OPENROUTER_PREFIX = "openrouter:"
_OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
_OPENAI_PREFIX = "openai:"
_OPENAI_BILLED_SURFACE = "openai-api"
_ANTHROPIC_OAUTH_PREFIX = "anthropic-oauth:"
_CODEX_EXEC_PREFIX = "codex-exec:"
_ANTHROPIC_OAUTH_MAX_RETRIES = 5
_AGENT_ROOT = Path(__file__).resolve().parent.parent
_REPO_ROOT = _AGENT_ROOT.parent

# Sprint zone4-warmth.E.01 (#2301): Anthropic prompt-caching cohort.
#
# OpenRouter forwards ``cache_control`` annotations through to Anthropic when
# the underlying model is ``anthropic/*``. The breakpoint goes on the LAST
# block of the system message; Anthropic caches the prefix server-side for
# 5 minutes and charges 90% less on cache hits.
#
# Scope is intentionally narrow — only ``design-visual-designer`` carries the
# marker today. The Chinese-cohort cheap-frontier models (Qwen, GLM, Kimi,
# DeepSeek) routed via OpenRouter do not honor ``cache_control`` and adding
# it would be wasted bytes at best.
_CACHE_CONTROL_AGENTS: frozenset[str] = frozenset({"design-visual-designer"})
_ANTHROPIC_MODEL_PREFIX = "anthropic/"


class CachingOpenRouterChatModel(OpenAIChatModel):
    """``OpenAIChatModel`` subclass that injects ``cache_control`` on the
    last system-prompt block when routing Anthropic models through OpenRouter.

    Why a subclass: pydantic-ai 1.80's ``OpenAIChatModel`` emits system
    messages as plain-string content (see ``openai.py::_map_messages``) and
    explicitly filters out ``CachePoint`` markers (line 1422-24, comment:
    "OpenAI doesn't support prompt caching via CachePoint, so we filter it
    out"). Neither ``extra_body`` nor ``OpenAIChatModelSettings`` exposes a
    per-message annotation surface. The only seam that lets us emit the
    OpenRouter/Anthropic-compatible structured-content form
    ``[{"type": "text", "text": "...", "cache_control": {"type": "ephemeral"}}]``
    is to post-process ``_map_messages`` output.

    Construction restricted to ``design-visual-designer`` via
    ``_resolve_model``; the rest of the fleet keeps the plain
    ``OpenAIChatModel`` byte-for-byte.
    """

    async def _map_messages(self, messages, model_request_parameters):  # type: ignore[override]
        mapped = await super()._map_messages(messages, model_request_parameters)
        return _annotate_last_system_block_with_cache_control(mapped)


def _annotate_last_system_block_with_cache_control(
    mapped: list,
) -> list:
    """Convert the last ``role=system`` message's content from string to a
    structured ``[{type, text, cache_control}]`` block list.

    Idempotent: if the last system message's content is already a list, the
    helper appends ``cache_control`` to the final block only. If there is no
    system message in the request, the helper is a no-op.

    The mapped list is mutated in place (it is the freshly-built list owned
    by ``super()._map_messages`` and not shared) and returned for chainability.
    """
    last_idx = -1
    for i, msg in enumerate(mapped):
        if isinstance(msg, dict) and msg.get("role") == "system":
            last_idx = i
    if last_idx < 0:
        return mapped
    sys_msg = mapped[last_idx]
    content = sys_msg.get("content")
    if isinstance(content, str):
        sys_msg["content"] = [
            {
                "type": "text",
                "text": content,
                "cache_control": {"type": "ephemeral"},
            }
        ]
    elif isinstance(content, list) and content:
        last_block = content[-1]
        if isinstance(last_block, dict):
            last_block["cache_control"] = {"type": "ephemeral"}
    return mapped


def _resolve_agent_config_path(path_value: str) -> Path:
    """Resolve YAML config paths from either repo-root or agent/ CWD."""
    path = Path(path_value).expanduser()
    if path.is_absolute():
        return path

    candidates = [path]
    parts = path.parts
    if parts and parts[0] == "agent":
        candidates.append(_AGENT_ROOT.joinpath(*parts[1:]))
    candidates.append(_AGENT_ROOT / path)
    candidates.append(_REPO_ROOT / path)

    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


def _resolve_openrouter_api_key() -> str:
    """Read ``BridgeConfig.openrouter_api_key`` if importable, else env var.

    Mirrors ``teams._team._resolve_board_cross_vendor_flag`` — production
    callers go through ``BridgeConfig`` (which loads from ``.secrets``);
    lightweight ``teams``-only unit fixtures may not have the bridge package
    available, in which case we fall back to the ``OPENROUTER_API_KEY``
    environment variable, then to empty string. Empty string means the
    provider is constructed with no credential — the model call fails at
    invocation time with a clear 401, not a silent at-construction crash.
    """
    try:
        from bridge.config import BridgeConfig

        key = BridgeConfig().openrouter_api_key or ""
        if key:
            return key
    except Exception:  # noqa: BLE001 — see docstring rationale
        pass
    import os

    return os.environ.get("OPENROUTER_API_KEY", "")


class MissingProviderCredentialError(RuntimeError):
    """Raised when an explicit model provider prefix lacks its credential."""


def _resolve_openai_api_key() -> str:
    """Read the OpenAI API key required for explicit ``openai:*`` models."""
    api_key = os.environ.get("OPENAI_API_KEY", "")
    if not api_key:
        raise MissingProviderCredentialError(
            "OpenAI provider credential missing: set OPENAI_API_KEY for "
            "openai:* Zone 4 models"
        )
    return api_key


def _resolve_claude_oauth_token() -> str:
    """Read the freshest Claude OAuth access token available to this process.

    TokenRefresher persists rotations back into ``.secrets``. RuntimeSecrets
    caches parses by default, so this helper explicitly reloads before reading
    to avoid pinning a stale bearer token in long-lived agent objects.
    """
    try:
        from bridge.runtime_secrets import get_runtime_secrets

        runtime_secrets = get_runtime_secrets()
        runtime_secrets.reload()
        token = runtime_secrets.claude_oauth_token(required=False)
        if token:
            return token
    except Exception as exc:  # noqa: BLE001 — optional canary path fallback
        log.debug("claude_oauth_token.runtime_secrets_unavailable: %s", exc)

    return os.environ.get("CLAUDE_CODE_OAUTH_TOKEN", "")


class _RuntimeOAuthAsyncAnthropic(AsyncAnthropic):
    """AsyncAnthropic client whose auth headers read a fresh OAuth token.

    ``AsyncAnthropic(auth_token=...)`` captures the token at construction
    time. Zone 4 agents can be cached for hours, so a static token would go
    stale after the bridge refreshes OAuth. This canary client keeps the
    PydanticAI provider shape while consulting a token provider whenever the
    SDK builds auth headers.

    It also refuses to emit ``X-Api-Key`` even when ``ANTHROPIC_API_KEY`` is
    present in the daemon environment. The canary is specifically for Claude
    OAuth, not mixed API-key + bearer auth. The retry headroom is higher than
    the SDK default so transient 429s can recover before manager fallback.
    """

    def __init__(self, token_provider: Callable[[], str]) -> None:
        self._bumba_token_provider = token_provider
        super().__init__(
            api_key=None,
            auth_token="",
            max_retries=_ANTHROPIC_OAUTH_MAX_RETRIES,
        )
        # ``api_key=None`` still consults ANTHROPIC_API_KEY during SDK
        # construction. Clear it so base/client debugging state reflects the
        # same OAuth-only contract enforced by ``_api_key_auth`` below.
        self.api_key = None

    @property
    def _api_key_auth(self) -> dict[str, str]:
        return {}

    @property
    def _bearer_auth(self) -> dict[str, str]:
        token = self._bumba_token_provider()
        if not token:
            return {}
        return {"Authorization": f"Bearer {token}"}


def _resolve_anthropic_oauth_model(spec: AgentSpec) -> AnthropicModel:
    """Build an AnthropicModel backed by Claude OAuth bearer auth.

    This is intentionally activated only by the explicit
    ``anthropic-oauth:`` model prefix. No production team YAML uses the prefix
    yet; it exists so the operator can canary one role without changing the
    OpenRouter fleet contract.
    """
    model_name = spec.model[len(_ANTHROPIC_OAUTH_PREFIX):]
    client = _RuntimeOAuthAsyncAnthropic(_resolve_claude_oauth_token)
    return AnthropicModel(
        model_name=model_name,
        provider=AnthropicProvider(anthropic_client=client),
    )


def _resolve_openai_model(spec: AgentSpec) -> OpenAIChatModel:
    """Build the Z4-16 OpenAI API canary model for explicit ``openai:*``."""
    model_name = spec.model[len(_OPENAI_PREFIX):]
    api_key = _resolve_openai_api_key()
    log.info(
        "model.provider_resolved agent=%s provider=openai "
        "billed_surface=%s model=%s",
        spec.name,
        _OPENAI_BILLED_SURFACE,
        model_name,
    )
    return OpenAIChatModel(
        model_name=model_name,
        provider=OpenAIProvider(api_key=api_key),
    )


def _resolve_codex_model(spec: AgentSpec) -> Model:
    """Build the Z4-17a codex-exec CLI model for explicit ``codex-exec:*``.

    Strips the ``codex-exec:`` prefix and returns a ``CodexExecModel`` that
    shells out to ``codex exec --json``. Unlike the OpenRouter/OpenAI HTTP
    branches, codex is a local CLI subprocess — see ``teams._codex_model`` for
    the message-flattening + subprocess contract. No credential is read at
    construction time: codex reads its own ``~/.codex/auth.json``, so a missing
    auth surfaces at invocation (subprocess non-zero exit), not here.
    """
    from teams._codex_model import CodexExecModel

    model_name = spec.model[len(_CODEX_EXEC_PREFIX):]
    log.info(
        "model.provider_resolved agent=%s provider=codex-exec model=%s",
        spec.name,
        model_name,
    )
    return CodexExecModel(model_name)


def _resolve_model(spec: AgentSpec) -> Model | str:
    """Resolve ``spec.model`` to a pydantic-ai ``Model`` or pass-through string.

    Sprint 04.07 (#1961) — completes the wiring left orphaned by Sprint 04.05.
    ``spec.adapter`` was declared and validated at config load (Sprint 04.05)
    but never consulted at construction time, so every specialist whose
    ``model:`` starts with ``openrouter:`` was being handed verbatim to
    pydantic-ai's default Anthropic provider — failing at run time, swallowed
    by the chief's tool-call loop, surfacing only as Gate 8 floor violations.

    Strategy: prefix-based routing. If ``spec.model`` starts with
    ``openrouter:``, strip the prefix and return an ``OpenAIModel`` pointed
    at OpenRouter's OpenAI-compatible chat-completions endpoint. If it starts
    with ``openai:``, strip the prefix and route through the explicit OpenAI
    API canary path certified by Z4-15. If it starts with ``codex-exec:``
    (Z4-17a #2566), strip the prefix and return a ``CodexExecModel`` that
    shells out to the ``codex exec --json`` CLI. Otherwise return the raw
    string so
    pydantic-ai's existing resolution path (``anthropic:*``, bare-name
    shortcuts via ``_MODEL_PREFIX_MAP`` in ``_config.py``) keeps working
    byte-for-byte.

    The ``spec.adapter`` field is intentionally ignored here: with prefix-
    based routing the model string is the source of truth, and the 6
    paradoxical ``adapter:"claude"`` + ``model:"openrouter:*"`` pairs across
    6 department YAMLs (board, qa, design, strategy, ops, job_search) start
    working without YAML surgery. A separate validator at config-load time
    warns on the mismatch so the contradiction surfaces in CI rather than
    hides in production.
    """
    if spec.model.startswith(_ANTHROPIC_OAUTH_PREFIX):
        return _resolve_anthropic_oauth_model(spec)

    if spec.model.startswith(_OPENAI_PREFIX):
        return _resolve_openai_model(spec)

    if spec.model.startswith(_CODEX_EXEC_PREFIX):
        return _resolve_codex_model(spec)

    if not spec.model.startswith(_OPENROUTER_PREFIX):
        return spec.model

    model_name = spec.model[len(_OPENROUTER_PREFIX):]
    api_key = _resolve_openrouter_api_key()
    # ``OpenAIChatModel`` (not the deprecated ``OpenAIModel`` alias) because
    # OpenRouter exposes the OpenAI Chat-Completions API specifically, not
    # OpenAI's newer Responses API. pydantic-ai 1.80+ DeprecationWarnings
    # the bare ``OpenAIModel`` for this exact reason.
    #
    # Sprint zone4-warmth.E.01 (#2301): one carve-out. When the spec is the
    # singular Claude exception (``design-visual-designer`` routed at
    # ``anthropic/*``), construct ``CachingOpenRouterChatModel`` so that the
    # last system-prompt block carries an ``ephemeral`` cache_control marker.
    # OpenRouter forwards it to Anthropic for 5-minute server-side caching at
    # ~10% input-token cost on hits. Every other agent stays on the plain
    # ``OpenAIChatModel`` byte-for-byte.
    model_cls = (
        CachingOpenRouterChatModel
        if spec.name in _CACHE_CONTROL_AGENTS
        and model_name.startswith(_ANTHROPIC_MODEL_PREFIX)
        else OpenAIChatModel
    )
    return model_cls(
        model_name=model_name,
        provider=OpenAIProvider(
            base_url=_OPENROUTER_BASE_URL,
            api_key=api_key,
        ),
    )


def _load_expertise(spec: AgentSpec) -> str:
    """Load expertise content for an agent spec, returning empty string if absent.

    Sprint 04.03: AgentSpec.expertise_path is captured from YAML at config-load
    time but was never read by _load_system_prompt. This helper closes the loop
    so the 40 updatable + 6 read-only expertise files at config/expertise/
    become live runtime context. Missing files log a warning and continue
    (expertise is enhancement, not requirement).
    """
    if not spec.expertise_path:
        return ""
    path = _resolve_agent_config_path(spec.expertise_path)
    if not path.exists():
        log.warning("Expertise file missing for %s: %s", spec.name, path)
        return ""
    content = path.read_text(encoding="utf-8").strip()
    if not content:
        return ""
    return f"## Expertise\n\n{content}"


# ---------------------------------------------------------------------------
# Sprint 24 (Phase 5D) — tier doctrine injection
# ---------------------------------------------------------------------------
#
# Every agent's system prompt is now prepended with a tier-appropriate
# doctrine block read from docs/doctrine/. The doctrine names what the agent
# does, what it never does, and the consequences of silent failure — turning
# the Phase 5 protocol from optional to enforced-by-behavior.
#
# FALLBACK_DOCTRINE provides the minimum viable instruction if the on-disk
# file is missing. We log an error and continue rather than crash agent
# construction — a missing doctrine file is a bug worth fixing, but a hard
# crash on startup makes every agent unreachable, which is strictly worse.

_DOCTRINE_ROOT = Path(__file__).resolve().parent.parent / "docs" / "doctrine"
_GOVERNANCE_ROOT = Path(__file__).resolve().parent.parent / "config" / "governance"
_DOCTRINE_LINE_CAP = 60

# Hard-coded fallbacks. Kept compact so even degraded agents have the
# load-bearing rule in their prompt: never go silent on failure.
FALLBACK_DOCTRINE: dict[str, str] = {
    "main": (
        "# Main Agent Doctrine (fallback)\n\n"
        "You are Bumba — direct chiefs via direct(); never bypass to a "
        "specialist. Read /surfaces unread before responding to the operator. "
        "Silent failure is the worst failure mode."
    ),
    "chief": (
        "# Chief Doctrine (fallback)\n\n"
        "Acknowledge directives FIRST via acknowledge_directive(). Delegate "
        "via delegate(specialist, task). Synthesise, never paste raw. "
        "Surface BLOCKER / POLICY_Q upward; never swallow specialist failures."
    ),
    "specialist": (
        "# Specialist Doctrine (fallback)\n\n"
        "Execute the task. Emit at least one surface(kind='result') per task "
        "before returning. Surface BLOCKER if you cannot proceed. Never "
        "delegate further; never go silent."
    ),
}


def _load_doctrine(tier: str) -> str:
    """Read the per-tier doctrine file from docs/doctrine/.

    ``tier`` is one of ``"main"``, ``"chief"``, ``"specialist"``. The
    on-disk filename is ``main-agent.md`` for the main tier and
    ``<tier>s.md`` for the others, matching ``docs/doctrine/`` layout.

    Returns the file contents on success. On a missing file or read
    error returns ``FALLBACK_DOCTRINE[tier]`` and logs an error so the
    operator can fix the gap. Files exceeding ``_DOCTRINE_LINE_CAP``
    are loaded but a warning is logged (operator should trim).
    """
    if tier not in FALLBACK_DOCTRINE:
        # Defensive: an unknown tier means the caller has a bug. Refuse
        # silently degrading to a generic doctrine — this is a code path,
        # not a config path, and should be loud.
        raise ValueError(
            f"Unknown doctrine tier {tier!r}; expected one of: "
            f"{sorted(FALLBACK_DOCTRINE.keys())}"
        )
    filename = "main-agent.md" if tier == "main" else f"{tier}s.md"
    path = _DOCTRINE_ROOT / filename
    if not path.exists():
        log.error(
            "doctrine.missing tier=%s path=%s — using FALLBACK_DOCTRINE",
            tier, path,
        )
        return FALLBACK_DOCTRINE[tier]
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        log.error(
            "doctrine.read_failed tier=%s path=%s error=%s — using FALLBACK_DOCTRINE",
            tier, path, exc,
        )
        return FALLBACK_DOCTRINE[tier]
    line_count = len(text.splitlines())
    if line_count > _DOCTRINE_LINE_CAP:
        log.warning(
            "doctrine.over_cap tier=%s path=%s lines=%d cap=%d "
            "(loaded anyway; operator should trim)",
            tier, path, line_count, _DOCTRINE_LINE_CAP,
        )
    return text


def _sum_delegation_cost_usd(
    collector: list[EmployeeResult], manager_model: str,
) -> float:
    """Estimate accumulated cost from completed delegations.

    P3.4 (#1586) helper. Sums ``EmployeeResult.tokens_used`` across the
    collector and converts to USD via ``bridge.cost_tracker.estimate_cost``
    using the manager's model as the pricing tier — the chief's spec is
    what the cap is configured against (``DepartmentConfig.constraints.
    cost_limit_usd``), so its pricing is the right approximation for the
    cap pre-check.

    The split is 50/50 input/output to mirror the D2.5 record convention
    in ``DepartmentTeam.run``. A pricing-lookup failure returns 0.0 so a
    broken cost_tracker doesn't accidentally fail-open ON the cap — the
    cap check above only fails the call when ``spent > cap``, and 0.0
    can never exceed a positive cap.
    """
    try:
        from bridge.cost_tracker import estimate_cost
    except Exception:  # noqa: BLE001
        return 0.0
    total_tokens = sum(er.tokens_used for er in collector)
    half = total_tokens // 2
    try:
        return float(estimate_cost(manager_model, half, half))
    except Exception:  # noqa: BLE001
        return 0.0


def _load_system_prompt(
    spec: AgentSpec,
    *,
    tier: str = "specialist",
    department: str = "",
    zone: int = 4,
) -> str:
    """Load the per-agent system prompt with doctrine and governance prepended.

    Sprint 24 (Phase 5D): the final prompt shape is::

        <tier-doctrine>

        ---

        <per-agent governance bundle, when present>

        ---

        <agent base prompt — possibly with {{ROSTER}} placeholder>

        ---

        ## Expertise
        <expertise text>     ← if expertise file present

    The roster placeholder ({{ROSTER}}) is substituted later by
    ``_inject_roster_into_prompt`` in ``build_manager_agent``, so chief
    prompts pass through this function with the marker still in place.

    ``tier`` defaults to ``"specialist"`` — the safe choice for the
    common path (employee agents). ``build_manager_agent`` overrides
    with ``tier="chief"``.
    """
    doctrine = _load_doctrine(tier)
    governance = (
        load_governance_bundle(
            _GOVERNANCE_ROOT,
            department=department,
            agent_name=spec.name,
            zone=zone,
        )
        if department
        else ""
    )

    if spec.system_prompt_path:
        path = _resolve_agent_config_path(spec.system_prompt_path)
        if path.exists():
            base = path.read_text(encoding="utf-8")
        else:
            log.warning("System prompt file not found: %s; using default", path)
            base = f"You are {spec.name}. {spec.role}"
    else:
        base = f"You are {spec.name}. {spec.role}"

    expertise = _load_expertise(spec)
    if expertise:
        agent_section = f"{base}\n\n---\n\n{expertise}"
    else:
        agent_section = base

    return "\n\n---\n\n".join(
        part.strip()
        for part in (doctrine, governance, agent_section)
        if part.strip()
    )


def _register_surface_tool(
    agent: "Agent[BridgeDeps, Any]",
    *,
    from_agent: str,
    to_agent: str,
    correlation_field: str,
) -> None:
    """Register a ``surface()`` tool on ``agent`` that writes to surface_store.

    Sprint 22 (Phase 5C). The tool is uniform across specialist and chief
    tiers — the only difference is the From/To naming and which field of
    ``ctx.deps`` is used as the correlation_id:

    - Specialist surface(): from=specialist.name, to=chief.name,
      correlation_id=ctx.deps.task_id
    - Chief surface(): from=chief.name, to="main",
      correlation_id=ctx.deps.directive_id

    Writes are best-effort. When ``ctx.deps.database`` is None or the store
    write fails, the tool returns a placeholder surface_id and logs a
    warning so the chief's actual work is never gated on a failed
    audit-log write.
    """

    async def surface(
        ctx: RunContext[BridgeDeps],
        kind: str,
        urgency: str = "attention",
        payload: Optional[dict] = None,
    ) -> str:
        """Surface work upward.

        Specialists: MUST call with kind='result' at least once per task.
        MAY also call with kind in {flag, blocker, scope_request,
        cross_team, policy_q} during execution.

        Chiefs: emit kind='result' at synthesis return and the others
        (especially blocker, policy_q, cross_team) when escalating to the
        operator.

        urgency: one of 'fyi' (no notification), 'attention' (Discord DM
        in PR B), 'immediate' (Discord DM with @operator in PR B).
        """
        from datetime import datetime, timezone

        from teams._types import Surface, SurfaceKind, Urgency

        try:
            kind_enum = SurfaceKind(kind)
            urgency_enum = Urgency(urgency)
        except ValueError as exc:
            # Surface caller error to the LLM so it retries with valid args
            raise ValueError(
                f"Invalid surface kind/urgency: {exc}. "
                f"kind must be one of: result, flag, blocker, scope_request, "
                f"cross_team, policy_q. urgency must be one of: fyi, attention, "
                f"immediate."
            )

        correlation_id = getattr(ctx.deps, correlation_field, None)
        database = getattr(ctx.deps, "database", None)
        allow_no_store = bool(
            getattr(ctx.deps, "allow_no_surface_store", False)
        )

        from bridge import surface_store

        # Sprint P3.5: in production directive/surface workflows the
        # surface row is a required handoff artifact. When a correlation_id
        # is in scope (we're inside a directive or task) and the database
        # is None, refuse to silently swallow the surface — raise so the
        # chief halts. Tests opt out explicitly via allow_no_surface_store.
        if (
            database is None
            and correlation_id is not None
            and not allow_no_store
        ):
            raise surface_store.MissingSurfaceStoreError(
                f"surface() called with correlation_id={correlation_id!r} "
                f"but BridgeDeps.database is None. Wire a Database in "
                f"production, or set allow_no_surface_store=True for tests."
            )

        s = Surface(
            surface_id=surface_store.new_surface_id(),
            from_agent=from_agent,
            to_agent=to_agent,
            kind=kind_enum,
            urgency=urgency_enum,
            correlation_id=correlation_id,
            payload=payload or {},
            created_at_utc=datetime.now(timezone.utc),
        )

        if database is None:
            log.debug(
                "surface.noop id=%s reason=no-database from=%s to=%s",
                s.surface_id, from_agent, to_agent,
            )
            return s.surface_id

        try:
            await surface_store.insert_surface(database, s)
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "surface.insert_failed id=%s from=%s to=%s error=%s",
                s.surface_id, from_agent, to_agent, exc,
            )

        # Sprint 22 PR B: fire the operator notification hook for high-urgency
        # surfaces addressed to "main". The function self-filters via
        # should_notify() and never raises — Discord failures log a warning
        # and the surface row remains visible via /surfaces unread.
        try:
            from bridge.surface_notify import maybe_notify_operator
            await maybe_notify_operator(s, getattr(ctx.deps, "app", None))
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "surface.notify_dispatch_failed id=%s error=%s",
                s.surface_id, exc,
            )

        return s.surface_id

    agent.tool(
        name="surface",
        description=(
            "Surface a structured event upward to your chief (specialists) "
            "or to the Main Agent (chiefs). kind: result, flag, blocker, "
            "scope_request, cross_team, policy_q. urgency: fyi, attention, "
            "immediate. payload: optional dict of structured fields. "
            "Returns the surface_id."
        ),
    )(surface)


def _register_artifact_tool(
    agent: "Agent[BridgeDeps, Any]",
    *,
    agent_name: str,
) -> None:
    async def write_artifact(
        ctx: RunContext[BridgeDeps],
        kind: str,
        filename: str,
        content: str,
    ) -> str:
        """Persist a text artifact into the current run workspace."""
        run_dir = getattr(ctx.deps, "run_artifact_dir", None)
        if run_dir is None:
            raise RuntimeError("run artifact directory is not available")
        run_dir_path = Path(run_dir).expanduser()
        if not (run_dir_path / "manifest.json").exists():
            raise RuntimeError("run artifact manifest is not available")

        payload = content.encode("utf-8")
        if len(payload) > TEXT_ARTIFACT_MAX_BYTES:
            raise ValueError(
                f"artifact content exceeds {TEXT_ARTIFACT_MAX_BYTES} bytes"
            )

        rel = _safe_artifact_relpath(agent_name, kind, filename)
        normalized_kind = rel.parts[1]

        from bridge.run_artifacts import (
            append_manifest_artifact,
            write_artifact as write_text_artifact,
        )

        entry = write_text_artifact(
            run_dir_path,
            rel.as_posix(),
            content,
            kind=normalized_kind,
            agent=agent_name,
        )
        append_manifest_artifact(run_dir_path, entry)
        return entry.path

    agent.tool(
        name="write_artifact",
        description=(
            "Persist a bounded UTF-8 text artifact in the current run workspace. "
            "Arguments: kind, filename, content. The filename stays inside your "
            "agent/kind namespace. Returns the manifest-relative artifact path."
        ),
    )(write_artifact)


def build_employee_agents(
    config: DepartmentConfig,
    *,
    tracker: Optional[Any] = None,
    cross_vendor_enabled: bool = True,
    skill_allocator: Optional[Any] = None,
    agent_cache: AgentCache | None = None,
) -> dict[str, Agent[BridgeDeps, str]]:
    """Build (or reuse) the department's specialist Agents.

    Uses defer_model_check=True so no API key is required at construction time.
    The model is only resolved when the agent is actually run.

    Sprint P3.3 (issue #1724): ``cross_vendor_enabled`` mirrors
    ``BridgeConfig.board_cross_vendor_enabled``. When False AND the
    department is ``board``, ``adapter: openrouter`` workers are omitted
    from the returned mapping — preventing the chief from delegating to
    cross-vendor seats while the flag is OFF. Default ``True`` preserves
    pre-#1724 behaviour for ad-hoc callers; production wiring in
    ``teams/_team.py::_build`` passes the BridgeConfig value.

    **Sprint zone4-warmth.A.03 (#2292):** consults ``GLOBAL_AGENT_CACHE``
    (or the explicit ``agent_cache`` arg for test isolation) PER SPECIALIST.
    Each specialist Agent is cached under ``(config.name, spec.name)`` so
    repeat calls return the SAME ``Agent`` instances — matching PydanticAI's
    documented design intent that ``Agent`` objects are module-globals
    reused across invocations. Behavior is otherwise byte-identical to
    pre-cache: same system prompt, same tools, same model resolution.

    The cross-vendor filter runs BEFORE cache lookup — filtered-out
    specialists are not constructed and not cached. Per-employee tool
    isolation continues to work: each cached Agent retains exactly the
    tool set built for its spec.

    Cache invalidation is process-local: a bridge restart clears the
    cache. Tests should construct their own ``AgentCache()`` instance
    (passed as ``agent_cache``) or rely on the autouse fixture in
    ``tests/test_teams/conftest.py`` that wipes ``GLOBAL_AGENT_CACHE``.

    Args:
        config: Department configuration.
        tracker: Optional tool call tracker.
        cross_vendor_enabled: Sprint P3.3 / #1724 — mirrors
            ``BridgeConfig.board_cross_vendor_enabled``. Applied BEFORE
            cache lookup; filtered-out specialists never reach the cache.
        skill_allocator: Sprint #1112/4.03 (#2150) — optional skill-manifest
            allocator. Best-effort INFO log per specialist; never raises.
        agent_cache: Sprint zone4-warmth.A.03 (#2292). Process-local
            ``AgentCache`` to consult before constructing each specialist.
            ``None`` (the default) routes through ``GLOBAL_AGENT_CACHE``;
            tests inject their own instance for isolation.
    """
    cache = agent_cache if agent_cache is not None else GLOBAL_AGENT_CACHE
    employees = _filter_cross_vendor_employees(config, cross_vendor_enabled)
    common_and_dept = _dedupe(config.common_tools + config.department_tools)
    capability_manifest = _load_capability_manifest_for_config(config)

    agents: dict[str, Agent[BridgeDeps, str]] = {}
    for spec in employees:
        # Bind ``spec`` via default-arg to defeat the late-binding-closure
        # bug: Python closures capture loop variables BY REFERENCE, so a
        # naive ``def _build():`` body referencing ``spec`` would, when
        # invoked later by ``get_or_build`` (or on a subsequent iteration's
        # rebind), see the LAST iteration's spec. The default-arg trick
        # snapshots the current ``spec`` at function-definition time.
        # See ``_build_employee_agent_uncached`` for the actual body —
        # this closure is a one-line trampoline.
        def _build_uncached(s: AgentSpec = spec) -> Agent[BridgeDeps, str]:
            return _build_employee_agent_uncached(
                s,
                config,
                tracker=tracker,
                common_and_dept=common_and_dept,
                skill_allocator=skill_allocator,
                capability_manifest=capability_manifest,
            )

        agents[spec.name] = cache.get_or_build(
            config.name, spec.name, _build_uncached
        )
    return agents


def _build_employee_agent_uncached(
    spec: AgentSpec,
    config: DepartmentConfig,
    *,
    tracker: Optional[Any] = None,
    common_and_dept: tuple[str, ...],
    skill_allocator: Optional[Any] = None,
    capability_manifest: CapabilityManifest | None = None,
) -> Agent[BridgeDeps, str]:
    """Uncached specialist construction body.

    Sprint zone4-warmth.A.03 (#2292): extracted from ``build_employee_agents``
    so the cache-aware wrapper can route through ``AgentCache.get_or_build``.
    Behavior is byte-identical to the pre-A.03 ``build_employee_agents`` loop
    body; this is structural-only. ``spec`` is a function parameter (not a
    captured loop variable), which is what makes the surrounding wrapper
    safe from the late-binding-closure trap regardless of how many
    specialists the department declares.
    """
    # Sprint 24: specialists get the specialist doctrine prepended.
    system_prompt = _load_system_prompt(
        spec,
        tier="specialist",
        department=config.name,
        zone=config.zone,
    )
    # Sprint 04.07 (#1961): route ``openrouter:*`` model strings through
    # an ``OpenAIModel`` pointed at OpenRouter; non-openrouter strings
    # pass through unchanged. See ``_resolve_model`` for rationale.
    agent: Agent[BridgeDeps, str] = Agent(
        model=_resolve_model(spec),
        deps_type=BridgeDeps,
        output_type=str,
        system_prompt=system_prompt,
        retries=spec.retries,
        defer_model_check=True,
    )

    per_emp = config.per_employee_tools.get(spec.name, ())
    all_tool_names = _dedupe(common_and_dept + per_emp)

    # E4.5 — apply effective TOOL-NAME allowlist: per-employee
    # `allowed_mcp_servers` (legacy field name — used here as a
    # tool-name override, kept stable for backward compat) wins over
    # team-level `allowed_tools`; empty everywhere = no narrowing.
    #
    # P2.4 (2026-05-11) — the legacy per-employee field `allowed_mcp_servers`
    # is RETAINED but is, semantically, a tool-name override. The MCP
    # server allowlist is a separate concern carried by
    # `DepartmentConfig.mcp_allowed_servers` / `BridgeDeps.mcp_allowed_servers`
    # and is applied at filter_mcp_config() time, not here.
    effective_allowlist = spec.allowed_mcp_servers or config.allowed_tools
    if effective_allowlist:
        all_tool_names = tuple(t for t in all_tool_names if t in effective_allowlist)

    # Sprint P2.4 — apply explicit blocklist AFTER the allowlist so
    # denied wins over allowed. Catches "allow everything in the team
    # default EXCEPT these dangerous names" patterns and lets a
    # security review pin a known-bad tool out of every employee in
    # one place.
    if config.denied_tools:
        denied = frozenset(config.denied_tools)
        all_tool_names = tuple(t for t in all_tool_names if t not in denied)

    candidate_tool_names = _dedupe(all_tool_names + _SPECIALIST_RUNTIME_TOOL_NAMES)
    filtered_tool_names = _filter_tool_names_for_capability_manifest(
        config=config,
        spec=spec,
        role="specialist",
        actual_tools=candidate_tool_names,
        manifest=capability_manifest,
    )
    registered_yaml_tool_names = tuple(
        tool_name for tool_name in all_tool_names if tool_name in filtered_tool_names
    )

    if registered_yaml_tool_names:
        # Sprint 04.05 (2026-04-30): forward the specialist's
        # deny_write_paths + agent name so make_tracked can enforce
        # write-path restrictions at tool-call time. Empty deny list
        # = no enforcement (current default for most YAMLs).
        # Sprint P3.5 (#1726, 2026-05-12): forward read_paths the
        # same way for read-side enforcement (read_file allowlist).
        for tool_name, wrapped_fn in resolve_tools(
            registered_yaml_tool_names,
            config.name,
            tracker=tracker,
            deny_write_paths=spec.deny_write_paths,
            read_paths=spec.read_paths,
            agent_name=spec.name,
        ):
            agent.tool(
                name=tool_name,
                description=wrapped_fn.__doc__ or tool_name,
            )(wrapped_fn)

    # Sprint 22 (Phase 5C): every specialist gets a surface() tool that
    # writes to the surface_store. The chief is the recipient. Closure
    # captures the specialist name and the chief name for the From/To.
    if "surface" in filtered_tool_names:
        _register_surface_tool(
            agent,
            from_agent=spec.name,
            to_agent=config.manager.name,
            correlation_field="task_id",
        )
    if "write_artifact" in filtered_tool_names:
        _register_artifact_tool(agent, agent_name=spec.name)

    log.debug("employee_agent.built name=%s model=%s tools=%d",
              spec.name, spec.model, len(filtered_tool_names))

    # Sprint #1112/4.03 (#2150) — SkillAllocator filter. When the
    # allocator is wired (production path via WarmChief →
    # DepartmentTeam), surface the per-specialist allowed-skill count
    # at INFO so operators can audit the manifest's effect at agent
    # spawn time. When None (back-compat for tests + ad-hoc
    # callers), the filter is skipped silently. Skill enforcement
    # downstream (prompt injection / tool gating) is deferred to a
    # later sprint — this sprint wires the seam end-to-end and
    # proves the filter point exists.
    if skill_allocator is not None:
        try:
            allowed = skill_allocator.allowed_skills(
                zone=config.zone,
                department=config.name,
                role="specialist",
                agent_name=spec.name,
            )
            log.info(
                "Agent %s instantiated with %d allowed skills",
                spec.name, len(allowed),
            )
        except Exception as exc:  # noqa: BLE001 — allocator query is best-effort
            log.warning(
                "skill_allocator.query_failed agent=%s error=%s",
                spec.name, exc,
            )
    _attach_capability_report(
        agent,
        config=config,
        spec=spec,
        role="specialist",
        manifest=capability_manifest,
    )
    return agent


def build_manager_agent(
    config: DepartmentConfig,
    employees: dict[str, Agent[BridgeDeps, str]],
    *,
    tracker: Optional[Any] = None,
    employee_results_collector: Optional[list[EmployeeResult]] = None,
    cross_vendor_enabled: bool = True,
    skill_allocator: Optional[Any] = None,
    specialist_retriever: Optional[Any] = None,
    directive_hint: Optional[str] = None,
    retrieval_top_k: int = 3,
    agent_cache: AgentCache | None = None,
    registered: tuple[Any, ...] = (),
) -> Agent[BridgeDeps, TeamOutput]:
    """Build (or reuse) the department's chief Agent with rostered delegation.

    Sprint 19 (Phase 5A) replaces the per-specialist ``delegate_to_<name>``
    tools with two rostered tools:

    - ``list_specialists()`` returns the chief's full roster as a list of
      SpecialistSpec dicts. The chief's LLM uses this to introspect its
      team at runtime (no docstring scraping).
    - ``delegate(specialist, task, constraints, deadline_seconds)`` is the
      single delegation primitive. Invalid specialist names raise
      ``ValueError`` so pydantic-ai retries the tool call with a valid
      name, instead of silently routing to nowhere.

    The chief's system prompt receives a deterministic roster block
    substituted at the ``{{ROSTER}}`` placeholder; if the placeholder is
    absent, the block is appended (with a warning log) so the chief
    remains operational while the prompt is being fixed.

    Uses defer_model_check=True so no API key is required at construction
    time. Department and common tools from YAML are still registered so
    the chief can act directly when delegation is unnecessary.

    **Sprint zone4-warmth.A.02 (#2291):** consults ``GLOBAL_AGENT_CACHE``
    (or the explicit ``agent_cache`` arg for test isolation). Repeat calls
    for the same ``(config.name, config.manager.name)`` return the SAME
    ``Agent`` instance — matching PydanticAI's documented design intent
    that ``Agent`` objects are module-globals reused across invocations.
    Behavior is otherwise byte-identical to pre-cache: same system prompt,
    same tools, same model resolution. The cache only avoids re-running
    the construction body.

    Cache invalidation is process-local: a bridge restart clears the
    cache. Tests should construct their own ``AgentCache()`` instance
    (passed as ``agent_cache``) or call ``GLOBAL_AGENT_CACHE.invalidate_all()``
    in setup — see the autouse fixture in ``tests/test_teams/conftest.py``.

    Args:
        config: Department configuration.
        employees: Pre-built employee agent mapping.
        tracker: Optional tool call tracker.
        employee_results_collector: Mutable list. When provided, each
            successful or failed specialist delegation appends an
            EmployeeResult to it. Pass the same list reference to
            DepartmentTeam so run() can read the results after the
            manager finishes. (Sprint B2.1)
        cross_vendor_enabled: Sprint P3.3 / #1724 — mirrors
            ``BridgeConfig.board_cross_vendor_enabled``. Forwarded to
            ``roster_from_department_config`` so the chief's prompt-side
            roster matches the filtered employee map when the flag is OFF.
        specialist_retriever: Sprint #1112/4.06 (#2153) — optional
            ``SpecialistRetriever`` instance. When provided together with
            ``directive_hint``, the chief's prompt-side roster is narrowed
            to the top-K ranked matches before injection. ``None`` (the
            default) keeps historical full-enumeration behaviour.
        directive_hint: Sprint #1112/4.06 (#2153) — directive text used to
            rank specialists at chief-construction time. Required for
            retrieval to fire; absent means we keep the full roster
            because we have no signal to rank on. The chief is built once
            per directive in the dispatcher path, so this hint is the
            cleanest seam available without restructuring the WARM
            lifecycle (explicitly out of scope per the spec). The
            ``delegate()`` tool still validates against the FULL roster
            so a chief that picks a name outside the top-K via
            ``list_specialists()`` (which still shows the narrowed set)
            does not stall — failure to find a name raises ValueError as
            before and the LLM retries.
        retrieval_top_k: How many top matches to keep when retrieval is
            active. Default 3 per the spec.
        agent_cache: Sprint zone4-warmth.A.02 (#2291). Process-local
            ``AgentCache`` to consult before constructing the chief.
            ``None`` (the default) routes through ``GLOBAL_AGENT_CACHE``;
            tests inject their own instance for isolation.
    """
    cache = agent_cache if agent_cache is not None else GLOBAL_AGENT_CACHE
    capability_manifest = _load_capability_manifest_for_config(config)

    def _build_uncached() -> Agent[BridgeDeps, TeamOutput]:
        return _build_manager_agent_uncached(
            config,
            employees,
            tracker=tracker,
            employee_results_collector=employee_results_collector,
            cross_vendor_enabled=cross_vendor_enabled,
            skill_allocator=skill_allocator,
            specialist_retriever=specialist_retriever,
            directive_hint=directive_hint,
            retrieval_top_k=retrieval_top_k,
            capability_manifest=capability_manifest,
            registered=registered,
        )

    manager = cache.get_or_build(
        config.name, config.manager.name, _build_uncached
    )
    # Direct factory callers may pass a fresh fallback collector on a cache hit.
    # Keep the cached chief instance warm, but update the per-caller fallback
    # before its delegate tool runs. Production DepartmentTeam runs still prefer
    # the collector threaded through ctx.deps.
    setattr(manager, _MANAGER_FALLBACK_COLLECTOR_ATTR, employee_results_collector)
    return manager


def _build_manager_agent_uncached(
    config: DepartmentConfig,
    employees: dict[str, Agent[BridgeDeps, str]],
    *,
    tracker: Optional[Any] = None,
    employee_results_collector: Optional[list[EmployeeResult]] = None,
    cross_vendor_enabled: bool = True,
    skill_allocator: Optional[Any] = None,
    specialist_retriever: Optional[Any] = None,
    directive_hint: Optional[str] = None,
    retrieval_top_k: int = 3,
    capability_manifest: CapabilityManifest | None = None,
    registered: tuple[Any, ...] = (),
) -> Agent[BridgeDeps, TeamOutput]:
    """Uncached chief construction body.

    Sprint zone4-warmth.A.02 (#2291): extracted from ``build_manager_agent``
    so the cache-aware wrapper can route through ``AgentCache.get_or_build``.
    Behavior is byte-identical to the pre-A.02 ``build_manager_agent`` body;
    this is structural-only.
    """
    roster = roster_from_department_config(
        config, cross_vendor_enabled=cross_vendor_enabled, registered=registered
    )
    # Sprint #1112/4.06 (#2153) — when the operator enables specialist
    # retrieval AND we have both a retriever and a directive hint, narrow
    # the roster block injected into the prompt to the top-K matches.
    # When any input is missing, fall through to the historical full-
    # enumeration behaviour. The ``roster`` variable above is the FULL
    # roster and remains the source of truth for the delegate tool's
    # validation (see _make_delegate_tool below). Only the prompt-side
    # display set is narrowed.
    prompt_roster = roster
    if specialist_retriever is not None and directive_hint:
        try:
            matches = specialist_retriever.retrieve_top_k(
                directive_hint, config.name, k=retrieval_top_k,
            )
            kept_names = {m.name for m in matches}
            narrowed = tuple(
                s for s in roster.specialists if s.name in kept_names
            )
            if narrowed:
                # Use dataclasses.replace so the Roster stays frozen and
                # the department / chief_name fields are preserved.
                from dataclasses import replace
                prompt_roster = replace(roster, specialists=narrowed)
                log.info(
                    "specialist_retrieval.applied department=%s kept=%d/%d",
                    config.name, len(narrowed), len(roster.specialists),
                )
            else:
                # Retriever returned matches but none align with the YAML
                # roster — fall back to the full roster rather than ship
                # an empty team to the chief.
                log.warning(
                    "specialist_retrieval.no_overlap department=%s matches=%d roster=%d",
                    config.name, len(matches), len(roster.specialists),
                )
        except Exception as exc:  # noqa: BLE001 — best-effort, never break chief build
            log.warning(
                "specialist_retrieval.failed department=%s error=%s",
                config.name, exc,
            )

    # Sprint 24: chiefs get the chief doctrine prepended; the roster block
    # then substitutes into the agent's base prompt at {{ROSTER}}.
    base_prompt = _load_system_prompt(
        config.manager,
        tier="chief",
        department=config.name,
        zone=config.zone,
    )
    system_prompt = _inject_roster_into_prompt(
        base_prompt,
        prompt_roster,
        expected_min_specialists=config.constraints.expected_min_specialists,
    )

    # Sprint 04.07 (#1961): the chief gets the same prefix-based routing
    # as specialists. The 6 ``adapter:"claude"`` + ``model:"openrouter:*"``
    # chief entries across department YAMLs were silently broken until
    # _resolve_model landed; this is what makes them work.
    manager: Agent[BridgeDeps, TeamOutput] = Agent(
        model=_resolve_model(config.manager),
        deps_type=BridgeDeps,
        output_type=TeamOutput,
        system_prompt=system_prompt,
        retries=config.manager.retries,
        defer_model_check=True,
    )
    manager_yaml_tool_names = _dedupe(config.common_tools + config.department_tools)
    candidate_tool_names = _dedupe(
        _MANAGER_RUNTIME_TOOL_NAMES + manager_yaml_tool_names
    )
    filtered_tool_names = _filter_tool_names_for_capability_manifest(
        config=config,
        spec=config.manager,
        role="chief",
        actual_tools=candidate_tool_names,
        manifest=capability_manifest,
    )
    registered_manager_tool_names = tuple(
        tool_name
        for tool_name in manager_yaml_tool_names
        if tool_name in filtered_tool_names
    )

    expected_min_specialists = config.constraints.expected_min_specialists
    if expected_min_specialists > 0:

        @manager.output_validator
        def enforce_delegation_floor(
            ctx: RunContext[BridgeDeps], output: TeamOutput
        ) -> TeamOutput:
            """Retry direct chief answers before post-run Gate 8 fails them."""
            deps_collector = getattr(
                ctx.deps, "employee_results_collector", None
            )
            latest_fallback_collector = getattr(
                manager,
                _MANAGER_FALLBACK_COLLECTOR_ATTR,
                employee_results_collector,
            )
            collector = (
                deps_collector
                if deps_collector is not None
                else latest_fallback_collector
            )
            if collector is None:
                return output

            actual = len(collector)
            if actual >= expected_min_specialists:
                return output

            missing = expected_min_specialists - actual
            available = ", ".join(roster.names())
            log.warning(
                "delegation.floor_retry manager=%s actual=%d expected=%d",
                config.manager.name,
                actual,
                expected_min_specialists,
            )
            raise ModelRetry(
                "Do not return final_result yet. This department requires "
                f"at least {expected_min_specialists} specialist delegation"
                f"{'s' if expected_min_specialists != 1 else ''} before "
                f"final synthesis; only {actual} "
                f"{'has' if actual == 1 else 'have'} completed, so "
                f"{missing} more "
                f"{'is' if missing == 1 else 'are'} required. Call "
                "delegate(specialist, task, constraints, deadline_seconds) "
                f"for one of these available specialists: {available}. "
                "Only call final_result after the delegation floor is met."
            )

    # --- list_specialists() — chief introspects its roster at runtime ---
    def _make_list_tool(r: Roster):
        async def list_specialists(ctx: RunContext[BridgeDeps]) -> list[dict[str, Any]]:
            """Return the chief's full roster (name, role, expertise_summary, when_to_call, domain_write_paths)."""
            return [
                {
                    "name": s.name,
                    "role": s.role,
                    "expertise_summary": s.expertise_summary,
                    "when_to_call": s.when_to_call,
                    "domain_write_paths": list(s.domain_write_paths),
                }
                for s in r.specialists
            ]
        return list_specialists

    if "list_specialists" in filtered_tool_names:
        manager.tool(
            name="list_specialists",
            description="Return the chief's full roster as a list of specialist specs.",
        )(_make_list_tool(roster))

    # --- delegate() — single rostered delegation primitive ---
    # Manager-model hint for the mid-run cost-cap pre-check (P3.4 #1586).
    # Captured once at build time so the per-delegation closure doesn't
    # re-query ``config.manager.model`` on every call. Empty string is the
    # safe default and routes to "sonnet" pricing inside ``estimate_cost``.
    _manager_model_hint = str(
        getattr(config.manager, "model", None) or "sonnet"
    )

    def _make_delegate_tool(
        r: Roster,
        emps: dict[str, Agent[BridgeDeps, str]],
        fallback_collector: Optional[list[EmployeeResult]],
    ):
        async def delegate(
            ctx: RunContext[BridgeDeps],
            specialist: str,
            task: str,
            constraints: Optional[list[str]] = None,
            deadline_seconds: Optional[int] = None,
        ) -> str:
            """Delegate ``task`` to ``specialist``. Raises ValueError if specialist is unknown."""
            # Sprint zone4-warmth (#2313, 2026-05-18): the chief's
            # ``employee_results_collector`` is per-RUN state, not per-BUILD
            # state. Prefer the collector on ``ctx.deps`` (populated by
            # ``DepartmentTeam.run`` from a fresh list each call). Direct
            # factory callers may drive ``manager.run`` without that deps field,
            # so cache-hit builds update an attribute on the cached chief and
            # the delegate reads that latest fallback before falling back to the
            # cold-build closure list.
            deps_collector = getattr(ctx.deps, "employee_results_collector", None)
            latest_fallback_collector = getattr(
                manager,
                _MANAGER_FALLBACK_COLLECTOR_ATTR,
                fallback_collector,
            )
            collector = (
                deps_collector
                if deps_collector is not None
                else latest_fallback_collector
            )

            # P3.4 (#1586) — mid-run cost-cap pre-check. Sums the running
            # delegation tokens captured on ``collector`` so far in this
            # chief run, estimates cost via the manager model's pricing,
            # and refuses the next delegation when ``cost_limit_usd`` is
            # already breached. The chief sees a ``COST_CAP_EXCEEDED:``
            # error string return so its synthesis can surface a
            # truncated answer rather than burning more budget.
            #
            # No-ops when ``ctx.deps.cost_limit_usd`` is non-positive or
            # the collector is None (chief invoked without one — direct
            # ``manager.run`` test fixtures).
            cap = float(
                getattr(ctx.deps, "cost_limit_usd", 0.0) or 0.0
            )
            if cap > 0 and collector is not None and collector:
                spent = _sum_delegation_cost_usd(
                    collector, _manager_model_hint,
                )
                if spent > cap:
                    msg = (
                        f"COST_CAP_EXCEEDED: prior delegations cost "
                        f"${spent:.4f} > cap ${cap:.4f}; refusing further "
                        f"delegations. Synthesise with what you have."
                    )
                    log.warning(
                        "delegation.cost_cap_exceeded manager=%s spent=%.4f cap=%.4f",
                        config.manager.name, spent, cap,
                    )
                    return msg

            spec = r.get(specialist)
            if spec is None:
                available = list(r.names())
                if _is_placeholder_specialist_name(specialist):
                    raise ModelRetry(
                        f"The specialist argument {specialist!r} is a schema "
                        "placeholder, not a roster member. Retry the delegate "
                        "tool call with the exact name of one available "
                        f"specialist: {available}. Do not pass placeholder "
                        "values like 'string', 'specialist', or '...'."
                    )
                raise ValueError(
                    f"No specialist named {specialist!r}. "
                    f"Available: {available}"
                )
            agent = emps.get(specialist)
            if agent is None:
                # Roster claims the specialist but no agent was built — config
                # mismatch. Surface as ValueError for the same reason: the
                # chief's LLM should retry with a different specialist.
                raise ValueError(
                    f"Specialist {specialist!r} is in the roster but has no "
                    f"built agent. This is a configuration error."
                )

            # Prepend constraints + deadline as a structured preamble so the
            # specialist's LLM sees them. Plain string concatenation keeps the
            # contract identical to the prior per-specialist tool's str input.
            preamble_parts: list[str] = []
            if constraints:
                preamble_parts.append("Constraints:\n" + "\n".join(f"- {c}" for c in constraints))
            if deadline_seconds is not None:
                preamble_parts.append(f"Deadline: {deadline_seconds} seconds")
            full_task = ("\n\n".join(preamble_parts) + "\n\n" + task) if preamble_parts else task
            original_full_task_chars = len(full_task)
            full_task = _cap_delegation_task(full_task)
            if len(full_task) != original_full_task_chars:
                log.warning(
                    "delegation.task_truncated manager=%s employee=%s "
                    "original_chars=%d capped_chars=%d cap=%d",
                    config.manager.name,
                    specialist,
                    original_full_task_chars,
                    len(full_task),
                    DELEGATION_TASK_MAX_CHARS,
                )

            # Sprint 21 (Phase 5B): create a Task record for this delegation.
            # Best-effort — store-write failures log a warning but never
            # block the chief's actual work. When ctx.deps.database is None
            # (test fixtures, cron contexts), the entire Task layer no-ops.
            task_id: Optional[str] = None
            database = getattr(ctx.deps, "database", None)
            if database is not None:
                try:
                    from bridge import task_store
                    from datetime import datetime, timedelta, timezone
                    task_id = task_store.new_task_id()
                    deadline_dt = (
                        datetime.now(timezone.utc) + timedelta(seconds=deadline_seconds)
                        if deadline_seconds is not None
                        else None
                    )
                    task_record = Task(
                        task_id=task_id,
                        directive_id=getattr(ctx.deps, "directive_id", None),
                        from_chief=config.manager.name,
                        to_specialist=specialist,
                        description=task,
                        constraints=tuple(constraints or ()),
                        deadline_utc=deadline_dt,
                        issued_at_utc=datetime.now(timezone.utc),
                    )
                    await task_store.insert_task(database, task_record)
                    await task_store.mark_in_progress(
                        database, task_id, note="specialist invocation starting",
                    )
                except Exception as exc:  # noqa: BLE001
                    log.warning(
                        "task.insert_or_in_progress_failed specialist=%s error=%s",
                        specialist, exc,
                    )
                    task_id = None  # disable terminal hooks for this run

            log.info(
                "delegation.start manager=%s employee=%s task_id=%s",
                config.manager.name,
                specialist,
                task_id,
            )
            # P3.3 (#1584) — observability publish for the chief →
            # specialist delegation step. The pre-cataloged event type
            # ``department.delegation.started`` (see
            # ``agent/config/registry/events/agents.yaml``) flows through
            # the EventBus so an operator subscribing to ``/ws/events``
            # sees the chief's delegate call alongside chief_session.*
            # transitions. ``correlation_id`` comes from ``ctx.deps.session_id``
            # — best available identifier reaching the tool boundary; in
            # the dispatcher path this is the same value the chief session
            # row carries on its ``session_id`` field.
            event_bus = getattr(ctx.deps, "event_bus", None)
            if event_bus is not None:
                payload = {
                    "session_id": getattr(ctx.deps, "session_id", ""),
                    "department": getattr(ctx.deps, "department", "")
                                  or config.name,
                    "manager": config.manager.name,
                    "specialist": specialist,
                    "task_id": task_id,
                    "task": task,
                }
                try:
                    try:
                        event_bus.publish(
                            "department.delegation.started",
                            payload,
                            correlation_id=getattr(ctx.deps, "session_id", None),
                        )
                    except TypeError:
                        event_bus.publish(
                            "department.delegation.started", payload,
                        )
                except Exception as exc:  # noqa: BLE001
                    log.warning(
                        "delegation.event_publish_failed manager=%s specialist=%s error=%s",
                        config.manager.name, specialist, exc,
                    )
            t0 = time.monotonic()
            try:
                # Sprint 21: pass a child BridgeDeps with task_id populated so
                # the specialist can read it for future Surface correlation.
                # Use dataclasses.replace to copy-with-mutate; falls back to
                # ctx.deps unchanged if replace fails (extremely defensive —
                # BridgeDeps is a frozen dataclass so this should never raise).
                child_deps = ctx.deps
                if task_id is not None:
                    try:
                        from dataclasses import replace
                        child_deps = replace(ctx.deps, task_id=task_id)
                    except Exception:  # noqa: BLE001
                        child_deps = ctx.deps

                # Sprint fix/z4-decouple-specialist-runusage (2026-05-19) —
                # decouple specialist usage tracking from the chief's
                # ``RunUsage``. Previously ``usage=ctx.usage`` was passed so
                # specialists shared the chief's usage counter, but that
                # caused every specialist's input tokens (specialist system
                # prompt + doctrine + task + tool-call schema) to accumulate
                # against the chief's ``input_tokens_limit`` budget. With
                # ``expected_min_specialists: 6+`` and multi-round
                # deliberation this trivially crossed 100K input tokens and
                # tripped ``UsageLimitExceeded`` on the chief's NEXT request,
                # even though the chief's own context was well within bounds.
                # See ``docs/architecture/2026-05-19-z4-board-token-budget-diagnostic-correction.md``
                # for the full diagnostic. Without the kwarg, pydantic-ai
                # initialises a fresh ``RunUsage`` per specialist call; the
                # chief's ``input_tokens_limit`` (resolved from
                # ``Constraints.request_token_limit`` via
                # ``_team._resolve_usage_limits``) now governs ONLY the
                # chief's own model requests, as intended. Aggregate cost
                # tracking is unaffected — ``EmployeeResult.tokens_used``
                # below still reports the specialist's actual token use
                # via ``result.usage()``, and the mid-run cost cap
                # (``_sum_delegation_cost_usd`` above) still polices the
                # cumulative spend.
                result = await agent.run(full_task, deps=child_deps)
                duration = time.monotonic() - t0
                output_str = str(result.output)

                usage_obj = (
                    result.usage()
                    if hasattr(result, "usage") and callable(result.usage)
                    else None
                )
                tokens_used = 0
                if usage_obj is not None:
                    tokens_used = (
                        getattr(usage_obj, "total_tokens", 0)
                        or (getattr(usage_obj, "request_tokens", 0) or 0)
                        + (getattr(usage_obj, "response_tokens", 0) or 0)
                    )

                if collector is not None:
                    collector.append(
                        EmployeeResult(
                            employee_name=specialist,
                            output=output_str,
                            success=True,
                            error=None,
                            tokens_used=tokens_used,
                            duration_seconds=duration,
                        )
                    )

                # Sprint 21: terminal DONE transition (best-effort).
                if task_id is not None and database is not None:
                    try:
                        from bridge import task_store
                        await task_store.mark_done(
                            database, task_id, note="specialist returned",
                        )
                    except Exception as exc:  # noqa: BLE001
                        log.warning(
                            "task.mark_done_failed task_id=%s error=%s",
                            task_id, exc,
                        )

                log.info(
                    "delegation.done manager=%s employee=%s task_id=%s tokens=%d dur=%.2fs",
                    config.manager.name, specialist, task_id, tokens_used, duration,
                )
                return output_str
            except ValueError:
                # Re-raise so pydantic-ai surfaces the validation error to the
                # chief's LLM for retry with a valid specialist name. We do
                # NOT mark the task BLOCKED here because pre-validation rejects
                # never reach this branch (the roster check is above) — only a
                # ValueError raised inside the specialist itself does, and
                # those are genuine failures. Mark BLOCKED for cleanliness.
                if task_id is not None and database is not None:
                    try:
                        from bridge import task_store
                        await task_store.mark_blocked(
                            database, task_id, note="ValueError raised in specialist",
                        )
                    except Exception:  # noqa: BLE001
                        pass
                raise
            except Exception as exc:  # noqa: BLE001
                duration = time.monotonic() - t0
                err_msg = f"{type(exc).__name__}: {exc}"
                log.warning(
                    "delegation.failed manager=%s employee=%s error=%s",
                    config.manager.name, specialist, err_msg,
                )
                if collector is not None:
                    collector.append(
                        EmployeeResult(
                            employee_name=specialist,
                            output="",
                            success=False,
                            error=err_msg,
                            tokens_used=0,
                            duration_seconds=duration,
                        )
                    )

                # Sprint 21: terminal BLOCKED transition (best-effort).
                if task_id is not None and database is not None:
                    try:
                        from bridge import task_store
                        await task_store.mark_blocked(
                            database, task_id, note=err_msg,
                        )
                    except Exception:  # noqa: BLE001
                        pass

                return f"ERROR: {err_msg}"

        return delegate

    if "delegate" in filtered_tool_names:
        manager.tool(
            name="delegate",
            description=(
                "Delegate a task to one of your specialists. "
                "Call list_specialists() first to discover available names. "
                "The 'specialist' argument must exactly match one roster name: "
                f"{list(roster.names())}. Do not pass schema placeholders like "
                "'string', 'specialist', or '...'. Raises ValueError if "
                "'specialist' is not in the roster."
            ),
        )(_make_delegate_tool(roster, employees, employee_results_collector))

    # --- acknowledge_directive (Sprint 20, Phase 5B) ---
    # The chief MUST call this as its first action when the incoming task
    # carries a [directive_id: dir-xxx] prefix. Transitions the directive
    # from ISSUED → ACCEPTED in the directive_store. No-ops cleanly when
    # the runtime is missing a Database (test fixtures, cron contexts).
    async def acknowledge_directive(
        ctx: RunContext[BridgeDeps], directive_id: str
    ) -> str:
        """Acknowledge receipt of a directive. MUST be called first when the
        incoming task starts with [directive_id: dir-xxx]. Pass the directive_id
        verbatim from that prefix. Returns 'acknowledged' on success."""
        database = getattr(ctx.deps, "database", None)
        if database is None:
            log.debug(
                "acknowledge_directive.noop id=%s reason=no-database",
                directive_id,
            )
            return "acknowledged (no-op: directive store unavailable)"
        try:
            from bridge import directive_store
            await directive_store.mark_accepted(
                database, directive_id, note="chief acknowledged"
            )
            return "acknowledged"
        except ValueError as exc:
            # Unknown directive_id — surface to the LLM so it can choose to
            # proceed without acknowledgment rather than loop on a bad id.
            log.warning(
                "acknowledge_directive.unknown_id id=%s error=%s",
                directive_id, exc,
            )
            return f"unknown directive_id: {directive_id}"
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "acknowledge_directive.failed id=%s error=%s",
                directive_id, exc,
            )
            return f"acknowledgment failed: {exc}"

    if "acknowledge_directive" in filtered_tool_names:
        manager.tool(
            name="acknowledge_directive",
            description=(
                "Acknowledge receipt of a directive. Call this FIRST when your "
                "incoming task starts with '[directive_id: dir-xxx]'. Pass the "
                "directive_id verbatim. Transitions the directive to ACCEPTED."
            ),
        )(acknowledge_directive)

    # --- surface (Sprint 22, Phase 5C) ---
    # Chief surface() emits to the Main Agent ("main"), correlated by the
    # active directive_id on ctx.deps. Use this to send the synthesis
    # RESULT, escalate BLOCKER / POLICY_Q to the operator, or signal
    # CROSS_TEAM when another department's specialist is needed.
    if "surface" in filtered_tool_names:
        _register_surface_tool(
            manager,
            from_agent=config.manager.name,
            to_agent="main",
            correlation_field="directive_id",
        )
    if "write_artifact" in filtered_tool_names:
        _register_artifact_tool(manager, agent_name=config.manager.name)

    # --- department + common tools from YAML config ---
    if registered_manager_tool_names:
        # Sprint 04.05: chief inherits its YAML deny_write_paths too.
        # Sprint P3.5 (#1726, 2026-05-12): chief also inherits read_paths
        # for read-side allowlist enforcement.
        for tool_name, wrapped_fn in resolve_tools(
            registered_manager_tool_names,
            config.name,
            tracker=tracker,
            deny_write_paths=config.manager.deny_write_paths,
            read_paths=config.manager.read_paths,
            agent_name=config.manager.name,
        ):
            manager.tool(
                name=tool_name,
                description=wrapped_fn.__doc__ or tool_name,
            )(wrapped_fn)

    log.debug(
        "manager_agent.built name=%s employees=%d dept_tools=%d roster=%d",
        config.manager.name,
        len(employees),
        len(filtered_tool_names),
        len(roster.specialists),
    )

    # Sprint #1112/4.03 (#2150) — SkillAllocator filter for the chief.
    # When the allocator is wired (production path via DepartmentTeam),
    # surface the chief's allowed-skill count at INFO so operators can
    # audit the manifest's effect at chief spawn time. None (the back-
    # compat default) skips the query silently. Downstream consumption
    # of the filtered set (prompt injection / tool gating) is a later
    # sprint — this one wires the seam end-to-end.
    if skill_allocator is not None:
        try:
            allowed = skill_allocator.allowed_skills(
                zone=config.zone,
                department=config.name,
                role="chief",
                agent_name=config.manager.name,
            )
            log.info(
                "Agent %s instantiated with %d allowed skills",
                config.manager.name, len(allowed),
            )
        except Exception as exc:  # noqa: BLE001 — allocator query is best-effort
            log.warning(
                "skill_allocator.query_failed agent=%s error=%s",
                config.manager.name, exc,
            )
    _attach_capability_report(
        manager,
        config=config,
        spec=config.manager,
        role="chief",
        manifest=capability_manifest,
    )
    return manager
