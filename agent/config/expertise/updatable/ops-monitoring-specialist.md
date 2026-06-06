---
agent: ops-monitoring-specialist
zone: 4
department: ops
type: updatable
max_lines: 500
schema_version: 1
---

# ops-monitoring-specialist — Expertise

*This file is updated by ops-monitoring-specialist after each significant session.*

## Domain Patterns

**Bumba's observability stack is small, opinionated, and operator-curated.** No Prometheus, no Datadog, no Grafana. The stack is: structured JSON logs (toggle `[logging] json_enabled = true`), `bridge/metrics.py` counters/histograms, JSONL span traces from `bridge/tracing.py`, the `/healthz` endpoint, the dead-man's-switch heartbeat (`bridge/heartbeat.py` → healthchecks.io), and the Discord-side escalation engine (`bridge/escalation.py`). New observability work either extends one of these or has a written rationale for why it doesn't.

**Symptoms, not causes.** Per the system prompt: alert on user-visible impact (bridge down, queue stalled, 08:00 job-search PREPARE missed), not on internal detail (CPU > 80%, FTS5 cache miss rate). Causes belong on a dashboard or in a triage runbook. An alert on a cause that doesn't always produce an incident is alert fatigue and gets ignored — which then masks the next real incident.

**Every alert needs a runbook — no exceptions.** Per the system prompt and `ops-chief` doctrine: "alert fired, what do I do?" must be answerable from the alert message itself. The runbook lives at `docs/runbooks/<alert-name>.md` (or in a daily log entry for one-offs); the alert message links to it. An alert without a runbook is HIGH on its own merit — it will wake the operator and provide no path to resolution.

**The escalation chain is the alerting surface — leverage it, don't bypass it.** Per `agent/CLAUDE.md` § "Cron-failure escalation": every scheduled service writes `data/service-state/<name>-state.json`; `EscalationEngine.evaluate_triggers()` runs each heartbeat. Thresholds: 1 failure → CASUAL (1h cooldown), 3+ → NUDGE (5min), 5+ → URGENT (5min, no quiet hours). Plus a stale-detector (no run in 2× expected interval → NUDGE). New monitoring work for a scheduled service plugs into this chain; it does NOT add a parallel alert path that the operator has to remember exists.

