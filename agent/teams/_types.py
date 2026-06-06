"""Core type definitions for the teams package."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Mapping, Optional

from pydantic import BaseModel, Field

from teams._run_telemetry import RunTelemetry


@dataclass(frozen=True)
class BridgeDeps:
    """Dependencies injected into every department tool at dispatch time.

    All fields except ``cost_limit_usd`` are required. There is no silent
    degradation path — if the live BridgeApp cannot populate a field, that
    must surface as a construction-time error, not as a tool-call-time
    "[no knowledge store]" string the LLM treats as truth.

    Use ``BridgeDeps.from_app()`` at every production construction site.
    """

    session_id: str
    department: str
    operator_id: str
    memory_store: Any
    event_bus: Any
    trust_manager: Any
    cost_tracker: Any
    knowledge_search: Any
    cost_limit_usd: float = 2.0  # route-time override ok; loaded from dept config
    mcp_allowed_servers: tuple[str, ...] = ()  # empty = inherit bridge default (permissive)
    # Sprint P2.4 — MCP-server-level mode. Carried alongside
    # `mcp_allowed_servers` so the registry can distinguish "empty list
    # under permissive mode (inherit bridge default)" from "empty list
    # under deny_by_default (no MCP servers at all)". Default is
    # "permissive" — preserves today's behaviour for every existing
    # construction site that omits the field.
    mcp_mode: str = "permissive"
    permission_mode: str = "bypassPermissions"  # #630: threaded from wo.constraints.permission_mode
    # Sprint 04.08: root directory for Z4 session artefacts (conversation.jsonl,
    # tool traces, meta.json). When set, DepartmentRegistry constructs a
    # ConversationLogger at sessions_dir/<sid>/<dept>/conversation.jsonl so the
    # /api/z4/sessions/{sid}/departments/{dept}/conversation reader sees real
    # content. None disables conversation logging (back-compat with existing
    # callers that don't pass it).
    sessions_dir: Optional[Path] = None
    # Sprint 20 (Phase 5B): live Database handle for tools that write to the
    # directive_store / task_store. None disables status writes — the chief
    # still works, but lifecycle transitions for any active directive_id /
    # task_id will not be recorded. Backward-compat with all existing test
    # fixtures that hand-build BridgeDeps with positional args.
    database: Any = None
    # Sprint 21 (Phase 5B): active directive_id flowing through the request,
    # set by DepartmentRegistry.route() when called with a directive id. The
    # chief's delegate() tool reads this to correlate the Tasks it creates
    # with the parent Directive. None when the chief was invoked outside a
    # directive flow (legacy /route, cron path).
    directive_id: Optional[str] = None
    # Sprint 21 (Phase 5B): active task_id, set on a per-specialist child
    # BridgeDeps when the chief's delegate() tool invokes the specialist.
    # Specialists can read this for future Surface correlation. None at the
    # chief tier and on the Main Agent path.
    task_id: Optional[str] = None
    # Sprint 22 PR B (Phase 5C): a duck-typed BridgeApp reference so
    # chief-side tools (surface() notification hook) can reach the live
    # Discord client without an import-time dependency on bridge.app.
    # None outside the live bridge daemon (test fixtures, cron context),
    # in which case the notification hook is a clean no-op.
    app: Any = None
    # Sprint P3.5 (2026-05-11 audit): explicit opt-in escape hatch for unit
    # tests that drive chief/specialist tools without spinning up a Database.
    # In production paths (deps.database is None AND directive_id is set), the
    # surface tool would otherwise silently degrade to a placeholder
    # surface_id; with allow_no_surface_store=False (default), that silent
    # degradation is upgraded to MissingSurfaceStoreError so the chief work
    # halts rather than handing back an un-correlated answer. Tests that
    # genuinely don't need a surface store pass allow_no_surface_store=True.
    allow_no_surface_store: bool = False
    # Sprint zone4-warmth (#2313, 2026-05-18): per-run mutable collector that
    # the chief's ``delegate`` tool appends to on every successful or failed
    # specialist invocation. Threaded through ``BridgeDeps`` — NOT captured in
    # the delegate tool's closure — because ``build_manager_agent`` caches the
    # chief Agent (A.02 / #2306) and a closure-captured list would bind to
    # the FIRST team build's collector forever, leaving warm-reuse runs with
    # an empty ``team.employee_results`` tuple. Construct deps with a fresh
    # collector per ``DepartmentTeam.run()`` call (see ``teams/_team.py``).
    # ``None`` disables result capture — back-compat for the handful of
    # construction sites that build a chief outside ``DepartmentTeam`` and
    # never need the populated list.
    employee_results_collector: Optional[list["EmployeeResult"]] = None
    # Z4-03 (2026-05-21 team-operability): durable raw run artifacts live
    # under artifact_root, not in the bumba-open-harness repository. project_root is a
    # metadata hint for target-project-relative suggestions, not a raw-write
    # destination.
    artifact_root: Optional[Path] = None
    project_root: Optional[Path] = None
    run_artifact_dir: Optional[Path] = None
    # Z4-07 (2026-05-21 team-operability): optional browser/computer-use trace
    # writer bound to this run's artifact workspace. Kept duck-typed so teams
    # can use bridge.browser_trace without importing bridge at dataclass load.
    browser_trace: Any = None
    # WS3.2 (#2570) — per-workflow cost attribution. When a department step is
    # driven by a WorkflowEngine run, the shim threads the workflow name here
    # so the existing team_run cost row (recorded in _team.py) is TAGGED with
    # the workflow — it is NOT a second cost record. Empty string = no
    # workflow attached (every legacy construction site keeps the default).
    workflow: str = ""

    @classmethod
    def from_app(
        cls,
        app: Any,
        *,
        session_id: str,
        department: str,
        cost_limit_usd: float = 2.0,
        mcp_allowed_servers: tuple[str, ...] = (),
        mcp_mode: str = "permissive",
        permission_mode: str = "bypassPermissions",
        workflow: str = "",
    ) -> "BridgeDeps":
        """Construct BridgeDeps by pulling all fields from the live BridgeApp.

        ``app`` is duck-typed: any object that exposes the attributes below.
        Raises ``AttributeError`` if a required attribute is missing.
        """
        # Pull operator_id from config if available
        operator_id: str = ""
        try:
            operator_id = app.config.operator.chat_id or ""
        except AttributeError:
            # Try bridge-style config
            try:
                operator_id = app._config.operator_discord_id or ""
            except AttributeError:
                pass

        # Sprint 04.08: derive sessions_dir from config.data_dir/z4-sessions —
        # the same root used by ToolTracker and the Zone4Routes reader at
        # bridge/observability/api_routes.py. We do not require the directory
        # to exist (ConversationLogger.__init__ creates parents on first write).
        sessions_dir: Optional[Path] = None
        try:
            data_dir = getattr(app.config, "data_dir", None)
            if data_dir:
                sessions_dir = Path(data_dir) / "z4-sessions"
        except AttributeError:
            sessions_dir = None

        # Sprint 20+21 (Phase 5B): plumb the live Database through so chief-side
        # tools (acknowledge_directive, delegate's task_store writes) work
        # without reaching into BridgeApp directly. BridgeApp exposes the
        # Database as ``app._db``; some test doubles use ``app.database`` so
        # we accept either. Falls back to None if neither is present, in which
        # case lifecycle writes silently degrade — existing non-directive
        # flows are unaffected.
        database = getattr(app, "_db", None) or getattr(app, "database", None)

        artifact_root: Optional[Path] = None
        try:
            configured_root = getattr(app.config, "zone4_artifact_root", None)
            if configured_root:
                artifact_root = Path(configured_root).expanduser()
        except AttributeError:
            artifact_root = None

        project_root: Optional[Path] = None
        configured_project_root = getattr(app, "project_root", None)
        if configured_project_root:
            project_root = Path(configured_project_root).expanduser()

        return cls(
            session_id=session_id,
            department=department,
            operator_id=operator_id,
            memory_store=app.memory,
            knowledge_search=app.knowledge_search,
            cost_tracker=app.cost_tracker,
            event_bus=app.event_bus,
            trust_manager=app.trust_manager,
            cost_limit_usd=cost_limit_usd,
            mcp_allowed_servers=mcp_allowed_servers,
            mcp_mode=mcp_mode,
            permission_mode=permission_mode,
            sessions_dir=sessions_dir,
            database=database,
            app=app,
            artifact_root=artifact_root,
            project_root=project_root,
            workflow=workflow,
        )

    @classmethod
    async def for_cron(
        cls,
        department: str,
        session_id: str,
        *,
        data_dir: str | None = None,
        cost_limit_usd: float = 2.0,
        mcp_allowed_servers: tuple[str, ...] = (),
        mcp_mode: str = "permissive",
        permission_mode: str = "bypassPermissions",
    ) -> "BridgeDeps":
        """Construct BridgeDeps for a standalone cron invocation (no live BridgeApp).

        Sprint 02.08: replaces the ``unittest.mock.MagicMock``-based stub that
        previously forfeited event fan-out, trust gating, and cost tracking from
        cron job_search runs. Each field is now a real bridge object.

        - ``memory_store``  → :class:`bridge.memory.MemoryKVAdapter` wrapping a
          :class:`bridge.memory.Memory` constructed with
          ``embedding_client=None`` (semantic search degrades cleanly to FTS5).
        - ``knowledge_search`` → ``Memory.search_knowledge`` (FTS5 path when no
          embedding client is configured).
        - ``event_bus`` → :class:`bridge.event_bus.EventBus` writing to a per-
          cron sub-directory at ``<DATA_DIR>/cron/<session_id>/events/<date>.jsonl``
          so each cron run produces a replayable event stream the operator can
          ``grep`` post-deploy.
        - ``cost_tracker`` → :class:`bridge.cost_tracker.CostTracker` writing to
          the bridge canonical ``<DATA_DIR>/cost_tracking.jsonl`` so cron costs
          aggregate with the rest of the daily/weekly summary.
        - ``trust_manager`` → :class:`bridge.trust_score.TrustScoreEngine` rooted
          at ``<DATA_DIR>`` so it shares state with the live bridge daemon.

        The function is async because constructing real :class:`bridge.memory.Memory`
        requires a connected :class:`bridge.database.Database`. Cron callers
        already wrap their entry point in ``asyncio.run`` so this fits naturally.

        Args:
            department: Department name (e.g. ``"job_search"``).
            session_id: Unique session id used to namespace the per-cron event
                stream sub-directory.
            data_dir: Override the default ``BridgeConfig.data_dir`` (canonical
                ``/opt/bumba-harness/data``). Tests pass a tmp_path here.
            cost_limit_usd: Forwarded to the returned BridgeDeps.
            mcp_allowed_servers: Forwarded to the returned BridgeDeps.
            permission_mode: Forwarded to the returned BridgeDeps.

        Returns:
            A fully-populated, real-object BridgeDeps suitable for routing
            through :class:`teams._registry.DepartmentRegistry`.
        """
        # Lazy imports so teams/_types.py stays import-cheap and avoids
        # pulling in the bridge package at module scope (the bridge has its
        # own larger dependency graph).
        from bridge.config import BridgeConfig
        from bridge.cost_tracker import CostTracker
        from bridge.database import Database
        from bridge.event_bus import EventBus
        from bridge.memory import Memory, MemoryKVAdapter
        from bridge.trust_score import TrustScoreEngine

        config = BridgeConfig(data_dir=data_dir) if data_dir else BridgeConfig()
        resolved_data_dir = Path(config.data_dir)
        resolved_data_dir.mkdir(parents=True, exist_ok=True)

        # Real Memory (FTS5-only fallback — embedding_client=None).
        # migrate() is idempotent: on production this is a no-op since the
        # bridge daemon has already migrated; in tests with a tmp_path it
        # creates the knowledge / knowledge_fts tables FTS5 search needs.
        db_path = resolved_data_dir / "memory.db"
        db = Database(db_path)
        await db.connect()
        await db.migrate()
        memory = Memory(db, config, embedding_client=None)
        memory_store = MemoryKVAdapter(memory)

        # Per-cron event stream — keeps cron events inspectable per session_id
        # while leaving production EventBus writes untouched.
        cron_event_dir = resolved_data_dir / "cron" / session_id
        cron_event_dir.mkdir(parents=True, exist_ok=True)
        event_bus = EventBus(data_dir=cron_event_dir)

        cost_tracker = CostTracker(data_dir=resolved_data_dir)
        trust_manager = TrustScoreEngine(data_dir=resolved_data_dir)

        return cls(
            session_id=session_id,
            department=department,
            operator_id="",
            memory_store=memory_store,
            event_bus=event_bus,
            trust_manager=trust_manager,
            cost_tracker=cost_tracker,
            knowledge_search=memory.search_knowledge,
            cost_limit_usd=cost_limit_usd,
            mcp_allowed_servers=mcp_allowed_servers,
            mcp_mode=mcp_mode,
            permission_mode=permission_mode,
            artifact_root=Path(config.zone4_artifact_root).expanduser(),
        )


@dataclass(frozen=True)
class EmployeeResult:
    employee_name: str
    output: str
    success: bool = True
    error: str | None = None
    tokens_used: int = 0
    duration_seconds: float = 0.0


class TeamOutput(BaseModel):
    """Structured output returned by a department manager agent (sprint B2.2).

    Replaces the free-form ``str`` that ``output_type=str`` produced.
    """

    answer: str
    """The synthesised answer or decision from the manager."""

    handoff_id: Optional[str] = None
    """Correlation ID of a HandoffEnvelope if the manager is handing off work."""

    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    """Manager's self-reported confidence in the answer (0.0–1.0)."""

    specialist_outputs: list[str] = Field(default_factory=list)
    """Raw outputs collected from each specialist during this run."""

    model_config = {"extra": "forbid"}


