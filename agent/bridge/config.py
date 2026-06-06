"""Bridge configuration: TOML loading, env overrides, Keychain secrets, validation."""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, get_type_hints

from . import model_defaults  # P0.01 canonical default-model constants


class ConfigError(Exception):
    """Raised when configuration is invalid or cannot be loaded."""


# Sprint P6.3 (issue #1595) — feature flag registry hookup.
# Single source of truth for every bool feature flag on BridgeConfig is
# ``agent/config/feature_flags.yaml``. The drift audit at
# ``agent/scripts/check_feature_flags.py`` enforces that every bool field
# below has a registry entry. This module does NOT load the registry at
# runtime (registry is a contract for tooling/CI, not a runtime gate); it
# only exposes the canonical path so callers/tests can resolve it.
FEATURE_FLAGS_REGISTRY_PATH = (
    Path(__file__).resolve().parent.parent / "config" / "feature_flags.yaml"
)


# -- S31: BridgeConfig dataclass --

@dataclass(frozen=True)
class BridgeConfig:
    """Typed configuration for the Bumba bridge process."""

    # [bridge]
    data_dir: str = "/opt/bumba-harness/data"
    log_dir: str = "/opt/bumba-harness/logs"
    heartbeat_interval: int = 60
    # Embedding model dir (#2560), relative to the agent package root. The
    # in-process LocalEmbeddingEngine loads model.onnx + tokenizer.json from
    # here; absence → deterministic hash fallback (degraded recall). The dir
    # name selecting the model family (gemma vs arctic) drives task-prefix and
    # pooled-output handling — see docs/operator/embedding-model-setup.md.
    embedding_model_dir: str = "data/models/embeddinggemma-300m"

    # [discord]
    discord_bot_token: str = ""
    operator_discord_id: str = ""
    service_channel_id: str = ""
    discord_guild_id: str = ""
    discord_voice_channel_id: str = ""
    # Human-facing latency knobs for Discord. The bridge ACKs accepted
    # messages immediately, then uses these values for durable progress
    # notices while Claude continues working.
    discord_first_response_sla_seconds: int = 30
    discord_progress_interval_seconds: int = 120
    # D7.10 (#1422) — pre-emptive output-length budget for Discord
    # responses. The bridge appends a soft target hint to the system
    # context so the model targets ≤N chars when the operator surface
    # is Discord. Default 1800 leaves headroom under the 2000-char
    # free-account cap. Set to 0 to disable the hint.
    discord_output_target_chars: int = 1800

    # [backends] — Codex-3 (#1837): backend routing policy. Maps agent_role
    # (main / chief / specialist) to a backend implementation name (e.g.
    # "claude", "codex"). The BackendRegistry in bridge.backends.registry
    # resolves these names against the dict of constructed backend instances
    # at dispatch time. Dormant until the `backends_enabled` feature flag
    # flips; defaults route everything to "claude" so flag-off behavior is
    # unchanged.
    backends_enabled: bool = False
    # [backends] — defaults sourced from the canonical model-config module
    # (P0.01) so a single edit there flips the model-agnostic default
    # everywhere. Current value "claude" preserved as the documented default.
    backends_main: str = model_defaults.DEFAULT_BACKEND_NAME
    backends_chiefs_default: str = model_defaults.DEFAULT_BACKEND_NAME
    backends_specialists_default: str = model_defaults.DEFAULT_BACKEND_NAME
    backends_specialists_overrides: dict[str, str] = field(default_factory=dict)

    # [claude]
    claude_timeout: int = 120
    claude_hard_timeout: int = 600
    claude_absolute_timeout: int = 1800
    claude_max_turns: int = 25
    claude_output_format: str = "stream-json"
    claude_working_dir: str = "/opt/bumba-harness/agent-flat/agent"
    claude_max_retries: int = 3
    claude_binary: str | None = None
    # [codex] — Codex-2 (#1836) operator override for the Codex CLI binary
    # path. Resolution order in ``bridge.backends.codex.CodexBackend.
    # resolve_binary`` is env override → this field → ``shutil.which`` →
    # Homebrew / npm fallbacks. None preserves auto-discovery.
    codex_binary: str | None = None
    claude_oauth_token: str = ""
    claude_oauth_refresh_token: str = ""
    claude_oauth_expires_at: int = 0
    # Sprint Codex-4 (issue #1838) — ChatGPT-OAuth credentials for the Codex
    # CLI backend. Shape mirrors ``claude_oauth_*`` exactly so the same
    # secrets-parser pattern + the same lifecycle assumptions apply. Empty
    # defaults keep the field dormant when no Codex backend is configured.
    # The fail-closed boot validator in ``BridgeApp._initialize`` refuses to
    # start when any role resolves to ``codex`` via the Codex-3 ``[backends]``
    # registry and ``codex_oauth_token`` is empty. Per the operator-binding
    # amendment on #1838: subscription-billed ChatGPT-OAuth is the active
    # path; static ``codex_api_key`` is intentionally NOT plumbed here
    # because OpenRouter already provides per-token API access via
    # ``bridge.cross_model.openrouter_client``.
    codex_oauth_token: str = ""
    codex_oauth_refresh_token: str = ""
    codex_oauth_expires_at: int = 0
    # Sprint Codex-7-followup (issue #1872) — raw id_token JWT, fourth
    # field needed to round-trip ``~/.codex/auth.json`` correctly. The
    # CLI derives access-token expiry from this JWT's ``exp`` claim
    # (see ``bridge.backends._auth._decode_jwt_exp``), so the bridge
    # must carry it alongside the access/refresh pair.
    codex_oauth_id_token: str = ""
    # Sprint D8.1 — reduce warm-process MCP set to "core 4" to drop spawn time
    # from 30-120s to 3-8s. Path resolved relative to data_dir.parent / "agent"
    # if not absolute. Empty string preserves today's behavior (warm process
    # inherits .mcp.json from working_dir).
    warm_mcp_config: str = ""
    # Warm Claude is an optimization. Keep its per-message wait short so
    # known `claude -p` hangs fall back to one-shot instead of spending
    # several minutes in the warm path.
    warm_response_timeout_seconds: int = 60

    # [session]
    session_idle_timeout: int = 1800
    session_max_file_size: int = 31457280
    session_max_errors: int = 3
    session_max_messages: int = 40
    session_max_duration: int = 7200

    # [memory]
    memory_context_window: int = 20
    memory_max_context_tokens: int = 4000
    memory_summary_count: int = 3
    # Sprint 03.02 — gate the 3-layer progressive disclosure API on
    # bridge.hybrid_search.HybridSearch (search_ids / timeline /
    # get_observations). Concept-only port of claude-mem-style 3-layer
    # progressive disclosure (no source copied). Default False; operator
    # flips on after merge once plan-05 wires call sites. When False,
    # search_ids() returns the legacy SearchResult shape (with content).
    memory_v2_disclosure_enabled: bool = False
    # Sprint 03.05 — PreCompact externalization hook in
    # bridge.compaction_checkpoint.externalize_before_compact (issue #995).
    # Concept-only port of egregore PreCompact externalization (MIT, no
    # source copied). Default False keeps existing checkpoint behavior
    # unchanged. When True, callers wired to the compound-pressure trigger
    # path will write a high-value transcript subset to
    # data_dir/precompact/<session_id>/*.json before compaction runs.
    precompact_externalization_enabled: bool = False
    # Sprint E1.1 — hard-stop on context pressure overflow (issue #1233).
    # When True, the runner fires capture_checkpoint() + handoff message
    # instead of the soft-hint advisory when pressure crosses compact_now.
    # Default False — opt-in via [context_pressure] hard_stop_enabled = true.
    context_pressure_hard_stop_enabled: bool = False

    # [security]
    security_disallowed_tools: tuple[str, ...] = ()
    tool_failure_threshold: int = 5
    tool_failure_window: int = 600
    crash_loop_threshold: int = 5
    crash_loop_window: int = 600
    db_size_warn: int = 524288000
    db_size_alert: int = 1073741824

    # [mcp] — Issue #1543: MCPMonitor interval knob + EscalationEngine tie-in.
    # ``mcp_health_check_interval_seconds`` throttles the MCP server health
    # check inside ``background_loops.heartbeat_loop`` (the loop still ticks
    # at ``heartbeat_interval`` for other tasks; the MCP check only fires
    # when this interval has elapsed since the last successful check).
    # Default 300s matches the legacy alert cooldown — flip lower for
    # diagnostics or higher to reduce pgrep churn on the host.
    mcp_health_check_interval_seconds: int = 300

    # [voice]
    voice_enabled: bool = False
    voice_stt_url: str = "http://127.0.0.1:8880"
    voice_tts_url: str = "http://127.0.0.1:7888"
    voice_tts_voice: str = "af_sky"

    # [vapi] — D1.7a: VAPI voice integration scaffolding (wired but dormant).
    # All four fields default to "" and voice_enabled defaults to False so
    # today's object() placeholder behavior is preserved byte-for-byte.
    # D1.7b will add live API calls; D1.7c will add voice commands.
    vapi_api_key: str = ""
    vapi_phone_number_id: str = ""
    vapi_assistant_id_receptionist: str = ""
    vapi_webhook_url: str = ""
    # P2.3 (#1578, audit C8) — VAPI webhook shared secret. Always loaded from
    # .secrets; never stored in bridge.toml. The /api/v1/voice/webhook handler
    # rejects requests whose `X-VAPI-SECRET` header doesn't match this value
    # via secrets.compare_digest (constant-time). When voice_enabled=True the
    # APIServer.start() validator refuses to boot with an empty secret —
    # fail-closed mirror of #1626's allow_remote_bind pattern.
    vapi_webhook_secret: str = ""

    # [calcom] — Sprint audit-2026-05-16.B.05 (#2054, HI-6).
    # Cal.com webhook receiver fail-closed gate. Default OFF — the route
    # /api/webhooks/calcom returns 503 unless this flag flips, and the handler
    # rejects unsigned requests with 401 when no secret is configured. When
    # True, calcom_webhook_secret MUST be set or BridgeConfig.validate() fails
    # boot with ConfigError. The secret itself is loaded from .secrets
    # (calcom_webhook_secret=...); the handler in bridge/calcom_webhook.py
    # also reads it directly from .secrets at module level (kept as fallback).
    calcom_webhook_enabled: bool = False
    calcom_webhook_secret: str = ""

    # [rate_limit]
    rate_limit_initial_backoff: int = 30
    rate_limit_max_backoff: int = 1800
    rate_limit_multiplier: float = 2.0
    rate_limit_jitter: float = 0.5

    # [checkin]
    checkin_enabled: bool = True
    checkin_active_hours_start: int = 8
    checkin_active_hours_end: int = 22
    checkin_check_interval: int = 3600
    checkin_quiet_after_message: int = 1800
    checkin_minimum_gap: int = 7200

    # [briefing]
    briefing_enabled: bool = True
    briefing_delivery_hour: int = 7
    briefing_delivery_minute: int = 30

    # [fallback] — default sourced from canonical constants (P0.01). Current
    # value "anthropic/claude-3.5-sonnet" preserved as the documented default.
    fallback_openrouter_model: str = model_defaults.DEFAULT_OPENROUTER_MODEL
    openrouter_api_key: str = ""
    # Default model for the registered OpenRouter backend (P5.02). Distinct
    # from fallback_openrouter_model (the cross-model FallbackChain default):
    # this is the model OpenRouterBackend dispatches to when a caller does not
    # name one. A cheap-frontier model per the migration's OpenRouter-first
    # intent.
    openrouter_default_model: str = "deepseek/deepseek-chat"

    # [budget]
    budget_daily_budget: float = 0.0

    # [few_shot]
    few_shot_enabled: bool = True  # #23: A/B bypass flag — set False to skip injection

    # [api]
    api_enabled: bool = True
    api_port: int = 8200
    api_host: str = "127.0.0.1"
    api_token: str = ""
    # Audit C9 (P2.2): CORS origin allowlist. Empty tuple = no
    # ``Access-Control-Allow-Origin`` header on any response (safe default —
    # the bridge is reached same-origin via SSH tunnel or tailscale per P2.1
    # / audit C8). Operators wanting a browser dashboard add explicit origins
    # like ``["http://localhost:5173", "https://dash.example.com"]``.
    api_cors_allowed_origins: tuple[str, ...] = ()
    # P2.1 follow-up (#1626): explicit two-knob opt-in for non-local bind.
    # Even if an operator sets ``host = "0.0.0.0"`` in ``bridge.toml``, the
    # bridge refuses to start unless ``allow_remote_bind = true`` is also
    # set. Closes the gap where a single-knob misconfiguration could
    # silently re-expose the API after P2.1 flipped the default to
    # 127.0.0.1. See ``api_server.APIServer.start`` for the fail-closed
    # validator.
    api_allow_remote_bind: bool = False
    github_webhook_secret: str = ""

    # [api] — webhook signing
    # webhook_secret is read by app.py:435 to construct SerialEventDeliverer
    # with HMAC-SHA256 signing of outbound payloads (Sprint 06.06 rework
    # PR #843). DO NOT delete — six other "dead webhook/event_delivery_*"
    # knobs were removed in Sprint 01.07; this one is live.
    webhook_secret: str = ""

    # [proactive]
    proactive_enabled: bool = False
    proactive_min_sleep_seconds: float = 60.0
    proactive_max_sleep_seconds: float = 3600.0
    # NOTE: proactive_default_sleep_seconds was DELETED by Sprint 01.07 as a
    # dead knob and must stay deleted (regression guard at
    # tests/test_config.py::TestSprint0107DeletedKnobs). TickManager's own
    # default (300.0) is the source of truth — no config thread.
    # D7.12 #1424 (slice 1) — perpetual-proactive scheduler skeleton.
    # `_enabled=False` keeps the scheduler dormant; `_dry_run=True` makes
    # the slice-1 release inert (selection + ledger only, no dispatch).
    # Slice 2 will introduce a `_dispatch_enabled` knob that flips on the
    # subagent / [autonomous] PR pipeline once the soak observation closes.
    proactive_scheduler_enabled: bool = False
    proactive_scheduler_dry_run: bool = True
    proactive_scheduler_interval_seconds: float = 900.0  # 15 min default
    proactive_scheduler_budget_threshold: float = 0.75
    # D7.12 #1424 (slice 2) — dispatch surface flag. When True AND
    # dry_run=False, the scheduler invokes its dispatch_callback (typically
    # the AutonomousPlanDrafter — posts a 3-bullet `[autonomous]` plan
    # comment to the picked issue). Default off so slice 2 ships dormant
    # and the soak window observes only ledger writes until the operator
    # explicitly opts in.
    proactive_scheduler_dispatch_enabled: bool = False

    # [daily_log]
    # Sprint 09.14 — gate DailyLogWriter construction. Default True matches
    # the existing bridge.toml [daily_log].enabled = true; flag-flipping to
    # False causes /healthz to report daily_log: disabled and the /log
    # slash command to return empty.
    daily_log_enabled: bool = True

    # [webhooks]
    webhooks_enabled: bool = False
    webhooks_urls: tuple[str, ...] = ()
    webhooks_max_queue: int = 1000
    webhooks_timeout_sec: float = 30.0
    webhooks_max_retries: int = 3

    # [remote_kill_switch]
    # Field lives under remote_kill_switch; security section mapping is legacy-compatible.
    # Both `[security].remote_halt_url` and `[remote_kill_switch].halt_url` populate this
    # same field via _TOML_MAP — see lines below for the dual mapping.
    remote_halt_url: str = ""
    remote_halt_check_interval: int = 300

    # [verification]
    verification_enabled: bool = False
    # P2.5 follow-up (#1664) — verification policy level. Three valid
    # values: "off" (skip verifier entirely), "warn" (advisory; failures
    # appended to issues but verdict untouched — pre-P2.5 behaviour and
    # the default), "block" (failures force verdict = "fail" so the
    # existing fail-event plumbing in app.py fires). The
    # ``BUMBA_VERIFICATION_POLICY`` env var overrides this at runtime.
    # Unrecognised values fall back to "warn" with a startup warning
    # (back-compat with the env-var path in self_verifier.resolve_policy).
    verification_policy: str = "warn"

    # [evaluator] — issue #1565: operator opt-out for ResponseEvaluator.
    # Default ``True`` preserves current behaviour (evaluator runs on every
    # Claude response). Set ``[evaluator] enabled = false`` in bridge.toml
    # to skip the evaluator call entirely — useful for short-duration
    # offline diagnostics or to save the per-response model call cost. The
    # gate lives in ``BridgeApp._deliver_response`` next to the existing
    # ``self._evaluator and result.response_text`` check. Sibling knob to
    # ``[verification] policy`` — both control adversarial quality scoring.
    response_evaluator_enabled: bool = True

    # [quality_chain] — D1.4: gates WorkOrder completion through 7-gate pipeline
    quality_chain_enabled: bool = False
    branch_protection_enabled: bool = False
    # D1.5 — posture for branch_protection gate: "warn" (allow with EventBus
    # event + log, default for 7-day soak) or "block" (fail the quality gate).
    # Operator flips to "block" via bridge.toml after the soak period ends.
    branch_protection_posture: str = "warn"

    # [dispatcher]
    dispatcher_enabled: bool = False
    # Sprint S4.2 (#2345) — fail-closed E2B activation gate. The executor
    # remains a stub until the sandbox lifecycle ships; this flag only
    # expresses explicit operator intent and pairs with e2b_api_key.
    e2b_executor_enabled: bool = False
    e2b_api_key: str = ""
    # Sprint D-R3 (#1933) — operator-configurable timeout ceiling for
    # SubagentExecutor WorkOrder execution. Applied as
    # min(executor_timeout_seconds, wo.constraints.timeout_ms / 1000) at
    # the dispatch site, so the WorkOrder-level constraint may be lower
    # but never higher. Reduced from the prior 600s effective value
    # (which came from WorkOrderConstraints.timeout_ms default) after
    # D-R1 (#1931) surfaced the 10-minute latency cascade on
    # conversational messages. 120s is the appropriate ceiling for a
    # genuine Zone 4 WorkOrder; raise via bridge.toml only with cause.
    executor_timeout_seconds: int = 120
    # Sprint D-R3 (#1933) — operator override for the dispatcher gate
    # confidence threshold defined in
    # ``bridge.intent_classifier.DISPATCHER_MIN_CONFIDENCE``. Default
    # mirrors the constant; raise to make the gate stricter, lower (with
    # care) to widen dispatcher entry. Validators enforce [0.0, 1.0].
    min_dispatch_confidence: float = 0.8

    # [zone3]
    # Sprint 03.07 — when True, EnvironmentSelector.select() will pick the
    # second-highest-scoring environment instead of the default whenever
    # validate_selection() reports a skew warning for the default. Default
    # False keeps environment choice unchanged from today; the skew warning
    # is still observable in logs/events/WorkOrder rationale.
    env_selector_force_alternative: bool = False

    # Sprint 03.06 — relative path under data_dir for the WorkOrderStore
    # SQLite file. Resolved as Path(data_dir) / workorder_db_path at
    # construction time in BridgeApp._initialize. Kept relative so
    # tests can override data_dir without also overriding this field.
    workorder_db_path: str = "workorders.db"

    # Sprint 07.01 — gate the recursive WorkOrder decomposition contract
    # (TinyAGI/fractals concept-only port, MIT). Default OFF; existing
    # call sites stay on the atomic-only path. Sprint 07.02 wires the
    # real decomposer; 07.03 wires worktree fan-out.
    workorder_decomposition_enabled: bool = False
    # Sprint D1.6 — complexity threshold for recursive decomposition.
    # WorkOrders with a heuristic complexity score >= this threshold are
    # eligible for decomposition when the flag is on. Default 7/10 per
    # operator decision O4; operator can adjust post-deploy.
    workorder_decomposition_complexity_threshold: int = 7

    # [z4_observability]
    z4_observability_tool_tracker_enabled: bool = False

    # [peer]
    # Sprint 07.04 — gate self-registration into the in-process PeerRegistry
    # (and, in later sprints, SQLite persistence + peer API routes). Default
    # False preserves today's no-registration behavior; setting this True
    # makes BridgeApp construct a PeerRegistry + PeerRegistrationManager in
    # _initialize(), call start() on bridge start(), and stop() on shutdown.
    # Schema ownership stays bridge-local until bumba-memory-mcp can round-trip
    # bridge PeerRecord fields. See docs/architecture/peer-registry-ownership.md.
    peer_coordination_enabled: bool = False

    # [chief_dispatcher]
    # Z4-S12 (#1383) — feature flag for the Z4 chief-session subsystem.
    # When True, the api_server registers the ``GET /api/chief_sessions``
    # + ``GET /api/chief_sessions/{sid}`` endpoints. Default False until
    # Z4-S22 wires ``BridgeApp._chief_session_store`` at startup; this
    # sprint adds the routes and the flag, the wiring sprint flips both.
    chief_dispatcher_enabled: bool = False
    # Z4-S22 (#1395) — additional knobs the dispatcher reads at startup.
    # Default department falls through to "strategy" when no rule matches
    # (RuleBasedWorkOrderRouter Tier 4). Idle-timeout reaper (Z4-S30 #1391)
    # reads `idle_timeout_seconds` to decide which AWAITING_EVALUATION
    # sessions to TIMED_OUT.
    chief_dispatcher_default_department: str = "strategy"
    # zone4-warmth.D.01 (#2299): default extended 1800 → 14400 (30 min → 4h)
    # to match the warm-reuse intent. Per-team overrides via
    # ``team.constraints.warm_idle_timeout_seconds`` let operators dial each
    # department independently (Board/Strategy 4h, Design/QA 2h,
    # Ops/JobSearch 10 min per the warmth-plan recommendation). Operators
    # who want the pre-D.01 30-minute global can override via bridge.toml.
    chief_dispatcher_idle_timeout_seconds: float = 14400.0
    # Z4-S60 (#1404) — retry-with-backoff knobs for failed chief sessions.
    # ``retry_with_backoff(session_id, attempt)`` computes the delay as
    # ``min(initial * (multiplier ** (attempt - 1)), max_backoff)``, sleeps,
    # then re-warms the FAILED session (FAILED → WARM via ``retry_failed``).
    # ``max_attempts`` includes the initial run, so the default 3 means
    # the initial attempt + up to 2 retries before MaxRetriesExceededError.
    chief_dispatcher_retry_max_attempts: int = 3
    chief_dispatcher_retry_initial_backoff_seconds: float = 5.0
    chief_dispatcher_retry_max_backoff_seconds: float = 300.0
    chief_dispatcher_retry_backoff_multiplier: float = 2.0
    # Phase 3 (zone4-warmth.C.01, #2295): warmth-reuse feature flag.
    #
    # When True, ``ChiefDispatcher.dispatch()`` looks up an existing
    # AWAITING_EVALUATION session for the same (team, operator) within the
    # ``chief_dispatcher_idle_timeout_seconds`` window. If found, the prior
    # conversation's serialized message_history is deserialized and passed
    # to ``Agent.run(message_history=...)`` on the next invocation, skipping
    # system-prompt regeneration and reusing chief context across runs.
    #
    # Default flipped True 2026-05-18 (C.04 bypass — operator decision to
    # skip the 1-week shadow soak). Risk acknowledged: without shadow
    # observation, any latent quality regression (e.g. stale prior-
    # conversation context bleeding into mismatched new asks) surfaces
    # directly in operator-cycle output. Operators who want pre-Phase-3
    # cold-start-every-dispatch behavior can flip to False in bridge.toml.
    chief_dispatcher_warmth_reuse_enabled: bool = True

    # [telemetry]
    # Sprint 07.12 — gate per-session drift telemetry. When True,
    # SessionManager._expire_session emits a MetricsRecord (7 behavioural
    # metrics) to data/bridge-metrics.jsonl via drift_telemetry.record_metrics.
    # Default False preserves today's behavior (no telemetry writes). The
    # daily 2-sigma digest loop is a separate future sprint; this flag wires
    # only the data-collection side.
    drift_telemetry_enabled: bool = False
    bridge_metrics_path: str = "bridge-metrics.jsonl"

    # [zone4]
    # Z4-03 (2026-05-21 team-operability): durable run artifacts live outside
    # the bumba-open-harness repository by default. Operators can override this path,
    # but raw run artifacts should not be aimed at a target project unless that
    # is an explicit review decision.
    zone4_artifact_root: str = "/opt/bumba-harness/zone4-runs"

    # [logging]
    # Sprint 07.11 — when True, root logger uses bridge.log_format.JSONFormatter
    # (one JSON line per record). When False (default), the existing plain-text
    # formatter is preserved for human readability. CorrelationFilter is
    # installed unconditionally so session_id / message_id fields are populated
    # for whichever formatter is active.
    log_json_enabled: bool = False

    # [heartbeat]
    # Sprint 07.09 — dead-man's switch URL for an external uptime monitor
    # (healthchecks.io, Uptime Kuma, BetterStack, etc.). When set,
    # HeartbeatPinger pings every interval; if pings stop, the monitor
    # alerts the operator. Loaded from BOTH config/bridge.toml [heartbeat]
    # AND /opt/bumba-harness/data/.secrets — `.secrets` wins if both are
    # set (deployment-topology secret per spec Q12 #3). Default empty
    # string disables the pinger silently with one INFO log at startup.
    healthcheck_bridge_url: str = ""

    # [identity]
    # Sprint 17 / issue #637 / activation #817 — wire SOUL+OPERATOR+RULES into
    # Memory.assemble_context. Safe-rollout default: false. Flip to true after
    # 1-week soak confirms no regressions. `identity_max_bytes` caps the total
    # bytes of injected identity content to prevent context-window exhaustion.
    inject_identity: bool = False
    identity_max_bytes: int = 24576

    # [tool_rag]
    # Sprint 03.03 / spec ref-audit-03-03 — gate the Smart Tool RAG
    # selection path on tool_shed.get_tools_for_intent. Default False
    # preserves the existing agent-keyed get_tools_for_agent behavior;
    # callers must pass intent text and opt in to the RAG selection.
    # DORMANT (D1.10): tool_shed.get_tools_for_intent does not yet exist;
    # this flag will be wired when Sprint 03.03 ships.
    smart_tool_rag_enabled: bool = False

    # [memory_tiers]
    # Sprint 03.04 / spec ref-audit-03-04 — feature flag for the L0-L4 memory
    # tier hierarchy in temporal_knowledge.py. Default False keeps existing
    # callers untouched (the schema migration runs unconditionally so the
    # column is always present, but plan-05 capture-side classifiers only
    # call assign_tier / set_tier / promote when this is True). When False,
    # rows still receive DEFAULT_TIER ('L2') from the SQLite default — the
    # flag gates the *active* tier-aware paths, not the column itself.
    # DORMANT (#1536): Plan-05 capture-side classifiers not yet implemented;
    # this flag will be wired when Plan-05 ships. See agent/CLAUDE.md
    # "Config knobs known dormant" table.
    memory_tiers_enabled: bool = False

    # Sprint Mem-1 (#1842) — per-tier policy overrides for the Memory-Tier
    # Architecture epic. Default empty dict — `bridge.memory_tiers.load_tier_policies`
    # falls back to module-level defaults (PREFERENCE / DECISION / CONTEXT)
    # when this is unset. TOML key: `[memory_tiers.policies.<tier>]` (see
    # `bridge.toml` for the commented example block). Mem-3 wires this in;
    # at HEAD nothing reads it.
    memory_tiers_policies: dict = field(default_factory=dict)

    # Sprint Mem-6 (#1847) — token budget for the tier-aware context-window
    # assembly path. Consumed by `KnowledgeMixin._tiered_search_branch` when
    # `memory_tiers_enabled` is True. Default 4000 mirrors the module
    # constant `bridge.memory_enhancement.MAX_CONTEXT_TOKENS`. Larger
    # budget = more memory entries per Claude call; smaller = leaner
    # prompts. TOML key: `memory_tiers.context_window_tokens`.
    memory_tiers_context_window_tokens: int = 4000

    # Sprint Mem-8 (#1849) — strict-mode tier requirement. When True, the
    # hybrid_search.search_tiered path filters any row whose `tier` column
    # is NULL/empty and logs a WARNING per dropped row. Defensive against
    # any future schema change that relaxes Migration 14's NOT NULL guard;
    # on the current schema (DEFAULT 'context' NOT NULL) this is a no-op.
    # Flip True only AFTER the backfill script has run and the operator
    # wants fail-loud behavior on any straggler. Default False preserves
    # pre-Mem-8 behavior. TOML key: `memory_tiers.strict_tier_required`.
    strict_tier_required: bool = False

    # [memory] — Sprint 03.06 / spec ref-audit-03-06 (write-ahead log).
    # Concept-only port from egregore audit (MIT). When enabled, every
    # long-term memory mutation is appended to memory_wal_path *before*
    # the canonical SQLite write, then drained on success. On bridge
    # restart any leftover WAL entries are replayed so a mid-write crash
    # doesn't lose memory. Default False — flip after operator A/B
    # validation (Plan 03.10 territory).
    memory_wal_enabled: bool = False
    # Relative path under data_dir; resolved as Path(data_dir) / memory_wal_path.
    memory_wal_path: str = "memory_wal.jsonl"

    # [skill_version_dag]
    # Sprint 03.07 / spec ref-audit-03-07 (issue #997) — feature flag for the
    # skill version DAG schema in temporal_knowledge.py. Default False keeps
    # existing skill_evolution callers untouched (the schema migration runs
    # unconditionally so the tables are present and the read API is callable,
    # but plan-07 callers gate active writes from skill_evolution behind this
    # flag). Concept-only port of OpenSpace's skill-graph idea (MIT, no source
    # copied verbatim).
    skill_version_dag_enabled: bool = False

    # [skill_evolution]
    # Sprint 03.08 / spec ref-audit-03-08 (issue #998) — feature flag for the
    # 3-trigger skill evolution loop on SkillEvolutionEngine. Default False
    # keeps existing single-trigger behavior (record_failure →
    # detect_recurring_failures → create_proposal) untouched. When True,
    # call sites compose evaluate_post_execution / monitor_tool_degradation /
    # periodic_health_check with create_proposal to emit reason-tagged
    # proposals. Concept-only port of OpenSpace's three-trigger evolution
    # model (MIT, paraphrased).
    skill_evolution_loop_enabled: bool = False

    # Sprint 03.09 / spec ref-audit-03-09 (issue #999) — feature flag for the
    # crystallize-from-trace trigger on SkillEvolutionEngine. Default False
    # keeps the existing failure-pattern flow untouched. When True, callers
    # may pass a successful execution trace into
    # ``crystallize_from_trace`` and receive a draft SkillProposal with
    # ``reason="crystallized_from_trace"``. The engine method itself stays
    # pure — gating happens at the call site by passing this flag through
    # the ``enabled`` keyword. Concept-only port of GenericAgent's auto-
    # distill model (MIT, paraphrased).
    skill_crystallization_enabled: bool = False

    # Sprint 07.04 / spec ref-audit-07-04 (issue #1033) — feature flag for the
    # markdown-skill persistence + discovery convention on
    # SkillEvolutionEngine. Default False keeps existing skill flows
    # untouched (proposals stay in SQLite only). When True, operators may
    # opt in to writing crystallized skills as plain markdown under
    # ``agent/config/domain-skills/<domain>/<name>.md`` and discovery via
    # ``discover_markdown_skills``. The engine methods themselves stay
    # pure — gating happens at the call site by reading this flag.
    # Concept-only port of browser-harness's git-friendly skill directory
    # (MIT, paraphrased — no source copied verbatim).
    markdown_skills_enabled: bool = False

    # [board]
    # Sprint 04.01 / spec ref-audit-04-01 — gate anonymized A/B/C peer-ranking
    # in bridge.deliberation. Concept-only port (no llm-council source copied;
    # that repo has no license). Default False preserves the existing memo
    # rendering and ranking flow byte-for-byte. Plan 04.07 flips this on after
    # a 7-day shadow period; the helpers themselves
    # (assign_anonymous_labels / anonymize_responses / deanonymize) are pure
    # and safe to call directly under test.
    board_v2_enabled: bool = False

    # Sprint 04.03 / spec ref-audit-04-03 — gate cross-vendor seats on the
    # Strategy Board's roster. When False (default), the 3 ``adapter:
    # openrouter`` workers on board.yaml (``board-cross-vendor-strategist``,
    # ``board-openrouter-generalist``, ``board-systems-thinker``) are
    # filtered out of both the chief's roster and the employee agent map
    # by ``teams._factory._filter_cross_vendor_employees`` (#1724).
    #
    # Sprint 04.07 (#1961, 2026-05-14) corrects an earlier comment that
    # claimed ``agent_router.py`` consults non-Claude adapters when this
    # flag is True — it does not, and never did. Pre-#1961 this flag
    # gated nothing functional; the orphaned adapter wiring that was meant
    # to land in Sprint 04.07 never shipped, leaving the entire OpenRouter
    # routing surface broken. Post-#1961, runtime routing is prefix-based
    # (see ``teams._factory._resolve_model``) and this flag only controls
    # roster inclusion of the 3 explicitly-openrouter-adapter seats.
    #
    # Concept-only port (llm-council has NO LICENSE; no source code copied).
    # Default False was the original shadow-period intent (3 openrouter seats
    # held back until explicitly enabled).
    #
    # 2026-05-18 zone4-model-allocation: default flipped to True. After the
    # cost-optimization migration (every board member now routes via
    # OpenRouter on the cheap-frontier cohort), False would strip ALL board
    # members from the team build — `_filter_cross_vendor_employees` removes
    # every `adapter: openrouter` worker when the flag is off. The flag's
    # purpose was a shadow-period gate, not a permanent toggle; that period
    # is over.
    board_cross_vendor_enabled: bool = True

    # Sprint #1112/4.06 (#2153) — Initial entry #1: replace full-roster
    # enumeration in chief prompts with embedding-based top-K specialist
    # retrieval. When False (default), ``build_manager_agent`` keeps its
    # historical behaviour of rendering every specialist in the roster
    # block. When True, the caller passes a directive hint + a
    # ``SpecialistRetriever`` and the chief's prompt receives only the
    # top-3 matches by cosine similarity over ``~/.claude/agents``
    # frontmatter ``description:`` fields. Default-off per memory
    # ``feedback_settings_local_json_drift`` — operators opt in via
    # ``bridge.toml`` once they want to A/B the prompt-size reduction.
    specialist_retrieval_enabled: bool = False

    # Sprint 5.00c (#2155) — workflow-first dispatch. When True, the
    # ``ChiefDispatcher`` consults ``WorkflowRegistry.match(directive)``
    # BEFORE constructing a ChiefSession. A matched workflow short-circuits
    # the chief by firing the workflow directly via WorkflowEngine; the
    # dispatcher still returns a ChiefSession (in SHUTDOWN state with
    # ``metadata.workflow_run_id``) so callers don't see a contract change.
    # Default False per #1112 Initial entry #3 — operator opts in once ≥10
    # workflows are registered and observed working (today: 17 workflows
    # registered as of 2026-05-18, threshold met).
    workflow_first_dispatch_enabled: bool = False

    # Sprint 5j.04 (#2129) — Computer-use authorization for job-search
    # browser-use-specialist. Default OFF — operator opts in per the
    # sandbox runbook (docs/operator/computer-use-sandbox-setup.md):
    # create bumba-browser macOS user, configure mode-0640 .secrets with
    # group access, seed pfctl egress allowlist, run capability check.
    # The driver verifies UID matches bumba-browser at construction time;
    # invocation from any other UID raises SandboxBoundaryError. Per the
    # sandbox ADR #2158 + credential vault ADR #2159, this is the load-
    # bearing flag for the entire job-search browser-use stack.
    computer_use_enabled: bool = False

    # Sprint 2.07 (#2142) — Zone 1 drift-gate cron. Default OFF per the
    # operator-confirm safety rule: cron drafts proposals, operator decides,
    # operator merges. NEVER auto-writes or auto-merges. Heuristics include
    # dead-file-ref grep, stale count detection, outdated verification stamps.
    # Operator opts in via bridge.toml once a manual run confirms heuristic
    # quality.
    zone1_drift_enabled: bool = False

    # [cost]
    # Sprint 04.04 / spec ref-audit-04-04 (issue #1005) — gate the per-feature
    # daily budget cap layer in cost_tracker.CostTracker.check_feature_cap.
    # Default False = bypass mode (always returns (True, "")), which keeps
    # existing call sites unaffected. When True, registered feature caps
    # (e.g. board: $1.00/day, auto-registered when board_v2_enabled is True)
    # are enforced. Composes with — does not replace — the global daily
    # budget enforcement in bridge.budget.
    feature_cost_caps_enabled: bool = False

    # [factory]
    # Sprint 14.04 / spec ref-audit-14-04 (issue #1042) — gate the Dark Factory
    # triage workflow that classifies `factory:opt-in` issues into
    # accept/reject/rate-limit/needs-human via a single sonnet subprocess call.
    # Concept-only port of coleam00/dark-factory-experiment (no LICENSE, no
    # source copied). Default False keeps the orchestrator from invoking
    # triage; the workflow is callable directly for tests/manual runs but is
    # a no-op via the public surface when this flag is OFF. Sprint 14.10 wires
    # the orchestrator call site.
    factory_triage_enabled: bool = False

    # Sprint 14.05 / spec ref-audit-14-05 (issue #1043) — gate the Dark Factory
    # implement workflow that picks `factory:accepted` issues, runs a 10-phase
    # agent pipeline (classify → plan → branch → implement → commit → test →
    # lint → draft-pr → transition → cleanup) inside an isolated git worktree
    # and opens a draft PR labeled `factory:needs-review`. Concept-only port
    # of coleam00/dark-factory-experiment (no LICENSE, no source copied).
    # Default False — the workflow is a callable function callable directly
    # for tests/manual runs but a no-op via the public surface when OFF.
    # Sprint 14.10 wires the orchestrator call site.
    factory_implement_enabled: bool = False

    # Sprint 14.07 / spec ref-audit-14-07 (issue #1045) — gate the Dark Factory
    # validate workflow that dispatches 4 holdout reviewers (behavioral,
    # security, code quality, test quality) against a draft PR opened by the
    # implement workflow. Each reviewer is a Haiku subprocess in an isolated
    # context with no shared state; outputs are aggregated and any `block`
    # verdict transitions the issue to `factory:needs-human`. Concept-only
    # port of coleam00/dark-factory-experiment (no LICENSE, no source copied).
    # Default False — the workflow is callable directly for tests/manual runs
    # but a no-op via the orchestrator seam (Sprint 14.10) when OFF.
    factory_validate_enabled: bool = False

    # Sprint 14.10 / spec ref-audit-14-10 (issue #1048) — gate the Dark Factory
    # orchestrator service that composes triage → implement → quality →
    # validate → synthesize → route into a 4h scheduled loop. Concept-only
    # port of coleam00/dark-factory-experiment (no LICENSE, no source copied).
    # Default False — operator opts in via bridge.toml after the triage /
    # implement / validate flags are also enabled. Sprint 14.10 owns this
    # service's call site at ``bridge/services/factory_orchestrator.py``.
    factory_orchestrator_enabled: bool = False

    # Sprint 14.09 / spec ref-audit-14-09 (issue #1047) — gate the Dark Factory
    # fresh-context fix loop that, on a synthesizer NEEDS_FIX outcome, spawns
    # up to 2 fresh Claude subprocesses (no --resume, no inherited session)
    # to address validator block reasons before escalating to
    # `factory:needs-human`. Concept-only port of
    # coleam00/dark-factory-experiment (no LICENSE, no source copied).
    # Default False — operator opts in via bridge.toml. The fix-loop module
    # is callable directly for tests/manual runs; the orchestrator call site
    # at ``bridge/services/factory_orchestrator.py`` is the gated seam.
    factory_fix_loop_enabled: bool = False
    # Sprint 14.09 — hard ceiling on auto-fix attempts. Default 2 mirrors
    # the spec ("max 2 attempts, then escalate"). The fix-loop module
    # additionally caps at DEFAULT_MAX_ATTEMPTS as a defensive backstop.
    factory_fix_loop_max_attempts: int = 2
    # Sprint 14.09 — per-attempt cost cap. Breach fails *that* attempt
    # (FixAttemptResult.error set); the next attempt still runs. Two
    # attempts × $1.50 = $3.00, matching ``factory_fix_loop_cost_cap_total_usd``
    # below.
    factory_fix_loop_cost_cap_per_attempt_usd: float = 1.50
    # Sprint 14.09 — total cost cap across all attempts in a single loop.
    # Breach mid-loop stops the loop and escalates so the cost-kill-switch
    # discipline matches the synthesizer's Rule 7.
    factory_fix_loop_cost_cap_total_usd: float = 3.00

    # Sprint 14.11 / spec ref-audit-14-11 (issue #1050) — gate the Dark Factory
    # soak harness service that runs the orchestrator pipeline in shadow mode
    # (observe-only, never acts) so the operator can verify 5 representative
    # issues against the factory's would-have-done predictions before flipping
    # ``factory_orchestrator_enabled`` to True. Default False — operator opts
    # in via bridge.toml. Distinct flag + service from the orchestrator's
    # production-action flag above; the harness never touches GitHub state
    # regardless of this flag's neighbour. Concept-only port of
    # coleam00/dark-factory-experiment (no LICENSE, no source copied).
    factory_soak_harness_enabled: bool = False
    # Sprint 14.11 — operator-tunable production-enable thresholds. Defaults
    # mirror the spec (5 verified-correct issues at 80% correctness over
    # ≥14d). Lowering either is a deliberate operator call documented at
    # flag-flip time.
    factory_soak_min_verified_count: int = 5
    factory_soak_min_correctness_rate: float = 0.80

    # Sprint 15.03 / spec ref-audit-15-03 (issue #1053) — gate the mailbox
    # back-channel between the bridge and the factory implement worker
    # subprocess. When OFF (default) the implement workflow runs as before
    # (one-way subprocess; bridge parses stdout). When ON the bridge opens
    # a per-issue Mailbox(role='bridge'), passes BUMBA_MAILBOX_NAME +
    # BUMBA_MAILBOX_DATA_DIR to the worker, and the worker may stream
    # progress, decision-requests, and partial-cost telemetry back via
    # bridge.factory.implement_mailbox_worker. Concept-only port of the
    # NanoClaw v2 dual-DB pattern (no LICENSE, no source copied).
    factory_mailbox_enabled: bool = False
    # Sprint 15.03 — bridge poll interval for worker_to_bridge messages.
    # Default 2s balances responsiveness with SQLite open/close cost.
    factory_mailbox_poll_interval_seconds: int = 2
    # Sprint 15.03 — max wall-clock time the worker blocks waiting for an
    # operator decision before falling back to the no-answer path. 1h
    # default matches the spec's "operator-gated" expectation.
    factory_mailbox_decision_timeout_seconds: int = 3600

    # Sprint 15.04 / spec ref-audit-15-04 (issue #1054) — gate the
    # channels-as-branches routing in the factory orchestrator. When OFF
    # (default) the orchestrator ignores ``factory:channel:*`` labels and
    # runs each child against ``main`` (legacy single-PR-per-issue
    # behaviour). When ON, an issue carrying ``factory:channel:<name>``
    # is routed to a per-channel integration branch
    # (``factory/channel/<name>/integration``); on every child PR merge
    # the orchestrator checks ``is_channel_close_ready`` and files a
    # ``factory:channel-close:<name>`` issue when no open child remains.
    # Concept-only port — Dark Factory channels variant (no LICENSE).
    factory_channels_enabled: bool = False
    # Sprint 15.04 — integration-branch prefix. Branches land at
    # ``<prefix>/<name>/integration`` so the existing git-worktree-gc
    # service keeps treating them as factory-owned (the prefix must
    # start with ``factory/``). Override at your own risk.
    factory_channels_integration_branch_prefix: str = "factory/channel"

    # [second_brain]
    # Sprint 05.0a / spec ref-audit-05-0a (issue #1018) — gate the
    # second-brain baseline-ingest pipeline that records pre-existing
    # operator-vault notes as grandfathered for the day-1 lint pass.
    # Default False keeps the subsystem inert until the operator opts
    # in. ADR Decision 1 signed 2026-05-01 (operator's vault is the
    # canonical wiki location). Concept-only — no source copied
    # (Karpathy gist informs the markdown-wiki shape only).
    second_brain_baseline_enabled: bool = False

    # Sprint 05.0b / spec ref-audit-05-0b (issue #1019) — gate the daily
    # vault-backup primitives in bridge.second_brain.backup. Default False
    # keeps the bridge from calling ensure_snapshot_today before any
    # contribution write; the primitives themselves stay pure and testable
    # regardless. Sprint 05.07 wires the call site behind this flag.
    # ADR: agent/docs/architecture/second-brain.md#decision-1-wiki-location
    # (the operator signed 2026-05-01 — wiki = operator's Obsidian vault).
    second_brain_backup_enabled: bool = False

    # [job_search]
    # Sprint 06.03 / spec ref-audit-06-03 (issue #1024) — gate the A-F
    # rubric scoring inside JobSearchAgent._research_phase + the
    # cover-letter / submit / outreach filter inside prepare(). Default
    # False keeps the cron untouched (no Haiku eval cost; no behavioural
    # filter). When True, rubric.evaluate runs per-listing; only listings
    # at-or-above ``job_search_rubric_threshold`` reach cover-letter
    # generation. Filtered listings are still staged in Notion (06.04
    # adds rubric columns there) so the operator can override.
    job_search_rubric_gate_enabled: bool = False
    # Operator-tunable letter-grade floor: A / B / C / D / F. Default "B"
    # mirrors the rubric.yaml threshold band (B >= 3.5, A >= 4.5).
    job_search_rubric_threshold: str = "B"
    # Sprint D5.2 (issue #1207) — gate job-search Zone 4 team scaffold.
    # When True, the PREPARE + EXECUTE cron entry points delegate to
    # job-search-chief (Zone 4 team) and write a per-run conversation log
    # at data/teams/job_search/conversations/<run_id>.jsonl. Default False
    # keeps the existing direct-service path (JobSearchAgent) unchanged.
    # D5.3+ will migrate logic from JobSearchAgent into the specialists;
    # this flag gates the delegation seam only.
    job_search_team_enabled: bool = False

    # [interrupts] — E1.5 universal tool-call gate + DialogueDelayMonitor
    # thresholds (issue #1237). All four flags are gated so operators can
    # tune thresholds or disable the gate without redeploying code.
    #
    # universal_tool_gate_enabled: when True (default), ClaudeRunner checks
    #   evaluate_gate(inbox) before spawning a subprocess. If the gate
    #   returns any BLOCK_* decision, invoke() returns the block_message
    #   instead of spawning Claude.
    # dialogue_delay_threshold_seconds: age after which a pending operator
    #   message emits a DELAY observability event (default 60s).
    # force_pause_threshold_seconds: age after which a FORCE_PAUSE event is
    #   emitted and the ForcePauseAlerter fires (default 300s).
    # poll_interval_seconds: DialogueDelayMonitor background-poll interval
    #   (default 10s).
    universal_tool_gate_enabled: bool = True
    dialogue_delay_threshold_seconds: int = 60
    force_pause_threshold_seconds: int = 300
    interrupts_poll_interval_seconds: int = 10
    # min_pending_to_gate: number of pending operator messages required to
    #   trigger a BLOCK_* decision. 1 = current behavior (any pending message
    #   blocks). 2+ = a single lone message no longer halts work, allowing
    #   short conversational openers ("hi") to flow through even if they
    #   classify as QUESTION. The classifier-side whitelist handles common
    #   greetings explicitly; this knob is the durable backstop for any
    #   other content that shouldn't single-handedly halt the work loop.
    min_pending_to_gate: int = 1

    # Sprint 05.04 / spec ref-audit-05-04 (issue #1013) — master gate for
    # the second-brain contributor subsystem. When True at bridge startup,
    # BridgeApp._initialize() calls ensure_subtree() against
    # second_brain_vault_root to materialize bumba-contributions/staging/
    # + bumba-contributions/curated/. Default False — subsystem stays
    # inert until the operator opts in. ADR Decision 3 (signed
    # 2026-05-01) — hybrid quarantine; Bumba never writes canonical.
    second_brain_enabled: bool = False

    # Sprint 05.04 — absolute path to the operator's second-brain vault
    # root (typically the Obsidian vault). Empty string = subsystem
    # disabled even when second_brain_enabled is True (defensive — a
    # mis-configured flag must never write to an unintended directory).
    # The bumba-contributions/ subtree is created directly under this
    # path; operator-canonical content above it is never touched.
    second_brain_vault_root: str = ""

    # Sprint 05.07 / spec ref-audit-05-07 (issue #1015) — per-contributor
    # granular control flags for the three concrete contributors that
    # mirror existing bridge surfaces into the operator's vault. All
    # default True so that flipping ``second_brain_enabled`` on without
    # any further config wires the standard publishing surface. Operator
    # opts a single contributor out by setting its flag to False (e.g.
    # to silence reflection mirrors during a low-quality streak).
    # Contributors are read at registry-build time inside
    # ``BridgeApp._initialize`` — runtime flag flips require a restart.
    second_brain_contributor_dailylog_enabled: bool = True
    second_brain_contributor_reflection_enabled: bool = True
    second_brain_contributor_consolidation_enabled: bool = True

    # Sprint 05.08 / spec ref-audit-05-08 (issue #1016) — operator-tunable
    # retrieval strategy for ``bridge.second_brain.query``. ADR Decision 4
    # (signed 2026-05-01) — index.md primary, hybrid_search as accelerator.
    # ``index_first`` (default) walks the IngestNote index and falls
    # through to hybrid_search when hits are sparse; ``index_only`` skips
    # hybrid_search entirely (small-vault mode); ``hybrid_only`` skips the
    # index walk (high-cardinality / pure-semantic queries). Concept-only
    # — no source copied (Karpathy gist informs the two-tier shape).
    second_brain_query_strategy: str = "index_first"
    # Top-K cap on the merged result set returned by query().
    second_brain_query_k: int = 10
    # Index-hit count below which ``index_first`` invokes hybrid_search.
    # Higher values = more aggressive fallthrough.
    second_brain_query_fallthrough_threshold: int = 3

    # Sprint 05.09 / spec ref-audit-05-09 (issue #1017) — gate the daily
    # vault lint pass that runs inside ``KnowledgeReviewService`` after
    # the existing knowledge-review work. Default False — operator opts
    # in. ADR Decision 5 signed 2026-05-01 (wiki = SoT;
    # temporal_knowledge = audit log; lint warnings flag schema /
    # integrity issues but never block writes). Concept-only — no
    # source copied (Karpathy gist informs the markdown-wiki shape).
    second_brain_lint_enabled: bool = False
    # Schema integer the lint pass enforces. Bumps require an ADR
    # addendum + migration script per
    # second-brain-schema.md#schema-versioning.
    second_brain_lint_schema_version: int = 1

    # Sprint 05.11 / spec ref-audit-05-11 (issue #1021) — 14-day shadow
    # + auto-routing decision harness for consolidation outputs. When
    # ``second_brain_shadow_router_enabled`` is True, BridgeApp wires a
    # :class:`bridge.second_brain.shadow_router.ShadowRouter` that
    # records what the auto-router *would* have done to each
    # ConsolidationContributor output. The router NEVER modifies vault
    # files — only writes JSONL sidecars to ``data/shadow-router/``.
    # ``window_days`` controls the rolling /shadow_report window
    # (default 14, matches the spec). ``promote_threshold`` is the
    # agreement-rate floor required for the "ready to flip"
    # recommendation in the report. ADR Decision 4 (signed 2026-05-01).
    # Concept-only port — no source copied.
    second_brain_shadow_router_enabled: bool = False
    second_brain_shadow_router_window_days: int = 14
    second_brain_shadow_router_promote_threshold: float = 0.90

    # [experiment_loop]
    # Sprint audit-2026-05-15.B.01 (issue #1996) — runtime mode trichotomy
    # for the experiment loop, replacing the legacy --dry-run boolean.
    # ``proposal_only`` exits before running the experiment, ``shadow``
    # validates and records but never ff-merges, ``production`` is the
    # historical keep/discard merge behavior. Default ``shadow`` matches
    # the current plist's effective behavior post-A.02.
    experiment_mode: Literal["proposal_only", "shadow", "production"] = "shadow"

    # Sprint audit-2026-05-16.A.05 (#2049, Section 8.3) — operator throttle
    # for the first production unhalt. Both default to "no throttle" so
    # existing shadow/proposal runs are unaffected; the operator dials them
    # up in bridge.toml before the first production unhalt.
    experiment_max_iterations_per_hour: int | None = None
    experiment_cooldown_after_merge_seconds: int = 0

    # Sprint 02.04 / spec ref-audit-02-05 (issue #979) — MAD confidence
    # scoring on fitness deltas. ``experiment_mad_window`` is the number
    # of recent iterations pulled from ``data/experiments.jsonl`` when
    # estimating the noise floor. ``experiment_mad_k`` is the multiplier
    # on the median absolute deviation that produces the confidence
    # band: K = 1.96 corresponds to ~95% CI under a true Gaussian, K =
    # 2.0 is the conservative-95% multiplier for the fat-tailed,
    # non-Gaussian runtime distribution we actually observe. Defaults
    # mirror ``scripts.experiment_loop.MAD_WINDOW`` / ``MAD_K``. This
    # sprint exposes the band advisorily; Sprint 02.05 wires it into
    # the keep/discard decision.
    experiment_mad_window: int = 20
    experiment_mad_k: float = 2.0

    # Sprint 02.13 / spec ref-audit-02-13 (issue #988) — stale threshold
    # for the experiment-loop heartbeat surfaced in /healthz. Default is
    # 2x the loop's 10-minute tick. Operator-tunable so a slower-tick
    # deployment can raise the bar without code change.
    experiment_heartbeat_stale_seconds: int = 1200

    # Sprint 02.14 / spec ref-audit-02-14 (issue #989) — holdout validator
    # subprocess that judges experiment-loop diffs against the program
    # from ``origin/main``. Default OFF — operator opts in once the
    # quality gates from #1142 have shipped a clean run of iterations.
    # ``cost_cap_usd`` is the per-invocation defensive cap (the actual
    # spend already happened by the time we see it; the cap surfaces
    # the breach as ``parse_error="cost_cap_exceeded"`` so the iteration
    # treats the verdict as UNSURE). ``model`` is operator-tunable —
    # haiku for cost, sonnet for fidelity.
    experiment_validator_enabled: bool = False
    experiment_validator_cost_cap_usd: float = 0.30
    experiment_validator_model: str = "haiku"
    # Sprint audit-2026-05-16.E.03 (#2071, Section 8.1) — validator readiness
    # contract. When experiment_validator_enabled = True, all four backing
    # settings (cost cap, model, timeout, min-signal floor) MUST be set to
    # positive/non-empty values or _validate raises ConfigError. Both new
    # fields default to 0 = "unset" so the validator stays opt-in and the
    # fail-closed check only fires when the operator has explicitly flipped
    # enabled = True.
    experiment_validator_timeout_seconds: int = 0
    experiment_validator_min_signals: int = 0

    # Sprint 15.02 / spec ref-audit-15-02 (issue #1052) — wire the mailbox
    # primitive (PR #1153) into the experiment-loop worktree boundary.
    # Default OFF so the loop continues to behave exactly as it does
    # today; operator opts in once the mailbox primitive has shipped a
    # clean run of iterations.  ``poll_interval_seconds`` is the bridge-
    # side cadence for ``mbox.read_since(...)`` while the subprocess
    # runs; ``vacuum_keep_n`` bounds the per-direction outbound table so
    # a long-running iteration doesn't grow the SQLite file unboundedly.
    experiment_mailbox_enabled: bool = False
    experiment_mailbox_poll_interval_seconds: int = 2
    experiment_mailbox_vacuum_keep_n: int = 5000

    # Sprint 02.04 / spec ref-audit-02-04 (issue #978) — append-only
    # ``autoresearch/iter-NNNN`` audit-branch trail. Default OFF because
    # the feature is additive: it accumulates branches that survive the
    # discard path, and the operator decides when the storage commitment
    # is worth it. ``push_to_origin`` is a separate gate because pushing
    # 1000+ branches/year up to GitHub is a bandwidth/storage decision
    # the operator must opt into independently of the local-only feature.
    experiment_audit_branches_enabled: bool = False
    experiment_audit_branches_push_to_origin: bool = False

    # Sprint audit-2026-05-16.E.02 (#2070, Section 8.2) — when audit branches
    # are enabled in LOCAL mode (push_to_origin=False), automatically delete
    # the local audit branch after a successful merge to keep the local
    # branch list bounded during multi-day trials. Default OFF so existing
    # operator workflows that depend on branch persistence (e.g. forensic
    # inspection days later) are not surprised. Has no effect when
    # audit_branches_enabled is False or when push_to_origin is True
    # (remote branches are never auto-cleaned by this flag).
    experiment_audit_branches_local_cleanup: bool = False

    # Sprint 02.08 / spec ref-audit-02-08 (issue #983) — finalize-experiments
    # operator command. Default OFF: the script is callable directly via
    # ``python -m scripts.finalize_experiments`` regardless, but the
    # ``/experiment_finalize`` operator surface stays gated until the
    # operator opts in. ``default_window_days`` and ``jaccard_threshold``
    # mirror the script's CLI defaults so flipping the flag doesn't
    # change behaviour.
    experiment_finalize_enabled: bool = False
    experiment_finalize_default_window_days: int = 30
    experiment_finalize_jaccard_threshold: float = 0.5

    # Sprint ref-audit-02-11 / spec ref-audit-02-11 (issue #986) — defense-in-depth
    # branch-name guard for the experiment loop's push code path. Default ON
    # because this is a security default — it costs nothing when no push is
    # attempted, and refuses pushes outside the allowed namespaces (see
    # ``scripts/experiment_loop_push_guard.ALLOWED_PUSH_NAMESPACES``) before
    # the network call. The GitHub PAT scope is still the primary deny gate;
    # this flag exists so an operator running an isolated test suite that
    # *intentionally* pushes to a non-standard branch can disable it without
    # editing source.
    experiment_push_guard_enabled: bool = True

    # [handoff] — Sprint 1112.1.01 (#2138): cross-harness operator-mediated
    # handoff protocol scaffolding. ``harness_id`` names this harness so a
    # handoff packet can be addressed unambiguously (e.g. "local-1" →
    # "mini-1"). ``peer_harness_ids`` is the allowlist of harnesses that
    # may *send* handoffs to this one; an empty tuple means no peers are
    # trusted yet, which is the safe default until the operator opts in.
    # Behavior is dormant until the Phase 1 composer + peer-listener
    # sprints land; these fields exist now so the data-model types in
    # ``bridge.handoff`` have a runtime-resolvable home.
    harness_id: str = "local-1"
    peer_harness_ids: tuple[str, ...] = ()

    # [handoff] — Sprint 1112.1.03 (#2140): the receiver-side listener
    # accepts handoff messages only from peer-bot Discord user IDs that
    # appear in this allowlist. This is a structural complement to
    # ``peer_harness_ids`` (which names harnesses logically) — ``peer_harness_bot_ids``
    # names *Discord identities*. An empty tuple is the safe default
    # (no peers can route handoffs to this harness).
    peer_harness_bot_ids: tuple[str, ...] = ()

    # ------------------------------------------------------------------
    # Cross-field invariants (issue #1541, Plan W W-5.2)
    # ------------------------------------------------------------------
    def validate(self) -> None:
        """Check cross-field invariants and raise ``ConfigError`` on failure.

        Single-field range checks live in :func:`_validate` (module level)
        because they predate this method and several pre-existing tests
        invoke ``_validate(config)`` directly. This method covers the
        *combinatorial* cases: pairs / triples of fields where each value
        is individually legal but the combination is contradictory.

        Invariants checked (each raises ``ConfigError`` naming both fields):

        - ``chief_dispatcher_enabled`` requires non-empty
          ``chief_dispatcher_default_department``. The Tier-4 fallback in
          :class:`bridge.work_order_router.RuleBasedWorkOrderRouter` resolves
          to this field when no rule matches; an empty value would route
          every unrouted WorkOrder to a department named ``""``.
        - ``universal_tool_gate_enabled`` requires ``min_pending_to_gate >= 1``.
          ``tool_call_gate.evaluate_gate`` clamps the value at ``max(1, n)``
          internally, but accepting a 0 / negative knob would silently mask
          an operator typo.
        - ``proactive_scheduler_enabled`` requires
          ``proactive_scheduler_interval_seconds > 0``. The scheduler loop
          sleeps for this many seconds between ticks; a 0 / negative value
          would either spin or crash the loop on first tick.
        - ``voice_enabled`` requires non-empty ``vapi_api_key``. Per
          ``agent/CLAUDE.md`` "Key Behaviors": activating voice requires
          adding the VAPI key to ``.secrets`` — without it the voice
          subsystem can't reach VAPI and would silently fail at first call.
        - ``e2b_executor_enabled`` requires non-empty ``e2b_api_key``.
          E2B activation must be explicit and credentialed before any
          future sandbox lifecycle can become routable.
        - ``api_enabled`` requires ``1 <= api_port <= 65535``. Standard
          TCP port range; rejecting at startup beats an opaque
          ``OSError: [Errno 49] Can't assign requested address`` mid-bind.
        - ``budget_daily_budget`` must be non-negative. ``BudgetGuard``
          treats 0.0 as "no cap" (the default); negative values are
          nonsensical and would either disable the guard or trip
          ``budget_exceeded`` on every spend check.
        """
        # Invariant 1: chief_dispatcher_enabled requires default_department
        if (
            self.chief_dispatcher_enabled
            and not self.chief_dispatcher_default_department.strip()
        ):
            raise ConfigError(
                "chief_dispatcher_enabled = true requires a non-empty "
                "chief_dispatcher_default_department (got empty string); "
                "the Tier-4 fallback in RuleBasedWorkOrderRouter resolves "
                "to this field when no rule matches."
            )

        # Invariant 2: universal_tool_gate_enabled requires min_pending_to_gate >= 1
        if self.universal_tool_gate_enabled and self.min_pending_to_gate < 1:
            raise ConfigError(
                "universal_tool_gate_enabled = true requires "
                f"min_pending_to_gate >= 1 (got {self.min_pending_to_gate}); "
                "values below 1 would either always-block or never-block "
                "depending on classifier output."
            )

        # Invariant 3: proactive_scheduler_enabled requires positive interval
        if (
            self.proactive_scheduler_enabled
            and self.proactive_scheduler_interval_seconds <= 0
        ):
            raise ConfigError(
                "proactive_scheduler_enabled = true requires "
                "proactive_scheduler_interval_seconds > 0 (got "
                f"{self.proactive_scheduler_interval_seconds}); "
                "the scheduler loop sleeps for this many seconds between "
                "ticks."
            )

        # Invariant 4: voice_enabled requires vapi_api_key
        # NOTE: P2.3's fail-closed startup validator in APIServer.start()
        # covers the separate `vapi_webhook_secret` field. This invariant is
        # distinct: it gates on `vapi_api_key` (outbound API auth) rather than
        # `vapi_webhook_secret` (inbound webhook auth). An operator enabling
        # voice needs BOTH.
        if self.voice_enabled and not self.vapi_api_key.strip():
            raise ConfigError(
                "voice_enabled = true requires a non-empty vapi_api_key "
                "(got empty string); add `vapi_api_key=<key>` to "
                "/opt/bumba-harness/data/.secrets or disable voice with "
                "[voice] enabled = false in bridge.toml."
            )

        # Invariant 5: e2b_executor_enabled requires e2b_api_key
        if self.e2b_executor_enabled and not self.e2b_api_key.strip():
            raise ConfigError(
                "e2b_executor_enabled = true requires a non-empty "
                "e2b_api_key (got empty string); add "
                "`e2b_api_key=<key>` to /opt/bumba-harness/data/.secrets "
                "or disable E2B with [dispatcher] e2b_executor_enabled = false."
            )

        # Invariant 6: api_enabled requires valid port range
        if self.api_enabled and not (1 <= self.api_port <= 65535):
            raise ConfigError(
                f"api_enabled = true requires 1 <= api_port <= 65535 "
                f"(got {self.api_port}); see [api] section in bridge.toml."
            )

        # Invariant 7: budget_daily_budget must be non-negative
        if self.budget_daily_budget < 0:
            raise ConfigError(
                f"budget_daily_budget must be >= 0 "
                f"(got {self.budget_daily_budget}); use 0.0 to disable "
                "the daily budget cap."
            )

        # Invariant 8: calcom_webhook_enabled requires calcom_webhook_secret
        # audit-2026-05-16.B.05 (#2054, HI-6) — fail-closed pairing. The
        # /api/webhooks/calcom route only accepts traffic when the flag is
        # True; the handler rejects unsigned requests when the secret is
        # absent. Refusing boot here prevents the third state where the flag
        # is on but the secret is missing, which would 401 every legitimate
        # delivery silently.
        if self.calcom_webhook_enabled and not self.calcom_webhook_secret.strip():
            raise ConfigError(
                "calcom_webhook_enabled = true requires a non-empty "
                "calcom_webhook_secret (got empty string); add "
                "`calcom_webhook_secret=<secret>` to "
                "/opt/bumba-harness/data/.secrets or disable the receiver "
                "with [calcom] webhook_enabled = false in bridge.toml. "
                "(audit-2026-05-16.B.05 / HI-6)"
            )


