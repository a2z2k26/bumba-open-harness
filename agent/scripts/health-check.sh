#!/bin/bash
# /opt/bumba-harness/agent-flat/agent/scripts/health-check.sh
# Quick health check for all system components.
# Uses set +e so every check runs even if one fails.
set +e

DATA_DIR="/opt/bumba-harness/data"
LOG_DIR="/opt/bumba-harness/logs"
SECRETS_FILE="$DATA_DIR/.secrets"

STATUS=0

echo "=== Bumba Agent Health Check -- $(date -Iseconds) ==="

# 1. Bridge process
echo ""
echo "--- Bridge Process ---"
PID=$(pgrep -u bumba-agent -f 'python.*bridge' 2>/dev/null | head -1)
if [ -n "$PID" ]; then
    RSS=$(ps -o rss= -p "$PID" 2>/dev/null | tr -d ' ')
    ELAPSED=$(ps -o etime= -p "$PID" 2>/dev/null | tr -d ' ')
    echo "  PID: $PID (running)"
    echo "  Memory: $((RSS / 1024)) MB RSS"
    echo "  Uptime: $ELAPSED"
else
    echo "  Bridge NOT RUNNING"
    STATUS=1
fi

# 2. Heartbeat freshness
echo ""
echo "--- Heartbeat ---"
if [ -f "$DATA_DIR/heartbeat" ]; then
    HEARTBEAT=$(cat "$DATA_DIR/heartbeat")
    HEARTBEAT_EPOCH=$(date -j -f "%Y-%m-%dT%H:%M:%S" "$HEARTBEAT" "+%s" 2>/dev/null || echo 0)
    NOW_EPOCH=$(date "+%s")
    AGE=$((NOW_EPOCH - HEARTBEAT_EPOCH))
    if [ "$AGE" -lt 120 ]; then
        echo "  Last: $HEARTBEAT (${AGE}s ago) OK"
    else
        echo "  Last: $HEARTBEAT (${AGE}s ago) STALE"
        STATUS=1
    fi
else
    echo "  Heartbeat file not found"
    STATUS=1
fi

# 3. Halt flag
echo ""
echo "--- Halt Status ---"
if [ -f "$DATA_DIR/halt.flag" ]; then
    echo "  HALTED: $(cat "$DATA_DIR/halt.flag")"
    STATUS=1
else
    echo "  Not halted"
fi

# 4. SQLite database
echo ""
echo "--- Database ---"
if [ -f "$DATA_DIR/memory.db" ]; then
    DB_SIZE=$(stat -f%z "$DATA_DIR/memory.db" 2>/dev/null || echo 0)
    echo "  Size: $((DB_SIZE / 1024 / 1024)) MB"
    INTEGRITY=$(sqlite3 "$DATA_DIR/memory.db" "PRAGMA integrity_check;" 2>/dev/null || echo "FAILED")
    if [ "$INTEGRITY" = "ok" ]; then
        echo "  Integrity: OK"
    else
        echo "  Integrity: $INTEGRITY"
        STATUS=1
    fi
    JOURNAL=$(sqlite3 "$DATA_DIR/memory.db" "PRAGMA journal_mode;" 2>/dev/null || echo "unknown")
    echo "  Journal: $JOURNAL"
    MSG_COUNT=$(sqlite3 "$DATA_DIR/memory.db" "SELECT COUNT(*) FROM conversations;" 2>/dev/null || echo "?")
    echo "  Conversations: $MSG_COUNT"
    PENDING=$(sqlite3 "$DATA_DIR/memory.db" "SELECT COUNT(*) FROM message_queue WHERE status='pending';" 2>/dev/null || echo "?")
    echo "  Queue pending: $PENDING"
else
    echo "  Database not found"
    STATUS=1
fi

# 5. Claude Code binary
echo ""
echo "--- Claude Code ---"
CLAUDE_BIN=$(which claude 2>/dev/null || echo "")
if [ -n "$CLAUDE_BIN" ]; then
    echo "  Binary: $CLAUDE_BIN"
    echo "  Version: $(claude --version 2>/dev/null || echo 'unknown')"
else
    echo "  Binary: NOT FOUND"
    STATUS=1
fi

# 6. Secrets file (replaces Keychain — LaunchDaemon has no Keychain access)
echo ""
echo "--- Secrets ---"
if [ -f "$SECRETS_FILE" ]; then
    if grep -q "discord_bot_token=" "$SECRETS_FILE" 2>/dev/null; then
        echo "  Discord bot token: present"
    else
        echo "  Discord bot token: MISSING"
        STATUS=1
    fi
    if grep -q "operator_id=" "$SECRETS_FILE" 2>/dev/null; then
        echo "  Operator ID: present"
    else
        echo "  Operator ID: MISSING"
        STATUS=1
    fi
    if grep -q "claude_oauth_token=" "$SECRETS_FILE" 2>/dev/null; then
        # Check if token is expired
        EXPIRES=$(grep "claude_oauth_expires_at=" "$SECRETS_FILE" 2>/dev/null | cut -d= -f2 | tr -d ' ')
        NOW=$(date +%s)
        if [ -n "$EXPIRES" ] && [ "$NOW" -lt "$EXPIRES" ] 2>/dev/null; then
            REMAINING=$(( (EXPIRES - NOW) / 3600 ))
            echo "  OAuth token: valid (${REMAINING}h remaining)"
        else
            echo "  OAuth token: EXPIRED or missing expiry"
        fi
    else
        echo "  OAuth token: MISSING"
        STATUS=1
    fi
else
    echo "  Secrets file not found"
    STATUS=1
fi

# 7. Disk usage
echo ""
echo "--- Disk Usage ---"
DISK_AVAIL=$(df -h / | tail -1 | awk '{print $4}')
echo "  Available: $DISK_AVAIL"
echo "  Data: $(du -sh "$DATA_DIR" 2>/dev/null | cut -f1 || echo '?')"
echo "  Logs: $(du -sh "$LOG_DIR" 2>/dev/null | cut -f1 || echo '?')"

# 8. Crash log
echo ""
echo "--- Crash History ---"
if [ -f "$DATA_DIR/crash.log" ]; then
    CRASH_COUNT=$(grep -c . "$DATA_DIR/crash.log" 2>/dev/null || echo 0)
    echo "  Total crashes: $CRASH_COUNT"
else
    echo "  No crash history"
fi

echo ""
if [ "$STATUS" -eq 0 ]; then
    echo "=== HEALTHY ==="
else
    echo "=== ISSUES DETECTED ==="
fi

exit $STATUS
