---
description: Run the maintenance cleanup and report results
---

Run the Bumba maintenance cleanup script and report the results:

```bash
bash ~/.claude/scripts/cleanup-claude-dir.sh --execute
```

After running, verify the results:
```bash
ls -lh ~/data/memory.db ~/data/memory.db-wal 2>/dev/null
du -sh ~/data ~/logs 2>/dev/null
```

Report what was cleaned, before/after sizes, and any issues encountered. If $ARGUMENTS contains "dry-run" or "check", run without --execute to preview what would be cleaned.
