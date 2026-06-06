# Bumba Agent — Developer Reference

## CANONICAL PATHS — READ BEFORE WRITING ANY FILE

**Load-bearing doctrine:** see [`docs/architecture/canonical-write-territory.md`](../docs/architecture/canonical-write-territory.md) for the full rules, the three forbidden moves, the pre-PR self-checks, and the wrong-tree recovery protocol. Every agent (autonomous or operator-driven) must read that file before its first commit and run the pre-PR checks before every `gh pr create`.

All Python source, tests, configs, and scripts live under `/agent/`. Never write
to these shadow locations at repo root:
- /bridge/         → use /agent/bridge/
- /teams/          → use /agent/teams/
- /tests/          → use /agent/tests/
- /job_search/     → use /agent/job_search/
- /pyproject.toml  → use /agent/pyproject.toml
- /uv.lock         → use /agent/uv.lock

The CI workflow /write-destination-guard.yml will fail any PR that violates
this. Once shadow trees are deleted (Plan 00 Sprint 00.05), these warnings
remain as historical guidance.

**2026-05-05 / 2026-05-09 forensic context:** the runtime tree on the Mac mini went through two corrective migrations. May 5 found two parallel trees (outer wrapper + inner clone); the cleanup attempt failed in 27 minutes and was reverted, leaving the runtime nested at `/opt/bumba-harness/agent/agent/`. May 9 evening completed the corrective fresh-clone-and-swap (D6-bis) to the new single-tree layout at `/opt/bumba-harness/agent-flat/agent/`. 9 files rescued in PR #1331; doctrine reconciled by PR #1485. The canonical-write-territory doctrine is the discipline that prevents recurrence. Read it.

## Identity + Doctrine + Rules

Identity refs, Code Quality, Workflow, and the universal Hard Rules live in the
repo-root [`/CLAUDE.md`](../CLAUDE.md) as the canonical source. Read root first
when starting bridge work. The agent-local additions below extend (not duplicate)
those universal rules with bridge-specific discipline.

### Hard Rules (bridge-additional)

- **Soak before shipping externally-consequential features**: see [`docs/architecture/soak-harness-pattern.md`](../docs/architecture/soak-harness-pattern.md)

---

## Config knobs known dormant

Dormant `BridgeConfig` fields (`smart_tool_rag_enabled`, `memory_tiers_enabled`) moved to [`../docs/operator/bridge-config-reference.md`](../docs/operator/bridge-config-reference.md). Don't try to "fix" them — each is wired to a not-yet-shipped subsystem.

---

## Dialogue gate operator reference

Per-knob operator reference for `interrupts.tool_call_gate_enabled` and `interrupts.min_pending_to_gate` moved to [`../docs/operator/operator-reference.md`](../docs/operator/operator-reference.md). **Doctrine that stays inline:** the gate sits in front of `ClaudeRunner.invoke()`, classifies every pending operator message by severity (HALT > QUESTION > INFO), and decides whether the agent may start another tool-call turn. HALT is always immediate. INFO never blocks. Code: `bridge/tool_call_gate.py::evaluate_gate` + `bridge/operator_inbox.py::classify_severity`.

---

## Wiring discipline

Sprint #1614 (2026-05-11 runtime audit) introduced this discipline after the
runtime self-audit found two related gaps that combined to leave the bridge in
silently-degraded states:

1. `ProactiveScheduler._dispatch` was assigned via direct attribute write in
   `app.py` instead of a setter call, so the wire was invisible to
   `WIRING_MANIFEST`.
2. When `proactive_init` raised, the manifest entry for
   `set_proactive_scheduler` resolved to `None` and was reported as PENDING —
   identical to "deferred by a future plan." The operator had no signal that
   the subsystem had tried and crashed.

### Rules

- **All cross-subsystem wires go through setters.** If subsystem A needs a
  reference to subsystem B, B exposes a `set_<name>(value)` setter and A
  calls it. Direct writes to `B._<name>` are forbidden — they bypass the
  WIRING_MANIFEST and become invisible to the boot wiring report.
- **All optional wires register in WIRING_MANIFEST.** Every setter that may
  be called during `_initialize()` gets a `WiringEntry`, even when the
  source attribute starts out None. The pending-list surfaces the contract
  to the operator at boot time.
- **Subsystems that depend on a wire raise `WiringMissingError` when
  invoked without it.** Silent no-op is the anti-pattern this discipline
  exists to eliminate. See `bridge.wiring.WiringMissingError` and
  `ProactiveScheduler.dispatch` for the canonical example.
- **Init failures escalate PENDING → FAILED in the wiring report.** When a
  construction block raises, set the matching `_<subsystem>_init_failed`
  flag on `BridgeApp` and reference it from the entry's
  `failed_marker_attr`. `apply_wiring_manifest` then routes the entry into
  `report.failed` (logged at WARNING, surfaced separately from the
  deferred-by-plan pile).

