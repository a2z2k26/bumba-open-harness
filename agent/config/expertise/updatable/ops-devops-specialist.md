---
agent: ops-devops-specialist
zone: 4
department: ops
type: updatable
max_lines: 500
schema_version: 1
---

# ops-devops-specialist — Expertise

*This file is updated by ops-devops-specialist after each significant session.*

## Domain Patterns

**Bumba is not a SaaS — there is no blue/green, no canary, no Kubernetes.** The runtime is a single LaunchDaemon (`com.bumba.agent-bridge`) on a Mac mini under the `bumba-agent` user. Pretending otherwise produces designs the operator will reject as overengineering. New CI/CD work has to fit this shape: a `git pull --ff-only origin main` against the Mac mini's working tree IS the deployment.

**Post-D6-bis: source clone IS the runtime.** Per `agent/CLAUDE.md` and `ops-chief`. The 24/7 agent's working tree at `/opt/bumba-harness/agent-flat/` is also the bridge's executing tree. The 4-step deploy sequence is operator-signed and the only sanctioned production path:

```bash
# 1. Pull main into runtime
sudo -u bumba-agent git -C /opt/bumba-harness/agent-flat pull --ff-only origin main
# 2. Regenerate kernel baseline
sudo -u bumba-agent env HOME=/opt/bumba-harness /opt/bumba-harness/agent-flat/agent/.venv/bin/python /opt/bumba-harness/agent-flat/scripts/regenerate_kernel_baseline.py --target-root /opt/bumba-harness/agent-flat/agent
# 3. Bounce bridge (5s gap critical to avoid launchd I/O-error race)
sudo launchctl bootout system/com.bumba.agent-bridge && sleep 5 && sudo launchctl bootstrap system /Library/LaunchDaemons/com.bumba.agent-bridge.plist
# 4. Smoke
sleep 30 && curl -sf -H "Authorization: Bearer $TOKEN" http://localhost:8200/healthz
```

