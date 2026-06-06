"""Universal service runner — standalone entry point for LaunchDaemon plists.

Usage:
    python -m bridge.services.runner <service_name> [--mode {micro,standard,deep}]
    python -m bridge.services.runner --list
    python -m bridge.services.runner --validate

The optional ``--mode`` flag is currently consumed only by the consolidation
service (three plists: ``consolidation-micro``, ``consolidation-standard``,
``consolidation-deep``). Other services ignore extra flags.
"""

from __future__ import annotations

import argparse
import asyncio
import importlib
import json
import logging
import os
import signal
import sys
import tempfile
import time
import types
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger(__name__)


def _resolve_agent_root() -> Path:
    """Resolve runtime tree root via the canonical helper (#1492).

    F3 of #1501: in-tree code should call this directly instead of relying
    on the module-level ``AGENT_ROOT`` constant. The constant is preserved
    for back-compat via PEP 562 ``__getattr__`` below; each access
    re-resolves so tests/scripts that mutate ``cwd`` between calls see the
    current value.
    """
    from bridge.paths import agent_root
    return agent_root()


def _resolve_data_root() -> Path:
    """Resolve data dir via the canonical helper (#1501 F4)."""
    from bridge.paths import data_root
    return data_root()


# DATA_DIR / DB_PATH are deliberately bound at import time. F4 of #1501
# made the resolution path canonical (via ``data_root()``) but the data
# dir lives at user-home level, so it's stable across the only migration
# that has moved it (none, post-D6-bis). Existing tests rely on the
# attribute-write form (``runner.DATA_DIR = tmp_path``) to swap it; that
# pattern stays load-bearing.
DATA_DIR = _resolve_data_root()
DB_PATH = DATA_DIR / "memory.db"


def __getattr__(name: str) -> Path:
    """PEP 562 — lazy resolution for ``AGENT_ROOT`` (F3 of #1501).

    Pre-fix: ``AGENT_ROOT = _resolve_agent_root()`` ran at import time and
    froze the value. Tests/scripts mutating ``cwd`` / ``BUMBA_AGENT_ROOT``
    between two imports of this module saw a stale value.

    Post-fix: the module-level binding is removed and every
    ``bridge.services.runner.AGENT_ROOT`` access re-routes here and
    re-resolves via ``_resolve_agent_root()``. In-tree code (e.g.
    ``_load_chat_id``, ``_load_bridge_config``) reads ``AGENT_ROOT`` as a
    module attribute, so they automatically pick up the lazy resolution
    without per-callsite changes.

    Note: callers that did ``from bridge.services.runner import AGENT_ROOT``
    at their import time still bind a local name to the resolved-at-that-
    moment value (Python import binding semantics — PEP 562 cannot fix
    that). No production caller does this today; the fix benefits the
    deferred-attribute-read pattern used in ``_load_chat_id`` /
    ``_load_bridge_config`` and any future module-attribute reader.
    """
    if name == "AGENT_ROOT":
        return _resolve_agent_root()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

SERVICE_MAP: dict[str, tuple[str, str]] = {
    "briefing": ("bridge.services.briefing", "BriefingService"),
    "checkin": ("bridge.services.checkin", "CheckinService"),
    "email": ("bridge.services.email", "EmailService"),
    "calendar": ("bridge.services.calendar", "CalendarService"),
    "knowledge_review": ("bridge.services.knowledge_review", "KnowledgeReviewService"),
    "retro": ("bridge.services.retro", "RetroService"),
    "weekly_review": ("bridge.services.weekly_review", "WeeklyReviewService"),
    "job_search": ("job_search.service", "JobSearchPrepareService"),
    "job_search_execute": ("job_search.service", "JobSearchExecuteService"),
    "consolidation": ("bridge.services.consolidation_service", "ConsolidationService"),
    # Z2-S5.x new services
    "inbox_nurture": ("bridge.services.inbox_nurture", "InboxNurtureService"),
    "subscription_tracker": ("bridge.services.subscription_tracker", "SubscriptionTrackerService"),
    "project_pulse": ("bridge.services.project_pulse", "ProjectPulseService"),
    # Z2-S2.1 FR-005 — daily 22:00 funnel summary post
    "funnel_post": ("bridge.services.funnel_post", "FunnelPostService"),
    # Z4 Phase G — Monday 08:00 workflow trigger
    "weekly_ceo_review": ("bridge.services.weekly_ceo_review", "WeeklyCEOReviewService"),
    # Z2-S4.2 + S5.1 — event-driven Cal.com prebrief + 10-min polling fallback
    "meeting_prebrief": ("bridge.services.meeting_prebrief", "MeetingPrebriefService"),
    # Sprint 14.10 — Dark Factory orchestrator (cron every 4h)
    "factory_orchestrator": (
        "bridge.services.factory_orchestrator",
        "FactoryOrchestrator",
    ),
    # Sprint 14.11 — Dark Factory soak harness (cron every 4h, observe-only)
    "factory_soak": (
        "bridge.services.factory_soak",
        "FactorySoakService",
    ),
    # Sprint 2.07 — Zone 1 doctrine drift detector (operator-review drafts only)
    "zone1_drift": ("bridge.services.zone1_drift", "Zone1DriftService"),
}

