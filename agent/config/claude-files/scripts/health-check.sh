#!/bin/bash
# Bumba System Health Check Script
# Run manually or invoked by the agent for system diagnostics

HOME_DIR="/opt/bumba-harness"
DATA_DIR="$HOME_DIR/data"
LOG_DIR="$HOME_DIR/logs"
DB="$DATA_DIR/memory.db"

echo "=== Bumba Health Check ==="
echo "Time: $(date -u '+%Y-%m-%dT%H:%M:%SZ')"
echo ""

# 1. Bridge process
echo "--- Bridge ---"
if [ -f "$DATA_DIR/bridge.pid" ]; then
    PID=$(cat "$DATA_DIR/bridge.pid")
    if ps -p "$PID" > /dev/null 2>&1; then
        RSS=$(ps -o rss= -p "$PID" 2>/dev/null | tr -d ' ')
        CPU=$(ps -o %cpu= -p "$PID" 2>/dev/null | tr -d ' ')
        ETIME=$(ps -o etime= -p "$PID" 2>/dev/null | tr -d ' ')
        echo "  Status: RUNNING (PID $PID)"
        echo "  Uptime: $ETIME"
        echo "  Memory: $((RSS / 1024)) MB"
        echo "  CPU: ${CPU}%"
    else
        echo "  Status: DEAD (stale PID $PID)"
    fi
else
    echo "  Status: NO PID FILE"
fi

# 2. Heartbeat
echo ""
echo "--- Heartbeat ---"
if [ -f "$DATA_DIR/heartbeat" ]; then
    HB=$(cat "$DATA_DIR/heartbeat")
    echo "  Last: $HB"
    # Calculate age if GNU date available
    if date -j -f "%Y-%m-%dT%H:%M:%S" "$(echo "$HB" | cut -c1-19)" "+%s" > /dev/null 2>&1; then
        HB_EPOCH=$(date -j -f "%Y-%m-%dT%H:%M:%SZ" "$HB" "+%s" 2>/dev/null || date -j -f "%Y-%m-%dT%H:%M:%S" "$(echo "$HB" | cut -c1-19)" "+%s" 2>/dev/null)
        NOW_EPOCH=$(date "+%s")
        if [ -n "$HB_EPOCH" ]; then
            AGE=$((NOW_EPOCH - HB_EPOCH))
            echo "  Age: ${AGE}s"
            if [ "$AGE" -gt 120 ]; then
                echo "  ALERT: Heartbeat stale (>120s)"
            fi
        fi
    fi
else
    echo "  Status: NO HEARTBEAT FILE"
fi

# 3. Halt flag
if [ -f "$DATA_DIR/halt" ]; then
    echo ""
    echo "--- ALERT: HALTED ---"
    echo "  Reason: $(cat "$DATA_DIR/halt")"
fi

# 4. Database
echo ""
echo "--- Database ---"
if [ -f "$DB" ]; then
    DB_SIZE=$(ls -lh "$DB" 2>/dev/null | awk '{print $5}')
    WAL_SIZE=$(ls -lh "${DB}-wal" 2>/dev/null | awk '{print $5}' || echo "none")
    echo "  Size: $DB_SIZE (WAL: $WAL_SIZE)"
    if command -v sqlite3 > /dev/null 2>&1; then
        MSG_COUNT=$(sqlite3 "$DB" "SELECT COUNT(*) FROM conversations" 2>/dev/null || echo "?")
        ERR_COUNT=$(sqlite3 "$DB" "SELECT COUNT(*) FROM audit_log WHERE event_type LIKE '%error%' AND timestamp > datetime('now', '-1 hour')" 2>/dev/null || echo "?")
        QUEUE=$(sqlite3 "$DB" "SELECT COUNT(*) FROM message_queue WHERE status='pending'" 2>/dev/null || echo "?")
        KNOWLEDGE=$(sqlite3 "$DB" "SELECT COUNT(*) FROM knowledge" 2>/dev/null || echo "?")
        echo "  Messages: $MSG_COUNT"
        echo "  Knowledge entries: $KNOWLEDGE"
        echo "  Errors (1h): $ERR_COUNT"
        echo "  Queue: $QUEUE pending"
    fi
else
    echo "  Status: NO DATABASE"
fi

# 5. Disk
echo ""
echo "--- Disk ---"
du -sh "$DATA_DIR" "$LOG_DIR" 2>/dev/null | sed 's/^/  /'
df -h /opt/bumba-harness 2>/dev/null | tail -1 | awk '{print "  Volume: " $4 " available (" $5 " used)"}'

# 6. Token
echo ""
echo "--- Token ---"
if grep -q "claude_oauth_token=" "$DATA_DIR/.secrets" 2>/dev/null; then
    echo "  Status: PRESENT"
else
    echo "  Status: MISSING"
fi

# 7. Recent errors
echo ""
echo "--- Recent Errors ---"
if [ -f "$LOG_DIR/bridge.log" ]; then
    ERROR_COUNT=$(grep -c -i "error\|critical" "$LOG_DIR/bridge.log" 2>/dev/null || echo "0")
    echo "  Total in log: $ERROR_COUNT"
    echo "  Last 3:"
    grep -i "error\|critical" "$LOG_DIR/bridge.log" 2>/dev/null | tail -3 | sed 's/^/    /'
    if [ "$(grep -c -i "error\|critical" "$LOG_DIR/bridge.log" 2>/dev/null)" -eq 0 ]; then
        echo "    (none)"
    fi
else
    echo "  No bridge log found"
fi

echo ""
echo "=== End Health Check ==="