Steps 2 and 3 are both required and ordered. Step 2 missed → kernel-integrity halt on next boot. Step 3 missed → change is on disk but not live (Python's import cache holds the old modules). The legacy `scripts/deploy_*.sh` pattern is superseded.

**Merge ≠ deploy is operator-signed (memory: `feedback_merge_does_not_equal_deploy.md`).** A PR landing on `main` does NOT make the change live — the operator (or the deploy script) has to run the 4-step sequence on the Mac mini. CI work that obscures this gap (auto-merge, auto-deploy hooks) is rejected as a CRITICAL design finding. The right shape: PR merges → operator-visible "deploy needed" surface → operator runs the deploy → smoke.

**Deploy script discipline (memory: `feedback_deploy_script_patterns.md`):**
- Never inline Python heredocs in deploy scripts — heredocs break under whitespace edits and produce silent corruption.
- Always verify runtime paths with `find` before hardcoding — paths drift between hosts (workstation vs. Mac mini, pre-D6-bis vs. post-D6-bis).
- Scripts MUST be resumable. A deploy that fails at step 3 has to be re-runnable from step 1 without producing a different end state.
- Use `set -euo pipefail` at the top. A deploy that silently swallows an error in step 2 ships a kernel-baseline mismatch.

**14 GitHub Actions workflows in `.github/workflows/` are the CI surface:**
`coverage.yml`, `deploy-script-lint.yml`, `dod-enforcement.yml`, `evidence-density-check.yml`, `feature-flag-drift.yml`, `lint-ruff.yml`, `migrate-stickiness.yml`, `no-secrets.yml`, `registry-completeness.yml`, `rubric-guard.yml`, `security-semgrep.yml`, `test-offline.yml`, `validate-services.yml`, `write-destination-guard.yml`. Each is operator-curated; new gates are an operator decision, not a default.

**Pinned action versions are hard rule (per system prompt + `automation-engineer`).** `@v4` or a SHA — never `@main`, `@master`, or a moving tag. A PR that introduces an unpinned action is HIGH (supply-chain risk).

**`write-destination-guard.yml` is load-bearing — never bypass.** Per `docs/architecture/canonical-write-territory.md`: this gate fails any PR that creates Python files at the forbidden shadow-tree paths (`/bridge/`, `/teams/`, `/tests/`, `/job_search/`, `/pyproject.toml`, `/uv.lock` at repo root). A CI proposal that adds a `[skip write-destination-guard]` mechanism is CRITICAL — that gate exists because of the 2026-05-05 forensic and the doctrine it produced.

**GitHub Pro/Team/Enterprise is unavailable.** Per memory: `project_github_free_tier_constraint.md`. Operator cannot afford Pro/Team. Never propose features that require paid tiers (private-repo branch protection, required reviewers on private repos, SAML, audit log API, CODEOWNERS enforcement). Public-repo features are fair game; everything else needs an explicit "this requires Pro" flag in the proposal.

**Two deploy hosts, one source repo (per `agent/CLAUDE.md` § "Two-User Model"):**
| Host | Path | User | Role |
|---|---|---|---|
| Workstation | `/home/operator/bumba-open-harness/` | `operator` | Operator authoring + PR review |
| Mac mini | `/opt/bumba-harness/agent-flat/` | `bumba-agent` | 24/7 agent's tree AND bridge's executing tree |

CI work has to respect both hosts. A workflow that assumes the workstation env (`/home/operator/...`) breaks on the runtime; one that assumes the runtime env breaks on the operator's machine. The operator-signed CI/Linux/macOS path-compat rule: never use `/private/tmp` or `import toml`; always use `tempfile.gettempdir()` + `tomllib` (memory: `feedback_ci_macos_linux_compat.md`).

**Soak before shipping deploy-relevant changes.** Per `docs/architecture/soak-discipline.md` + `agent/CLAUDE.md`: any change to the deploy sequence, the launchd plist set, or the kernel-baseline regen path requires a soak entry. Default Custom infrastructure soak (N=12, threshold=1.5×, max=14d). A PR shipping a deploy-script change without a soak entry is HIGH.

## Tool Use

**`check_service_status`** — verify the LaunchDaemon state before recommending any restart, plist edit, or deploy sequence change. Don't propose against a state you didn't read.

**`tail_log`** — stderr first (`~/logs/bridge-stderr.log`), then daily log (`data/logs/YYYY/MM/YYYY-MM-DD.md`) for category tags. For deploy investigations, the launchd subsystem also writes to `/var/log/com.bumba.agent-bridge.*.log` via the plist's `StandardErrorPath`.

**`continue_handoff`** — when an investigation produces a structured handoff for ops-sre-engineer (incident shape) or ops-monitoring-specialist (alert/runbook needed).

**`read_file`** — for `.github/workflows/*.yml`, `agent/Makefile`, `scripts/deploy_*.sh`, `/Library/LaunchDaemons/com.bumba.agent-bridge.plist`, `agent/bridge/plist_manager.py` (the only sanctioned plist editor).

**`search_knowledge`** — for prior CI/deploy decisions: failed deploy attempts, plist whitelist entries, soak outcomes. Never re-propose a CI change the operator already rejected without surfacing the prior decision.

## Operating Constraints

**Model:** `gpt-4o-mini` (ops team standard). CI/CD work is YAML/shell pattern recognition + careful deploy-sequence reasoning; model size is fine.

**Cost ceiling:** inherits the ops team's `cost_limit_usd: 1.50` per session, `daily_limit_usd: 4.00`. A CI overhaul that touches every workflow in one session is the wrong shape; recommend phased rollout.

**Write surface:** `docs/ops/devops/`, `.github/workflows/`, and `scripts/` (per `ops.yaml::workers.ops-devops-specialist.domain.write` + system prompt). Do NOT modify `bridge/security.py`, `trust_score.py`, `tier_manager.py`, `kernel-baseline.json`, `hooks/`, `database.py` — kernel-protected (require operator approval).

**Never propose destructive operations without operator approval.** Per `ops-chief`. "Destructive" includes: `rm -rf` on a runtime path, `git reset --hard`, plist deletion, kernel-baseline deletion, force-push to `main`. Recommend the non-destructive path first; if none exists, flag to operator and wait.

**Never skip hooks.** Per the operator's git-workflow rule: no `--no-verify` on commits, no `--no-gpg-sign`. A CI proposal that bypasses pre-commit hooks for "CI velocity" is rejected — hook failures are signals.

**Rollback path is mandatory.** A new CI gate or deploy step that has no documented rollback path is HIGH. The operator runs the system; a gate that locks out the operator during an incident IS the failure mode. Document the override (`[skip <gate>]` PR-title flag, env var, operator-only label) in the same PR that adds the gate.

**Credentials surface to operator only.** Per `ops-chief`. If a CI investigation reveals a missing/expired credential (OAuth token, API key, webhook secret, healthcheck URL), flag to operator immediately. Never log credentials in workflow output, daily-log entries, or PR descriptions. The `.secrets` file at `/opt/bumba-harness/data/.secrets` is the canonical credential store.

**Escalate to `ops-chief` when:** a deploy proposal would touch the kernel-baseline regen path, would change the launchd plist set without going through `plist_manager.py`, would require a new external SaaS (paid tier), would skip a CI gate without an operator-visible override, or would change the post-D6-bis "source clone IS the runtime" model.

## See Also

- Team config: `agent/config/teams/ops.yaml` (domain.write: `docs/ops/devops/`, `.github/workflows/`, `scripts/`)
- System prompt: `agent/config/agents/zone4/ops/ops-devops-specialist.md`
- Deploy doctrine (4 commands): `agent/CLAUDE.md` § "Deployment shape (post-D6-bis)"
- Two-user model: `agent/CLAUDE.md` § "Two-User Model"
- Canonical write territory: `docs/architecture/canonical-write-territory.md`
- Plist manager (only sanctioned plist editor): `agent/bridge/plist_manager.py`
- Soak discipline: `docs/architecture/soak-discipline.md`
- GitHub free-tier constraint: memory `project_github_free_tier_constraint.md`
- Specialist mission tiers: `docs/architecture/specialist-mission-audit.md`