# Common aliases (hyphenated → underscored)
SERVICE_ALIASES: dict[str, str] = {
    "knowledge-review": "knowledge_review",
    "weekly-review": "weekly_review",
    "job-search": "job_search",
    "job-search-execute": "job_search_execute",
    "job-execute": "job_search_execute",
    "inbox-nurture": "inbox_nurture",
    "subscription-tracker": "subscription_tracker",
    "project-pulse": "project_pulse",
    "funnel-post": "funnel_post",
    "weekly-ceo-review": "weekly_ceo_review",
    "meeting-prebrief": "meeting_prebrief",
    "factory-orchestrator": "factory_orchestrator",
    "factory-soak": "factory_soak",
    "zone1-drift": "zone1_drift",
}

# Services deferred pending upstream dependencies.
# When the runner encounters a deferred service it logs a warning and exits 0
# rather than attempting to instantiate the class. The set is currently empty;
# keep the guard so future deferred plists can opt in without changing
# ``_async_main`` again.
DEFERRED_SERVICES: frozenset[str] = frozenset()

# Services that need db_path in __init__
NEEDS_DB = {"briefing", "checkin", "knowledge_review", "retro", "weekly_review", "consolidation"}

# Per-service timeout in seconds
SERVICE_TIMEOUTS: dict[str, int] = {
    "briefing": 300,
    "checkin": 120,
    "email": 180,
    "calendar": 120,
    "knowledge_review": 600,
    "retro": 300,
    "weekly_review": 300,
    "job_search": 1800,
    "job_search_execute": 600,
    "consolidation": 900,
    "inbox_nurture": 120,
    "subscription_tracker": 180,
    "project_pulse": 120,
    "funnel_post": 60,
    "weekly_ceo_review": 120,
    "meeting_prebrief": 120,
    # Sprint 14.10 — orchestrator processes up to 20 issues, each ~2 min
    # implement + 30s validate + cost-cap halts; 30 min is the safe ceiling.
    "factory_orchestrator": 1800,
    # Sprint 14.11 — shadow harness shares the orchestrator's pipeline so
    # the timeout matches; it never acts so cost is per-issue Claude calls
    # only, but the per-issue ceiling is identical.
    "factory_soak": 1800,
    # Zone 1 drift scan is filesystem-only over a small doctrine set.
    "zone1_drift": 300,
}

DEFAULT_TIMEOUT = 300

# Shutdown event for SIGTERM handling
_shutdown_event = asyncio.Event()


def _resolve_service_name(name: str) -> str:
    """Resolve service name, handling aliases."""
    if name in SERVICE_MAP:
        return name
    if name in SERVICE_ALIASES:
        resolved = SERVICE_ALIASES[name]
        log.info("Resolved service alias: %s -> %s", name, resolved)
        return resolved
    return name  # let run_service() raise the error


def _load_chat_id() -> str:
    """Load service delivery channel ID from .secrets or bridge.toml.

    Prefers service_channel_id (dedicated channel for automated outputs),
    falls back to operator_discord_id for backwards compatibility.
    """
    secrets_path = DATA_DIR / ".secrets"
    service_id = ""
    operator_id = ""
    if secrets_path.exists():
        for line in secrets_path.read_text().splitlines():
            line = line.strip()
            if line.startswith("service_channel_id="):
                service_id = line.split("=", 1)[1].strip()
            elif line.startswith("operator_discord_id=") or line.startswith("operator_id="):
                operator_id = line.split("=", 1)[1].strip()
        if service_id:
            return service_id
        if operator_id:
            return operator_id
    # Fallback: read from bridge config.
    # F3 of #1501: call ``_resolve_agent_root()`` directly so the lookup
    # happens at call time, not at module-import time.
    try:
        import tomllib
        config_path = _resolve_agent_root() / "config" / "bridge.toml"
        if config_path.exists():
            with open(config_path, "rb") as f:
                cfg = tomllib.load(f)
            discord_cfg = cfg.get("discord", {})
            return discord_cfg.get("service_channel_id", "") or discord_cfg.get("operator_id", "")
    except (ImportError, Exception):
        pass
    return ""


def _load_bridge_config() -> "object | None":
    """Load BridgeConfig for the runner. Returns None on any import/parse error.

    Called once per service instantiation. Uses skip_secrets + skip_validation
    so the runner never blocks on missing Discord credentials — services only
    need the subset of config flags relevant to their own behaviour.
    """
    try:
        from bridge.config import load_config
        # F3 of #1501: resolve at call time (see ``_load_chat_id`` above).
        config_path = _resolve_agent_root() / "config" / "bridge.toml"
        if not config_path.exists():
            return None
        return load_config(config_path, skip_secrets=True, skip_validation=True)
    except Exception as e:
        log.debug("Could not load BridgeConfig in runner: %s", e)
        return None


