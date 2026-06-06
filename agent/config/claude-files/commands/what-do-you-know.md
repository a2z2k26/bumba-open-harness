---
description: Summarize everything known about a topic
---

Compile everything stored in the knowledge base about the given topic. Search using both FTS and pattern matching:

```bash
sqlite3 ~/data/memory.db "SELECT key, value, updated_at FROM knowledge WHERE key IN (SELECT key FROM knowledge_fts WHERE knowledge_fts MATCH '$ARGUMENTS') ORDER BY updated_at DESC"
```

```bash
sqlite3 ~/data/memory.db "SELECT key, value, updated_at FROM knowledge WHERE key LIKE '%$ARGUMENTS%' OR value LIKE '%$ARGUMENTS%' ORDER BY updated_at DESC"
```

Combine all results into a coherent summary. Group by type (decisions, user preferences, context, session summaries). Note when each piece was last updated. If nothing is found, say so clearly.
