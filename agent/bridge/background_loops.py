"""Background timer loops extracted from BridgeApp.

These loops run as asyncio tasks and are not on the critical message path.
They use shutdown_event for graceful termination.
"""

from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path

from ._async_supervision import spawn_background_task

logger = logging.getLogger(__name__)

# MCP crash-loop alert throttle — once per hour
_last_mcp_alert_time: float = 0.0
_MCP_ALERT_COOLDOWN = 3600  # seconds

DECAY_INTERVAL = 86400       # 24 h
BACKUP_INTERVAL = 86400      # 24 h
REFLECTION_INTERVAL = 86400  # 24 h
DRIFT_INTERVAL = 21600       # 6 h — runtime drift check cadence (issue #832)
WARM_CLAUDE_HEALTH_INTERVAL = 30  # 30 s — warm-process proactive health check (Sprint D8.4)
CHIEF_SESSION_REAPER_INTERVAL = 60.0  # 60 s — idle-timeout reaper sweep cadence (Z4-S30 #1391)


async def decay_loop(shutdown_event: asyncio.Event, memory) -> None:
    """Run salience decay sweep every 24 hours."""
    while not shutdown_event.is_set():
        try:
            await asyncio.wait_for(shutdown_event.wait(), timeout=DECAY_INTERVAL)
            return  # Shutdown signaled
        except asyncio.TimeoutError:
            pass  # interval elapsed — run sweep
        if memory:
            try:
                result = await memory.run_decay_sweep()
                logger.info("Daily decay sweep: %s", result)
            except Exception as e:
                logger.warning("Daily decay sweep failed: %s", e)


async def backup_loop(shutdown_event: asyncio.Event, db, config) -> None:
    """Daily database backup with verification and rotation."""
    from .database import Database

    while not shutdown_event.is_set():
        try:
            await asyncio.wait_for(shutdown_event.wait(), timeout=BACKUP_INTERVAL)
            return  # Shutdown signaled
        except asyncio.TimeoutError:
            pass  # interval elapsed — run backup
        if db and config:
            try:
                backup_dir = Path(config.data_dir) / "backups"
                backup_dir.mkdir(exist_ok=True)
                timestamp = time.strftime("%Y%m%d-%H%M%S")
                dest = backup_dir / f"memory-{timestamp}.db"
                path, ok = await db.backup_with_verify(str(dest))
                if ok:
                    removed = Database.rotate_backups(backup_dir)
                    logger.info("Backup created: %s (removed %d old)", path, removed)
                else:
                    logger.error("Backup integrity check FAILED: %s", path)
            except Exception as e:
                logger.error("Backup failed: %s", e)