def _build_weekly_ceo_workflow_kwargs() -> dict[str, object]:
    """Construct standalone workflow dependencies for weekly CEO review.

    ``BridgeApp`` owns the full live wiring boundary for workflow execution
    (department runner, task queue, store, event bus, Discord callback). The
    standalone service runner cannot reuse those in-process objects, so it
    constructs the lightweight registry and engine directly. If either import
    or constructor fails, the caller receives no kwargs and
    ``WeeklyCEOReviewService`` preserves its explicit "workflow engine not
    configured" skip result.
    """
    try:
        from bridge.workflow_engine import WorkflowEngine
        from bridge.workflow_registry import WorkflowRegistry
    except Exception as exc:
        log.warning(
            "weekly_ceo_review workflow dependency import failed: %s",
            exc,
        )
        return {}

    try:
        return {
            "workflow_registry": WorkflowRegistry(),
            "workflow_engine": WorkflowEngine(),
        }
    except Exception as exc:
        log.warning(
            "weekly_ceo_review workflow dependency construction failed: %s",
            exc,
        )
        return {}


def _setup_logging(service_name: str) -> None:
    """Configure logging for standalone service execution."""
    log_dir = Path("/opt/bumba-harness/logs")
    log_dir.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format=f"%(asctime)s [{service_name}] %(levelname)s %(message)s",
        handlers=[
            logging.FileHandler(log_dir / f"{service_name}.log"),
            logging.StreamHandler(),
        ],
    )


def _import_service_class(name: str) -> type:
    """Import and return the service class for a given name."""
    if name not in SERVICE_MAP:
        available = ", ".join(sorted(SERVICE_MAP.keys()))
        raise ValueError(f"Unknown service: {name}. Available: {available}")

    module_path, class_name = SERVICE_MAP[name]
    mod = importlib.import_module(module_path)
    return getattr(mod, class_name)


def _create_event_callback(service_name: str) -> tuple:
    """Create an EventBus and a callback that publishes to it.

    Returns (event_bus, callback).  The event_bus is kept alive so that
    the caller can publish additional lifecycle events.
    """
    try:
        from bridge.event_bus import EventBus

        # Use data_dir only if it's writable; fall back to in-memory only
        events_dir = DATA_DIR / "events"
        try:
            events_dir.mkdir(parents=True, exist_ok=True)
            bus_data_dir = DATA_DIR
        except OSError:
            bus_data_dir = None  # in-memory only, no persistence

        event_bus = EventBus(data_dir=bus_data_dir)

        def _callback(event_type: str, payload: dict) -> None:
            payload.setdefault("service", service_name)
            try:
                event_bus.publish(event_type, payload=payload, source=f"service:{service_name}")
            except Exception:
                log.debug("Event publish failed", exc_info=True)

        return event_bus, _callback
    except Exception:
        log.debug("EventBus unavailable, running without event hooks", exc_info=True)
        return None, None