# Mapping from TOML section.key → dataclass field name
_TOML_MAP: dict[str, str] = {
    "bridge.data_dir": "data_dir",
    "bridge.log_dir": "log_dir",
    "bridge.heartbeat_interval": "heartbeat_interval",
    "bridge.embedding_model_dir": "embedding_model_dir",
    "discord.guild_id": "discord_guild_id",
    "discord.service_channel_id": "service_channel_id",
    "discord.voice_channel_id": "discord_voice_channel_id",
    "discord.first_response_sla_seconds": "discord_first_response_sla_seconds",
    "discord.progress_interval_seconds": "discord_progress_interval_seconds",
    "discord.output_target_chars": "discord_output_target_chars",
    "claude.timeout": "claude_timeout",
    "claude.hard_timeout": "claude_hard_timeout",
    "claude.absolute_timeout": "claude_absolute_timeout",
    "claude.max_turns": "claude_max_turns",
    "claude.output_format": "claude_output_format",
    "claude.working_dir": "claude_working_dir",
    "claude.max_retries": "claude_max_retries",
    "claude.binary": "claude_binary",
    # Codex-2 (#1836) — operator override for the Codex CLI binary path.
    # Lives under [codex] in bridge.toml; parallels [claude] binary.
    "codex.codex_binary": "codex_binary",
    # Sprint D8.1 — narrow warm-process MCP set.
    "claude.warm_mcp_config": "warm_mcp_config",
    "claude.warm_response_timeout_seconds": "warm_response_timeout_seconds",
    # Codex-3 (#1837) — backend routing policy. Dormant until `backends_enabled`.
    # NOTE: the existing _load_toml flattener only flattens one section level
    # deep, so nested headers like `[backends.chiefs]` would silently drop.
    # Flat keys under `[backends]` are used instead — operators set
    # `chiefs_default = "claude"`, `specialists_overrides = { ... }` etc.
    "backends.enabled": "backends_enabled",
    "backends.main": "backends_main",
    "backends.chiefs_default": "backends_chiefs_default",
    "backends.specialists_default": "backends_specialists_default",
    "backends.specialists_overrides": "backends_specialists_overrides",
    "session.idle_timeout": "session_idle_timeout",
    "session.max_file_size": "session_max_file_size",
    "session.max_errors": "session_max_errors",
    "session.max_messages": "session_max_messages",
    "session.max_duration": "session_max_duration",
    "memory.context_window": "memory_context_window",
    "memory.max_context_tokens": "memory_max_context_tokens",
    "memory.summary_count": "memory_summary_count",
    # Sprint 03.02 — feature flag for 3-layer progressive disclosure API.
    "memory.v2_disclosure_enabled": "memory_v2_disclosure_enabled",
    # Sprint 03.05 — feature flag for PreCompact externalization (#995).
    "memory.precompact_externalization_enabled": "precompact_externalization_enabled",
    # Sprint E1.1 — hard-stop on context pressure overflow (issue #1233).
    "context_pressure.hard_stop_enabled": "context_pressure_hard_stop_enabled",
    # Sprint 03.06 — write-ahead log for memory mutations.
    "memory.wal_enabled": "memory_wal_enabled",
    "memory.wal_path": "memory_wal_path",
    "security.disallowed_tools": "security_disallowed_tools",
    "security.tool_failure_threshold": "tool_failure_threshold",
    "security.tool_failure_window": "tool_failure_window",
    "security.crash_loop_threshold": "crash_loop_threshold",
    "security.crash_loop_window": "crash_loop_window",
    "security.db_size_warn": "db_size_warn",
    "security.db_size_alert": "db_size_alert",
    "security.remote_halt_url": "remote_halt_url",
    "security.remote_halt_check_interval": "remote_halt_check_interval",
    # Issue #1543 — MCP health check interval knob.
    "mcp.health_check_interval_seconds": "mcp_health_check_interval_seconds",
    "voice.enabled": "voice_enabled",
    "voice.stt_url": "voice_stt_url",
    "voice.tts_url": "voice_tts_url",
    "voice.tts_voice": "voice_tts_voice",
    # D1.7a — VAPI voice integration scaffolding.
    "vapi.phone_number_id": "vapi_phone_number_id",
    "vapi.assistant_id_receptionist": "vapi_assistant_id_receptionist",
    "vapi.webhook_url": "vapi_webhook_url",
    # audit-2026-05-16.B.05 (#2054) — Cal.com webhook receiver fail-closed.
    # Secret is loaded from .secrets, never bridge.toml.
    "calcom.webhook_enabled": "calcom_webhook_enabled",
    "rate_limit.initial_backoff": "rate_limit_initial_backoff",
    "rate_limit.max_backoff": "rate_limit_max_backoff",
    "rate_limit.multiplier": "rate_limit_multiplier",
    "rate_limit.jitter": "rate_limit_jitter",
    "checkin.enabled": "checkin_enabled",
    "checkin.active_hours_start": "checkin_active_hours_start",
    "checkin.active_hours_end": "checkin_active_hours_end",
    "checkin.check_interval": "checkin_check_interval",
    "checkin.quiet_after_message": "checkin_quiet_after_message",
    "checkin.minimum_gap": "checkin_minimum_gap",
    "briefing.enabled": "briefing_enabled",
    "briefing.delivery_hour": "briefing_delivery_hour",
    "briefing.delivery_minute": "briefing_delivery_minute",
    "fallback.openrouter_model": "fallback_openrouter_model",
    "openrouter.default_model": "openrouter_default_model",
    "budget.daily_budget": "budget_daily_budget",
    "api.enabled": "api_enabled",
    "api.port": "api_port",
    "api.host": "api_host",
    "api.cors_allowed_origins": "api_cors_allowed_origins",
    # P2.1 follow-up (#1626) — two-knob opt-in for non-local bind.
    "api.allow_remote_bind": "api_allow_remote_bind",
    "few_shot.enabled": "few_shot_enabled",
    "proactive.enabled": "proactive_enabled",
    "proactive.min_sleep_seconds": "proactive_min_sleep_seconds",
    "proactive.max_sleep_seconds": "proactive_max_sleep_seconds",
    # D7.12 #1424 (slice 1) — perpetual-proactive scheduler.
    "proactive.scheduler_enabled": "proactive_scheduler_enabled",
    "proactive.scheduler_dry_run": "proactive_scheduler_dry_run",
    "proactive.scheduler_interval_seconds": "proactive_scheduler_interval_seconds",
    "proactive.scheduler_budget_threshold": "proactive_scheduler_budget_threshold",
    "proactive.scheduler_dispatch_enabled": "proactive_scheduler_dispatch_enabled",
    # Sprint 09.14 — daily_log section maps to two config fields. The
    # bridge.toml default: [daily_log] enabled = true
    "daily_log.enabled": "daily_log_enabled",
    "webhooks.enabled": "webhooks_enabled",
    "webhooks.urls": "webhooks_urls",
    "webhooks.max_queue": "webhooks_max_queue",
    "webhooks.timeout_sec": "webhooks_timeout_sec",
    "webhooks.max_retries": "webhooks_max_retries",
    "remote_kill_switch.halt_url": "remote_halt_url",
    "remote_kill_switch.check_interval": "remote_halt_check_interval",
    "verification.enabled": "verification_enabled",
    # P2.5 follow-up (#1664) — verification policy level
    # ("off" | "warn" | "block"). See BridgeConfig.verification_policy.
    "verification.policy": "verification_policy",
    "verification.mode": "verification_policy",  # alias — spec used "mode"
    # Issue #1565 — operator opt-out for ResponseEvaluator. Default True
    # preserves current behaviour; set to false to skip the per-response
    # evaluator call. See BridgeConfig.response_evaluator_enabled.
    "evaluator.enabled": "response_evaluator_enabled",
    "dispatcher.enabled": "dispatcher_enabled",
    "dispatcher.e2b_executor_enabled": "e2b_executor_enabled",
    # Sprint D-R3 (#1933)
    "dispatcher.executor_timeout_seconds": "executor_timeout_seconds",
    "dispatcher.min_dispatch_confidence": "min_dispatch_confidence",
    # D1.4 quality chain flags
    "quality_chain.enabled": "quality_chain_enabled",
    "quality_chain.branch_protection_enabled": "branch_protection_enabled",
    # D1.5 — branch protection posture ("warn" | "block")
    "quality_chain.branch_protection_posture": "branch_protection_posture",
    "zone3.env_selector_force_alternative": "env_selector_force_alternative",
    "zone3.workorder_db_path": "workorder_db_path",
    # Sprint 07.01 — recursive WorkOrder decomposition contract feature flag.
    "zone3.workorder_decomposition_enabled": "workorder_decomposition_enabled",
    # Sprint D1.6 — complexity threshold for recursive decomposition gate.
    "zone3.workorder_decomposition_complexity_threshold": "workorder_decomposition_complexity_threshold",
    "z4_observability.tool_tracker_enabled": "z4_observability_tool_tracker_enabled",
    "peer.coordination_enabled": "peer_coordination_enabled",
    # Z4-S12 (#1383) — chief-session subsystem flag (REST routes today,
    # full BridgeApp wiring in Z4-S22).
    "chief_dispatcher.enabled": "chief_dispatcher_enabled",
    "chief_dispatcher.default_department": "chief_dispatcher_default_department",
    "chief_dispatcher.idle_timeout_seconds": "chief_dispatcher_idle_timeout_seconds",
    # Z4-S60 (#1404) — retry-with-backoff knobs.
    "chief_dispatcher.retry_max_attempts": "chief_dispatcher_retry_max_attempts",
    "chief_dispatcher.retry_initial_backoff_seconds": "chief_dispatcher_retry_initial_backoff_seconds",
    "chief_dispatcher.retry_max_backoff_seconds": "chief_dispatcher_retry_max_backoff_seconds",
    "chief_dispatcher.retry_backoff_multiplier": "chief_dispatcher_retry_backoff_multiplier",
    # Phase 3 (zone4-warmth.C.01, #2295) — warmth-reuse feature flag.
    # No call site consults this yet; C.02/C.03 wire the behavior.
    "chief_dispatcher.warmth_reuse_enabled": "chief_dispatcher_warmth_reuse_enabled",
    "telemetry.drift_enabled": "drift_telemetry_enabled",
    "telemetry.metrics_path": "bridge_metrics_path",
    "zone4.artifact_root": "zone4_artifact_root",
    "z4_observability.artifact_root": "zone4_artifact_root",
    "logging.json_enabled": "log_json_enabled",
    "heartbeat.healthcheck_bridge_url": "healthcheck_bridge_url",
    "identity.inject_identity": "inject_identity",
    "identity.identity_max_bytes": "identity_max_bytes",
    "tool_rag.enabled": "smart_tool_rag_enabled",
    "memory_tiers.enabled": "memory_tiers_enabled",
    # Sprint Mem-1 (#1842) — per-tier policy overrides for the Memory-Tier
    # Architecture epic. TOML shape: `[memory_tiers.policies.<tier>]` with
    # keys matching TierPolicy fields. Omit `ttl_seconds` for "no expiry"
    # (TOML has no null; `load_tier_policies` treats omission as None).
    "memory_tiers.policies": "memory_tiers_policies",
    # Sprint Mem-6 (#1847) — token budget for tier-aware context-window
    # assembly (consumed by Branch 0 in `KnowledgeMixin.search_knowledge`).
    "memory_tiers.context_window_tokens": "memory_tiers_context_window_tokens",
    # Sprint Mem-8 (#1849) — fail-loud strict-mode filter for NULL-tier
    # rows in hybrid_search.search_tiered. Default false (no-op).
    "memory_tiers.strict_tier_required": "strict_tier_required",
    # Sprint 03.07 — feature flag for the skill version DAG (#997).
    "skill_version_dag.enabled": "skill_version_dag_enabled",
    # Sprint 03.08 — feature flag for the 3-trigger skill evolution loop (#998).
    "skill_evolution.loop_enabled": "skill_evolution_loop_enabled",
    # Sprint 03.09 — feature flag for crystallize-from-trace (#999).
    "skill_evolution.crystallization_enabled": "skill_crystallization_enabled",
    # Sprint 07.04 — feature flag for markdown-skill convention (#1033).
    "skill_evolution.markdown_skills_enabled": "markdown_skills_enabled",
    # Sprint 04.01 — anonymized A/B/C peer-ranking flag.
    "board.v2_enabled": "board_v2_enabled",
    # Sprint 04.03 — cross-vendor (OpenRouter) adapter feature flag (#1003).
    "board.cross_vendor_enabled": "board_cross_vendor_enabled",
    # Sprint #1112/4.06 — specialist retrieval over enumeration (#2153).
    "specialist_retrieval.enabled": "specialist_retrieval_enabled",
    # Sprint 5.00c (#2155) — workflow-first dispatch.
    "workflow_first_dispatch.enabled": "workflow_first_dispatch_enabled",
    # Sprint 5j.04 (#2129) — computer-use authorization.
    "computer_use.enabled": "computer_use_enabled",
    # Sprint 2.07 (#2142) — Zone 1 drift cron flag.
    "zone1_drift.enabled": "zone1_drift_enabled",
    # Sprint 04.04 — per-feature daily cost cap enforcement (#1005).
    "cost.feature_caps_enabled": "feature_cost_caps_enabled",
    # Sprint 14.04 — Dark Factory triage workflow feature flag (#1042).
    "factory.triage_enabled": "factory_triage_enabled",
    # Sprint 14.05 — Dark Factory implement workflow feature flag (#1043).
    "factory.implement_enabled": "factory_implement_enabled",
    # Sprint 14.07 — Dark Factory validate workflow feature flag (#1045).
    "factory.validate_enabled": "factory_validate_enabled",
    # Sprint 14.10 — Dark Factory orchestrator service feature flag (#1048).
    "factory.orchestrator_enabled": "factory_orchestrator_enabled",
    # Sprint 14.09 — Dark Factory fresh-context fix-loop flags (#1047).
    "factory.fix_loop_enabled": "factory_fix_loop_enabled",
    "factory.fix_loop_max_attempts": "factory_fix_loop_max_attempts",
    "factory.fix_loop_cost_cap_per_attempt_usd": (
        "factory_fix_loop_cost_cap_per_attempt_usd"
    ),
    "factory.fix_loop_cost_cap_total_usd": "factory_fix_loop_cost_cap_total_usd",
    # Sprint 14.11 — Dark Factory soak harness flags (#1050).
    "factory.soak_harness_enabled": "factory_soak_harness_enabled",
    "factory.soak_min_verified_count": "factory_soak_min_verified_count",
    "factory.soak_min_correctness_rate": "factory_soak_min_correctness_rate",
    # Sprint 15.03 — Dark Factory mailbox back-channel flags (#1053).
    "factory.mailbox_enabled": "factory_mailbox_enabled",
    "factory.mailbox_poll_interval_seconds": "factory_mailbox_poll_interval_seconds",
    "factory.mailbox_decision_timeout_seconds": "factory_mailbox_decision_timeout_seconds",
    # Sprint 15.04 — channels-as-branches flags (#1054).
    "factory.channels_enabled": "factory_channels_enabled",
    "factory.channels_integration_branch_prefix": (
        "factory_channels_integration_branch_prefix"
    ),
    # Sprint 05.0a — second-brain baseline-ingest feature flag (#1018).
    "second_brain.baseline_enabled": "second_brain_baseline_enabled",
    # Sprint 05.0b — daily vault-backup feature flag (#1019).
    "second_brain.backup_enabled": "second_brain_backup_enabled",
    # Sprint 06.03 — rubric gate flag + threshold (#1024).
    "job_search.rubric_gate_enabled": "job_search_rubric_gate_enabled",
    "job_search.rubric_threshold": "job_search_rubric_threshold",
    # Sprint D5.2 — Zone 4 team delegation gate (#1207).
    "job_search.team_enabled": "job_search_team_enabled",
    # Sprint E1.5 — universal tool-call gate + DialogueDelayMonitor flags
    # (#1237). Section [interrupts] in bridge.toml.
    "interrupts.universal_tool_gate_enabled": "universal_tool_gate_enabled",
    # Operator-friendly alias for the same field — both keys write the same
    # attribute. If both appear in bridge.toml, the loader's last-write-wins
    # behavior applies (TOML disallows duplicate sibling keys, so the alias
    # collision only matters across reloads, not within one file).
    "interrupts.tool_call_gate_enabled": "universal_tool_gate_enabled",
    "interrupts.dialogue_delay_threshold_seconds": "dialogue_delay_threshold_seconds",
    "interrupts.force_pause_threshold_seconds": "force_pause_threshold_seconds",
    "interrupts.poll_interval_seconds": "interrupts_poll_interval_seconds",
    "interrupts.min_pending_to_gate": "min_pending_to_gate",
    # Sprint 05.04 — master second-brain contributor subsystem flag (#1013).
    "second_brain.enabled": "second_brain_enabled",
    # Sprint 05.04 — operator vault root path; empty disables subsystem.
    "second_brain.vault_root": "second_brain_vault_root",
    # Sprint 05.07 — per-contributor granular flags (#1015).
    "second_brain.contributor_dailylog_enabled": "second_brain_contributor_dailylog_enabled",
    "second_brain.contributor_reflection_enabled": "second_brain_contributor_reflection_enabled",
    "second_brain.contributor_consolidation_enabled": "second_brain_contributor_consolidation_enabled",
    # Sprint 05.08 — query strategy + tuning fields (#1016).
    "second_brain.query_strategy": "second_brain_query_strategy",
    "second_brain.query_k": "second_brain_query_k",
    "second_brain.query_fallthrough_threshold": "second_brain_query_fallthrough_threshold",
    # Sprint 05.09 — daily vault lint pass feature flag + schema version (#1017).
    "second_brain.lint_enabled": "second_brain_lint_enabled",
    "second_brain.lint_schema_version": "second_brain_lint_schema_version",
    # Sprint 05.11 — 14-day shadow + auto-routing decision harness (#1021).
    "second_brain.shadow_router_enabled": "second_brain_shadow_router_enabled",
    "second_brain.shadow_router_window_days": (
        "second_brain_shadow_router_window_days"
    ),
    "second_brain.shadow_router_promote_threshold": (
        "second_brain_shadow_router_promote_threshold"
    ),
    # Sprint audit-2026-05-15.B.01 (issue #1996) — experiment runtime mode.
    "experiment_loop.mode": "experiment_mode",
    # Sprint audit-2026-05-16.A.05 (#2049, Section 8.3) — operator throttle
    # for the first production unhalt.
    "experiment_loop.max_iterations_per_hour": (
        "experiment_max_iterations_per_hour"
    ),
    "experiment_loop.cooldown_after_merge_seconds": (
        "experiment_cooldown_after_merge_seconds"
    ),
    # Sprint 02.04 / spec ref-audit-02-05 (issue #979) — MAD confidence
    # scoring window + multiplier for fitness deltas.
    "experiment_loop.mad_window": "experiment_mad_window",
    "experiment_loop.mad_k": "experiment_mad_k",
    # Sprint 02.13 / spec ref-audit-02-13 (issue #988) — heartbeat stale
    # threshold in seconds.
    "experiment_loop.heartbeat_stale_seconds": "experiment_heartbeat_stale_seconds",
    # Sprint 02.14 / spec ref-audit-02-14 (issue #989) — holdout validator
    # subprocess controls.
    "experiment_loop.validator_enabled": "experiment_validator_enabled",
    "experiment_loop.validator_cost_cap_usd": "experiment_validator_cost_cap_usd",
    "experiment_loop.validator_model": "experiment_validator_model",
    # Sprint audit-2026-05-16.E.03 (#2071, Section 8.1) — readiness contract
    # bounding fields. Default 0 = "unset"; _validate enforces > 0 only when
    # experiment_validator_enabled is True.
    "experiment_loop.validator_timeout_seconds": "experiment_validator_timeout_seconds",
    "experiment_loop.validator_min_signals": "experiment_validator_min_signals",
    # Sprint 15.02 / spec ref-audit-15-02 (issue #1052) — mailbox wiring
    # for the experiment-loop worktree boundary.
    "experiment_loop.mailbox_enabled": "experiment_mailbox_enabled",
    "experiment_loop.mailbox_poll_interval_seconds": (
        "experiment_mailbox_poll_interval_seconds"
    ),
    "experiment_loop.mailbox_vacuum_keep_n": "experiment_mailbox_vacuum_keep_n",
    # Sprint 02.04 / spec ref-audit-02-04 (issue #978) — append-only
    # ``autoresearch/iter-NNNN`` audit-branch trail.
    "experiment_loop.audit_branches_enabled": "experiment_audit_branches_enabled",
    "experiment_loop.audit_branches_push_to_origin": (
        "experiment_audit_branches_push_to_origin"
    ),
    # Sprint audit-2026-05-16.E.02 (#2070) — auto-cleanup of local audit
    # branches during trial windows.
    "experiment_loop.audit_branches_local_cleanup": (
        "experiment_audit_branches_local_cleanup"
    ),
    # Sprint 02.08 / spec ref-audit-02-08 (issue #983) — finalize-experiments
    # operator command + tuning knobs.
    "experiment_loop.finalize_enabled": "experiment_finalize_enabled",
    "experiment_loop.finalize_default_window_days": (
        "experiment_finalize_default_window_days"
    ),
    "experiment_loop.finalize_jaccard_threshold": (
        "experiment_finalize_jaccard_threshold"
    ),
    # Sprint ref-audit-02-11 / spec ref-audit-02-11 (issue #986) — push-guard
    # toggle for the experiment loop. Default ON in the dataclass.
    "experiment_loop.push_guard_enabled": "experiment_push_guard_enabled",
}

