"""Startup initializer for BridgeApp.

Sprint S4.1 part 1 extracts the startup spine from ``bridge.app`` while
leaving ``BridgeApp`` as the composition root and keeping ``_wire()`` in
``app.py`` for manifest auditability.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .app import (
    AgentRouter, AutonomyLayer, BudgetGuard, CircuitBreakerConfig,
    CircuitBreakerRegistry, ClaudeRunner, CommandHandler, CostAttributor,
    CostTracker, DailyLogWriter, Database, DepartmentRegistry,
    DiscordBot, FallbackChain, FewShotStore, HybridSearch,
    LocalEmbeddingEngine, MCPMonitor, Memory, MessageQueue,
    MetricsAggregator, Path, ProjectRegistry, ReflectionStore,
    ReflexionContext, ResponseEvaluator, RoutingFeedbackEngine, RunbookEngine,
    SecurityManager, SelfEditMemory, SelfVerifier, SessionHookRegistry,
    SessionManager, SessionRecoveryManager, SkillAllocator, SkillEvolutionEngine, StreamCoalescer,
    SubprocessLifecycle, TaskQueue, TemporalKnowledgeStore, TickManager,
    TokenBucket, TokenRefresher, ToolTracker, Tracer,
    WarmClaudeProcess, _PROVIDERS_AVAILABLE, _TEAMS_AVAILABLE, _TOOL_TRACKER_AVAILABLE,
    _load_provider_keys, _read_pyproject_version, _validate_backend_readiness,
    _validate_claude_oauth_required, _validate_codex_cost_readiness,
    _validate_codex_oauth, _validate_openrouter_api_key_required,
    apply_command_tier_gating, load_commands_section, logger,
    record_completed_span, time,
)
from .config import load_config

if TYPE_CHECKING:
    from .app import BridgeApp


def _warm_claude_enabled_for_config(config: object) -> bool:
    """Return whether startup should construct the persistent Claude process."""
    if not bool(getattr(config, "backends_enabled", False)):
        return True
    main_backend = str(getattr(config, "backends_main", "claude") or "claude")
    return main_backend.strip().lower() == "claude"


class BridgeAppInit:
    """Run BridgeApp startup construction in the original order."""

    def __init__(self, app: "BridgeApp") -> None:
        self._app = app

    async def run(self) -> None:
        """Load config, connect DB, migrate, create all components, wire callbacks."""
        self = self._app
        _startup_phases: list[tuple[str, float, float, dict[str, object]]] = []

        _phase_config_start = time.time()
        # Step 2-3: Load config (includes TOML + Keychain secrets)
        if self._config_path:
            self._config = load_config(self._config_path)
        else:
            self._config = load_config()
        _startup_phases.append((
            "startup.config_load",
            _phase_config_start,
            time.time(),
            {"config_path": self._config_path or "default"},
        ))

        config = self._config

        # Ensure directories exist
        Path(config.data_dir).mkdir(parents=True, exist_ok=True)
        Path(config.log_dir).mkdir(parents=True, exist_ok=True)

        # Sprint Codex-4 (issue #1838) — fail-closed validator for the Codex
        # backend's ChatGPT-OAuth credentials. Mirrors #1626's
        # ``allow_remote_bind`` and P2.3's ``vapi_webhook_secret`` pattern:
        # if any [backends] role resolves to ``codex`` (Codex-3 sibling
        # feature) and ``codex_oauth_token`` is empty in .secrets, refuse
        # to boot with an actionable error. The validator is a no-op when
        # ``backends_enabled`` is false or the Codex-3 fields are not yet
        # present on the config object — preserves legacy claude-only boot.
        _validate_codex_oauth(config)

        # Model-agnostic runtime: OpenRouter is the first HTTP backend we are
        # willing to smoke live, so fail at boot if it is active without auth.
        _validate_openrouter_api_key_required(config)

        # Backend Operability S2.1 (#2279) — make the ``readiness_for_flip``
        # guard load-bearing during startup. Pre-S2.1 a token-bearing Codex
        # config passed ``_validate_codex_oauth`` even though
        # ``codex_cost_computable()`` was False, so the daemon would boot
        # into a state where Codex turns silently report cost as ``None``
        # and budget enforcement is meaningless. Runs immediately after the
        # OAuth validator so the order matches the failure modes operators
        # surface: token missing → token present but cost not computable →
        # cost contract regressed (D.03 below).
        _validate_backend_readiness(config)

        # Sprint audit-2026-05-16.B.03 (#2052, HI-5) — fail-closed validator
        # for the Claude OAuth access token. Mirrors ``_validate_codex_oauth``
        # but without the [backends] gating: ``claude -p`` is the always-on
        # backend, so an empty ``claude_oauth_token`` is unconditionally a
        # boot blocker. Pre-B.03 the bridge would start with an empty token
        # and surface the failure on the first API call, with an opaque
        # subprocess error far from the root cause.
        _validate_claude_oauth_required(config)

        # Sprint audit-2026-05-16.D.03 (#2064) — readiness contract check
        # that runs immediately after the OAuth validator. Probes the
        # in-memory CodexBackend.parse_cost against three synthetic events
        # to verify the D.01/D.02 CostMeasurement contract is honored.
        # No I/O; same no-op posture as ``_validate_codex_oauth`` when the
        # backends registry doesn't route to codex. Without this check, a
        # silent regression in parse_cost (e.g. back to a legacy float
        # collapse) would make budget enforcement meaningless without
        # surfacing any error at boot.
        _validate_codex_cost_readiness(config)

        # #1071 Part 2 — apply slash-command tier gating from `[commands]`
        # in bridge.toml. Tier 1 + Tier 2 always live; Tier 3 entries
        # require opt-in. Failure to read the section is non-fatal —
        # default behaviour keeps Tier 3 off.
        try:
            from bridge.paths import agent_root

            commands_section = load_commands_section(
                self._config_path
                or str(agent_root() / "config" / "bridge.toml")
            )
            apply_command_tier_gating(commands_section)
        except Exception as e:  # noqa: BLE001
            logger.warning("Command tier gating failed (Tier 3 stays off): %s", e)
            apply_command_tier_gating(None)

        # Sprint 07.10 — record the running bridge version on first boot.
        # init_version reads data/version.json (written by deploy scripts) and
        # falls back to the source-tree version from pyproject.toml so /healthz
        # always advertises a meaningful version. Sets the module-level
        # _RUNNING_VERSION used by get_running_version() / health.
        from . import version as _version_mod
        _version_mod.init_version(
            data_dir=config.data_dir,
            default_version=_read_pyproject_version(),
        )

        # Load non-Anthropic provider API keys (no-op if none configured)
        if _PROVIDERS_AVAILABLE:
            try:
                _load_provider_keys()
            except Exception as e:
                logger.warning("Failed to load provider keys: %s", e)

        # Step 4: Open SQLite, run WAL pragma init
        _phase_db_start = time.time()
        db_path = str(Path(config.data_dir) / "memory.db")
        self._db = Database(db_path)
        await self._db.connect()
        await self._db.migrate()
        _startup_phases.append((
            "startup.db_migrate",
            _phase_db_start,
            time.time(),
            {"db_path": db_path},
        ))

        # Sprint 05.01 — construct LocalEmbeddingEngine + LocalEmbeddingClient
        # shim BEFORE Memory so the embedding_client kwarg can be passed at
        # construction. The engine is reused at line ~587 to avoid
        # double-construction. Per Plan 05 §05.01: pass shim at constructor
        # rather than introducing a new self._memory.set_embedding_client(...)
        # setter — keeps the wiring-manifest free of memory-internal plumbing.
        try:
            embed_cache = str(Path(config.data_dir) / "embedding_cache.db")
            # #2560 — load the configured model dir (default: embeddinggemma);
            # absence of the model file falls back to hash inside _load_model.
            self._embedding_engine = LocalEmbeddingEngine(
                model_dir=config.embedding_model_dir,
                cache_db=embed_cache,
            )
            from .embeddings import LocalEmbeddingClient
            self._embedding_client = LocalEmbeddingClient(self._embedding_engine)
        except Exception as e:
            logger.warning(
                "LocalEmbeddingEngine init failed; Memory will run FTS5-only: %s", e
            )
            self._embedding_engine = None
            self._embedding_client = None

        # Create components
        self._queue = MessageQueue(self._db)
        self._memory = Memory(self._db, config, embedding_client=self._embedding_client)
        # Board Phase 3 WS1 (#2392) — recall-usage tracker. No external deps,
        # so constructed unconditionally here; wired onto Memory via the
        # WIRING_MANIFEST (set_recall_tracker) so the wire is observable.
        from .memory.recall_learning import RecallTracker
        self._recall_tracker = RecallTracker()
        self._session_mgr = SessionManager(self._db, config)
        # #488: wire primer-write callback so session expire + /reset fire it
        self._session_mgr.set_primer_callback(self._primer_callback)
        self._security = SecurityManager(self._db, config)
        self._claude = ClaudeRunner(config)

        # P1.1 (audit C1) — unified one-shot/warm invocation state.
        # Wired into _claude immediately; into _warm_claude when it's
        # constructed below at line ~691.
        from .invocation_controller import InvocationController
        self._invocation_controller = InvocationController()
        self._claude.set_invocation_controller(self._invocation_controller)

        # D7.9 #1421 (slice 2) — wire OperatorInbox so mid-stream interrupt
        # activation (slice 1, claude_runner.invoke) can fire. One inbox per
        # bridge process; messages from Discord during an in-flight invoke
        # land here, the slice-1 poll detects them, SIGTERMs the subprocess,
        # and the bridge sends the BLOCK message to Discord. Auto-ACK after
        # delivery (in _process_single_message) clears the inbox so the next
        # dequeue processes the operator's actual message normally.
        from .operator_inbox import OperatorInbox
        self._operator_inbox = OperatorInbox(session_id="bridge")
        self._claude.set_operator_inbox(self._operator_inbox)

        # #1535 (Plan W W-1.4) — wire the DialogueDelayMonitor + force-pause
        # alerter. The monitor polls self._operator_inbox.pending() on a
        # fixed interval; when a pending message ages past
        # dialogue_delay_threshold_seconds it logs a DELAY observability
        # event, and when it ages past force_pause_threshold_seconds it
        # fires the alerter which (a) posts to Discord and (b) sets a flag
        # ClaudeRunner.invoke() checks before spawning the next subprocess.
        # The monitor itself is started/stopped per session by
        # SessionManager — see set_dialogue_delay_monitor below.
        from .claude_runner import DiscordForcePauseAlerter
        from .dialogue_delay_monitor import (
            DialogueDelayEvent,
            DialogueDelayMonitor,
        )

        # notify_fn closure: self._discord is created later (~line 707) so we
        # capture self and look it up lazily at alert time. Returns a coroutine
        # so DiscordForcePauseAlerter.alert can await it.
        async def _force_pause_notify(message: str) -> None:
            discord = self._discord
            cfg = self._config
            if discord is None or cfg is None:
                return
            channel = getattr(cfg, "operator_discord_id", "") or ""
            if not channel:
                return
            try:
                await discord.send_message(channel, message)
            except Exception:
                logger.exception(
                    "force_pause_notify: failed to post Discord alert"
                )

        self._force_pause_alerter = DiscordForcePauseAlerter(
            notify_fn=_force_pause_notify
        )
        self._claude.set_force_pause_alerter(self._force_pause_alerter)

        # Inline JSONL MetricsSink — appends one event per line to
        # data/dialogue-delay-events.jsonl. Synchronous per the MetricsSink
        # Protocol contract (no awaiting I/O on the hot path).
        _events_path = Path(config.data_dir) / "dialogue-delay-events.jsonl"

        class _JsonlDialogueDelaySink:
            def __init__(self, path: Path) -> None:
                self._path = path

            def log(self, event: DialogueDelayEvent) -> None:
                import json as _json

                try:
                    self._path.parent.mkdir(parents=True, exist_ok=True)
                    record = {
                        "msg_id": event.msg_id,
                        "severity": event.severity.value,
                        "age_seconds": event.age_seconds,
                        "kind": event.kind.value,
                        "logged_at": event.logged_at.isoformat(),
                    }
                    with self._path.open("a", encoding="utf-8") as fh:
                        fh.write(_json.dumps(record) + "\n")
                except Exception:
                    logger.exception(
                        "dialogue_delay_sink: failed to append event"
                    )

        self._dialogue_delay_monitor = DialogueDelayMonitor(
            inbox=self._operator_inbox,
            metrics_sink=_JsonlDialogueDelaySink(_events_path),
            alerter=self._force_pause_alerter,
            delay_threshold_seconds=config.dialogue_delay_threshold_seconds,
            force_pause_threshold_seconds=config.force_pause_threshold_seconds,
            poll_interval_seconds=config.interrupts_poll_interval_seconds,
            # #2207 Part A — suppress force-pause when no agent subprocess
            # is running. ClaudeRunner.is_active returns True only while a
            # subprocess is actually in flight; during idle conversational
            # sessions there's nothing to interrupt.
            is_agent_active=lambda: self._claude.is_active,
        )
        self._session_mgr.set_dialogue_delay_monitor(
            self._dialogue_delay_monitor
        )

        self._task_queue = TaskQueue(self._db)

        # Mission Control modules (Phases 3, 5, 6)
        from .task_pipeline import TaskPipeline
        self._task_pipeline = TaskPipeline(self._db)
        await self._task_pipeline.initialize()

        from .quality_gate import QualityGate
        self._quality_gate = QualityGate(self._db)
        await self._quality_gate.initialize()

        self._fallback = FallbackChain(
            api_key=config.openrouter_api_key,
            model=config.fallback_openrouter_model,
        )

        # Resilience modules
        self._budget = BudgetGuard(self._db, daily_limit=config.budget_daily_budget)
        self._breakers = CircuitBreakerRegistry()
        self._breakers.register("claude", CircuitBreakerConfig(failure_threshold=5, timeout_seconds=120, window_seconds=300))
        self._lifecycle = SubprocessLifecycle()
        self._rate_limiter = TokenBucket(capacity=10.0, refill_rate=0.5)

        # Phase 5 autonomy layer
        self._autonomy = AutonomyLayer(
            data_dir=Path(config.data_dir),
            operator_mention=config.operator_discord_id,
        )

        # Board Phase 2 WS4 / Phase 3 WS2 (#2391/#2392) — board-run store.
        from .board_run_store import BoardRunStore
        self._board_run_store = BoardRunStore(config.data_dir)

        # Webhook receiver (Phase 6) — needs task_pipeline + event_bus
        from .webhook_receiver import WebhookReceiver
        webhook_secret = getattr(config, "github_webhook_secret", "")
        self._webhook_receiver = WebhookReceiver(
            webhook_secret=webhook_secret,
            task_pipeline=self._task_pipeline,
            event_bus=self._autonomy.event_bus if self._autonomy else None,
        )

        # Sprint 14: Serial webhook event deliverer with backpressure
        # Sprint 06.06 rework: HMAC-SHA256 signing of outbound payloads
        if config.webhooks_enabled:
            from .webhook_deliverer import SerialEventDeliverer
            self._webhook_deliverer = SerialEventDeliverer(
                max_queue=config.webhooks_max_queue,
                timeout_sec=config.webhooks_timeout_sec,
                max_retries=config.webhooks_max_retries,
                webhook_secret=config.webhook_secret,
            )
            # Register webhook URLs from config
            for url in config.webhooks_urls:
                if url:
                    self._webhook_deliverer.register_webhook(url, f"config_webhook_{len(self._webhook_deliverer.list_webhooks())}")
            logger.info(f"Webhook deliverer enabled with {len(config.webhooks_urls)} configured URLs")

        # Tmux agent spawning
        from .tmux_manager import TmuxManager
        from .tmux_agents import TmuxAgentManager
        tmux = TmuxManager()
        if await tmux.is_available():
            self._tmux_agents = TmuxAgentManager(
                tmux=tmux,
                config=config,
                token_provider=None,  # Set after token_refresher is created
                autonomy=self._autonomy,
            )
            logger.info("Tmux agent spawning enabled")
        else:
            logger.info("tmux not installed — agent spawning disabled")

        # Set up token refresher if refresh token is available
        if config.claude_oauth_refresh_token:
            secrets_file = str(Path(config.data_dir) / ".secrets")

            async def _token_alert(message: str) -> None:
                if self._discord and self._config:
                    await self._discord.send_message(
                        self._config.operator_discord_id, message
                    )

            self._token_refresher = TokenRefresher(
                access_token=config.claude_oauth_token,
                refresh_token=config.claude_oauth_refresh_token,
                secrets_file=secrets_file,
                expires_at_ms=config.claude_oauth_expires_at,
                alert_callback=_token_alert,
            )
            self._claude.set_token_provider(self._token_refresher)

        # Persistent Claude process for Claude-routed text messages
        # (haiku/sonnet). HTTP main backends use one-shot ClaudeRunner.invoke()
        # instead, so startup must not spawn a dormant Claude subprocess.
        if _warm_claude_enabled_for_config(config):
            self._warm_claude = WarmClaudeProcess(
                config=config,
                token_provider=self._token_refresher,
            )
            # P1.1 (audit C1) — share the InvocationController so app-level
            # interrupt detection sees warm in-flight calls.
            self._warm_claude.set_invocation_controller(self._invocation_controller)
        else:
            self._warm_claude = None

        # Sprint D8.2 — pre-spawn double-buffer on OAuth token refresh.
        # Build the new warm process FIRST, swap atomically, then close the
        # old one in the background. Eliminates the 6h scheduled cold window
        # the old close-then-spawn cycle introduced.
        if self._token_refresher and self._warm_claude:
            async def _on_token_refresh() -> None:
                await self._refresh_warm_claude()
            self._token_refresher.set_on_refresh(_on_token_refresh)

        self._discord = DiscordBot(config)
        # Voice subsystem — gated behind cfg.voice_enabled (issue #1612).
        # When the flag is off we leave the attributes as None rather than
        # bare object() placeholders so health.py and any other caller can
        # distinguish "feature disabled" from "active". Downstream consumers
        # are guarded by `config.voice_enabled` or `hasattr(self, "_vapi")`
        # already — see _provision_vapi_squad and the API server wiring.
        if config.voice_enabled:
            from .voice_manager import VoiceManager
            from .tts_engine import TTSEngine
            from .vapi_client import VAPIClient
            from .voice.vapi_squad import build_bumba_squad  # noqa: F401 — used in _provision_vapi_squad
            from .voice.department_tools import DepartmentToolHandler
            self._voice = VoiceManager(
                bot=self._discord,
                voice_channel_id=int(config.discord_voice_channel_id) if config.discord_voice_channel_id else None,
            )
            self._tts = TTSEngine(base_url=config.voice_tts_url, voice=config.voice_tts_voice)
            self._vapi = VAPIClient(
                api_key=config.vapi_api_key,
                webhook_url=config.vapi_webhook_url,
                vapi_assistant_id_receptionist=config.vapi_assistant_id_receptionist,
            )

            async def _voice_health_snapshot() -> dict:
                health_server = getattr(self, "_health_server", None)
                if health_server is None:
                    return {
                        "status": "unavailable",
                        "components": {},
                        "message": "HealthServer not initialized",
                    }
                return await health_server.collect_health()

            def _voice_mcp_snapshot() -> dict:
                monitor = getattr(self, "_mcp_monitor", None)
                if monitor is None:
                    return {
                        "status": "unavailable",
                        "healthy": False,
                        "monitor_wired": False,
                    }
                summary = monitor.get_status_summary()
                return {
                    "status": (
                        "ok"
                        if int(summary.get("crash_loop", 0)) == 0
                        else "degraded"
                    ),
                    "healthy": int(summary.get("crash_loop", 0)) == 0,
                    "monitor_wired": True,
                    "summary": summary,
                }

            async def _voice_active_sessions_snapshot(args: dict) -> dict:
                store = getattr(self, "_chief_session_store", None)
                if store is None:
                    raise FileNotFoundError("ChiefSessionStore not initialized")

                from .chief_session import ChiefSessionState

                try:
                    limit = int(args.get("limit", 10))
                except (TypeError, ValueError):
                    limit = 10
                limit = max(1, min(25, limit))

                sessions = []
                for state in (
                    ChiefSessionState.WARM,
                    ChiefSessionState.EXECUTING,
                    ChiefSessionState.AWAITING_EVALUATION,
                ):
                    sessions.extend(await store.list_by_state(state))
                sessions.sort(
                    key=lambda s: s.updated_at_utc or "",
                    reverse=True,
                )
                limited = sessions[:limit]
                return {
                    "status": "ok",
                    "count": len(limited),
                    "sessions": [s.to_dict() for s in limited],
                }

            self._tool_handler = DepartmentToolHandler(
                health_provider=_voice_health_snapshot,
                mcp_health_provider=_voice_mcp_snapshot,
                active_sessions_provider=_voice_active_sessions_snapshot,
            )
            # Wire tool handler into VAPI client so function-call events can dispatch.
            # Sprint P8.3 / audit M-4 (#1749): setter call instead of direct
            # write to the VAPIClient ``_tool_handler`` private attribute so
            # the wire is visible to WIRING_MANIFEST + readers of vapi_client.py.
            self._vapi.set_tool_handler(self._tool_handler)
            self._vapi_squad: dict | None = None  # set by _provision_vapi_squad()
            logger.info("Voice subsystem: active (VAPI mode)")
        else:
            self._voice = None
            self._tts = None
            self._audio_pipeline = None
            logger.info("Voice subsystem: disabled (voice_enabled = false)")
        self._discord.set_voice_manager(self._voice)

        # Sprint 07.13 — construct StreamCoalescer here so the WIRING_MANIFEST
        # entry below has a non-None source. on_flush closes over the operator's
        # Discord channel: this bridge is single-operator, so all coalesced
        # text goes to the same channel. Reduces ~50 Discord edits per
        # response to ~5 (the documented goal in stream_coalescer.py).
        # The setter wiring is performed by _wire() via the manifest entry,
        # NOT inline here, so the operator's "Wiring complete" boot line
        # accounts for it.
        operator_chat_id = config.operator_discord_id

        async def _coalescer_flush(text: str) -> None:
            # Bound at construction time so the coalescer's on_flush signature
            # (Callable[[str], Awaitable[None]]) matches what StreamCoalescer
            # expects without leaking chat_id concerns into stream_coalescer.py.
            if self._discord is not None and operator_chat_id:
                await self._discord.send_message(operator_chat_id, text)

        self._stream_coalescer = StreamCoalescer(on_flush=_coalescer_flush)
        self._commands = CommandHandler(
            db=self._db,
            queue=self._queue,
            session_manager=self._session_mgr,
            claude_runner=self._claude,
        )

        # Per-session hook registry (#19)
        # Sprint 01.08b: file-based HookDispatcher removed — see audit at
        # docs/audits/2026-04-24-activation-plans/plan-01-hooks-audit.md
        self._session_hooks = SessionHookRegistry()
        self._session_hooks.register(
            "careful",
            "Force Opus model + extra thoroughness",
        )
        self._session_hooks.register(
            "freeze",
            "Read-only mode — block file modifications",
        )
        logger.info("SessionHookRegistry initialized (careful, freeze)")

        # Self-verifier (#20) — disabled by default, /verify on to enable
        self._self_verifier = SelfVerifier(enabled=False)
        logger.info("SelfVerifier initialized (disabled — /verify on to enable)")

        # Daily log writer — Sprint 09.14 closes the wire-to-None slot from
        # Sprint 01.03. The writer is constructed under config.daily_log_enabled
        # (default True; matches bridge.toml [daily_log] enabled = true) and
        # propagated via setters to SessionManager + CommandHandler. The
        # WIRING_MANIFEST then mirrors it onto self via the reflexive
        # BridgeApp.set_daily_log entry from Sprint 01.04.
        if getattr(config, "daily_log_enabled", True):
            try:
                self._daily_log = DailyLogWriter(config)
                # Propagate to SessionManager — its set_daily_log is NOT in
                # the WIRING_MANIFEST (the manifest only governs CommandHandler
                # + reflexive BridgeApp setters), so we call it here.
                self._session_mgr.set_daily_log(self._daily_log)
                logger.info(
                    "DailyLogWriter initialized (enabled=True); /healthz "
                    "daily_log check now reports up"
                )
            except Exception as e:
                logger.warning(
                    "DailyLogWriter init failed (non-fatal): %s", e
                )
                self._daily_log = None
        else:
            logger.info(
                "DailyLogWriter disabled via config.daily_log_enabled=False"
            )
            self._daily_log = None

        # Sprint 05.04 — second-brain contributor subsystem bootstrap.
        # When config.second_brain_enabled is True AND
        # config.second_brain_vault_root is a non-empty path that exists,
        # materialize bumba-contributions/staging/ + curated/ under the
        # vault root (idempotent). The double guard is defensive: a
        # mis-configured flag with an empty vault root must never write
        # to an unintended directory. See ADR Decision 3 (signed
        # 2026-05-01) in agent/docs/architecture/second-brain.md.
        if getattr(config, "second_brain_enabled", False):
            vault_root_str = getattr(config, "second_brain_vault_root", "") or ""
            if vault_root_str:
                try:
                    from .second_brain import ensure_subtree as _sb_ensure_subtree
                    _sb_ensure_subtree(Path(vault_root_str))
                    logger.info(
                        "second-brain: ensured bumba-contributions/ subtree "
                        "at %s",
                        vault_root_str,
                    )
                except Exception as e:  # noqa: BLE001 — non-fatal at startup
                    logger.warning(
                        "second-brain: ensure_subtree failed (non-fatal): %s",
                        e,
                    )
            else:
                logger.info(
                    "second-brain: enabled flag set but vault_root empty — "
                    "subsystem stays inert"
                )

        # Sprint 09.13 — TickManager + ProactiveGuard + TickContextBuilder.
        # All three live behind config.proactive_enabled (default False).
        # When the flag is off, the attributes stay None and BridgeApp.start()
        # never spawns the background tick loop — preserving today's no-tick
        # behavior. When True, ProactiveGuard is wired into TickManager so
        # check_action() runs before tick injection (Plan 06 §9 item 7).
        # Order matters: TickContextBuilder is constructed first so it can
        # receive the daily_log + future event_bus references; TickManager is
        # constructed last because it consumes the guard.
        self._proactive_guard = None
        self._tick_context_builder = None
        # Sprint #1614 (2026-05-11) — init-failure marker. The WIRING_MANIFEST
        # below uses ``failed_marker_attr="_tick_manager_init_failed"`` to
        # surface "tried and crashed" separately from "deferred by future
        # plan" in the boot wiring report. Default False; set True only when
        # the construction block raises.
        self._tick_manager_init_failed = False
        if getattr(config, "proactive_enabled", False):
            try:
                from .proactive_safety import ProactiveGuard
                from .tick_context import TickContextBuilder

                self._proactive_guard = ProactiveGuard()
                self._tick_context_builder = TickContextBuilder(config)
                # Wire daily_log into the context builder if available — its
                # set_daily_log is also not in the WIRING_MANIFEST, so call
                # it directly. None is a valid input (the builder no-ops).
                self._tick_context_builder.set_daily_log(self._daily_log)
                # Wire the event bus too (autonomy may not have constructed
                # successfully yet, in which case set_event_bus(None) is fine).
                event_bus = (
                    self._autonomy.event_bus if self._autonomy else None
                )
                self._tick_context_builder.set_event_bus(event_bus)
                self._tick_context_builder.set_task_pipeline(self._task_pipeline)

                # default_sleep_seconds intentionally NOT threaded from config
                # — the matching knob was deleted by Sprint 01.07 as dead.
                # TickManager's own default of 300s is the source of truth.
                discord_ref = self._discord
                operator_channel = config.operator_discord_id

                async def _post_orientation_to_discord(brief: str) -> None:
                    """E3.2 — route a tick brief to the operator's Discord channel."""
                    if discord_ref is not None and operator_channel:
                        await discord_ref.send_message(operator_channel, brief)

                self._tick_manager = TickManager(
                    min_sleep_seconds=config.proactive_min_sleep_seconds,
                    max_sleep_seconds=config.proactive_max_sleep_seconds,
                    proactive_guard=self._proactive_guard,
                    inbox_poster=_post_orientation_to_discord,
                    tick_context_builder=self._tick_context_builder,
                )
                logger.info(
                    "TickManager + ProactiveGuard initialized "
                    "(proactive_enabled=True); flip /proactive on to start "
                    "ticking"
                )
            except Exception as e:
                logger.warning(
                    "TickManager / ProactiveGuard init failed (non-fatal): %s",
                    e,
                )
                self._tick_manager = None
                self._proactive_guard = None
                self._tick_context_builder = None
                # Sprint #1614 — flip the marker so the WIRING_MANIFEST
                # routes set_tick_manager into the FAILED bucket instead
                # of PENDING.
                self._tick_manager_init_failed = True
        else:
            logger.info(
                "TickManager skipped (proactive_enabled=False); "
                "WiringReport will list set_tick_manager as pending"
            )

        # D7.12 #1424 (slice 1) — perpetual-proactive scheduler. Default-off;
        # default dry-run when on. Reads the dep-graph + activity ledger; in
        # slice 1 it does NOT dispatch (dispatch_callback stays None). The
        # commands surface (`/proactive status`) consumes the ledger to render
        # last-7-days activity in D7.11 late-night-profile shape.
        #
        # Sprint #1614 (2026-05-11) — init-failure marker. Same pattern as
        # ``_tick_manager_init_failed`` above; default False, set True only
        # when the construction block raises.
        self._proactive_scheduler_init_failed = False
        if config.proactive_scheduler_enabled:
            try:
                from .proactive_scheduler import ProactiveScheduler

                # Inbox wired in slice 2 of D7.9; tolerate None either way.
                inbox_ref = self._operator_inbox

                async def _inbox_pending_count() -> int:
                    if inbox_ref is None:
                        return 0
                    try:
                        pending = await inbox_ref.pending()
                        return len(pending)
                    except Exception:
                        return 0

                # Sync wrapper — the scheduler's should_skip_tick is async-
                # native and awaits the count, so we spin a small adapter.
                _pending_holder: dict[str, int] = {"count": 0}

                def _sync_pending() -> int:
                    # Best-effort sync read; ProactiveScheduler refreshes
                    # this holder through set_inbox_pending_refresh before
                    # calling should_skip_tick().
                    return _pending_holder["count"]

                async def _refresh_inbox_pending_count() -> int:
                    _pending_holder["count"] = await _inbox_pending_count()
                    return _pending_holder["count"]

                budget_ref = self._budget

                def _daily_spend_fraction() -> float:
                    if budget_ref is None:
                        return 0.0
                    try:
                        # BudgetGuard.spend_fraction returns 0.0..1.0 today
                        # cumulative spend / daily limit. Best-effort.
                        return float(getattr(budget_ref, "spend_fraction", lambda: 0.0)())
                    except Exception:
                        return 0.0

                halt_flag_path = Path(config.data_dir) / "halt.flag"

                def _halt_present() -> bool:
                    return halt_flag_path.exists()

                # D7.12 #1424 (slice 2) — closed-issue cache feeds the
                # selector so sprints with prereq edges become eligible
                # once their prereqs close. The cache file is refreshed
                # every 6h by `refresh_closed_issue_cache()`; the lambda
                # here reads the on-disk snapshot synchronously.
                closed_cache_path = (
                    Path(config.data_dir) / "closed-issues-cache.json"
                )

                from .proactive_scheduler import load_closed_issue_cache

                def _closed_issues_provider() -> set[int]:
                    return load_closed_issue_cache(closed_cache_path)

                self._proactive_scheduler = ProactiveScheduler(
                    graph_path=Path(config.data_dir).parent / "docs"
                        / "sprint-dependency-graph.json",
                    ledger_path=Path(config.data_dir)
                        / "proactive-activity.jsonl",
                    budget_threshold=config.proactive_scheduler_budget_threshold,
                    interval_seconds=config.proactive_scheduler_interval_seconds,
                    dry_run=config.proactive_scheduler_dry_run,
                    get_inbox_pending_count=_sync_pending,
                    get_daily_spend_fraction=_daily_spend_fraction,
                    get_halt_flag_present=_halt_present,
                    get_closed_issue_numbers=_closed_issues_provider,
                    # D7.12 slice 3 #1424 — weekly digest at
                    # `data/weekly-digest.md`. Self-rate-limited via the
                    # scheduler's ISO-week boundary check; safe to set
                    # unconditionally (never produces multiple sections per week).
                    digest_path=Path(config.data_dir) / "weekly-digest.md",
                )

                self._proactive_scheduler.set_inbox_pending_refresh(
                    _refresh_inbox_pending_count
                )

                # D7.12 #1424 (slice 2) — wire the AutonomousPlanDrafter as
                # dispatch_callback when the dispatch flag is on AND
                # dry_run is off. Either guard alone keeps the dispatch
                # surface inert; both must be flipped to actually post.
                #
                # Sprint #1614 (2026-05-11): uses ``set_dispatch`` (not the
                # raw ``_dispatch`` attribute) to keep this wire visible to
                # any future audit of "where is dispatch registered?".
                # Direct-attribute assignment was the anti-pattern this
                # sprint closes — see "Wiring discipline" in agent/CLAUDE.md.
                if (
                    config.proactive_scheduler_dispatch_enabled
                    and not config.proactive_scheduler_dry_run
                ):
                    try:
                        from .proactive_scheduler import (
                            AutonomousPlanDrafter,
                            make_drafter_callback,
                        )
                        drafter = AutonomousPlanDrafter(runner=self._claude)
                        self._proactive_scheduler.set_dispatch(
                            make_drafter_callback(drafter)
                        )
                        logger.info(
                            "ProactiveScheduler: AutonomousPlanDrafter wired "
                            "(dispatch_enabled=True, dry_run=False)"
                        )
                    except Exception as e:
                        logger.warning(
                            "AutonomousPlanDrafter wiring failed (non-fatal): %s",
                            e,
                        )

                logger.info(
                    "ProactiveScheduler initialized (interval=%ds, "
                    "dry_run=%s, dispatch_enabled=%s); "
                    "call .start() to begin ticking",
                    int(config.proactive_scheduler_interval_seconds),
                    config.proactive_scheduler_dry_run,
                    config.proactive_scheduler_dispatch_enabled,
                )
            except Exception as e:
                logger.warning(
                    "ProactiveScheduler init failed (non-fatal): %s", e
                )
                self._proactive_scheduler = None
                # Sprint #1614 — flip the marker so the WIRING_MANIFEST
                # routes set_proactive_scheduler into the FAILED bucket
                # instead of PENDING.
                self._proactive_scheduler_init_failed = True
        else:
            logger.info(
                "ProactiveScheduler skipped "
                "(proactive_scheduler_enabled=False)"
            )

        # E3.3 — register orientation update hooks (must run before TickManager starts).
        # Hook registration order: plan_state → daily_log. OperatorInbox wires itself
        # lazily in operator_inbox.py::_orientation_hooks (no startup registration needed).
        try:
            from .plan_state import register_completion_hook
            from .daily_log import register_entry_hook
            from .orientation import update_on_step_completed, update_on_decision_logged

            register_completion_hook(update_on_step_completed)
            register_entry_hook(
                lambda entry, category: (
                    update_on_decision_logged(entry) if category == "decision" else None
                )
            )
            logger.info("E3.3: orientation update hooks registered (plan_state, daily_log)")
        except Exception as e:
            logger.warning("E3.3: orientation hook registration failed (non-fatal): %s", e)

        # MEMORY.md writer (Sprint 11; renamed Sprint 05.06) — set via set_memory_file()
        # #2599: activate the dormant injection wire. The class, setter,
        # WIRING_MANIFEST entry and health check all pre-existed, but nothing
        # constructed a MemoryFile, so _memory_file stayed None and MEMORY.md
        # was never injected into the Claude context (the "running outside the
        # harness" incident, 2026-06-04). Construct it against the runtime data
        # dir and wire it via the setter. Best-effort: a construction failure
        # leaves the wire dormant (None) rather than aborting boot.
        self._memory_file = None
        try:
            from .memory_file import MemoryFile

            self.set_memory_file(MemoryFile(memory_dir=Path(config.data_dir)))
            logger.info(
                "MemoryFile wired (#2599): MEMORY.md injection active at %s",
                Path(config.data_dir) / "MEMORY.md",
            )
        except Exception as e:
            logger.warning(
                "MemoryFile construction failed (non-fatal); MEMORY.md "
                "injection stays dormant: %s", e
            )

        # Sprint 01.02 — pre-stash the lambda source so the wiring manifest
        # can resolve it via getattr.
        self._shutdown_callback = lambda: self._shutdown_event.set()

        if self._tmux_agents and self._token_refresher:
            # Now that token_refresher exists, wire it to tmux agents
            self._tmux_agents._token_provider = self._token_refresher

        # Few-shot example store (Patch D)
        few_shot_db = str(Path(config.data_dir) / "few_shot.db")
        self._few_shot = FewShotStore(db_path=few_shot_db)
        logger.info("FewShotStore initialized at %s", few_shot_db)

        # Self-edit memory (Patch E)
        edit_db = str(Path(config.data_dir) / "self_edit.db")
        self._self_edit = SelfEditMemory(db_path=edit_db)
        logger.info("SelfEditMemory initialized at %s", edit_db)

        # Temporal knowledge store (Patch F)
        tkb_db = str(Path(config.data_dir) / "temporal_kb.db")
        self._temporal_kb = TemporalKnowledgeStore(db_path=tkb_db)
        logger.info("TemporalKnowledgeStore initialized at %s", tkb_db)

        # Request tracer (Patch G)
        trace_path = Path(config.data_dir) / "traces.jsonl"
        self._tracer = Tracer(service_name="bridge", output_path=trace_path)
        logger.info("Tracer initialized → %s", trace_path)

        # P6.4 (#1599) — flush retroactive startup phase spans now that the
        # tracer exists. Each phase was checkpointed earlier in _initialize
        # via time.time() pairs. Best-effort: a write failure must not abort
        # startup, so we log and continue.
        for _ph_name, _ph_start, _ph_end, _ph_attrs in _startup_phases:
            try:
                record_completed_span(
                    self._tracer,
                    _ph_name,
                    _ph_start,
                    _ph_end,
                    attributes=_ph_attrs,
                )
            except Exception as _ph_exc:  # noqa: BLE001
                logger.warning(
                    "Startup phase telemetry write failed for %s "
                    "(non-fatal): %s",
                    _ph_name,
                    _ph_exc,
                )

        # Cost tracker (per-model USD tracking)
        try:
            from teams._config import load_team_limits as _load_team_limits
            _team_limits = _load_team_limits()
        except Exception as _tle:
            logger.debug("Could not load team limits for CostTracker: %s", _tle)
            _team_limits = {}
        self._cost_tracker = CostTracker(
            data_dir=config.data_dir,
            feature_caps_enabled=config.feature_cost_caps_enabled,
            board_v2_enabled=config.board_v2_enabled,
            team_limits=_team_limits,
        )
        logger.info("CostTracker initialized")

        # Routing feedback engine (tool/model performance tracking)
        routing_db = str(Path(config.data_dir) / "routing_feedback.db")
        self._routing_feedback = RoutingFeedbackEngine(db_path=routing_db)
        logger.info("RoutingFeedbackEngine initialized")

        # Self-healing: session recovery manager
        self._session_recovery = SessionRecoveryManager()

        # Reflection store + in-session reflexion context
        reflection_db = str(Path(config.data_dir) / "reflections.db")
        self._reflection_store = ReflectionStore(db_path=reflection_db)
        self._reflexion_ctx = ReflexionContext()
        logger.info("ReflectionStore initialized")

        # Sprint 05.07 — second-brain contributor registry build (#1015).
        # Wire DailyLogContributor + ReflectionContributor +
        # ConsolidationContributor into a ContributorRegistry once both
        # daily_log + reflection_store are bound. Each contributor
        # honors its own granular flag so the operator can silence one
        # without flipping the master switch. Empty-vault-root short-
        # circuit happens above; if we get here with the master flag on
        # we know the subtree exists.
        self._second_brain_registry = None
        if (
            getattr(config, "second_brain_enabled", False)
            and (getattr(config, "second_brain_vault_root", "") or "")
        ):
            try:
                from .second_brain import ContributorRegistry
                from .second_brain.contributors import (
                    ConsolidationContributor,
                    DailyLogContributor,
                    ReflectionContributor,
                )
                registry = ContributorRegistry()
                _bridge_session_id = "bridge-app"
                if getattr(
                    config,
                    "second_brain_contributor_dailylog_enabled",
                    True,
                ):
                    registry.register(
                        DailyLogContributor(
                            daily_log_root=Path(config.data_dir) / "logs",
                            session_id=_bridge_session_id,
                        )
                    )
                if getattr(
                    config,
                    "second_brain_contributor_reflection_enabled",
                    True,
                ):
                    registry.register(
                        ReflectionContributor(
                            reflection_store=self._reflection_store,
                            session_id=_bridge_session_id,
                        )
                    )
                if getattr(
                    config,
                    "second_brain_contributor_consolidation_enabled",
                    True,
                ):
                    registry.register(
                        ConsolidationContributor(
                            consolidation_output_dir=(
                                Path(config.data_dir) / "consolidation"
                            ),
                            session_id=_bridge_session_id,
                        )
                    )
                self._second_brain_registry = registry
                logger.info(
                    "second-brain: ContributorRegistry built with %d "
                    "contributor(s)",
                    len(registry.all()),
                )
            except Exception as e:  # noqa: BLE001 — non-fatal at startup
                logger.warning(
                    "second-brain: ContributorRegistry build failed "
                    "(non-fatal): %s",
                    e,
                )

        # Sprint 05.11 — ShadowRouter wiring (#1021). The shadow harness
        # observes ConsolidationContributor outputs without modifying
        # the vault. JSONL sidecars land under ``data/shadow-router/``.
        # Operator inspects via ``/shadow_report`` and promotes / rejects
        # via ``/promote`` / ``/reject_wiki`` (which correlate back).
        # ADR Decision 4 (signed 2026-05-01).
        self._shadow_router = None
        if (
            getattr(config, "second_brain_shadow_router_enabled", False)
            and getattr(config, "second_brain_enabled", False)
            and (getattr(config, "second_brain_vault_root", "") or "")
        ):
            try:
                from .second_brain import WikiRepo
                from .second_brain.shadow_router import ShadowRouter
                vault_root_path = Path(
                    getattr(config, "second_brain_vault_root", "")
                )
                shadow_log_dir = (
                    Path(config.data_dir) / "shadow-router"
                )
                self._shadow_router = ShadowRouter(
                    wiki_repo=WikiRepo(vault_root_path),
                    log_dir=shadow_log_dir,
                )
                logger.info(
                    "second-brain: ShadowRouter wired (log_dir=%s)",
                    shadow_log_dir,
                )
            except Exception as e:  # noqa: BLE001 — non-fatal at startup
                logger.warning(
                    "second-brain: ShadowRouter wiring failed "
                    "(non-fatal): %s",
                    e,
                )
                self._shadow_router = None

        # Sprint Mem-4 (#1845) — DualWritePipeline construction. Gated by
        # ``memory_tiers_enabled`` (default False). The legacy second_brain
        # ContributorRegistry + ShadowRouter paths above keep running at
        # flag-on; the new pipeline ALSO writes through its second_brain
        # destination. The known double-write is tracked as Mem-4.5; risk-
        # budget priority here is "ship dual-write wiring without breaking
        # second_brain".
        self._dual_write_pipeline = None
        self._dual_write_pipeline_init_failed = False
        if getattr(config, "memory_tiers_enabled", False):
            try:
                from .advanced_memory.destinations import (
                    SQLiteDestination,
                    SecondBrainDestination,
                    VectorDestination,
                )
                from .advanced_memory.dual_write import DualWritePipeline
                # Resolve secondary-destination clients lazily — they may be
                # unset (None) and the destinations short-circuit cleanly on
                # write attempts.
                _wiki_repo_for_dw = None
                if (
                    getattr(config, "second_brain_enabled", False)
                    and (getattr(config, "second_brain_vault_root", "") or "")
                ):
                    try:
                        from .second_brain import WikiRepo
                        _wiki_repo_for_dw = WikiRepo(
                            Path(getattr(config, "second_brain_vault_root", ""))
                        )
                    except Exception:  # noqa: BLE001
                        logger.debug(
                            "Mem-4: WikiRepo unavailable for DualWritePipeline; "
                            "second_brain destination will report failure",
                            exc_info=True,
                        )
                # Mem-4.5 (#1867) — VectorDestination needs a connected
                # ``VectorStore``. Production wiring lives here; failures
                # log at debug and fall through to a None store so the
                # secondary write reports failure cleanly.
                _vector_store_for_dw = None
                try:
                    from .vector_store import VectorStore as _VectorStore
                    _vec_db_path = Path(config.data_dir) / "memory.db"
                    _vs = _VectorStore(db_path=str(_vec_db_path))
                    _vs.connect()
                    _vector_store_for_dw = _vs
                except Exception:  # noqa: BLE001
                    logger.debug(
                        "Mem-4.5: VectorStore unavailable for DualWritePipeline; "
                        "vector destination will report failure",
                        exc_info=True,
                    )
                destinations = {
                    "sqlite": SQLiteDestination(self._db),
                    "second_brain": SecondBrainDestination(_wiki_repo_for_dw),
                    "vector": VectorDestination(_vector_store_for_dw),
                }
                self._dual_write_pipeline = DualWritePipeline(
                    destinations=destinations,
                )
                logger.info(
                    "Mem-4: DualWritePipeline initialised with %d destination(s)",
                    len(destinations),
                )
            except Exception:
                logger.exception(
                    "Mem-4: DualWritePipeline init failed — wiring will report FAILED",
                )
                self._dual_write_pipeline = None
                self._dual_write_pipeline_init_failed = True

        # MCP server health monitor.
        # Issue #1543: pass the shared service_state dir so MCPMonitor
        # can emit a state file the EscalationEngine reads (CASUAL@1,
        # NUDGE@3, URGENT@5 consecutive-failure progression).
        _working_dir = getattr(config, "claude_working_dir", None)
        if _working_dir:
            mcp_config = Path(_working_dir) / ".mcp.json"
            if mcp_config.exists():
                self._mcp_monitor = MCPMonitor(
                    mcp_config_path=mcp_config,
                    state_dir=Path(config.data_dir) / "service_state",
                )
                logger.info("MCPMonitor initialized")

        # Semantic search stack — HybridSearch (RRF fusion FTS5+vector).
        # Sprint 05.01 moved engine construction earlier (right before Memory)
        # so the shim could be passed at constructor time. This block now
        # reuses self._embedding_engine if it was constructed successfully,
        # and only builds HybridSearch on top.
        if self._embedding_engine is not None:
            try:
                self._hybrid_search = HybridSearch(
                    embedding_engine=self._embedding_engine,
                    metrics_file=Path(config.data_dir) / "search_metrics.jsonl",
                )
                logger.info(
                    "Semantic search stack initialized (backend: %s)",
                    self._embedding_engine.backend,
                )
            except Exception as e:
                logger.warning("HybridSearch init failed (FTS5 still active): %s", e)
        else:
            logger.warning(
                "Skipping HybridSearch — embedding engine unavailable; FTS5 still active"
            )

        # Skill evolution engine (failure pattern detection + skill proposals)
        skill_db = str(Path(config.data_dir) / "skill_evolution.db")
        self._skill_evolution = SkillEvolutionEngine(db_path=skill_db)
        logger.info("SkillEvolutionEngine initialized")

        # Sprint #1112/4.03 (#2150) — central SkillAllocator. Loads the
        # operator-approved manifest at agent/config/skill-allocation/
        # manifest.yaml and threads default-deny semantics down to every
        # agent-instantiation site (ChiefDispatcher → WarmChief →
        # DepartmentTeam → build_*_agent). When the manifest file is
        # absent the bridge boots with an empty (default-deny) allocator
        # and logs a warning — runtime engineers MUST deploy the
        # manifest before bouncing the daemon, or every agent receives
        # zero allowed skills. Parsing exceptions flip
        # ``_skill_allocator_init_failed`` so the WIRING_MANIFEST entry
        # routes the wire to ``report.failed`` (operator can tell
        # "manifest missing" from "manifest broken").
        manifest_path = Path(__file__).parent.parent / "config" / "skill-allocation" / "manifest.yaml"
        try:
            if manifest_path.exists():
                self._skill_allocator = SkillAllocator.from_manifest(manifest_path)
                logger.info(
                    "SkillAllocator initialized: %d rules from %s",
                    len(self._skill_allocator.rules),
                    manifest_path,
                )
            else:
                self._skill_allocator = SkillAllocator(rules=[])
                logger.warning(
                    "SkillAllocator manifest missing at %s; defaulting to "
                    "deny-all (every agent receives zero allowed skills)",
                    manifest_path,
                )
        except Exception as e:  # noqa: BLE001
            self._skill_allocator = SkillAllocator(rules=[])
            self._skill_allocator_init_failed = True
            logger.error(
                "SkillAllocator construction failed (%s); falling back to "
                "deny-all empty allocator. Investigate manifest at %s",
                e,
                manifest_path,
            )

        # Project registry (Zone 3 — multi-project tracking)
        self._project_registry = ProjectRegistry(data_dir=config.data_dir)
        logger.info("ProjectRegistry initialized (%d project(s))", len(self._project_registry.list_all()))

        # Response evaluator (adversarial quality scoring)
        # P2.5 follow-up (#1664) — thread `verification_policy` from config so
        # bridge.toml becomes the canonical policy source. Env var still wins.
        self._evaluator = ResponseEvaluator(
            data_dir=config.data_dir,
            verification_policy=config.verification_policy,
        )
        self._evaluator.set_runner(self._claude)
        # Wire self-verifier into evaluator (#21)
        if self._self_verifier:
            self._evaluator.set_verifier(self._self_verifier)
        # Issue #1565 — log opt-out posture at startup. The evaluator instance
        # is always constructed (other code paths may invoke it directly); the
        # gate sits in _deliver_response so the per-response call is skipped
        # when the flag is false.
        logger.info(
            "ResponseEvaluator initialized (per-response call %s)",
            "enabled" if config.response_evaluator_enabled else "DISABLED (issue #1565 opt-out)",
        )

        # Diagnostic runbook engine
        runbook_dir = Path(__file__).parent.parent / "config" / "runbooks"
        self._runbook_engine = RunbookEngine(runbook_dir=runbook_dir)
        loaded = self._runbook_engine.load_runbooks()
        logger.info("RunbookEngine initialized: %d runbook(s) loaded", loaded)

        # AgentRouter — Board of Directors for /board command
        self._agent_router = AgentRouter()
        logger.info("AgentRouter initialized")

        # Zone 4 tool tracker (observability)
        self._tool_tracker = None
        if (
            _TOOL_TRACKER_AVAILABLE
            and getattr(config, "z4_observability_tool_tracker_enabled", False)
        ):
            self._tool_tracker = ToolTracker(
                sessions_dir=Path(config.data_dir) / "z4-sessions",
            )
            logger.info("ToolTracker initialized (sessions_dir=%s/z4-sessions)", config.data_dir)

        # Zone 4 cost attributor + metrics aggregator (depend on tool tracker)
        self._cost_attributor = None
        self._metrics_aggregator = None
        if self._tool_tracker:
            z4_sessions_dir = Path(config.data_dir) / "z4-sessions"
            self._cost_attributor = CostAttributor(
                tracker=self._tool_tracker,
                sessions_dir=z4_sessions_dir,
            )
            self._metrics_aggregator = MetricsAggregator(
                tracker=self._tool_tracker,
                sessions_dir=z4_sessions_dir,
            )
            logger.info("CostAttributor + MetricsAggregator initialized")

        # Zone 4 department registry (Pydantic AI teams)
        self._departments = None
        if _TEAMS_AVAILABLE:
            try:
                teams_dir = Path(__file__).parent.parent / "config" / "teams"
                self._departments = DepartmentRegistry.from_directory(
                    teams_dir,
                    tool_tracker=self._tool_tracker,
                )
                # RR.6 (#2593) — construct + wire the self-serve roster registry
                # store BEFORE prewarm (prewarm eagerly builds teams; they must
                # carry the store so the chief roster reflects registrations).
                # The store validates registrations against the live dept
                # configs (config_lookup) and fires on_change → AgentCache
                # .invalidate so a registration evicts the cached chief and the
                # next build shows the new specialist. Best-effort: a store
                # construction failure leaves the registry dormant (REST/command
                # surfaces already degrade to a "not wired" message) rather than
                # aborting boot.
                try:
                    from bridge.roster_registry_store import RosterRegistryStore
                    from teams._agent_cache import GLOBAL_AGENT_CACHE

                    def _roster_config_lookup(dept: str):
                        try:
                            return self._departments.get_config(dept)
                        except KeyError:
                            return None

                    self._roster_registry = RosterRegistryStore(
                        Path(config.data_dir) / "roster_registry.db",
                        config_lookup=_roster_config_lookup,
                        on_change=GLOBAL_AGENT_CACHE.invalidate,
                    )
                    self._departments.set_roster_registry(self._roster_registry)
                    logger.info("RosterRegistryStore wired (#2593, RR.6)")
                except Exception as e:
                    self._roster_registry = None
                    logger.warning(
                        "RosterRegistryStore construction failed (non-fatal); "
                        "self-serve roster registry stays dormant: %s", e
                    )
                # Sprint 01.02 — these two synthetic sources are only assigned
                # non-None inside this success branch, preserving the original
                # gate so set_circuit_registry / set_memory only fire when the
                # teams stack is alive. The wiring manifest reads these via
                # getattr; outside this branch they remain None and become
                # pending entries in the WiringReport.
                from teams._circuit import get_registry as get_circuit_registry
                self._circuit_registry = get_circuit_registry()
                self._memory_for_zone4 = self._memory
                # P6.4 (#1599) — wrap registry prewarm in a span so the
                # operator can compare cold-start spawn cost against
                # subsequent restarts via /api/traces.
                _prewarm_attrs = {
                    "department_count": len(self._departments.department_names()),
                }
                if self._tracer is not None:
                    with self._tracer.context_span(
                        "startup.registry_prewarm",
                        attributes=_prewarm_attrs,
                    ):
                        self._departments.prewarm()
                else:
                    self._departments.prewarm()
                logger.info(
                    "Z4 pre-warmed %d teams: %s",
                    len(self._departments.department_names()),
                    ", ".join(self._departments.department_names()),
                )
                logger.info(
                    "DepartmentRegistry initialized (%d departments: %s)",
                    len(self._departments.department_names()),
                    ", ".join(self._departments.department_names()),
                )
            except Exception as e:
                logger.warning("Failed to initialize DepartmentRegistry: %s", e)
        else:
            logger.debug("Zone 4 teams package not installed, skipping")

        # Z4-S22 #1395 — chief-session orchestration stack.
        # Conditionally instantiate the dispatcher trio (store + router +
        # dispatcher) when `chief_dispatcher_enabled=True`. When False
        # (the default), all three attributes stay None and:
        #   - api_server.py (Z4-S12 #1383) skips the chief_sessions routes
        #   - commands.py (Z4-S13 #1388) keeps /chief_sessions in
        #     "not initialized" mode
        # Order matters: dispatcher needs the store + router + dept
        # registry. Registry was initialized above; the database is
        # already wired earlier in _initialize.
        if config.chief_dispatcher_enabled:
            try:
                from .chief_session_store import SQLiteChiefSessionStore
                from .work_order_router import RuleBasedWorkOrderRouter
                from .chief_dispatcher import ChiefDispatcher

                self._chief_session_store = SQLiteChiefSessionStore(self._db)
                self._chief_router = RuleBasedWorkOrderRouter(
                    self._departments,
                    default_department=config.chief_dispatcher_default_department,
                )
                self._chief_dispatcher = ChiefDispatcher(
                    router=self._chief_router,
                    session_store=self._chief_session_store,
                    dept_registry=self._departments,
                    event_bus=(
                        self._autonomy.event_bus if self._autonomy else None
                    ),
                    # Escalation surface is None until BridgeApp grows a
                    # top-level escalation handle. The dispatcher's
                    # NUDGE-on-low-confidence path is best-effort and
                    # no-ops when escalation is None — see
                    # `bridge.chief_dispatcher.ChiefDispatcher._nudge`.
                    escalation=None,
                    # Sprint #1112/4.03 (#2150) — thread the central
                    # SkillAllocator down to WarmChief → DepartmentTeam →
                    # build_*_agent. None is the back-compat default for
                    # tests; production wiring always passes the live
                    # allocator constructed above.
                    skill_allocator=self._skill_allocator,
                )
                logger.info(
                    "ChiefDispatcher initialized "
                    "(default_dept=%s, idle_timeout=%.0fs)",
                    config.chief_dispatcher_default_department,
                    config.chief_dispatcher_idle_timeout_seconds,
                )
            except Exception as e:
                logger.warning(
                    "ChiefDispatcher init failed (non-fatal): %s", e
                )
                self._chief_session_store = None
                self._chief_router = None
                self._chief_dispatcher = None
        else:
            logger.debug(
                "ChiefDispatcher skipped (chief_dispatcher_enabled=False)"
            )

        # Sprint 01.02 — pre-stash log_dir as a Path so the wiring manifest
        # source resolution (getattr) can find it.
        self._log_dir = Path(config.log_dir)

        # Sprint 03.06 — construct WorkOrderStore + WorkOrderStreamManager so
        # the api_server.py:1385/1409/1434/1446 getattr callsites stop seeing
        # None and either 503'ing (`/api/workorders/{id}` GET) or silently
        # skipping persistence (`POST /api/workorders`). 01.04 declared the
        # two attributes as None at __init__ but added no manifest setter
        # entries — the construction lives here, not in the WIRING_MANIFEST.
        # Both blocks fail soft so a broken Zone 3 dependency cannot crash
        # the bridge boot path.
        try:
            from .work_order_store import WorkOrderStore
            wo_db_path = Path(config.data_dir) / config.workorder_db_path
            self._workorder_store = WorkOrderStore(wo_db_path)
            logger.info("WorkOrderStore initialized at %s", wo_db_path)
        except Exception as exc:
            logger.warning(
                "WorkOrderStore init failed (non-fatal): %s", exc
            )
            self._workorder_store = None

        try:
            from .workorder_ingest import WorkOrderIngestor
            self._workorder_ingestor = WorkOrderIngestor(
                event_bus=self._autonomy.event_bus if self._autonomy else None,
                temporal_knowledge=getattr(self, "_temporal_kb", None),
                work_order_store=self._workorder_store,
            )
            try:
                self._workorder_ingestor.wire()
            except Exception as wire_exc:
                logger.warning(
                    "WorkOrderIngestor.wire failed: %s",
                    wire_exc,
                )
            logger.info("WorkOrderIngestor initialized")
        except Exception as exc:
            logger.warning(
                "WorkOrderIngestor init failed (non-fatal): %s", exc
            )
            self._workorder_ingestor = None

        try:
            from .workorder_stream import WorkOrderStreamManager
            self._workorder_stream = WorkOrderStreamManager(
                event_bus=self._autonomy.event_bus if self._autonomy else None,
            )
            # Hook the stream onto the event bus so workorder.* events fan
            # out to subscribed WS queues. wire_event_bus() is idempotent
            # and a no-op if event_bus is None.
            try:
                self._workorder_stream.wire_event_bus()
            except Exception as wire_exc:
                logger.warning(
                    "WorkOrderStreamManager.wire_event_bus failed: %s",
                    wire_exc,
                )
            logger.info("WorkOrderStreamManager initialized")
        except Exception as exc:
            logger.warning(
                "WorkOrderStreamManager init failed (non-fatal): %s", exc
            )
            self._workorder_stream = None

        # Zone 3 dispatcher (feature-flagged — flag stays False until Z3.11)
        try:
            from .dispatcher import Dispatcher
            self._dispatcher = Dispatcher(
                claude_runner=self._claude,
                tmux_manager=getattr(self, '_tmux_agents', None),
                event_bus=self._autonomy.event_bus if self._autonomy else None,
                department_registry=self._departments,
                app=self,
                # Sprint 03.03 follow-up: thread BridgeConfig so the
                # ``verification_enabled`` toml knob the dispatcher reads
                # in _run_executor is no longer inert.
                config=self._config,
            )
            logger.info(
                "Dispatcher initialized (enabled=%s)",
                getattr(self._config, "dispatcher_enabled", False),
            )
            # D1.4: wire QualityChain into the dispatcher when flag enabled
            _quality_chain = self._build_quality_chain()
            if _quality_chain is not None:
                self._dispatcher._quality_chain = _quality_chain
                logger.info(
                    "quality_chain.wired gates=%d branch_protection=%s",
                    len(_quality_chain._gates),
                    getattr(self._config, "branch_protection_enabled", False),
                )
            if self._departments and self._dispatcher:
                logger.info(
                    "dispatcher.departments.wired count=%d departments=%s",
                    len(self._departments.department_names()),
                    ",".join(self._departments.department_names()),
                )
            elif self._dispatcher:
                logger.info("dispatcher.departments.unavailable reason=no_registry")
        except Exception as _disp_exc:
            logger.warning("Dispatcher init failed (non-fatal): %s", _disp_exc)

        # Sprint P2.1 #1717 — Wire RecursiveDecomposer into the dispatcher.
        # The decomposer is gated at runtime by config.workorder_decomposition_enabled
        # (default False); this block makes the gate functional. Cost guards
        # are baked into the decomposer itself: per-call cap $0.02 and
        # max_depth=3 (recursive_decomposer.py:82,87). Haiku-backed via the
        # ``make_haiku_decomposer`` factory — cheapest model tier.
        #
        # Follows the "Wiring discipline" pattern documented in agent/CLAUDE.md:
        # setter call (not direct attribute write) + WIRING_MANIFEST entry +
        # ``_recursive_decomposer_init_failed`` marker for PENDING/FAILED
        # disambiguation in the boot WiringReport.
        if self._dispatcher is not None:
            try:
                from .recursive_decomposer import (
                    RecursiveDecomposer,
                    make_haiku_decomposer,
                )

                self._recursive_decomposer = RecursiveDecomposer(
                    decompose_call=make_haiku_decomposer(self._claude),
                )
                self._dispatcher.set_recursive_decomposer(self._recursive_decomposer)
                logger.info(
                    "RecursiveDecomposer wired into dispatcher "
                    "(gated by workorder_decomposition_enabled=%s)",
                    getattr(self._config, "workorder_decomposition_enabled", False),
                )
            except Exception as _rd_exc:
                logger.warning(
                    "RecursiveDecomposer init failed (non-fatal): %s", _rd_exc
                )
                self._recursive_decomposer = None
                self._recursive_decomposer_init_failed = True

        # P8.2 #1748 — Wire DreamNotifier with the live Discord client.
        # The notifier exposes phase-progress message methods; the bridge
        # daemon holds it as the post-target for consolidation event hooks.
        # ConsolidationService runs in a separate subprocess (services/runner.py)
        # so this instance is not directly threaded into the consolidation
        # pipeline; downstream event subscribers (future work) consume it.
        # Channel falls back to service_channel_id (the dedicated channel for
        # automated outputs) → operator_discord_id as the operator DM.
        try:
            from .dream_notifier import DreamNotifier
            _dream_channel = (
                getattr(self._config, "service_channel_id", None)
                or getattr(self._config, "operator_discord_id", None)
            )
            if self._discord is not None and _dream_channel:
                self._dream_notifier = DreamNotifier(
                    discord_client=self._discord,
                    dream_channel_id=int(_dream_channel),
                )
                logger.info(
                    "DreamNotifier wired (channel=%s)",
                    _dream_channel,
                )
            else:
                logger.debug(
                    "DreamNotifier skipped (discord=%s, channel=%s)",
                    self._discord is not None,
                    bool(_dream_channel),
                )
        except Exception as _dn_exc:
            logger.warning("DreamNotifier init failed (non-fatal): %s", _dn_exc)
            self._dream_notifier = None
            self._dream_notifier_init_failed = True

        # Zone 3 EnvironmentSelector (S02d — consulted at dispatch time)
        try:
            from .environment_selector import EnvironmentSelector
            # Sprint 03.07 — opt-in auto-rebalancing via config flag.
            # Default False keeps env choice unchanged from today.
            _force_alt = bool(
                getattr(self._config, "env_selector_force_alternative", False)
            )
            self._env_selector = EnvironmentSelector(force_alternative=_force_alt)
            logger.info(
                "EnvironmentSelector initialized (force_alternative=%s)",
                _force_alt,
            )
        except Exception as _sel_exc:
            logger.warning("EnvironmentSelector init failed (non-fatal): %s", _sel_exc)

        # Sprint 03.05 — Construct RoutingBrain so the WIRING_MANIFEST entry from
        # Sprint 01.03 (set_routing_brain → _routing_brain, required=False) finally
        # has a non-None source. Without this, /dispatch returns "RoutingBrain not
        # configured." despite the manifest declaring the wire. Placed after
        # EnvironmentSelector init because RoutingBrain consults the selector for
        # moderate-complexity (3-4) hint resolution. Lazy import keeps the cost
        # local to this branch.
        try:
            from .routing_brain import RoutingBrain
            if self._env_selector is not None:
                self._routing_brain = RoutingBrain(selector=self._env_selector)
                logger.info("RoutingBrain initialized")
            else:
                logger.warning(
                    "EnvironmentSelector unavailable — RoutingBrain skipped "
                    "(set_routing_brain stays pending in WiringReport)"
                )
        except Exception as _rb_exc:
            logger.warning("RoutingBrain init failed (non-fatal): %s", _rb_exc)

        # Sprint 04.06 — Construct WorkflowRegistry + WorkflowEngine so the
        # Sprint 01.03 wire-to-None entries (set_workflow_registry,
        # set_workflow_engine → both Plan 04 owned) finally have non-None
        # sources. Without this, /workflows short-circuits with "WorkflowRegistry
        # is not initialised." even though both modules (workflow_registry.py
        # 221 LOC + workflow_engine.py 592 LOC) are fully implemented.
        #
        # The registry uses its built-in default config_dir
        # (`bridge/../config/workflows`) so the YAML location stays canonical.
        # The engine wires the four optional dependencies the operator-facing
        # wiring contract expects:
        #   - department_runner: Sprint 04.07 — _workflow_department_runner
        #     adapts DepartmentRegistry.route's TeamResult to the
        #     WorkflowEngine's expected (str, float) shape. When the
        #     DepartmentRegistry is missing it returns a typed sentinel so
        #     the engine degrades gracefully instead of crashing.
        #   - task_queue: TaskQueue for operator gate steps.
        #   - store: WorkOrderStore (workflow_runs table lives there).
        #   - event_bus: AutonomyLayer.event_bus when present.
        #   - discord_callback: DiscordBot.send_message — channel-id aware
        #     callable matching the (channel, message) shape the engine
        #     awaits at workflow_engine.py:394.
        # Both blocks fail soft so a broken Z4 dependency never crashes boot.
        try:
            from .workflow_registry import WorkflowRegistry
            self._workflow_registry = WorkflowRegistry(
                store=self._workorder_store,
            )
            logger.info(
                "WorkflowRegistry initialized (%d workflows: %s)",
                len(self._workflow_registry.names()),
                ", ".join(self._workflow_registry.names()),
            )
            # Sprint 04.07 — validate every YAML's department references
            # resolve in DepartmentRegistry. Mismatches log a warning but
            # never crash boot: a typo in one workflow YAML must not take
            # down the bridge.
            self._validate_workflow_departments()
        except Exception as _wr_exc:
            logger.warning("WorkflowRegistry init failed (non-fatal): %s", _wr_exc)
            self._workflow_registry = None

        try:
            from .workflow_engine import WorkflowEngine
            self._workflow_engine = WorkflowEngine(
                department_runner=self._workflow_department_runner,
                task_queue=self._task_queue,
                store=self._workorder_store,
                event_bus=self._autonomy.event_bus if self._autonomy else None,
                discord_callback=(
                    self._discord.send_message if self._discord else None
                ),
            )
            logger.info("WorkflowEngine initialized")
        except Exception as _we_exc:
            logger.warning("WorkflowEngine init failed (non-fatal): %s", _we_exc)
            self._workflow_engine = None

        # Command suggester (keyword-based discovery of commands/skills)
        try:
            from .command_suggester import CommandSuggester
            commands_dir = Path(config.claude_working_dir) / "config" / "claude-files" / "commands"
            skills_dir = Path(config.claude_working_dir) / "config" / "claude-files" / "skills"
            self._suggester = CommandSuggester(commands_dir, skills_dir)
        except Exception as e:
            logger.warning("CommandSuggester init failed: %s", e)

        # E2.4 — Registry loader: load agent/config/registry/ at startup.
        # Validation failures are logged but non-fatal (E2.6 is the CI gate).
        try:
            from .registry_loader import RegistryLoader
            _registry_root = Path(config.claude_working_dir) / "config" / "registry"
            _reg_index = RegistryLoader().load_all(_registry_root)
            self._registry_index = _reg_index
            logger.info(
                "registry: %d event(s), %d metric(s), %d action(s) loaded; %d error(s)",
                len(_reg_index.events),
                len(_reg_index.metrics),
                len(_reg_index.actions),
                len(_reg_index.errors),
            )
            for _err in _reg_index.errors:
                logger.warning(
                    "registry: validation error in %s[%s]: %s",
                    _err.file.name,
                    _err.entry_key,
                    _err.message,
                )
        except Exception as _reg_exc:
            logger.warning("registry loader init failed (non-fatal): %s", _reg_exc)
            self._registry_index = None

        # Sprint 07.04 — Peer coordination scaffolding. Construction is gated
        # behind config.peer_coordination_enabled (default False). When the
        # flag is off, both attributes stay None and start()/stop() are
        # no-ops; this preserves today's no-registration behavior.
        # When True, we construct an in-memory PeerRegistry and a
        # PeerRegistrationManager that owns this bridge's lifecycle in the
        # registry. The actual register/heartbeat/deregister calls fire from
        # start()/stop() below — not here — so a constructor failure cannot
        # delay boot beyond the warning log.
        # Out-of-scope per Sprint 07.04 (deliberately deferred):
        #   - SQLite persistence of the registry → Sprint 07.05
        #   - Mounting peer API routes on api_server → Sprint 07.06
        #   - Bridging peer events into AutonomyLayer.event_bus → Sprint 07.07
        if getattr(config, "peer_coordination_enabled", False):
            try:
                from .peer_registry import PeerRegistry
                from .peer_registration import (
                    PeerRegistrationManager,
                    RegistrationConfig,
                )
                self._peer_registry = PeerRegistry()
                self._peer_registration = PeerRegistrationManager(
                    registry=self._peer_registry,
                    config=RegistrationConfig.from_environment(),
                )
                logger.info(
                    "PeerRegistrationManager initialized (peer_id=%s)",
                    self._peer_registration.self_peer_id,
                )
            except Exception as _peer_exc:
                logger.warning(
                    "PeerRegistrationManager init failed (non-fatal): %s",
                    _peer_exc,
                )
                self._peer_registry = None
                self._peer_registration = None
        else:
            self._peer_registry = None
            self._peer_registration = None

        # Sprint 07.07 — RemoteEventBridge construction. Same gate as the
        # PeerRegistrationManager block above (peer_coordination_enabled).
        # When the flag is off the bridge stays None and the
        # WIRING_MANIFEST entry surfaces in the boot WiringReport's
        # pending list — operator-visible dormancy beats a silent no-op.
        # When the flag is on, we construct the bridge with the default
        # _LocalLogTransport which preserves the prior stub behavior:
        # log the target peer + (because the AutonomyLayer.event_bus is
        # passed through) re-publish locally for any subscriber that
        # was wired against the legacy contract. A real
        # MCPRemoteTransport is documented in remote_events.py but not
        # yet implemented — the bridge half is in place pending
        # bumba-memory-mcp shipping its event-broadcast tool.
        if getattr(config, "peer_coordination_enabled", False):
            try:
                from .remote_events import RemoteEventBridge

                event_bus_for_bridge = (
                    self._autonomy.event_bus if self._autonomy else None
                )
                self._remote_event_bridge = RemoteEventBridge(
                    event_bus=event_bus_for_bridge,
                )
                logger.info(
                    "RemoteEventBridge initialized "
                    "(transport=_LocalLogTransport, peer_coordination_enabled=True)"
                )
            except Exception as _bridge_exc:
                logger.warning(
                    "RemoteEventBridge init failed (non-fatal): %s",
                    _bridge_exc,
                )
                self._remote_event_bridge = None
        else:
            self._remote_event_bridge = None

        # Wire callbacks
        self._discord.set_message_callback(self._handle_new_message)
        self._discord.set_command_callback(self._handle_command)

        self._pid_path = Path(config.data_dir) / "bridge.pid"

        # Sprint 01.02 — declarative wiring manifest. Replaces the previous 28
        # scattered self._commands.set_*(...) calls between line ~479 and ~696
        # with a single declarative pass. Construction happened above; wiring
        # happens here. Order is preserved bit-for-bit from the pre-migration
        # call sequence so the operator's deploy-verification log line
        # ("Wiring complete: N active, M pending, K errors") is meaningful.
        self._wire()
