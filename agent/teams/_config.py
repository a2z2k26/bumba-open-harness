"""Department YAML config loader (sprint B-S.3).

Prior to B-S.3 the loader used ``data.get("key", default)`` dict indexing —
a YAML typo (e.g. ``cost_limit_us: 1.5`` instead of ``cost_limit_usd: 1.5``)
silently fell back to the default, making the operator's intent invisible.

B-S.3 replaces every ``_parse_*`` function with a Pydantic ``BaseModel``
schema for the raw YAML shape.  Unknown fields raise ``ValidationError`` at
load time so typos surface immediately rather than silently reverting to
defaults.
"""

from __future__ import annotations

import logging
from dataclasses import replace
from pathlib import Path
from typing import Optional

import yaml
from pydantic import BaseModel, Field, ValidationError

from teams._types import (
    AgentSpec,
    Budget,
    Constraints,
    DepartmentConfig,
    VAPIReceptionist,
)

log = logging.getLogger(__name__)


class InvalidConfigError(ValueError):
    """Raised when a department YAML config is invalid."""


# Sprint 04.05 — recognised adapter values for the per-member adapter field.
# `claude` preserves existing pydantic_ai / Anthropic behaviour (default).
# `openrouter` routes via the OpenAI-compatible provider pointed at
# ``https://openrouter.ai/api/v1`` (see ``teams._factory._resolve_model``).
#
# Sprint 04.07 (#1961, 2026-05-14) — actual runtime routing is **prefix-
# based on ``AgentSpec.model``**, not on this field. Any ``model:`` starting
# with ``openrouter:`` is routed through OpenRouter regardless of the
# declared adapter. ``adapter`` is consulted only for: (a) the cross-vendor
# roster filter in ``teams._factory._filter_cross_vendor_employees`` (#1724),
# and (b) the load-time consistency warning emitted by
# ``_warn_adapter_model_mismatch`` below. ``OpenRouterAdapter`` in
# ``bridge.cross_model`` remains orphaned by design — the
# ``OpenRouterClient`` it wraps is reachable directly from
# ``bridge.fallback.FallbackChain``, and pydantic-ai's OpenAI-compatible
# provider is the runtime surface for agent invocation.
ALLOWED_ADAPTERS: frozenset[str] = frozenset({"claude", "openrouter", "codex-exec"})
DEFAULT_ADAPTER: str = "claude"
_OPENROUTER_MODEL_PREFIX: str = "openrouter:"

# Sprint P2.4 — allowed values for `team.mcp.mode`. `permissive` (default)
# preserves today's behaviour: empty `allowed_servers` means "inherit the
# bridge default MCP config" (every server reachable). `deny_by_default`
# treats an empty `allowed_servers` as "no MCP servers at all" — the
# filtered MCP config is `{}`. Production teams that want strict isolation
# should set `mode: deny_by_default` and enumerate every server they need.
ALLOWED_MCP_MODES: frozenset[str] = frozenset({"permissive", "deny_by_default"})
DEFAULT_MCP_MODE: str = "permissive"
_CANONICAL_TEAMS_ROOT = Path(__file__).resolve().parents[1] / "config" / "teams"


_MODEL_PREFIX_MAP = {
    "opus-4.6": "anthropic:claude-opus-4-6",
    "opus-4.5": "anthropic:claude-opus-4-5",
    "sonnet-4.6": "anthropic:claude-sonnet-4-6",
    "sonnet-4.5": "anthropic:claude-sonnet-4-5",
    "haiku-4.5": "anthropic:claude-haiku-4-5",
}


def _normalize_model_string(model: str) -> str:
    if ":" in model:
        return model
    return _MODEL_PREFIX_MAP.get(model, model)


# ---------------------------------------------------------------------------
# Raw YAML shape schemas (strict = extra fields forbidden)
# ---------------------------------------------------------------------------


class _UsageLimitsSchema(BaseModel):
    request_limit: int = 20
    request_token_limit: int = 250_000
    response_token_limit: int = 250_000

    model_config = {"extra": "forbid"}


