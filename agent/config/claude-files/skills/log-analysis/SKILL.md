---
name: log-analysis
description: How to read, search, and summarize Bumba's bridge and session logs. Use when investigating issues, answering questions about recent activity, or doing periodic reviews.
---

# Log Analysis

## When to Use
- Operator asks "what happened?" or "any errors?"
- Investigating slow responses or failures
- Periodic health review
- After a restart or recovery

## Log Locations

| Log | Path | Contains |
|-----|------|----------|
| Bridge | `~/logs/bridge.log` | Telegram polling, message processing, errors, restarts |
| Burn-in | `~/logs/burn-in.log` | Periodic health snapshots during burn-in |

## Analysis Patterns

### Recent Errors
```bash
grep -i "error\|critical\|fatal\|warning" ~/logs/bridge.log | tail -20
```

### Errors in Last Hour
```bash
# Get entries from the last hour (approximate by checking timestamps)
grep "$(date -u '+%Y-%m-%d %H')" ~/logs/bridge.log | grep -i "error\|critical"
```

### Message Processing
```bash
# Count Claude invocations
grep "Claude exit=" ~/logs/bridge.log | tail -20
```

### Rate Limiting
```bash
grep -i "rate.limit\|429\|backoff\|retry" ~/logs/bridge.log | tail -10
```

### Token Issues
```bash
grep -i "token\|oauth\|login\|auth" ~/logs/bridge.log | tail -10
```

### Crash/Restart History
```bash
grep -i "fatal\|crash\|restart\|exit\|starting bridge" ~/logs/bridge.log
```

## Summarization Approach

When summarizing logs:
1. Count total errors, warnings, and info-level events
2. Identify patterns (repeated errors, time clusters)
3. Note the time range covered
4. Highlight anything actionable
5. Keep the summary to 5-10 lines

## Output Format

```
Log Summary (last [timeframe])
==============================
Period: [start] to [end]
Errors: [count] ([types])
Warnings: [count]
Messages processed: [count]
Notable: [any patterns or concerns]
Status: [healthy / needs attention / critical]
```
