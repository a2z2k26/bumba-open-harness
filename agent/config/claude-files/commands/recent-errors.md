---
description: Show errors from the last N hours
---

Check for recent errors in both the bridge log and the audit database.

Bridge log errors:
```bash
grep -i "error\|critical\|fatal" ~/logs/bridge.log | tail -20
```

Database audit errors:
```bash
sqlite3 ~/data/memory.db "SELECT timestamp, event_type, substr(outcome, 1, 150) FROM audit_log WHERE event_type LIKE '%error%' ORDER BY timestamp DESC LIMIT 20"
```

If $ARGUMENTS is provided, use it as the number of hours to look back (default: 1 hour). Summarize: how many errors, what types, any patterns, and whether action is needed.
