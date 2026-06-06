---
description: Search the knowledge base by topic
---

Search the knowledge base for entries related to the query. Use both full-text search and key prefix matching:

```bash
sqlite3 ~/data/memory.db "SELECT key, substr(value, 1, 200), updated_at FROM knowledge WHERE key IN (SELECT key FROM knowledge_fts WHERE knowledge_fts MATCH '$ARGUMENTS') ORDER BY updated_at DESC LIMIT 10"
```

Also check by key prefix:
```bash
sqlite3 ~/data/memory.db "SELECT key, substr(value, 1, 200), updated_at FROM knowledge WHERE key LIKE '%$ARGUMENTS%' OR value LIKE '%$ARGUMENTS%' ORDER BY updated_at DESC LIMIT 10"
```

Present results clearly with the key, a summary of the value, and when it was last updated. If no results found, say so.
