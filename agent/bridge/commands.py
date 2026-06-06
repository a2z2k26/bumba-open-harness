"""Bridge and agent command handlers for all operator commands."""

from __future__ import annotations

import logging
import time
import tomllib
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import quote

from .command_handlers import (
    AgentsAndMemoryMixin,
    BoardAndVoiceMixin,
    CostAndZ4Mixin,
    DepartmentsMixin,
    JobsAndFactoryMixin,
    LifecycleMixin,
    SkillsAndHooksMixin,
    WikiMixin,
)
from .memory_writes import tail as _memory_writes_tail  # noqa: F401 — re-export for back-compat

if TYPE_CHECKING:
    from .claude_runner import ClaudeRunner
    from .database import Database
    from .message_queue import MessageQueue
    from .session_manager import SessionManager

logger = logging.getLogger(__name__)

# Agent command prefix
_AGENT_PREFIX = "The operator issued a management command. Respond concisely and factually."

# Mapping of agent commands to Claude prompts
_AGENT_COMMANDS: dict[str, str] = {
    "audit": 'Review the audit log and report: {args}. Use sqlite3 to query /opt/bumba-harness/data/memory.db',
    "permissions": "List all currently granted permissions from settings.json and report any that have changed since the last session.",
    "memory": "Search your memory for: {args}",
    "review": "Review your self-improvement tickets (knowledge keys matching 'decision:self-improvement:*') and present a prioritized list.",
    # NOTE: ``skills`` was previously a Claude-prompted "list files in
    # ~/.claude/skills/" command. Sprint 4.04 / #2151 replaces it with
    # the authoritative SkillAllocator-backed handler in
    # ``skills_and_hooks._cmd_skills``. Promoted to Tier 2 below.
    "search": "Search past conversations for: {args}. Use the search results below to answer.",
    "tmux": (
        "The operator wants to spawn a background agent via tmux. Their request: {args}\n\n"
        "Instructions:\n"
        "1. Take the operator's description and expand it into a clear, self-contained task prompt. "
        "The spawned agent has NO context from this conversation — be specific about file paths, scope, and expected output format.\n"
        "2. Run: bash scripts/tmux-agent.sh spawn \"<your expanded task prompt>\"\n"
        "3. Report the agent ID and a one-line summary. Mention they can check with /agents or kill with /kill-agent <id>.\n\n"
        "If the operator's request is vague, make reasonable assumptions and state them. "
        "Do NOT run the task yourself — ALWAYS spawn it via tmux-agent.sh."
    ),
}

# #1071 Part 2 — three-tier classification of the operator slash-command
# surface. Tier 1 + Tier 2 are always live; Tier 3 entries register only
# when the operator opts in via [commands] in bridge.toml. Per-department
# names registered dynamically by ``CommandHandler._register_department_commands``
# (Part 1) are added on top.

# Tier 1 — operator essentials (always visible)
_TIER_1_ESSENTIAL: frozenset[str] = frozenset({
    "ping", "status", "uptime", "queue", "health",
    "halt", "resume", "cancel", "reset", "restart",
    "log", "cost", "mcp", "memory_writes", "writes",
})

# Tier 2 — Z4 operational surface (always visible). Per-department
# commands (strategy, design, qa, ops, outreach, job_search, board)
# are added dynamically when the DepartmentRegistry is wired.
_TIER_2_Z4: frozenset[str] = frozenset({
    "board",
    # Board Phase 2 WS4 (#2391) — recent board-run history with phase,
    # member count, cost. Normalizes from /board-history.
    "board_history",
    "directives", "direct", "surfaces", "ack", "z4_tasks",
    "z4_status", "z4_cost", "z4_metrics",
    "departments", "handoff", "route",
    # RR.4 (#2593) — self-serve roster registry. Register/unregister a
    # runtime specialist into a department roster (no YAML edit / redeploy)
    # and list the overlay. Operational Z4 surface (behind operator auth).
    "register_specialist", "unregister_specialist", "roster",
    # WS2.6 (#2570) — list resumable run checkpoints. The companion
    # `/resume <run_id>` re-dispatch verb is folded into the existing
    # Tier-1 `resume` command (no-arg halt-clear preserved).
    "checkpoints",
    # D5.8 — structured funnel-failure aggregator (per-board/ATS/step report)
    "funnel",
    # Z4-S13 (#1388) — chief-session inspection (list active / detail by sid)
    "chief_sessions",
    # Sprint 4.04 / #2151 — per-agent skill-allocator discovery.
    # Promoted from Tier 3 because operator discovery ("what skills
    # does this agent have?") is a Tier-2 operational need now that
    # default-deny allocation means the answer is no longer obvious
    # from the skill-directory listing.
    "skills",
})