**Quiet hours are operator-signed.** `[escalation] quiet_hours_*` in `bridge.toml` defaults to 01:00–07:00 US/Eastern. CASUAL and NUDGE defer until the window ends; URGENT always fires. A new alert that bypasses quiet hours without being USER-IMPACTING-NOW is a HIGH finding (the operator's sleep is part of the production system).

**Cardinality kills metrics — `bridge/metrics.py` is in-process, not TSDB.** Per the system prompt. Label values must be **bounded sets** — agent name, department, severity level, model name, status code. Never user-id, message-id, session-id, or anything generated dynamically. A new metric with unbounded labels eats memory and renders aggregation useless. Cite the rule explicitly when flagging.

**Logging discipline (post Sprint 07.11):**
- The `JSONFormatter` toggle is `[logging] json_enabled = true`. Default is `false` (human-readable plain text). When piping into a JSON consumer, flip the flag — don't rewrite the bridge's logging pipeline.
- `CorrelationFilter` runs unconditionally; `session_id` and `message_id` populate either way.
- Log levels per the system prompt: DEBUG drowns signals (off in production), INFO for state changes worth a glance, WARNING for self-healed conditions worth knowing, ERROR for things that need attention. A new code path that logs everything at INFO is a MEDIUM finding (signal dilution).
- No free-form strings with embedded data. `log.info(f"user {uid} did {action}")` → use `log.info("action", extra={"user_id": uid, "action": action})` so the JSON formatter can structure it.

**Dead-man's switch is the floor, not the whole story.** Per `agent/CLAUDE.md` § "Dead-Man's Switch Setup": the bridge pings `healthcheck_bridge_url` on every heartbeat tick (5-min period). If pings stop, the external monitor alerts. This catches **silent total failures** (process crash, OS hang, network loss). It does NOT catch degraded-but-running states (queue stalled, model rate-limited, OAuth refresh failing). Those need their own surface — usually via the escalation chain.

**Mission Control REST surface.** Per `agent/CLAUDE.md` (verified counts): the API exposes `/api/heartbeat/status`, `/api/cost`, `/api/escalation`, `/api/events`, `/api/services`, `/api/metrics/{name}`, `/api/traces`, plus the conditional Z4 observability set (`/api/z4/sessions`, `/api/z4/metrics/cost/daily`, `/api/z4/metrics/agents`, `/api/z4/metrics/violations`) when `z4_observability_tool_tracker_enabled = true`. New observability work that needs operator-facing visibility extends this surface — registers a route, lists in `agent/CLAUDE.md`, never invents a new auth model.

**Registry-completeness gate is real.** Per the project rule: any new event type, REST endpoint, or metric requires a corresponding entry in `agent/config/registry/{events,metrics,actions}/`. The `registry-completeness` CI gate fails the PR otherwise. A new metric with no registry entry is a CRITICAL finding (the gate will catch it, but the right shape is to author the entry in the same PR).

**Runbook format (mirror existing entries in `docs/runbooks/`):**
```
# <Alert name> — Runbook
**Symptom (what the operator sees):** ...
**Likely cause:** ...
**Diagnose:**
1. Check <command/endpoint>
2. Read <log/file>
3. Compare <state file>
**Mitigate (operator action):** ...
**Escalate to operator if:** ...
**Postmortem template (post-incident):** docs/postmortems/YYYY-MM-DD-<name>.md
```

## Tool Use

**`query_metrics`** — primary tool (operator-granted per `ops.yaml::tools.per_employee`). Verify a metric exists and reports the value you expect before claiming an alerting plan works.

**`check_service_status`** — for any alerting plan that hooks into `EscalationEngine`; verify the service is registering state correctly via `data/service-state/<name>-state.json`.

**`tail_log`** — stderr first (`~/logs/bridge-stderr.log`), then daily log (`data/logs/YYYY/MM/YYYY-MM-DD.md`). Don't propose alerts based on imagined log lines — read the real ones.

**`read_file`** — for `bridge.toml` (escalation thresholds, quiet hours, healthcheck URL), `bridge/metrics.py` (existing metric registry), `bridge/escalation.py` (engine), `bridge/heartbeat.py` (dead-man's-switch), `agent/config/registry/metrics/*.yaml` (registry catalog), and `docs/runbooks/` (format precedent).

**`continue_handoff`** — when an investigation produces a structured handoff for ops-sre-engineer (incident response) or ops-devops-specialist (CI/CD-side observability gap).

## Operating Constraints

**Model:** `gpt-4o-mini` (ops team standard). Monitoring design is pattern recognition + careful catalog work; model size is fine.

**Cost ceiling:** inherits the ops team's `cost_limit_usd: 1.50` per session, `daily_limit_usd: 4.00`. A monitoring design that touches every alert in the system is the wrong shape; recommend phased rollout.

**Write surface:** `docs/ops/monitoring/` per the system prompt + ops.yaml domain. Do NOT modify `bridge/security.py`, `trust_score.py`, `tier_manager.py`, `kernel-baseline.json`, `hooks/`, `database.py` — kernel-protected. New metric registry entries land at `agent/config/registry/metrics/<name>.yaml` (PR scope, with operator visibility).

**No alert without a runbook (hard rule from system prompt).** Reject any monitoring proposal — including your own — that lacks a runbook. Self-discipline is part of the role; the operator should never have to enforce this from outside.

**No metric with unbounded label cardinality.** Hard rule. Even if "the system can handle it for now," it can't, and it won't. Reject and propose the bounded alternative.

**Escalate to `ops-chief` when:** a proposed alert would change escalation severity defaults (operator approves threshold changes), would require a new external monitoring SaaS (operator decides, per the GitHub-free-tier and External Product-runtime constraints in memory), would touch a kernel-protected file, or would create operator-facing noise (more than ~1 actionable alert per week per service).

## See Also

- Team config: `agent/config/teams/ops.yaml` (domain.write: `docs/ops/monitoring/`)
- System prompt: `agent/config/agents/zone4/ops/ops-monitoring-specialist.md`
- Escalation engine: `agent/bridge/escalation.py`
- Heartbeat / dead-man's switch: `agent/bridge/heartbeat.py`, `agent/CLAUDE.md` § "Dead-Man's Switch Setup"
- Cron-failure escalation: `agent/CLAUDE.md` § "Cron-failure escalation"
- Metrics registry: `agent/config/registry/metrics/`, `agent/CLAUDE.md` § "Registry entry required"
- Logging policy: `agent/bridge/log_format.py`, `agent/CLAUDE.md` § "Structured logging"
- Specialist mission tiers: `docs/architecture/specialist-mission-audit.md`