@dataclass(frozen=True)
class TeamResult:
    department: str
    manager_output: str
    employee_results: tuple[EmployeeResult, ...] = ()
    total_tokens: int = 0
    total_cost_usd: float = 0.0
    duration_seconds: float = 0.0
    success: bool = True
    error: str | None = None
    structured: Optional[TeamOutput] = None  # B2.2: populated when manager returns TeamOutput
    # Sprint P3.5 (2026-05-11 audit): id of the chief→main RESULT surface
    # written on synthesis return, when a directive_id is in scope and the
    # database is wired. None when (a) no directive_id was supplied (legacy
    # /route, cron path), (b) allow_no_surface_store=True bypass was used,
    # or (c) the chief did not synthesise (timeout/error before completion).
    surface_id: Optional[str] = None
    # Z4-02 (2026-05-21): deterministic per-run metadata for provider path,
    # usage counts, specialist counts, durable writes, and normalized failures.
    telemetry: Optional[RunTelemetry] = None
    # Z4-05 (2026-05-21): durable run relay pointers returned to the main
    # agent after a Zone 4 run. Artifact bodies stay on disk; callers receive
    # concrete pointers they can use to inspect prior work.
    run_id: Optional[str] = None
    manifest_path: Optional[str] = None
    memory_ref: Optional[str] = None