# Tier 2 — Zone 3 shortcuts that should also be always visible.
# These are NOT DepartmentRegistry teams; they route through Zone 3 surfaces.
_TIER_2_Z3: frozenset[str] = frozenset({
    "engineering",
})

_TIER_2_ALWAYS: frozenset[str] = _TIER_2_Z4 | _TIER_2_Z3

# Tier 3 — power-user / scaffolded surface (default off, opt-in via
# `[commands]` table in bridge.toml). The handler still exists on the
# class; only registration into BRIDGE_COMMANDS is gated. When a Tier 3
# command is invoked while disabled, ``handle()`` returns a friendly
# "not enabled" hint rather than the generic "Unknown command".
_TIER_3_POWER_USER: frozenset[str] = frozenset({
    # Multi-agent + lifecycle
    "spawn", "agents", "kill_agent",
    # Autonomy + governance
    # NOTE: ``skills`` promoted to Tier 2 in Sprint 4.04 / #2151
    # (per-agent allocator discovery is now an operational need).
    "digest", "proposals", "failures",
    "edits", "approve", "reject",
    "knowledge", "trace", "events", "escalation", "trust",
    "routing", "reflect", "fewshot", "services", "diagnose",
    # Session hooks
    "careful", "freeze", "relax", "hooks", "verify",
    # Audit / housekeeping
    "redundancy", "deprecation_report", "drift", "determinism", "features",
    "skill_audit", "resources",
    # Sprint 02.04 (#978) — append-only audit-branch trail listing.
    "experiment_branches",
    # Voice / proactive
    "tts", "voice", "proactive",
    # Project + workflow
    "project", "projects", "dispatch", "workflows",
    # Misc Z3/Z4 inspection
    "z3_status", "primer", "job_status", "job_funnel",
    # Job-search rubric evidence harness (Sprint 06.08)
    "rubric_evidence",
    # Dark Factory soak harness (Sprint 14.11) — production-enable gate
    "soak_status", "soak_verify",
    # Sprint 02.08 / spec ref-audit-02-08 (issue #983) — finalize-experiments
    # grouping pass. Tier 3 because the harness shells out to ``git
    # cherry-pick`` and creates branches; we do not want it on by default.
    "experiment_finalize", "experiment_finalize_status",
    # Dark Factory operator commands (Sprint 14.11 — issue #1049).
    # Subcommands: status / pause / resume / escalate. Tier 3 because
    # the orchestrator itself is feature-flagged; we don't want this
    # in the always-live surface until the operator opts in.
    "factory",
    # Goal / task management (legacy generic; not Phase 5 z4_tasks)
    "goals", "tasks",
    # Sprint 05.10 — second-brain operator UX (#1020). Gated at the
    # handler level by ``second_brain_enabled`` on the live config; the
    # Tier 3 registration here just exposes them when the operator opts
    # in via ``[commands]``.
    "wiki", "promote", "reject_wiki",
    # Sprint 05.11 — 14-day shadow + auto-routing decision report (#1021).
    # Same gating shape: handler-level check on
    # ``second_brain_shadow_router_enabled`` returns a helpful message
    # when the harness is off; Tier 3 registration only exposes the
    # command when the operator opts in via ``[commands]``.
    "shadow_report",
    # Sprint D2.1 (#1186) — fan-out memory recall across 9 stores.
    # Implemented but omitted from tier list; added by D7.4 health pass.
    "recall", "find",
    # D7.8 (#1420) — operator-visible signal for compaction events.
    "compact_status",
    # zone4-warmth.D.02 (#2300) — warm-session population summary.
    # Tier 3 because the underlying REST endpoint already exposes the
    # same data and this is a power-user observability shortcut.
    "warmth_stats",
})