async def reflection_loop(
    shutdown_event: asyncio.Event,
    reflection_store,
    *,
    cost_tracker=None,
    routing_feedback=None,
    few_shot_store=None,
    event_bus=None,
    memory=None,
) -> None:
    """Run weekly reflection check — fires once per week per ISO week number.

    Checks daily; if the current ISO week has no stored reflection yet,
    gathers real metrics from the wired data sources via
    :mod:`bridge.reflection_gatherer` and stores a reflection. Each source
    is optional — missing sources are recorded in the reflection's
    ``patterns`` field rather than silently ignored.

    Does nothing if ``reflection_store`` is None.
    """
    from .reflection import make_week_key, ReflectionResult
    from .reflection_gatherer import GatherDeps, gather_week_data

    while not shutdown_event.is_set():
        try:
            await asyncio.wait_for(shutdown_event.wait(), timeout=REFLECTION_INTERVAL)
            return  # Shutdown signaled
        except asyncio.TimeoutError:
            pass  # 24h elapsed — check if reflection is due

        if not reflection_store:
            continue

        try:
            week_key = make_week_key()
            existing = reflection_store.get_reflection(week_key)
            if existing is not None:
                logger.debug("Reflection already stored for %s — skipping", week_key)
                continue

            # Pre-resolve async memory counts so the sync gatherer can read them.
            knowledge_count, conversation_count = await _resolve_memory_counts(memory)

            week_data = gather_week_data(
                GatherDeps(
                    cost_tracker=cost_tracker,
                    routing_feedback=routing_feedback,
                    few_shot_store=few_shot_store,
                    event_bus=event_bus,
                    knowledge_count=knowledge_count,
                    conversation_count=conversation_count,
                )
            )

            # Pre-format the gathered metrics into the existing
            # ReflectionResult schema (we deliberately do NOT change the
            # reflections-table schema here).
            improvements = (
                ["Wire additional data sources: "
                 + ", ".join(week_data.notes)]
                if week_data.notes
                else []
            )
            patterns: list[str] = []
            if week_data.error_event_count > 0:
                patterns.append(
                    f"{week_data.error_event_count} error/fail events in last 7 days"
                )
            if week_data.model_success_rates:
                pretty = ", ".join(
                    f"{tier}={rate:.0%}"
                    for tier, rate in week_data.model_success_rates
                )
                patterns.append(f"Model success rates: {pretty}")

            result = ReflectionResult(
                week_key=week_key,
                achievements=list(week_data.achievements),
                improvements=improvements,
                patterns=patterns,
                recommendations=[],
                raw_text=(
                    f"Auto-generated reflection for {week_key}. "
                    f"Sources: cost_tracker={'ok' if cost_tracker else 'off'}, "
                    f"routing_feedback={'ok' if routing_feedback else 'off'}, "
                    f"few_shot={'ok' if few_shot_store else 'off'}, "
                    f"event_bus={'ok' if event_bus else 'off'}, "
                    f"memory={'ok' if memory else 'off'}."
                ),
            )
            reflection_store.store_reflection(result)
            logger.info("Weekly reflection stored: %s", week_key)
        except Exception as e:
            logger.warning("Weekly reflection failed: %s", e)


async def _resolve_memory_counts(memory) -> tuple[int | None, int | None]:
    """Resolve knowledge and conversation counts from the async Memory.

    Returns ``(None, None)`` if memory is missing; (count, None) etc. when a
    single sub-query fails. Failures are logged but never raised.
    """
    if memory is None or not hasattr(memory, "_db"):
        return None, None
    knowledge_count: int | None = None
    conversation_count: int | None = None
    try:
        row = await memory._db.fetchone(
            "SELECT COUNT(*) FROM knowledge "
            "WHERE archived IS NULL OR archived = 0"
        )
        knowledge_count = int(row[0]) if row else 0
    except Exception as exc:
        logger.warning("reflection_loop: knowledge count failed: %s", exc)
    try:
        row = await memory._db.fetchone("SELECT COUNT(*) FROM messages")
        conversation_count = int(row[0]) if row else 0
    except Exception as exc:
        logger.warning("reflection_loop: conversation count failed: %s", exc)
    return knowledge_count, conversation_count