# Reverse map: field name → BUMBA_ENV_VAR_NAME
_ENV_PREFIX = "BUMBA_"

# Accepted truthy/falsy spellings for BUMBA_* bool overrides. Match is
# case-insensitive after .strip().lower(); anything outside these sets
# raises ConfigError instead of silently defaulting to False (audit
# finding M-2, sprint audit-2026-05-16.B.06). The accepted spellings
# are also documented in docs/operator/configuration.md.
_ENV_BOOL_TRUE = frozenset({"1", "true", "yes", "on"})
_ENV_BOOL_FALSE = frozenset({"0", "false", "no", "off"})


# -- S32: TOML loading and env overrides --

def _load_toml(path: Path) -> dict[str, Any]:
    """Read bridge.toml and flatten section.key → value."""
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        raise ConfigError(f"Config file not found: {path}")
    except OSError as e:
        raise ConfigError(f"Cannot read config file {path}: {e}")

    try:
        data = tomllib.loads(raw.decode())
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"Invalid TOML in {path}: {e}")

    flat: dict[str, Any] = {}
    for section, values in data.items():
        if isinstance(values, dict):
            for key, val in values.items():
                toml_key = f"{section}.{key}"
                if toml_key in _TOML_MAP:
                    field_name = _TOML_MAP[toml_key]
                    if isinstance(val, list):
                        val = tuple(val)
                    flat[field_name] = val
    return flat


