---
description: Show session statistics
---

Query the database for session and conversation statistics:

```bash
sqlite3 -header ~/data/memory.db "
SELECT
  COUNT(*) as total_sessions,
  SUM(CASE WHEN status='active' THEN 1 ELSE 0 END) as active,
  SUM(CASE WHEN status='expired' THEN 1 ELSE 0 END) as expired,
  SUM(message_count) as total_messages,
  ROUND(AVG(message_count), 1) as avg_msgs_per_session
FROM sessions"
```

```bash
sqlite3 -header ~/data/memory.db "
SELECT
  date(created_at) as day,
  COUNT(*) as messages,
  COUNT(DISTINCT session_id) as sessions
FROM conversations
GROUP BY day
ORDER BY day DESC
LIMIT 7"
```

Present as a clear summary with total sessions, messages, average session length, and daily breakdown.