class _ConstraintsSchema(BaseModel):
    cost_limit_usd: float = 2.0
    timeout_seconds: int = 600
    concurrency_limit: int = 4
    usage_limits: _UsageLimitsSchema = Field(default_factory=_UsageLimitsSchema)
    # Sprint 04.15 / Gate 8 opt-in: per-department override for the minimum
    # specialist-invocation count enforced by teams._verify.verify_team_result.
    # Default 0 disables Gate 8; production department YAMLs typically set
    # this to len(workers) for strict delegation enforcement.
    expected_min_specialists: int = 0
    # zone4-warmth.D.01 (#2299) — optional per-team override for the
    # warm idle-timeout window. ``None`` (omitted in YAML) means "use
    # the global ``chief_dispatcher_idle_timeout_seconds`` default".
    # Operator recommendation (per the 2026-05-18 warmth plan):
    #   - Board/Strategy: 14400 (4h) — long approval cycles, big synth runs
    #   - Design/QA: 7200 (2h) — moderate operator-cycle
    #   - Ops/JobSearch: 600 (10 min) — high-volume cron-driven
    warm_idle_timeout_seconds: int | None = None

    model_config = {"extra": "forbid"}


class _BudgetSchema(BaseModel):
    daily_limit_usd: float = 5.0
    alert_thresholds: list[float] = Field(default_factory=lambda: [0.5, 0.75, 0.9])

    model_config = {"extra": "forbid"}


class _VAPISchema(BaseModel):
    enabled: bool = False
    model: str = "gpt-4o-mini"
    voice: str = "shimmer"
    greeting: str = ""
    tools: list[str] = Field(default_factory=list)

    model_config = {"extra": "forbid"}


class _DomainSchema(BaseModel):
    deny_write: list[str] = Field(default_factory=list)
    # Extended domain spec used by real department configs
    read: list[str] = Field(default_factory=list)
    write: list[str] = Field(default_factory=list)

    model_config = {"extra": "forbid"}


class _EscalationTriggerSchema(BaseModel):
    from_zone: int = 3
    triggers: list[str] = Field(default_factory=list)
    complexity_threshold: int = 5
    auto_escalate: bool = False

    model_config = {"extra": "forbid"}


class _AgentSpecSchema(BaseModel):
    name: str
    model: str = ""  # default filled in later based on is_manager
    fallback_model: str = ""
    role: str = ""
    system_prompt: str = ""
    expertise: str = ""
    expertise_max_lines: int = 1000
    # P8.4 LO-8 — chief-rostering UX fields. AgentSpec (teams/_types.py:351-352)
    # already declares these with default ""; SpecialistSpec
    # (teams/_types.py:374-375) requires them; teams/_factory.py:46,93-94 reads
    # `emp.expertise_summary or emp.role` and `emp.when_to_call or emp.role or
    # emp.name`. Pre-P8.4 the schema's `extra: forbid` rejected YAMLs that
    # tried to set these, so the runtime fell through to the `or` chains and
    # the chief's "## Your Team" block printed roles instead of the documented
    # "Call alpha when you need X, Y, or Z." Adding the fields closes the
    # schema-vs-types drift; populating worker YAMLs is a separate sprint.
    expertise_summary: str = ""
    when_to_call: str = ""
    # Sprint 04.04 (2026-04-30 delete-it path): execution_mode removed.
    # YAMLs that still carry an execution_mode line are accepted for
    # backward compat (model_config below uses "ignore" for unknown
    # fields when applicable), but the field is no longer plumbed to
    # AgentSpec. Future dual-mode work should reintroduce this via the
    # AgentExecutor Protocol surface in teams/_executor.py.
    retries: int = 1
    max_tokens: int = 4096
    tools: list[str] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)
    domain: _DomainSchema = Field(default_factory=_DomainSchema)
    thinking: str = ""
    max_turns: int = 10
    timeout_minutes: float = 10.0
    # Sprint 04.05 — optional cross-vendor adapter routing knob. Default
    # `claude` preserves the existing Anthropic / pydantic_ai pipeline so
    # YAMLs that omit the field load unchanged. `openrouter` routes the
    # member through `bridge.cross_model.openrouter_adapter`. Loader-side
    # validation only — wiring into agent_router.py is Sprint 04.07.
    adapter: str = DEFAULT_ADAPTER
    # E4.5 — per-employee MCP server allowlist. Empty = inherit team-level
    # allowed_tools. Non-empty = this specialist can only call servers in
    # this list. Per-employee wins over per-team (narrowest scope wins).
    allowed_mcp_servers: list[str] = Field(default_factory=list)

    model_config = {"extra": "forbid"}

    @classmethod
    def __get_validators__(cls):  # pragma: no cover — Pydantic v1 fallback
        yield from ()

    def model_post_init(self, __context: object) -> None:  # type: ignore[override]
        if self.adapter not in ALLOWED_ADAPTERS:
            allowed = ", ".join(sorted(ALLOWED_ADAPTERS))
            raise ValueError(
                f"adapter '{self.adapter}' not recognised; "
                f"allowed values: {allowed}"
            )


