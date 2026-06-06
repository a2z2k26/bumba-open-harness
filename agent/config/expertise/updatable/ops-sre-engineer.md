---
agent: ops-sre-engineer
zone: 4
department: ops
type: updatable
max_lines: 500
schema_version: 1
---

# ops-sre-engineer — Expertise

*This file is updated by ops-sre-engineer after each significant session.*

## Domain Patterns

**Reliability is a design property, not a monitoring concern.** Reliability problems surface in monitoring, but they are caused by design. When evaluating an incident or a proposed change, trace back to the design decision that enabled the failure mode — alerting on symptoms is insufficient.

**Fail-open by default for non-critical gates.** The operator's pattern throughout this codebase is explicit: the remote kill switch (`remote_kill_switch.py`) is fail-open (network errors never trigger a halt). The circuit breaker (`circuit_breaker.py`) has configurable thresholds. When designing reliability mechanisms, default to fail-open for anything that would block the system from operating — fail-closed only for security boundaries.

**Halt mode is the emergency lever.** `/halt` sets `data/halt.flag`; the bridge stops processing but stays connected to Discord. `/resume` clears it. This is the operator's manual reliability escape hatch. SRE work should never recommend destructive actions when halt + investigate is available.

**Dead-man's switch awareness.** The bridge pings an external healthchecks.io endpoint every heartbeat tick. If pings stop, the monitor alerts the operator. The relevant config key is `healthcheck_bridge_url` in `.secrets`. When diagnosing silent crashes, check the healthcheck dashboard first — it's the leading indicator.

**Kernel integrity is the tamper-detection layer.** On startup, SHA-256 hashes of core files are verified against `data/kernel-baseline.json`. Mismatches set halt flag and alert the operator. After any deploy that touches core files, the baseline must be regenerated via `scripts/regenerate_kernel_baseline.py`. A deploy without this step will trigger false integrity alerts on next boot — this happened on the 2026-04-25 Plan 06 deploy.

**LaunchDaemon is the process model on macOS.** The bridge runs as `com.bumba.agent-bridge` via `launchctl bootstrap system`. Each scheduled service is its own LaunchDaemon (`com.bumba.agent-<name>`). Restart procedures:
```
sudo launchctl bootout system/com.bumba.agent-bridge
sudo launchctl bootstrap system /Library/LaunchDaemons/com.bumba.agent-bridge.plist
```
Never `kill -9` the daemon directly — launchd will restart it immediately and the cleanup state is undefined.

**Post-D6-bis (2026-05-09): source clone IS the runtime.** The 24/7 agent's git working tree at `/opt/bumba-harness/agent-flat/` IS the bridge daemon's executing tree. The pre-D6-bis source/runtime split is retired. Specialists modify the runtime tree via PR + merge + `git pull --ff-only origin main` on the runtime, not via direct edits. Operator-only writes (kernel-baseline regen, plist edits) still belong to the operator-with-sudo, not autonomous specialists. Violating this model bypasses the integrity envelope.

**Consecutive failure escalation.** `services/base.py` tracks `consecutive_failures` per scheduled service. Thresholds: 1 failure → CASUAL alert (1h cooldown), 3+ → NUDGE (5min), 5+ → URGENT (5min). Quiet hours 01:00–07:00 Eastern defer CASUAL/NUDGE. URGENT always fires. When diagnosing a flapping service, check `data/service-state/<name>-state.json` for the failure history before touching the service.

**Session recovery over restart.** The operator's preference is `--resume <session_id>` for Claude Code sessions. Sessions expire after 30min idle, >30MB file size, or 3 consecutive errors. Before recommending a full restart, check whether a session resume is possible — it preserves conversation state and is faster.

## Tool Use

**Primary tools:** `check_service_status` (LaunchDaemon health), `tail_log` (logs at `~/logs/bridge-stdout.log`, `~/logs/bridge-stderr.log`), `read_file` (config files, plist files, kernel baseline).

**Log triage order:** stderr first (errors and warnings), then stdout (operational flow). For bridge issues, also check `data/logs/YYYY/MM/YYYY-MM-DD.md` (daily append-only log with category tags: `session`, `service`, `error`, `alert`).

**`check_service_status` before any restart recommendation.** Always verify current service state before proposing a restart. A service that is already stopped needs `bootstrap`, not `bootout + bootstrap`.

**`tail_log` window:** default to the last 50 lines for initial triage; expand to 200 if the failure is not visible in the tail.

**Do not use write tools for runbooks.** Runbooks live in `docs/runbooks/` and are authored by the operator. This specialist proposes runbook content; the operator decides whether to write it to disk.

**When `check_service_status` is unavailable:** fall back to describing the `launchctl list | grep bumba` command and what output to expect.

## Operating Constraints

**Model budget:** `gpt-4o-mini` with 50K-token request limit and 3 concurrent agents per team YAML. For multi-service incident triage, prioritize the service with the highest `consecutive_failures` count first.

**Do not escalate every incident to ops-chief.** Handle independently: log analysis, service restart recommendation, runbook lookup, config review. Escalate to chief when: (1) the incident involves multiple services simultaneously, (2) the fix requires a deploy (operator must approve all deploys), (3) the failure is in a security-critical path (`security.py`, kernel integrity, auth).

**Deployment requires operator approval.** This specialist can diagnose and recommend, but never initiate a deploy. Deploys follow the pattern: source → runtime copy → `chown bumba-agent:staff` → version record → clear `__pycache__` → regen kernel baseline → restart daemon. The operator runs the deploy script; the specialist writes it if needed.

**MAD-based soak stopping applies.** If recommending a soak for a reliability change, default to the Custom infrastructure type (N=12, threshold=1.5×, max=14d) per `docs/architecture/soak-discipline.md`.

**Budget awareness.** The ops team has a `daily_limit_usd: 4.00`. Incident investigations that run long should produce a structured summary at the 3/4 budget mark rather than exhausting the budget on open-ended analysis.

## See Also

- Team config: `agent/config/teams/ops.yaml`
- Deploy script pattern: `agent/CLAUDE.md` — "Deploy Script Pattern"
- Kernel baseline regen: `agent/scripts/regenerate_kernel_baseline.py`
- Soak discipline: `docs/architecture/soak-discipline.md`
- Zone 4 autonomy model: `docs/architecture/zone4-three-tier-autonomy.md`
- Specialist mission tiers: `docs/architecture/specialist-mission-audit.md`
