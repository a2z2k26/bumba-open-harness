#!/bin/bash
# Bumba Maintenance Cleanup Script
# Cleans logs, expired knowledge, old session data, and temp files

HOME_DIR="/opt/bumba-harness"
DATA_DIR="$HOME_DIR/data"
LOG_DIR="$HOME_DIR/logs"
DB="$DATA_DIR/memory.db"

echo "=== Bumba Maintenance Cleanup ==="
echo "Time: $(date -u '+%Y-%m-%dT%H:%M:%SZ')"
echo ""

# Dry run by default
DRY_RUN=true
if [ "$1" == "--execute" ]; then
    DRY_RUN=false
    echo "EXECUTING CLEANUP (not dry run)"
else
    echo "DRY RUN MODE (use --execute to actually clean)"
fi
echo ""

# 1. Rotate logs older than 7 days
echo "--- Logs ---"
OLD_LOGS=$(find "$LOG_DIR" -name "*.log" -mtime +7 2>/dev/null | wc -l | tr -d ' ')
echo "  Old logs (>7 days): $OLD_LOGS"
if [ "$DRY_RUN" = false ] && [ "$OLD_LOGS" -gt 0 ]; then
    find "$LOG_DIR" -name "*.log" -mtime +7 -delete 2>/dev/null
    echo "  Removed"
fi

# Current log sizes
if [ -d "$LOG_DIR" ]; then
    echo "  Current log dir: $(du -sh "$LOG_DIR" 2>/dev/null | awk '{print $1}')"
fi

echo ""

# 2. Clean expired knowledge entries
echo "--- Knowledge ---"
if [ -f "$DB" ] && command -v sqlite3 > /dev/null 2>&1; then
    EXPIRED=$(sqlite3 "$DB" "SELECT COUNT(*) FROM knowledge WHERE expires_at IS NOT NULL AND expires_at < datetime('now')" 2>/dev/null || echo "0")
    TOTAL=$(sqlite3 "$DB" "SELECT COUNT(*) FROM knowledge" 2>/dev/null || echo "?")
    echo "  Total entries: $TOTAL"
    echo "  Expired entries: $EXPIRED"
    if [ "$DRY_RUN" = false ] && [ "$EXPIRED" -gt 0 ]; then
        sqlite3 "$DB" "DELETE FROM knowledge WHERE expires_at IS NOT NULL AND expires_at < datetime('now')"
        echo "  Expired entries removed"
    fi

    # Old session summaries (keep last 30)
    OLD_SUMMARIES=$(sqlite3 "$DB" "SELECT COUNT(*) FROM knowledge WHERE key LIKE 'session:summary:%' AND key NOT IN (SELECT key FROM knowledge WHERE key LIKE 'session:summary:%' ORDER BY updated_at DESC LIMIT 30)" 2>/dev/null || echo "0")
    echo "  Old session summaries: $OLD_SUMMARIES"
    if [ "$DRY_RUN" = false ] && [ "$OLD_SUMMARIES" -gt 0 ]; then
        sqlite3 "$DB" "DELETE FROM knowledge WHERE key LIKE 'session:summary:%' AND key NOT IN (SELECT key FROM knowledge WHERE key LIKE 'session:summary:%' ORDER BY updated_at DESC LIMIT 30)"
        echo "  Old summaries removed"
    fi
else
    echo "  Database not found or sqlite3 not available"
fi

echo ""

# 3. Clean old audit log entries (older than 30 days)
echo "--- Audit Log ---"
if [ -f "$DB" ] && command -v sqlite3 > /dev/null 2>&1; then
    OLD_AUDIT=$(sqlite3 "$DB" "SELECT COUNT(*) FROM audit_log WHERE timestamp < datetime('now', '-30 days')" 2>/dev/null || echo "0")
    echo "  Old entries (>30 days): $OLD_AUDIT"
    if [ "$DRY_RUN" = false ] && [ "$OLD_AUDIT" -gt 0 ]; then
        sqlite3 "$DB" "DELETE FROM audit_log WHERE timestamp < datetime('now', '-30 days')"
        echo "  Old entries removed"
    fi
fi

echo ""

# 4. Clean temp files
echo "--- Temp Files ---"
BUMBA_TEMPS=$(find /tmp -name "bumba-context-*" -mtime +1 2>/dev/null | wc -l | tr -d ' ')
echo "  Stale context files: $BUMBA_TEMPS"
if [ "$DRY_RUN" = false ] && [ "$BUMBA_TEMPS" -gt 0 ]; then
    find /tmp -name "bumba-context-*" -mtime +1 -delete 2>/dev/null
    echo "  Removed"
fi

echo ""

# 5. Database maintenance
echo "--- Database ---"
if [ -f "$DB" ] && command -v sqlite3 > /dev/null 2>&1; then
    DB_SIZE=$(ls -lh "$DB" 2>/dev/null | awk '{print $5}')
    WAL_SIZE=$(ls -lh "${DB}-wal" 2>/dev/null | awk '{print $5}' || echo "none")
    echo "  DB size: $DB_SIZE"
    echo "  WAL size: $WAL_SIZE"
    if [ "$DRY_RUN" = false ]; then
        sqlite3 "$DB" "PRAGMA wal_checkpoint(TRUNCATE)" > /dev/null 2>&1
        sqlite3 "$DB" "VACUUM" > /dev/null 2>&1
        echo "  WAL checkpointed and vacuumed"
    fi
fi

echo ""

# Summary
echo "=== Summary ==="
echo "  Data dir: $(du -sh "$DATA_DIR" 2>/dev/null | awk '{print $1}')"
echo "  Log dir: $(du -sh "$LOG_DIR" 2>/dev/null | awk '{print $1}')"
if [ "$DRY_RUN" = true ]; then
    echo ""
    echo "  This was a dry run. Use --execute to apply changes."
fi
echo ""
echo "=== Cleanup Complete ==="
