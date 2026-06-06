"""Schema DDL constants and versioned migration runner.

Extracted from ``bridge/database.py`` as part of the issue #1305 demote-split.

The bulk of this module is SQL DDL strings — the base table set
(``_TABLES``), FTS5 + triggers (``_FTS_AND_TRIGGERS``), and the 14 versioned
migrations (``_MIGRATIONS``). The mixin owns the migration runner and the
schema-version getter.

The migration system is forward-only and idempotent — every statement is
``CREATE ... IF NOT EXISTS`` / ``ALTER ... ADD COLUMN``-style, and the
``schema_version`` table guarantees each numbered migration runs exactly
once.

The mixin assumes the concrete class provides:

* ``self._ensure_connected()`` → ``aiosqlite.Connection`` (from
  ``ConnectionMixin``).
* ``self.fetchone()`` (from ``ConnectionMixin``).
"""

from __future__ import annotations

import logging

import aiosqlite

log = logging.getLogger(__name__)

# -- S36: Schema (tables + indexes) --

_TABLES = [
    # knowledge
    """CREATE TABLE IF NOT EXISTS knowledge (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL,
        tags TEXT,
        created_at TEXT NOT NULL DEFAULT (datetime('now')),
        updated_at TEXT NOT NULL DEFAULT (datetime('now')),
        expires_at TEXT,
        source TEXT NOT NULL DEFAULT 'agent'
    );""",
    "CREATE INDEX IF NOT EXISTS idx_knowledge_tags ON knowledge(tags);",
    "CREATE INDEX IF NOT EXISTS idx_knowledge_updated ON knowledge(updated_at);",
    "CREATE INDEX IF NOT EXISTS idx_knowledge_source ON knowledge(source);",

    # conversations
    """CREATE TABLE IF NOT EXISTS conversations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id TEXT NOT NULL,
        chat_id TEXT NOT NULL,
        role TEXT NOT NULL,
        content TEXT NOT NULL,
        platform_message_id INTEGER,
        tools_used TEXT,
        cost_usd REAL,
        duration_ms INTEGER,
        created_at TEXT NOT NULL DEFAULT (datetime('now'))
    );""",
    "CREATE INDEX IF NOT EXISTS idx_conversations_session ON conversations(session_id);",
    "CREATE INDEX IF NOT EXISTS idx_conversations_chat ON conversations(chat_id);",
    "CREATE INDEX IF NOT EXISTS idx_conversations_created ON conversations(created_at);",

    # sessions
    """CREATE TABLE IF NOT EXISTS sessions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        chat_id TEXT NOT NULL,
        claude_session_id TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'active',
        created_at TEXT NOT NULL DEFAULT (datetime('now')),
        last_active_at TEXT NOT NULL DEFAULT (datetime('now')),
        message_count INTEGER NOT NULL DEFAULT 0,
        total_cost_usd REAL NOT NULL DEFAULT 0.0,
        expired_reason TEXT
    );""",
    "CREATE INDEX IF NOT EXISTS idx_sessions_chat ON sessions(chat_id);",
    "CREATE INDEX IF NOT EXISTS idx_sessions_status ON sessions(status);",
    """CREATE UNIQUE INDEX IF NOT EXISTS idx_sessions_active
        ON sessions(chat_id) WHERE status = 'active';""",

    # message_queue
    """CREATE TABLE IF NOT EXISTS message_queue (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        platform_message_id INTEGER NOT NULL,
        chat_id TEXT NOT NULL,
        text TEXT NOT NULL,
        received_at TEXT NOT NULL DEFAULT (datetime('now')),
        status TEXT NOT NULL DEFAULT 'pending',
        attempt_count INTEGER NOT NULL DEFAULT 0,
        response_text TEXT,
        completed_at TEXT,
        error_details TEXT
    );""",
    "CREATE INDEX IF NOT EXISTS idx_mq_status ON message_queue(status);",
    "CREATE INDEX IF NOT EXISTS idx_mq_received ON message_queue(received_at);",

    # audit_log
    """CREATE TABLE IF NOT EXISTS audit_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp TEXT NOT NULL DEFAULT (datetime('now')),
        event_type TEXT NOT NULL,
        tool_name TEXT,
        arguments TEXT,
        outcome TEXT,
        details TEXT,
        session_id TEXT,
        chat_id TEXT
    );""",
    "CREATE INDEX IF NOT EXISTS idx_audit_timestamp ON audit_log(timestamp);",
    "CREATE INDEX IF NOT EXISTS idx_audit_event_type ON audit_log(event_type);",
    "CREATE INDEX IF NOT EXISTS idx_audit_session ON audit_log(session_id);",
]