class _ToolsSchema(BaseModel):
    common: list[str] = Field(default_factory=list)
    department: list[str] = Field(default_factory=list)
    per_employee: dict[str, list[str]] = Field(default_factory=dict)
    # E4.5 — team-level tool-name allowlist (NOT MCP-server allowlist; see
    # `_MCPSchema` below for the server-level filter). Empty = no narrowing
    # (today's default). Non-empty = every employee is restricted to these
    # tool names unless their own legacy `allowed_mcp_servers` override
    # narrows further. Narrowest scope wins.
    allowed_tools: list[str] = Field(default_factory=list)
    # Sprint P2.4 — explicit blocklist applied AFTER `allowed_tools`.
    # Catches "all tools EXCEPT these dangerous ones" patterns; a name
    # listed here is removed even if it would otherwise be allowed. Empty
    # = no extra removal (today's behaviour).
    denied_tools: list[str] = Field(default_factory=list)

    model_config = {"extra": "forbid"}


class _MCPSchema(BaseModel):
    """Sprint P2.4 — explicit MCP-server-level allowlist schema.

    This is a separate concern from `_ToolsSchema.allowed_tools` (which is a
    tool-NAME allowlist that filters the in-process pydantic-ai tool
    registry). `_MCPSchema` controls which MCP SERVERS the department's
    Claude subprocess sees in its filtered `.mcp.json` config.

    Both layers compose: a tool name not in `tools.allowed_tools` cannot
    be invoked by any specialist even if its underlying server is allowed
    here; conversely, an MCP server not in `mcp.allowed_servers` (under
    `deny_by_default`) cannot be reached even if some tool referenced it.
    """

    mode: str = DEFAULT_MCP_MODE
    allowed_servers: list[str] = Field(default_factory=list)

    model_config = {"extra": "forbid"}

    def model_post_init(self, __context: object) -> None:  # type: ignore[override]
        if self.mode not in ALLOWED_MCP_MODES:
            allowed = ", ".join(sorted(ALLOWED_MCP_MODES))
            raise ValueError(
                f"mcp.mode '{self.mode}' not recognised; "
                f"allowed values: {allowed}"
            )


class _TeamSchema(BaseModel):
    name: str
    zone: int
    description: str = ""
    chief: _AgentSpecSchema
    workers: list[_AgentSpecSchema] = Field(default_factory=list)
    constraints: _ConstraintsSchema = Field(default_factory=_ConstraintsSchema)
    budget: _BudgetSchema = Field(default_factory=_BudgetSchema)
    vapi: _VAPISchema = Field(default_factory=_VAPISchema)
    tools: _ToolsSchema = Field(default_factory=_ToolsSchema)
    # Sprint P2.4 — split out from the legacy top-level `mcp_servers` list.
    # The new nested form makes the mode + server-allowlist explicit and
    # validates against `ALLOWED_MCP_MODES`. Backward compat: when the
    # block is omitted, the schema default is `permissive` with an empty
    # list (today's "inherit bridge default" behaviour).
    mcp: _MCPSchema = Field(default_factory=_MCPSchema)
    escalation: Optional[_EscalationTriggerSchema] = None

    model_config = {"extra": "forbid"}