@dataclass(frozen=True)
class Constraints:
    cost_limit_usd: float = 2.0
    timeout_seconds: int = 600
    concurrency_limit: int = 4
    request_limit: int = 20
    request_token_limit: int = 250_000
    response_token_limit: int = 250_000
    # Sprint 04.15 / Gate 8: minimum specialist count enforced by
    # teams._verify.verify_team_result. Default 0 disables the gate so
    # backward-compatible direct-answer department tests keep passing.
    # Real production department YAMLs opt in by setting this to a positive
    # integer (commonly len(employees) for strict delegation enforcement).
    expected_min_specialists: int = 0
    # zone4-warmth.D.01 (#2299) — optional per-team override for the warm
    # idle-timeout window the reaper uses on AWAITING_EVALUATION sessions.
    # ``None`` means "use the global
    # ``config.chief_dispatcher_idle_timeout_seconds`` default". When set,
    # this department's AWAITING_EVALUATION sessions are reaped after this
    # many seconds idle. See docs/plans/2026-05-18-zone4-warmth/.
    warm_idle_timeout_seconds: int | None = None


@dataclass(frozen=True)
class Budget:
    daily_limit_usd: float = 5.0
    alert_thresholds: tuple[float, ...] = (0.5, 0.75, 0.9)


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str = ""
    scope: str = "common"


