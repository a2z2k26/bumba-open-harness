---
description: Export the knowledge table to a CSV backup
---

Export all knowledge entries to a timestamped CSV file:

```bash
sqlite3 -header -csv ~/data/memory.db "SELECT key, value, tags, source, created_at, updated_at, expires_at FROM knowledge ORDER BY key" > /tmp/knowledge-backup-$(date +%Y%m%d).csv
```

Report the file path, number of entries exported, and file size. Also show a summary of entries by key prefix:

```bash
sqlite3 ~/data/memory.db "SELECT substr(key, 1, instr(key || ':', ':')) as prefix, COUNT(*) FROM knowledge GROUP BY prefix ORDER BY COUNT(*) DESC"
```