class _RootSchema(BaseModel):
    team: _TeamSchema
    mcp_servers: list = []  # noqa: RUF012 — declared in YAMLs, ignored by config loader

    model_config = {"extra": "forbid"}


# ---------------------------------------------------------------------------
# Conversion helpers: validated schema → domain types
# ---------------------------------------------------------------------------


def _collapse_wildcard_reads(reads: list[str]) -> tuple[str, ...]:
    """Collapse the ``read: ["*"]`` YAML idiom to an empty tuple.

    Sprint P3.5 (#1726): the established YAML convention (see
    ``_template.yaml``) uses ``read: ["*"]`` to mean "this agent can read
    anywhere". Downstream the tool-registry wrapper treats an empty
    ``read_paths`` as "no enforcement", so collapsing the wildcard here
    preserves backward compat for the 5 teams (board, design, ops,
    strategy, qa) that declare it. A list containing ``"*"`` alongside
    other globs is treated as wildcard-dominant — explicit allowlists
    must omit ``"*"`` entirely to take effect.
    """
    if not reads:
        return ()
    if "*" in reads:
        return ()
    return tuple(reads)


def _agent_spec_from_schema(schema: _AgentSpecSchema, *, is_manager: bool) -> AgentSpec:
    """Convert a validated _AgentSpecSchema to an AgentSpec domain type."""
    default_model = "opus-4.6" if is_manager else "sonnet-4.6"
    raw_model = schema.model or default_model
    return AgentSpec(
        name=schema.name,
        model=_normalize_model_string(raw_model),
        fallback_model=(
            _normalize_model_string(schema.fallback_model)
            if schema.fallback_model
            else ""
        ),
        role=schema.role,
        system_prompt_path=schema.system_prompt,
        expertise_path=schema.expertise,
        # Sprint 04.04 (2026-04-30): execution_mode removed from
        # AgentSpec — schema.execution_mode is silently dropped here.
        # See teams/_executor.py docstring for context.
        retries=schema.retries,
        max_tokens=schema.max_tokens,
        tools=tuple(schema.tools),
        deny_write_paths=tuple(schema.domain.deny_write),
        # Sprint P3.5 (#1726): plumb ``domain.read`` through the loader so the
        # tool-registry wrapper can enforce read-path allowlists. Mirrors the
        # ``deny_write_paths`` line above. ``read: ["*"]`` is the established
        # YAML idiom for "read-anywhere" (see _template.yaml's domain block);
        # we collapse it to ``()`` here so the registry wrapper's
        # "empty = no enforcement" contract works without a per-token
        # wildcard check downstream. Teams with an empty/missing ``read``
        # block also produce ``()``. Only non-wildcard, non-empty
        # declarations (today: the 5 job_search entries on
        # ``["config/job-search/**", "job_search/**"]``) become enforced.
        read_paths=_collapse_wildcard_reads(schema.domain.read),
        # P8.4 LO-8 — plumb chief-rostering UX fields from schema to AgentSpec.
        expertise_summary=schema.expertise_summary,
        when_to_call=schema.when_to_call,
        skills=tuple(schema.skills),
        adapter=schema.adapter,
        allowed_mcp_servers=tuple(schema.allowed_mcp_servers),
    )


def _constraints_from_schema(schema: _ConstraintsSchema) -> Constraints:
    return Constraints(
        cost_limit_usd=schema.cost_limit_usd,
        timeout_seconds=schema.timeout_seconds,
        concurrency_limit=schema.concurrency_limit,
        request_limit=schema.usage_limits.request_limit,
        request_token_limit=schema.usage_limits.request_token_limit,
        response_token_limit=schema.usage_limits.response_token_limit,
        expected_min_specialists=schema.expected_min_specialists,
        warm_idle_timeout_seconds=schema.warm_idle_timeout_seconds,
    )