@dataclass(frozen=True)
class VAPIReceptionist:
    enabled: bool = False
    model: str = "gpt-4o-mini"
    voice: str = "shimmer"
    greeting: str = ""
    tools: tuple[str, ...] = ()


@dataclass(frozen=True)
class AgentSpec:
    name: str
    model: str
    role: str = ""
    system_prompt_path: str = ""
    expertise_path: str = ""
    retries: int = 1
    max_tokens: int = 4096
    tools: tuple[str, ...] = ()
    deny_write_paths: tuple[str, ...] = ()
    # Sprint P3.5 (#1726, 2026-05-12): per-agent read-path allowlist enforced
    # at tool-call time by ``teams._tool_registry.make_tracked`` for read tools
    # (currently ``read_file``). Empty tuple = no enforcement (opt-in via the
    # agent's YAML ``domain.read`` field) — preserves backward compat with the
    # 5 teams that today declare ``["*"]`` or omit the block. Non-empty tuple =
    # only paths matching one of these globs may be read; violations return
    # ``DOMAIN_VIOLATION:`` to the LLM and emit ``z4.domain.violation``.
    # Mirrors the ``deny_write_paths`` precedent from Sprint 04.05.
    read_paths: tuple[str, ...] = ()
    expertise_summary: str = ""
    when_to_call: str = ""
    skills: tuple[str, ...] = ()
    # Sprint 04.05 — cross-vendor adapter selection from board.yaml.
    # `claude` (default) routes through the existing Anthropic pipeline;
    # `openrouter` routes through bridge.cross_model.openrouter_adapter.
    # Loader-validated against `teams._config.ALLOWED_ADAPTERS`.
    adapter: str = "claude"
    # Optional manager-level fallback. Empty means no fallback. When set,
    # DepartmentTeam may retry a rate-limited chief call against this model.
    fallback_model: str = ""
    # E4.5 — per-employee MCP server allowlist. Empty = inherit team-level.
    allowed_mcp_servers: tuple[str, ...] = ()