When you add a new subsystem that needs to be reached from another subsystem, default to "setter + WIRING_MANIFEST entry" and only deviate with an explicit ADR or follow-up issue. The canonical reference implementation is `ProactiveScheduler` post-#1614 in `bridge/proactive_scheduler.py` + `bridge/app.py`'s init block + manifest entry. One outstanding anti-pattern remains tracked: `self._proactive_scheduler.tick_once = _tick_with_inbox_refresh` in `app.py` ~line 1047 (monkey-patch of a public method) — migration to a formal hook surface deferred.

---

## HaltPolicy contract (audit-2026-05-16.C.01, keystone for C.02–C.05)

Autonomous surfaces (job-search, factory, proactive, warm-chief, experiment-loop, workflow_engine, …) historically each rolled their own pause concept — halt-flag reads, per-service enabled flags, direct CLI behavior, in-flight cancellation state. `bridge/halt.py` introduces ONE shared contract every surface converges on. Surfaces are identified by stable string keys passed to the policy so operator logs grep cleanly.

### Two-method API

```python
@dataclass(frozen=True)
class HaltDecision:
    blocked: bool
    reason: str | None = None

class HaltPolicy:
    def check_start(self, surface: str) -> HaltDecision: ...
    def check_continue(self, surface: str) -> HaltDecision: ...
```

- `check_start(surface)` — "may new autonomous work START on this surface?" Consult before kicking off a tick, a workflow run, a chief deliberation, an experiment iteration, etc.
- `check_continue(surface)` — "should in-flight work on this surface CANCEL?" Consult at safe checkpoints inside long-running work. The policy's `cancel_in_flight` flag (default `True`) decides whether halt blocks this method; pass `cancel_in_flight=False` for surfaces that must drain rather than abort.

`HaltPolicy` is intentionally pure — no I/O, no `SecurityManager` import. The halt source is two callables passed to the constructor (`is_halted: () -> bool`, `halt_reason: () -> str | None`), so tests need no fixtures and the same policy class works against any halt source.

### Default construction

`bridge/config.py::build_default_halt_policy(security_manager, *, cancel_in_flight=True)` wires the canonical halt source (`SecurityManager.is_halted` + `SecurityManager.check_halt_flag`) into a policy. This is the keystone wiring; surfaces should call it rather than hand-rolling their own halt reads.

### Migration status

C.01 (contract + default builder) + C.02–C.05 (call-site migration: warm-chief, experiment-loop, job-search, factory) all shipped. `HaltPolicy` is the canonical halt source for every autonomous surface; new surfaces consume it from the start rather than rolling their own halt-flag reads.

---

## Delegation-floor convention (P3.6 → activated #1645)