def _budget_from_schema(schema: _BudgetSchema) -> Budget:
    return Budget(
        daily_limit_usd=schema.daily_limit_usd,
        alert_thresholds=tuple(schema.alert_thresholds),
    )


def _vapi_from_schema(schema: _VAPISchema) -> VAPIReceptionist:
    return VAPIReceptionist(
        enabled=schema.enabled,
        model=schema.model,
        voice=schema.voice,
        greeting=schema.greeting,
        tools=tuple(schema.tools),
    )


# ---------------------------------------------------------------------------
# Adapter ↔ model-prefix consistency check (Sprint 04.07 / #1961)
# ---------------------------------------------------------------------------


def _warn_adapter_model_mismatch(
    spec: AgentSpec, *, path: Path, role: str
) -> None:
    """WARN at load time when ``adapter`` and ``model:`` prefix disagree.

    The runtime routes by model-string prefix (see
    ``teams._factory._resolve_model``), so a YAML that declares
    ``adapter: "claude"`` alongside ``model: "openrouter:..."`` is internally
    inconsistent. Strategy 1 (prefix-based routing) makes the runtime do
    the right thing anyway, but the operator-visible intent is contradictory.

    Two mismatch shapes are warned:

    - ``adapter: "claude"`` + ``model: "openrouter:*"`` — runtime routes
      through OpenRouter, contradicting the declared ``claude`` intent.
      This is the shape that exists today across 6 department YAMLs
      (board, qa, design, strategy, ops, job_search).
    - ``adapter: "openrouter"`` + ``model:`` without ``openrouter:`` prefix
      — runtime routes through pydantic-ai's default Anthropic provider,
      contradicting the declared ``openrouter`` intent.

    We emit a WARNING rather than raise so existing deployed YAMLs continue
    to load; CI gates that pin warning counts (and the validate-team-yaml
    --strict path) surface the contradiction without forcing immediate
    YAML surgery.
    """
    model_has_openrouter_prefix = spec.model.startswith(_OPENROUTER_MODEL_PREFIX)
    if spec.adapter == "claude" and model_has_openrouter_prefix:
        log.warning(
            "%s [%s/%s] adapter=claude but model=%s starts with 'openrouter:' — "
            "runtime routes through OpenRouter (prefix wins, #1961). Update "
            "adapter to 'openrouter' or change the model string to remove "
            "the prefix.",
            path,
            role,
            spec.name,
            spec.model,
        )
    elif spec.adapter == "openrouter" and not model_has_openrouter_prefix:
        log.warning(
            "%s [%s/%s] adapter=openrouter but model=%s lacks 'openrouter:' "
            "prefix — runtime falls through to pydantic-ai's default "
            "provider (#1961). Add the 'openrouter:' prefix to the model "
            "string or change adapter to 'claude'.",
            path,
            role,
            spec.name,
            spec.model,
        )


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def load_department_config(path: str | Path) -> DepartmentConfig:
    """Load and validate a department YAML config, raising InvalidConfigError on any problem.

    Typos in field names now surface as ``InvalidConfigError`` at load time
    rather than silently reverting to defaults. (Sprint B-S.3)
    """
    path = Path(path)
    if not path.exists():
        raise InvalidConfigError(f"Config file not found: {path}")

    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise InvalidConfigError(f"Could not read {path}: {exc}") from exc

    config = load_department_config_from_string(text, source=str(path))
    return replace(
        config,
        capability_manifest_enforced=_is_canonical_team_config_path(path),
    )


def _is_canonical_team_config_path(path: Path) -> bool:
    try:
        return path.resolve().parent == _CANONICAL_TEAMS_ROOT
    except OSError:
        return False


