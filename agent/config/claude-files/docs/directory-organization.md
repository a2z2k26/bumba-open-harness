# Directory Organization Audit

This document provides an audit of your `.claude` directory structure with recommendations for cleanup and organization.

## Directory Size Analysis

Based on current disk usage:

| Directory | Size | Status | Recommendation |
|-----------|------|--------|----------------|
| `debug/` | 288 MB | 🟡 Large | Review and archive old debug files |
| `projects/` | 276 MB | ✅ Expected | Project configs - keep |
| `shell-snapshots/` | 63 MB | 🟡 Large | Archive old snapshots |
| `plugins/` | 53 MB | ✅ Expected | Plugin code - keep |
| `file-history/` | 27 MB | 🟡 Large | Consider retention policy |
| `templates/` | 7 MB | ✅ Expected | Code templates - keep |
| `todos/` | 3.1 MB | ✅ Expected | Active todos - keep |
| `history.jsonl` | 2.1 MB | ✅ Expected | Session history - keep |
| `skills/` | 1.6 MB | ✅ Expected | Knowledge modules - keep |
| `commands/` | 1.1 MB | ✅ Expected | Slash commands - keep |
| `paste-cache/` | 668 KB | 🟢 Small | Temporary cache - OK |
| `agents/` | 488 KB | ✅ Expected | Agent definitions - keep |
| `shared-modules/` | 452 KB | ✅ Expected | Shared code - keep |
| `scripts/` | 304 KB | ✅ Expected | Utility scripts - keep |
| `docs/` | 280 KB | ✅ NEW | Documentation - keep |
| `hooks/` | 244 KB | ✅ Expected | Event hooks - keep |
| `plans/` | 212 KB | ✅ Expected | Planning docs - keep |
| `wrappers/` | 156 KB | ✅ Expected | Wrapper scripts - keep |
| `instructions/` | 76 KB | ✅ Expected | Global instructions - keep |
| `cache/` | 72 KB | 🟢 Small | Temporary cache - OK |

**Total Size**: ~720 MB

## Cleanup Recommendations

### High Priority (Could Save ~300MB)

#### 1. Debug Directory (288 MB)
**Current State**: Contains debug output from sessions
**Recommendation**:
```bash
# Review debug files older than 30 days
find ~/.claude/debug -type f -mtime +30 -ls

# Archive to compressed backup
tar -czf ~/.claude/archive/debug-$(date +%Y%m).tar.gz ~/.claude/debug/*
find ~/.claude/debug -type f -mtime +30 -delete

# Keep only last 30 days
```

**Expected Savings**: 200-250 MB

#### 2. Shell Snapshots (63 MB)
**Current State**: 803 shell snapshot files
**Recommendation**:
```bash
# Archive snapshots older than 60 days
find ~/.claude/shell-snapshots -type f -mtime +60 -ls
tar -czf ~/.claude/archive/snapshots-$(date +%Y%m).tar.gz \
  $(find ~/.claude/shell-snapshots -type f -mtime +60)
find ~/.claude/shell-snapshots -type f -mtime +60 -delete
```

**Expected Savings**: 40-50 MB

#### 3. File History (27 MB)
**Current State**: 95 file history entries
**Recommendation**:
```bash
# Archive history older than 90 days
find ~/.claude/file-history -type f -mtime +90 -ls
tar -czf ~/.claude/archive/history-$(date +%Y%m).tar.gz \
  $(find ~/.claude/file-history -type f -mtime +90)
find ~/.claude/file-history -type f -mtime +90 -delete
```

**Expected Savings**: 15-20 MB

### Medium Priority

#### 4. Plugin Backups
**Current State**: `design-explorer-BACKUP-20260111-131227/` exists
**Recommendation**:
```bash
# Verify new implementation works, then remove backup
# Only if you're confident new version is stable
rm -rf ~/.claude/plugins/design-explorer-BACKUP-20260111-131227/
```

**Expected Savings**: 5-10 MB

#### 5. Paste Cache
**Current State**: 32 paste cache entries
**Recommendation**:
```bash
# Clear paste cache older than 7 days
find ~/.claude/paste-cache -type f -mtime +7 -delete
```

