#!/bin/bash
# /opt/bumba-harness/agent/scripts/maintenance.sh
# Daily maintenance: backup, log rotation, WAL checkpoint, session cleanup
# Run by launchd at 03:00 via com.bumba.agent-maintenance plist
set -euo pipefail

DATA_DIR="/opt/bumba-harness/data"
BACKUP_DIR="/opt/bumba-harness/backups"
LOG_DIR="/opt/bumba-harness/logs"
CLAUDE_DIR="/opt/bumba-harness/.claude"

echo "=== Bumba Agent Maintenance -- $(date -Iseconds) ==="

# 1. SQLite backup
echo "[1/8] SQLite backup..."
if [ -f "$DATA_DIR/memory.db" ]; then
    sqlite3 "$DATA_DIR/memory.db" ".backup $BACKUP_DIR/memory-$(date +%Y%m%d).db"
    echo "  Backup created: memory-$(date +%Y%m%d).db"
else
    echo "  WARNING: $DATA_DIR/memory.db not found"
fi

# 2. Remove backups older than 30 days
echo "[2/8] Cleaning old backups..."
count=$(find "$BACKUP_DIR" -name "memory-*.db" -mtime +30 2>/dev/null | wc -l | tr -d ' ')
find "$BACKUP_DIR" -name "memory-*.db" -mtime +30 -delete 2>/dev/null || true
echo "  Removed $count old backups"

# 3. WAL checkpoint
echo "[3/8] WAL checkpoint..."
if [ -f "$DATA_DIR/memory.db" ]; then
    sqlite3 "$DATA_DIR/memory.db" "PRAGMA wal_checkpoint(TRUNCATE);"
    echo "  WAL checkpoint complete"
fi

# 4. Rotate bridge logs (>10MB)
echo "[4/8] Rotating bridge logs..."
for logfile in bridge-stdout.log bridge-stderr.log; do
    if [ -f "$LOG_DIR/$logfile" ]; then
        size=$(stat -f%z "$LOG_DIR/$logfile" 2>/dev/null || echo 0)
        if [ "$size" -gt 10485760 ]; then
            mv "$LOG_DIR/$logfile" "$LOG_DIR/$logfile.$(date +%Y%m%d)"
            gzip "$LOG_DIR/$logfile.$(date +%Y%m%d)"
            echo "  Rotated $logfile ($size bytes)"
        fi
    fi
done

# 5. Remove gzipped logs older than 28 days
echo "[5/8] Cleaning old log archives..."
find "$LOG_DIR" -name "*.gz" -mtime +28 -delete 2>/dev/null || true

# 6. Rotate audit JSONL (>50MB)
echo "[6/8] Rotating audit log..."
if [ -f "$LOG_DIR/audit.jsonl" ]; then
    size=$(stat -f%z "$LOG_DIR/audit.jsonl" 2>/dev/null || echo 0)
    if [ "$size" -gt 52428800 ]; then
        mv "$LOG_DIR/audit.jsonl" "$LOG_DIR/audit-$(date +%Y%m%d).jsonl"
        gzip "$LOG_DIR/audit-$(date +%Y%m%d).jsonl"
        touch "$LOG_DIR/audit.jsonl"
        # Restore append-only ACL
        chmod +a "bumba-agent allow append" "$LOG_DIR/audit.jsonl" 2>/dev/null || true
        echo "  Rotated audit.jsonl ($size bytes)"
    fi
fi

# Remove archived audit logs older than 365 days
find "$LOG_DIR" -name "audit-*.jsonl.gz" -mtime +365 -delete 2>/dev/null || true

# 7. Clean old Claude Code session files (>30 days)
echo "[7/8] Cleaning old session files..."
if [ -d "$CLAUDE_DIR/projects/" ]; then
    count=$(find "$CLAUDE_DIR/projects/" -name "*.jsonl" -mtime +30 2>/dev/null | wc -l | tr -d ' ')
    find "$CLAUDE_DIR/projects/" -name "*.jsonl" -mtime +30 -delete 2>/dev/null || true
    echo "  Removed $count old session files"
fi

# Git gc on ~/.claude (if it's a git repo)
if [ -d "$CLAUDE_DIR/.git" ]; then
    cd "$CLAUDE_DIR" && git gc --quiet 2>/dev/null || true
    echo "  Git gc complete"
fi

# 8. Report disk usage
echo "[8/8] Disk usage report:"
echo "  Data:    $(du -sh "$DATA_DIR" 2>/dev/null | cut -f1)"
echo "  Backups: $(du -sh "$BACKUP_DIR" 2>/dev/null | cut -f1)"
echo "  Logs:    $(du -sh "$LOG_DIR" 2>/dev/null | cut -f1)"
echo "  Claude:  $(du -sh "$CLAUDE_DIR" 2>/dev/null | cut -f1)"

echo "=== Maintenance complete -- $(date -Iseconds) ==="