# -- S37: FTS5 + triggers --

_FTS_AND_TRIGGERS = [
    # FTS5 virtual table
    """CREATE VIRTUAL TABLE IF NOT EXISTS knowledge_fts USING fts5(
        key, value, tags,
        content='knowledge',
        content_rowid='rowid'
    );""",

    # FTS sync triggers
    """CREATE TRIGGER IF NOT EXISTS knowledge_ai AFTER INSERT ON knowledge BEGIN
        INSERT INTO knowledge_fts(rowid, key, value, tags)
        VALUES (new.rowid, new.key, new.value, new.tags);
    END;""",

    """CREATE TRIGGER IF NOT EXISTS knowledge_ad AFTER DELETE ON knowledge BEGIN
        INSERT INTO knowledge_fts(knowledge_fts, rowid, key, value, tags)
        VALUES('delete', old.rowid, old.key, old.value, old.tags);
    END;""",

    """CREATE TRIGGER IF NOT EXISTS knowledge_au AFTER UPDATE ON knowledge BEGIN
        INSERT INTO knowledge_fts(knowledge_fts, rowid, key, value, tags)
        VALUES('delete', old.rowid, old.key, old.value, old.tags);
        INSERT INTO knowledge_fts(rowid, key, value, tags)
        VALUES (new.rowid, new.key, new.value, new.tags);
    END;""",

    # Audit log append-only enforcement
    """CREATE TRIGGER IF NOT EXISTS audit_no_delete
    BEFORE DELETE ON audit_log
    BEGIN
        SELECT RAISE(ABORT, 'Audit log entries cannot be deleted');
    END;""",

    """CREATE TRIGGER IF NOT EXISTS audit_no_update
    BEFORE UPDATE ON audit_log
    BEGIN
        SELECT RAISE(ABORT, 'Audit log entries cannot be modified');
    END;""",
]

# -- Schema version tracking --

_SCHEMA_VERSION_TABLE = """CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER PRIMARY KEY,
    description TEXT NOT NULL,
    applied_at TEXT NOT NULL DEFAULT (datetime('now'))
);"""

