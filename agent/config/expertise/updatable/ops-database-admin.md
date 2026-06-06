---
agent: ops-database-admin
zone: 4
department: ops
type: updatable
max_lines: 500
schema_version: 1
---

# ops-database-admin — Expertise

*This file is updated by ops-database-admin after each significant session.*

## Domain Patterns

**Bumba runs on SQLite, not Postgres.** This is the load-bearing constraint. The bridge has multiple SQLite databases:
- `data/memory.db` — knowledge, conversations, FTS5, vector store. Schema lives in `agent/bridge/db/migrations.py` (`_TABLES` + 15 versioned migrations as of Mem-2.5 #1863).
- `data/workorders.db` — Z3 WorkOrder + Z4 ChiefSession state.
- `data/experiments.db` — autonomous experiment-loop state.
- `data/audit.jsonl` — append-only audit trail (NOT a database, but operationally adjacent).

All run in WAL mode. SQLite version is 3.45.x on the runtime; CI is 3.43+. ALTER TABLE constraints (no non-constant DEFAULTs on ADD COLUMN; no DROP COLUMN before 3.35) are real and have bitten this codebase. Mem-2.5 #1863 is the recent canonical example of how to write a clean migration.

**Migration discipline (operator-signed via the existing migrations):**
- One numbered tuple per migration in `_MIGRATIONS` in `agent/bridge/db/migrations.py`. Format: `(version, "description", [SQL_STATEMENT_1, ...])`.
- Migrations are forward-only by default. Reversibility documented in a sibling SQL file at `agent/scripts/rollback_migration_<N>.sql` when the column or table is load-bearing.
- Versioned migrations track in `schema_version` table; the runner skips already-applied versions (idempotent).
- New columns with non-constant defaults (e.g. `datetime('now')`) MUST be added nullable, then backfilled in a follow-up `UPDATE` statement in the same migration. SQLite refuses non-constant DEFAULTs on `ALTER TABLE ADD COLUMN`. See Mem-2.5 (#1863) commit body for the full pattern.
- New columns must NOT also be added to `_TABLES` `CREATE TABLE` if migration owns them — duplicate column errors on fresh DBs. Single source of truth (per Mem-2.5 lesson).
- Index every column that participates in a `WHERE` or `ORDER BY` for a hot path. The bridge's hot paths include `knowledge.tier`, `knowledge.last_accessed_at`, `chief_sessions.idle_since_utc`. Coverage is uneven — recommend index when missing.

**`bridge/database.py` is in the kernel integrity envelope.** Per ops-chief: "Forbidden files. No specialist recommends changes to `database.py` without explicit operator approval." Schema additions go through `agent/bridge/db/migrations.py` (which is NOT forbidden); the database connection / mixin orchestration in `database.py` itself is.

**Performance posture:**
- Backups run daily at 03:00 via `data/maintenance.sh`. The strategy is simple file copy of the WAL-checkpointed DBs to `data/backups/` with rolling retention. Off-site backup is not currently configured (see ops-cloud-architect for that recommendation).
- Slow query analysis: SQLite's `EXPLAIN QUERY PLAN` is the diagnostic. The runner doesn't have query logging enabled by default; turning it on (`PRAGMA query_only`, custom logger wrapper) is itself a performance hit — use only during diagnosis.
- VACUUM is part of the daily maintenance. Not safe to run while the bridge is running (locks the DB). Schedule against the daily maintenance window.
- FTS5 indexes need explicit `INSERT INTO knowledge_fts(knowledge_fts) VALUES('rebuild')` after large bulk-write operations. The triggers in `_FTS_AND_TRIGGERS` keep them current incrementally; rebuild is for recovery, not maintenance.

**Two parallel `tier` columns** (per CLAUDE.md + Mem-3.5 #1864):
- `knowledge.tier` — PREFERENCE | DECISION | CONTEXT (memory-tier-architecture epic)
- `knowledge_history.temporal_tier` — L0..L4 (Sprint 03.04 altitude tiers; renamed from `tier` in Mem-3.5)

These are different vocabularies and different consumers. A schema review that proposes "harmonize the tier columns" is the wrong shape — they're orthogonal.

**Backup + recovery contract:**
- RPO (Recovery Point Objective): 24 hours. Daily backup is the only durable copy.
- RTO (Recovery Time Objective): minutes. Backup is a file copy; restore is a file copy back.
- Off-site is the gap. Recommend addressing.

**Severity ladder:**
- **CRITICAL** — schema change without rollback path; ALTER that would lock the DB during runtime; backup script that doesn't survive a crashed bridge mid-write.
- **HIGH** — missing index on a hot-path query; non-idempotent migration; new column added to `_TABLES` AND a migration (Mem-2.5 lesson).
- **MEDIUM** — slow query that would benefit from refactor but isn't blocking; backup retention that doesn't survive a 7-day rolling window.
- **LOW** — docstring drift; `EXPLAIN QUERY PLAN` not captured in the migration commit body.

**Finding format:**
```
**[SEVERITY]** <one-line title>
DB: <which database file>
Schema/query: <table.column or SQL snippet>
Repro: <how to reproduce locally — sqlite3 command or pytest target>
Fix: <smallest-surface change; cite the canonical pattern>
Cite: <migration discipline rule, kernel-envelope rule, etc.>
```

## Tool Use

**`read_file`** — for `agent/bridge/db/migrations.py`, `agent/bridge/database.py` (READ ONLY — kernel envelope), `agent/bridge/memory/knowledge.py`, `agent/bridge/db/queries.py`, `agent/data/maintenance.sh`, `agent/scripts/rollback_migration_*.sql`.

**`run_tests`** (when available) — `pytest tests/test_database.py tests/test_migration_*.py -q` is the canonical migration-test cluster. Always run before recommending a migration.

**`search_knowledge`** — for prior schema decisions: which migrations were rolled back, which columns were renamed (Mem-3.5 #1864 is recent canonical), which indexes were added after a perf incident.

**Do NOT modify production code or migrations directly.** This specialist proposes; ops-chief reviews; ops-devops-specialist or memory-tier sprint owner implements.

## Operating Constraints

**Model:** `gpt-4o-mini` (ops team standard).

**Cost ceiling:** inherits the ops team's `cost_limit_usd: 1.50` per session.

**Write surface:** documentation only (typically `docs/architecture/` notes for migration design, or `docs/operator/` for backup runbooks). NEVER `agent/`, `tests/`, or schema source.

**SQLite version assumptions explicit.** Recommendations that require SQLite 3.35+ (DROP COLUMN), 3.25+ (RENAME COLUMN), or other version-gated features must state the requirement. Runtime is 3.45.x; CI is 3.43+; older client tools may be on 3.31 (macOS system SQLite).

**Migration commit body documents the why.** Per Mem-2.5's commit example: every migration PR body includes the bug found, the workaround chosen, and the rejected alternatives. This becomes the historical record next time someone asks "why did we do it this way?"

**Backup is not optional.** Any schema change proposal includes a verification step that the daily backup will pick up the new tables/columns automatically (it will — `maintenance.sh` is whole-DB copy, not table-list-driven).

**Escalate to ops-chief when:** a migration would require runtime downtime (none of the existing 15 do), `bridge/database.py` itself needs modification (kernel envelope), backup strategy is being changed, or off-site backup is being proposed (cost decision goes to ops-chief + operator).

## See Also

- Team config: `agent/config/teams/ops.yaml`
- System prompt: `agent/config/agents/zone4/ops/ops-database-admin.md`
- Migrations source: `agent/bridge/db/migrations.py`
- Kernel-envelope rule: `agent/CLAUDE.md` § "Forbidden files" (referenced from ops-chief expertise)
- Mem-2.5 migration pattern: PR #1964 commit body (the canonical "right way to add a column with datetime default")
- Mem-3.5 column rename: PR #1958 (the canonical RENAME COLUMN migration with three-DB-state idempotency)
- Sibling: `ops-cloud-architect.md` (for off-site backup recommendations)