def load_department_config_from_string(
    yaml_text: str, *, source: str = "<string>"
) -> DepartmentConfig:
    """Parse and validate a department YAML body without touching the filesystem.

    Tests use this to round-trip schema changes (e.g. zone4-warmth.D.01's
    ``warm_idle_timeout_seconds``) without writing temp files.
    ``source`` flows into error messages so a failure points back at the
    caller's test name rather than ``<string>``.
    """
    try:
        raw = yaml.safe_load(yaml_text)
    except yaml.YAMLError as exc:
        raise InvalidConfigError(f"YAML parse error in {source}: {exc}") from exc

    if not isinstance(raw, dict):
        raise InvalidConfigError(f"Config {source}: top-level must be a mapping")

    # Sprint B-S.3: validate via Pydantic schema — unknown fields are rejected
    try:
        validated = _RootSchema.model_validate(raw)
    except ValidationError as exc:
        raise InvalidConfigError(
            f"Config validation error in {source}:\n{exc}"
        ) from exc

    team = validated.team
    manager = _agent_spec_from_schema(team.chief, is_manager=True)
    employees = tuple(
        _agent_spec_from_schema(w, is_manager=False) for w in team.workers
    )
    # Sprint 04.07 (#1961) — surface adapter ↔ model prefix contradictions
    # at load time. Runtime routes by prefix (see _factory._resolve_model);
    # this warning makes a divergent operator intent visible in logs and CI.
    path = Path(source) if source != "<string>" else Path(source)
    _warn_adapter_model_mismatch(manager, path=path, role="chief")
    for emp in employees:
        _warn_adapter_model_mismatch(emp, path=path, role="worker")
    constraints = _constraints_from_schema(team.constraints)
    budget = _budget_from_schema(team.budget)
    vapi = _vapi_from_schema(team.vapi)

    common_tools = tuple(team.tools.common)
    department_tools = tuple(team.tools.department)
    per_employee_tools: dict[str, tuple[str, ...]] = {
        name: tuple(tools)
        for name, tools in team.tools.per_employee.items()
    }

    return DepartmentConfig(
        name=team.name,
        zone=team.zone,
        description=team.description,
        manager=manager,
        employees=employees,
        constraints=constraints,
        budget=budget,
        vapi=vapi,
        common_tools=common_tools,
        department_tools=department_tools,
        per_employee_tools=per_employee_tools,
        allowed_tools=tuple(team.tools.allowed_tools),
        denied_tools=tuple(team.tools.denied_tools),
        mcp_mode=team.mcp.mode,
        mcp_allowed_servers=tuple(team.mcp.allowed_servers),
    )


def load_team_limits(teams_dir: str | Path | None = None) -> dict[str, float]:
    """Read ``team.budget.daily_limit_usd`` from every ``*.yaml`` in *teams_dir*.

    Args:
        teams_dir: Directory containing team YAML files. Defaults to
            ``agent/config/teams/`` relative to this file's package root.

    Returns:
        Mapping from team name (file stem, e.g. ``"design"``) to the
        configured daily cap in USD. Teams missing the field are skipped
        with a WARNING so a single YAML typo does not break startup.
    """
    if teams_dir is None:
        teams_dir = Path(__file__).resolve().parent.parent / "config" / "teams"
    teams_dir = Path(teams_dir)
    out: dict[str, float] = {}
    for yaml_path in sorted(teams_dir.glob("*.yaml")):
        # D7.13 #1425 — `_template.yaml` and other `_*` files are
        # non-runtime; skip them at the budget loader the same way
        # `_registry.py` does at discovery.
        if yaml_path.name.startswith("_"):
            continue
        try:
            raw = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
        except Exception as exc:
            log.warning("load_team_limits: failed to parse %s: %s", yaml_path.name, exc)
            continue
        try:
            limit = float(raw["team"]["budget"]["daily_limit_usd"])
        except (KeyError, TypeError, ValueError):
            log.warning(
                "load_team_limits: %s has no team.budget.daily_limit_usd", yaml_path.name
            )
            continue
        out[yaml_path.stem] = limit
    return out