async def heartbeat_loop(
    shutdown_event: asyncio.Event,
    config,
    *,
    autonomy=None,
    discord=None,
    runbook_engine=None,
    tmux_agents=None,
    mcp_monitor=None,
    security=None,
) -> None:
    """Write heartbeat timestamp, run escalation scans, resource checks, MCP monitoring, and remote halt check."""
    import aiohttp
    from .resource_manager import check_disk_usage, rotate_jsonl, rotate_logs

    heartbeat_path = Path(config.data_dir) / "heartbeat"
    heartbeat_count = 0
    remote_halt_next_check = 0.0
    # Issue #1543 — throttle MCP health check on its own interval rather
    # than firing on every heartbeat tick. 0.0 means "fire on the first
    # tick" so the loop still produces an initial check at startup.
    mcp_next_check = 0.0

    # Create a persistent aiohttp session for remote halt checks
    session: aiohttp.ClientSession | None = None
    if config.remote_halt_url:
        session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10))

    try:
        while not shutdown_event.is_set():
            try:
                heartbeat_path.write_text(
                    time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
                )
            except OSError as e:
                logger.error("Heartbeat write failed: %s", e)

            # Remote halt check (throttled by interval)
            now = time.monotonic()
            if security and config.remote_halt_url and session and now >= remote_halt_next_check:
                try:
                    if await security.check_remote_halt(session):
                        security.set_halt("Remote halt endpoint activated")
                        if autonomy and autonomy.event_bus:
                            autonomy.event_bus.publish("security.remote_halt_activated", {
                                "url": config.remote_halt_url,
                                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                            })
                        if discord and config.operator_discord_id:
                            await discord.send_message(
                                config.operator_discord_id,
                                "[SECURITY] Remote halt activated\n\n"
                                f"Endpoint: {config.remote_halt_url}\n"
                                f"Timestamp: {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())}"
                            )
                except Exception as e:
                    logger.warning("Remote halt check iteration failed: %s", e)
                remote_halt_next_check = now + config.remote_halt_check_interval

            # Escalation scan
            if autonomy and discord and config:
                try:
                    states = autonomy.escalation.scan_service_states()
                    new_alerts = autonomy.escalation.evaluate_triggers(states)
                    autonomy.escalation.check_de_escalation(states)

                    if new_alerts:
                        deliver, deferred = autonomy.escalation.apply_quiet_hours(new_alerts)
                        for alert in deliver:
                            formatted = autonomy.escalation.format_alert(alert)
                            if not formatted:
                                continue
                            # Append runbook diagnosis if a matching runbook exists
                            if runbook_engine:
                                try:
                                    health_state = dict(states.get(alert.source, {})) if hasattr(alert, 'source') else {}
                                    matched = runbook_engine.match_triggers(health_state)
                                    if matched:
                                        rb = matched[0]
                                        diag_result = await runbook_engine.execute_runbook(rb)
                                        formatted += f"\n\n**Diagnosis — {diag_result.runbook_name}:**\n{diag_result.format_summary()}"
                                except Exception as _diag_err:
                                    logger.debug("Runbook diagnosis skipped: %s", _diag_err)
                            await discord.send_message(
                                config.operator_discord_id, formatted
                            )
                except Exception as e:
                    logger.warning("Escalation scan failed: %s", e)

            # Monitor tmux agents
            if tmux_agents:
                try:
                    changes = await tmux_agents.monitor_agents()
                    for msg in changes:
                        logger.info("Agent monitor: %s", msg)
                except Exception as e:
                    logger.warning("Agent monitor failed: %s", e)

            # Resource management — log rotation + disk check every 10 heartbeats
            heartbeat_count += 1
            if heartbeat_count % 10 == 0:
                try:
                    log_dir = Path(config.log_dir)
                    rot_result = rotate_logs(log_dir)
                    if rot_result.get("rotated", 0) > 0 or rot_result.get("deleted", 0) > 0:
                        logger.info("Log rotation: %d rotated, %d deleted",
                                    rot_result.get("rotated", 0), rot_result.get("deleted", 0))
                    # Sprint 07.01 — rotate append-only jsonl files in data/ via
                    # explicit filename allowlist (traces.jsonl, metrics.jsonl,
                    # cost_tracking.jsonl, bridge-metrics.jsonl, events.jsonl).
                    data_dir = Path(config.data_dir)
                    jsonl_result = rotate_jsonl(data_dir)
                    if jsonl_result.get("rotated", 0) > 0 or jsonl_result.get("deleted", 0) > 0:
                        logger.info(
                            "JSONL rotation: %d rotated, %d deleted",
                            jsonl_result.get("rotated", 0),
                            jsonl_result.get("deleted", 0),
                        )
                    disk = check_disk_usage("/")
                    if disk["used_pct"] >= 90.0:
                        logger.warning("Disk usage critical: %.1f%%", disk["used_pct"])
                        if discord and config:
                            await discord.send_alert(
                                f"Disk usage critical: {disk['used_pct']:.1f}% used "
                                f"({disk['free_gb']:.1f}GB free of {disk['total_gb']:.1f}GB)"
                            )
                except Exception as e:
                    logger.warning("Resource management check failed: %s", e)

            # MCP server health check — issue #1543 throttles on its own
            # interval so the loop still ticks at heartbeat_interval for
            # other tasks (escalation scan, remote halt, log rotation)
            # without pgrep-thrashing the host on every heartbeat.
            mcp_interval_raw = getattr(
                config, "mcp_health_check_interval_seconds", 300
            )
            mcp_interval = (
                float(mcp_interval_raw)
                if isinstance(mcp_interval_raw, (int, float))
                else 300.0
            )
            now_mono = time.monotonic()
            if mcp_monitor and now_mono >= mcp_next_check:
                try:
                    global _last_mcp_alert_time
                    await mcp_monitor.check_server_health()
                    # Emit EscalationEngine-readable state file. No-op
                    # when MCPMonitor was constructed without state_dir.
                    try:
                        mcp_monitor.record_health_state()
                    except Exception as exc:
                        logger.debug("MCPMonitor state record failed: %s", exc)
                    summary = mcp_monitor.get_status_summary()
                    crash_count = summary.get("crash_loop", 0)
                    if crash_count > 0:
                        unhealthy = mcp_monitor.get_unhealthy_servers()
                        logger.warning(
                            "MCP crash loops detected: %s — servers: %s",
                            summary,
                            unhealthy,
                        )
                        now = time.time()
                        if discord and config and (now - _last_mcp_alert_time >= _MCP_ALERT_COOLDOWN):
                            server_list = ", ".join(unhealthy) if unhealthy else "unknown"
                            await discord.send_alert(
                                f"MCP server crash loop detected: "
                                f"{crash_count} server(s) in crash loop — [{server_list}]"
                            )
                            _last_mcp_alert_time = now
                    else:
                        # Reset throttle when all crash loops resolve
                        _last_mcp_alert_time = 0.0
                except Exception as e:
                    logger.debug("MCP health check failed: %s", e)
                mcp_next_check = now_mono + mcp_interval


            try:
                await asyncio.wait_for(
                    shutdown_event.wait(),
                    timeout=config.heartbeat_interval,
                )
                return  # Shutdown signaled
            except asyncio.TimeoutError:
                pass  # Continue loop
    finally:
        if session and not session.closed:
            await session.close()


