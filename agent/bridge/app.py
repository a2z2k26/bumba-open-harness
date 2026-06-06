"""BridgeApp: wires all components, startup/shutdown, message processing, error handling."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import re as _re
import signal
import time
from dataclasses import dataclass
from pathlib import Path

from .autonomy import AutonomyLayer
from .budget import BudgetGuard
from .circuit_breaker import CircuitBreakerRegistry, CircuitBreakerConfig, State as CircuitState  # noqa: F401
from .claude_runner import ClaudeRunner, ClaudeResult, WarmClaudeProcess
# Sprint P6.1 (#1591): classify / strip_model_override / CAREFUL_OPUS_MODEL
# moved to bridge/invocation_pipeline.py with the extracted body.
from .commands import (
    CommandHandler,
    BRIDGE_COMMANDS,
    AGENT_COMMANDS,
    apply_command_tier_gating,  # noqa: F401
    load_commands_section,  # noqa: F401
)
from .config import (
    BridgeConfig,
    _requires_claude_oauth,
    _requires_openrouter_api_key,
)  # noqa: F401
from .wiring import (
    WiringEntry,
    WiringReport,
    apply_wiring_manifest,
    log_wiring_report,
)
from .database import Database
from .daily_log import DailyLogWriter
from .fallback import FallbackChain
from .tick_manager import TickManager  # noqa: F401
from .hooks import SessionHookRegistry
from .lifecycle import SubprocessLifecycle, State as LifecycleState
from .memory import Memory
from .message_queue import MessageQueue, QueuedMessage
from . import model_defaults  # P0.04 canonical default-model constants
from .rate_limiter import TokenBucket
from .security import SecurityManager
from .session_manager import SessionManager


# ─────────────────────────────────────────────────────────────────────
# #488 primer_writer adapters — tiny shims so BridgeApp state surfaces
# through the BridgeDeps-shaped interface write_primer expects.
# ─────────────────────────────────────────────────────────────────────

class _EmptyBackend:
    def list_active(self, *a, **kw): return []
    def recent_decisions(self, *a, **kw): return []
    def pending(self, *a, **kw): return []
    def pending_tasks(self, *a, **kw): return []


class _ProjectRegistryAdapter:
    """Wraps ProjectRegistry to expose list_active() for primer_writer."""
    def __init__(self, registry):
        self._registry = registry

    def list_active(self):
        try:
            all_projects = self._registry.list_all() or []
        except Exception:
            return []
        active = []
        for p in all_projects:
            if p.get("status") == "active":
                active.append({
                    "name": p.get("name", "unknown"),
                    "status": p.get("status", "active"),
                    "current_phase": p.get("current_phase") or p.get("phase"),
                    "next_action": p.get("next_action"),
                    "github_branch": p.get("github_branch"),
                    "type": p.get("type", "product"),
                })
        return active


class _MemoryAdapter:
    """Wraps Memory to expose recent_decisions()."""
    def __init__(self, memory):
        self._memory = memory

    def recent_decisions(self, limit: int = 10):
        try:
            if hasattr(self._memory, "recent_decisions"):
                return self._memory.recent_decisions(limit=limit) or []
        except Exception as exc:
            logger.warning("memory adapter recent_decisions failed: %s", exc)
        return []


class _TaskQueueAdapter:
    def __init__(self, tq):
        self._tq = tq

    def pending(self, limit: int = 10):
        try:
            if hasattr(self._tq, "list_pending"):
                return self._tq.list_pending(limit=limit) or []
            if hasattr(self._tq, "pending"):
                return self._tq.pending(limit=limit) or []
        except Exception as exc:
            logger.warning("task queue adapter pending() failed: %s", exc)
        return []


class _ClaudeRunnerAdapter:
    """Adapts ClaudeRunner to the shape primer_writer expects.

    ClaudeRunner.invoke returns a ClaudeResult dataclass with .response_text
    and .cost_usd. We normalize to a dict for the primer_writer interface.

    Always passes session_id=None to force a fresh one-shot (no --resume),
    since we want a clean synthesis call, not a continuation of prior state.
    """
    def __init__(self, runner):
        self._runner = runner

    async def invoke(self, *, prompt: str, model: str, session_id: str, max_turns: int = 1):
        # ClaudeRunner.invoke takes `message` (positional or first kwarg) and `model`.
        # session_id=None means "fresh session" — we don't want to resume prior primer calls.
        result = await self._runner.invoke(message=prompt, session_id=None, model=model)
        return {
            "response_text": getattr(result, "response_text", "") or "",
            "cost_usd": float(getattr(result, "cost_usd", 0.0) or 0.0),
            "is_error": bool(getattr(result, "is_error", False)),
        }
from .tag_parser import parse_tags, strip_tags
from .task_queue import TaskQueue, detect_question_with_options
from .discord_bot import DiscordBot
from .stream_coalescer import StreamCoalescer  # noqa: F401
from .health import HealthServer
from .heartbeat import HeartbeatPinger
from .metrics import MetricsCollector
from .token_refresher import TokenRefresher
from .few_shot import FewShotStore, FewShotExample, classify_task_type
from .self_edit_memory import SelfEditMemory, EditRequest
from .temporal_knowledge import TemporalKnowledgeStore
from .tracing import Tracer, record_completed_span  # noqa: F401
from .cost_tracker import CostTracker
from .routing_feedback import RoutingFeedbackEngine
from .self_healing import force_token_refresh, SessionRecoveryManager  # invoke_with_retry → invocation_pipeline (P6.1)
from .reflection import ReflectionStore, ReflexionContext
from .mcp_monitor import MCPMonitor
from .skill_evolution import SkillEvolutionEngine
from .skill_allocator import SkillAllocator
from .project_registry import ProjectRegistry
from .response_evaluator import ResponseEvaluator
from .self_verifier import SelfVerifier  # noqa: F401
from . import background_loops
from . import log_format
from .error_handler import handle_processing_error
from .diagnosis import RunbookEngine
from .agent_router import AgentRouter

# Zone 4 teams package (optional, bridge-independent)
try:
    from teams._registry import DepartmentRegistry  # noqa: F401
    _TEAMS_AVAILABLE = True
except ImportError:
    _TEAMS_AVAILABLE = False

try:
    from bridge.observability.tool_tracker import ToolTracker  # noqa: F401
    from bridge.observability.cost import CostAttributor  # noqa: F401
    from bridge.observability.metrics_aggregator import MetricsAggregator  # noqa: F401
    from bridge.observability.api_routes import Zone4Routes
    _TOOL_TRACKER_AVAILABLE = True
except ImportError:
    _TOOL_TRACKER_AVAILABLE = False
from .local_embeddings import LocalEmbeddingEngine
from .hybrid_search import HybridSearch
# Sprint P6.1 (#1591): _classify_message_intent and _load_modality_for_intent
# moved to bridge/invocation_pipeline.py with the extracted body.
from .api_server import APIServer

try:
    from teams._providers import load_provider_keys as _load_provider_keys  # noqa: F401
    _PROVIDERS_AVAILABLE = True
except ImportError:
    _PROVIDERS_AVAILABLE = False

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Skill derivation for WorkOrder construction (#629).
# Maps intent enum values to skill strings for EnvironmentSelector.
# ---------------------------------------------------------------------------
_INTENT_SKILL_MAP = {
    "build": "implement",
    "fix": "fix-task",
    "optimize": "refactor",
    "migrate": "migrate",
    "deploy": "implement",
    "test": "analyze",
    "analyze": "analyze",
    "document": "explain",
    # Sprint 04.01 — Board (Zone 4) single-skill end-to-end. The "board-query"
    # skill string passes EnvironmentSelector._SKILL_CLASS_RULES "board"
    # prefix → task class "department" → Environment.DEPARTMENT, then
    # _derive_department("board-query") returns "board" so the dispatcher
    # plumbs department_target="board" through to DepartmentExecutor.
    "board_query": "board-query",
    # Sprint 04.02 — broaden classifier to the 4 remaining departments.
    # Each skill string is constructed so EnvironmentSelector classifies
    # it via _SKILL_CLASS_RULES into "department" task class:
    #   "qa-review"        matches "qa-"      → department_target="qa"
    #   "ops-diagnose"     matches "ops-"     → department_target="ops"
    #   "strategy-analyze" matches "strategy" → department_target="strategy"
    #   "design-review"    matches "design"   → department_target="design"
    # Note: "strategy-analyze" contains the substring "analyze" (a
    # readonly pattern) and "design-review" contains "review", but
    # _SKILL_CLASS_RULES is iterated in declaration order with first-match
    # wins — the department prefixes are listed BEFORE the readonly
    # prefixes in environment_selector.py, so classification stays
    # "department" for both.
    "qa_review": "qa-review",
    "ops_diagnose": "ops-diagnose",
    "strategy_analyze": "strategy-analyze",
    "design_review": "design-review",
    "unknown": "chat",
}


def _intent_to_skill(intent_value):
    """Return skill string for an intent value (falls back to 'chat')."""
    return _INTENT_SKILL_MAP.get(intent_value, "chat")


# Maps Intent enum values to Modality enum values for preamble injection.
# Engineering-class intents (build/analyze/fix/optimize/test/deploy/document)
# receive the "engineer" modality supplement.  Department-routing intents
# map to the owning department's modality.  Unknown / chat intents map to None
# (no preamble injected).
_INTENT_TO_MODALITY: dict[str, str] = {
    "build": "engineer",
    "analyze": "engineer",
    "fix": "engineer",
    "optimize": "engineer",
    "test": "engineer",
    "deploy": "orchestrator",
    "document": "engineer",
    "board_query": "orchestrator",
    "qa_review": "engineer",
    "ops_diagnose": "orchestrator",
    "strategy_analyze": "pa",
    "design_review": "communicator",
}


def _intent_to_modality_name(intent_value: str | None) -> str | None:
    """Map an intent string to a modality name, or None if no preamble applies."""
    if intent_value is None:
        return None
    return _INTENT_TO_MODALITY.get(intent_value)


@dataclass
class MessageContext:
    """Immutable context object threaded through the message-processing pipeline.

    Created once at the top of ``_process_single_message`` and passed to every
    stage.  Stages return new ``MessageContext`` instances rather than mutating
    this one, keeping each stage independently testable and side-effect-free.
    """

    # Identifiers
    msg: QueuedMessage
    correlation_id: str | None = None

    # Channel routing
    channel: str = "discord"
    reply_channel: str = ""  # defaults to same as channel if empty

    # Timing
    msg_start: float = 0.0

    # Pre-flight results
    claude_breaker: object | None = None  # CircuitBreaker instance, if available

    # Session resolution
    session_id: str = ""
    resume_id: str | None = None

    # Invoke result
    result: object | None = None  # ClaudeResult, populated after _invoke_claude

    # Budget
    budget_pressure: str | None = None

    # Post-processing flags
    hitl_detected: bool = False


def _read_pyproject_version() -> str:
    """Return the project version from ``agent/pyproject.toml``.

    Sprint 07.10 helper — used as the ``default_version`` fallback when
    ``data/version.json`` has not yet been written by a deploy script. Walks
    upward from this file to find ``pyproject.toml`` so it works in both the
    source tree (``agent/bridge/app.py``) and the runtime tree
    (``/opt/bumba-harness/agent/bridge/app.py``). Returns ``"0.0.0"`` if the
    file or the ``[project] version`` field is missing.
    """
    try:
        import tomllib  # stdlib (Python 3.11+)
    except Exception:
        return "0.0.0"
    here = Path(__file__).resolve()
    for parent in (here.parent, *here.parents):
        candidate = parent / "pyproject.toml"
        if candidate.exists():
            try:
                with candidate.open("rb") as f:
                    data = tomllib.load(f)
                project = data.get("project") or {}
                value = project.get("version")
                if isinstance(value, str) and value:
                    return value
            except Exception:
                return "0.0.0"
            break
    return "0.0.0"


def _validate_codex_oauth(config: object) -> None:
    """Refuse to boot when a [backends] role resolves to ``codex`` without OAuth.

    Sprint Codex-4 (issue #1838) — fail-closed validator that mirrors the
    ``allow_remote_bind`` (#1626) and ``vapi_webhook_secret`` (P2.3 #1578)
    precedents from ``APIServer.start``. Lives at module scope so it can be
    tested without constructing a full ``BridgeApp``.

    The Codex backend is wired in via Codex-3's ``[backends]`` registry; its
    fields (``backends_enabled``, ``backends_main``, ``backends_chiefs_default``,
    ``backends_specialists_default``, ``backends_specialists_overrides``) are
    added in a sibling parallel sprint and may not exist on ``config`` when
    this PR lands. Use ``getattr`` with safe defaults so a config that
    predates Codex-3 still boots cleanly (legacy claude-only path preserved).

    Raises:
        RuntimeError: when ``backends_enabled`` is true, any role resolves
            to ``"codex"``, and ``codex_oauth_token`` is empty. The error
            message names both the backend role and the missing secret
            field, plus the exact operator workflow to remediate.
    """
    # Defensive getattr — Codex-3 fields land in a sibling PR; this validator
    # must be a no-op when they're absent so the live Claude-only boot path
    # is unaffected.
    backends_enabled = bool(getattr(config, "backends_enabled", False))
    if not backends_enabled:
        return

    codex_oauth_token = str(getattr(config, "codex_oauth_token", "") or "")
    if codex_oauth_token:
        return

    backends_main = getattr(config, "backends_main", "") or ""
    backends_chiefs_default = getattr(config, "backends_chiefs_default", "") or ""
    backends_specialists_default = (
        getattr(config, "backends_specialists_default", "") or ""
    )
    overrides_raw = getattr(config, "backends_specialists_overrides", None)
    # ``backends_specialists_overrides`` is expected to be a dict[str, str]
    # mapping specialist name -> backend name. Tolerate None or other shapes
    # without crashing the validator — callers will hit the missing-field
    # error first if Codex-3 fields are malformed.
    if isinstance(overrides_raw, dict):
        override_values = tuple(str(v) for v in overrides_raw.values())
    else:
        override_values = ()

    configured_backends = {
        str(backends_main),
        str(backends_chiefs_default),
        str(backends_specialists_default),
        *override_values,
    }
    if "codex" not in configured_backends:
        return

    raise RuntimeError(
        "Bridge refuses to boot: backend 'codex' is configured via "
        "[backends] but codex_oauth_token is missing from .secrets. "
        "Either remove codex from [backends] or run `codex login` on the "
        "Mac mini and copy the token quartet from ~/.codex/auth.json into "
        "/opt/bumba-harness/data/.secrets (chmod 600). Required fields: "
        "codex_oauth_token, codex_oauth_refresh_token, codex_oauth_id_token, "
        "codex_oauth_expires_at. The id_token JWT field (Codex-7-followup, "
        "issue #1872) is required for materializing ~/.codex/auth.json on "
        "rotation; run `python3 -m agent.scripts.seed_codex_secrets` to "
        "emit all four lines from a seeded ~/.codex/auth.json."
    )


def _validate_claude_oauth_required(config: object) -> None:
    """Refuse to boot when active Claude routing lacks an OAuth token.

    Sprint audit-2026-05-16.B.03 (#2052 / HI-5) — sibling fail-closed validator
    to ``_validate_codex_oauth``. Pre-B.03 the bridge would start with an empty
    Claude OAuth token (``BridgeConfig.claude_oauth_token`` defaults to ``""``)
    and surface the failure on the first ``claude -p`` invocation, with an
    opaque subprocess error far from the actual root cause. The fix is the
    same shape as the Codex validator: refuse to boot at startup, name the
    missing field and the remediation steps in the error message.

    Lives at module scope so the unit test can call it without constructing a
    full ``BridgeApp``. No I/O — reads only config fields.

    Raises:
        RuntimeError: when ``claude_oauth_token`` is empty and the runtime can
            route work to Claude. The message names the missing field, the
            rotation companion fields, the canonical secrets path, the mode
            discipline, and the restart action.
    """
    token = str(getattr(config, "claude_oauth_token", "") or "")
    if token:
        return
    if not _requires_claude_oauth(config):
        return
    raise RuntimeError(
        "Bridge refuses to boot: claude_oauth_token is missing from "
        ".secrets. Add `claude_oauth_token=<token>` (plus "
        "`claude_oauth_refresh_token` and `claude_oauth_expires_at`) to "
        "/opt/bumba-harness/data/.secrets, then `chmod 600` the file and "
        "restart the bridge. Sprint audit-2026-05-16.B.03 (#2052, HI-5)."
    )


def _validate_openrouter_api_key_required(config: object) -> None:
    """Refuse to boot when active OpenRouter routing lacks an API key."""
    if not _requires_openrouter_api_key(config):
        return
    key = str(getattr(config, "openrouter_api_key", "") or "")
    if key:
        return
    raise RuntimeError(
        "Bridge refuses to boot: backend 'openrouter' is configured via "
        "[backends] but openrouter_api_key is missing from .secrets. "
        "Either remove openrouter from [backends] or add "
        "`openrouter_api_key=<key>` to /opt/bumba-harness/data/.secrets, "
        "then `chmod 600` the file and restart the bridge."
    )


def _validate_codex_cost_readiness(config: object) -> None:
    """Refuse to boot when the Codex backend cannot produce cost measurements.

    Sprint audit-2026-05-16.D.03 / HI-3 (#2064) — readiness contract check that
    runs after ``_validate_codex_oauth``. D.01 introduced ``CostMeasurement``
    and D.02 wired Codex's ``parse_cost`` to return ``source='unknown'`` for
    turns with no ``cost_usd`` field instead of collapsing into a measured
    zero. If that contract is silently broken at boot (missing method, wrong
    return type, or the legacy float collapse comes back), budget enforcement
    becomes meaningless without surfacing any error. This validator probes
    the in-memory backend with three synthetic events and refuses to boot
    when the responses do not match the contract.

    No I/O is performed — the check constructs a ``CodexBackend`` and calls
    ``parse_cost`` on dict literals. Mirrors ``_validate_codex_oauth``: lives
    at module scope, defensive ``getattr``, no-op when ``backends_enabled``
    is false or no role resolves to ``codex``, raises ``RuntimeError`` with
    an actionable operator-facing message on failure.

    Imports of ``CodexBackend`` and ``CostMeasurement`` are deferred to
    function body to avoid circular imports at module load time.

    Raises:
        RuntimeError: when the Codex backend's ``parse_cost`` does not honor
            the D.01/D.02 contract (e.g. missing method, returns a legacy
            float, returns a ``CostMeasurement`` with the wrong ``source``
            or ``amount_usd`` for the probe inputs).
    """
    # Defensive getattr — same posture as ``_validate_codex_oauth``. When
    # Codex isn't in the backends registry, there's nothing to validate.
    backends_enabled = bool(getattr(config, "backends_enabled", False))
    if not backends_enabled:
        return

    backends_main = getattr(config, "backends_main", "") or ""
    backends_chiefs_default = getattr(config, "backends_chiefs_default", "") or ""
    backends_specialists_default = (
        getattr(config, "backends_specialists_default", "") or ""
    )
    overrides_raw = getattr(config, "backends_specialists_overrides", None)
    if isinstance(overrides_raw, dict):
        override_values = tuple(str(v) for v in overrides_raw.values())
    else:
        override_values = ()

    configured_backends = {
        str(backends_main),
        str(backends_chiefs_default),
        str(backends_specialists_default),
        *override_values,
    }
    if "codex" not in configured_backends:
        return

    # Lazy imports avoid the circular dependency between ``bridge.app`` and
    # ``bridge.backends.codex`` / ``bridge.cost_tracker``.
    from decimal import Decimal

    from .backends.codex import CodexBackend
    from .cost_tracker import CostMeasurement

    remediation = (
        "Codex backend parse_cost contract is broken — budget enforcement "
        "would be silently meaningless. See audit-2026-05-16.D.03 (#2064) "
        "and bridge/cost_tracker.py for the CostMeasurement contract. "
        "D.02 (#2063) is the live wiring; verify bridge/backends/codex.py "
        "parse_cost has not regressed to a legacy float return."
    )

    try:
        backend = CodexBackend(config)  # type: ignore[arg-type]
    except Exception as exc:  # noqa: BLE001 — surface every failure mode
        raise RuntimeError(
            f"Bridge refuses to boot: cannot construct CodexBackend for "
            f"cost-readiness probe: {exc}. {remediation}"
        ) from exc

    parse_cost = getattr(backend, "parse_cost", None)
    if not callable(parse_cost):
        raise RuntimeError(
            "Bridge refuses to boot: CodexBackend is missing the "
            "``parse_cost`` method. " + remediation
        )

    # Probe 1: empty event → not_applicable (no ``type`` field at all).
    # Probe 2: turn.completed with no cost_usd → source='unknown', amount=None.
    # Probe 3: turn.completed with cost_usd=0.0 → source='measured',
    #          amount=Decimal('0') (the SW-3 invariant: measured zero is
    #          distinct from unknown).
    probes: tuple[tuple[dict, str, object], ...] = (
        ({}, "not_applicable", None),
        ({"type": "turn.completed"}, "unknown", None),
        (
            {"type": "turn.completed", "cost_usd": 0.0},
            "measured",
            Decimal("0"),
        ),
    )

    for event, expected_source, expected_amount in probes:
        try:
            result = parse_cost(event)
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(
                f"Bridge refuses to boot: CodexBackend.parse_cost raised "
                f"on probe event {event!r}: {exc}. {remediation}"
            ) from exc

        if not isinstance(result, CostMeasurement):
            raise RuntimeError(
                f"Bridge refuses to boot: CodexBackend.parse_cost returned "
                f"{type(result).__name__} for event {event!r} (expected "
                f"CostMeasurement). This is the legacy-float collapse the "
                f"D.01/D.02 contract exists to prevent. " + remediation
            )

        if result.source != expected_source:
            raise RuntimeError(
                f"Bridge refuses to boot: CodexBackend.parse_cost returned "
                f"source={result.source!r} for event {event!r} (expected "
                f"{expected_source!r}). " + remediation
            )

        if result.amount_usd != expected_amount:
            raise RuntimeError(
                f"Bridge refuses to boot: CodexBackend.parse_cost returned "
                f"amount_usd={result.amount_usd!r} for event {event!r} "
                f"(expected {expected_amount!r}). An ``unknown`` measurement "
                f"that carries a numeric amount, or a ``measured`` zero that "
                f"loses its Decimal type, breaks the SW-3 invariant. "
                + remediation
            )


def _active_backends_from_config(config: object) -> tuple[str, ...]:
    """Return the tuple of backend names a config would route work through.

    Backend Operability S2.1 (#2279) — pure helper consumed by
    ``_validate_backend_readiness`` so the boot guard sees the same active
    set as runtime dispatch. Mirrors the ``configured_backends`` walk inside
    ``_validate_codex_oauth`` and ``_validate_codex_cost_readiness`` but
    returns a tuple so order is preserved for diagnostic messages.

    Reads ``backends_main``, ``backends_chiefs_default``,
    ``backends_specialists_default``, and the values of
    ``backends_specialists_overrides`` (when present and a dict). Empty
    strings are filtered so a stub config without any backends field reads
    as an empty active set.
    """
    values: list[str] = []
    for attr in ("backends_main", "backends_chiefs_default", "backends_specialists_default"):
        value = str(getattr(config, attr, "") or "")
        if value:
            values.append(value)
    overrides_raw = getattr(config, "backends_specialists_overrides", None)
    if isinstance(overrides_raw, dict):
        values.extend(str(v) for v in overrides_raw.values() if v)
    return tuple(values)


def _validate_backend_readiness(config: object) -> None:
    """Refuse to boot when ``readiness_for_flip`` rejects the active backend set.

    Backend Operability S2.1 (#2279) — makes ``readiness_for_flip`` (E.04
    #2011) load-bearing during startup. Previously the flip guard was only
    consulted by operator tooling; a token-bearing Codex config could pass
    ``_validate_codex_oauth`` even though Codex still emits
    ``cost_unknown=True`` on every turn (``codex_cost_computable()`` is
    False). This validator wires the same predicate into bridge boot so the
    daemon refuses to come up when budget enforcement would be silently
    meaningless.

    No-op when ``backends_enabled`` is false. Defensive ``getattr`` mirrors
    the sibling validators so configs that predate the Codex-3 registry
    fields still boot cleanly through the legacy claude-only path.

    Raises:
        RuntimeError: when ``readiness_for_flip`` returns ``(False, reason)``.
            The ``reason`` string from ``readiness_for_flip`` names the
            missing precondition and the issue it tracks.
    """
    # Lazy import avoids the circular dependency between ``bridge.app`` and
    # ``bridge.backends`` at module load.
    from bridge.backends import readiness_for_flip

    ready, reason = readiness_for_flip(
        backends_enabled=bool(getattr(config, "backends_enabled", False)),
        active_backends=_active_backends_from_config(config),
    )
    if not ready:
        raise RuntimeError(reason)


class BridgeApp:
    """Main application: initializes components, runs startup/shutdown, processes messages."""

    def __init__(self, config_path: str | None = None) -> None:
        self._config_path = config_path
        self._config: BridgeConfig | None = None
        # Board Phase 2 WS1 (#2391) — last wiring report from
        # apply_wiring_manifest(), retained so the operator dashboard can
        # summarize active/pending/error/failed wires without re-running
        # the manifest. None until _wire() completes.
        self._wiring_report: "WiringReport | None" = None
        self._db: Database | None = None
        self._queue: MessageQueue | None = None
        self._memory: Memory | None = None
        self._session_mgr: SessionManager | None = None
        self._security: SecurityManager | None = None
        self._claude: ClaudeRunner | None = None
        # D7.9 #1421 — operator inbox for mid-stream interrupt activation.
        # Initialized in _initialize() right after self._claude. One inbox
        # per bridge process; sees operator messages that arrive during an
        # in-flight claude.invoke() so the slice-1 mid-stream check can yield.
        self._operator_inbox = None  # type: ignore[assignment]  # OperatorInbox | None
        # #1535 (Plan W W-1.4) — DialogueDelayMonitor wires the third leg of
        # the Phase-4B triad (inbox + tool-call gate + delay monitor). One
        # monitor per bridge process; started/stopped per session by
        # SessionManager. Held here so tests + diagnostics can inspect it.
        self._dialogue_delay_monitor = None  # type: ignore[assignment]  # DialogueDelayMonitor | None
        self._discord: DiscordBot | None = None
        self._commands: CommandHandler | None = None

        self._shutdown_event = asyncio.Event()
        self._processing_task: asyncio.Task | None = None
        self._heartbeat_task: asyncio.Task | None = None
        self._decay_task: asyncio.Task | None = None
        self._backup_task: asyncio.Task | None = None
        self._reflection_task: asyncio.Task | None = None
        self._consolidation_task: asyncio.Task | None = None
        self._drift_task: asyncio.Task | None = None
        self._warm_health_task: asyncio.Task | None = None  # Sprint D8.4
        self._hooks_telemetry_subscriber = None  # E2.3 — HooksTelemetrySubscriber
        self._token_refresher: TokenRefresher | None = None
        self._warm_claude: WarmClaudeProcess | None = None
        self._pid_path: Path | None = None
        self._halted = False
        # Sprint 01.08b: HookDispatcher deleted (audit found 0 production hooks)
        self._task_queue: TaskQueue | None = None
        self._fallback: FallbackChain | None = None
        self._health_server: HealthServer | None = None
        self._heartbeat_pinger: HeartbeatPinger | None = None
        self._budget: BudgetGuard | None = None
        self._breakers: CircuitBreakerRegistry | None = None
        self._lifecycle: SubprocessLifecycle | None = None
        self._rate_limiter: TokenBucket | None = None
        self._metrics: MetricsCollector | None = None
        self._autonomy: AutonomyLayer | None = None
        self._tmux_agents = None  # TmuxAgentManager | None
        self._suggester = None  # CommandSuggester | None
        self._registry_index = None  # RegistryIndex | None (E2.4)
        self._few_shot: FewShotStore | None = None
        self._self_edit: SelfEditMemory | None = None
        self._temporal_kb: TemporalKnowledgeStore | None = None
        self._tracer: Tracer | None = None
        self._cost_tracker: CostTracker | None = None
        self._routing_feedback: RoutingFeedbackEngine | None = None
        self._session_recovery: SessionRecoveryManager | None = None
        self._reflection_store: ReflectionStore | None = None
        self._reflexion_ctx: ReflexionContext | None = None
        self._mcp_monitor: MCPMonitor | None = None
        self._skill_evolution: SkillEvolutionEngine | None = None
        # Sprint #1112/4.03 (#2150) — central SkillAllocator (manifest-driven,
        # default-deny). Constructed in ``app_init.py`` from
        # ``agent/config/skill-allocation/manifest.yaml`` and threaded down to
        # every agent-instantiation site via ChiefDispatcher → WarmChief →
        # DepartmentTeam → build_manager_agent / build_employee_agents.
        # ``_skill_allocator_init_failed`` flips True when manifest parsing
        # raises so the WIRING_MANIFEST entry routes the wire into
        # ``report.failed`` (mirrors the ProactiveScheduler pattern #1614).
        self._skill_allocator: SkillAllocator | None = None
        self._skill_allocator_init_failed = False
        self._project_registry: ProjectRegistry | None = None
        self._evaluator: ResponseEvaluator | None = None
        self._agent_router: AgentRouter | None = None
        self._runbook_engine: RunbookEngine | None = None
        self._embedding_engine: LocalEmbeddingEngine | None = None
        # Sprint 05.01 — LocalEmbeddingClient shim (duck-typed
        # is_configured + generate); wired into Memory at construction.
        self._embedding_client = None  # LocalEmbeddingClient | None
        self._hybrid_search: HybridSearch | None = None
        # Board Phase 3 WS1 (#2392) — recall-usage tracker for the learning
        # knowledge store. Constructed unconditionally in _initialize; wired
        # onto Memory via the WIRING_MANIFEST so used_count boosting + recall
        # recording activate.
        self._recall_tracker = None
        self._api_server: APIServer | None = None
        self._session_hooks: SessionHookRegistry | None = None
        self._self_verifier = None  # SelfVerifier | None
        self._task_pipeline = None  # TaskPipeline | None
        self._quality_gate = None  # QualityGate | None
        self._webhook_receiver = None  # WebhookReceiver | None
        # Board Phase 2 WS4 / Phase 3 WS2 (#2391/#2392) — board-run + outcome
        # store. Constructed in app_init; wired onto the WebhookReceiver via
        # the WIRING_MANIFEST so issue-close events record board outcomes.
        self._board_run_store = None
        self._webhook_deliverer = None  # SerialEventDeliverer | None
        self._departments = None  # DepartmentRegistry | None (Zone 4)
        # RR.6 (#2593) — RosterRegistryStore, constructed in app_init inside the
        # teams-available branch and wired to the command handler + REST surface.
        # None until then (or if the teams stack is unavailable).
        self._roster_registry = None
        # Z4-S22 #1395 — chief-session orchestration stack.
        # All three remain None unless `chief_dispatcher_enabled=True` in
        # bridge.toml. The api_server (Z4-S12 #1383) reads
        # ``self._chief_session_store`` via getattr to gate route
        # registration; the commands layer (Z4-S13 #1388) reads it via
        # `set_chief_session_store()` for /chief_sessions.
        self._chief_session_store = None  # SQLiteChiefSessionStore | None
        self._chief_router = None  # RuleBasedWorkOrderRouter | None
        self._chief_dispatcher = None  # ChiefDispatcher | None
        # Z4-S30 #1391 — idle-timeout reaper task handle. Spawned in
        # ``start()`` only when chief dispatcher + store are both wired.
        self._chief_session_reaper_task = None  # asyncio.Task | None
        self._dispatcher = None  # Dispatcher | None (Zone 3)
        # P2.1 #1717 — RecursiveDecomposer wired into the dispatcher when
        # ``workorder_decomposition_enabled`` is true. Declared here as None
        # so the WIRING_MANIFEST source resolution is well-defined even
        # before _initialize() runs.
        self._recursive_decomposer = None  # RecursiveDecomposer | None (Zone 3)
        self._recursive_decomposer_init_failed = False
        # P8.2 #1748 — DreamNotifier instance. Constructed in _initialize()
        # once self._discord is available. Holds the live Discord client so
        # consolidation phase updates can be surfaced to the operator. The
        # ConsolidationService runs in a separate LaunchDaemon subprocess
        # (services/runner.py) so this attribute does not feed that service
        # directly; it's the bridge-side handle for future event-driven
        # consumers (e.g. an event-bus subscriber that mirrors
        # consolidation.started/completed into Discord).
        self._dream_notifier = None  # DreamNotifier | None
        self._dream_notifier_init_failed = False
        self._env_selector = None  # EnvironmentSelector | None (Zone 3 S02d)
        # Sprint 07.13 — StreamCoalescer pre-stash. The actual instance is
        # constructed in _initialize() once self._discord exists; declared
        # here as None so the WIRING_MANIFEST source resolution
        # (getattr(app, "_stream_coalescer")) is well-defined even before
        # _initialize() runs.
        self._stream_coalescer = None  # StreamCoalescer | None
        # Sprint 01.02 — pre-stashed sources for the wiring manifest. These
        # carry values that aren't simple stored attributes (lambda, computed
        # Path, function call) so they can flow through apply_wiring_manifest's
        # getattr-based source resolution. Set during _initialize() right
        # before _wire().
        self._shutdown_callback = None  # Callable[[], None] | None
        self._log_dir: Path | None = None
        # Zone 4 synthetic sources — only assigned non-None inside the
        # _TEAMS_AVAILABLE try-block, preserving the original gate.
        self._circuit_registry = None
        self._memory_for_zone4 = None  # gated mirror of self._memory
        # Sprint 01.03 — wire-to-None CommandHandler sources. These five
        # setter targets exist on CommandHandler today (commands.py:118,134,
        # 138,142,146) but their upstream constructors live in future plans:
        #   _workflow_registry / _workflow_engine — Plan 04
        #   _routing_brain                        — Plan 03
        #   _tick_manager                         — Sprint 09.13 (deferred)
        #   _daily_log                            — Plan 02 (Sprint 09.14)
        # Declaring them as None at __init__ keeps the WIRING_MANIFEST entries
        # discoverable via getattr without firing — they show up in the boot
        # WiringReport's pending list with their owning-plan reason.
        self._workflow_registry = None
        self._workflow_engine = None
        self._routing_brain = None
        self._tick_manager = None
        # Sprint 09.13 — declare proactive scaffolding attrs as None at
        # __init__ time. _initialize() sets them when proactive_enabled=True;
        # otherwise they stay None and the WiringReport surfaces dormancy.
        self._proactive_guard = None  # ProactiveGuard | None
        self._tick_context_builder = None  # TickContextBuilder | None
        # D7.12 #1424 (slice 1) — perpetual-proactive scheduler. Distinct
        # from TickManager: TickManager injects <tick> prompts (agent-driven
        # choice); the scheduler is the bridge-driven peer that picks work
        # items from the dep-graph. Slice 1 ships dry-run only.
        self._proactive_scheduler = None  # ProactiveScheduler | None
        self._tick_loop_task = None  # asyncio.Task | None — set in start()
        # _daily_log was previously initialized inside _initialize() (~line 498)
        # — moving the default here so all five wire-to-None sources sit
        # together. set_daily_log() at the BridgeApp level still mutates this
        # attribute when Plan 02 wires it.
        self._daily_log: DailyLogWriter | None = None
        # Sprint 01.04 — three more reflexive BridgeApp wire-to-None sources
        # plus two WorkOrder attributes whose construction shape Plan 03 will
        # decide. _workorder_store / _workorder_stream stay attribute-only
        # (no manifest entry) so api_server.py:1385 reads a deliberate None
        # via getattr instead of risking AttributeError.
        self._memory_file = None
        self._workorder_store = None
        self._workorder_ingestor = None
        self._workorder_stream = None
        # Sprint 07.04 — peer coordination scaffolding. Both attributes are
        # always declared (None by default) so subsequent sprints
        # (07.05/06/07/08) can reference them without getattr. They stay
        # None unless config.peer_coordination_enabled is True, in which
        # case _initialize() constructs both and start()/stop() drive the
        # PeerRegistrationManager lifecycle.
        self._peer_registry = None  # PeerRegistry | None
        self._peer_registration = None  # PeerRegistrationManager | None
        # Sprint 07.07 — RemoteEventBridge for peer-target event routing.
        # Stays None unless config.peer_coordination_enabled is True;
        # when True, _initialize() constructs the bridge with the
        # default _LocalLogTransport (preserving prior stub behavior)
        # and the WIRING_MANIFEST hands it to AutonomyLayer.event_bus
        # via set_remote_event_bridge. EventBus.publish detects
        # ``peer_target`` payload entries and forwards through this
        # bridge; the actual MCPRemoteTransport is a documented stub.
        self._remote_event_bridge = None  # RemoteEventBridge | None

    def _require(self, *names: str) -> None:
        """Verify that named attributes are initialized, or raise RuntimeError."""
        missing = [n for n in names if getattr(self, n, None) is None]
        if missing:
            raise RuntimeError(
                f"BridgeApp not initialized (missing {', '.join(missing)}). "
                "Call start() first."
            )

    # -- S77: Initialize and wire all components --

    async def _initialize(self) -> None:
        """Load config, connect DB, migrate, create all components, wire callbacks."""
        from .app_init import BridgeAppInit

        await BridgeAppInit(self).run()

    def _wire(self) -> None:
        """Apply the WIRING_MANIFEST against this BridgeApp instance.

        Constructs the 28-entry manifest covering every CommandHandler setter
        that the previous scattered-calls path invoked at ``_initialize()`` time.
        ``required=True`` entries fire unconditionally (their absence is a
        production bug — RuntimeError surfaces it loud). ``required=False``
        entries with matching ``reason_if_none`` capture the cases that were
        previously gated by ``if self._X:`` checks or try/except wrapping —
        when their source is ``None``, they appear in the report's pending
        list with the owning-plan reason.

        See agent/scripts/lint_no_scattered_setters.py — CI fails any new
        ``self._commands.set_*(...)`` call outside this method.
        """
        ch = self._commands
        manifest: list[WiringEntry] = [
            # Always-on subsystems — their absence is a boot bug.
            WiringEntry("CommandHandler", ch, "set_session_hooks",
                        "_session_hooks", True,
                        "session hooks must be live", "command-handler"),
            WiringEntry("CommandHandler", ch, "set_security",
                        "_security", True,
                        "security manager must be live", "command-handler"),
            WiringEntry("CommandHandler", ch, "set_self_verifier",
                        "_self_verifier", True,
                        "self-verifier always constructed", "command-handler"),
            WiringEntry("CommandHandler", ch, "set_shutdown_callback",
                        "_shutdown_callback", True,
                        "shutdown callback always installed", "command-handler"),
            # Conditional subsystems — pre-existing if-guards now live in the
            # manifest as required=False with reason_if_none.
            WiringEntry("CommandHandler", ch, "set_autonomy",
                        "_autonomy", False,
                        "AutonomyLayer init may fail; runs without it",
                        "command-handler"),
            WiringEntry("CommandHandler", ch, "set_webhook_deliverer",
                        "_webhook_deliverer", False,
                        "webhook delivery is opt-in via [api] config",
                        "command-handler"),
            WiringEntry("CommandHandler", ch, "set_tmux_agents",
                        "_tmux_agents", False,
                        "tmux multi-agent stack may be disabled",
                        "command-handler"),
            # Always-on subsystems again.
            WiringEntry("CommandHandler", ch, "set_few_shot_store",
                        "_few_shot", True,
                        "few-shot store always constructed",
                        "command-handler"),
            WiringEntry("CommandHandler", ch, "set_self_edit",
                        "_self_edit", True,
                        "self-edit memory always constructed",
                        "command-handler"),
            WiringEntry("CommandHandler", ch, "set_temporal_kb",
                        "_temporal_kb", True,
                        "temporal KB always constructed",
                        "command-handler"),
            WiringEntry("CommandHandler", ch, "set_tracer",
                        "_tracer", True,
                        "tracer always constructed",
                        "command-handler"),
            WiringEntry("CommandHandler", ch, "set_cost_tracker",
                        "_cost_tracker", True,
                        "cost tracker always constructed",
                        "command-handler"),
            WiringEntry("CommandHandler", ch, "set_routing_feedback",
                        "_routing_feedback", True,
                        "routing feedback always constructed",
                        "command-handler"),
            WiringEntry("CommandHandler", ch, "set_reflection_store",
                        "_reflection_store", True,
                        "reflection store always constructed",
                        "command-handler"),
            # MCP monitor only when claude_working_dir + .mcp.json exist.
            WiringEntry("CommandHandler", ch, "set_mcp_monitor",
                        "_mcp_monitor", False,
                        "MCP monitor needs claude_working_dir + .mcp.json",
                        "command-handler"),
            # Always-on.
            WiringEntry("CommandHandler", ch, "set_skill_evolution",
                        "_skill_evolution", True,
                        "skill evolution always constructed",
                        "command-handler"),
            WiringEntry("CommandHandler", ch, "set_project_registry",
                        "_project_registry", True,
                        "project registry always constructed",
                        "command-handler"),
            WiringEntry("CommandHandler", ch, "set_runbook_engine",
                        "_runbook_engine", True,
                        "runbook engine always constructed",
                        "command-handler"),
            WiringEntry("CommandHandler", ch, "set_agent_router",
                        "_agent_router", True,
                        "agent router always constructed",
                        "command-handler"),
            # Zone 4 observability — gated on tool_tracker availability.
            WiringEntry("CommandHandler", ch, "set_cost_attributor",
                        "_cost_attributor", False,
                        "Z4 cost attributor needs tool_tracker enabled",
                        "command-handler"),
            WiringEntry("CommandHandler", ch, "set_metrics_aggregator",
                        "_metrics_aggregator", False,
                        "Z4 metrics aggregator needs tool_tracker enabled",
                        "command-handler"),
            # Zone 4 departments stack — gated on _TEAMS_AVAILABLE + successful
            # DepartmentRegistry init. set_circuit_registry / set_memory share
            # the same gate via _circuit_registry / _memory_for_zone4 which
            # are only assigned non-None inside that try-block.
            WiringEntry("CommandHandler", ch, "set_departments",
                        "_departments", False,
                        "Zone 4 teams package may be unavailable",
                        "command-handler"),
            # RR.6 (#2593) — wire the roster store into the command handler so
            # /register-specialist, /unregister-specialist, /roster reach it.
            # Shares the _departments gate: the store is only constructed in the
            # teams-available branch, so it stays None (pending) otherwise.
            WiringEntry("CommandHandler", ch, "set_roster_registry",
                        "_roster_registry", False,
                        "Zone 4 teams package may be unavailable",
                        "command-handler"),
            WiringEntry("CommandHandler", ch, "set_circuit_registry",
                        "_circuit_registry", False,
                        "circuit registry only when teams stack initializes",
                        "command-handler"),
            WiringEntry("CommandHandler", ch, "set_memory",
                        "_memory_for_zone4", False,
                        "memory wiring gated on Zone 4 teams success",
                        "command-handler"),
            # Conditional.
            WiringEntry("CommandHandler", ch, "set_warm_claude",
                        "_warm_claude", False,
                        "warm Claude process may be disabled",
                        "command-handler"),
            # Always-on (pre-stashed Path).
            WiringEntry("CommandHandler", ch, "set_log_dir",
                        "_log_dir", True,
                        "log directory path always available",
                        "command-handler"),
            # Sprint 01.05: deleted dead "set_metrics" WiringEntry — the
            # CommandHandler class has no set_metrics() method (only
            # set_metrics_aggregator), and _metrics is None at _initialize()
            # apply time, so the entry never fired. Confirmed by grep across
            # bridge/, tests/, teams/.
            # Dispatcher — try/except wrapped, may fail.
            WiringEntry("CommandHandler", ch, "set_dispatcher",
                        "_dispatcher", False,
                        "dispatcher init may fail (non-fatal)",
                        "command-handler"),
            # Sprint 01.03 — five wire-to-None CommandHandler entries.
            # The setter targets exist (commands.py:118,134,138,142,146) but
            # their upstream sources are owned by future plans. Declared here
            # so the WiringReport surfaces dormancy at boot time instead of
            # at first /workflows or /dispatch invocation. When the owning
            # plans assign self._X to a real instance, the same entry fires
            # automatically — no second refactor.
            WiringEntry("CommandHandler", ch, "set_workflow_registry",
                        "_workflow_registry", False,
                        "Plan 04 owns construction",
                        "command-handler"),
            WiringEntry("CommandHandler", ch, "set_workflow_engine",
                        "_workflow_engine", False,
                        "Plan 04 owns construction",
                        "command-handler"),
            WiringEntry("CommandHandler", ch, "set_routing_brain",
                        "_routing_brain", False,
                        "Plan 03 owns construction",
                        "command-handler"),
            # Sprint #1614 — pass ``failed_marker_attr`` so that an init
            # exception in the proactive blocks above (TickManager /
            # ProactiveScheduler construction) routes the entry into
            # ``report.failed`` instead of ``report.pending``. The operator
            # can then tell "deferred by plan" from "tried and crashed".
            WiringEntry("CommandHandler", ch, "set_tick_manager",
                        "_tick_manager", False,
                        "Deferred; revive if proactive mode activated (Sprint 09.13)",
                        "command-handler",
                        failed_marker_attr="_tick_manager_init_failed"),
            WiringEntry("CommandHandler", ch, "set_proactive_scheduler",
                        "_proactive_scheduler", False,
                        "Deferred; revive when proactive_scheduler_enabled=True (D7.12 #1424 slice 1)",
                        "command-handler",
                        failed_marker_attr="_proactive_scheduler_init_failed"),
            # Z4-S22 #1395 NOTE: the `set_chief_session_store` WiringEntry
            # lands when Z4-S13 (#1388, /chief_sessions Discord command,
            # PR #1453) merges — that PR adds the setter on CommandHandler.
            # Until then, this WiringEntry is omitted to avoid an
            # AttributeError at startup.
            WiringEntry("CommandHandler", ch, "set_daily_log",
                        "_daily_log", False,
                        "Plan 02 owns construction via BridgeApp.set_daily_log "
                        "then mirrors here (Sprint 09.14)",
                        "command-handler"),
            # Sprint 01.04 — three reflexive BridgeApp wire-to-None entries.
            # target=self means the manifest calls a BridgeApp setter on
            # itself when source is non-None. The setters are idempotent
            # (self._X = self._X is a no-op when source resolves to the same
            # attribute already present) so the reflexive call doesn't
            # recurse. Their purpose is to make the upstream-wiring contract
            # operator-visible at boot time.
            WiringEntry("BridgeApp", self, "set_daily_log",
                        "_daily_log", False,
                        "Plan 02 owns DailyLogWriter construction",
                        "bridge-app"),
            WiringEntry("BridgeApp", self, "set_memory_file",
                        "_memory_file", False,
                        "Plan 05 owns MemoryFile construction",
                        "bridge-app"),
            # Sprint #1112/4.03 (#2150) — reflexive entry for the central
            # SkillAllocator. Construction lives in app_init.py from
            # agent/config/skill-allocation/manifest.yaml. required=False
            # because the manifest file may be absent at boot — in that case
            # app_init constructs an empty (default-deny) SkillAllocator,
            # logs a warning, and the wire still fires with a non-None
            # source. ``failed_marker_attr`` escalates a construction crash
            # from PENDING to FAILED so the operator can tell "manifest not
            # deployed" from "manifest deployed but parsing raised."
            WiringEntry("BridgeApp", self, "set_skill_allocator",
                        "_skill_allocator", False,
                        "Manifest at agent/config/skill-allocation/manifest.yaml "
                        "(default-deny if absent — Sprint #1112/4.03)",
                        "bridge-app",
                        failed_marker_attr="_skill_allocator_init_failed"),
            # Sprint 07.13 — wire StreamCoalescer onto DiscordBot. The bridge
            # constructs the coalescer in _initialize() so the manifest entry
            # has a non-None source; `set_stream_coalescer` was a Pattern B
            # setter-orphan (R2 audit: imported, no callers) until this entry
            # closed the loop. required=True because once the coalescer is
            # constructed it must be attached — anything else means streaming
            # text bypasses batching and floods Discord with edits.
            WiringEntry("DiscordBot", self._discord, "set_stream_coalescer",
                        "_stream_coalescer", True,
                        "Plan 07.13 owns construction",
                        "discord-bot"),
            # Sprint 05.02 — wire HybridSearch onto Memory after both are
            # constructed. `target=self._memory` (not BridgeApp) because
            # the setter lives on Memory. Pending until the engine
            # constructs HybridSearch successfully (FTS5 still active in
            # that case). Sprint 05.03 makes Memory.search_knowledge
            # consume `self._hybrid_search` — until then this wire is
            # observable but inert.
            WiringEntry("Memory", self._memory, "set_hybrid_search",
                        "_hybrid_search", False,
                        "Plan 05 Sprint 05.02 — HybridSearch may fail to "
                        "init (FTS5 still active); Sprint 05.03 activates "
                        "consumption",
                        "memory"),
            # Sprint Mem-4 (#1845) — DualWritePipeline wire onto Memory.
            # Construction lives in _initialize above (gated by
            # memory_tiers_enabled). When the flag is off, source resolves to
            # None and the entry surfaces in the WiringReport's pending list.
            # ``failed_marker_attr`` escalates a construction crash from
            # PENDING to FAILED so the operator can tell "deferred by flag"
            # from "tried and crashed" (mirrors the ProactiveScheduler
            # pattern from #1614).
            WiringEntry("Memory", self._memory, "set_dual_write_pipeline",
                        "_dual_write_pipeline", False,
                        "Gated by memory_tiers_enabled (default False)",
                        "memory",
                        failed_marker_attr="_dual_write_pipeline_init_failed"),
            # Board Phase 3 WS1 (#2392) — RecallTracker wire onto Memory.
            # Constructed unconditionally in app_init, so this resolves to
            # ACTIVE at boot. Activates used_count recall boosting + recall
            # recording in Memory.search_knowledge.
            WiringEntry("Memory", self._memory, "set_recall_tracker",
                        "_recall_tracker", False,
                        "Board Phase 3 learning knowledge store (#2392)",
                        "memory"),
            # Board Phase 3 WS2 (#2392) — wire the BoardRunStore onto the
            # WebhookReceiver so closed board-generated issues record outcomes.
            # Both constructed in app_init, so this resolves ACTIVE at boot.
            WiringEntry("WebhookReceiver", self._webhook_receiver,
                        "set_board_run_store", "_board_run_store", False,
                        "Board Phase 3 feedback loop (#2392)",
                        "memory"),
        ]

        # Sprint 07.07 — wire RemoteEventBridge onto the AutonomyLayer's
        # EventBus. The setter lives on EventBus (target= autonomy
        # event_bus, group="autonomy"). required=False because the
        # source (_remote_event_bridge) is constructed only when
        # config.peer_coordination_enabled is True; in the off case the
        # entry surfaces in the WiringReport's pending list. We compute
        # the target after the AutonomyLayer is live (_initialize ran
        # AutonomyLayer construction before _wire) and only add the
        # entry when a setter target exists — the absence of the
        # AutonomyLayer is itself a separate failure surfaced through
        # set_autonomy on CommandHandler.
        event_bus_target = (
            self._autonomy.event_bus if self._autonomy is not None else None
        )
        if event_bus_target is not None and hasattr(
            event_bus_target, "set_remote_event_bridge"
        ):
            manifest.append(
                WiringEntry(
                    "EventBus",
                    event_bus_target,
                    "set_remote_event_bridge",
                    "_remote_event_bridge",
                    False,
                    "Plan 07.07 owns construction; flag-gated by "
                    "peer_coordination_enabled",
                    "autonomy",
                )
            )

        # Sprint P8.3 / audit M-4 (#1749) — declare the VAPI tool-handler
        # wire in the manifest so the previously-invisible direct write to
        # the VAPIClient ``_tool_handler`` private attribute becomes
        # operator-visible at boot. required=False because _vapi /
        # _tool_handler are only constructed when ``voice_enabled=True``;
        # in the off case the entry surfaces in the WiringReport's pending
        # list. The actual ``set_tool_handler`` call still runs inline in
        # _initialize (alongside _vapi construction) — this entry is the
        # declarative mirror, mirroring the EventBus/RemoteEventBridge
        # pattern above.
        vapi_target = getattr(self, "_vapi", None)
        if vapi_target is not None and hasattr(vapi_target, "set_tool_handler"):
            manifest.append(
                WiringEntry(
                    "VAPIClient",
                    vapi_target,
                    "set_tool_handler",
                    "_tool_handler",
                    False,
                    "Voice subsystem only — gated by voice_enabled",
                    "bridge-app",
                )
            )

        # Sprint P2.1 #1717 — declare the RecursiveDecomposer wire in the
        # manifest so the boot WiringReport surfaces it. The setter lives
        # on Dispatcher (target=self._dispatcher); required=False because
        # the dispatcher itself is optional (construction may fail
        # non-fatally above). ``failed_marker_attr`` routes the entry into
        # report.failed when construction raises, mirroring the
        # ProactiveScheduler pattern (#1614). The flag
        # ``workorder_decomposition_enabled`` (default False) is the
        # operator-facing gate; this wire makes the gate functional.
        if self._dispatcher is not None and hasattr(
            self._dispatcher, "set_recursive_decomposer"
        ):
            manifest.append(
                WiringEntry(
                    "Dispatcher",
                    self._dispatcher,
                    "set_recursive_decomposer",
                    "_recursive_decomposer",
                    False,
                    "Gated by workorder_decomposition_enabled (default False)",
                    "dispatcher",
                    failed_marker_attr="_recursive_decomposer_init_failed",
                )
            )

        report = apply_wiring_manifest(self, manifest, logger)
        log_wiring_report(report, logger)
        # Board Phase 2 WS1 (#2391) — retain for the operator dashboard.
        self._wiring_report = report

        # Sprint 04.09/04.10/04.11: hand the live BridgeApp to CommandHandler
        # so _cmd_board / _cmd_route / _cmd_handoff can construct BridgeDeps
        # via the BridgeDeps.from_app(self._app, ...) factory. This call lives
        # inside _wire() (lint-compliant) but outside the manifest because the
        # manifest pattern resolves source values via getattr(app, source_attr)
        # — the source here is the app itself, not an attribute on it.
        ch.set_app(self)

        # Sprint 05.11 (#1021) — wire ShadowRouter into CommandHandler so
        # /shadow_report and /promote+/reject_wiki correlation hooks can
        # find it. Mirrors the set_wiki_repo wiring shape (off-manifest
        # because the source is gated on three flags and the manifest
        # currently has no entry for set_wiki_repo either).
        if self._shadow_router is not None:
            ch.set_shadow_router(self._shadow_router)

    def set_daily_log(self, writer: DailyLogWriter | None) -> None:
        """Wire DailyLogWriter for append-only daily log system."""
        self._daily_log = writer

    def set_skill_allocator(self, allocator: SkillAllocator | None) -> None:
        """Wire the central SkillAllocator (Sprint #1112/4.03 — #2150).

        Reflexive setter so the WIRING_MANIFEST entry surfaces the wire in
        the boot WiringReport. Idempotent: ``self._skill_allocator =
        self._skill_allocator`` is a no-op when the source resolves to the
        same attribute already present. Mirrors the ``set_daily_log`` and
        ``set_memory_file`` pattern documented in Sprint 01.04.
        """
        self._skill_allocator = allocator

    async def _primer_callback(self, session_id: str, trigger: str) -> None:
        """#488 primer-write callback wired into session_mgr.

        Called on session expire + /reset. Best-effort: failures are logged
        inside write_primer but never propagate back to the session manager.
        """
        try:
            from bridge.primer_writer import write_primer
        except Exception:
            logger.debug("primer: write_primer import failed", exc_info=True)
            return

        # Minimal deps surface used by write_primer; fields primer_writer tolerates missing.
        _live_registry = getattr(self, "_project_registry", None)
        class _PrimerDeps:
            project_registry = _ProjectRegistryAdapter(_live_registry) if _live_registry else _EmptyBackend()
            memory_store = _MemoryAdapter(self._memory) if self._memory else _EmptyBackend()
            task_queue = _TaskQueueAdapter(self._task_queue) if self._task_queue else _EmptyBackend()
            plan_state = getattr(self, "_plan_state", None) or _EmptyBackend()
            event_bus = getattr(self, "_event_bus", None)
            claude_runner = _ClaudeRunnerAdapter(self._claude) if self._claude else None

            @staticmethod
            def daily_log_tail() -> str:
                dl = getattr(self, "_daily_log", None)
                if dl is None:
                    return ""
                try:
                    return dl.tail(30) if hasattr(dl, "tail") else ""
                except Exception:
                    return ""

        try:
            await write_primer(_PrimerDeps(), session_id=session_id, trigger_source=trigger)  # type: ignore[arg-type]
        except Exception:
            logger.debug("primer: write_primer raised", exc_info=True)

    def set_memory_file(self, memory_file) -> None:
        """Wire MemoryFile for MEMORY.md distilled index injection.

        Renamed from ``set_memory_index`` in Sprint 05.06 of Plan 05 — the
        underlying class is a size-capped MEMORY.md writer, not a vector index.
        """
        self._memory_file = memory_file

    # ------------------------------------------------------------------
    # Sprint 04.07 — WorkflowEngine ↔ DepartmentRegistry signature shim
    # ------------------------------------------------------------------

    def _validate_workflow_departments(self) -> dict[str, list[str]]:
        """Walk every loaded workflow and surface unresolved department refs.

        Returns a mapping ``workflow_name → list_of_unresolved_department_names``.
        Workflows that resolve cleanly map to an empty list; the result is
        useful for tests + the verification evidence file.

        Mismatches log at WARNING level but never raise — failing loudly here
        would crash bridge startup over a YAML typo, which is the wrong
        trade-off given workflows can be reloaded at runtime via
        ``/workflows reload`` once the typo is fixed.
        """
        unresolved: dict[str, list[str]] = {}
        if self._workflow_registry is None:
            return unresolved

        known_departments: set[str] = set()
        if self._departments is not None:
            try:
                known_departments = set(self._departments.department_names())
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "Workflow validation: department_names() failed: %s", exc
                )
                known_departments = set()

        for name in self._workflow_registry.names():
            cfg = self._workflow_registry.get(name)
            if cfg is None:
                continue
            missing: list[str] = []
            for step in cfg.steps:
                dept = getattr(step, "department", None)
                if not dept:
                    continue  # gate / action step — no department
                if known_departments and dept not in known_departments:
                    missing.append(dept)
            unresolved[name] = missing
            if missing:
                logger.warning(
                    "Workflow %r references departments not loaded in "
                    "DepartmentRegistry: %s. Steps will reach the runner "
                    "shim but DepartmentRegistry.route will return an "
                    "Unknown-department TeamResult.",
                    name,
                    sorted(set(missing)),
                )
        return unresolved

    async def _workflow_department_runner(
        self,
        department: str,
        intent: str,
        context: dict,
    ) -> tuple[str, float]:
        """Adapter that lets WorkflowEngine call the live DepartmentRegistry.

        Sprint 04.06 wired ``WorkflowEngine`` with ``department_runner=None``
        because the two halves disagree on shape:

        - WorkflowEngine awaits ``(department, intent, context) -> (str, float)``
          (workflow_engine.py:316-318).
        - DepartmentRegistry exposes ``async route(department, task, deps)
          -> TeamResult`` (teams/_registry.py:194-257).

        This shim closes the gap. It:

        1. Builds a ``BridgeDeps`` for the call via ``BridgeDeps.from_app``,
           tagging the synthetic session id ``workflow:<department>`` so the
           Z4 conversation logger and event bus emit traceable artefacts.
        2. Awaits ``self._departments.route(department, intent, deps)``.
        3. Adapts the returned ``TeamResult`` to ``(str, float)`` — the
           workflow engine's expected tuple — via ``manager_output`` and
           ``total_cost_usd``.

        When the DepartmentRegistry is unavailable (Zone 4 teams package
        missing or YAML load failure), the runner returns
        ``("[department-registry-unavailable]", 0.0)`` so the workflow can
        degrade gracefully instead of crashing the engine. Workflow steps
        that depend on real outputs should fail their downstream gates
        rather than silently treating the placeholder as truth — the empty
        cost ensures budget accounting stays honest.

        ``context`` is the per-step subset of the workflow's shared context
        (the engine projects ``step.inputs`` keys before calling). It is
        currently unused by the adapter; routing through the team uses the
        rendered ``intent`` string. Future sprints can extend BridgeDeps to
        carry it explicitly when needed.
        """
        if self._departments is None:
            logger.warning(
                "Workflow runner: DepartmentRegistry unavailable; "
                "department=%s intent=%.60s — returning empty stub result",
                department,
                intent,
            )
            return ("[department-registry-unavailable]", 0.0)

        try:
            from teams._types import BridgeDeps  # local import: avoids hard dep at module load
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Workflow runner: BridgeDeps import failed (%s); "
                "department=%s — returning empty stub result",
                exc,
                department,
            )
            return ("[bridge-deps-unavailable]", 0.0)

        # WS3.2 (#2570): the engine injects the running workflow name under the
        # reserved ``_workflow_name`` context key (see workflow_engine.py
        # ``_run_department_step``). Threading it onto BridgeDeps tags the
        # team_run cost row that DepartmentRegistry.route() already records —
        # we do NOT add a second cost row. Empty string when absent.
        workflow_name = ""
        if isinstance(context, dict):
            workflow_name = context.get("_workflow_name", "") or ""

        try:
            deps = BridgeDeps.from_app(
                self,
                session_id=f"workflow:{department}",
                department=department,
                cost_limit_usd=self._departments.get_cost_limit(department),
                workflow=workflow_name,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Workflow runner: BridgeDeps.from_app failed for department=%s: %s",
                department,
                exc,
            )
            return (f"[bridge-deps-init-failed: {exc}]", 0.0)

        try:
            result = await self._departments.route(department, intent, deps)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Workflow runner: DepartmentRegistry.route raised for "
                "department=%s: %s",
                department,
                exc,
            )
            return (f"[route-failed: {exc}]", 0.0)

        result_text = getattr(result, "manager_output", "") or ""
        cost = float(getattr(result, "total_cost_usd", 0.0) or 0.0)
        return (result_text, cost)

    # ------------------------------------------------------------------
    # Public accessors for BridgeDeps.from_app() duck-typing
    # ------------------------------------------------------------------

    @property
    def memory(self):
        """Return a MemoryKVAdapter wrapping the bridge Memory instance."""
        if self._memory is None:
            return None
        try:
            from bridge.memory import MemoryKVAdapter
            return MemoryKVAdapter(self._memory)
        except Exception:
            return None

    @property
    def knowledge_search(self):
        """Return the knowledge search callable from the bridge Memory instance."""
        if self._memory is None:
            return None
        return getattr(self._memory, "search_knowledge", None)

    @property
    def cost_tracker(self):
        """Return the CostTracker instance."""
        return getattr(self, "_cost_tracker", None)

    @property
    def event_bus(self):
        """Return the EventBus from the AutonomyLayer."""
        if self._autonomy is None:
            return None
        return getattr(self._autonomy, "event_bus", None)

    @property
    def trust_manager(self):
        """Return the TrustScore manager from the AutonomyLayer."""
        if self._autonomy is None:
            return None
        return getattr(self._autonomy, "trust", None)

    _REQUIRED_FILES = {
        "critical": [
            "SOUL.md",
            "CLAUDE.md",
            # `data_dir:` prefix → resolve against config.data_dir, not
            # claude_working_dir. The kernel baseline lives in the data dir
            # (canonical: /opt/bumba-harness/data/), which is a sibling of
            # the agent dir, not a child.
            "data_dir:kernel-baseline.json",
        ],
        "warning": [
            "OPERATOR.md",
            "RULES.md",
            "TOOLS.md",
        ],
    }

    async def _refresh_warm_claude(self) -> None:
        """Sprint D8.2 — pre-spawn double-buffer on OAuth token refresh.

        Build the replacement warm process BEFORE closing the old one so the
        operator never sees a dead warm process. Sequence:

        1. Spawn a new WarmClaudeProcess with the same parameters as the old.
        2. If new spawn succeeds, atomically swap (self._warm_claude = new),
           then close the old one in the background.
        3. If new spawn fails, keep the old one and best-effort cycle it so
           it picks up the new token. The next cold message would otherwise
           hit an invalidated token.
        4. If the old never spawned (no working_dir captured), skip the
           double-buffer and just cycle in place.

        Replaces the previous close-then-spawn cycle that created a 30-120s
        cold window every ~6h on token refresh.
        """
        old = self._warm_claude
        if old is None:
            return  # nothing to swap

        # Capture spawn parameters from the old process so the new one matches.
        working_dir = getattr(old, "_working_dir", "")
        model = getattr(old, "_model", "haiku")
        system_prompt_file = getattr(old, "_system_prompt_file", None)

        if not working_dir:
            # Old process never spawned — nothing to double-buffer. Fall back
            # to in-place cycle so the old instance is the one that picks up
            # the new token if/when it ever spawns.
            logger.info(
                "Token refresh: warm process never spawned, doing in-place cycle"
            )
            if old.is_alive:
                await old.cycle()
            return

        if self._config is None:
            logger.warning(
                "Token refresh: config missing during refresh; skipping double-buffer"
            )
            return

        logger.info(
            "Token refresh: building replacement warm process before swap"
        )
        new_warm = WarmClaudeProcess(
            config=self._config,
            token_provider=self._token_refresher,
        )
        # P1.1 — re-wire the controller on the respawned process so
        # warm-path interrupt detection survives token-refresh cycles.
        # getattr defaults to None so partially-mocked BridgeApp instances
        # in unit tests don't AttributeError before construction is done.
        _ic = getattr(self, "_invocation_controller", None)
        if _ic is not None:
            new_warm.set_invocation_controller(_ic)
        ok = await new_warm.spawn(working_dir, model, system_prompt_file)
        if not ok:
            logger.warning(
                "Token refresh: replacement warm process failed to spawn; "
                "keeping old (will need cycle on next message)"
            )
            # Best-effort: cycle the old one so it picks up the new token.
            if old.is_alive:
                try:
                    await old.cycle()
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "Token refresh fallback cycle also failed: %s", exc
                    )
            return

        # Atomic swap: new is alive, old is still alive — point at new, then
        # close old in the background so the operator doesn't wait on it.
        self._warm_claude = new_warm
        logger.info(
            "Token refresh: swapped warm process; closing old in background"
        )
        asyncio.create_task(self._close_old_warm(old))

    @staticmethod
    async def _close_old_warm(old_warm: WarmClaudeProcess) -> None:
        """Background-close helper for the displaced warm process.

        Sprint D8.2: scheduled via ``asyncio.create_task`` after the swap so
        the OAuth refresh callback returns immediately and the operator
        doesn't pay close-time on the foreground path.
        """
        try:
            await old_warm.close()
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Background close of old warm process failed: %s", exc
            )

    async def _provision_vapi_squad(self) -> None:
        """Provision the Bumba voice squad to VAPI's API at startup (D1.7b).

        Checks is_configured before making any network calls.
        Stores the provisioned receptionist ID in self._vapi_squad.
        """
        vapi: object | None = getattr(self, "_vapi", None)
        if vapi is None:
            return
        if not vapi.is_configured:  # type: ignore[attr-defined]
            logger.warning(
                "VAPI squad provisioning skipped: vapi_api_key not configured. "
                "Add vapi_api_key to .secrets to enable voice calls."
            )
            return

        try:
            from .voice.vapi_squad import build_bumba_squad

            squad = build_bumba_squad()
            config = self._config
            receptionist_config = {
                "name": "Bumba Receptionist",
                "model": {
                    "provider": "anthropic",
                    "model": model_defaults.DEFAULT_VOICE_MODEL,
                },
                "firstMessage": "Hi, Bumba here, how can I help?",
                "serverUrl": config.vapi_webhook_url,
            }
            receptionist_id = await vapi.create_assistant(receptionist_config)  # type: ignore[attr-defined]
            self._vapi_squad = {
                "squad_id": squad.squad_id,
                "receptionist_id": receptionist_id,
                "assistant_count": len(squad.assistants),
            }
            logger.info(
                "VAPI squad provisioned: squad_id=%s receptionist_id=%s assistants=%d",
                squad.squad_id,
                receptionist_id,
                len(squad.assistants),
            )
        except Exception as exc:
            logger.warning("VAPI squad provisioning failed (non-fatal): %s", exc)

    async def _verify_agent_directory(self) -> None:
        """Verify required files exist on startup. Logs issues."""
        if not self._config:
            return
        base = Path(self._config.claude_working_dir)  # agent root
        data_dir = Path(self._config.data_dir)
        issues = []
        for level, files in self._REQUIRED_FILES.items():
            for f in files:
                if f.startswith("data_dir:"):
                    path = data_dir / f[len("data_dir:"):]
                else:
                    path = base / f
                if not path.exists():
                    msg = f"[{level.upper()}] Missing: {f}"
                    issues.append(msg)
                    if level == "critical":
                        logger.error(msg)
                    else:
                        logger.warning(msg)
        if issues:
            logger.info("Directory verification: %d issue(s) found", len(issues))

    async def _generate_session_summary(self, chat_id: str, session_id: str) -> str | None:
        """Generate a brief summary of a session from its stored conversation history."""
        self._require("_memory")
        try:
            messages = await self._memory.get_session_messages(session_id, limit=20)
            if not messages:
                return None
            lines = []
            for m in messages:
                role = m["role"].capitalize()
                content = m["content"][:300].strip()
                if content:
                    lines.append(f"{role}: {content}")
            if not lines:
                return None
            msg_count = len(messages)
            summary = (
                f"Session expired ({msg_count} messages). Last exchange:\n"
                + "\n".join(lines[-6:])
            )
            return summary[:1000]
        except Exception as e:
            logger.warning("Session summary generation failed: %s", e)
            return None

    async def _extract_session_knowledge(self, session_id: str) -> None:
        """Extract and persist knowledge from an expiring session's messages."""
        if self._memory is None:
            return
        try:
            messages = await self._memory.get_session_messages(session_id, limit=20)
            stored = 0
            for i in range(len(messages) - 1):
                if messages[i].get("role") == "user" and messages[i + 1].get("role") == "assistant":
                    user_text = messages[i].get("content", "")
                    asst_text = messages[i + 1].get("content", "")
                    if user_text and asst_text:
                        count = await self._memory.extract_and_store_knowledge(user_text, asst_text)
                        stored += count
            if stored:
                logger.info("Extracted %d knowledge entries from session %s", stored, session_id[:8])
        except Exception as e:
            logger.warning("Session knowledge extraction failed: %s", e)

    async def _retry_unsent_responses(self) -> None:
        """At startup, resend any responses that failed to reach Discord."""
        self._require("_queue", "_discord")
        unsent = await self._queue.get_unsent_responses()
        if not unsent:
            return
        logger.info("Retrying %d unsent response(s) from previous run", len(unsent))
        for msg_id, chat_id, response_text in unsent:
            sent = await self._send_response(chat_id, response_text)
            if sent:
                await self._queue.complete(msg_id)
                logger.info("Resent queued response for message %d", msg_id)
            else:
                logger.warning("Failed to resend response for message %d — will retry next startup", msg_id)

    # ------------------------------------------------------------------
    # Sprint 02.07 — Cal.com booking event handler
    # ------------------------------------------------------------------

    def _on_calcom_booking_created(self, event) -> None:
        """Sync EventBus callback — schedules the async handler on the loop.

        EventBus._dispatch invokes callbacks synchronously, so we must NOT
        register a coroutine function directly (it would return an unawaited
        coroutine). Instead we define a sync entry point that schedules the
        real async work via ``asyncio.create_task``.

        Best-effort: never propagates exceptions — event handlers must not
        crash the bus.

        Sprint 02.11: extracts ``account`` from the event payload (set by
        ``calcom_webhook.py`` from organizer email domain) and threads it
        into ``handle_booking_event`` so multi-account bookings hit the
        correct Cal.com API key.
        """
        try:
            payload = event.payload if hasattr(event, "payload") else {}
            booking = payload.get("booking", {}) if isinstance(payload, dict) else {}
            booking_id = (
                payload.get("raw_uid")
                or booking.get("uid")
                or booking.get("id")
                or ""
            )
            if not booking_id:
                logger.warning(
                    "calcom.booking.created received with no booking id; payload keys=%s",
                    list(payload.keys()) if isinstance(payload, dict) else type(payload),
                )
                return

            account = payload.get("account") if isinstance(payload, dict) else None
            if account is not None:
                account = str(account).strip() or None

            asyncio.create_task(
                self._dispatch_meeting_prebrief(str(booking_id), account=account)
            )
        except Exception as exc:  # noqa: BLE001 — bus handlers must not crash
            logger.warning("meeting_prebrief.event_callback_failed: %s", exc)

    async def _dispatch_meeting_prebrief(
        self,
        booking_id: str,
        *,
        account: str | None = None,
    ) -> None:
        """Async helper: build a MeetingPrebriefService and run handle_booking_event.

        Construction mirrors what runner.py does for the polling path:
        ``data_dir`` from config, ``chat_id`` from service_channel_id (with
        fallback to operator_discord_id). EventBus callback is wired so the
        service's success/failure events still flow to the daily log.
        """
        try:
            from bridge.services.meeting_prebrief import MeetingPrebriefService

            data_dir = Path(self._config.data_dir) if self._config else Path(".")
            chat_id = ""
            if self._config is not None:
                chat_id = (
                    getattr(self._config, "service_channel_id", "")
                    or getattr(self._config, "operator_discord_id", "")
                )

            event_bus = self._autonomy.event_bus if self._autonomy else None
            event_callback = None
            if event_bus is not None:
                def _callback(event_type: str, payload_: dict) -> None:
                    payload_.setdefault("service", "meeting_prebrief")
                    try:
                        event_bus.publish(
                            event_type,
                            payload=payload_,
                            source="service:meeting_prebrief",
                        )
                    except Exception:
                        logger.debug("meeting_prebrief event publish failed", exc_info=True)
                event_callback = _callback

            svc = MeetingPrebriefService(
                data_dir=data_dir,
                chat_id=chat_id,
                event_callback=event_callback,
            )
            # handle_booking_event is sync — run in a thread so we don't block
            # the event loop on calcom_interface I/O or Claude subprocess.
            # Sprint 02.11: thread account through so the lookup hits the
            # correct Cal.com API key (personal vs business).
            result = await asyncio.to_thread(
                lambda: svc.handle_booking_event(booking_id, account=account)
            )
            logger.info(
                "meeting_prebrief.event_dispatched uid=%s account=%s ok=%s skip=%s items=%s",
                booking_id,
                account,
                getattr(result, "ok", "?"),
                getattr(result, "skip_reason", None),
                getattr(result, "work_items", "?"),
            )
        except Exception as exc:  # noqa: BLE001 — best-effort
            logger.warning(
                "meeting_prebrief.event_dispatch_failed uid=%s account=%s: %s",
                booking_id, account, exc,
            )

    # -- D1.4: Quality chain factory --

    def _build_quality_chain(self) -> object | None:
        """Instantiate and register QualityChain checkers when flag enabled.

        Returns the configured QualityChain, or None when quality_chain_enabled
        is False (dark-deploy default).  The dispatcher treats None as
        'chain disabled' and falls back to auto-complete behaviour.
        """
        if not getattr(self._config, "quality_chain_enabled", False):
            return None
        try:
            from .quality_chain import QualityChain, GateLevel
            from .quality_checkers import (
                LintChecker,
                TypecheckChecker,
                TestChecker,
                SecurityChecker,
                CodeReviewChecker,
                HumanApprovalChecker,
            )
            chain = QualityChain()
            chain.register(GateLevel.LINT, LintChecker(), strict=True)
            chain.register(GateLevel.TYPECHECK, TypecheckChecker(), strict=True)
            chain.register(GateLevel.TEST, TestChecker(), strict=True)
            chain.register(GateLevel.SECURITY, SecurityChecker(), strict=True)
            chain.register(GateLevel.CODE_REVIEW, CodeReviewChecker(), strict=False)
            chain.register(GateLevel.HUMAN_APPROVAL, HumanApprovalChecker(), strict=False)
            # 7th gate: branch-protection (D1.5) — conditional on its own flag
            if getattr(self._config, "branch_protection_enabled", False):
                try:
                    from .branch_protection import BranchProtectionChecker
                    chain.register(GateLevel.ARCHITECTURE, BranchProtectionChecker(), strict=True)
                except Exception as _bp_exc:
                    logger.warning("branch_protection checker unavailable: %s", _bp_exc)
            return chain
        except Exception as _qc_exc:
            logger.warning("QualityChain build failed (non-fatal): %s", _qc_exc)
            return None

    # -- S78: Startup sequence (13 steps) --

    async def start(self) -> None:
        """Full startup sequence per BRIDGE-ARCHITECTURE.md Section 2."""
        await self._initialize()
        self._require("_config", "_db", "_security", "_claude", "_discord", "_queue", "_pid_path")

        config = self._config

        # Step 1: Write PID
        self._pid_path.write_text(str(os.getpid()))

        # Step 1a: Initialize autonomy layer
        if self._autonomy:
            await self._autonomy.initialize()

            # Wire service completion events into the daily log
            if self._daily_log:
                def _on_service_success(event) -> None:
                    p = event.payload if hasattr(event, "payload") else event
                    svc = p.get("service", "unknown")
                    dur = int(p.get("duration_ms", 0))
                    self._daily_log.log_service_completion(svc, "OK", duration_ms=dur)

                def _on_service_failure(event) -> None:
                    p = event.payload if hasattr(event, "payload") else event
                    svc = p.get("service", "unknown")
                    reason = p.get("error") or p.get("last_error") or ""
                    self._daily_log.log_service_completion(svc, "FAIL", reason=str(reason))

                self._autonomy.event_bus.subscribe("schedule.triggered", _on_service_success)
                self._autonomy.event_bus.subscribe("failure.detected", _on_service_failure)

            # Sprint 02.07: subscribe MeetingPrebriefService to calcom.booking.created.
            # The producer (CalcomWebhookHandler in calcom_webhook.py) has been live
            # since Plan 04 spec; this is the consumer half. Belt-and-suspenders with
            # the 10-min polling fallback in com.bumba.agent-meeting-prebrief.plist.
            if self._autonomy.event_bus is not None:
                self._autonomy.event_bus.subscribe(
                    "calcom.booking.created",
                    self._on_calcom_booking_created,
                )

        # Step 1a-2: Recover tmux agents from previous run
        if self._tmux_agents:
            try:
                recovered = await self._tmux_agents.recover_from_restart()
                if recovered:
                    logger.info("Recovered %d tmux agents from restart", recovered)
            except Exception as e:
                logger.warning("Tmux agent recovery failed: %s", e)

        # Step 1b: Verify agent directory structure
        await self._verify_agent_directory()

        # Step 5: Check halt flag
        halt_reason = await asyncio.to_thread(self._security.check_halt_flag)
        if halt_reason:
            self._halted = True
            if self._commands:
                self._commands._halted = True
            logger.warning("Bridge starting in HALTED state: %s", halt_reason)

        # Step 6: Write crash timestamp
        await asyncio.to_thread(self._security.record_crash_timestamp)

        # Step 7: Check crash loop
        if await asyncio.to_thread(self._security.check_crash_loop):
            await asyncio.to_thread(self._security.set_halt, "crash_loop_detected")
            self._halted = True
            if self._commands:
                self._commands._halted = True
            logger.error("Crash loop detected — entering halted state")

        # Step 8: Cleanup stale claude.pid
        await self._claude.cleanup_stale()

        # Step 9: Reset orphaned 'processing' messages back to 'pending'
        orphaned = await self._queue.reset_orphaned()
        if orphaned:
            logger.info("Reset %d orphaned messages to pending", orphaned)

        # Step 9b: Retry any responses that failed to send (Discord was down)
        await self._retry_unsent_responses()

        # Step 10-11: Initialize and start Discord (retries until network is ready)
        await self._discord.start()

        # Auto-clear crash-loop halt after successful startup
        # (network is confirmed working — the crash loop was transient, e.g. post-reboot)
        if self._halted:
            halt_reason = await asyncio.to_thread(self._security.check_halt_flag) or ""
            if halt_reason == "crash_loop_detected":
                logger.info("Auto-clearing crash_loop halt after successful startup")
                await asyncio.to_thread(self._security.clear_halt)
                self._halted = False
                if self._commands:
                    self._commands._halted = False

        # Clean up old crash timestamps so they don't accumulate across reboots
        crash_log = Path(config.data_dir) / "crash.log"
        if crash_log.exists():
            await asyncio.to_thread(crash_log.write_text, "")

        # Step 11a: Start metrics collection
        self._metrics = MetricsCollector(data_dir=config.data_dir)
        await self._metrics.start_flush_loop()

        # Step 11b: Start health endpoint
        self._health_server = HealthServer(self)
        try:
            await self._health_server.start()
        except Exception as e:
            logger.warning("Health server failed to start: %s", e)

        # Step 11b-2: Start REST API server (Mission Control)
        api_enabled = getattr(config, "api_enabled", True)
        api_port = getattr(config, "api_port", 8200)
        api_host = getattr(config, "api_host", "127.0.0.1")
        api_token = getattr(config, "api_token", "")
        # P2.2 / audit C9 — CORS allowlist. Default empty tuple = no CORS
        # header on any response. Operators add origins via
        # ``[api] cors_allowed_origins`` in ``bridge.toml``.
        api_cors_allowed_origins = tuple(
            getattr(config, "api_cors_allowed_origins", ()) or ()
        )
        # P2.1 follow-up (#1626): two-knob opt-in for non-local bind. The
        # API server's start() validator refuses to bind to a non-local
        # interface unless this flag is True.
        api_allow_remote_bind = bool(
            getattr(config, "api_allow_remote_bind", False)
        )
        # P2.3 (#1578, audit C8): VAPI webhook auth. The APIServer's start()
        # fail-closed validator refuses to boot when voice_enabled=True and
        # vapi_webhook_secret is empty. When voice_enabled=False the secret
        # is optional (the webhook route still registers but the handler
        # rejects every call — defense in depth even when voice is meant
        # to be off).
        api_voice_enabled = bool(getattr(config, "voice_enabled", False))
        api_vapi_webhook_secret = str(getattr(config, "vapi_webhook_secret", "") or "")
        # Sprint audit-2026-05-16.B.04 (#2053, M-3): GitHub webhook secret is
        # required when the API server starts (the /api/webhooks/github
        # handler verifies HMAC signatures against this value). Passed
        # through to APIServer.__init__ where the fail-closed validator
        # in start() refuses to boot on empty.
        api_github_webhook_secret = str(
            getattr(config, "github_webhook_secret", "") or ""
        )
        if api_enabled:
            self._api_server = APIServer(
                self,
                host=api_host,
                port=api_port,
                api_token=api_token,
                cors_allowed_origins=api_cors_allowed_origins,
                allow_remote_bind=api_allow_remote_bind,
                voice_enabled=api_voice_enabled,
                vapi_webhook_secret=api_vapi_webhook_secret,
                github_webhook_secret=api_github_webhook_secret,
            )
            # Wire Zone 4 departments into API server for VAPI routes — must
            # happen BEFORE start() so the aiohttp router is not yet frozen.
            if self._departments:
                self._api_server.set_departments(self._departments)

            # Wire Zone 4 observability routes BEFORE start() so that
            # _register_routes() mounts them while the router is still mutable.
            # Previously this block ran after start(), which silently 404'd all
            # 14 /api/z4/* endpoints (fix for issue #624).
            if self._tool_tracker:
                z4_sessions_dir = Path(config.data_dir) / "z4-sessions"
                teams_dir = Path(__file__).parent.parent / "config" / "teams"
                expertise_dir = Path(__file__).parent.parent / "config" / "expertise"
                z4_routes = Zone4Routes(
                    sessions_dir=z4_sessions_dir,
                    teams_dir=teams_dir,
                    expertise_dir=expertise_dir,
                    tracker=self._tool_tracker,
                    attributor=self._cost_attributor,
                    aggregator=self._metrics_aggregator,
                )
                self._api_server.set_zone4_routes(z4_routes)
                logger.info("Zone4Routes queued for mounting on API server")

            # Sprint 23: Phase 5 directive lifecycle dashboard routes.
            # Always wired (no flag) — the routes are read-only inspection
            # over substrate that's already shipping.
            try:
                from bridge.api.directives_routes import DirectiveRoutes
                directive_routes = DirectiveRoutes(db=self._db)
                self._api_server.set_directive_routes(directive_routes)
                logger.info("DirectiveRoutes queued for mounting on API server")
            except Exception as e:  # noqa: BLE001
                logger.warning("DirectiveRoutes wiring failed: %s", e)

            # D1.7b: Wire VAPIClient into API server before start() so the
            # webhook route can dispatch to it from the first request.
            if config.voice_enabled and hasattr(self, "_vapi"):
                self._api_server.set_vapi_client(self._vapi)
                logger.info("VAPIClient wired into API server")

            # P6.4 (#1599) — span the API server start so operators can
            # baseline the aiohttp bind + middleware install latency.
            _api_span = (
                self._tracer.start_span(
                    "startup.api_start",
                    attributes={"host": api_host, "port": api_port},
                )
                if self._tracer is not None
                else None
            )
            try:
                await self._api_server.start()
                if _api_span is not None:
                    _api_span.attributes["started"] = True
            except Exception as e:
                logger.warning("API server failed to start: %s", e)
                if _api_span is not None:
                    _api_span.status = "error"
                    _api_span.add_event(
                        "exception",
                        {
                            "exception.type": type(e).__name__,
                            "exception.message": str(e),
                        },
                    )
            finally:
                if _api_span is not None:
                    self._tracer.end_span(_api_span)

        # D1.7b: Provision VAPI squad after API server is up (async network call).
        if config.voice_enabled and hasattr(self, "_vapi"):
            await self._provision_vapi_squad()

        # Step 11c: Start dead man's switch heartbeat
        if self._health_server:
            hc_url = getattr(config, "healthcheck_bridge_url", None)
            self._heartbeat_pinger = HeartbeatPinger(hc_url, self._health_server)
            await self._heartbeat_pinger.start()

        # Step 12: Start heartbeat writer
        self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())

        # Run initial decay sweep and start daily timer
        if self._memory:
            try:
                result = await self._memory.run_decay_sweep()
                logger.info("Startup decay sweep: %s", result)
            except Exception as e:
                logger.warning("Startup decay sweep failed: %s", e)
            self._decay_task = asyncio.create_task(self._decay_loop())
            self._backup_task = asyncio.create_task(self._backup_loop())
            self._consolidation_task = asyncio.create_task(self._consolidation_loop())

        # Issue #832 — source↔runtime drift check (6h cadence).
        # Self-gates on canonical root existence, so this is a no-op in dev.
        self._drift_task = asyncio.create_task(self._drift_loop())

        # Sprint D8.4 — proactive warm-process health monitor. Provider closure
        # picks up swaps from D8.2 token-refresh double-buffer pattern.
        self._warm_health_task = asyncio.create_task(
            background_loops.warm_claude_health_loop(
                self._shutdown_event,
                lambda: self._warm_claude,
            ),
            name="warm-claude-health-loop",
        )

        # Z4-S30 #1391 — chief-session idle-timeout reaper. Only spawned
        # when the chief dispatcher stack initialized successfully (store
        # present). The reaper is intentionally store-only — it does not
        # touch the dispatcher itself, so a dispatcher init failure that
        # leaves the store wired is still safe to reap against.
        if (
            config.chief_dispatcher_enabled
            and self._chief_session_store is not None
        ):
            reaper_event_bus = (
                self._autonomy.event_bus if self._autonomy else None
            )
            self._chief_session_reaper_task = asyncio.create_task(
                background_loops.chief_session_reaper_loop(
                    self._shutdown_event,
                    chief_session_store=self._chief_session_store,
                    idle_timeout_seconds=(
                        config.chief_dispatcher_idle_timeout_seconds
                    ),
                    event_bus=reaper_event_bus,
                    # zone4-warmth.D.01 (#2299): wire the DepartmentRegistry
                    # so the reaper honors per-team
                    # ``constraints.warm_idle_timeout_seconds`` overrides.
                    # None-tolerant when the teams package failed to
                    # initialize — the reaper falls back to the global
                    # default for every session.
                    department_registry=self._departments,
                ),
                name="chief-session-reaper-loop",
            )

        # Sprint E2.3 — tail hooks JSONL and re-publish as hook.* EventBus events.
        if getattr(self, "_event_bus", None) is not None:
            from bridge.hooks_telemetry_subscriber import HooksTelemetrySubscriber
            self._hooks_telemetry_subscriber = HooksTelemetrySubscriber(bus=self._event_bus)
            await self._hooks_telemetry_subscriber.start()

        # Start weekly reflection loop
        if self._reflection_store:
            self._reflection_task = asyncio.create_task(self._reflection_loop())

        # Sprint 09.13 — start the tick loop when TickManager is constructed.
        # Construction is gated by config.proactive_enabled in _initialize();
        # the actual `<tick>` injection still requires /proactive on at
        # runtime (TickManager.wait_for_tick returns False when disabled).
        if self._tick_manager is not None:
            self._tick_loop_task = asyncio.create_task(self._tick_manager.run())
            logger.info(
                "TickManager background loop started (use /proactive on to "
                "begin ticking)"
            )

        # Start token refresher
        if self._token_refresher:
            self._token_refresher.start()

        # Spawn the persistent warm Claude process (sonnet default)
        # P6.4 (#1599) — wrap warm-process spawn in a span so the operator
        # can see whether warm MCP narrowing improved cold-start cost.
        # Span end_time captures the FULL spawn cycle including the 5s
        # backoff + retry branch when the first attempt fails.
        if self._warm_claude:
            _spawn_span = (
                self._tracer.start_span(
                    "startup.warm_process_spawn",
                    attributes={"model": "sonnet"},
                )
                if self._tracer is not None
                else None
            )
            ok = await self._warm_claude.spawn(
                working_dir=config.claude_working_dir,
                model="sonnet",
            )
            if not ok:
                logger.warning("Warm Claude spawn failed — retrying once after 5s")
                await asyncio.sleep(5)
                ok = await self._warm_claude.spawn(
                    working_dir=config.claude_working_dir,
                    model="sonnet",
                )
            if _spawn_span is not None:
                _spawn_span.attributes["spawned"] = bool(ok)
                if not ok:
                    _spawn_span.status = "error"
                self._tracer.end_span(_spawn_span)
            if ok:
                logger.info("Warm Claude process spawned (sonnet)")
            else:
                logger.warning("Warm Claude process failed to spawn — falling back to one-shot")

        # Step 12a: Start webhook deliverer (Sprint 14)
        if self._webhook_deliverer:
            self._webhook_deliverer.start()
            logger.info("SerialEventDeliverer started (max_queue=%d, timeout=%.1fs)",
                       self._webhook_deliverer._max_queue, self._webhook_deliverer._timeout_sec)

        # Sprint 07.04: register this bridge in the peer registry. The
        # manager's start() registers the PeerRecord and spawns a heartbeat
        # task; both stay no-ops when the flag is off (manager is None).
        if self._peer_registration is not None:
            try:
                await self._peer_registration.start()
                logger.info("Peer registration started")
            except Exception as e:
                logger.warning("Peer registration start failed (non-fatal): %s", e)

        # Step 12b: Kernel integrity check (reads + hashes files — offload to thread)
        mismatches = await asyncio.to_thread(self._security.verify_kernel_hashes)
        if mismatches:
            if mismatches != ["baseline file missing"]:
                logger.error("Kernel integrity check FAILED: %s", mismatches)
                await self._security.log_event(
                    "kernel_integrity_failure",
                    details={"mismatches": mismatches},
                )
                await asyncio.to_thread(self._security.set_halt, "kernel_integrity_failure")
                await self._discord.send_message(
                    config.operator_discord_id,
                    "[ALERT] Kernel integrity mismatch detected. Bridge halted. "
                    "Restart after verifying baseline.\n"
                    + "\n".join(f"  {m}" for m in mismatches),
                )
            else:
                logger.info("No kernel baseline found — skipping integrity check")
        else:
            logger.info("Kernel integrity check passed")

        # Step 13: Log startup audit event and send notification
        await self._security.log_event(
            "bridge_startup",
            details={"pid": os.getpid(), "halted": self._halted},
        )

        # Sprint 01.08b: bridge_startup HookDispatcher.dispatch() removed
        # (audit found 0 production hooks; see plan-01-hooks-audit.md)

        # Send startup notification
        status = " [HALTED]" if self._halted else ""
        await self._discord.send_message(
            config.operator_discord_id,
            f"Agent online{status}. Uptime reset.",
        )

        # Install signal handlers
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, self._signal_handler)

        # Start message processing loop
        self._processing_task = asyncio.create_task(self._process_messages())

        # Wait for shutdown
        await self._shutdown_event.wait()
        await self.stop()

    def _signal_handler(self) -> None:
        """Handle SIGTERM/SIGINT by setting shutdown event."""
        logger.info("Received shutdown signal")
        self._shutdown_event.set()

    async def _heartbeat_loop(self) -> None:
        """Delegate to background_loops.heartbeat_loop."""
        self._require("_config")
        await background_loops.heartbeat_loop(
            self._shutdown_event,
            self._config,
            autonomy=self._autonomy,
            discord=self._discord,
            runbook_engine=self._runbook_engine,
            tmux_agents=self._tmux_agents,
            mcp_monitor=self._mcp_monitor,
            security=self._security,
        )

    async def _decay_loop(self) -> None:
        """Delegate to background_loops.decay_loop."""
        await background_loops.decay_loop(self._shutdown_event, self._memory)

    async def _backup_loop(self) -> None:
        """Delegate to background_loops.backup_loop."""
        await background_loops.backup_loop(self._shutdown_event, self._db, self._config)

    async def _reflection_loop(self) -> None:
        """Delegate to background_loops.reflection_loop with live data sources."""
        event_bus = self._autonomy.event_bus if self._autonomy else None
        await background_loops.reflection_loop(
            self._shutdown_event,
            self._reflection_store,
            cost_tracker=self._cost_tracker,
            routing_feedback=self._routing_feedback,
            few_shot_store=self._few_shot,
            event_bus=event_bus,
            memory=self._memory,
        )

    async def _consolidation_loop(self) -> None:
        """Delegate to background_loops.consolidation_loop."""
        await background_loops.consolidation_loop(self._shutdown_event, self._db, self._memory)

    async def _drift_loop(self) -> None:
        """Delegate to background_loops.drift_loop (issue #832)."""
        await background_loops.drift_loop(
            self._shutdown_event,
            discord=self._discord,
            config=self._config,
        )

    # -- S79: Message processing loop --

    async def _process_messages(self) -> None:
        """Core loop: dequeue -> resolve session -> build context -> invoke Claude -> store -> send."""
        self._require("_config", "_queue", "_memory", "_session_mgr", "_claude", "_discord", "_security", "_commands")

        while not self._shutdown_event.is_set():
            # Don't process messages if halted
            if self._halted:
                try:
                    await asyncio.wait_for(
                        self._shutdown_event.wait(), timeout=5.0
                    )
                    return
                except asyncio.TimeoutError:
                    continue

            # Check for HITL tasks with pending responses
            if self._task_queue:
                try:
                    task = await self._task_queue.get_next_pending_with_response()
                    if task and task.claude_session_id and self._claude and self._discord:
                        result = await self._claude.invoke(
                            message=f"The operator chose: {task.user_response}",
                            session_id=task.claude_session_id,
                        )
                        if result.is_error:
                            await self._task_queue.fail(task.id, result.error_type)
                        else:
                            await self._task_queue.complete(task.id, result.response_text)
                            await self._discord.send_message(task.chat_id, result.response_text)
                except Exception as e:
                    logger.warning("HITL task resume failed: %s", e)

            # Deliver any pending service messages (check-in, briefing)
            await self._deliver_service_messages()

            # Dequeue next message
            msg = await self._queue.dequeue()
            if msg is None:
                # No messages — wait briefly before checking again
                try:
                    await asyncio.wait_for(
                        self._shutdown_event.wait(), timeout=2.0
                    )
                    return
                except asyncio.TimeoutError:
                    continue

            # Process the message
            await self._process_single_message(msg)

    async def _process_single_message(self, msg: QueuedMessage) -> None:
        """Process one dequeued message through the full pipeline.

        Delegates to five named stages that each receive (and return) an
        immutable ``MessageContext``.  The top-level orchestrator owns the
        try/except/finally so that error handling and cleanup are never
        accidentally skipped by an early return inside a stage.
        """
        self._require("_config", "_queue", "_memory", "_session_mgr", "_claude", "_discord", "_security", "_commands")

        # Build initial context
        correlation_id: str | None = None
        if self._autonomy:
            correlation_id = self._autonomy.event_bus.start_chain()
            self._autonomy.event_bus.publish(
                "message.received",
                payload={"chat_id": msg.chat_id, "text_length": len(msg.text)},
                source="bridge",
                correlation_id=correlation_id,
            )

        ctx = MessageContext(
            msg=msg,
            correlation_id=correlation_id,
            msg_start=time.monotonic(),
        )

        # Log incoming message (Phase 1, Sprint 1)
        if self._daily_log:
            self._daily_log.append(
                f"User message: {msg.text[:100]}{'...' if len(msg.text) > 100 else ''}",
                category="message",
            )

        # Start typing indicator
        self._discord._start_typing(msg.chat_id)
        latency_watchdog = self._start_response_latency_watchdog(msg)

        # Sprint 07.11 — bind correlation IDs for the duration of this
        # handler. message_id is the queue row id (always available); the
        # session_id is filled in after Stage 2 resolves it. clear_message_context
        # is paired in the finally block so context never leaks to the next
        # message even if an exception unwinds through the pipeline.
        log_format.set_message_context(
            session_id="",
            message_id=str(msg.id),
        )

        try:
            # Stage 1: Pre-flight checks (guardrails, budget, circuit breaker, rate limiter)
            ctx = await self._preflight_checks(ctx)
            if ctx.result is not None:
                # A preflight check short-circuited the pipeline (early return).
                # result is used as a sentinel — the check already sent the
                # appropriate Discord message and updated queue state.
                return

            # Stage 2: Invoke Claude (session resolution, context assembly, subprocess)
            ctx = await self._invoke_claude(ctx)
            # Refresh context with the resolved session_id so subsequent
            # log records (post-process, deliver, telemetry) carry both IDs.
            log_format.set_message_context(
                session_id=ctx.session_id or "",
                message_id=str(msg.id),
            )
            result = ctx.result
            if result.is_error:
                if self._lifecycle:
                    self._lifecycle.transition(LifecycleState.FAILED, result.error_type)
                if ctx.claude_breaker:
                    ctx.claude_breaker.record_failure(Exception(result.error_type))
                if self._autonomy:
                    self._autonomy.trust.record_event(
                        "routing", "failure", reason=result.error_type
                    )
                await self._handle_processing_error(msg, result, ctx.session_id)
                return

            # Lifecycle: ACTIVE -> COMPLETING
            if self._lifecycle:
                self._lifecycle.transition(LifecycleState.COMPLETING)

            # Stage 3: Post-process (storage, knowledge extraction, HITL, tags)
            ctx = await self._post_process(ctx, result)

            # Stage 4: Deliver response (formatting, sending, audit logging).
            # Returns the evaluator verdict ("pass"/"flag"/"fail"/None) so
            # Stage 5 can quality-gate few-shot ingest (Sprint 05.08).
            evaluator_verdict = await self._deliver_response(ctx, result)

            # Stage 5: Record telemetry (metrics, cost, anomaly checks)
            await self._record_telemetry(ctx, result, evaluator_verdict=evaluator_verdict)

        except Exception as e:
            logger.error("Unexpected error processing message %d: %s", msg.id, e)
            await self._queue.fail(msg.id, str(e))
            self._commands.record_error()
            if self._metrics:
                self._metrics.increment("errors_total")
            if self._autonomy:
                self._autonomy.event_bus.publish(
                    "failure.detected",
                    payload={"chat_id": msg.chat_id, "error": str(e)[:200]},
                    source="bridge",
                    correlation_id=ctx.correlation_id,
                )
                if ctx.correlation_id:
                    self._autonomy.event_bus.fail_chain(ctx.correlation_id)
            await self._security.log_event(
                "processing_error",
                details={"error": str(e), "message_id": msg.id},
                chat_id=msg.chat_id,
            )
        finally:
            if latency_watchdog is not None:
                latency_watchdog.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await latency_watchdog
            self._discord._stop_typing(msg.chat_id)
            # Clean up temp image files embedded as [image: /path/bumba_img_...] in msg.text
            for _img_path in _re.findall(r'\[image: ([^\]]*bumba_img_[^\]]+)\]', msg.text):
                try:
                    Path(_img_path).unlink(missing_ok=True)
                except OSError:
                    pass
            # Sprint 07.11 — clear correlation IDs at end of every message
            # so logs emitted between messages (idle loop, background tasks)
            # don't carry stale session/message identifiers.
            log_format.clear_message_context()

    # -- Pipeline stages (independently testable) --

    async def _preflight_checks(self, ctx: MessageContext) -> MessageContext:
        """Stage 1: Guardrails, budget, circuit breaker, rate limiter.

        Returns a new ``MessageContext``.  If a check fails and the message
        should be dropped, ``ctx.result`` is set to a sentinel (True) so the
        orchestrator knows to short-circuit.
        """
        msg = ctx.msg

        # Guardrail input check
        if self._autonomy:
            from .guardrails import ACTION_BLOCK
            input_check = self._autonomy.guardrails.check_input(msg.text)
            if not input_check.passed:
                self._autonomy.event_bus.publish(
                    "guardrail.triggered",
                    payload={"direction": "input", "action": input_check.action, "details": input_check.details},
                    source="guardrails",
                )
                if input_check.action == ACTION_BLOCK:
                    await self._queue.fail(msg.id, "guardrail_blocked")
                    await self._discord.send_message(
                        msg.chat_id,
                        "Message blocked by safety guardrails.",
                    )
                    return MessageContext(
                        msg=msg,
                        correlation_id=ctx.correlation_id,
                        msg_start=ctx.msg_start,
                        result=True,  # sentinel: pipeline should stop
                    )

        # Budget check
        if self._budget:
            budget = await self._budget.check()
            if not budget["allowed"]:
                await self._queue.fail(msg.id, "budget_exceeded")
                await self._discord.send_message(
                    msg.chat_id,
                    f"Daily budget exceeded (${budget['spent_today']:.2f} / ${budget['daily_limit']:.2f}). "
                    "Message dropped.",
                )
                return MessageContext(
                    msg=msg,
                    correlation_id=ctx.correlation_id,
                    msg_start=ctx.msg_start,
                    result=True,  # sentinel: pipeline should stop
                )
            alert_msg = await self._budget.should_alert()
            if alert_msg:
                await self._discord.send_alert(alert_msg)

        # Circuit breaker
        claude_breaker = self._breakers.get("claude") if self._breakers else None
        if claude_breaker and claude_breaker.get_state().state == CircuitState.OPEN:
            await self._queue.retry(msg.id)
            logger.warning("Claude circuit open — deferring message %d", msg.id)
            return MessageContext(
                msg=msg,
                correlation_id=ctx.correlation_id,
                msg_start=ctx.msg_start,
                claude_breaker=claude_breaker,
                result=True,  # sentinel: pipeline should stop
            )

        # Rate limiter
        if self._rate_limiter:
            allowed, wait = self._rate_limiter.check()
            if not allowed:
                await self._rate_limiter.wait_and_consume()

        # All preflight checks passed — return updated context with breaker
        return MessageContext(
            msg=msg,
            correlation_id=ctx.correlation_id,
            msg_start=ctx.msg_start,
            claude_breaker=claude_breaker,
        )

    def _decide_use_warm(
        self,
        *,
        model: str,
        intent: str | None,
        has_tools: bool,
        is_workorder: bool,
    ) -> bool:
        """Narrow seam for the warm-vs-one-shot policy decision (Sprint P6.1).

        Delegates to ``bridge.warm_policy.should_use_warm_path``. This thin
        method exists so the policy module can be swapped or stubbed in tests
        without touching ``invocation_pipeline.py``. Per Sprint P1.3 (#1571),
        callers MUST still verify warm-process availability (``_warm_claude
        is not None and _warm_claude.is_alive``) before consulting this seam —
        availability is an orthogonal precondition.
        """
        from .warm_policy import should_use_warm_path
        return should_use_warm_path(
            model=model,
            intent=intent,
            has_tools=has_tools,
            is_workorder=is_workorder,
        )

    async def _invoke_claude(self, ctx: MessageContext) -> MessageContext:
        """Stage 2 delegate — see ``invocation_pipeline.invoke_claude_pipeline``.

        Sprint P6.1 (#1591) extracted the 440-LOC body into
        ``bridge.invocation_pipeline`` to make the pipeline independently
        readable and testable. Public behavior is unchanged.
        """
        from .invocation_pipeline import invoke_claude_pipeline
        return await invoke_claude_pipeline(self, ctx)

    async def _post_process(self, ctx: MessageContext, result: ClaudeResult) -> MessageContext:
        """Stage 3: Storage, knowledge extraction, HITL detection, tag processing.

        Returns a new ``MessageContext`` with ``hitl_detected`` set.
        """
        msg = ctx.msg
        session_id = ctx.session_id
        resume_id = ctx.resume_id

        # Update session with Claude's real session_id
        if result.session_id:
            if resume_id is None:
                # First successful invocation: store Claude's session_id
                await self._session_mgr.set_claude_session_id(
                    msg.chat_id, result.session_id
                )
            await self._session_mgr.update_session(
                result.session_id, cost_usd=result.cost_usd
            )

        # Store user message
        await self._memory.store_message(
            session_id=result.session_id or session_id,
            chat_id=msg.chat_id,
            role="user",
            content=msg.text,
            platform_message_id=msg.platform_message_id,
        )

        # Guardrail output check — run before storing assistant message so we
        # can persist redacted_text instead of raw response (Sprint 06.05)
        _assistant_content = result.response_text
        if self._autonomy and result.response_text:
            output_check = self._autonomy.guardrails.check_output(result.response_text)
            if output_check.triggered_tripwires:
                self._autonomy.event_bus.publish(
                    "guardrail.triggered",
                    payload={"direction": "output", "action": output_check.action, "details": output_check.details},
                    source="guardrails",
                )
            # Use redacted_text for memory storage when guardrails stripped tokens
            if output_check.redacted_text:
                _assistant_content = output_check.redacted_text

        # Store assistant message (redacted if guardrails stripped any tokens)
        await self._memory.store_message(
            session_id=result.session_id or session_id,
            chat_id=msg.chat_id,
            role="assistant",
            content=_assistant_content,
            tools_used=",".join(result.tools_used) if result.tools_used else None,
            cost_usd=result.cost_usd,
            duration_ms=result.duration_ms,
        )

        # Process structured tags from Claude's response
        try:
            tags = parse_tags(result.response_text)
            if tags:
                processed = await self._memory.process_tags(tags)
                if processed:
                    logger.info("Processed %d structured tag(s)", processed)
                result.response_text = strip_tags(result.response_text)
        except Exception as e:
            logger.warning("Tag processing failed: %s", e)

        # Extract and store knowledge from the exchange (Option B fallback)
        try:
            extracted = await self._memory.extract_and_store_knowledge(
                msg.text, result.response_text
            )
            if extracted:
                logger.info("Auto-extracted %d knowledge entry(ies)", extracted)
        except Exception as e:
            logger.warning("Knowledge extraction failed: %s", e)

        # Check for HITL question with options
        hitl_detected = False
        if self._task_queue:
            try:
                detection = detect_question_with_options(result.response_text)
                if detection:
                    question, options = detection
                    task_id = await self._task_queue.create(
                        chat_id=msg.chat_id,
                        session_id=session_id,
                        claude_session_id=result.session_id,
                        pending_question=question,
                        pending_options=options,
                    )
                    logger.info("HITL task %d created with %d options", task_id, len(options))
                    hitl_detected = True
            except Exception as e:
                logger.warning("HITL detection failed: %s", e)

        # Record cost and update circuit breaker / rate limiter
        if self._budget:
            await self._budget.record(
                result.cost_usd,
                session_id=result.session_id or session_id,
                chat_id=msg.chat_id,
            )
        if ctx.claude_breaker:
            ctx.claude_breaker.record_success()
        if self._rate_limiter:
            self._rate_limiter.on_success()
        if self._autonomy:
            self._autonomy.trust.record_event("routing", "success")

        # Lifecycle: COMPLETING -> COMPLETED
        if self._lifecycle:
            self._lifecycle.transition(LifecycleState.COMPLETED)

        # Suggested commands footer (only for complex multi-step tasks)
        if self._suggester and result.num_turns >= 5:
            try:
                suggestions = self._suggester.suggest(
                    msg.text,
                    tools_used=result.tools_used,
                    num_turns=result.num_turns,
                )
                if suggestions:
                    suggestion_text = "\n\n> Suggested: " + ", ".join(
                        f"`/{s}`" for s in suggestions
                    )
                    result.response_text += suggestion_text
            except Exception as e:
                logger.warning("Command suggestion failed: %s", e)

        # Verification tier (Z3.11) — advisory only, never blocks delivery
        if self._config and self._config.verification_enabled and result is not None and not result.is_error:
            try:
                from .verification import VerificationLayer, VerificationTier
                verifier = VerificationLayer()
                verification_dict = {
                    "result": result.response_text,
                    "confidence": 0.8,
                    "metadata": {
                        "cost": getattr(result, "cost_usd", 0),
                        "turns": getattr(result, "num_turns", 1),
                    },
                }
                vr = verifier.verify(verification_dict, tier=VerificationTier.STANDARD)
                if not vr.passed:
                    logger.warning(
                        "Verification warnings (%d) for message: %s",
                        len(vr.issues),
                        vr.issues,
                    )
                    if result.response_text and vr.issues:
                        result.response_text = (
                            f"[Verification warnings: {len(vr.issues)}] {result.response_text}"
                        )
            except Exception as e:
                logger.debug("Verification skipped: %s", e)

        # Complete queue entry
        await self._queue.complete(msg.id)

        return MessageContext(
            msg=msg,
            correlation_id=ctx.correlation_id,
            msg_start=ctx.msg_start,
            claude_breaker=ctx.claude_breaker,
            session_id=session_id,
            resume_id=resume_id,
            result=result,
            hitl_detected=hitl_detected,
            budget_pressure=ctx.budget_pressure,
        )

    async def _deliver_response(self, ctx: MessageContext, result: ClaudeResult) -> str | None:
        """Stage 4: Formatting, sending response, audit logging.

        Returns the evaluator verdict (``"pass"``, ``"flag"``, ``"fail"``) when
        the response evaluator ran, or ``None`` when it was skipped (no
        evaluator wired, empty response, or evaluation raised). The caller
        threads this verdict into Stage 5 (_record_telemetry) so few-shot
        ingest can gate on quality (Sprint 05.08).
        """
        msg = ctx.msg
        session_id = ctx.session_id

        # Evaluate response quality (async, non-blocking on failure)
        # Issue #1565 — operator opt-out: when [evaluator] enabled = false in
        # bridge.toml, skip the evaluator call entirely (no model call, no
        # event, no routing-feedback signal). Default True preserves current
        # behaviour.
        evaluator_verdict: str | None = None
        _evaluator_enabled = bool(
            self._config is None
            or getattr(self._config, "response_evaluator_enabled", True)
        )
        if self._evaluator and result.response_text and _evaluator_enabled:
            try:
                _few_shot_was_active = bool(
                    self._config and getattr(self._config, "few_shot_enabled", True)
                )
                eval_result = await self._evaluator.evaluate(
                    request=msg.text or "",
                    response=result.response_text,
                    few_shot_active=_few_shot_was_active,  # A/B analysis (#23)
                )
                evaluator_verdict = eval_result.verdict
                if eval_result.verdict == "fail":
                    logger.warning(
                        "Evaluator flagged response: overall=%.1f, issues=%s",
                        eval_result.overall, eval_result.issues,
                    )
                    # Sprint 05.10 — surface fail verdicts on the EventBus so
                    # operators / Mission Control can react. Also record a
                    # failure signal on routing_feedback so the model_router
                    # can auto-escalate on repeated failures. Both calls are
                    # wrapped in try/except — neither must block delivery.
                    _model_used = getattr(result, "model", None) or "sonnet"
                    if self._autonomy is not None:
                        try:
                            self._autonomy.event_bus.publish(
                                "response.evaluator.fail",
                                payload={
                                    "session_id": session_id,
                                    "verdict": eval_result.verdict,
                                    "evaluator_score": {
                                        "overall": eval_result.overall,
                                        "completeness": eval_result.completeness,
                                        "correctness": eval_result.correctness,
                                        "actionability": eval_result.actionability,
                                        "safety": eval_result.safety,
                                        "issues": list(eval_result.issues),
                                    },
                                    "response_prefix": (result.response_text or "")[:200],
                                    "timestamp": time.time(),
                                    "model": _model_used,
                                },
                                source="bridge",
                                correlation_id=ctx.correlation_id,
                            )
                        except Exception:
                            logger.exception(
                                "response.evaluator.fail publish failed (non-fatal)"
                            )
                    if self._routing_feedback is not None:
                        try:
                            _task_type = (
                                classify_task_type(msg.text or "", [])
                                if self._few_shot
                                else "general"
                            )
                            self._routing_feedback.record_model_use(
                                model_tier=_model_used,
                                task_type=_task_type,
                                success=False,
                            )
                        except Exception:
                            logger.exception(
                                "routing_feedback.record_model_use(fail) failed (non-fatal)"
                            )
            except Exception as e:
                logger.debug("Evaluation skipped: %s", e)

        # Send response (text always)
        sent = await self._send_response(msg.chat_id, result.response_text, msg.platform_message_id)
        if not sent:
            await self._queue.mark_send_failed(msg.id, result.response_text)

        # D7.9 #1421 (slice 2) — auto-ACK the inbox after delivering a BLOCK
        # message. The slice-1 mid-stream interrupt returns a response whose
        # text starts with "TOOL CALL BLOCKED"; once the bridge has shown
        # that to Discord, the inbox's job is done — we ACK on the agent's
        # behalf so the next dequeue (the operator's actual message, which
        # is already in the queue) processes normally without re-blocking.
        # The agent does NOT need to emit [ACK:msg_id] markers in this
        # slice; the bridge handles the contract.
        if (
            sent
            and self._operator_inbox is not None
            and result.response_text
            and "TOOL CALL BLOCKED" in result.response_text
        ):
            try:
                pending = await self._operator_inbox.pending()
                for pmsg in pending:
                    await self._operator_inbox.acknowledge(pmsg.id)
                if pending:
                    logger.info(
                        "operator_inbox: auto-acked %d pending message(s) "
                        "after BLOCK delivery (D7.9 slice 2)",
                        len(pending),
                    )
            except Exception:
                logger.exception(
                    "operator_inbox: auto-ack after BLOCK delivery failed "
                    "(non-fatal — next dequeue may re-block until manual ack)"
                )

        # Log response delivery (Phase 1, Sprint 1)
        if self._daily_log:
            preview = result.response_text[:100] if result.response_text else "(empty)"
            status = "✓ sent" if sent else "✗ send_failed"
            self._daily_log.append(
                f"Response ({status}): {preview}{'...' if len(result.response_text or '') > 100 else ''}",
                category="response",
            )

        # Log audit
        await self._security.log_event(
            "message_processed",
            details={
                "cost_usd": result.cost_usd,
                "num_turns": result.num_turns,
                "tools_used": result.tools_used,
                "duration_ms": result.duration_ms,
            },
            session_id=result.session_id or session_id,
            chat_id=msg.chat_id,
        )

        # Record stats
        self._commands.record_message()

        # Publish message.processed event
        if self._autonomy:
            self._autonomy.event_bus.publish(
                "message.processed",
                payload={
                    "chat_id": msg.chat_id,
                    "cost_usd": result.cost_usd,
                    "duration_ms": result.duration_ms,
                },
                source="bridge",
                correlation_id=ctx.correlation_id,
            )
            if ctx.correlation_id:
                self._autonomy.event_bus.complete_chain(ctx.correlation_id)

        return evaluator_verdict

    async def _record_telemetry(
        self,
        ctx: MessageContext,
        result: ClaudeResult,
        evaluator_verdict: str | None = None,
    ) -> None:
        """Stage 5: Metrics, cost tracking, anomaly checks, session health.

        ``evaluator_verdict`` (Sprint 05.08) is threaded in from
        :meth:`_deliver_response` and gates few-shot ingest:
        - ``"fail"``  -> skip ingest (low-quality output protects future recall)
        - ``"flag"``  -> ingest at quality 0.5 (de-prioritised in eviction)
        - ``"pass"``  -> ingest at quality 1.0 (current/default behaviour)
        - ``None``    -> ingest at quality 0.75 (cautious default when no eval)
        Unknown verdicts are treated as ``None`` and logged at WARNING.
        """
        msg = ctx.msg
        session_id = ctx.session_id

        # Record metrics
        if self._metrics:
            elapsed = time.monotonic() - ctx.msg_start
            self._metrics.observe("message_response_time", elapsed)
            self._metrics.observe("claude_invocation_latency", result.duration_ms / 1000.0)
            self._metrics.increment("messages_total")
            self._metrics.increment("claude_invocations_success")

        # Sprint 01.08b: message_processed HookDispatcher.dispatch() removed
        # (audit found 0 production hooks; see plan-01-hooks-audit.md)

        # Store successful interaction as few-shot example (Patch D),
        # gated by evaluator verdict (Sprint 05.08).
        if self._few_shot and ctx.msg.text and result.response_text:
            # Map verdict -> (quality, metric_suffix). Default to cautious 0.75
            # so an unknown verdict or a try/except fall-through still records
            # something useful rather than silently dropping the row or
            # lying at quality 1.0.
            try:
                if evaluator_verdict == "fail":
                    logger.debug(
                        "few_shot.ingest_skipped: verdict=fail session=%s",
                        session_id,
                    )
                    if self._metrics:
                        self._metrics.increment("few_shot.ingest_skipped_fail")
                    _ingest_quality = None  # sentinel: skip
                elif evaluator_verdict == "flag":
                    _ingest_quality = 0.5
                    if self._metrics:
                        self._metrics.increment("few_shot.ingest_quality_flag")
                elif evaluator_verdict == "pass":
                    _ingest_quality = 1.0
                    if self._metrics:
                        self._metrics.increment("few_shot.ingest_quality_pass")
                elif evaluator_verdict is None:
                    _ingest_quality = 0.75
                    if self._metrics:
                        self._metrics.increment("few_shot.ingest_quality_no_eval")
                else:
                    logger.warning(
                        "few_shot.ingest unknown verdict=%r; falling back to no_eval quality",
                        evaluator_verdict,
                    )
                    _ingest_quality = 0.75
                    if self._metrics:
                        self._metrics.increment("few_shot.ingest_quality_no_eval")
            except Exception as _vge:
                # Never let verdict-handling block ingest entirely; cautious default.
                logger.exception(
                    "few_shot.ingest verdict gate raised (non-fatal): %s", _vge,
                )
                _ingest_quality = 0.75

            if _ingest_quality is not None:
                try:
                    _task_type = classify_task_type(ctx.msg.text, [])
                    self._few_shot.store(FewShotExample(
                        task_type=_task_type,
                        input_text=ctx.msg.text,
                        output_text=result.response_text[:500],
                        quality_score=_ingest_quality,
                    ))
                except Exception as _fse:
                    logger.debug("Few-shot store failed (non-fatal): %s", _fse)

        # Record session progress for active project (non-blocking)
        if self._project_registry and result.response_text:
            _active_proj = self._project_registry.get_active_project_name()
            if _active_proj:
                try:
                    self._project_registry.record_session(
                        _active_proj,
                        summary=result.response_text[:300],
                    )
                    logger.debug("Progress: session recorded for project '%s'", _active_proj)
                except Exception as _pre:
                    logger.debug("Progress record failed (non-fatal): %s", _pre)

        # Cost tracking (per-model USD) — estimate tokens from cost_usd
        if self._cost_tracker and result.cost_usd > 0:
            try:
                _tt = classify_task_type(ctx.msg.text, []) if self._few_shot else "general"
                # Estimate tokens from cost_usd (ClaudeResult doesn't expose token counts)
                _model = getattr(result, "model", None) or "sonnet"
                # Codex-6 (#1840): derive the backend name from the
                # runner's resolved backend class so per-backend rollups
                # in ``/cost`` reflect which CLI produced this turn.
                # Default to "" (treated as "claude" by the summary
                # aggregators) when the runner has no backend attribute
                # — handles unit-test fixtures and the pre-Codex-1 path.
                _backend = ""
                _runner = getattr(self, "_claude_runner", None)
                _bk = getattr(_runner, "_backend", None) if _runner is not None else None
                if _bk is not None:
                    _cls = _bk.__class__.__name__
                    if _cls == "CodexBackend":
                        _backend = "codex"
                    elif _cls == "ClaudeBackend":
                        _backend = "claude"
                self._cost_tracker.record(
                    model=_model,
                    input_tokens=0,
                    output_tokens=0,
                    task_type=_tt,
                    backend=_backend,
                )
            except Exception as _cte:
                logger.debug("Cost tracking failed (non-fatal): %s", _cte)

        # Routing feedback — record model success
        if self._routing_feedback:
            try:
                _tt = classify_task_type(ctx.msg.text, []) if self._few_shot else "general"
                self._routing_feedback.record_model_use(
                    model_tier=getattr(result, "model", None) or "sonnet",
                    task_type=_tt,
                    success=True,
                )
                # Record tool usage
                for tool in (result.tools_used or []):
                    self._routing_feedback.record_tool_use(tool, success=True, latency_ms=result.duration_ms)
            except Exception as _rfe:
                logger.debug("Routing feedback failed (non-fatal): %s", _rfe)

        # Session recovery — record success (resets consecutive error counter)
        if self._session_recovery and result.session_id:
            self._session_recovery.record_success(result.session_id)

        # Clear reflexion context on success
        if self._reflexion_ctx:
            self._reflexion_ctx.clear()

        # Check for anomalies
        alerts = await self._security.check_anomalies(
            "message_processed", {"chat_id": msg.chat_id}
        )
        for alert in alerts:
            await self._discord.send_alert(alert)

        # Check session health
        if result.session_id:
            expire_reason = None
            if await self._session_mgr.check_session_file_size(result.session_id):
                expire_reason = "file_size_exceeded"
            elif await self._session_mgr.check_error_count(result.session_id):
                expire_reason = "error_threshold"
            else:
                # Proactive summarize-and-reset at context pressure >= 0.9
                try:
                    ctx_p = await self._session_mgr.context_pressure(result.session_id)
                    if ctx_p >= 0.9:
                        expire_reason = "proactive_context_reset"
                        logger.info(
                            "Proactive context reset triggered: pressure=%.2f session=%s",
                            ctx_p, result.session_id[:8],
                        )
                except Exception as _cpe:
                    logger.debug("Context pressure check failed (non-fatal): %s", _cpe)

            if expire_reason:
                summary = await self._generate_session_summary(
                    msg.chat_id, result.session_id
                )
                await self._session_mgr.expire_with_summary(
                    msg.chat_id, result.session_id, expire_reason, summary
                )
                # Capture summary to project progress on session expiry
                if self._project_registry and summary:
                    _active_proj = self._project_registry.get_active_project_name()
                    if _active_proj:
                        try:
                            self._project_registry.record_session(
                                _active_proj,
                                summary=summary[:300],
                            )
                            if expire_reason == "proactive_context_reset":
                                logger.debug(
                                    "Progress: proactive reset recorded for project '%s'",
                                    _active_proj,
                                )
                        except Exception as _prse:
                            logger.debug("Progress expiry record failed (non-fatal): %s", _prse)
                # Extract knowledge from the expiring session's messages
                await self._extract_session_knowledge(result.session_id)
                # Record session learning to self-edit memory (#218)
                if self._self_edit and summary:
                    try:
                        edit_req = EditRequest(
                            key=f"session:{result.session_id[:8]}",
                            action="create",
                            new_value=summary[:500],
                            reason=f"Session expired ({expire_reason})",
                            category="learning",
                        )
                        self._self_edit.process_edit(edit_req, metrics=self._metrics)
                        logger.debug("Self-edit recorded for session %s", result.session_id[:8])
                    except Exception as _see:
                        logger.debug("Self-edit record failed (non-fatal): %s", _see)
                # Sprint 01.08b: session_expired HookDispatcher.dispatch() removed
                # (audit found 0 production hooks; see plan-01-hooks-audit.md)
                # Reset session hooks on expiry (#19)
                if self._session_hooks:
                    self._session_hooks.reset()

    async def _deliver_service_messages(self) -> None:
        """Pick up and deliver JSON service messages from data/service_messages/."""
        if not self._config or not self._discord:
            return

        messages_dir = Path(self._config.data_dir) / "service_messages"
        if not messages_dir.exists():
            return

        import json
        for msg_file in sorted(messages_dir.glob("*.json")):
            try:
                data = json.loads(msg_file.read_text())
                chat_id = data.get("chat_id") or self._config.service_channel_id or self._config.operator_discord_id
                text = data.get("text", "")
                if text:
                    await self._discord.send_message(chat_id, text)
                    logger.info("Delivered service message: %s", msg_file.name)
                msg_file.unlink()
            except Exception as e:
                logger.warning("Failed to deliver service message %s: %s", msg_file.name, e)
                # Remove broken files to prevent infinite retry
                try:
                    msg_file.unlink()
                except OSError:
                    pass

    def _start_response_latency_watchdog(
        self, msg: QueuedMessage
    ) -> asyncio.Task | None:
        """Start a Discord progress notice timer for a dequeued message."""
        if self._config is None or self._discord is None:
            return None
        delay = int(getattr(self._config, "discord_first_response_sla_seconds", 30))
        if delay <= 0:
            return None
        return asyncio.create_task(self._response_latency_watchdog(msg))

    async def _response_latency_watchdog(self, msg: QueuedMessage) -> None:
        """Send durable progress notices before a long invocation goes silent."""
        if self._config is None or self._discord is None:
            return

        delay = int(getattr(self._config, "discord_first_response_sla_seconds", 30))
        interval = int(getattr(self._config, "discord_progress_interval_seconds", 120))
        if delay <= 0:
            return

        await asyncio.sleep(delay)
        await self._send_processing_notice(msg)

        while interval > 0:
            await asyncio.sleep(interval)
            await self._send_processing_notice(msg)

    async def _send_processing_notice(self, msg: QueuedMessage) -> None:
        """Best-effort Discord progress notice for long-running processing."""
        if self._discord is None:
            return
        try:
            await self._discord.send_message(
                msg.chat_id,
                "Still working on this. No final answer yet.",
                reply_to=msg.platform_message_id,
            )
            if self._metrics:
                self._metrics.increment("discord_processing_notices_total")
        except Exception as e:  # noqa: BLE001
            logger.warning("Failed to send processing notice: %s", e)

    async def _send_response(
        self, chat_id: str, text: str, reply_to: int | None = None
    ) -> bool:
        """Send response to Discord. Returns True if successful."""
        self._require("_discord")
        try:
            await self._discord.send_message(chat_id, text, reply_to=reply_to)
            return True
        except Exception as e:
            logger.error(
                "Failed to send Discord response to %s: %s. "
                "Message will be retried on next startup.", chat_id, e
            )
            return False

    # -- S80: Error handling in processing loop --

    async def _handle_processing_error(
        self, msg: QueuedMessage, result: ClaudeResult, session_id: str,
    ) -> None:
        """Handle all failure modes from Claude Code invocation.

        Delegates to error_handler module; performs halt state mutation locally.
        """
        self._require("_config", "_queue", "_security", "_discord", "_commands")

        _classify_fn = (lambda text, tools: classify_task_type(text, tools)) if self._few_shot else None

        action = await handle_processing_error(
            msg=msg,
            result=result,
            session_id=session_id,
            config=self._config,
            queue=self._queue,
            security=self._security,
            discord=self._discord,
            commands=self._commands,
            routing_feedback=self._routing_feedback,
            session_recovery=self._session_recovery,
            session_mgr=self._session_mgr,
            skill_evolution=self._skill_evolution,
            reflexion_ctx=self._reflexion_ctx,
            token_refresher=self._token_refresher,
            rate_limiter=self._rate_limiter,
            fallback=self._fallback,
            few_shot=self._few_shot,
            shutdown_event=self._shutdown_event,
            classify_task_fn=_classify_fn,
            send_response_fn=self._send_response,
            force_token_refresh_fn=force_token_refresh,
        )

        # Log error (Phase 1, Sprint 1)
        # Sprint 09.14 — fixed latent bug: ClaudeResult has no `error_message`
        # attribute; the right field is `stderr_output`. The bug was unreachable
        # before this sprint because self._daily_log was always None — when
        # 09.14 wires the writer under config.daily_log_enabled (default True),
        # this branch fires and the AttributeError surfaces. See
        # bridge/claude_runner.py:101-104 for the ClaudeResult fields.
        if self._daily_log:
            self._daily_log.append(
                f"Error: {result.error_type} — {(result.stderr_output or '')[:100]}",
                category="error",
            )

        # Halt state mutation stays in BridgeApp — the single source of truth
        if action.should_halt:
            self._halted = True
            self._commands._halted = True

    # -- S81: Graceful shutdown --

    async def _persist_voice_exchange(
        self,
        session_id: str,
        chat_id: str,
        user_text: str,
        assistant_text: str,
        cost_usd: float = 0.0,
        duration_ms: int = 0,
    ) -> None:
        try:
            await self._memory.store_message(
                session_id=session_id, chat_id=chat_id,
                role="user", content=user_text,
            )
            await self._memory.store_message(
                session_id=session_id, chat_id=chat_id,
                role="assistant", content=assistant_text,
                cost_usd=cost_usd,
            )
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning("Failed to persist voice exchange: %s", e)

    async def _shutdown_all_chief_sessions(self) -> None:
        """Z4-S32 #1394 — graceful shutdown sweep for active chief sessions.

        Called from ``stop()`` when ``chief_dispatcher_enabled=true``.
        Walks every non-SHUTDOWN state in the store and calls
        ``ChiefDispatcher.shutdown_session()`` for each row. Idempotent
        per-session: a session already in SHUTDOWN is filtered out (we
        never call shutdown_session on it).

        Best-effort per row: a failure on one session logs a WARNING
        and the loop continues. The 30s caller-side timeout caps the
        worst case; the next-boot reaper picks up anything left over.
        """
        if (
            self._chief_session_store is None
            or self._chief_dispatcher is None
        ):
            return

        from .chief_session import ChiefSessionState

        # Every state except SHUTDOWN is "active" — including FAILED and
        # TIMED_OUT, which can transition to SHUTDOWN. The terminal
        # path (FAILED/TIMED_OUT → SHUTDOWN) is what completes the
        # row's lifecycle.
        active_states = [
            ChiefSessionState.COLD,
            ChiefSessionState.WARM,
            ChiefSessionState.EXECUTING,
            ChiefSessionState.AWAITING_EVALUATION,
            ChiefSessionState.DONE,
            ChiefSessionState.FAILED,
            ChiefSessionState.TIMED_OUT,
        ]

        sessions = []
        for state in active_states:
            try:
                sessions.extend(
                    await self._chief_session_store.list_by_state(state)
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "Chief session shutdown: list_by_state(%s) failed: %s",
                    state.value, exc,
                )

        if not sessions:
            return

        logger.info(
            "Z4-S32: shutting down %d active chief session(s) on bridge exit.",
            len(sessions),
        )
        for session in sessions:
            try:
                await self._chief_dispatcher.shutdown_session(
                    session.session_id, "bridge exit"
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "Chief session shutdown: %s failed: %s",
                    session.session_id, exc,
                )

    async def stop(self) -> None:
        """Clean shutdown sequence per BRIDGE-ARCHITECTURE.md."""
        logger.info("Shutting down bridge...")

        # Sprint 01.08b: bridge_shutdown HookDispatcher.dispatch() removed
        # (audit found 0 production hooks; see plan-01-hooks-audit.md)

        # Send shutdown notification
        if self._discord and self._config:
            try:
                await self._discord.send_message(
                    self._config.operator_discord_id,
                    "Agent shutting down gracefully.",
                )
            except Exception as exc:
                logger.warning("shutdown notification send failed: %s", exc)

        # Shutdown autonomy layer (persist trust scores, escalation state)
        if self._autonomy:
            await self._autonomy.shutdown()

        # Z4-S32 #1394 — gracefully shut down all active chief sessions.
        # Runs AFTER autonomy shutdown but BEFORE the Claude kill so the
        # dispatcher's `shutdown_session()` has a working event_bus +
        # store. 30s timeout caps the worst case; sessions still
        # non-SHUTDOWN after the timeout are logged as WARNING and the
        # bridge exits anyway.
        if self._config and self._config.chief_dispatcher_enabled:
            try:
                await asyncio.wait_for(
                    self._shutdown_all_chief_sessions(),
                    timeout=30.0,
                )
            except asyncio.TimeoutError:
                logger.warning(
                    "Chief session shutdown timed out after 30s — "
                    "some sessions may remain in non-SHUTDOWN state in "
                    "the store. The reaper will pick them up on next "
                    "boot."
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "Chief session shutdown failed (non-fatal): %s", exc
                )

        # Stop token refresher
        if self._token_refresher:
            await self._token_refresher.stop()

        # Close persistent warm Claude process
        if self._warm_claude:
            await self._warm_claude.close()

        # Shutdown tmux agents
        if self._tmux_agents:
            try:
                await self._tmux_agents.shutdown()
            except Exception as e:
                logger.warning("Tmux agent shutdown failed: %s", e)

        # Kill Claude if running
        if self._claude:
            await self._claude.kill_current()

        # Cancel processing task
        if self._processing_task and not self._processing_task.done():
            self._processing_task.cancel()
            try:
                await self._processing_task
            except asyncio.CancelledError:
                pass

        # Cancel heartbeat
        if self._heartbeat_task and not self._heartbeat_task.done():
            self._heartbeat_task.cancel()
            try:
                await self._heartbeat_task
            except asyncio.CancelledError:
                pass

        # Cancel decay timer
        if self._decay_task and not self._decay_task.done():
            self._decay_task.cancel()
            try:
                await self._decay_task
            except asyncio.CancelledError:
                pass

        # Cancel backup timer
        if self._backup_task and not self._backup_task.done():
            self._backup_task.cancel()
            try:
                await self._backup_task
            except asyncio.CancelledError:
                pass

        # Cancel reflection loop
        if self._reflection_task and not self._reflection_task.done():
            self._reflection_task.cancel()
            try:
                await self._reflection_task
            except asyncio.CancelledError:
                pass

        # Cancel consolidation timer
        if self._consolidation_task and not self._consolidation_task.done():
            self._consolidation_task.cancel()
            try:
                await self._consolidation_task
            except asyncio.CancelledError:
                pass

        # Cancel drift check timer (issue #832)
        if self._drift_task and not self._drift_task.done():
            self._drift_task.cancel()
            try:
                await self._drift_task
            except asyncio.CancelledError:
                pass

        # Cancel warm-process health monitor (Sprint D8.4)
        if self._warm_health_task and not self._warm_health_task.done():
            self._warm_health_task.cancel()
            try:
                await self._warm_health_task
            except asyncio.CancelledError:
                pass

        # Sprint E2.3 — stop the hooks telemetry subscriber.
        if self._hooks_telemetry_subscriber is not None:
            await self._hooks_telemetry_subscriber.stop()

        # Sprint 09.13 — stop the tick loop. Mirrors the consolidation pattern:
        # signal stop_event via TickManager.stop(), then cancel the task to
        # surface immediately if the loop is mid-sleep. The wake_event inside
        # stop() also pre-empts a pending wait_for_tick() sleep.
        if self._tick_manager is not None:
            try:
                await self._tick_manager.stop()
            except Exception as e:
                logger.warning("TickManager.stop failed (non-fatal): %s", e)
        if self._tick_loop_task and not self._tick_loop_task.done():
            self._tick_loop_task.cancel()
            try:
                await self._tick_loop_task
            except asyncio.CancelledError:
                pass

        # Stop metrics collector (final flush)
        if self._metrics:
            await self._metrics.stop()

        # Stop heartbeat pinger
        if self._heartbeat_pinger:
            await self._heartbeat_pinger.stop()

        # Stop API server
        if self._api_server:
            try:
                await self._api_server.stop()
            except Exception as exc:
                logger.warning("api server stop failed during shutdown: %s", exc)

        # Stop health server
        if self._health_server:
            try:
                await self._health_server.stop()
            except Exception as exc:
                logger.warning("health server stop failed during shutdown: %s", exc)

        # Stop webhook deliverer (Sprint 14)
        if self._webhook_deliverer:
            await self._webhook_deliverer.stop()

        # Sprint 07.04: deregister from the peer registry and cancel the
        # heartbeat loop. Wrapped in try/except so a failed deregister
        # never crashes shutdown — at worst the peer record times out via
        # PeerRegistry.prune_stale on the receiving side.
        if self._peer_registration is not None:
            try:
                await self._peer_registration.stop()
            except Exception:
                logger.exception("peer deregistration failed")

        # Checkpoint WAL
        if self._db:
            try:
                await self._db.checkpoint()
            except Exception as e:
                logger.error("WAL checkpoint failed: %s", e)

        # Stop Discord
        if self._discord:
            await self._discord.stop()

        # Sprint R2.3 (#1895) — close synchronous-sqlite stores that BridgeApp
        # owns and whose lifecycle ends with the bridge. Each store keeps a
        # long-lived ``self._conn`` whose orphan emits a ``ResourceWarning:
        # unclosed database`` once GC catches it; explicit close() at shutdown
        # makes ownership deterministic and the warnings stop.
        for _attr, _store in (
            ("_embedding_engine", self._embedding_engine),
            ("_workorder_store", self._workorder_store),
            ("_peer_registry", self._peer_registry),
        ):
            if _store is not None and hasattr(_store, "close"):
                try:
                    _store.close()
                except Exception as exc:  # noqa: BLE001
                    logger.warning("%s.close() failed (non-fatal): %s", _attr, exc)

        # Close DB
        if self._db:
            await self._db.close()

        # Remove PID file
        if self._pid_path and self._pid_path.exists():
            self._pid_path.unlink(missing_ok=True)

        # Log shutdown
        logger.info("Bridge shutdown complete")

    # -- S82: Command integration --

    async def _handle_command(
        self, chat_id: str, command: str, args: str
    ) -> str | None:
        """Route slash commands to bridge/agent handlers.

        Wraps the dispatch in ``_start_typing`` / ``_stop_typing`` so that
        long-running bridge commands (``/direct``, ``/strategy``,
        ``/board``, ``/handoff``, anything that hits Z4 routing) show a
        Discord "typing..." indicator while the operator waits. Without
        this, slash-command UX silently stalls for 60-90s on Z4 dispatch
        — the message pipeline at ``_process_message`` already does
        this, but slash commands took a different code path until #1071
        landed and surfaced the gap.
        """
        self._require("_commands", "_security")

        # Log command
        await self._security.log_event(
            "command",
            details={"command": command, "args": args},
            chat_id=chat_id,
        )

        # Start typing indicator — fires BEFORE dispatch so the operator
        # sees feedback as soon as the bridge picks up the slash command,
        # not when the response is ready to post.
        if self._discord is not None:
            try:
                self._discord._start_typing(chat_id)
            except Exception as e:  # noqa: BLE001
                logger.debug("Could not start typing indicator: %s", e)

        try:
            # Bridge-level commands: handle directly
            # Normalize hyphens to underscores (e.g. kill-agent → kill_agent)
            normalized_cmd = command.replace("-", "_")
            if normalized_cmd in BRIDGE_COMMANDS:
                result = await self._commands.handle(chat_id, command, args)

                # Sync halt state from commands
                self._halted = self._commands.is_halted()
                if normalized_cmd == "resume" and not self._halted:
                    await asyncio.to_thread(self._security.clear_halt)

                return result

            # Agent-level commands: get the prompt and enqueue as a message
            if command in AGENT_COMMANDS:
                prompt = self._commands.get_agent_prompt(command, args)
                if prompt and self._queue:
                    await self._queue.enqueue(0, chat_id, prompt)
                    return f"Agent command /{command} queued for processing."
                return await self._commands.handle(chat_id, command, args)

            return f"Unknown command: /{command}"
        finally:
            # Always stop typing — even if dispatch raised. The pipeline
            # path at line 2449 follows the same pattern.
            if self._discord is not None:
                try:
                    self._discord._stop_typing(chat_id)
                except Exception as e:  # noqa: BLE001
                    logger.debug("Could not stop typing indicator: %s", e)

    async def _handle_new_message(
        self, chat_id: str, text: str, platform_message_id: int
    ) -> None:
        """Handle incoming Discord messages: enqueue and acknowledge."""
        self._require("_queue", "_discord", "_security")

        if self._halted:
            await self._discord.send_message(
                chat_id,
                "Agent is halted. Send /resume to restart processing.",
            )
            return

        # D7.9 #1421 (slice 2) — conditional inbox-receive for mid-stream
        # interrupt activation. We feed the inbox ONLY when an invocation
        # is currently in flight. Idle-state messages skip the inbox
        # entirely so the next-spawn gate doesn't block the very message
        # the bridge is about to dequeue and process. In-flight messages
        # land in the inbox → trigger the slice-1 mid-stream check in
        # claude_runner.invoke() → SIGTERM the subprocess → return the
        # gate's BLOCK message → the bridge's normal _send_response path
        # delivers the BLOCK to Discord (this IS the within-5s ack
        # acceptance bar).
        #
        # P1.1 (audit C1) — the in-flight check now consults the shared
        # InvocationController so it returns True for BOTH paths
        # (one-shot ClaudeRunner.invoke AND WarmClaudeProcess.send_message).
        # Pre-P1.1 this checked `self._claude._lock.locked()` which only
        # sees the one-shot lock; the default warm path was invisible
        # and operator interrupts silently no-op'd.
        invocation_active = False
        if self._invocation_controller is not None:
            try:
                invocation_active = (await self._invocation_controller.active()) is not None
            except Exception:
                logger.exception(
                    "invocation_controller: active() raised — "
                    "treating as idle for interrupt activation"
                )

        if self._operator_inbox is not None and invocation_active:
            try:
                await self._operator_inbox.receive_classified(text)
            except Exception:
                logger.exception(
                    "operator_inbox: receive_classified raised — "
                    "queue path proceeds without interrupt activation"
                )

        # Enqueue the message
        await self._queue.enqueue(platform_message_id, chat_id, text)

        # Sprint 01.08b: message_received HookDispatcher.dispatch() removed
        # (audit found 0 production hooks; see plan-01-hooks-audit.md)

        # Send queue position acknowledgment — only when the message is
        # actually waiting on something. Post-D-R1 (PR #1917) the warm path
        # replies in 1-2s, so a "Starting now." ACK for the immediate-handle
        # case races the actual response and is pure noise. The two queued
        # cases below carry information the user can't otherwise see
        # (your message is waiting); leave those.
        position = await self._queue.get_position(chat_id)
        if position > 1:
            await self._discord.send_message(
                chat_id,
                f"Message queued (position {position}).",
                reply_to=platform_message_id,
            )
        elif invocation_active:
            await self._discord.send_message(
                chat_id,
                "Received. Queued behind the active turn.",
                reply_to=platform_message_id,
            )

        # Log
        await self._security.log_event(
            "message_received",
            details={"text_length": len(text)},
            chat_id=chat_id,
        )