@dataclass(frozen=True)
class SpecialistSpec:
    """Runtime-introspectable spec for one specialist in a chief's roster.

    Sprint 19 (Phase 5A): the chief calls ``list_specialists()`` and gets back
    a tuple of these. The chief's LLM uses ``when_to_call`` to decide which
    specialist to dispatch; ``domain_write_paths`` is informational only here
    (enforcement lives in the executor write-jail).
    """

    name: str
    role: str
    expertise_summary: str
    when_to_call: str
    domain_write_paths: tuple[str, ...]


@dataclass(frozen=True)
class Roster:
    """The chief's team as the chief sees it at runtime.

    Sprint 19 (Phase 5A): replaces the implicit roster-via-tool-docstrings
    pattern. ``specialists`` preserves YAML order so the chief's prompt and
    its ``list_specialists()`` output are deterministic.
    """

    department: str
    chief_name: str
    specialists: tuple[SpecialistSpec, ...]

    def get(self, name: str) -> "SpecialistSpec | None":
        """Return the SpecialistSpec for ``name`` or None if absent."""
        for s in self.specialists:
            if s.name == name:
                return s
        return None

    def names(self) -> tuple[str, ...]:
        """Return all specialist names in YAML order."""
        return tuple(s.name for s in self.specialists)


@dataclass(frozen=True)
class DepartmentConfig:
    name: str
    zone: int
    description: str
    manager: AgentSpec
    employees: tuple[AgentSpec, ...]
    constraints: Constraints = field(default_factory=Constraints)
    budget: Budget = field(default_factory=Budget)
    vapi: VAPIReceptionist = field(default_factory=VAPIReceptionist)
    common_tools: tuple[str, ...] = ()
    department_tools: tuple[str, ...] = ()
    per_employee_tools: dict[str, tuple[str, ...]] = field(default_factory=dict)
    # E4.5 — team-level TOOL-NAME allowlist (applies to the in-process
    # pydantic-ai tool registry, not the MCP server list). Empty = no
    # narrowing; non-empty = a tool not in this list cannot be registered
    # on any employee for this team.
    allowed_tools: tuple[str, ...] = ()
    # Sprint P2.4 — explicit blocklist on top of `allowed_tools`. Names in
    # this list are removed AFTER `allowed_tools` filtering, so denied wins
    # over allowed. Use for "everything in allowed_tools EXCEPT these"
    # patterns. Empty = no extra removal (today's behavior).
    denied_tools: tuple[str, ...] = ()
    # Sprint P2.4 — MCP-server-level allowlist (distinct from tool-name
    # allowlist above). Empty + mode="permissive" = inherit bridge default
    # (every server in `.mcp.json` is reachable). Non-empty = filter the
    # master MCP config down to only these servers. Mode "deny_by_default"
    # with an empty list = no MCP servers (the chief / specialist runs
    # with `{}` config).
    mcp_mode: str = "permissive"
    mcp_allowed_servers: tuple[str, ...] = ()
    # Z4-14: production team YAMLs opt into Tool Shed capability manifests
    # at load time. Direct unit-test fixtures default to isolated behavior so
    # a synthetic config named "strategy" does not inherit repo strict mode.
    capability_manifest_enforced: bool = False