**Expected Savings**: 300-400 KB

### Low Priority (Maintenance)

#### 6. Old Plan Files
**Recommendation**:
```bash
# Review and archive old plan files
ls -lt ~/.claude/plans/ | tail -20
# Archive if needed
```

#### 7. Session Environment Files
**Recommendation**:
```bash
# Clean up stale session environment files
find ~/.claude/session-env -type f -mtime +7 -delete
```

## Organizational Improvements

### 1. Create Archive Directory
Store old files in compressed archives:

```bash
mkdir -p ~/.claude/archive
# Structure:
# archive/
# ├── debug-202601.tar.gz
# ├── snapshots-202601.tar.gz
# └── history-202601.tar.gz
```

### 2. Add .gitignore Patterns
If your `.claude` directory is version controlled:

```gitignore
# Temporary files
debug/
shell-snapshots/
file-history/
paste-cache/
session-env/
cache/
todos/

# Large binaries
archive/

# Keep configuration and features
!agents/
!commands/
!skills/
!hooks/
!plugins/
!config/
!templates/
!instructions/
!rules/
!docs/
```

### 3. Organize Plugins
Current state shows some organization but could be improved:

**Suggested Structure**:
```
plugins/
├── bumba-design-sync/          # Keep
├── bumba-frontend-design/      # Keep
├── bumba-nlp-design/           # Keep
├── design-explorer-ui/         # Keep
├── design-explorer-ux/         # Keep
├── e2b-design-orchestrator/    # Keep
├── frontend-design/            # Keep
└── archive/                    # NEW - for deprecated plugins
    └── design-explorer-BACKUP-20260111-131227/  # Move here
```

### 4. Consolidate Documentation
Great start with the new `docs/` directory! Consider adding:

```
docs/
├── README.md                    # ✅ Created
├── inventory-agents.md          # ✅ Created
├── inventory-commands.md        # ✅ Created
├── inventory-skills.md          # ✅ Created
├── inventory-hooks.md           # ✅ Created
├── inventory-plugins.md         # ✅ Created
├── directory-organization.md    # ✅ This file
├── workflows/                   # NEW - Workflow documentation
│   ├── design-to-code.md       # Design Bridge workflow
│   ├── github-workflow.md      # GitHub automation workflow
│   └── e2b-orchestration.md    # E2B sandbox workflow
└── guides/                      # NEW - How-to guides
    ├── getting-started.md
    ├── creating-agents.md
    ├── creating-commands.md
    └── creating-plugins.md
```

## Directory Purpose Reference

