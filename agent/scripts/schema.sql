-- Bumba Agent SQLite Schema
-- Database: /opt/bumba-harness/data/memory.db

-- Initialization pragmas (run on every connection open)
PRAGMA journal_mode = WAL;
PRAGMA busy_timeout = 5000;
PRAGMA synchronous = NORMAL;
PRAGMA cache_size = -64000;   -- 64MB cache
PRAGMA foreign_keys = ON;
PRAGMA temp_store = MEMORY;

-- ============================================================
-- Core knowledge store (key-value with metadata)
-- ============================================================
CREATE TABLE IF NOT EXISTS knowledge (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    tags TEXT,                          -- comma-separated tags
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    expires_at TEXT,                    -- NULL = never expires
    source TEXT NOT NULL DEFAULT 'agent'  -- 'agent', 'operator', 'system', 'hook'
);

CREATE INDEX IF NOT EXISTS idx_knowledge_tags ON knowledge(tags);
CREATE INDEX IF NOT EXISTS idx_knowledge_updated ON knowledge(updated_at);
CREATE INDEX IF NOT EXISTS idx_knowledge_source ON knowledge(source);

-- Full-text search on knowledge
CREATE VIRTUAL TABLE IF NOT EXISTS knowledge_fts USING fts5(
    key, value, tags,
    content='knowledge',
    content_rowid='rowid'
);

-- Triggers to keep FTS in sync
CREATE TRIGGER IF NOT EXISTS knowledge_ai AFTER INSERT ON knowledge BEGIN
    INSERT INTO knowledge_fts(rowid, key, value, tags)
    VALUES (new.rowid, new.key, new.value, new.tags);
END;

CREATE TRIGGER IF NOT EXISTS knowledge_ad AFTER DELETE ON knowledge BEGIN
    INSERT INTO knowledge_fts(knowledge_fts, rowid, key, value, tags)
    VALUES('delete', old.rowid, old.key, old.value, old.tags);
END;

CREATE TRIGGER IF NOT EXISTS knowledge_au AFTER UPDATE ON knowledge BEGIN
    INSERT INTO knowledge_fts(knowledge_fts, rowid, key, value, tags)
    VALUES('delete', old.rowid, old.key, old.value, old.tags);
    INSERT INTO knowledge_fts(rowid, key, value, tags)
    VALUES (new.rowid, new.key, new.value, new.tags);
END;

-- ============================================================
-- Conversation history
-- ============================================================
CREATE TABLE IF NOT EXISTS conversations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,           -- Claude Code session UUID
    chat_id TEXT NOT NULL,              -- Telegram chat ID
    role TEXT NOT NULL,                 -- 'user', 'assistant', 'system'
    content TEXT NOT NULL,
    platform_message_id INTEGER,        -- For reply threading
    tools_used TEXT,                    -- JSON array of tool names (assistant only)
    cost_usd REAL,                      -- API cost (assistant only)
    duration_ms INTEGER,                -- Response time (assistant only)
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_conversations_session ON conversations(session_id);
CREATE INDEX IF NOT EXISTS idx_conversations_chat ON conversations(chat_id);
CREATE INDEX IF NOT EXISTS idx_conversations_created ON conversations(created_at);

-- ============================================================
-- Session tracking
-- ============================================================
CREATE TABLE IF NOT EXISTS sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id TEXT NOT NULL,
    claude_session_id TEXT NOT NULL,     -- UUID for --resume
    status TEXT NOT NULL DEFAULT 'active',  -- 'active', 'expired', 'error'
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    last_active_at TEXT NOT NULL DEFAULT (datetime('now')),
    message_count INTEGER NOT NULL DEFAULT 0,
    total_cost_usd REAL NOT NULL DEFAULT 0.0,
    expired_reason TEXT                  -- 'idle_timeout', 'operator_reset', 'file_too_large', 'error'
);

CREATE INDEX IF NOT EXISTS idx_sessions_chat ON sessions(chat_id);
CREATE INDEX IF NOT EXISTS idx_sessions_status ON sessions(status);
CREATE UNIQUE INDEX IF NOT EXISTS idx_sessions_active
    ON sessions(chat_id) WHERE status = 'active';

-- ============================================================
-- Message queue (for rate limiting and crash recovery)
-- ============================================================
CREATE TABLE IF NOT EXISTS message_queue (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    platform_message_id INTEGER NOT NULL,
    chat_id TEXT NOT NULL,
    text TEXT NOT NULL,
    received_at TEXT NOT NULL DEFAULT (datetime('now')),
    status TEXT NOT NULL DEFAULT 'pending',  -- 'pending', 'processing', 'completed', 'failed', 'rate_limited', 'send_failed'
    attempt_count INTEGER NOT NULL DEFAULT 0,
    response_text TEXT,                 -- Stored response for send_failed retry
    completed_at TEXT,
    error_details TEXT                  -- JSON with error info if failed
);

CREATE INDEX IF NOT EXISTS idx_mq_status ON message_queue(status);
CREATE INDEX IF NOT EXISTS idx_mq_received ON message_queue(received_at);

-- ============================================================
-- Audit log (APPEND-ONLY)
-- ============================================================
CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL DEFAULT (datetime('now')),
    event_type TEXT NOT NULL,
    tool_name TEXT,
    arguments TEXT,                     -- JSON (truncated to 500 chars)
    outcome TEXT,                       -- 'success', 'failure', 'denied', 'timeout'
    details TEXT,                       -- JSON with full context
    session_id TEXT,
    chat_id TEXT
);

CREATE INDEX IF NOT EXISTS idx_audit_timestamp ON audit_log(timestamp);
CREATE INDEX IF NOT EXISTS idx_audit_event_type ON audit_log(event_type);
CREATE INDEX IF NOT EXISTS idx_audit_session ON audit_log(session_id);

-- Append-only enforcement triggers (PROTECTED KERNEL)
CREATE TRIGGER IF NOT EXISTS audit_no_delete
BEFORE DELETE ON audit_log
BEGIN
    SELECT RAISE(ABORT, 'Audit log entries cannot be deleted');
END;

CREATE TRIGGER IF NOT EXISTS audit_no_update
BEFORE UPDATE ON audit_log
BEGIN
    SELECT RAISE(ABORT, 'Audit log entries cannot be modified');
END;