def _cast_env_value(field_name: str, raw: str, field_type: type) -> Any:
    """Cast a string environment variable to the expected field type."""
    import types

    args = getattr(field_type, "__args__", ())
    origin = getattr(field_type, "__origin__", None)

    # Handle union types like str | None
    if origin is types.UnionType or origin is type(str | None):
        # Use the first non-None type in the union
        for arg in args:
            if arg is not type(None):
                return _cast_env_value(field_name, raw, arg)

    if field_type is bool:
        normalized = raw.strip().lower()
        if normalized in _ENV_BOOL_TRUE:
            return True
        if normalized in _ENV_BOOL_FALSE:
            return False
        raise ConfigError(
            f"Env override {_ENV_PREFIX}{field_name.upper()} must be one of: "
            f"true/false/1/0/yes/no/on/off (got {raw!r})"
        )
    if field_type is int:
        try:
            return int(raw)
        except ValueError:
            raise ConfigError(f"Env override {_ENV_PREFIX}{field_name.upper()} must be int: {raw!r}")
    if field_type is float:
        try:
            return float(raw)
        except ValueError:
            raise ConfigError(f"Env override {_ENV_PREFIX}{field_name.upper()} must be float: {raw!r}")
    if field_type is str:
        return raw
    return raw


def _apply_env_overrides(config: dict[str, Any]) -> dict[str, Any]:
    """Scan BUMBA_* env vars and merge into config dict."""
    # get_type_hints resolves string annotations to actual types
    field_types = get_type_hints(BridgeConfig)

    for env_key, env_val in os.environ.items():
        if not env_key.startswith(_ENV_PREFIX):
            continue
        field_name = env_key[len(_ENV_PREFIX):].lower()
        if field_name in field_types:
            config[field_name] = _cast_env_value(field_name, env_val, field_types[field_name])
    return config


