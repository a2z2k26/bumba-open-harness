---
name: knowledge-maintenance
description: How to maintain and organize Bumba's knowledge base. Use periodically or when the database is growing large.
---

# Knowledge Maintenance

## When to Use
- Database size exceeds 500 MB
- Knowledge entries exceed 500
- Periodic maintenance (weekly)
- Operator asks to clean up or organize knowledge

## Maintenance Tasks

### 1. Remove Expired Entries
```bash
sqlite3 ~/data/memory.db "SELECT COUNT(*) FROM knowledge WHERE expires_at IS NOT NULL AND expires_at < datetime('now')"
sqlite3 ~/data/memory.db "DELETE FROM knowledge WHERE expires_at IS NOT NULL AND expires_at < datetime('now')"
```

### 2. Trim Old Session Summaries (keep last 30)
```bash
sqlite3 ~/data/memory.db "SELECT COUNT(*) FROM knowledge WHERE key LIKE 'session:summary:%'"
sqlite3 ~/data/memory.db "DELETE FROM knowledge WHERE key LIKE 'session:summary:%' AND key NOT IN (SELECT key FROM knowledge WHERE key LIKE 'session:summary:%' ORDER BY updated_at DESC LIMIT 30)"
```

### 3. Find and Remove Duplicates
```bash
sqlite3 ~/data/memory.db "SELECT key, COUNT(*) as c FROM knowledge GROUP BY key HAVING c > 1"
```

### 4. Review Stale Handoffs
```bash
sqlite3 ~/data/memory.db "SELECT key, substr(value, 1, 100), updated_at FROM knowledge WHERE key LIKE 'handoff:%' ORDER BY updated_at"
```
Delete handoffs older than 7 days that are no longer relevant.

### 5. Clean Old Audit Log
```bash
sqlite3 ~/data/memory.db "SELECT COUNT(*) FROM audit_log WHERE timestamp < datetime('now', '-30 days')"
sqlite3 ~/data/memory.db "DELETE FROM audit_log WHERE timestamp < datetime('now', '-30 days')"
```

### 6. WAL Checkpoint and Vacuum
```bash
sqlite3 ~/data/memory.db "PRAGMA wal_checkpoint(TRUNCATE)"
sqlite3 ~/data/memory.db "VACUUM"
```

### 7. Check Database Size
```bash
ls -lh ~/data/memory.db ~/data/memory.db-wal 2>/dev/null
```

## Knowledge Inventory
```bash
sqlite3 ~/data/memory.db "SELECT substr(key, 1, instr(key || ':', ':')) as prefix, COUNT(*) as count FROM knowledge GROUP BY prefix ORDER BY count DESC"
```

## Salience Review

The bridge runs automatic salience decay. Review salience health:
```bash
# Entries with lowest salience (candidates for auto-archive)
sqlite3 ~/data/memory.db "SELECT key, salience, access_count, accessed_at FROM knowledge WHERE archived IS NULL OR archived = 0 ORDER BY salience ASC LIMIT 15"

# High-salience entries (most accessed/important)
sqlite3 ~/data/memory.db "SELECT key, salience, access_count FROM knowledge WHERE salience >= 3.0 ORDER BY salience DESC LIMIT 10"

# Entries auto-archived by decay (can be restored if needed)
sqlite3 ~/data/memory.db "SELECT key, salience, accessed_at FROM knowledge WHERE archived = 1 AND salience < 0.1 ORDER BY accessed_at DESC LIMIT 10"

# Restore a wrongly-archived entry
sqlite3 ~/data/memory.db "UPDATE knowledge SET archived = 0, salience = 1.0 WHERE key = 'the-key'"
```

Decay rates: operator/preference/person entries are exempt. Project/decision/process decay at 0.99/day. Learning/tool/reference at 0.98/day. Session summaries at 0.95/day.

## Quality Review

Periodically check that knowledge entries are still accurate:
```bash
# Oldest entries — may be outdated
sqlite3 ~/data/memory.db "SELECT key, substr(value, 1, 80), updated_at FROM knowledge ORDER BY updated_at ASC LIMIT 10"

# Entries without tags
sqlite3 ~/data/memory.db "SELECT key FROM knowledge WHERE tags = '' OR tags IS NULL"
```

## Maintenance Report Format
```
Knowledge Maintenance Report
============================
Total entries: [count]
Expired removed: [count]
Old summaries trimmed: [count]
Stale handoffs: [count]
Audit log trimmed: [count]
DB size: [before] → [after]
```
