---
description: Check disk usage across all Bumba directories
---

Check disk usage for all Bumba directories:

```bash
du -sh ~/data ~/logs ~/agent ~/.claude 2>/dev/null
```

```bash
df -h /opt/bumba-harness 2>/dev/null | tail -1
```

```bash
ls -lh ~/data/memory.db ~/data/memory.db-wal 2>/dev/null
```

Report total usage, available space, and database size. Flag if any directory exceeds expected sizes (data >100MB, logs >50MB, database >500MB).