# -- S33: Keychain secrets and validation --

REQUIRED_BOOT_SECRET_KEYS: tuple[str, ...] = ("claude_oauth_token",)
API_ENABLED_REQUIRED_SECRET_KEYS: tuple[str, ...] = (
    "api_token",
    "github_webhook_secret",
)


def _active_backends_from_config(config: object) -> tuple[str, ...]:
    """Return configured backend names that can receive runtime work."""
    values: list[str] = []
    for attr in (
        "backends_main",
        "backends_chiefs_default",
        "backends_specialists_default",
    ):
        value = str(getattr(config, attr, "") or "")
        if value:
            values.append(value)
    overrides_raw = getattr(config, "backends_specialists_overrides", None)
    if isinstance(overrides_raw, dict):
        values.extend(str(v) for v in overrides_raw.values() if v)
    return tuple(values)


def _requires_claude_oauth(config: object) -> bool:
    """Return whether this config can route work to Claude."""
    if not bool(getattr(config, "backends_enabled", False)):
        return True
    active_backends = set(_active_backends_from_config(config))
    return not active_backends or "claude" in active_backends


def _requires_openrouter_api_key(config: object) -> bool:
    """Return whether this config can route work to OpenRouter."""
    if not bool(getattr(config, "backends_enabled", False)):
        return False
    return "openrouter" in set(_active_backends_from_config(config))


