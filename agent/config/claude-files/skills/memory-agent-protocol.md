# Memory Agent Protocol

How to interact with Bumba's SQLite memory system. This protocol covers reading, writing, and searching the knowledge base that persists across sessions.

## Database Location

```
/opt/bumba-harness/data/memory.db
```

Access via: `sqlite3 ~/data/memory.db "<SQL>"`

## Tables

| Table | Purpose |
|-------|---------|
| **knowledge** | Long-term facts, decisions, preferences (has FTS5 index) |
| **conversations** | Chat history per session |
| **sessions** | Claude Code session metadata |
| **message_queue** | Telegram message queue |
| **audit_log** | Immutable event log (append-only) |

## Knowledge Table Schema

```sql
CREATE TABLE knowledge (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL,
  tags TEXT DEFAULT '',
  source TEXT DEFAULT 'agent',  -- 'operator' or 'agent'
  created_at TEXT DEFAULT (datetime('now')),
  updated_at TEXT DEFAULT (datetime('now')),
  expires_at TEXT DEFAULT NULL
);
```

## Key Prefix Conventions

| Prefix | Purpose | Example |
|--------|---------|---------|
| `user:` | Operator preferences, facts | `user:timezone`, `user:preferences` |
| `decision:` | Decisions with rationale | `decision:use-sqlite-fts5` |
| `decision:self-improvement:` | Agent evolution decisions | `decision:self-improvement:log-summarizer` |
| `session:summary:` | Session summaries | `session:summary:abc123` |
| `context:` | Shared project state | `context:current-phase` |
| `handoff:` | Incomplete work for next session | `handoff:feature-monitoring` |

## Core Operations

### Store Knowledge
```bash
sqlite3 ~/data/memory.db "INSERT OR REPLACE INTO knowledge (key, value, tags, source, updated_at) VALUES ('decision:use-fts5', 'Chose FTS5 for full-text search because it integrates natively with SQLite', 'architecture,search', 'agent', datetime('now'))"
```

### Search Knowledge (FTS5)
```bash
sqlite3 ~/data/memory.db "SELECT key, value FROM knowledge WHERE key IN (SELECT key FROM knowledge_fts WHERE knowledge_fts MATCH 'search query') ORDER BY updated_at DESC LIMIT 5"
```

### Search by Key Prefix
```bash
sqlite3 ~/data/memory.db "SELECT key, value FROM knowledge WHERE key LIKE 'decision:%' ORDER BY updated_at DESC LIMIT 10"
```

### Read Specific Key
```bash
sqlite3 ~/data/memory.db "SELECT value FROM knowledge WHERE key = 'user:timezone'"
```

### Delete Expired Knowledge
```bash
sqlite3 ~/data/memory.db "DELETE FROM knowledge WHERE expires_at IS NOT NULL AND expires_at < datetime('now')"
```

## Session Lifecycle

### On Session Start (handled by hook)
The `memory-session-start.sh` hook automatically:
1. Loads recent decisions, user facts, last session summary
2. Checks kernel integrity (file hash baseline)
3. Injects context via `--append-system-prompt-file`

You don't need to manually load context — it arrives in your system prompt.

### During Work
Store important discoveries as you go:
- Decisions: `decision:{topic}` — what was decided and why
- User facts: `user:{topic}` — operator preferences and corrections
- Progress: `context:{topic}` — current state of ongoing work

### On Session Stop (handled by hook)
The `memory-session-stop.sh` hook prompts you to persist:
- Session summary → `session:summary:{session_id}`
- Any decisions made → `decision:{topic}`
- User preferences learned → `user:{topic}`

## Search Before Create

Before storing new knowledge, check if it already exists:
```bash
sqlite3 ~/data/memory.db "SELECT key, value FROM knowledge WHERE key LIKE '%topic%' OR value LIKE '%topic%' LIMIT 5"
```

This prevents duplicate or contradictory entries.

## Context Assembly

The bridge automatically assembles context for each session from:
1. Last 3 session summaries
2. Last 20 conversation messages
3. Top 10 relevant knowledge entries (by recency)
4. Maximum ~12,000 characters (4000 tokens)

This context is injected before your first response in each session.