# Mutable runtime view: starts as Tier 1 ∪ Tier 2; Tier 3 entries are
# added by ``apply_command_tier_gating``; per-department names are added
# by ``CommandHandler._register_department_commands``.
BRIDGE_COMMANDS: set[str] = set(_TIER_1_ESSENTIAL) | set(_TIER_2_ALWAYS)
AGENT_COMMANDS = set(_AGENT_COMMANDS.keys())


def load_commands_section(toml_path: str | Path) -> dict:
    """Read the ``[commands]`` table from ``bridge.toml``, if present.

    Returns ``{}`` when the file is missing, the section is missing, or
    the section is malformed. Errors are non-fatal — a missing section
    means "Tier 3 stays off", which is the correct default.
    """
    try:
        with open(toml_path, "rb") as f:
            data = tomllib.load(f)
    except FileNotFoundError:
        return {}
    except (tomllib.TOMLDecodeError, OSError) as e:
        logger.warning("Could not read [commands] from %s: %s", toml_path, e)
        return {}
    section = data.get("commands")
    if not isinstance(section, dict):
        return {}
    return section


def apply_command_tier_gating(commands_section: dict | None) -> None:
    """Reconcile ``BRIDGE_COMMANDS`` with the ``[commands]`` toml table.

    The table is a flat ``name = bool`` mapping with an optional
    ``all = true`` shortcut to enable every Tier 3 command. Unknown
    keys are ignored. Tier 1 + Tier 2 are immutable and always present.

    Called once at bridge startup from BridgeApp after config is loaded.
    Idempotent — safe to call multiple times.
    """
    BRIDGE_COMMANDS.clear()
    BRIDGE_COMMANDS.update(_TIER_1_ESSENTIAL)
    BRIDGE_COMMANDS.update(_TIER_2_ALWAYS)

    if not commands_section:
        return

    if commands_section.get("all") is True:
        BRIDGE_COMMANDS.update(_TIER_3_POWER_USER)
        return

    for name, enabled in commands_section.items():
        if name == "all" or not isinstance(name, str):
            continue
        if not enabled:
            continue
        if name in _TIER_3_POWER_USER:
            BRIDGE_COMMANDS.add(name)
        # Unknown / non-Tier-3 keys silently ignored — config drift is
        # not fatal, and Tier 1/2 are already on.