# Versioned migrations: (version, description, list_of_sql_statements)
# Each migration runs exactly once, tracked by schema_version table.
_MIGRATIONS: list[tuple[int, str, list[str]]] = [
    # Migration 1: Knowledge categories and archiving
    (1, "Add category and archived columns to knowledge", [
        "ALTER TABLE knowledge ADD COLUMN category TEXT DEFAULT 'reference';",
        "ALTER TABLE knowledge ADD COLUMN archived INTEGER DEFAULT 0;",
    ]),
    # Migration 2: Auto-categorize existing knowledge entries
    (2, "Auto-categorize existing knowledge entries", [
        "UPDATE knowledge SET category = 'preference' WHERE key LIKE 'user:%';",
        "UPDATE knowledge SET category = 'decision' WHERE key LIKE 'decision:%';",
        "UPDATE knowledge SET category = 'process' WHERE key LIKE 'session:summary:%';",
        "UPDATE knowledge SET category = 'person' WHERE key LIKE 'person:%';",
        "UPDATE knowledge SET category = 'project' WHERE key LIKE 'project:%';",
        "UPDATE knowledge SET category = 'tool' WHERE key LIKE 'tool:%';",
    ]),
    # Migration 3: Async tasks table for HITL
    (3, "Create async_tasks table for HITL task queue", [
        """CREATE TABLE IF NOT EXISTS async_tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            status TEXT NOT NULL DEFAULT 'pending',
            prompt TEXT,
            session_id TEXT,
            claude_session_id TEXT,
            pending_question TEXT,
            pending_options TEXT,
            user_response TEXT,
            result TEXT,
            chat_id TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        );""",
        "CREATE INDEX IF NOT EXISTS idx_async_tasks_status ON async_tasks(status);",
        "CREATE INDEX IF NOT EXISTS idx_async_tasks_chat ON async_tasks(chat_id);",
    ]),
    # Migration 4: Embedding columns for semantic search
    (4, "Add embedding columns to knowledge and conversations", [
        "ALTER TABLE knowledge ADD COLUMN embedding BLOB;",
        "ALTER TABLE conversations ADD COLUMN embedding BLOB;",
    ]),
    # Migration 5: Rebuild FTS5 to include category column
    (5, "Rebuild FTS5 index to include category column", [
        # Drop old triggers first
        "DROP TRIGGER IF EXISTS knowledge_ai;",
        "DROP TRIGGER IF EXISTS knowledge_ad;",
        "DROP TRIGGER IF EXISTS knowledge_au;",
        # Drop and rebuild FTS5 with category
        "DROP TABLE IF EXISTS knowledge_fts;",
        """CREATE VIRTUAL TABLE knowledge_fts USING fts5(
            key, value, tags, category,
            content='knowledge',
            content_rowid='rowid'
        );""",
        # Rebuild triggers with category
        """CREATE TRIGGER knowledge_ai AFTER INSERT ON knowledge BEGIN
            INSERT INTO knowledge_fts(rowid, key, value, tags, category)
            VALUES (new.rowid, new.key, new.value, new.tags, new.category);
        END;""",
        """CREATE TRIGGER knowledge_ad AFTER DELETE ON knowledge BEGIN
            INSERT INTO knowledge_fts(knowledge_fts, rowid, key, value, tags, category)
            VALUES('delete', old.rowid, old.key, old.value, old.tags, old.category);
        END;""",
        """CREATE TRIGGER knowledge_au AFTER UPDATE ON knowledge BEGIN
            INSERT INTO knowledge_fts(knowledge_fts, rowid, key, value, tags, category)
            VALUES('delete', old.rowid, old.key, old.value, old.tags, old.category);
            INSERT INTO knowledge_fts(rowid, key, value, tags, category)
            VALUES (new.rowid, new.key, new.value, new.tags, new.category);
        END;""",
        # Repopulate FTS5 from existing data
        """INSERT INTO knowledge_fts(rowid, key, value, tags, category)
            SELECT rowid, key, value, tags, category FROM knowledge;""",
    ]),
    # Migration 6: Salience-weighted memory decay
    (6, "Add salience, accessed_at, access_count columns for memory decay", [
        "ALTER TABLE knowledge ADD COLUMN salience REAL NOT NULL DEFAULT 1.0;",
        "ALTER TABLE knowledge ADD COLUMN accessed_at TEXT;",
        "ALTER TABLE knowledge ADD COLUMN access_count INTEGER NOT NULL DEFAULT 0;",
        "CREATE INDEX IF NOT EXISTS idx_knowledge_salience ON knowledge(salience);",
        "CREATE INDEX IF NOT EXISTS idx_knowledge_accessed ON knowledge(accessed_at);",
        # Seed accessed_at from updated_at for existing rows
        "UPDATE knowledge SET accessed_at = updated_at WHERE accessed_at IS NULL;",
        # Operator-sourced entries start at high salience (protected)
        "UPDATE knowledge SET salience = 4.0 WHERE source = 'operator';",
        # Active goals start at high salience
        "UPDATE knowledge SET salience = 3.0 WHERE key LIKE 'goal:%' AND (archived IS NULL OR archived = 0);",
    ]),
    # Migration 7: Budget tracking table
    (7, "Create budget_log table for daily cost tracking", [
        """CREATE TABLE IF NOT EXISTS budget_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL DEFAULT (datetime('now')),
            cost_usd REAL NOT NULL,
            session_id TEXT,
            chat_id TEXT
        );""",
        "CREATE INDEX IF NOT EXISTS idx_budget_timestamp ON budget_log(timestamp);",
    ]),
    # Migration 8: FTS5 full-text search on conversations
    (8, "Add FTS5 search index on conversations", [
        """CREATE VIRTUAL TABLE IF NOT EXISTS conversations_fts USING fts5(
            content,
            content='conversations',
            content_rowid='id'
        );""",
        """CREATE TRIGGER IF NOT EXISTS conversations_fts_insert
        AFTER INSERT ON conversations BEGIN
            INSERT INTO conversations_fts(rowid, content)
            VALUES (new.id, new.content);
        END;""",
        """CREATE TRIGGER IF NOT EXISTS conversations_fts_delete
        AFTER DELETE ON conversations BEGIN
            INSERT INTO conversations_fts(conversations_fts, rowid, content)
            VALUES('delete', old.id, old.content);
        END;""",
        """CREATE TRIGGER IF NOT EXISTS conversations_fts_update
        AFTER UPDATE ON conversations BEGIN
            INSERT INTO conversations_fts(conversations_fts, rowid, content)
            VALUES('delete', old.id, old.content);
            INSERT INTO conversations_fts(rowid, content)
            VALUES (new.id, new.content);
        END;""",
        # Backfill existing conversations
        """INSERT INTO conversations_fts(rowid, content)
            SELECT id, content FROM conversations;""",
    ]),
    # Migration 9: Experiment log for autonomous self-improvement loop
    (9, "Create experiment_log table for autonomous experiment tracking", [
        """CREATE TABLE IF NOT EXISTS experiment_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            commit_hash TEXT,
            branch TEXT,
            tests_passed INTEGER,
            tests_failed INTEGER,
            tests_total INTEGER,
            status TEXT CHECK(status IN ('keep', 'discard', 'crash')),
            description TEXT,
            diff_summary TEXT,
            cost_usd REAL DEFAULT 0.0,
            duration_seconds REAL,
            created_at TEXT DEFAULT (datetime('now'))
        );""",
        "CREATE INDEX IF NOT EXISTS idx_experiment_log_status ON experiment_log(status);",
        "CREATE INDEX IF NOT EXISTS idx_experiment_log_created ON experiment_log(created_at);",
    ]),
    # Migration 10: Directive protocol persistence (Sprint 20, Phase 5B).
    # Stores Main Agent → chief directives with an immutable history audit
    # trail. Status transitions append to directive_history so the lifecycle
    # is reconstructible after a bridge restart.
    (10, "Create directives + directive_history tables for Phase 5 directive protocol", [
        """CREATE TABLE IF NOT EXISTS directives (
            directive_id TEXT PRIMARY KEY,
            from_agent TEXT NOT NULL,
            to_chief TEXT NOT NULL,
            intent TEXT NOT NULL,
            constraints_json TEXT NOT NULL DEFAULT '[]',
            deadline_utc TEXT,
            priority TEXT NOT NULL CHECK(priority IN ('p0', 'p1', 'p2')),
            issued_at_utc TEXT NOT NULL,
            status TEXT NOT NULL CHECK(status IN (
                'issued', 'accepted', 'in_progress', 'done', 'blocked', 'cancelled'
            )),
            context_json TEXT NOT NULL DEFAULT '{}',
            operator_id TEXT NOT NULL DEFAULT '',
            updated_at_utc TEXT NOT NULL
        );""",
        "CREATE INDEX IF NOT EXISTS idx_directives_status ON directives(status);",
        "CREATE INDEX IF NOT EXISTS idx_directives_to_chief ON directives(to_chief);",
        "CREATE INDEX IF NOT EXISTS idx_directives_issued_at ON directives(issued_at_utc);",
        """CREATE TABLE IF NOT EXISTS directive_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            directive_id TEXT NOT NULL,
            from_status TEXT,
            to_status TEXT NOT NULL,
            note TEXT,
            transitioned_at_utc TEXT NOT NULL DEFAULT (datetime('now')),
            FOREIGN KEY (directive_id) REFERENCES directives(directive_id)
        );""",
        "CREATE INDEX IF NOT EXISTS idx_directive_history_directive_id ON directive_history(directive_id);",
        "CREATE INDEX IF NOT EXISTS idx_directive_history_transitioned_at ON directive_history(transitioned_at_utc);",
    ]),
    # Migration 11: Task protocol persistence (Sprint 21, Phase 5B).
    # Stores chief → specialist tasks with an immutable history audit trail.
    # Tasks correlate to their parent Directive via directive_id (FK to the
    # directives table from migration #10). When a chief is invoked outside
    # a directive flow (legacy /route, cron), directive_id is NULL — Tasks
    # are still recorded for observability.
    (11, "Create tasks + task_history tables for Phase 5 task protocol", [
        """CREATE TABLE IF NOT EXISTS tasks (
            task_id TEXT PRIMARY KEY,
            directive_id TEXT,
            from_chief TEXT NOT NULL,
            to_specialist TEXT NOT NULL,
            description TEXT NOT NULL,
            constraints_json TEXT NOT NULL DEFAULT '[]',
            deadline_utc TEXT,
            issued_at_utc TEXT NOT NULL,
            status TEXT NOT NULL CHECK(status IN (
                'assigned', 'in_progress', 'done', 'blocked', 'cancelled'
            )),
            updated_at_utc TEXT NOT NULL,
            FOREIGN KEY (directive_id) REFERENCES directives(directive_id)
        );""",
        "CREATE INDEX IF NOT EXISTS idx_tasks_directive_id ON tasks(directive_id);",
        "CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);",
        "CREATE INDEX IF NOT EXISTS idx_tasks_to_specialist ON tasks(to_specialist);",
        "CREATE INDEX IF NOT EXISTS idx_tasks_issued_at ON tasks(issued_at_utc);",
        """CREATE TABLE IF NOT EXISTS task_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id TEXT NOT NULL,
            from_status TEXT,
            to_status TEXT NOT NULL,
            note TEXT,
            transitioned_at_utc TEXT NOT NULL DEFAULT (datetime('now')),
            FOREIGN KEY (task_id) REFERENCES tasks(task_id)
        );""",
        "CREATE INDEX IF NOT EXISTS idx_task_history_task_id ON task_history(task_id);",
        "CREATE INDEX IF NOT EXISTS idx_task_history_transitioned_at ON task_history(transitioned_at_utc);",
    ]),
    # Migration 12: Surface protocol persistence (Sprint 22, Phase 5C).
    # Stores upward-flowing events from specialists to chiefs and chiefs
    # to the Main Agent. Every Task must produce at least one RESULT
    # surface (synthesized in _team.py if the specialist forgets); chiefs
    # emit RESULT to "main" on synthesis return. Mid-flight surfaces
    # (FLAG, BLOCKER, SCOPE_REQUEST, CROSS_TEAM, POLICY_Q) let agents
    # communicate progress and blockers without terminating the run.
    #
    # ``correlation_id`` is task_id for specialist→chief, directive_id
    # for chief→main. NULL allowed for out-of-band surfaces. We don't add
    # a FK because correlation_id refers to two different tables — the
    # column is intentionally polymorphic, validated by the application
    # layer that knows which kind of correlation it is writing.
    (12, "Create surfaces table for Phase 5 surface protocol", [
        """CREATE TABLE IF NOT EXISTS surfaces (
            surface_id TEXT PRIMARY KEY,
            from_agent TEXT NOT NULL,
            to_agent TEXT NOT NULL,
            kind TEXT NOT NULL CHECK(kind IN (
                'result', 'flag', 'blocker', 'scope_request', 'cross_team', 'policy_q'
            )),
            urgency TEXT NOT NULL CHECK(urgency IN (
                'fyi', 'attention', 'immediate'
            )),
            correlation_id TEXT,
            payload_json TEXT NOT NULL DEFAULT '{}',
            created_at_utc TEXT NOT NULL,
            read_at_utc TEXT
        );""",
        "CREATE INDEX IF NOT EXISTS idx_surfaces_correlation_id ON surfaces(correlation_id);",
        "CREATE INDEX IF NOT EXISTS idx_surfaces_to_agent ON surfaces(to_agent);",
        "CREATE INDEX IF NOT EXISTS idx_surfaces_kind ON surfaces(kind);",
        "CREATE INDEX IF NOT EXISTS idx_surfaces_created_at ON surfaces(created_at_utc);",
        # Composite for the /surfaces unread <agent> query path
        "CREATE INDEX IF NOT EXISTS idx_surfaces_unread ON surfaces(to_agent, read_at_utc);",
    ]),
    # Migration 13: Chief session persistence (Z4-S10 #1381, Phase 1).
    # Stores ``ChiefSession`` envelopes — the durable per-WorkOrder record
    # of a chief agent's lifecycle from COLD through SHUTDOWN. Today's
    # chief is WARM single-run (per the team-playbook from Z4-S00 #1384);
    # the *envelope* persists across the WorkOrder's lifetime so requeue,
    # retry, and idle-timeout reaping survive a bridge restart.
    #
    # ``chief_session_history`` records every state transition so post-hoc
    # debugging of "why did this chief end up SHUTDOWN" is possible without
    # log spelunking. The history table is reserved capacity for Z4-S30
    # (idle-timeout reaper #1391); the SQLite store ships in this PR but
    # the history rows wire up later.
    #
    # Reversibility (informational — the migration system is forward-only):
    #   DROP TABLE IF EXISTS chief_session_history;
    #   DROP TABLE IF EXISTS chief_sessions;
    #
    # Idempotent: ``CREATE TABLE IF NOT EXISTS`` + ``CREATE INDEX IF NOT EXISTS``
    # everywhere; running ``migrate()`` twice is a no-op.
    (13, "Create chief_sessions + chief_session_history tables for Z4 chief-session persistence", [
        """CREATE TABLE IF NOT EXISTS chief_sessions (
            session_id TEXT PRIMARY KEY,
            work_order_id TEXT NOT NULL,
            department TEXT NOT NULL,
            chief_name TEXT NOT NULL,
            state TEXT NOT NULL DEFAULT 'cold',
            created_at_utc TEXT NOT NULL,
            warmed_at_utc TEXT,
            execution_started_at_utc TEXT,
            completed_at_utc TEXT,
            idle_since_utc TEXT,
            run_count INTEGER NOT NULL DEFAULT 0,
            cost_usd REAL NOT NULL DEFAULT 0.0,
            error TEXT,
            metadata_json TEXT NOT NULL DEFAULT '{}',
            CHECK (state IN (
                'cold','warm','executing','awaiting_evaluation',
                'done','failed','timed_out','shutdown'
            ))
        );""",
        "CREATE INDEX IF NOT EXISTS idx_chief_sessions_work_order ON chief_sessions(work_order_id);",
        "CREATE INDEX IF NOT EXISTS idx_chief_sessions_state ON chief_sessions(state);",
        # Partial index for the idle-timeout reaper (Z4-S30 #1391) — only
        # AWAITING_EVALUATION rows are candidates, so narrowing the index
        # keeps it small even if the table grows large.
        """CREATE INDEX IF NOT EXISTS idx_chief_sessions_idle
            ON chief_sessions (state, idle_since_utc)
            WHERE state = 'awaiting_evaluation';""",
        """CREATE TABLE IF NOT EXISTS chief_session_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL REFERENCES chief_sessions(session_id),
            from_state TEXT NOT NULL,
            to_state TEXT NOT NULL,
            transitioned_at_utc TEXT NOT NULL,
            reason TEXT
        );""",
        "CREATE INDEX IF NOT EXISTS idx_chief_session_history_session_id ON chief_session_history(session_id);",
    ]),
    # Migration 14: Memory-tier column for Mem-2 (memory-tier-architecture epic, #1843).
    # Adds the canonical `knowledge.tier` column carrying Mem-1's MemoryTier
    # enum values (`preference` | `decision` | `context`). The DEFAULT is
    # `'context'` so unspecified writes fall through to the lowest tier;
    # auto-backfill UPDATEs reuse Migration 2's prefix conventions
    # (`'user:%'` → preference, `'decision:%'` → decision). NOT NULL is
    # safe at ALTER-time in SQLite 3.x because the constant DEFAULT
    # satisfies the constraint on existing rows.
    #
    # Reversibility: agent/scripts/rollback_migration_14.sql
    #     (requires SQLite ≥ 3.35 for ALTER TABLE DROP COLUMN).
    #
    # Known parallel system: `knowledge_history.temporal_tier` (added by
    # Sprint 03.04 / PR #993 as `tier`, renamed by Mem-3.5 #1864) carries
    # L0-L4 semantics — different vocabulary from this column's
    # PREFERENCE/DECISION/CONTEXT enum. Do not modify `knowledge_history`
    # from this migration.
    (14, "Add tier column to knowledge for memory-tiers epic", [
        "ALTER TABLE knowledge ADD COLUMN tier TEXT DEFAULT 'context' NOT NULL;",
        "UPDATE knowledge SET tier = 'preference' WHERE key LIKE 'user:%';",
        "UPDATE knowledge SET tier = 'decision' WHERE key LIKE 'decision:%';",
        "CREATE INDEX IF NOT EXISTS idx_knowledge_tier ON knowledge(tier);",
    ]),
    # Sprint Mem-2.5 (#1863): add `last_accessed_at` for hybrid TTL.
    #
    # Distinct from `accessed_at` (Sprint 06.x decay column): `accessed_at`
    # is updated by `_reinforce_entries` and is coupled to salience math
    # (only fires on results that get bumped). `last_accessed_at` updates
    # on EVERY read — `get_knowledge`, every branch of `search_knowledge`,
    # `assemble_context_window` — without touching salience. This gives
    # the future tier-eviction sweep (Mem-7 dream_agent) a clean signal
    # to evict-on-stale rather than evict-on-age.
    #
    # Migration owns the column for BOTH fresh and legacy DBs (the base
    # `CREATE TABLE` in `_TABLES` does NOT include `last_accessed_at`).
    # SQLite refuses non-constant DEFAULTs on `ALTER TABLE ADD COLUMN`
    # ("Cannot add a column with non-constant default" — `datetime('now')`
    # is not a constant), so the column is nullable at ALTER time and
    # backfilled with a follow-up UPDATE. New rows inserted by
    # `KnowledgeMixin.store_knowledge` after migration get NULL for this
    # column; the first read via `_touch_last_accessed` populates it.
    # That's good enough for the tier-eviction-on-stale signal (Mem-7).
    (15, "Add last_accessed_at column to knowledge for Mem-2.5 hybrid TTL", [
        "ALTER TABLE knowledge ADD COLUMN last_accessed_at TEXT;",
        "UPDATE knowledge SET last_accessed_at = datetime('now') WHERE last_accessed_at IS NULL;",
        "CREATE INDEX IF NOT EXISTS idx_knowledge_last_accessed ON knowledge(last_accessed_at);",
    ]),
    # Sprint zone4-warmth.B.01 (#2293): add `message_history_blob` to
    # `chief_sessions` so Phase 3 (warm-chief reload) can persist the
    # serialized PydanticAI message history across runs.
    #
    # The BLOB stores the bytes output of
    #   pydantic_ai.messages.ModelMessagesTypeAdapter.dump_json(messages)
    # SQLite BLOB is the right type — we deliberately don't use TEXT to
    # avoid encoding ambiguity around the pydantic-ai message schema's
    # binary fields (tool-call IDs etc.).
    #
    # The column is NULLABLE: pre-Phase-3 sessions never populate it, and
    # the nullability also lets a clean revert leave the dormant column
    # behind without breaking reads.
    #
    # Schema-only sprint: no readers, no writers yet. B.02 will write
    # the blob in WarmChief.__aexit__; C.03 will read it on warm reload.
    #
    # WAL-safe: ALTER TABLE ADD COLUMN with a nullable column is O(1) in
    # SQLite under WAL mode — no row rewrite required.
    #
    # No DOWN migration: SQLite's ALTER TABLE DROP COLUMN (added in 3.35)
    # is not WAL-safe across all SQLite builds the bridge might run on.
    # Reverts happen via PR revert; the dormant column stays in the
    # schema as a harmless NULL.
    #
    # NOTE: the sprint spec (sprint-b01) refers to this as "migration #14"
    # because the spec was drafted against an older baseline. Migration
    # slots 14 (knowledge.tier) and 15 (knowledge.last_accessed_at)
    # landed in between; this is migration #16.
    (16, "Add message_history_blob column to chief_sessions for zone4-warmth Phase 2", [
        "ALTER TABLE chief_sessions ADD COLUMN message_history_blob BLOB;",
    ]),
    # Board Phase 3 WS1 (#2392) — learning knowledge store. ``used_count``
    # counts the times the operator *acted on* a recalled memory (within the
    # recall window, RecallTracker), distinct from ``access_count`` (every
    # read) and ``salience`` (decay math). ``last_recalled_at`` records when
    # a key last surfaced in a recall result, so the "act within 5 min"
    # window can be evaluated on the next operator action.
    #
    # Both columns are additive and nullable/zero-default — pre-Phase-3 rows
    # read 0 / NULL and are unaffected. ``used_count >= 3`` boosts recall
    # rank; ``used_count == 0 AND age > 90d`` flags for consolidation review.
    (17, "Add used_count + last_recalled_at columns to knowledge for Board Phase 3 learning store", [
        "ALTER TABLE knowledge ADD COLUMN used_count INTEGER NOT NULL DEFAULT 0;",
        "ALTER TABLE knowledge ADD COLUMN last_recalled_at TEXT;",
        "CREATE INDEX IF NOT EXISTS idx_knowledge_used_count ON knowledge(used_count);",
    ]),
]