Sprint P3.6 (PR #1644) shipped the validator rule `delegation_floor`.
Sprint #1645 (2026-05-12) activated it as a strict-fail per operator
policy call, per the classification doc at
[`docs/architecture/2026-05-12-1645-delegation-floor-classification.md`](../docs/architecture/2026-05-12-1645-delegation-floor-classification.md).

### Rule

Every **delegate-mode team** (one with `workers:` non-empty in its YAML)
MUST declare `constraints.expected_min_specialists ≥ 1`. The chief is
expected to delegate to at least that many specialists per run; Gate 8
in `teams._verify` enforces this at runtime by flipping `success=False`
when `len(employee_results) < expected_min_specialists`.

**Single-director teams** (`workers: []`, e.g. `outreach.yaml`) are
exempt — there is no roster to delegate to.

### Enforcement

Two layers: validator (`agent/scripts/validate_team_yaml.py` — warning by default, ERROR under `--strict`; CI uses `--strict`) and runtime (`agent/teams/_verify.py::verify_team_result` Gate 8 — fires when `expected_min_specialists > 0`). When you add a new team YAML, include `expected_min_specialists` in `constraints:` (typically `1`; use `len(workers)` for peer-ranked deliberation). When you write a chief test, use `make_chief_delegating_model` from `tests/test_teams/conftest.py` rather than the direct-answer helper.

---

## Architecture Overview

Bumba is a Python bridge that connects **Discord** to Claude Code. The operator sends messages via Discord; the bridge processes them, invokes Claude Code as a subprocess with conversation context, and returns the response.

```
Discord → DiscordBot → BridgeApp → ClaudeRunner → Claude Code (`claude -p`)
                            ↕
                 SessionManager / Memory / SecurityManager
                            ↕
                       SQLite (memory.db)
```

All state is persisted in SQLite. The bridge is stateless between restarts — sessions resume via `--resume`.

The memory surface is **three-tier** (PREFERENCE / DECISION / CONTEXT) when `memory_tiers_enabled = true`, with per-tier TTL, dual-write fan-out to SQLite + second_brain + vector, and tier-aware recall. Flag-off (default) preserves the legacy flat memory path. Design rationale: [`docs/architecture/memory-tier-architecture.md`](../docs/architecture/memory-tier-architecture.md). Operator runbook: [`docs/operator/memory-tiers-runbook.md`](../docs/operator/memory-tiers-runbook.md).

## Bridge architecture reference

Module-by-module breakdown of `bridge/`, the Mission Control REST API, Zone 3 / Workflows / Zone 4 / Voice / Cross-Machine / Subpackages module tables, and the Chief Lifecycle (durable ChiefSession + WARM single-run) reference moved to [`docs/architecture/bridge-reference.md`](../docs/architecture/bridge-reference.md) in PR 2 of the 2026-05-18 cleanup. Read that file when you need to look up a module, an endpoint, or the ChiefSession state machine.

**Subagent-preamble doctrine stays inline here** (it's load-bearing for every dispatcher): every subagent task brief should be prefixed by `agent/config/zone1/subagent-preamble.md` (manual prepend, pre-1.0; auto-injection post-1.0). The preamble carries the Behavioral Doctrine excerpt, Operator-Decides Rule, verification convention, and worktree contract — the minimum the subagent needs before reading the task. Dispatchers (main agent or operator) are responsible for prepend discipline until auto-injection lands.

**ADR pointer:** [`docs/architecture/adr/2026-z4-chief-session-lifecycle.md`](../docs/architecture/adr/2026-z4-chief-session-lifecycle.md) for chief-session lifecycle decisions.


## Operator Commands (three-tier surface — 88 total)

Full command catalog (Tier-1 essential / Tier-2 Z4 operational / Tier-3 power-user) moved to [`../docs/operator/operator-reference.md`](../docs/operator/operator-reference.md). The canonical source remains `agent/bridge/commands.py` (`_TIER_1_ESSENTIAL` / `_TIER_2_Z4` / `_TIER_3_POWER_USER`). Tier-3 is dynamically registered and changes frequently.

## Scheduled Services (`bridge/services/`)

Services run as independent **LaunchDaemons** via `python -m bridge.services.runner <name>`.

| Service | Plist | Schedule |
|---------|-------|----------|
| `briefing` | `com.bumba.agent-briefing` | Daily at 07:30 |
| `checkin` | `com.bumba.agent-checkin` | Multiple daily check-ins |
| `email` | `com.bumba.agent-email` | Every 2 hours |
| `calendar` | `com.bumba.agent-calendar` | Daily at 07:00 (morning digest only — 30-min meeting alerts retired 2026-05-12) |
| `knowledge_review` | `com.bumba.agent-knowledge-review` | Daily at 23:00 |
| `retro` | `com.bumba.agent-retro` | Daily at 18:00 |
| `weekly_review` | `com.bumba.agent-weekly-review` | Sunday at 18:00 |
| `job_search` | `com.bumba.agent-job-search` | Daily at 08:00 (PREPARE) |
| `job_search_execute` | `com.bumba.agent-job-execute` | Every 2hrs 10:00-20:00 (EXECUTE) |
| `funnel_post` | `com.bumba.agent-funnel-post` | Daily at 22:00 |
| `inbox_nurture` | `com.bumba.agent-inbox-nurture` | Daily at 09:15 |
| `subscription_tracker` | `com.bumba.agent-subscription-tracker` | Daily at 11:00 |
| `project_pulse` | `com.bumba.agent-project-pulse` | Daily at 23:30 |
| `meeting_prebrief` | `com.bumba.agent-meeting-prebrief` | Every 10 minutes (event-driven via EventBus + poll-scan) |
| `weekly_ceo_review` | `com.bumba.agent-weekly-ceo-review` | Monday at 08:00 UTC |
| `factory_orchestrator` | `com.bumba.agent-factory-orchestrator` | Every 4 hours — Dark Factory production loop (gate-flagged `factory_orchestrator_enabled`) |
| `factory_soak` | `com.bumba.agent-factory-soak` | Every 4 hours — Dark Factory shadow/soak harness (gate-flagged `factory_soak_harness_enabled`) |
| `consolidation` (micro) | `com.bumba.agent-consolidation-micro` | Every 6 hours — decay pass only |
| `consolidation` (standard) | `com.bumba.agent-consolidation-standard` | Daily at 02:00 — full 6-phase pipeline |
| `consolidation` (deep) | `com.bumba.agent-consolidation-deep` | Sunday at 02:00 — DreamAgent deep pass |
| `worktree_gc` | _(no plist)_ | Internal cleanup — prunes stale `/private/tmp/` git worktrees (mtime > 24h) |

> **Service count verified against `agent/bridge/services/` at HEAD `79a43121` on 2026-05-17 (issue #2124).** Re-verify via:
> `find agent/bridge/services -maxdepth 1 -name "*.py" -not -name "_*" -not -name "runner.py" | wc -l`
>
> **Plist location note:** the per-service LaunchDaemon plists live in two directories — `agent/scripts/*.plist` (most services) and `agent/config/launchdaemons/*.plist` (consolidation 3×, factory orchestrator/soak, weekly-CEO-review, experiment). All plists named in the table above resolve to one of these two dirs; sweep both when inventorying.

Entry point: `bridge/services/runner.py` — loads the named service class and runs it.

### Cron-failure escalation (Sprint D2.4)

Every scheduled service writes `data/service-state/<name>-state.json` on each
run via `services/base.py::record_success | record_failure | record_skipped`.
The `consecutive_failures` counter increments on `record_failure` and resets on
`record_success` and `record_skipped`.

`background_loops.heartbeat_loop` calls `EscalationEngine.evaluate_triggers()`
each tick. Triggers fire by level:

| Threshold | Level | Cooldown | Message |
|-----------|-------|----------|---------|
| `consecutive_failures == 1` | CASUAL | 1h | `{service} failed once: {last_error}` |
| `consecutive_failures >= 3` | NUDGE | 5 min | `{service} has N consecutive failures: {last_error}` |
| `consecutive_failures >= 5` | URGENT | 5 min | `{service} has N consecutive failures: {last_error}` |
| stale (no run in 2× expected interval) | NUDGE | per-service | `{service} hasn't run in Nh` |

Quiet hours (`[escalation] quiet_hours_*` in `bridge.toml`, default 01:00–07:00
US/Eastern) defer CASUAL and NUDGE alerts until the window ends; URGENT always
fires immediately. On recovery (`consecutive_failures` returns to 0 from >= 3),
one de-escalation message fires.

Operator commands:
- `/escalation` — current active alerts and deferred queue
- `/services` — full state-file dump for all services
- `/halt` / `/resume` — set/clear the `data/halt.flag` file

**Halt scope today (verified at HEAD `79a43121` on 2026-05-17, issue #2124):** `data/halt.flag` is consulted by the
scheduled-service runner (`bridge/services/runner.py`), the scheduled-service
context builder (`bridge/services/context_builder.py`), the warm-chief
execution path (`bridge/warm_chief.py` via injected `HaltPolicy`,
audit-2026-05-16.C.02 #2101), the experiment loop (`scripts/experiment_loop.py`
via `_check_halt` + `HaltPolicy` adapter, C.03 #2105), the job-search loop
(C.04 #2099), and the factory + proactive loops (C.05 #2100). Phase C of the
2026-05-16 audit remediation closed the original gap: keystone #2056
(HaltPolicy + scope contract) plus C.02–C.05 are all shipped. `/halt` now
propagates across the scheduled-service chain AND the autonomous surfaces;
the only remaining historical exemption is any code path that has not been
audited against the `HaltPolicy` contract.

The chain is always-on; there is no enable flag. Wiring trace:
`ServiceBase.record_success` / `record_failure` / `record_skipped` in
`bridge/services/base.py` →
`EscalationEngine.evaluate_triggers()` in `bridge/escalation.py` →
`heartbeat_loop()` in `bridge/background_loops.py`.

**Composition primitives** (not scheduled, used by services):
- `dispatch_adapter.py` — `ServiceDispatchAdapter` (Z2-S3.1) wraps `DepartmentRegistry.route()` so scheduled services can optionally route their work through a Zone 4 department; never raises (returns `SynthesisResult` with `success=False` on error).

### Scheduled-service state-file schema (#1806)

Each service writes its state to `data/service_state/<name>-state.json` via
`ServiceBase.record_success` / `record_failure` / `record_skipped`. The
canonical fields below are the contract — `bridge/health.py::_check_services`
and `scripts/audit/s5-1-service-state-probe.sh` both consume them by name.
Defaults are merged from `REQUIRED_STATE_FIELDS` on every `load_state()`.

| Field | Type | Written by | Semantics |
|---|---|---|---|
| `last_run` | ISO-8601 str \| null | `record_success` | Timestamp of most recent successful run. Not updated on failure or skip — use `last_error_time` / `last_skipped_at` for those. |
| `last_status` | `"success"` \| `"failure"` \| `"skipped"` \| null | all three `record_*` | Terminal class of the most recent run. Lets the operator answer "what happened last" without comparing three timestamps. |
| `last_error` | str \| null | `record_failure` (set), `record_success` (cleared) | Error message from the most recent failure. Cleared on next success. |
| `last_error_time` | ISO-8601 str \| null | `record_failure` | Timestamp of most recent failure. |
| `consecutive_failures` | int (≥0) | `record_failure` (++), `record_success` / `record_skipped` (reset to 0) | Drives `EscalationEngine` thresholds (CASUAL ==1, NUDGE ≥3, URGENT ≥5). A skip MUST reset this — a service that correctly no-ops is not failing. |
| `total_runs` | int | `record_success` (++ only) | Lifetime success counter. Skips do NOT advance this. |
| `total_failures` | int | `record_failure` (++ only) | Lifetime failure counter. |
| `total_skipped` | int | `record_skipped` (++ only) | Lifetime no-op counter (Sprint 3.1). |
| `last_skipped_at` | ISO-8601 str \| null | `record_skipped` | Timestamp of most recent skip. |
| `last_skipped_reason` | str (≤200) \| null | `record_skipped` | Rendered skip reason; truncated at 200 chars. For typed skips this is `<class>:<param>` or `<class> (<detail>)` (see `SkipReason.render`). |
| `last_skipped_class` | str \| null | `record_skipped` (typed path only) | `SkipClass` value (`missing_secret`, `missing_config`, `not_due`, `dependency_unavailable`, `operator_disabled`, `nothing_to_do`). `None` for plain-string back-compat path. |
| `last_duration_ms` | int | `record_success` | Wall-clock duration of most recent successful run. |
| `total_cost_usd` | float (≥0) | `record_success` (+= per-run cost) | Cumulative USD spend across successful runs (Board Phase 1, #2390). Per-run cost arrives via `record_success(..., cost_usd=ServiceResult.cost_usd)` from `runner.py`; negative inputs are clamped to 0.0. Skips and failures do NOT accrue. Surfaced by `/services` (table line `cumulative=$X` + detail `Cumulative cost:` block). |

Add a field by extending `REQUIRED_STATE_FIELDS` and writing it from the
matching `record_*` method. Don't add fields that duplicate existing
semantics — `health.py` and the probe script already glob this dir, so
schema drift across consumers is silent until an audit catches it.

## Job Search Pipeline (`job_search/`)

Two-cron pipeline: PREPARE (08:00 daily — scrape → dedup → ATS-detect → cover-letter → stage in Notion) and EXECUTE (every 2h, 10:00-20:00 — operator-approved Notion rows → submit). See ADRs `2026-05-17-job-search-browser-substrate.md`, `2026-05-18-job-search-credential-vault.md`, `2026-05-18-job-search-sandbox-model.md` for design rationale. Operator runbook: `docs/operator/computer-use-sandbox-setup.md`.

## Deployment

The bridge runs as a LaunchDaemon:
```bash
sudo launchctl bootstrap system /Library/LaunchDaemons/com.bumba.agent-bridge.plist
sudo launchctl bootout system/com.bumba.agent-bridge
```

Logs: `~/logs/bridge-stdout.log`, `~/logs/bridge-stderr.log`

Maintenance (daily at 03:00 via launchd): backup, expired knowledge cleanup, VACUUM, log rotation.

## Two-User Model

**Post-D6-bis (2026-05-09):** the source clone on the Mac mini IS the runtime. There is no separate "deploy" step — the 24/7 agent's `git pull --ff-only origin main` against its working tree IS the deployment.

| | Workstation (operator) | Mac mini (24/7 agent + runtime) |
|---|---|---|
| **Path** | `/home/operator/bumba-open-harness/` | `/opt/bumba-harness/agent-flat/` (post-D6-bis canonical) |
| **User** | `operator` | `bumba-agent` (restricted) |
| **Purpose** | Operator-side code authoring + PR review | Combined: 24/7 agent's git working tree AND bridge daemon's executing tree |

The bridge daemon's launchd plist sets `WorkingDirectory = /opt/bumba-harness/agent-flat/agent` so `python -m bridge` resolves the package from the runtime tree.

### Behavioral Rules

1. **Authoring is via PR**, regardless of host. Workstation authors a feature branch + PR; 24/7 agent authors a feature branch + PR. Direct commits to `main` on the runtime tree are forbidden — the runtime's `main` advances only via `git pull --ff-only origin main` from this side.
2. **Bridge restart picks up changes.** After a `git pull` lands new code on the runtime tree, the bridge daemon needs to be bounced (`launchctl bootout` + `bootstrap`) to load the new modules. Python's import cache holds onto whatever was loaded at process start.
3. **Kernel baseline must match the on-disk files.** After any `git pull` that changes hashed files (bridge code, identity docs, config), regenerate the baseline before restarting: `sudo -u bumba-agent .venv/bin/python /opt/bumba-harness/agent-flat/scripts/regenerate_kernel_baseline.py --target-root /opt/bumba-harness/agent-flat/agent`. Skip this and the daemon halts at startup.

### Deployment shape (post-D6-bis)

A "deploy" is now four commands run from the Mac mini, all under `bumba-agent`:

```bash
# 1. Pull main into the runtime tree.
sudo -u bumba-agent git -C /opt/bumba-harness/agent-flat pull --ff-only origin main

# 1b. Rebuild MCP server deps when mcp-servers/ changed since the last deploy
#     (#2582). The bumba-sandbox MCP fails with "Cannot find module
#     @modelcontextprotocol/sdk" if node_modules is stale/corrupt. Use the
#     bumba-agent-owned npm cache — the default /home/bumba/.npm is owned by
#     admin `bumba` and will EACCES under sudo -u bumba-agent.
for srv in bumba-sandbox bumba-memory; do
  d="/opt/bumba-harness/agent-flat/mcp-servers/$srv"
  [ -f "$d/package.json" ] || continue
  sudo -u bumba-agent env HOME=/opt/bumba-harness npm --prefix "$d" \
      --cache /opt/bumba-harness/.npm-cache ci 2>/dev/null \
    || sudo -u bumba-agent env HOME=/opt/bumba-harness npm --prefix "$d" \
       --cache /opt/bumba-harness/.npm-cache install
  sudo -u bumba-agent env HOME=/opt/bumba-harness npm --prefix "$d" \
      --cache /opt/bumba-harness/.npm-cache run build 2>/dev/null || true
done

# 1c. Reconcile the runtime .mcp.json against the canonical mirror (#2582).
#     .mcp.json is gitignored (runtime-only, chmod 600) so `git pull` never
#     touches it — a hand-edit on the runtime can silently drift from
#     config/mcp-servers.canonical.json (e.g. a pre-D6-bis bumba-sandbox path).
#     The canonical file is the source of truth; diff before trusting the live
#     copy, and re-sync the changed server entries by hand if they diverge:
diff <(python3 -c 'import json,sys;print(json.dumps(json.load(open("/opt/bumba-harness/agent-flat/agent/.mcp.json")).get("mcpServers",{}),sort_keys=True,indent=2))') \
     <(python3 -c 'import json,sys;print(json.dumps(json.load(open("/opt/bumba-harness/agent-flat/agent/config/mcp-servers.canonical.json")).get("mcpServers",{}),sort_keys=True,indent=2))') \
  || echo "WARN: runtime .mcp.json drifted from canonical — reconcile before bouncing"

# 2. Regenerate the kernel baseline to match the new files.
sudo -u bumba-agent env HOME=/opt/bumba-harness \
    /opt/bumba-harness/agent-flat/agent/.venv/bin/python \
    /opt/bumba-harness/agent-flat/scripts/regenerate_kernel_baseline.py \
    --target-root /opt/bumba-harness/agent-flat/agent

# 3. Bounce the bridge daemon.
sudo launchctl bootout system/com.bumba.agent-bridge
sudo launchctl bootstrap system /Library/LaunchDaemons/com.bumba.agent-bridge.plist

# 4. Smoke.
curl -sf -H "Authorization: Bearer $(grep '^api_token=' /opt/bumba-harness/data/.secrets | cut -d= -f2)" http://localhost:8200/healthz | python3 -m json.tool
```

The legacy `scripts/deploy_*.sh` pattern (copy source→runtime, regen baseline, restart) is **superseded** by the 4-step pull-regen-restart-smoke sequence. Old deploy scripts in `scripts/` will be moved to `scripts/archived/` post-D6-bis.

### Identity-doc convention (post-D6-bis: superseded #851)

Identity docs (`SOUL.md`, `OPERATOR.md`, `TOOLS.md`, `RULES.md`, `AGENTS.md`, `CLAUDE.md`) live at a single canonical path: `/opt/bumba-harness/agent-flat/agent/<doc>.md` — git-tracked under the repo's `agent/` subtree, arriving on the runtime via the same `git pull` that updates bridge code. The pre-D6-bis dual-location workaround (#851) is obsolete; `scripts/deploy_helpers.sh::copy_identity_docs_flat` is a no-op slated for removal post-soak.

## Configuration + Secrets

Per-section `bridge.toml` reference (logging, API bind, verification policy, evaluator opt-out, `[backends]` routing) and `.secrets` file inventory moved to [`../docs/operator/bridge-config-reference.md`](../docs/operator/bridge-config-reference.md). Config file path: `/opt/bumba-harness/agent-flat/agent/config/bridge.toml`. Secrets file: `/opt/bumba-harness/data/.secrets` (mode 0600). LaunchDaemons have NO Keychain access. Claude OAuth tokens auto-refresh via `token_refresher.py` (~8h rotation). For env-var override casting (`BUMBA_*`), see [`../docs/operator/configuration.md`](../docs/operator/configuration.md).

## MCP Servers

Config: `/opt/bumba-harness/agent-flat/agent/.mcp.json` (chmod 600, owned by bumba-agent; post-D6-bis canonical).
13 entries / 12 effective MCP servers available to Claude subprocess (verified via operator probe 2026-05-12, issue #1735). The 13th entry `_cloudflare_disabled` is an intentional parked stub (underscore-keyed) — disabled 2026-05-09 after a 4-day crash loop, kept as a re-enable hint pending stable upstream `mcp-remote`/cloudflare binding. Credentials resolved from `.secrets` via `${VAR}` references.
Canonical: `config/mcp-servers.canonical.json` — mirrors the live runtime exactly (post P5.4 reconciliation, #1735). This is the **source of truth** for the runtime `.mcp.json`. Because `.mcp.json` is gitignored, a hand-edit on the runtime never round-trips back to source and can silently drift; deploy step 1c diffs the two and the canonical file wins. Server invocation paths use the post-D6-bis sibling layout `/opt/bumba-harness/agent-flat/mcp-servers/<server>/` — **no** extra `agent/` segment (`mcp-servers/` is a sibling of `agent/`, not a child). The 2026-06-02 E2B outage (#2582) was a runtime `.mcp.json` carrying the pre-D6-bis `…/agent/mcp/bumba-sandbox/` path; the canonical file already had the correct sibling path.
Template: `config/mcp-servers.template.json` — historical reference copy used as a test fixture (`test_warm_mcp_config.py` asserts the warm narrow-set is a strict subset); diverges from runtime by design. See `TOOLS.md` for full inventory. Note (#2582): reconciled `bumba-sandbox` and `bumba-memory` to the canonical sibling layout (`/agent-flat/mcp-servers/<server>/`, no extra `agent/`) — both confirmed against `mcp-servers.canonical.json`. The `bumba-figma` and `figma-console` entries STILL carry the legacy `agent-flat/agent/mcp-servers/` path: neither server is listed in canonical, so the correct runtime path could not be confirmed and they were left rather than guessed. Confirm those two against the live runtime `.mcp.json` (or add them to canonical) before reconciling the template's last two stale paths.

> **Canonical tool surface (E4.4):** [`docs/architecture/main-agent-tool-surface.md`](../docs/architecture/main-agent-tool-surface.md) — full inventory of built-in tools, MCP servers with rationales, bash deny-list, and filesystem scope.

## Testing

```bash
python3 -m pytest tests/ -q           # Bridge tests
python3 -m pytest job_search/tests/ -q # Job search tests
```

Tests use in-memory SQLite. All external services (Discord, Claude subprocess, APIs) are mocked.

- **memory-tier E2E:** `make memory-tier-e2e` — Mem-11 (#1852) acceptance harness for the memory-tier-architecture epic. Runs integration tests + Mem-6 A/B harness + feature-flag drift check; exit 0 is the operator's green light to flip `memory_tiers_enabled = true`.

### Coverage gate — 80% on bridge core (1.0-Q3, #1111)

The `coverage` target in `agent/Makefile` and the `coverage.yml` CI workflow
both enforce `--cov-fail-under=80` on the combined `bridge/ + teams/ +
job_search/` packages — the bridge-core surface called out by the 1.0
acceptance criterion. The two flags MUST stay in sync; if you ratchet one,
ratchet the other.

Reproduce locally:

```bash
cd agent && make coverage
```

Pass: combined coverage ≥ 80%, exit 0, HTML report at `agent/htmlcov/index.html`.
Fail: pytest exits non-zero with `Required test coverage of 80% not reached`.

Measurement context (2026-05-09 baseline, captured in PR opening 1.0-Q3):
combined coverage was at exactly 80% (`bridge/` 80%, `teams/` 82%); the gate
guards regression rather than forcing immediate ratchet. As bridge-core test
coverage improves, ratchet both files together.

## Live-smoke testing (Zone 4)

Opt-in tests that hit the real Anthropic API. Run before flag flips, before
major Z4 merges, or after any change to department YAMLs:

```bash
export ANTHROPIC_API_KEY=<anthropic-api-key>
make live-smoke           # ~5-6 tests, ~$0.50-1.00 total
make test-offline         # full suite excluding live tests
```

Configuration:
- `LIVE_COST_CAP=0.75` to raise per-test cost cap (default $0.50)
- Tests defined in `tests/test_teams/test_live_smoke.py`
- `@pytest.mark.live` gating ensures these NEVER run in CI
- Live fixtures in `tests/test_teams/conftest_live.py`
- See Sprint B2.4 for harness details

## Key Behaviors

**Session continuity**: Claude is invoked with `--resume <session_id>`. Sessions expire after 30 min idle, file size >30MB, or 3 consecutive errors.

**Kernel integrity**: On startup, SHA-256 hashes of core files are verified against `data/kernel-baseline.json`. Mismatches alert the operator and set halt flag.

**Halt mode**: `/halt` sets `data/halt.flag`. Bridge stops processing but stays connected to Discord. `/resume` clears the flag.

**Voice**: VAPI integration is wired and default-off (D1.7a-D1.7c). Set `voice_enabled = true` in `[voice]` and add **both** `vapi_api_key` and `vapi_webhook_secret` to `.secrets` to activate. The `vapi_api_key` authenticates outbound bridge-to-VAPI API calls; the `vapi_webhook_secret` (P2.3 #1578, audit C8) is the shared secret VAPI sends in the `X-VAPI-SECRET` header on every callback to `/api/v1/voice/webhook`; the handler verifies it via `secrets.compare_digest`. The bridge **refuses to boot** if `voice_enabled = true` and `vapi_webhook_secret` is empty (fail-closed validator in `APIServer.start()`, mirrors #1626's `allow_remote_bind` pattern). Operator commands: `/voice` (status/call), `/tts` (text synthesis). Squad architecture: 4 assistants (receptionist + engineering + qa + ops) provisioned to VAPI at startup. The Discord voice-receive pipeline (`audio_pipeline.py`, `voice_metrics.py`, `stt_engine.py`) was removed in PR #1773 (P2.2). Operator activation checklist: [`../docs/operator/vapi-voice-activation-runbook.md`](../docs/operator/vapi-voice-activation-runbook.md).

**Smart model routing**: Short/conversational messages route to Haiku (~5-10s), code/analysis to Sonnet, complex architecture to Opus. Department-aware: engineering messages stay Sonnet even if short. Override with `@haiku:`, `@sonnet:`, `@opus:` prefix.

## Daily Logs

Append-only markdown log at `data/logs/YYYY/MM/YYYY-MM-DD.md`. Entries are timestamped bullets with category tags: `session`, `service`, `error`, `alert`, `memory`, `event`, `decision`, `message`, `response`, `dream`, `search`, `proactive`.

View with `/log` (defaults to last 20 lines) or `/log 50` for more.

## Proactive Mode

When enabled (`[proactive] enabled = true` in `bridge.toml`), the bridge fires periodic ticks when idle. On each permitted tick, the loop builds an orientation brief — combining the current `TickContext` (local time, pending tasks, recent events) with the operator-curated `agent/state/orientation.json` — and posts it to the operator's Discord channel. the operator sees a message ("here's what I'd do next, want me to proceed?") and replies to approve, redirect, or ignore.

**The tick loop never invokes `claude_runner` directly** — autonomous execution remains an explicit operator-initiated act, per operator decision E-O8.

Tick rate is capped at `max_ticks_per_hour = 12` to control cost. Enable/disable at runtime with `/proactive on` / `/proactive off`.

## Deep Consolidation

When enabled (`[consolidation] enabled = true`), the DreamAgent runs a deep consolidation pass on daily logs, summarizing and indexing knowledge. Uses `consolidation_lock.py` to prevent concurrent runs. Lock is PID-based; stale locks (>60 min) are auto-cleared.

## Remote Kill Switch

`[remote_halt] url` (default unset) makes `background_loops.heartbeat_loop` poll the endpoint each tick via `security.check_remote_halt()`. `{"halt": true}` response sets halt mode; network errors are fail-open. Plan 06.09 retired the separate `RemoteKillSwitch` class; `[remote_kill_switch]` survives as a TOML alias for `[remote_halt]`.

## Operator runbooks

Dead-Man's Switch setup (healthchecks.io heartbeat ping), Experiment Loop (`scripts/experiment_loop.py` autonomous self-improvement), and Local Development Setup (`uv sync --dev` + `pre-commit install`) all moved to [`../docs/operator/operator-reference.md`](../docs/operator/operator-reference.md).

## Hook System

Three lifecycle hooks in `~/.claude/hooks/` (source: `config/hooks/`) fire from
the **Claude Code CLI subprocess**, not from the bridge daemon:

| Hook | Event | Purpose |
|------|-------|---------|
| `memory-session-start.sh` | `SessionStart` | Inject memory context, verify kernel integrity |
| `memory-session-stop.sh` | `Stop` | Prompt knowledge persistence before session ends |
| `memory-subagent-stop.sh` | `SubagentStop` | Save subagent findings before subprocess exits |

Hooks are kernel-protected. Only the `bumba` (admin) user can modify them.

The bridge daemon does **not** have its own file-based hook dispatcher.
Sprint 01.08b removed the `HookDispatcher` class after a 2026-04-25 audit
of the runtime hooks dir found zero scripts targeting bridge lifecycle
events; activating one would have caught files owned by Claude Code CLI
and Bumba Design Bridge sharing the same directory. Audit at
`docs/audits/2026-04-24-activation-plans/plan-01-hooks-audit.md`. If
file-based bridge hooks become desirable later, they should live in a
dedicated dir (e.g. `~/.claude/bumba-bridge-hooks/<event>/`) — never the
shared `~/.claude/hooks/`.

`SessionHookRegistry` (in-process, unrelated to file-based hooks) is
preserved at `bridge/hooks.py` and tracks operator-activated session
modifiers like `/careful` and `/freeze`.

---
*Behavioral Doctrine + Effectiveness Indicators live in root [`/CLAUDE.md`](../CLAUDE.md) (canonical).*
*For the 2026-04-23 master audit and the activation plans that followed, see `docs/audits/2026-04-23-master-audit/` and `docs/plans/2026-04-24-activation-plans/`.*