CONSOLIDATION_INTERVAL = 86400  # 24 h — run consolidation pipeline daily
CONSOLIDATION_WARMUP = 300      # 5 min — startup-prime delay before first run


async def _run_consolidation_once(db, memory) -> None:
    """Run the consolidation pipeline once. Extracted from consolidation_loop
    so the pipeline body is independently testable and so the loop can prime
    itself with one run shortly after startup.
    """
    from . import consolidation

    try:
        rows = await memory.fetch_all_knowledge_rows()
        if not rows:
            logger.debug("Consolidation: no rows to process")
            return

        report = await asyncio.to_thread(
            consolidation.run_pipeline, rows, mode="standard"
        )
        logger.info(
            "Consolidation pipeline complete: %dms, mode=%s",
            report.total_duration_ms,
            report.mode,
        )

        # Apply decay results — update salience for decayed rows, archive pruned rows
        decay_result = report.phase_results.get("decay")
        if decay_result:
            for row in rows:
                action = row.get("_action")
                new_sal = row.get("_new_salience")
                if action == "prune":
                    await db.execute(
                        "UPDATE knowledge SET salience = ?, archived = 1, "
                        "updated_at = datetime('now') WHERE key = ?",
                        (new_sal, row["key"]),
                    )
                elif action == "decay" and new_sal is not None:
                    await db.execute(
                        "UPDATE knowledge SET salience = ?, "
                        "updated_at = datetime('now') WHERE key = ?",
                        (new_sal, row["key"]),
                    )

        # Apply merge results — archive duplicates
        merge_result = report.phase_results.get("merge")
        if merge_result:
            for row in rows:
                if row.get("_merge_action") == "archive":
                    await db.execute(
                        "UPDATE knowledge SET archived = 1, "
                        "updated_at = datetime('now') WHERE key = ?",
                        (row["key"],),
                    )

        await db.commit()
        logger.info("Consolidation results written to DB")

    except Exception as exc:
        logger.error("Consolidation loop error: %s", exc)


