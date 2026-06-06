<!-- status: current — authored 2026-05-18 (#2133 / Sprint 5o.02) -->

# Output Quality Bar — `ops-database-admin`

**Specialist:** ops-database-admin
**Paired workflow:** Manual invocation (no Phase 5 workflow yet; future `ops.db_change` candidate)
**Authored:** 2026-05-18

---

## 1. What the specialist produces

A markdown DB-change artifact saved under `docs/ops/db-changes/<date>-<change-name>.md`, plus a Discord summary with change status + rollback path + verification evidence.

The DB-change covers any schema migration, data migration, index addition, VACUUM, or destructive query against `data/memory.db`, the second_brain SQLite, or any future operational store.

### Required output sections

1. **Change description** — what's changing, why, which DB, which tables, expected blast radius
2. **Backup-before evidence** — backup file path + size + timestamp + verification it's restorable
3. **Migration steps** — per step: idempotent SQL (or python migration call) + expected effect + verification query
4. **Staging-tested evidence** — same migration run against a staging copy of the DB; results captured
5. **Rollback path** — exact commands to revert (down-migration OR backup-restore OR data-mutation reversal)

---

## 2. The bar (what's acceptable)

**A DB-change artifact is acceptable when:**

- **Backup before.** Always. Pre-change backup taken + verified restorable (not just "the file exists" — actual smoke restore to a temp DB + simple query).
- **Idempotent.** Every step can run twice without breaking. `IF NOT EXISTS`, `INSERT ... ON CONFLICT`, `ALTER TABLE ... ADD COLUMN IF NOT EXISTS`. Re-running the migration after a partial failure is safe.
- **Tested in staging.** A copy of the production DB has had this migration applied; results verified before production fires.
- **Rollback is one command, not a runbook.** "Restore backup from `data/backups/memory-pre-mem8-migration.db`" is acceptable. "Drop the new column, then..." is acceptable only if down-migration is one transaction.
- **Verification queries run post-change.** Every step has a check: row count, schema shape, sample row sanity. Not "looks good" — actual query output captured.

**Specifically NOT acceptable:**

- "I'll back up after" / no backup
- Non-idempotent steps (`CREATE TABLE` without `IF NOT EXISTS`)
- Production-first changes (no staging test)
- Rollback that's a multi-step recipe with judgment calls
- Verification by inspection instead of query

---

## 3. Failure modes (what degraded output looks like)

| Mode | Symptom | How to catch |
|---|---|---|
| **No backup** | Backup section says "skipped — small change" | Backup is non-negotiable; section presence enforced |
| **Backup unverified** | Backup file exists but never restored to smoke | Verification step required: restore to temp DB + SELECT |
| **Non-idempotent** | Step 3 fails; re-running step 3 errors instead of resuming | Each step must declare its idempotency mechanism (IF NOT EXISTS, conflict clause, etc.) |
| **Skipped staging** | "Looks similar to migration X which worked" without actual staging run | Staging-tested section must show actual staging-DB output |
| **Multi-step rollback** | Rollback is a 6-step recipe with "if X then Y" branches | Rollback must collapse to one command per change-type |
| **Verification by inspection** | "Schema looks right" without `PRAGMA table_info` or `SELECT COUNT(*)` output | Each step's verification query must show output, not assertion |

---

## 4. Recent specialist invocations

> Operator-fill table populated post-invocation. Each DB change gets a row; reference the change doc.

| Date | Change | Backup verified? | Staging tested? | Rollback fired? | Notes |
|---|---|---|---|---|---|
| YYYY-MM-DD | _name_ | _yes / no_ | _yes / no_ | _no / yes-clean / yes-partial_ | _what shipped, what broke_ |

---

## 5. Specialist performance verdict

> **PENDING** until specialist has executed ≥3 real DB changes. Verdict slot:

- [ ] Healthy — backup-tested, idempotent, staging-validated, rollback-ready
- [ ] Degraded — changes land but staging gets skipped OR rollback path is vague
- [ ] Stale — running but operator stopped reviewing DB-change artifacts

Date recorded: _____________
