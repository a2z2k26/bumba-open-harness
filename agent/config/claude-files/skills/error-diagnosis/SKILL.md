---
name: error-diagnosis
description: Common error patterns in Bumba and how to diagnose and resolve them. Reference this when encountering errors or when the operator reports issues.
---

# Error Diagnosis

## When to Use
- An error appears in logs or responses
- The operator reports something isn't working
- System health check shows anomalies

## Common Error Patterns

### "Telegram token is missing"
**Cause:** Bridge can't read credentials from .secrets file
**Check:** `grep -c "telegram_token=" ~/data/.secrets`
**Fix:** Operator needs to verify .secrets file contents. This is a kernel issue — report it, don't attempt to fix.

### "Not logged in · Please run /login"
**Cause:** Claude OAuth token has expired or is invalid
**Check:** `grep -c "claude_oauth_token=" ~/data/.secrets`
**Fix:** Operator needs to run `claude setup-token` and redeploy the token. Report immediately — the agent can't process messages without a valid token.

### Rate Limiting (429 / backoff)
**Cause:** Too many Claude API calls in a short period
**Check:** `grep -i "rate.limit\|429\|backoff" ~/logs/bridge.log | tail -5`
**Diagnosis:** Normal during high traffic. The bridge has automatic exponential backoff. Only escalate if backoff exceeds 30 minutes.

### Crash Loop (repeated restarts)
**Cause:** Bridge crashes repeatedly, launchd restarts it
**Check:** `grep -i "fatal\|starting bridge" ~/logs/bridge.log | tail -10`
**Diagnosis:** Look for the CRITICAL/FATAL error just before each restart. Common causes: bad config, missing secrets, database corruption.

### Session Timeout
**Cause:** Claude session expired due to inactivity (>30 min idle)
**Check:** `sqlite3 ~/data/memory.db "SELECT * FROM sessions WHERE status='expired' ORDER BY last_active_at DESC LIMIT 3"`
**Diagnosis:** Normal behavior. A new session starts automatically on the next message.

### Database Locked
**Cause:** Multiple processes trying to write to SQLite simultaneously
**Check:** `ls -la ~/data/memory.db-wal ~/data/memory.db-shm`
**Fix:** Usually resolves itself. If persistent: `sqlite3 ~/data/memory.db "PRAGMA wal_checkpoint(TRUNCATE)"`

### Kernel Integrity Alert
**Cause:** Session-start hook detected file hash mismatch
**Check:** `cat ~/data/halt 2>/dev/null`
**Fix:** This is a security alert. Report to operator immediately. Do NOT attempt to clear the halt flag.

## Diagnosis Workflow

1. **Identify**: What error? When? How often?
2. **Check logs**: `grep` for the error in bridge.log
3. **Check database**: Query audit_log for error events
4. **Assess severity**: Is it blocking? Recurring? Self-resolving?
5. **Report**: Tell the operator what you found and recommend action
6. **Store**: If it's a new pattern, record it in knowledge:
   ```bash
   sqlite3 ~/data/memory.db "INSERT OR REPLACE INTO knowledge (key, value, source, updated_at) VALUES ('decision:error-pattern:description', 'Error X caused by Y, fixed by Z', 'agent', datetime('now'))"
   ```