async def consolidation_loop(shutdown_event: asyncio.Event, db, memory) -> None:
    """Run the knowledge consolidation pipeline daily, with a startup priming pass.

    On bridge restart, the loop sleeps CONSOLIDATION_WARMUP seconds (default 300s
    = 5 min), runs _run_consolidation_once() once, then enters the normal
    CONSOLIDATION_INTERVAL (24h) cycle. The priming pass ensures the consolidation
    pipeline runs at least once per bridge lifetime even if the bridge restarts
    daily, instead of waiting up to 24 hours after every restart.

    Uses consolidation.run_pipeline() on all non-archived knowledge rows.
    Applies decay and merge results back to the DB.
    """
    logger.info(
        "Consolidation loop started; first run in %ds", CONSOLIDATION_WARMUP
    )

    # Startup priming: wait CONSOLIDATION_WARMUP seconds (or until shutdown), then run once
    try:
        await asyncio.wait_for(
            asyncio.shield(shutdown_event.wait()), timeout=CONSOLIDATION_WARMUP
        )
        return  # Shutdown signaled during warmup
    except asyncio.TimeoutError:
        pass  # Warmup elapsed — run priming pass

    if shutdown_event.is_set():
        return

    await _run_consolidation_once(db, memory)

    # Normal daily cycle
    while not shutdown_event.is_set():
        try:
            await asyncio.wait_for(
                asyncio.shield(shutdown_event.wait()), timeout=CONSOLIDATION_INTERVAL
            )
            return  # Shutdown signaled
        except asyncio.TimeoutError:
            pass  # 24h elapsed — run pipeline

        if shutdown_event.is_set():
            return

        await _run_consolidation_once(db, memory)


async def drift_loop(
    shutdown_event: asyncio.Event,
    *,
    discord=None,
    config=None,
) -> None:
    """Run source-vs-runtime drift check every 6 hours (issue #832).

    Calls :func:`bridge.runtime_drift.compute_drift_report` against the
    canonical SOURCE_ROOT / RUNTIME_ROOT pair. The loop is automatically
    dormant when either path is absent (e.g. dev workstations) — this
    keeps the loop a no-op in test/dev environments without requiring a
    feature flag.

    Behaviour:

    - Every iteration logs a short summary at INFO regardless of clean/dirty.
    - When ``not report.is_clean`` and a Discord client + operator id are
      configured, posts a single alert message via ``discord.send_alert``
      (preferred) or ``discord.send_message`` (fallback).
    """
    from .runtime_drift import RUNTIME_ROOT, SOURCE_ROOT, compute_drift_report

    while not shutdown_event.is_set():
        try:
            await asyncio.wait_for(shutdown_event.wait(), timeout=DRIFT_INTERVAL)
            return  # Shutdown signaled
        except asyncio.TimeoutError:
            pass  # interval elapsed — run drift check

        # Dormant in dev: skip when either canonical root is missing.
        if not (SOURCE_ROOT.exists() and RUNTIME_ROOT.exists()):
            logger.debug(
                "drift_loop: SOURCE_ROOT (%s) or RUNTIME_ROOT (%s) missing — "
                "skipping (likely dev environment).",
                SOURCE_ROOT,
                RUNTIME_ROOT,
            )
            continue

        try:
            report = await asyncio.to_thread(
                compute_drift_report, SOURCE_ROOT, RUNTIME_ROOT
            )
        except Exception as exc:
            logger.warning("drift_loop: compute_drift_report raised: %s", exc)
            continue

        logger.info("drift_loop: %s", report.summary())

        if report.is_clean:
            continue

        # Drift detected — alert the operator if Discord is wired.
        if discord is None:
            continue

        msg = (
            "[DRIFT] Source ↔ runtime mismatch detected.\n"
            f"{report.summary()}"
        )
        try:
            send_alert = getattr(discord, "send_alert", None)
            if callable(send_alert):
                await send_alert(msg)
            elif config is not None and getattr(config, "operator_discord_id", None):
                await discord.send_message(config.operator_discord_id, msg)
        except Exception as exc:
            logger.warning("drift_loop: failed to send Discord alert: %s", exc)