def _write_crash_state(name: str, error_msg: str) -> None:
    """Write failure state directly when service crashes before instantiation.

    This catches the gap where a service crashes during __init__ (e.g., TypeError
    from unexpected kwargs) — before the service object exists, so svc.record_failure()
    is unavailable and no state file gets written.
    """
    state_dir = DATA_DIR / "service_state"
    state_dir.mkdir(parents=True, exist_ok=True)
    state_path = state_dir / f"{name}-state.json"

    try:
        state = json.loads(state_path.read_text()) if state_path.exists() else {}
    except (json.JSONDecodeError, OSError):
        state = {}

    state["consecutive_failures"] = state.get("consecutive_failures", 0) + 1
    state["last_error"] = error_msg[:500]
    state["last_error_time"] = datetime.now(timezone.utc).isoformat()
    state["service"] = name

    # Atomic write
    fd, tmp_path = tempfile.mkstemp(dir=state_dir, suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(state, f, indent=2)
        os.replace(tmp_path, state_path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def _write_crash_alert(name: str, error_msg: str) -> None:
    """Write a crash notification file for the bridge to pick up and send to Discord."""
    messages_dir = DATA_DIR / "service_messages"
    messages_dir.mkdir(parents=True, exist_ok=True)

    alert = {
        "type": "crash",
        "service": name,
        "message": f"Service `{name}` crashed during startup: {error_msg[:200]}",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    alert_path = messages_dir / f"crash_{name}_{timestamp}.json"
    fd, tmp_path = tempfile.mkstemp(dir=messages_dir, suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(alert, f, indent=2)
        os.replace(tmp_path, alert_path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


def _instantiate_service(
    name: str,
    cls: type,
    event_callback=None,
    extra_kwargs: dict | None = None,
) -> object:
    """Instantiate a service with appropriate arguments.

    ``extra_kwargs`` (Sprint 02.02) is layered on top of the base kwargs and
    overrides them on conflict — used to thread CLI flags such as ``--mode``
    into the constructor (e.g. ``ConsolidationService(..., mode="deep")``).
    Defaults to ``None`` to keep call sites that don't pass flags untouched.
    """
    chat_id = _load_chat_id()
    if not chat_id:
        log.warning("No chat_id configured — messages will use empty chat_id")

    # Ensure directories exist
    state_dir = DATA_DIR / "service_state"
    state_dir.mkdir(parents=True, exist_ok=True)
    messages_dir = DATA_DIR / "service_messages"
    messages_dir.mkdir(parents=True, exist_ok=True)

    kwargs: dict = {"data_dir": DATA_DIR, "chat_id": chat_id}
    if name in NEEDS_DB:
        kwargs["db_path"] = DB_PATH
    if event_callback is not None:
        kwargs["event_callback"] = event_callback

    # Thread BridgeConfig flags for services that honour them (D1.10 #1182).
    # Loaded once per runner invocation — fast TOML parse, no secrets needed.
    cfg = _load_bridge_config()
    if cfg is not None:
        if name == "briefing":
            kwargs["enabled"] = cfg.briefing_enabled
            kwargs["delivery_hour"] = cfg.briefing_delivery_hour
            kwargs["delivery_minute"] = cfg.briefing_delivery_minute
        elif name == "checkin":
            kwargs["enabled"] = cfg.checkin_enabled
            kwargs["active_hours_start"] = cfg.checkin_active_hours_start
            kwargs["active_hours_end"] = cfg.checkin_active_hours_end
            kwargs["minimum_gap"] = cfg.checkin_minimum_gap
            kwargs["quiet_after_message"] = cfg.checkin_quiet_after_message

    if name == "weekly_ceo_review":
        kwargs.update(_build_weekly_ceo_workflow_kwargs())

    if extra_kwargs:
        kwargs.update(extra_kwargs)
    return cls(**kwargs)


def _wire_retro_metrics(svc: object) -> None:
    """Wire MetricsAggregator into the retro service for Zone 4 activity source.

    Only activates if z4-sessions directory exists and the required
    observability modules are importable.
    """
    z4_sessions_dir = DATA_DIR / "z4-sessions"
    if not z4_sessions_dir.exists():
        log.debug("z4-sessions dir not found, skipping retro metrics wiring")
        return

    try:
        from bridge.observability.tool_tracker import ToolTracker
        from bridge.observability.metrics_aggregator import MetricsAggregator

        tracker = ToolTracker(sessions_dir=z4_sessions_dir)
        aggregator = MetricsAggregator(tracker=tracker, sessions_dir=z4_sessions_dir)

        # Use the static setter on RetroService to inject the aggregator
        from bridge.services.retro import RetroService
        RetroService.set_metrics_aggregator(aggregator)

        log.info("MetricsAggregator wired into retro service")
    except Exception as e:
        log.debug("Could not wire MetricsAggregator into retro: %s", e)


def _wire_consolidation_dream_agent(svc: object) -> None:
    """Wire DreamAgent into ConsolidationService for deep-mode consolidation.

    P8.2 sub-decision 2 (#1748). The setter contract has lived on
    ``ConsolidationService`` since the dream_agent module shipped
    (``set_dream_agent`` at consolidation_service.py:414), but no caller
    invoked it — so the "deep" branch of ``run_pipeline`` always received
    ``_dream_agent=None`` and the DreamAgent module was unreachable in
    production. This helper closes that gap.

    Wiring lives here (in the consolidation subprocess runner) rather than
    in ``BridgeApp._initialize`` because ConsolidationService runs as a
    separate LaunchDaemon process; the bridge daemon never holds a
    ConsolidationService instance. Mirrors the ``_wire_retro_metrics``
    pattern shipped at line 423.

    No-op when:
      - BridgeConfig cannot be loaded (no runtime config), or
      - DreamAgent import fails (e.g. missing optional dep).

    Failures are logged but never raise — the consolidation pipeline still
    runs in micro/standard modes; only the deep branch is affected.
    """
    cfg = _load_bridge_config()
    if cfg is None:
        log.debug("BridgeConfig unavailable, skipping DreamAgent wiring")
        return

    try:
        from bridge.dream_agent import DreamAgent
        from bridge.database import Database

        # Mem-7 (#1848): construct (but do not connect) a Database handle
        # against the consolidation DB path. DreamAgent._run_tier_ops opens
        # the connection lazily inside the asyncio.run loop and closes it
        # again on completion. When `memory_tiers_enabled = False`, the
        # database handle is never touched.
        db = Database(DB_PATH)
        agent = DreamAgent(cfg, database=db)
        # Setters are idempotent and never raise — the consolidation pipeline
        # only consults _dream_agent when effective_mode == "deep".
        svc.set_dream_agent(agent)
        svc.set_config(cfg)
        log.info(
            "DreamAgent wired into consolidation service (gated by mode=deep)"
        )
    except Exception as e:
        log.warning("DreamAgent init failed (non-fatal): %s", e)


async def run_service_with_timeout(
    name: str, extra_kwargs: dict | None = None
) -> bool:
    """Instantiate and run a service with timeout protection.

    ``ServiceBase.run`` may be sync OR async; async is invoked inline, sync is
    invoked via ``asyncio.to_thread`` for timeout-safety. The defensive
    ``isinstance(result, types.CoroutineType)`` check is a future-proofing hedge
    against regressions where an async method slips through the sync path
    (e.g. a service migrated to ``async def`` without updating the dispatcher).

    ``extra_kwargs`` (Sprint 02.02) is forwarded to ``_instantiate_service``
    so CLI flags like ``--mode`` can override the default constructor args.
    Defaults to ``None``; existing callers do not need to pass it.

    Returns True if the service sent a message, False otherwise.
    Raises asyncio.TimeoutError if the service exceeds its timeout.
    """
    # Sprint 07.11 — bind correlation IDs for the entire service run so every
    # log record carries a synthetic message_id (services have no natural one)
    # and a session_id matching the service's own identity. clear is paired
    # in the ``finally`` below so context never leaks to the next service.
    from bridge import log_format

    _service_msg_id = f"service-{name}-{int(time.time())}"
    log_format.set_message_context(
        session_id=f"service:{name}",
        message_id=_service_msg_id,
    )
    try:
        return await _run_service_inner(name, extra_kwargs)
    finally:
        log_format.clear_message_context()


async def _run_service_inner(
    name: str, extra_kwargs: dict | None = None
) -> bool:
    """Body of :func:`run_service_with_timeout` — split out in Sprint 07.11
    so the outer wrapper can pair ``set_message_context`` with a guaranteed
    ``clear_message_context`` in ``finally`` without duplicating the
    existing try/except scaffolding.
    """
    try:
        cls = _import_service_class(name)
        event_bus, event_callback = _create_event_callback(name)
        svc = _instantiate_service(
            name,
            cls,
            event_callback=event_callback,
            extra_kwargs=extra_kwargs,
        )
    except Exception as e:
        error_msg = f"{type(e).__name__}: {e}"
        log.error("service.instantiation.error", extra={"service": name, "error": error_msg})
        _write_crash_state(name, error_msg)
        _write_crash_alert(name, error_msg)
        raise

    # Wire MetricsAggregator into retro service for Zone 4 activity source
    if name == "retro":
        _wire_retro_metrics(svc)

    # P8.2 #1748 — wire DreamAgent into ConsolidationService for deep mode
    if name == "consolidation":
        _wire_consolidation_dream_agent(svc)

    timeout = SERVICE_TIMEOUTS.get(name, DEFAULT_TIMEOUT)
    start_ms = time.monotonic()

    log.info(
        "service.run.begin",
        extra={"service": name, "timeout_s": timeout, "pid": os.getpid()},
    )

    # Publish run-start event
    if event_bus:
        event_bus.publish(
            "schedule.triggered",
            payload={"service": name, "status": "started", "timeout_s": timeout},
            source=f"service:{name}",
        )

    try:
        # Sprint 02.01: branch on iscoroutinefunction so async run() methods
        # are awaited inline rather than scheduled into a thread (which would
        # leave the coroutine unawaited and silently report success).
        if asyncio.iscoroutinefunction(svc.run):
            result = await asyncio.wait_for(svc.run(), timeout=timeout)
        else:
            result = await asyncio.wait_for(
                asyncio.to_thread(svc.run),
                timeout=timeout,
            )

        # Defensive post-await coroutine catch — future-proof against a sync
        # run() that has been quietly upgraded to async without
        # `iscoroutinefunction` reflecting it (e.g. a wrapped/decorated
        # callable). If we still hold an unawaited coroutine, await it now
        # and warn rather than fall through to ``non_standard_return``.
        if isinstance(result, types.CoroutineType):
            log.warning(
                "run_service_with_timeout: %s.run() returned a bare coroutine "
                "— awaiting defensively",
                name,
            )
            result = await result

        duration_ms = int((time.monotonic() - start_ms) * 1000)

        # Normalise to ServiceResult (BET 1 keystone). Services mid-migration
        # may still return bool — synthesize one to keep the pipeline intact.
        from bridge.services.result import (
            ServiceResult,
            format_completion_line,
            write_last_run,
        )

        if isinstance(result, ServiceResult):
            service_result = result
        elif isinstance(result, bool):
            service_result = ServiceResult(
                service=name,
                ok=bool(result),
                work_items=0,
                duration_ms=duration_ms,
                cost_usd=0.0,
            )
        else:
            service_result = ServiceResult(
                service=name,
                ok=True,
                work_items=0,
                duration_ms=duration_ms,
                cost_usd=0.0,
                anomalies=("non_standard_return",),
            )

        # Emit the structured completion line — the keystone signal that
        # /services, monitor.sh, and the event bus all consume (FR-002).
        log.info(format_completion_line(service_result))

        log.info(
            "service.run.complete",
            extra={
                "service": name,
                "duration_ms": duration_ms,
                "ok": service_result.ok,
                "work_items": service_result.work_items,
            },
        )

        # Persist aggregate to data/service_state/last_run.json (FR-003).
        try:
            state_dir = DATA_DIR / "service_state"
            write_last_run(state_dir, service_result)
        except OSError as e:
            # Read-only state dir, etc. — completion line is still observable,
            # so we do not crash the service.
            log.warning(
                "service.last_run.write_failed",
                extra={"service": name, "error": str(e)[:200]},
            )

        # Record success in state file (also fires event_callback)
        # FR-007: Do NOT call record_success when the service returned a SKIP.
        # The service already called record_skipped(); calling record_success here
        # would bump total_runs and overwrite last_run, inflating telemetry.
        if service_result.skip_reason is not None:
            # SKIP result — record_skipped() already fired; leave total_runs intact
            pass
        elif hasattr(svc, "record_success"):
            # Board Phase 1 metering (#2390): thread the per-run cost into the
            # cumulative total_cost_usd ledger. ServiceResult.cost_usd is the
            # producer; record_success is the consumer/accumulator.
            svc.record_success(duration_ms, cost_usd=service_result.cost_usd)

        # Publish health.changed on completion
        if event_bus:
            event_bus.publish(
                "health.changed",
                payload={"service": name, "status": "healthy", "duration_ms": duration_ms},
                source=f"service:{name}",
            )

        return service_result.ok

    except asyncio.TimeoutError:
        duration_ms = int((time.monotonic() - start_ms) * 1000)
        error_msg = f"timeout after {timeout}s"

        log.error(
            "service.run.timeout",
            extra={"service": name, "timeout_s": timeout, "duration_ms": duration_ms},
        )

        if hasattr(svc, "record_failure"):
            svc.record_failure(error_msg)

        if event_bus:
            event_bus.publish(
                "health.changed",
                payload={"service": name, "status": "unhealthy", "error": error_msg},
                source=f"service:{name}",
            )

        raise

    except Exception as e:
        duration_ms = int((time.monotonic() - start_ms) * 1000)

        log.error(
            "service.run.error",
            extra={
                "service": name,
                "error_type": type(e).__name__,
                "error": str(e)[:500],
                "duration_ms": duration_ms,
            },
        )

        if hasattr(svc, "record_failure"):
            svc.record_failure(str(e)[:500])

        if event_bus:
            event_bus.publish(
                "health.changed",
                payload={"service": name, "status": "unhealthy", "error": str(e)[:200]},
                source=f"service:{name}",
            )

        raise


def run_service(name: str) -> bool:
    """Synchronous wrapper for backwards compatibility."""
    return asyncio.run(run_service_with_timeout(name))


def list_services() -> None:
    """Print all available services and exit."""
    print("Available services:")
    for name in sorted(SERVICE_MAP.keys()):
        module_path, class_name = SERVICE_MAP[name]
        timeout = SERVICE_TIMEOUTS.get(name, DEFAULT_TIMEOUT)
        print(f"  {name:<25s} {module_path}:{class_name} (timeout: {timeout}s)")


def _check_no_agent_messages_resurrection(repo_root: "Path | None" = None) -> "list[str]":
    """Sprint 04.14 guard — fail if ``agent/bridge/agent_messages.py`` reappears.

    Sprint 04.13 deleted ``agent/bridge/agent_messages.py`` (per round-3 D2
    verdict in the 2026-04-23 master audit). The deleted module defined a
    ``WorkOrder`` class that **collided** with the canonical
    ``bridge/work_order.py:150 WorkOrder``. The shadow was latent — no
    production importer — but resurrecting it would re-introduce the
    naming collision and silently mis-route any future
    ``from bridge.agent_messages import WorkOrder`` import to the wrong
    class.

    This guard runs as part of ``validate_services()`` so resurrection
    surfaces at PR time, not after a future operator hits the latent trap.

    Returns a list of error strings (empty if clean).
    """
    import pathlib
    root = repo_root if repo_root is not None else pathlib.Path(__file__).resolve().parents[3]
    forbidden_path = root / "agent" / "bridge" / "agent_messages.py"
    if forbidden_path.exists():
        return [
            f"agent_messages.py resurrected at {forbidden_path}. "
            "agent_messages.py was deleted in Sprint 04.13 (D2 verdict). "
            "Resurrecting it would re-introduce the WorkOrder class collision "
            "with bridge/work_order.py:150. If you need agent-message types, "
            "add them to bridge/work_order.py or a new differently-named module."
        ]
    return []


def validate_services() -> bool:
    """Enforce structural integrity between plists, SERVICE_MAP, and ServiceResult contract.

    Rule 1: Every plist label maps to a SERVICE_MAP entry (or documented exception).
    Rule 2: Every SERVICE_MAP key has a corresponding plist (or on-demand exception).
    Rule 3: Every service class constructor accepts a 'data_dir' parameter.
    Rule 4: Every service run() method is annotated to return ServiceResult (or bool).
    Rule 5: ``agent/bridge/agent_messages.py`` must not exist (Sprint 04.14
            guard against duplicate WorkOrder class resurrection).

    Returns True if all rules pass, False otherwise.
    """
    import glob as _glob
    import inspect
    import re

    errors: list[str] = []

    # --- Rule 0: no Python source at repo root outside /scripts/ and /agent/ -
    def _check_no_root_python_shadows(repo_root: "Path | None" = None) -> "list[str]":
        import pathlib
        root = repo_root if repo_root is not None else pathlib.Path(__file__).resolve().parents[3]
        forbidden_dirs = ["bridge", "teams", "tests", "job_search"]
        forbidden_files = ["pyproject.toml", "uv.lock"]
        shadow_errors: list[str] = []
        for d in forbidden_dirs:
            path = root / d
            if path.exists() and any(path.rglob("*.py")):
                shadow_errors.append(
                    f"Shadow-tree detected: {path} contains .py files. "
                    f"Canonical location is agent/{d}/."
                )
        for f in forbidden_files:
            path = root / f
            if path.exists():
                shadow_errors.append(
                    f"Shadow file detected at repo root: {path}. "
                    f"Canonical location is agent/{f}."
                )
        return shadow_errors

    errors.extend(_check_no_root_python_shadows())

    # --- Rule 5: agent_messages.py resurrection guard (Sprint 04.14) ----------
    errors.extend(_check_no_agent_messages_resurrection())

    # --- Collect plist labels -----------------------------------------------
    # Search all known plist locations relative to the repo root.
    # Runner may be invoked from inside agent/ or from repo root.
    search_roots = [
        Path(__file__).resolve().parent.parent.parent.parent,  # repo root
        Path(__file__).resolve().parent.parent.parent,          # agent/ subdir
        Path.cwd(),
    ]
    plist_labels: set[str] = set()
    plist_files_found: list[str] = []
    for root in search_roots:
        for pattern in (
            "agent/scripts/com.bumba.agent-*.plist",
            "agent/config/launchdaemons/com.bumba.agent-*.plist",
            "scripts/com.bumba.agent-*.plist",
        ):
            for plist in _glob.glob(str(root / pattern)):
                plist_files_found.append(plist)
                m = re.search(r"com\.bumba\.agent-([^./]+)\.plist", plist)
                if m:
                    plist_labels.add(m.group(1))

    # Documented on-demand / infrastructure plists that have no SERVICE_MAP entry.
    # These are intentional and do not represent orphan drift.
    ON_DEMAND_PLISTS: frozenset[str] = frozenset({
        "bridge",        # main bridge daemon — not a scheduled service
        "maintenance",   # cron maintenance task — not in SERVICE_MAP
        "cost-rollup",   # standalone cron script — not in SERVICE_MAP
        "monitor",       # monitoring daemon — not in SERVICE_MAP
        "oauth-refresh", # standalone token refresh — not in SERVICE_MAP
        "deploy-helper", # on-demand deploy helper
        "experiment",    # experiment-loop is a standalone cron script (scripts/experiment_loop.py), not a ServiceBase subclass
        # consolidation variants that run via their own plists
        "consolidation-deep",
        "consolidation-micro",
        "consolidation-standard",
        # weekly CEO review is a Z4 service with a custom plist
        "weekly-ceo-review",
        # job-execute plist maps to job_search_execute via SERVICE_ALIASES (not a direct key)
        "job-execute",
    })

    # SERVICE_MAP keys that are invoked programmatically (no plist required).
    ON_DEMAND_KEYS: frozenset[str] = frozenset({
        "consolidation",        # on-demand internal service — no launchd plist
        "job_search_execute",    # called by job-execute plist but key uses underscore
        "funnel_post",
        "weekly_ceo_review",
    })

    # --- Rule 1: plist → SERVICE_MAP -----------------------------------------
    for label in plist_labels:
        if label in ON_DEMAND_PLISTS:
            continue
        # Normalize hyphen → underscore for SERVICE_MAP lookup
        normalized = label.replace("-", "_")
        if label not in SERVICE_MAP and normalized not in SERVICE_MAP:
            errors.append(
                f"RULE1: plist com.bumba.agent-{label} has no SERVICE_MAP entry "
                f"(tried keys '{label}' and '{normalized}')"
            )

    # --- Rule 2: SERVICE_MAP → plist ------------------------------------------
    for key in SERVICE_MAP:
        if key in ON_DEMAND_KEYS:
            continue
        # Normalize underscore → hyphen for plist label lookup
        plist_key = key.replace("_", "-")
        if plist_key not in plist_labels and key not in plist_labels:
            errors.append(
                f"RULE2: SERVICE_MAP[{key!r}] has no corresponding plist "
                f"(tried labels '{key}' and '{plist_key}')"
            )

    # --- Rule 3: constructor must accept data_dir ----------------------------
    for key, (module_path, class_name) in SERVICE_MAP.items():
        try:
            mod = importlib.import_module(module_path)
            cls = getattr(mod, class_name)
            sig = inspect.signature(cls.__init__)
            params = list(sig.parameters.keys())
            if "data_dir" not in params:
                errors.append(
                    f"RULE3: {class_name}.__init__ missing 'data_dir' param "
                    f"(has: {params})"
                )
        except Exception as e:
            errors.append(f"RULE3: cannot inspect {key} ({module_path}:{class_name}): {e}")

    # --- Rule 4: run() must be annotated → ServiceResult or bool -------------
    for key, (module_path, class_name) in SERVICE_MAP.items():
        try:
            mod = importlib.import_module(module_path)
            cls = getattr(mod, class_name)
            run_fn = getattr(cls, "run", None)
            if run_fn is None:
                errors.append(f"RULE4: {class_name} has no run() method")
                continue
            hints = getattr(run_fn, "__annotations__", {})
            ret = hints.get("return")
            if ret is None:
                # Missing annotation is non-fatal — services mid-migration
                # may not yet have it; warn rather than error
                print(
                    f"  [WARN] {key}: {class_name}.run() has no return annotation "
                    f"(expected ServiceResult)"
                )
            else:
                ret_str = str(ret)
                if "ServiceResult" not in ret_str and "bool" not in ret_str:
                    errors.append(
                        f"RULE4: {class_name}.run() return annotation is {ret_str!r}, "
                        f"expected ServiceResult or bool"
                    )
        except Exception as e:
            errors.append(f"RULE4: cannot inspect {key} ({module_path}:{class_name}): {e}")

    # --- Report ---------------------------------------------------------------
    if plist_files_found:
        print(f"  [INFO] scanned {len(plist_files_found)} plist(s), found {len(plist_labels)} unique label(s)")
    else:
        print("  [WARN] no plist files found — Rule 1 and Rule 2 skipped")

    # Legacy import check (Rule 0) — keep backwards compat
    import_ok = True
    for name in sorted(SERVICE_MAP.keys()):
        module_path, class_name = SERVICE_MAP[name]
        try:
            mod = importlib.import_module(module_path)
            getattr(mod, class_name)
            print(f"  [PASS] {name}: {module_path}:{class_name}")
        except Exception as e:
            print(f"  [FAIL] {name}: {module_path}:{class_name} — {e}")
            import_ok = False

    if errors:
        print(f"\nStructural validation found {len(errors)} error(s):", file=sys.stderr)
        for err in errors:
            print(f"  VALIDATE_ERROR: {err}", file=sys.stderr)
        return False

    print(
        f"\nvalidate: OK ({len(SERVICE_MAP)} services, {len(plist_labels)} plists, "
        f"all 5 structural rules passed)"
    )
    return import_ok


def _install_signal_handlers(loop: asyncio.AbstractEventLoop) -> None:
    """Install SIGTERM/SIGINT handlers that set the shutdown event."""
    def _handle_signal() -> None:
        log.info("Received shutdown signal, finishing current service...")
        _shutdown_event.set()

    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, _handle_signal)


async def _async_main(name: str, extra_kwargs: dict | None = None) -> None:
    """Async entry point with signal handling."""
    loop = asyncio.get_running_loop()
    _install_signal_handlers(loop)

    log.info(
        "service.start",
        extra={"service": name, "pid": os.getpid()},
    )

    # Check if shutdown was requested before we start
    if _shutdown_event.is_set():
        log.info("Shutdown requested before service start, exiting")
        return

    # Check halt flag — operator-set bridge halt propagates to services
    halt_flag = DATA_DIR / "halt.flag"
    if halt_flag.exists():
        log.warning(
            "Halt flag set (%s) — skipping service %s",
            halt_flag,
            name,
        )
        return

    # Guard: deferred services exit cleanly rather than attempting instantiation.
    # The plist for these services should be unloaded; this guard is a belt-and-
    # suspenders safety net in case a stale plist fires before the operator
    # removes it.
    if name in DEFERRED_SERVICES:
        log.warning(
            "service.deferred: %s is deferred pending upstream wiring. "
            "Plist should be unloaded. Exiting without running.",
            name,
        )
        return

    try:
        await run_service_with_timeout(name, extra_kwargs=extra_kwargs)
    except asyncio.TimeoutError:
        log.error("Service %s timed out", name)
        sys.exit(1)
    except Exception as e:
        log.error("Service %s failed: %s", name, e, exc_info=True)
        sys.exit(1)


def _build_arg_parser() -> argparse.ArgumentParser:
    """Build the argparse parser for trailing service flags (argv[2:]).

    Sprint 02.02: ``--mode`` is currently consumed only by the consolidation
    service. Three plists (``com.bumba.agent-consolidation-{micro,standard,deep}``)
    each pass ``--mode <value>`` after the service name; before this sprint
    those tokens were silently dropped, so all three cadences ran the
    default ``standard`` pipeline.

    All flags are optional, so services that don't pass them keep working
    unchanged.
    """
    parser = argparse.ArgumentParser(
        prog="bridge.services.runner",
        description="Universal service runner trailing flags (after <service_name>).",
    )
    parser.add_argument(
        "--mode",
        choices=["micro", "standard", "deep"],
        default=None,
        required=False,
        help="Consolidation mode override (consolidation service only).",
    )
    return parser


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python -m bridge.services.runner <service_name> [--mode {micro,standard,deep}]")
        print("       python -m bridge.services.runner --list")
        print("       python -m bridge.services.runner --validate")
        sys.exit(1)

    arg = sys.argv[1]

    if arg == "--list":
        list_services()
        return

    if arg == "--validate":
        ok = validate_services()
        sys.exit(0 if ok else 1)

    name = _resolve_service_name(arg)
    _setup_logging(name)

    # Sprint 02.02: parse trailing flags (argv[2:]) so the three consolidation
    # plists' ``--mode`` argument actually reaches the constructor. Currently
    # only consolidation consumes any flag; others ignore it.
    parser = _build_arg_parser()
    args = parser.parse_args(sys.argv[2:])

    extra_kwargs: dict | None = None
    if name == "consolidation" and args.mode is not None:
        extra_kwargs = {"mode": args.mode}

    asyncio.run(_async_main(name, extra_kwargs=extra_kwargs))


if __name__ == "__main__":
    main()