class CommandHandler(
    LifecycleMixin,
    JobsAndFactoryMixin,
    CostAndZ4Mixin,
    BoardAndVoiceMixin,
    AgentsAndMemoryMixin,
    DepartmentsMixin,
    SkillsAndHooksMixin,
    WikiMixin,
):
    """Routes and handles all operator commands."""

    def __init__(
        self,
        db: Database,
        queue: MessageQueue,
        session_manager: SessionManager,
        claude_runner: ClaudeRunner | None = None,
    ) -> None:
        self._db = db
        self._queue = queue
        self._session_mgr = session_manager
        self._claude_runner = claude_runner
        self._start_time = time.monotonic()
        self._halted = False
        self._message_count = 0
        self._error_count = 0
        self._rate_limit_count = 0
        self._shutdown_callback: Callable[[], None] | None = None
        self._autonomy = None  # AutonomyLayer | None
        self._tmux_agents = None  # TmuxAgentManager | None
        self._few_shot_store = None  # FewShotStore | None
        self._self_edit = None  # SelfEditMemory | None
        self._temporal_kb = None  # TemporalKnowledgeStore | None
        self._tracer = None  # Tracer | None
        self._cost_tracker = None  # CostTracker | None
        self._routing_feedback = None  # RoutingFeedbackEngine | None
        self._reflection_store = None  # ReflectionStore | None
        self._mcp_monitor = None  # MCPMonitor | None
        self._skill_evolution = None  # SkillEvolutionEngine | None
        self._agent_router = None  # AgentRouter | None
        self._runbook_engine = None  # RunbookEngine | None
        self._warm_claude = None  # WarmClaudeProcess | None
        self._log_dir: Path | None = None
        self._session_hooks = None  # SessionHookRegistry | None
        self._session_hook_registry = None  # alias for _session_hooks
        self._self_verifier = None  # SelfVerifier | None
        self._metrics = None  # MetricsCollector | None
        self._daily_log = None  # DailyLogWriter | None
        self._tick_manager = None  # TickManager | None
        self._proactive_scheduler = None  # ProactiveScheduler | None  # D7.12 #1424
        self._webhook_deliverer = None  # SerialEventDeliverer | None
        self._project_registry = None  # ProjectRegistry | None
        self._departments = None  # DepartmentRegistry | None (Zone 4)
        self._circuit_registry = None  # CircuitBreakerRegistry | None (Zone 4)
        self._dispatcher = None  # Dispatcher | None (Zone 3)
        self._routing_brain = None  # ModelRouter-compatible | None (Zone 3)
        self._cost_attributor = None  # CostAttributor | None (Zone 4)
        self._metrics_aggregator = None  # MetricsAggregator | None (Zone 4)
        self._memory = None  # Memory | None (Zone 4 handoff)
        self._workflow_registry = None  # WorkflowRegistry | None (Zone 4 Layer 2)
        self._workflow_engine = None  # WorkflowEngine | None (Zone 4 Layer 2)
        self._security = None  # SecurityManager | None (Sprint 06.03)
        self._wiki_repo = None  # WikiRepo | None (Sprint 05.10 second-brain)
        self._shadow_router = None  # ShadowRouter | None (Sprint 05.11 #1021)
        self._chief_session_store = None  # ChiefSessionStore | None (Z4-S13 #1388)
        self._roster_registry = None  # RosterRegistryStore | None (RR.4 #2593)
        # Sprint 04.09/04.10/04.11: hold a reference to the live BridgeApp so
        # _cmd_board / _cmd_route / _cmd_handoff can construct BridgeDeps via
        # the BridgeDeps.from_app(...) factory instead of hand-assembling every
        # field. set_app() is the canonical wiring point; it is invoked by the
        # WIRING_MANIFEST in BridgeApp._wire().
        self._app = None  # BridgeApp | None (Sprint 04.09-04.11)
        # Sprint 1112.1.02 (#2139) — pending cross-harness handoff drafts,
        # keyed by chat_id. Populated by ``/handoff <to-harness> <topic>``
        # composition; consumed by the fire path that lands in Sprint 1.04
        # (#2141) when the operator replies ``go``/``edit``/``abort``.
        # Type: dict[str, tuple[HandoffDraft, str]] where the second tuple
        # element is the durable gist URL for the conversation transcript.
        self._pending_handoffs: dict = {}

    def set_app(self, app) -> None:
        """Set the live BridgeApp reference for BridgeDeps.from_app() factory.

        Wired by BridgeApp._wire() so that command handlers constructing
        BridgeDeps for Zone 4 routing pull the same field set as every other
        production caller — keeping new fields (e.g. sessions_dir from
        Sprint 04.08) from silently underfilling.
        """
        self._app = app

    def set_security(self, security) -> None:
        """Set the SecurityManager for halt-flag disk persistence."""
        self._security = security

    def set_project_registry(self, registry) -> None:
        """Set the ProjectRegistry for /project and /projects commands."""
        self._project_registry = registry

    def set_departments(self, registry) -> None:
        """Set the DepartmentRegistry for Zone 4 department-aware routing.

        Also registers per-department slash commands (#1071 Part 1) so the
        operator can type ``/strategy <task>`` instead of ``/route strategy
        <task>``. Adding ``--directive`` upgrades the dispatch to a Phase 5
        Directive (current ``/direct <chief> <intent>`` semantics).
        """
        self._departments = registry
        self._register_department_commands()

    def _register_department_commands(self) -> None:
        """Wire per-department slash commands from the live DepartmentRegistry.

        Iterates ``DepartmentRegistry.department_names()`` and binds an
        instance attribute ``_cmd_<dept>`` for each — so changing the set
        of departments in YAML stays a config-only change. Departments
        that already have a hand-written ``_cmd_<name>`` on the class
        (notably ``board`` for multi-perspective deliberation) are skipped
        — we do not clobber existing behaviour.
        """
        if self._departments is None:
            return
        for dept in self._departments.department_names():
            method_name = f"_cmd_{dept}"
            # Skip if a class-level handler already exists (e.g. _cmd_board)
            if getattr(type(self), method_name, None) is not None:
                BRIDGE_COMMANDS.add(dept)
                continue
            setattr(self, method_name, self._make_department_handler(dept))
            BRIDGE_COMMANDS.add(dept)

    def _make_department_handler(self, department: str):
        """Build a closure that dispatches to one department.

        Without ``--directive`` the closure mimics ``/route <dept> <task>``
        (fire-and-route). With ``--directive`` (anywhere in args), it
        mimics ``/direct <dept> <intent>`` — issuing a Phase 5 Directive
        and propagating its lifecycle.
        """
        async def _handler(chat_id: str, args: str) -> str:
            stripped = args.strip()
            if not stripped:
                return (
                    f"Usage: /{department} <task>  "
                    f"(append --directive to issue a Phase 5 Directive)"
                )
            tokens = stripped.split()
            if "--directive" in tokens:
                tokens = [t for t in tokens if t != "--directive"]
                if not tokens:
                    return (
                        f"Usage: /{department} --directive <intent>"
                    )
                rebuilt = f"{department} {' '.join(tokens)}"
                return await self._cmd_direct(chat_id, rebuilt)
            rebuilt = f"{department} {stripped}"
            return await self._cmd_route(chat_id, rebuilt)

        _handler.__name__ = f"_cmd_{department}"
        return _handler

    async def _cmd_engineering(self, chat_id: str, args: str) -> str:
        """Shortcut for Zone 3 engineering work via the dispatcher.

        Readiness asks ("ready to work?", "roster", "status") short-circuit to
        a deterministic Zone 3 roster with zero Claude subprocess spawn (Z3-03).
        Substantive tasks route through the **Zone 3 ``EngineeringDispatcher``**
        (#2437): it selects a specialist, assembles the governance-aware prompt,
        and drives the ``claude -p`` executor — this is the path that makes the
        dojo operable. If the dispatcher cannot be constructed (config or binary
        unavailable) the handler falls back to the generic WorkOrder/SUBAGENT
        dispatcher. Engineering never touches the Zone 4 PydanticAI
        DepartmentRegistry.
        """
        task = args.strip()
        if not task:
            return "Usage: /engineering <task>"

        # Z3-03: deterministic readiness path — no Claude, no executor.
        try:
            from zone3.engineering_config import load_engineering_team_config
            from zone3.engineering_dispatcher import (
                classify_cross_zone_handoff,
                is_engineering_readiness_prompt,
                render_cross_zone_handoff,
                render_engineering_readiness,
            )

            if is_engineering_readiness_prompt(task):
                return render_engineering_readiness(load_engineering_team_config())
            handoff = classify_cross_zone_handoff(task)
            if handoff is not None:
                return render_cross_zone_handoff(handoff)
        except Exception:  # pragma: no cover - config/import issues fall through
            pass

        # #2437: substantive tasks go through the operable Zone 3 dojo path —
        # EngineeringDispatcher.route() -> claude_p executor. Graceful fallback
        # to the legacy WorkOrder path if the dispatcher can't be built.
        eng_dispatcher = self._build_engineering_dispatcher()
        if eng_dispatcher is not None:
            try:
                from pathlib import Path

                cwd = Path(self._engineering_cwd())
                result = await eng_dispatcher.route(task, cwd=cwd)
            except Exception as e:
                return f"Engineering dispatch error: {e}"
            if result.success:
                return result.stdout or "Engineering dispatch complete."
            detail = result.stderr.strip() or result.error_class or "unknown error"
            return f"Engineering dispatch failed ({detail})."

        dispatcher = getattr(self, "_dispatcher", None)
        if dispatcher is None:
            return await self._cmd_dispatch(chat_id, task)

        from . import model_defaults  # P0.01 canonical default-model constants
        from .work_order import (
            Environment,
            WorkOrder,
            WorkOrderAssignment,
            WorkOrderStatus,
        )

        wo = WorkOrder.create(
            intent=task,
            skill="engineering",
            project="operator",
        )
        wo = wo.with_environment(
            Environment.SUBAGENT,
            "Explicit /engineering command routes to Zone 3 engineering chief.",
        )
        wo = wo.with_assignment(
            WorkOrderAssignment(
                agent_type="engineering",
                agent_id="engineering-chief",
                # Sourced from canonical constant (P0.01); the /engineering
                # route now uses the canonical paid default.
                model=model_defaults.DEFAULT_PAID_MODEL,
            )
        )
        wo = wo.transition(WorkOrderStatus.ASSIGNED)

        try:
            result = await dispatcher.dispatch(wo)
        except Exception as e:
            return f"Engineering dispatch error: {e}"

        if not result.valid:
            return f"Engineering dispatch rejected: {result.reason}"
        if not result.handled:
            return f"Engineering dispatch did not complete: {result.reason}"

        response = ""
        if result.result is not None:
            response = getattr(result.result, "response_text", "") or ""
        return response or "Engineering dispatch complete."

    def _engineering_cwd(self) -> str:
        """Resolve the working directory for Zone 3 engineering runs.

        Prefers the live ClaudeRunner's configured ``claude_working_dir`` (the
        runtime tree the bridge executes from); falls back to the process cwd
        when no runner is wired (e.g. unit-test contexts).
        """
        runner = getattr(self, "_claude_runner", None)
        config = getattr(runner, "config", None)
        working_dir = getattr(config, "claude_working_dir", None)
        if working_dir:
            return str(working_dir)
        import os

        return os.getcwd()

    def _build_engineering_dispatcher(self):
        """Construct an operable Zone 3 EngineeringDispatcher, or None.

        Returns ``None`` (signalling a graceful fallback to the legacy
        WorkOrder path) when the engineering config cannot load or the Zone 3
        modules are unavailable. The executor's ``claude`` binary is resolved
        from the live ClaudeRunner config when present, else left to the
        executor's PATH lookup. The construction is intentionally dependency-
        light: ``EngineeringDispatcher.route()`` needs only a parsed config and
        an ``_ExecutorLike`` — no app-level wiring — so it is built on demand
        here rather than via a setter/WIRING_MANIFEST entry.
        """
        try:
            from zone3.claude_p_executor import ClaudePExecutor
            from zone3.engineering_config import load_engineering_team_config
            from zone3.engineering_dispatcher import EngineeringDispatcher
        except Exception:  # pragma: no cover - import guard
            return None

        try:
            config = load_engineering_team_config()
        except Exception:
            return None

        runner = getattr(self, "_claude_runner", None)
        runner_config = getattr(runner, "config", None)
        claude_binary = getattr(runner_config, "claude_binary", None) or "claude"

        executor = ClaudePExecutor(claude_binary=claude_binary)
        return EngineeringDispatcher(config=config, executor=executor)

    def set_circuit_registry(self, registry) -> None:
        """Set the CircuitBreakerRegistry for department circuit state display."""
        self._circuit_registry = registry

    def set_dispatcher(self, dispatcher) -> None:
        """Set the Dispatcher for /dispatch command (Zone 3)."""
        self._dispatcher = dispatcher

    def set_routing_brain(self, brain) -> None:
        """Set the routing brain (ModelRouter-compatible) for /dispatch command."""
        self._routing_brain = brain

    def set_cost_attributor(self, attributor) -> None:
        """Set the CostAttributor for /z4-cost command (Zone 4)."""
        self._cost_attributor = attributor

    def set_metrics_aggregator(self, aggregator) -> None:
        """Set the MetricsAggregator for /z4-metrics command (Zone 4)."""
        self._metrics_aggregator = aggregator

    def set_memory(self, memory) -> None:
        """Set the Memory instance for Zone 4 BridgeDeps injection."""
        self._memory = memory

    def set_workflow_registry(self, registry) -> None:
        """Set the WorkflowRegistry for /workflows command (Zone 4 Layer 2)."""
        self._workflow_registry = registry

    def set_workflow_engine(self, engine) -> None:
        """Set the WorkflowEngine for /workflows trigger|cancel (Zone 4 Layer 2)."""
        self._workflow_engine = engine

    def set_daily_log(self, writer) -> None:
        """Set the DailyLogWriter for /log command."""
        self._daily_log = writer

    def set_tick_manager(self, manager) -> None:
        """Set the TickManager for /proactive command."""
        self._tick_manager = manager

    def set_proactive_scheduler(self, scheduler) -> None:
        """Set the ProactiveScheduler (D7.12 #1424) so /proactive status
        can surface the last-7-days activity ledger.

        Optional — when None, /proactive status falls back to the legacy
        TickManager-only output.
        """
        self._proactive_scheduler = scheduler

    def set_autonomy(self, autonomy) -> None:
        """Set the AutonomyLayer for /trust, /escalation, /events, /digest commands."""
        self._autonomy = autonomy

    def set_tmux_agents(self, mgr) -> None:
        """Set the TmuxAgentManager for /spawn, /agents, /kill-agent commands."""
        self._tmux_agents = mgr

    def set_few_shot_store(self, store) -> None:
        self._few_shot_store = store

    def set_self_edit(self, sem) -> None:
        self._self_edit = sem

    def set_temporal_kb(self, store) -> None:
        self._temporal_kb = store

    def set_warm_claude(self, warm) -> None:
        self._warm_claude = warm

    def set_tracer(self, tracer) -> None:
        self._tracer = tracer

    def set_cost_tracker(self, tracker) -> None:
        self._cost_tracker = tracker

    def set_routing_feedback(self, engine) -> None:
        self._routing_feedback = engine

    def set_reflection_store(self, store) -> None:
        self._reflection_store = store

    def set_mcp_monitor(self, monitor) -> None:
        self._mcp_monitor = monitor

    def set_skill_evolution(self, engine) -> None:
        self._skill_evolution = engine

    def set_agent_router(self, router) -> None:
        self._agent_router = router

    def set_log_dir(self, log_dir) -> None:
        self._log_dir = log_dir

    def set_runbook_engine(self, engine) -> None:
        self._runbook_engine = engine

    def set_webhook_deliverer(self, deliverer) -> None:
        """Set the SerialEventDeliverer for /webhooks command."""
        self._webhook_deliverer = deliverer

    def set_session_hooks(self, registry) -> None:
        """Set the SessionHookRegistry for /careful, /freeze, /relax, /hooks commands."""
        self._session_hooks = registry
        self._session_hook_registry = registry

    def set_session_hook_registry(self, registry) -> None:
        """Alias for set_session_hooks — used by tests and app wiring."""
        self._session_hooks = registry
        self._session_hook_registry = registry

    def set_self_verifier(self, verifier) -> None:
        """Set the SelfVerifier for /verify command."""
        self._self_verifier = verifier

    def set_wiki_repo(self, wiki_repo) -> None:
        """Set the WikiRepo for /wiki, /promote, /reject_wiki commands.

        Sprint 05.10 (#1020). When ``second_brain_enabled`` is False or
        the WikiRepo is otherwise unwired, the three commands return a
        helpful "second-brain not enabled" string instead of touching
        the vault.
        """
        self._wiki_repo = wiki_repo

    def set_shadow_router(self, shadow_router) -> None:
        """Set the ShadowRouter for /shadow_report + correlation hooks.

        Sprint 05.11 (#1021). When the shadow harness is disabled or
        unwired, ``/shadow_report`` returns a helpful "not enabled"
        message and ``/promote`` / ``/reject_wiki`` skip correlation
        silently (correlation is best-effort and never blocks the
        primary command).
        """
        self._shadow_router = shadow_router

    def set_chief_session_store(self, store) -> None:
        """Set the ChiefSessionStore for the /chief_sessions command.

        Z4-S13 (#1388). When unwired, /chief_sessions returns a friendly
        "store not initialized" message instead of raising. The wiring
        of the store INTO BridgeApp lives in Z4-S22 (#1395 — app.py
        wiring); this setter is the seam that sprint will call.
        """
        self._chief_session_store = store

    def set_roster_registry(self, store) -> None:
        """Set the RosterRegistryStore for the roster operator commands.

        RR.4 (#2593). When unwired, ``/register-specialist`` /
        ``/unregister-specialist`` / ``/roster`` return a friendly
        "not wired" message instead of raising. The store is the same
        instance the REST surface (RR.3) reaches via ``_roster_registry``
        on the bridge; app-boot wiring lands in a later sprint.
        """
        self._roster_registry = store

    def set_shutdown_callback(self, callback: Callable[[], None]) -> None:
        """Set callback for graceful shutdown (called by /restart)."""
        self._shutdown_callback = callback

    # -- Public API --

    async def handle(self, chat_id: str, command: str, args: str) -> str | None:
        """Route a command to its handler. Returns response text."""
        command = command.lower().strip()
        # Normalize hyphens to underscores for method lookup (e.g. kill-agent → kill_agent)
        normalized = command.replace("-", "_")

        if normalized in BRIDGE_COMMANDS:
            handler = getattr(self, f"_cmd_{normalized}", None)
            if handler:
                return await handler(chat_id, args)

        if command in AGENT_COMMANDS:
            return self.get_agent_prompt(command, args)

        # #1071 Part 2 — friendly hint for known-but-disabled Tier 3 commands.
        if normalized in _TIER_3_POWER_USER:
            return (
                f"/{command} is a power-user command and is disabled by default. "
                f"Enable it in `bridge.toml` under `[commands]`:\n"
                f"```toml\n[commands]\n{normalized} = true\n```\n"
                f"Or set `[commands].all = true` to enable every Tier 3 command."
            )

        return f"Unknown command: /{command}"

    def is_halted(self) -> bool:
        """Check if the agent is halted."""
        return self._halted

    def record_message(self) -> None:
        """Record a processed message for stats."""
        self._message_count += 1

    def record_error(self) -> None:
        """Record an error for stats."""
        self._error_count += 1

    def record_rate_limit(self) -> None:
        """Record a rate limit hit for stats."""
        self._rate_limit_count += 1

    # -- Bridge commands --

    # -- Agent command routing --

    @staticmethod
    def get_agent_prompt(command: str, args: str) -> str | None:
        """Map agent command to Claude prompt string."""
        template = _AGENT_COMMANDS.get(command)
        if not template:
            return None
        prompt = template.format(args=args or "all")
        return f"{_AGENT_PREFIX}\n\n{prompt}"

    # -- Helpers --

    def _format_uptime(self) -> str:
        """Format uptime as 'Xh Ym'."""
        elapsed = int(time.monotonic() - self._start_time)
        hours, remainder = divmod(elapsed, 3600)
        minutes = remainder // 60
        return f"{hours}h {minutes}m"

    def _z4_session_output_footer(self, deps: object, department: str) -> str:
        """Return a short operator hint for persisted Z4 session output."""
        sessions_dir = getattr(deps, "sessions_dir", None)
        session_id = str(getattr(deps, "session_id", "") or "")
        if sessions_dir is None or not session_id:
            return ""

        department_slug = str(department)
        conversation_path = (
            Path(sessions_dir)
            / session_id
            / department_slug
            / "conversation.jsonl"
        )
        api_path = (
            "/api/z4/sessions/"
            f"{quote(session_id, safe='')}/departments/"
            f"{quote(department_slug, safe='')}/conversation"
        )
        return (
            "\n\n"
            f"Session transcript: `{conversation_path}`\n"
            f"API: `{api_path}`"
        )