def _load_secrets(
    token_service: str = "bumba-discord-token",
    operator_service: str = "bumba-operator-id",
    keychain_path: str | None = None,
    secrets_file: str | None = None,
) -> dict[str, str]:
    """Retrieve Discord bot token and operator ID.

    Tries macOS Keychain first, then falls back to a secrets file.
    The secrets file is needed when running as a LaunchDaemon
    (no login session = no Keychain access).
    """
    secrets = {}
    keychain_args = [keychain_path] if keychain_path else []

    # Try Keychain first
    for service, secret_field in [
        (token_service, "discord_bot_token"),
        (operator_service, "operator_discord_id"),
    ]:
        try:
            cmd = [
                "/usr/bin/security", "find-generic-password",
                "-s", service, "-w",
            ] + keychain_args
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=10,
            )
            if result.returncode == 0 and result.stdout.strip():
                secrets[secret_field] = result.stdout.strip()
        except (subprocess.TimeoutExpired, OSError):
            pass

    # Fall back to secrets file if Keychain didn't provide both
    if "discord_bot_token" not in secrets or "operator_discord_id" not in secrets:
        file_secrets = _load_secrets_file(secrets_file)
        for key, val in file_secrets.items():
            if key not in secrets:
                secrets[key] = val

    return secrets