### Core Directories (Keep)
- **agents/**: Specialized AI agent definitions
- **commands/**: Slash command implementations
- **skills/**: Reusable knowledge modules
- **hooks/**: Event-driven automation scripts
- **plugins/**: Feature bundles (commands + agents + skills + hooks)
- **config/**: Configuration files
- **templates/**: Code and file templates
- **scripts/**: Utility scripts
- **instructions/**: Global instructions and rules
- **rules/**: Complexity assessment and decision frameworks
- **docs/**: Feature documentation (NEW)

### Project Directories (Keep)
- **projects/**: Project-specific configurations and state

### Temporary/Cache Directories (Clean Periodically)
- **debug/**: Debug output and logs
- **shell-snapshots/**: Command history snapshots
- **file-history/**: File modification history
- **session-env/**: Session environment variables
- **paste-cache/**: Clipboard cache
- **cache/**: General cache files
- **todos/**: Todo list state

### Planning Directories (Archive Old Files)
- **plans/**: Planning documents from plan mode

### Support Directories (Keep)
- **shared-modules/**: Shared JavaScript modules
- **wrappers/**: Wrapper scripts for tools
- **tests/**: Test files and test harnesses

### Special Directories
- **.claude/**: Plugin metadata (hidden from main list)
- **apps/**: Application integrations
- **assets/**: Static assets
- **logs/**: Log files
- **output-styles/**: Output formatting styles
- **statsig/**: Analytics and feature flags
- **team/**: Team collaboration files
- **telemetry/**: Usage telemetry

## Cleanup Script

Here's a safe cleanup script you can run:

```bash
#!/bin/bash
# Claude Code Directory Cleanup
# Run from: ~/.claude/

echo "Claude Code Directory Cleanup"
echo "============================="
echo

# Create archive directory
mkdir -p archive

# 1. Debug files (older than 30 days)
echo "Archiving debug files older than 30 days..."
find debug -type f -mtime +30 2>/dev/null | wc -l
if [ $(find debug -type f -mtime +30 2>/dev/null | wc -l) -gt 0 ]; then
  tar -czf archive/debug-$(date +%Y%m).tar.gz $(find debug -type f -mtime +30) 2>/dev/null
  find debug -type f -mtime +30 -delete 2>/dev/null
  echo "✓ Debug files archived"
else
  echo "✓ No old debug files to archive"
fi

# 2. Shell snapshots (older than 60 days)
echo "Archiving shell snapshots older than 60 days..."
if [ $(find shell-snapshots -type f -mtime +60 2>/dev/null | wc -l) -gt 0 ]; then
  tar -czf archive/snapshots-$(date +%Y%m).tar.gz $(find shell-snapshots -type f -mtime +60) 2>/dev/null
  find shell-snapshots -type f -mtime +60 -delete 2>/dev/null
  echo "✓ Snapshots archived"
else
  echo "✓ No old snapshots to archive"
fi

# 3. File history (older than 90 days)
echo "Archiving file history older than 90 days..."
if [ $(find file-history -type f -mtime +90 2>/dev/null | wc -l) -gt 0 ]; then
  tar -czf archive/history-$(date +%Y%m).tar.gz $(find file-history -type f -mtime +90) 2>/dev/null
  find file-history -type f -mtime +90 -delete 2>/dev/null
  echo "✓ File history archived"
else
  echo "✓ No old file history to archive"
fi

# 4. Paste cache (older than 7 days)
echo "Cleaning paste cache older than 7 days..."
find paste-cache -type f -mtime +7 -delete 2>/dev/null
echo "✓ Paste cache cleaned"

# 5. Session environment (older than 7 days)
echo "Cleaning session environment files older than 7 days..."
find session-env -type f -mtime +7 -delete 2>/dev/null
echo "✓ Session environment cleaned"

echo
echo "Cleanup complete!"
echo "Check archive/ directory for backups"
du -sh archive/
```

## Retention Policy Recommendation

Establish retention policies for temporary files:

| Directory | Retention | Archive | Reason |
|-----------|-----------|---------|--------|
| debug/ | 30 days | Yes | Debug info becomes stale quickly |
| shell-snapshots/ | 60 days | Yes | Command history less useful over time |
| file-history/ | 90 days | Yes | Recent changes most relevant |
| paste-cache/ | 7 days | No | Very temporary |
| session-env/ | 7 days | No | Session-specific only |
| todos/ | Keep all | No | Active task management |
| plans/ | Keep all | Optional | May reference old plans |

## Automated Maintenance

Consider setting up a cron job or adding to your shell profile:

```bash
# Add to ~/.zshrc or ~/.bashrc
# Weekly cleanup (runs once per week)
if [ ! -f ~/.claude/.last_cleanup ] || [ $(find ~/.claude/.last_cleanup -mtime +7) ]; then
  (cd ~/.claude && bash cleanup.sh > /dev/null 2>&1) &
  touch ~/.claude/.last_cleanup
fi
```

## Summary

### Immediate Actions
1. ✅ Create `docs/` directory with inventories (DONE)
2. 🔲 Create `archive/` directory
3. 🔲 Run cleanup script to archive old files
4. 🔲 Move plugin backup to archive

### Regular Maintenance
1. Monthly: Review and archive debug files
2. Monthly: Review and archive shell snapshots
3. Quarterly: Review and archive file history
4. Weekly: Clear paste cache

### Future Enhancements
1. Add workflow documentation
2. Create how-to guides
3. Set up automated cleanup
4. Establish retention policies

---

**Last Updated**: 2026-01-15
**Potential Space Savings**: ~300 MB
**Organization Status**: Good foundation, room for improvement