class MigrationsMixin:
    """Schema migration runner + schema-version getter."""

    # Provided by ConnectionMixin.
    def _ensure_connected(self) -> aiosqlite.Connection: ...  # type: ignore[empty-body]

    async def fetchone(
        self, sql: str, params: tuple = ()
    ) -> aiosqlite.Row | None: ...  # type: ignore[empty-body]

    # -- S36: Schema migration --

    async def migrate(self) -> None:
        """Create all tables, indexes, FTS5, and triggers (idempotent)."""
        conn = self._ensure_connected()

        for stmt in _TABLES:
            await conn.execute(stmt)

        for stmt in _FTS_AND_TRIGGERS:
            await conn.execute(stmt)

        # Rename telegram_message_id → platform_message_id (Discord migration)
        for table in ("conversations", "message_queue"):
            cols = await conn.execute_fetchall(f"PRAGMA table_info({table})")
            col_names = [row[1] for row in cols]
            if "telegram_message_id" in col_names and "platform_message_id" not in col_names:
                # `table` is a hardcoded literal from the tuple two lines above;
                # SQLite ALTER TABLE does not accept parameterized identifiers.
                # Sprint 08.03 (#781). Revisit 2026-09-01.
                # nosemgrep: python.sqlalchemy.security.sqlalchemy-execute-raw-query.sqlalchemy-execute-raw-query
                await conn.execute(
                    f"ALTER TABLE {table} RENAME COLUMN telegram_message_id TO platform_message_id"
                )

        await conn.commit()

        # Apply versioned migrations
        await self._apply_migrations()

    async def _apply_migrations(self) -> None:
        """Apply all pending versioned migrations."""
        conn = self._ensure_connected()

        # Ensure schema_version table exists
        await conn.execute(_SCHEMA_VERSION_TABLE)
        await conn.commit()

        # Get current version
        row = await conn.execute("SELECT MAX(version) FROM schema_version")
        result = await row.fetchone()
        current_version = result[0] if result and result[0] is not None else 0

        applied = 0
        for version, description, statements in _MIGRATIONS:
            if version <= current_version:
                continue
            try:
                for stmt in statements:
                    await conn.execute(stmt)
                await conn.execute(
                    "INSERT INTO schema_version (version, description) VALUES (?, ?)",
                    (version, description),
                )
                await conn.commit()
                applied += 1
                log.info("Applied migration %d: %s", version, description)
            except Exception as e:
                log.error("Migration %d failed: %s", version, e)
                raise

        if applied:
            log.info("Applied %d migration(s), now at version %d", applied, current_version + applied)

    async def get_schema_version(self) -> int:
        """Return the current schema version number."""
        self._ensure_connected()
        try:
            row = await self.fetchone("SELECT MAX(version) FROM schema_version")
            return row[0] if row and row[0] is not None else 0
        except Exception:
            return 0