def _require_private_file(path: Path, *, purpose: str) -> None:
    """Refuse to load a sensitive file with group/world-readable permissions.

    Sprint audit-2026-05-16.B.01 (#2050 / HI-1) — closes the gap between the
    documented `chmod 600 .secrets` contract and runtime enforcement. The
    error message names the path and the remediation command but never
    surfaces file contents.
    """
    try:
        mode = stat.S_IMODE(path.stat().st_mode)
    except FileNotFoundError:
        # Caller already handles missing-file fallback; don't shadow it here.
        return
    if mode & 0o077:
        raise ConfigError(
            f"{purpose} is group/world-readable (mode={mode:04o}): {path} — "
            f"run `chmod 600 {path}` to remediate. "
            f"Sprint audit-2026-05-16.B.01 (#2050, HI-1)."
        )


def _load_secrets_file(path: str | None = None) -> dict[str, Any]:
    """Read secrets from a key=value file (fallback for LaunchDaemon).

    Sprint audit-2026-05-16.B.02 (#2051, M-1) — thin wrapper around
    :class:`bridge.runtime_secrets.RuntimeSecrets`. The canonical parse,
    permission guard (B.01), and key-by-key whitelist live in the helper
    module. The signature is preserved so external test fixtures and any
    legacy importers keep working. Return type widened from ``dict[str, str]``
    to ``dict[str, Any]`` to cover the int-typed
    ``claude_oauth_expires_at`` / ``codex_oauth_expires_at`` slots — matches
    the previous ad-hoc runtime behaviour, which was already producing ints
    despite the narrower annotation.
    """
    # Local import avoids a circular import at module load time:
    # ``bridge.runtime_secrets`` imports ``ConfigError`` and
    # ``_require_private_file`` from this module.
    from bridge.runtime_secrets import RuntimeSecrets

    secrets_path = Path(path) if path is not None else Path.home() / "data" / ".secrets"
    rs = RuntimeSecrets(secrets_path=secrets_path)

    # Keys this loader is allowed to surface back to ``BridgeConfig``.
    # Mirrors the original key whitelist; preserves the alias mappings
    # (e.g. ``discord_token`` → ``discord_bot_token``) so configs in the
    # field don't have to change shape.
    raw = rs.as_dict()
    secrets: dict[str, Any] = {}

    _STRING_KEYS = (
        "service_channel_id",
        "discord_guild_id",
        "discord_voice_channel_id",
        "claude_oauth_token",
        "claude_oauth_refresh_token",
        "codex_oauth_token",
        "codex_oauth_refresh_token",
        "codex_oauth_id_token",
        "openrouter_api_key",
        "e2b_api_key",
        "api_token",
        "github_webhook_secret",
        "healthcheck_bridge_url",
        "vapi_api_key",
        "vapi_webhook_secret",
        "calcom_webhook_secret",
    )
    _ALIAS_KEYS = {
        "discord_bot_token": ("discord_bot_token", "discord_token"),
        "operator_discord_id": ("operator_discord_id", "operator_id"),
    }

    # ``RuntimeSecrets`` preserves the original key case; the legacy loader
    # lowercased the key before lookup. Build a case-insensitive view so
    # both shapes resolve identically.
    lowered = {k.lower(): v for k, v in raw.items()}

    for canonical, aliases in _ALIAS_KEYS.items():
        for alias in aliases:
            val = lowered.get(alias)
            if val:
                secrets[canonical] = val
                break

    for key in _STRING_KEYS:
        val = lowered.get(key)
        if val is not None and val != "":
            secrets[key] = val

    # Claude OAuth expiry — int-parse, silent skip on bogus value.
    claude_exp = rs.claude_oauth_expires_at()
    if claude_exp is not None:
        secrets["claude_oauth_expires_at"] = claude_exp

    # Codex OAuth expiry — preserves the original quirk: missing key omits
    # the entry entirely; present-but-empty parses as 0 (matches
    # ``BridgeConfig`` default); present-but-bogus is silently skipped.
    if "codex_oauth_expires_at" in lowered:
        codex_raw = lowered["codex_oauth_expires_at"]
        if codex_raw == "":
            secrets["codex_oauth_expires_at"] = 0
        else:
            try:
                secrets["codex_oauth_expires_at"] = int(codex_raw)
            except ValueError:
                pass

    return secrets


