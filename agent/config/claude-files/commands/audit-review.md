---
description: Review recent audit log entries
---

Query the audit log for recent events:

```bash
sqlite3 -header ~/data/memory.db "SELECT timestamp, event_type, tool_name, substr(outcome, 1, 100) FROM audit_log ORDER BY timestamp DESC LIMIT 20"
```

If $ARGUMENTS is provided, filter by event type:
```bash
sqlite3 -header ~/data/memory.db "SELECT timestamp, event_type, tool_name, substr(outcome, 1, 100) FROM audit_log WHERE event_type LIKE '%$ARGUMENTS%' ORDER BY timestamp DESC LIMIT 20"
```

Summarize: total events, types breakdown, any anomalies or patterns worth noting.
