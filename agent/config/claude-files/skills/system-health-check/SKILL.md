---
name: system-health-check
description: Comprehensive system health diagnostics for Bumba. Use when asked about system health, when troubleshooting, or proactively when something seems wrong.
---

# System Health Check

## When to Use
- Operator asks about system health or status
- Something seems slow or broken
- After a restart or recovery
- Proactively when anomalies are detected

## Diagnostic Steps

### 1. Bridge Process
```bash
PID=$(cat ~/data/bridge.pid 2>/dev/null)
if [ -n "$PID" ] && ps -p "$PID" > /dev/null 2>&1; then
    ps -p "$PID" -o pid,rss,%cpu,etime
else
    echo "Bridge NOT RUNNING"
fi
```

### 2. Heartbeat
```bash
cat ~/data/heartbeat 2>/dev/null || echo "No heartbeat file"
```
Heartbeat should be <90 seconds old.

### 3. Halt Flag
```bash
cat ~/data/halt 2>/dev/null || echo "No halt"
```

### 4. Resources
```bash
# Memory and CPU
ps -o rss=,%cpu= -p "$(cat ~/data/bridge.pid 2>/dev/null)" 2>/dev/null

# Disk
du -sh ~/data ~/logs 2>/dev/null
```

### 5. Database
```bash
# Size
ls -lh ~/data/memory.db ~/data/memory.db-wal 2>/dev/null

# Message count
sqlite3 ~/data/memory.db "SELECT COUNT(*) as total_messages FROM conversations"

# Queue depth
sqlite3 ~/data/memory.db "SELECT COUNT(*) as pending FROM message_queue WHERE status='pending'"

# Recent errors
sqlite3 ~/data/memory.db "SELECT COUNT(*) as errors_1h FROM audit_log WHERE event_type LIKE '%error%' AND timestamp > datetime('now', '-1 hour')"
```

### 6. Recent Errors
```bash
grep -i "error\|warning\|critical" ~/logs/bridge.log 2>/dev/null | tail -5
```

### 7. Token Status
```bash
grep -c "claude_oauth_token=" ~/data/.secrets 2>/dev/null && echo "Token present" || echo "Token MISSING"
```

## Report Format

Present findings as a structured report:

```
System Health Report
====================
Bridge: [RUNNING/STOPPED] (PID, uptime)
Heartbeat: [FRESH/STALE] (age)
Resources: [RSS] MB RAM, [CPU]% CPU
Disk: data [size], logs [size]
Database: [size], [count] messages, [count] errors (1h)
Queue: [count] pending
Token: [PRESENT/MISSING]
Alerts: [list any concerns]
Recommendation: [action needed or "all clear"]
```

## Alert Thresholds

| Condition | Action |
|-----------|--------|
| Memory >500MB | Recommend restart to operator |
| Errors >10 in last hour | Investigate logs, report patterns |
| Heartbeat >120s stale | Bridge may be hung — alert operator |
| Database >1GB | Run cleanup: `bash ~/.claude/scripts/cleanup-claude-dir.sh --execute` |
| Token missing | Critical — notify operator immediately |
| Queue >50 pending | Check for rate limiting or processing issues |