def _validate(config: BridgeConfig) -> None:
    """Validate configuration values. Raises ConfigError on failure."""
    # Sprint audit-2026-05-15.B.01 (issue #1996) — fail-closed on unknown mode.
    if config.experiment_mode not in ("proposal_only", "shadow", "production"):
        raise ConfigError(
            "experiment_loop.mode must be one of "
            "('proposal_only', 'shadow', 'production'), "
            f"got {config.experiment_mode!r}"
        )

    # Sprint audit-2026-05-16.A.05 (#2049, Section 8.3) — operator throttle
    # invariants. ``None`` means "no cap"; if set, must be a positive
    # iteration count. Cooldown of 0 means "no cooldown"; negative is
    # nonsense.
    if (
        config.experiment_max_iterations_per_hour is not None
        and config.experiment_max_iterations_per_hour <= 0
    ):
        raise ConfigError(
            "experiment_loop.max_iterations_per_hour must be > 0 when set "
            f"(got {config.experiment_max_iterations_per_hour!r}); use null "
            "or omit the field for no throttle"
        )
    if config.experiment_cooldown_after_merge_seconds < 0:
        raise ConfigError(
            "experiment_loop.cooldown_after_merge_seconds must be >= 0 "
            f"(got {config.experiment_cooldown_after_merge_seconds!r})"
        )

    if not config.discord_bot_token:
        raise ConfigError("Discord bot token is missing (check Keychain or .secrets)")

    if not config.operator_discord_id:
        raise ConfigError("Operator Discord ID is missing (check Keychain or .secrets)")

    if config.heartbeat_interval < 10:
        raise ConfigError(f"heartbeat_interval too low: {config.heartbeat_interval}")
    if config.mcp_health_check_interval_seconds < 10:
        raise ConfigError(
            f"mcp_health_check_interval_seconds too low: {config.mcp_health_check_interval_seconds}"
        )
    if config.discord_first_response_sla_seconds < 0:
        raise ConfigError(
            "discord_first_response_sla_seconds must be >= 0 "
            f"(got {config.discord_first_response_sla_seconds})"
        )
    if config.discord_progress_interval_seconds < 0:
        raise ConfigError(
            "discord_progress_interval_seconds must be >= 0 "
            f"(got {config.discord_progress_interval_seconds})"
        )
    if config.claude_timeout < 10:
        raise ConfigError(f"claude_timeout too low: {config.claude_timeout}")
    if config.warm_response_timeout_seconds < 10:
        raise ConfigError(
            "warm_response_timeout_seconds too low: "
            f"{config.warm_response_timeout_seconds}"
        )
    # Sprint D-R3 (#1933) — dispatcher knobs
    if config.executor_timeout_seconds < 10:
        raise ConfigError(
            "executor_timeout_seconds too low (min 10s): "
            f"{config.executor_timeout_seconds}"
        )
    if not (0.0 <= config.min_dispatch_confidence <= 1.0):
        raise ConfigError(
            "min_dispatch_confidence must be 0.0-1.0: "
            f"{config.min_dispatch_confidence}"
        )
    if config.claude_hard_timeout <= config.claude_timeout:
        raise ConfigError("claude_hard_timeout must exceed claude_timeout")
    if config.claude_absolute_timeout <= config.claude_hard_timeout:
        raise ConfigError("claude_absolute_timeout must exceed claude_hard_timeout")
    if config.claude_max_turns < 1:
        raise ConfigError(f"claude_max_turns too low: {config.claude_max_turns}")
    if config.session_idle_timeout < 60:
        raise ConfigError(f"session_idle_timeout too low: {config.session_idle_timeout}")
    if config.rate_limit_multiplier < 1.0:
        raise ConfigError(f"rate_limit_multiplier must be >= 1.0: {config.rate_limit_multiplier}")
    if not (0.0 <= config.rate_limit_jitter <= 1.0):
        raise ConfigError(f"rate_limit_jitter must be 0.0-1.0: {config.rate_limit_jitter}")

    # Validate paths exist
    for path_field in ("data_dir", "log_dir"):
        p = Path(getattr(config, path_field))
        if not p.is_dir():
            raise ConfigError(f"{path_field} does not exist: {p}")

    if config.claude_binary and not shutil.which(config.claude_binary):
        if not Path(config.claude_binary).is_file():
            raise ConfigError(f"claude_binary not found: {config.claude_binary}")

    # Sprint audit-2026-05-16.B.03 (#2052, HI-5) — fail-closed on missing
    # Claude OAuth token only when this config can route work to Claude.
    # Sibling check to the boot-time validator
    # ``bridge.app._validate_claude_oauth_required``; this one fires earlier
    # (during ``load_config``) and gives operators a single, deterministic
    # error surface regardless of which entry point loads the config.
    # Intentionally placed AFTER the timeout/range invariants so that
    # narrowly-focused unit tests asserting on those specific errors still
    # match the expected exception message.
    if _requires_claude_oauth(config) and not getattr(
        config, REQUIRED_BOOT_SECRET_KEYS[0]
    ):
        raise ConfigError(
            "claude_oauth_token is missing — add claude_oauth_token to "
            ".secrets (audit-2026-05-16.B.03 / HI-5)"
        )

    if _requires_openrouter_api_key(config) and not config.openrouter_api_key:
        raise ConfigError(
            "openrouter_api_key is missing — add openrouter_api_key to "
            ".secrets or remove openrouter from [backends]"
        )

    # Sprint audit-2026-05-16.B.04 (#2053, M-3) — fail-closed on missing
    # API auth secrets when the API server is enabled. The bridge can't
    # authenticate /api/* bearer-token requests without ``api_token`` and
    # can't verify GitHub HMAC signatures without ``github_webhook_secret``.
    # Sibling check to the boot-time validator in
    # ``bridge.api_server.APIServer.start``; this one fires earlier (during
    # ``load_config``) and gives operators a deterministic error surface
    # regardless of which entry point loads the config. Lives in
    # ``_validate`` rather than ``BridgeConfig.validate()`` so dataclass
    # tests using ``replace(BridgeConfig(), ...)`` keep working — the
    # defaults must still produce a satisfiable ``validate()`` per the
    # ``test_default_config_passes_validate`` contract.
    if config.api_enabled and not getattr(config, API_ENABLED_REQUIRED_SECRET_KEYS[0]):
        raise ConfigError(
            "api_enabled=true requires a non-empty api_token in .secrets "
            "(audit-2026-05-16.B.04 / M-3)"
        )
    if config.api_enabled and not getattr(
        config, API_ENABLED_REQUIRED_SECRET_KEYS[1]
    ):
        raise ConfigError(
            "api_enabled=true requires a non-empty github_webhook_secret in "
            ".secrets (audit-2026-05-16.B.04 / M-3)"
        )

    # Sprint audit-2026-05-16.E.03 (#2071, Section 8.1) — validator readiness
    # contract. The validator can flip ``status="discard"`` on a REGRESSION or
    # NOISE verdict, so enabling it without bounded cost / timeout / signal
    # requirements would let it silently kill iterations. Refuse to load a
    # config that turns the validator on without committing to all four
    # bounding fields. Lives in ``_validate`` rather than
    # ``BridgeConfig.validate()`` for the same reason B.03/B.04 do — the
    # ``test_default_config_passes_validate`` contract requires
    # ``BridgeConfig()`` defaults to satisfy ``validate()``, and the default
    # validator-disabled posture (enabled=False, timeout=0, signals=0) would
    # break that contract if the gate lived there.
    if config.experiment_validator_enabled:
        if (
            config.experiment_validator_cost_cap_usd is None
            or config.experiment_validator_cost_cap_usd <= 0
        ):
            raise ConfigError(
                "experiment_validator_enabled=true requires "
                "experiment_validator_cost_cap_usd > 0 "
                "(audit-2026-05-16.E.03 / Section 8.1)"
            )
        if not config.experiment_validator_model:
            raise ConfigError(
                "experiment_validator_enabled=true requires a non-empty "
                "experiment_validator_model (audit-2026-05-16.E.03 / Section 8.1)"
            )
        if config.experiment_validator_timeout_seconds <= 0:
            raise ConfigError(
                "experiment_validator_enabled=true requires "
                "experiment_validator_timeout_seconds > 0 "
                "(audit-2026-05-16.E.03 / Section 8.1)"
            )
        if config.experiment_validator_min_signals <= 0:
            raise ConfigError(
                "experiment_validator_enabled=true requires "
                "experiment_validator_min_signals > 0 "
                "(audit-2026-05-16.E.03 / Section 8.1)"
            )

    # Issue #1541 (Plan W W-5.2) — cross-field invariants. Single-field
    # range checks above; combinatorial checks delegated to the dataclass
    # method so they can be exercised in isolation by test fixtures that
    # bypass _validate() via dataclasses.replace.
    config.validate()


_LEGACY_DEFAULT_CONFIG_PATH = Path("/opt/bumba-harness/agent/config/bridge.toml")


def _resolve_config_path() -> Path:
    """Return the canonical bridge.toml path, layered in priority order.

    Priority chain (first hit wins):

    1. ``BUMBA_BRIDGE_CONFIG`` env var, if set and pointing at an existing
       file. Lets operators or test harnesses override without touching code.
    2. ``<cwd>/config/bridge.toml``, if it exists. The launchd plist sets
       ``WorkingDirectory`` to the runtime tree's ``agent/`` dir, so this
       resolves to ``<runtime_root>/agent/config/bridge.toml`` automatically.
    3. ``<cwd>/agent/config/bridge.toml``, if it exists. For invocations
       from the repo root rather than the ``agent/`` subtree.
    4. Legacy hardcoded ``/opt/bumba-harness/agent/config/bridge.toml``,
       returned as the last resort. Pre-D6-bis (#1488) this was the only
       lookup; kept for backward-compat with the symlink workaround that
       has been operational since 2026-05-09.

    Returns:
        The first path in the chain that exists, or the legacy hardcoded
        path if none exist (so callers see the same ``ConfigError`` with the
        legacy path quoted, preserving the historical error shape).
    """
    env_override = os.environ.get("BUMBA_BRIDGE_CONFIG", "").strip()
    if env_override:
        candidate = Path(env_override).expanduser()
        if candidate.is_file():
            return candidate
        # If env var is set but points at a non-existent file, surface that
        # specifically so a typo doesn't silently fall through to legacy.
        raise ConfigError(
            f"BUMBA_BRIDGE_CONFIG points at a non-existent file: {candidate}"
        )

    cwd = Path.cwd()
    for candidate in (
        cwd / "config" / "bridge.toml",
        cwd / "agent" / "config" / "bridge.toml",
    ):
        if candidate.is_file():
            return candidate

    return _LEGACY_DEFAULT_CONFIG_PATH


def load_config(
    path: str | Path | None = None,
    *,
    skip_secrets: bool = False,
    skip_validation: bool = False,
) -> BridgeConfig:
    """Load, merge, and validate the full bridge configuration.

    Args:
        path: Path to bridge.toml. If ``None`` (the default), resolves via
            :func:`_resolve_config_path` — env var, then cwd-relative, then
            legacy hardcoded path. The launchd plist's ``WorkingDirectory``
            drives the cwd-relative branch for production startups.
        skip_secrets: If True, skip Keychain lookup (for testing).
        skip_validation: If True, skip validation (for testing).
    """
    if path is None:
        path = _resolve_config_path()
    path = Path(path)
    flat = _load_toml(path)

    if not skip_secrets:
        secrets = _load_secrets()
        # Sprint 07.09 — keys for which `.secrets` MUST win over bridge.toml.
        # The dead-man's switch URL is a deployment-topology secret: anyone
        # holding the URL can mark the check up or down, so prefer .secrets
        # whenever both sources provide a value.
        _SECRETS_WINS = frozenset({"healthcheck_bridge_url"})
        for key, val in secrets.items():
            if key in _SECRETS_WINS and val:
                flat[key] = val
            elif key not in flat or not flat[key]:
                flat[key] = val

    flat = _apply_env_overrides(flat)
    config = BridgeConfig(**flat)

    if not skip_validation:
        _validate(config)

    return config


# -- audit-2026-05-16.C.01: HaltPolicy default-construction helper --
#
# Keystone wiring for the shared HaltPolicy contract. Surfaces converge on
# this builder so the global halt source (SecurityManager) is named in
# exactly one place. Call-site migration is deferred to C.02-C.05; see
# bridge/halt.py for the contract.

def build_default_halt_policy(security_manager, *, cancel_in_flight: bool = True):
    """Construct a HaltPolicy bound to the SecurityManager's halt flag.

    The returned policy reads ``security_manager.is_halted()`` and
    ``security_manager.check_halt_flag()`` lazily on every check; no state
    is cached. Pass ``cancel_in_flight=False`` for surfaces that must
    drain in-flight work cleanly rather than abort on halt.
    """
    from bridge.halt import HaltPolicy

    return HaltPolicy(
        is_halted=security_manager.is_halted,
        halt_reason=security_manager.check_halt_flag,
        cancel_in_flight=cancel_in_flight,
    )