async def warm_claude_health_loop(
    shutdown_event: asyncio.Event,
    warm_claude_provider,  # callable returning current WarmClaudeProcess or None
) -> None:
    """Periodically check warm Claude process health; trigger respawn if dead.

    Sprint D8.4 — proactive crash detection so a dead warm process is healed
    before the next operator message arrives. Reactive respawn from
    ``_stdout_reader`` (D8.3) handles the common case; this loop catches edge
    cases where reactive respawn failed or never fired.

    Uses a callable provider rather than a direct reference so it picks up
    swaps from D8.2's token-refresh double-buffer pattern (where
    ``app._warm_claude`` is reassigned to a new instance).
    """
    while not shutdown_event.is_set():
        try:
            await asyncio.wait_for(
                shutdown_event.wait(), timeout=WARM_CLAUDE_HEALTH_INTERVAL
            )
            return  # shutdown signaled
        except asyncio.TimeoutError:
            pass  # interval elapsed — run health check

        try:
            warm = warm_claude_provider()
        except Exception as exc:  # noqa: BLE001
            logger.warning("warm_claude_health_loop: provider raised: %s", exc)
            continue

        if warm is None:
            continue  # voice-style "not configured" path

        if warm.is_alive:
            continue  # healthy

        # Dead. Check if a respawn is already in progress (D8.3 flag).
        if getattr(warm, "_respawn_in_progress", False):
            logger.debug(
                "warm_claude_health_loop: respawn already in progress, skipping"
            )
            continue

        # Skip if never spawned (fresh instance with no working_dir).
        working_dir = getattr(warm, "_working_dir", "")
        if not working_dir:
            continue

        logger.warning(
            "warm_claude_health_loop: warm process is dead and no respawn in "
            "progress, scheduling one"
        )
        try:
            warm._respawn_in_progress = True
            spawn_background_task(
                warm._background_respawn(),  # added by D8.3
                name="warm-claude-health-respawn",
                logger=logger,
            )
        except AttributeError:
            # D8.3 not yet merged — fall back to direct spawn().
            logger.info(
                "warm_claude_health_loop: _background_respawn not available, "
                "using spawn()"
            )
            spawn_background_task(
                warm.spawn(
                    working_dir,
                    getattr(warm, "_model", "haiku"),
                    getattr(warm, "_system_prompt_file", None),
                ),
                name="warm-claude-health-spawn",
                logger=logger,
            )


def _resolve_team_idle_timeout(
    department: str,
    global_timeout_seconds: float,
    department_registry,
) -> float:
    """Return the effective warm-idle timeout for ``department``.

    zone4-warmth.D.01 (#2299) per-team override resolver. Looks up the
    department's YAML config via the registry and returns
    ``constraints.warm_idle_timeout_seconds`` when set, else falls back
    to ``global_timeout_seconds`` (the
    ``chief_dispatcher_idle_timeout_seconds`` bridge config).

    Failure modes (unknown department, missing constraints, registry
    None) all silently fall through to the global so the reaper still
    reaps stale sessions even when registry wiring is degraded.
    """
    if department_registry is None:
        return global_timeout_seconds
    try:
        team_cfg = department_registry.get_config(department)
    except (KeyError, AttributeError):
        return global_timeout_seconds
    per_team = getattr(team_cfg.constraints, "warm_idle_timeout_seconds", None)
    if per_team is None:
        return global_timeout_seconds
    return float(per_team)