# ---------------------------------------------------------------------------
# Sprint 20 (Phase 5B) — Directive protocol downward (Main Agent → chief)
# ---------------------------------------------------------------------------


class DirectiveStatus(str, Enum):
    """Lifecycle states for a Directive issued by the Main Agent to a chief.

    The status transitions form a directed graph:

        ISSUED ──▶ ACCEPTED ──▶ IN_PROGRESS ──▶ DONE
                       │              │            │
                       ▼              ▼            ▼
                   CANCELLED       BLOCKED     CANCELLED
                                      │
                                      └──▶ ACCEPTED  (chief retried)

    Inherits from ``str`` so values are JSON-serialisable and compare cleanly
    against SQL string columns without coercion.
    """

    ISSUED = "issued"
    ACCEPTED = "accepted"
    IN_PROGRESS = "in_progress"
    DONE = "done"
    BLOCKED = "blocked"
    CANCELLED = "cancelled"


# Allowed priorities — also enforced at the database layer via CHECK constraint
# on the ``directives.priority`` column (migration #10).
DIRECTIVE_PRIORITIES: tuple[str, ...] = ("p0", "p1", "p2")


@dataclass(frozen=True)
class Directive:
    """A typed directive from the Main Agent to a department chief.

    Sprint 20 (Phase 5B): replaces the implicit ``/route <dept> <task>`` flow
    with a durable, correlated work item. Every directive is persisted to the
    ``directives`` table (migration #10) at issue time; status transitions
    append rows to ``directive_history`` so the lifecycle is reconstructible
    after a bridge restart.

    Fields are immutable. Status lives on the row in SQLite, not on the
    dataclass — the dataclass is the issuance envelope, not the live state.
    Read current status via ``directive_store.get_directive(id)``.

    Attributes:
        directive_id: ``dir-<12-hex>`` — generated by ``new_directive_id()``.
        from_agent: Logical name of the issuing agent (almost always
            ``"main"`` today; Sprint 24 may add cross-tier issuance).
        to_chief: Department chief name, e.g. ``"strategy-product-chief"``.
        intent: Free-form task description the chief LLM reads.
        constraints: Tuple of constraint strings prepended to the chief's
            initial prompt (e.g. ``("budget=$2", "deadline=24h")``).
        deadline_utc: Optional UTC datetime; chief may surface BLOCKED if
            unreachable. Stored as ISO-8601 string in SQLite.
        priority: One of ``DIRECTIVE_PRIORITIES``. Validated at insert time.
        issued_at_utc: When the Main Agent created the directive.
        context: JSON-serialisable mapping of arbitrary side-channel context
            (correlation IDs, Discord message refs, …). Persisted as
            ``context_json`` in the row.
        operator_id: Discord chat_id or other operator identity at issue time
            — empty string if not derivable from session.
    """

    directive_id: str
    from_agent: str
    to_chief: str
    intent: str
    constraints: tuple[str, ...]
    deadline_utc: Optional[datetime]
    priority: str  # validated against DIRECTIVE_PRIORITIES at the boundary
    issued_at_utc: datetime
    context: Mapping[str, Any]
    operator_id: str


