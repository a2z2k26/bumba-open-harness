<!-- status: current — authored 2026-05-18 (#2133 / Sprint 5o.02) -->

# Output Quality Bar — `ops-devops-specialist`

**Specialist:** ops-devops-specialist
**Paired workflow:** `ops.deploy_to_mini` (#2180, Sprint 5o.03)
**Authored:** 2026-05-18

---

## 1. What the specialist produces

A deploy artifact: a tracked, auditable deployment from source to the Mac mini runtime, plus a markdown post-deploy report saved under `docs/ops/<date>-deploy-<commit>.md` and a Discord summary with deploy status + smoke evidence.

The deploy follows the post-D6-bis 4-step shape documented in `agent/CLAUDE.md` "Two-User Model": pull → kernel-baseline regen → bootout/bootstrap → smoke.

### Required output sections

1. **Deploy target** — commit SHA going live, branch, prior commit SHA on runtime
2. **Pre-deploy checklist** — clean working tree, kernel baseline status, halt-flag state, current health
3. **Deploy steps executed** — per step: timestamp + exit code + output excerpt
4. **Post-deploy smoke** — `/healthz` response, identity-doc kernel-baseline hash match, first scheduled-service tick captured
5. **Rollback path** — exact `git revert <sha>` + plist re-deploy commands ready if smoke fails

---

## 2. The bar (what's acceptable)

**A deploy artifact is acceptable when:**

- **Atomic.** Either the full 4-step sequence succeeds OR rollback runs to clean state. No half-deployed runtime ever.
- **Reversible.** Rollback command is explicit + tested-ready before the deploy fires. `git revert <sha>` AND any plist-revert AND any data-state-revert (if migrations ran).
- **Audit-trailed.** Every deploy lands a row in `data/deploys/<sha>.json` with timestamp + actor + exit codes per step.
- **Post-deploy smoke is real.** Not "I ran the command" — actual `/healthz` response captured, kernel-baseline hash verified, first scheduled-service tick observed within 5 min.
- **Halt-respect.** If halt flag is set, deploy refuses to proceed (the deploy is itself an autonomous action subject to operator halt).

**Specifically NOT acceptable:**

- "Deploy succeeded" without smoke evidence
- Half-rolled-back state (some plists re-deployed, some not)
- Audit row missing or partial (skipped exit codes)
- Rollback command "we'll figure it out if needed" — pre-deploy must declare the exact revert sequence
- Bypassing halt flag for "small" deploys

---

## 3. Failure modes (what degraded output looks like)

| Mode | Symptom | How to catch |
|---|---|---|
| **No smoke evidence** | Report says "deployed" but no `/healthz` response captured | Smoke section must include actual JSON response, not a description |
| **Kernel-baseline mismatch silenced** | Daemon halts on startup due to baseline drift; deploy report doesn't surface | Smoke must explicitly run `regenerate_kernel_baseline.py` OR verify hashes match post-deploy |
| **Audit row truncated** | data/deploys/<sha>.json exists but missing exit codes for some steps | Every step in the 4-step sequence must have an exit code recorded |
| **Rollback declared but untested** | Rollback section says "git revert" but the revert path was never validated | High-risk deploys (touching `bridge/`, identity docs, plists) must dry-run the rollback before firing the deploy |
| **First-tick missed** | Smoke says "service deployed" but never confirmed first scheduled-service tick fired post-deploy | Smoke must wait + capture at least one scheduled-service tick log entry |
| **Half-rolled-back** | Code reverted but plists already restarted with new binary; daemon now references old code via cached symbol table | Rollback must restart daemon AFTER code revert, not before |

---

## 4. Recent specialist invocations

> Operator-fill table populated post-invocation. The `ops.deploy_to_mini` workflow (#2180) emits Discord summaries with deploy results; record them here.

| Date | Commit | Steps OK? | Smoke OK? | Rollback fired? | Notes |
|---|---|---|---|---|---|
| YYYY-MM-DD | _SHA_ | _yes / partial_ | _yes / no_ | _no / yes-clean / yes-partial_ | _what shipped, what broke_ |

---

## 5. Specialist performance verdict

> **PENDING** until specialist has executed ≥3 real deploys. Verdict slot:

- [ ] Healthy — atomic, audit-trailed, smoke-verified, rollback-ready
- [ ] Degraded — deploys land but smoke is skipped OR audit rows incomplete
- [ ] Stale — running but operator has stopped trusting the deploy reports

Date recorded: _____________