def _min_sweep_threshold(
    global_timeout_seconds: float,
    department_registry,
) -> float:
    """Return the smallest configured idle timeout across all departments.

    The reaper uses this as its ``list_idle(older_than_seconds=...)``
    SQL filter so departments with short overrides (e.g. ops/job_search
    at 600s) get swept on the same tick a 4h-window department would
    not. Per-team enforcement happens in Python on the returned
    candidate set.
    """
    if department_registry is None:
        return global_timeout_seconds
    smallest = global_timeout_seconds
    try:
        dept_names = department_registry.department_names()
    except AttributeError:
        return global_timeout_seconds
    for name in dept_names:
        try:
            cfg = department_registry.get_config(name)
        except (KeyError, AttributeError):
            continue
        per_team = getattr(cfg.constraints, "warm_idle_timeout_seconds", None)
        if per_team is not None and per_team < smallest:
            smallest = float(per_team)
    return smallest


async def chief_session_reaper_loop(
    shutdown_event: asyncio.Event,
    *,
    chief_session_store,
    idle_timeout_seconds: float,
    event_bus=None,
    department_registry=None,
    poll_interval: float = CHIEF_SESSION_REAPER_INTERVAL,
) -> None:
    """Sweep for idle ``ChiefSession`` rows and shut them down (Z4-S30 #1391).

    Runs every ``poll_interval`` seconds (default 60s). On each tick the
    reaper queries
    ``chief_session_store.list_idle(older_than_seconds=idle_timeout_seconds)``
    and, for every returned session:

    1. Transitions ``AWAITING_EVALUATION`` -> ``TIMED_OUT`` (persists via
       ``store.update``).
    2. Transitions ``TIMED_OUT`` -> ``SHUTDOWN`` (persists again).
    3. Clears the persisted ``message_history_blob`` to NULL
       (zone4-warmth.D.01) and publishes ``chief_session.history_cleared``.
    4. Publishes a ``chief_session.timed_out`` event on ``event_bus`` (if
       wired) carrying ``session_id``, ``work_order_id``, ``idle_seconds``,
       and ``department``.

    The state machine in ``bridge.chief_session`` requires going through
    ``TIMED_OUT`` before ``SHUTDOWN`` — we cannot skip. Two transitions
    per reaping is the contract, not an oversight.

    Best-effort everywhere: any exception from the store, transition, or
    bus is caught and logged; one bad row never kills the loop, and one
    bad sweep never kills the bridge.

    The reaper is intentionally store-only — it does **not** call into
    ``ChiefDispatcher.shutdown_session()`` so the loop stays self-contained
    and testable without spinning up the full dispatcher trio.

    Args:
        shutdown_event: Set by the bridge during graceful shutdown to
            terminate the loop.
        chief_session_store: Any object implementing the
            ``ChiefSessionStore`` protocol — the in-memory and SQLite-backed
            stores both qualify.
        idle_timeout_seconds: Sessions in ``AWAITING_EVALUATION`` whose
            ``idle_since_utc`` is older than this threshold are reaped.
            zone4-warmth.D.01 (#2299): this is the *global default*;
            per-team overrides take precedence when
            ``department_registry`` is passed and the team's YAML declares
            ``constraints.warm_idle_timeout_seconds``.
        event_bus: Optional ``EventBus``. When ``None``, timeouts are
            still applied; the event is dropped at debug level.
        department_registry: Optional ``DepartmentRegistry`` — when wired,
            per-team ``warm_idle_timeout_seconds`` overrides apply. When
            ``None`` (legacy callers / tests), every session uses the
            global ``idle_timeout_seconds`` threshold.
        poll_interval: Seconds between sweeps. Defaults to
            ``CHIEF_SESSION_REAPER_INTERVAL`` (60s); tests pin this lower.
    """
    from datetime import datetime, timezone

    from bridge.chief_session import ChiefSessionState

    logger.info(
        "chief_session_reaper_loop started "
        "(idle_timeout=%.0fs, poll=%.0fs, per_team_overrides=%s)",
        idle_timeout_seconds,
        poll_interval,
        department_registry is not None,
    )

    # do-while over the shutdown event so a pre-set event still runs one
    # final sweep — matches the existing pattern of "drain on the way out"
    # and lets unit tests pin the loop to a single iteration by calling
    # ``shutdown_event.set()`` before invoking the loop.
    while True:
        # zone4-warmth.D.01 — sweep at the smallest configured threshold
        # across all teams so short-override departments (e.g. ops/job_search
        # at 600s) get caught on the same tick a 4h-window team would not.
        # When no registry is wired, this collapses to the global default
        # (legacy behavior).
        sweep_threshold = _min_sweep_threshold(
            idle_timeout_seconds, department_registry
        )
        try:
            idle_sessions = await chief_session_store.list_idle(
                older_than_seconds=sweep_threshold
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "chief_session_reaper_loop: list_idle failed: %s", exc
            )
            idle_sessions = []

        for session in idle_sessions:
            session_id = getattr(session, "session_id", "?")
            try:
                idle_secs = 0.0
                if session.idle_since_utc is not None:
                    now = datetime.now(timezone.utc)
                    idle_secs = (now - session.idle_since_utc).total_seconds()

                # zone4-warmth.D.01 — apply the per-team threshold. The
                # SQL filter used the smallest threshold across all teams
                # so this Python filter is what enforces each department's
                # own window. A session whose dept-specific timeout is
                # *larger* than its idle interval stays warm.
                team_timeout = _resolve_team_idle_timeout(
                    session.department,
                    idle_timeout_seconds,
                    department_registry,
                )
                if idle_secs < team_timeout:
                    continue

                logger.info(
                    "chief_session_reaper: timing out session %s "
                    "(idle=%.0fs, dept=%s, team_timeout=%.0fs)",
                    session_id,
                    idle_secs,
                    session.department,
                    team_timeout,
                )

                # Two-step transition: state machine forbids skipping
                # AWAITING_EVALUATION -> SHUTDOWN directly.
                timed_out = session.transition(ChiefSessionState.TIMED_OUT)
                await chief_session_store.update(timed_out)
                shutdown = timed_out.transition(ChiefSessionState.SHUTDOWN)
                await chief_session_store.update(shutdown)

                # zone4-warmth.D.01 — clear the persisted message_history
                # blob so stale Pydantic-AI history doesn't accumulate in
                # SQLite. Best-effort: a failure here doesn't roll back the
                # reap, since the SHUTDOWN row already records the lifecycle.
                history_cleared = False
                try:
                    await chief_session_store.update_message_history(
                        shutdown.session_id, None
                    )
                    history_cleared = True
                except Exception as clear_exc:  # noqa: BLE001
                    logger.warning(
                        "chief_session_reaper: history clear failed for %s: %s",
                        session_id,
                        clear_exc,
                    )

                if event_bus is not None:
                    if history_cleared:
                        try:
                            event_bus.publish(
                                "chief_session.history_cleared",
                                {
                                    "session_id": shutdown.session_id,
                                    "reason": "idle_timeout",
                                },
                            )
                        except Exception as bus_exc:  # noqa: BLE001
                            logger.warning(
                                "chief_session_reaper: history_cleared "
                                "publish failed for %s: %s",
                                session_id,
                                bus_exc,
                            )
                    try:
                        event_bus.publish(
                            "chief_session.timed_out",
                            {
                                "session_id": shutdown.session_id,
                                "work_order_id": shutdown.work_order_id,
                                "idle_seconds": idle_secs,
                                "department": shutdown.department,
                                "team_timeout_seconds": team_timeout,
                            },
                        )
                    except Exception as bus_exc:  # noqa: BLE001
                        logger.warning(
                            "chief_session_reaper: event publish failed "
                            "for %s: %s",
                            session_id,
                            bus_exc,
                        )
            except Exception as exc:  # noqa: BLE001
                # The session may have already been transitioned out of
                # AWAITING_EVALUATION between list_idle() and update()
                # (e.g. concurrent requeue). InvalidTransitionError is
                # the expected race — log and continue.
                logger.warning(
                    "chief_session_reaper: skipped session %s: %s",
                    session_id,
                    exc,
                )

        if shutdown_event.is_set():
            return

        try:
            await asyncio.wait_for(shutdown_event.wait(), timeout=poll_interval)
            return  # shutdown signaled mid-sleep
        except asyncio.TimeoutError:
            pass  # interval elapsed — next sweep