# ---------------------------------------------------------------------------
# Sprint 21 (Phase 5B) — Task protocol downward (chief → specialist)
# ---------------------------------------------------------------------------


class TaskStatus(str, Enum):
    """Lifecycle states for a Task issued by a chief to a specialist.

    Sprint 21 (Phase 5B). Inherits from ``str`` so values compare cleanly
    against SQL string columns and serialise to JSON without coercion.
    The state machine mirrors DirectiveStatus but starts at ASSIGNED
    (the chief picked the specialist) rather than ISSUED (the operator
    handed work to the chief).
    """

    ASSIGNED = "assigned"
    IN_PROGRESS = "in_progress"
    DONE = "done"
    BLOCKED = "blocked"
    CANCELLED = "cancelled"


@dataclass(frozen=True)
class Task:
    """A typed delegation envelope from a chief to one of its specialists.

    Sprint 21 (Phase 5B): Tasks are the chief→specialist analogue of
    Directives (Main Agent → chief). Every call to the chief's
    ``delegate(specialist, task, ...)`` tool creates one Task row and
    transitions it through ASSIGNED → IN_PROGRESS → DONE/BLOCKED.

    Tasks correlate to their parent Directive via ``directive_id``. A
    chief processing one Directive may issue multiple Tasks; the
    ``directive_id`` field threads them together so /tasks and the
    future /api/directives/{id}/tree endpoint can show the full call
    graph.

    Fields are immutable. Status lives on the row in SQLite, not on the
    dataclass. Read current status via ``task_store.get_status(id)``.

    Attributes:
        task_id: ``task-<12-hex>`` — generated by ``new_task_id()``.
        directive_id: Parent directive id. ``None`` when the chief was
            invoked outside a directive flow (legacy /route, cron path).
        from_chief: The chief that issued this task — config.manager.name.
        to_specialist: Specialist name from the chief's roster.
        description: The task text passed to ``delegate(task=...)``.
        constraints: Tuple of constraint strings prepended to the
            specialist's prompt at invocation time.
        deadline_utc: Optional deadline for the specialist's work.
        issued_at_utc: When the chief issued the delegation.
    """

    task_id: str
    directive_id: Optional[str]
    from_chief: str
    to_specialist: str
    description: str
    constraints: tuple[str, ...]
    deadline_utc: Optional[datetime]
    issued_at_utc: datetime


# ---------------------------------------------------------------------------
# Sprint 22 (Phase 5C) — Surface protocol upward (specialist → chief → main)
# ---------------------------------------------------------------------------


class SurfaceKind(str, Enum):
    """The semantic type of an upward-flowing Surface event.

    Sprint 22 (Phase 5C). Inherits from ``str`` so values compare cleanly
    against SQL string columns and serialise to JSON without coercion.

    - ``RESULT``: the work product. Required from specialists per task,
      and from chiefs per directive (the synthesis).
    - ``FLAG``: noteworthy observation that doesn't block progress.
    - ``BLOCKER``: cannot proceed without operator/upstream input.
    - ``SCOPE_REQUEST``: task requires work beyond the original scope.
    - ``CROSS_TEAM``: needs another department's specialist.
    - ``POLICY_Q``: governance / policy question for the operator.
    """

    RESULT = "result"
    FLAG = "flag"
    BLOCKER = "blocker"
    SCOPE_REQUEST = "scope_request"
    CROSS_TEAM = "cross_team"
    POLICY_Q = "policy_q"


class Urgency(str, Enum):
    """How aggressively a Surface should reach the operator.

    Sprint 22 (Phase 5C):
    - ``FYI``: visible in /surfaces only, no notification
    - ``ATTENTION``: Discord DM, plain formatting (PR B will wire this)
    - ``IMMEDIATE``: Discord DM with @operator mention (PR B will wire this)
    """

    FYI = "fyi"
    ATTENTION = "attention"
    IMMEDIATE = "immediate"


# Allowed kind/urgency strings — also enforced at the database layer via CHECK
# constraints (migration #12). Exported for consumers that want to validate
# inputs before constructing a Surface.
SURFACE_KINDS: tuple[str, ...] = tuple(k.value for k in SurfaceKind)
SURFACE_URGENCIES: tuple[str, ...] = tuple(u.value for u in Urgency)


@dataclass(frozen=True)
class Surface:
    """An upward-flowing event from a specialist to a chief, or chief to main.

    Sprint 22 (Phase 5C): Surfaces are the bidirectional protocol's upward
    leg. Every specialist must emit at least one ``RESULT`` surface per
    Task; ``_team.py`` synthesises one with ``payload.synthesized=true``
    if the specialist forgot. Chiefs emit a ``RESULT`` surface to ``main``
    on synthesis return for dashboard visibility.

    Mid-flight surfaces (FLAG, BLOCKER, SCOPE_REQUEST, CROSS_TEAM,
    POLICY_Q) let specialists and chiefs communicate progress, blockers,
    and policy questions without needing to terminate the run.

    Fields are immutable. ``read_at_utc`` lives on the row, not on the
    dataclass — this is the issuance envelope, not the live state.

    Attributes:
        surface_id: ``surf-<12-hex>`` — generated by ``new_surface_id()``.
        from_agent: Logical name of the emitting agent (specialist name
            or chief name).
        to_agent: Logical name of the recipient (chief name when
            specialist→chief, ``"main"`` when chief→Main Agent).
        kind: One of ``SurfaceKind``. Validated at insert time.
        urgency: One of ``Urgency``. Drives the notification path in PR B.
        correlation_id: ``task_id`` for specialist→chief, ``directive_id``
            for chief→main. NULL allowed for out-of-band surfaces (test
            fixtures, cron context where neither id is in scope).
        payload: JSON-serialisable mapping with the surface body
            (``summary``, ``output``, ``synthesized`` flag, etc.).
        created_at_utc: When the surface was emitted.
    """

    surface_id: str
    from_agent: str
    to_agent: str
    kind: SurfaceKind
    urgency: Urgency
    correlation_id: Optional[str]
    payload: Mapping[str, Any]
    created_at_utc: datetime
