#!/bin/bash
# /opt/bumba-harness/agent-flat/agent/scripts/monitor.sh
# Hourly health monitor — runs via LaunchDaemon, alerts via Discord if unhealthy.
set +e

DATA_DIR="/opt/bumba-harness/data"
SECRETS_FILE="$DATA_DIR/.secrets"
ALERT_SENT_FLAG="$DATA_DIR/.monitor-alerted"

# Load Discord credentials from .secrets
BOT_TOKEN=""
OPERATOR_ID=""
if [ -f "$SECRETS_FILE" ]; then
    BOT_TOKEN=$(grep "^discord_bot_token=" "$SECRETS_FILE" 2>/dev/null | cut -d= -f2- | tr -d ' ')
    OPERATOR_ID=$(grep "^operator_discord_id=" "$SECRETS_FILE" 2>/dev/null | cut -d= -f2- | tr -d ' ')
fi

send_alert() {
    local msg="$1"
    if [ -z "$BOT_TOKEN" ] || [ -z "$OPERATOR_ID" ]; then
        echo "Cannot send alert — missing Discord credentials"
        return 1
    fi
    # Open DM channel, then send message
    CHANNEL=$(curl -s -H "Authorization: Bot $BOT_TOKEN" \
        -H "Content-Type: application/json" \
        -d "{\"recipient_id\": \"$OPERATOR_ID\"}" \
        "https://discord.com/api/v10/users/@me/channels" 2>/dev/null | \
        python3 -c "import sys,json; print(json.load(sys.stdin).get('id',''))" 2>/dev/null)
    if [ -n "$CHANNEL" ]; then
        curl -s -H "Authorization: Bot $BOT_TOKEN" \
            -H "Content-Type: application/json" \
            -d "{\"content\": \"$msg\"}" \
            "https://discord.com/api/v10/channels/$CHANNEL/messages" >/dev/null 2>&1
    fi
}

ISSUES=""

# 1. Bridge process alive?
PID=$(pgrep -u bumba-agent -f 'python.*bridge' 2>/dev/null | head -1)
if [ -z "$PID" ]; then
    ISSUES="$ISSUES\n- Bridge process NOT RUNNING"
fi

# 2. Heartbeat fresh? (< 120s old)
if [ -f "$DATA_DIR/heartbeat" ]; then
    HEARTBEAT=$(cat "$DATA_DIR/heartbeat")
    # Parse ISO timestamp (strip trailing Z)
    HEARTBEAT_CLEAN=$(echo "$HEARTBEAT" | tr -d 'Z')
    HEARTBEAT_EPOCH=$(date -j -f "%Y-%m-%dT%H:%M:%S" "$HEARTBEAT_CLEAN" "+%s" 2>/dev/null || echo 0)
    NOW_EPOCH=$(date "+%s")
    AGE=$((NOW_EPOCH - HEARTBEAT_EPOCH))
    if [ "$AGE" -gt 120 ]; then
        ISSUES="$ISSUES\n- Heartbeat STALE (${AGE}s old)"
    fi
else
    ISSUES="$ISSUES\n- Heartbeat file missing"
fi

# 3. Halt flag?
if [ -f "$DATA_DIR/halt.flag" ]; then
    REASON=$(cat "$DATA_DIR/halt.flag")
    ISSUES="$ISSUES\n- Bridge HALTED: $REASON"
fi

# 4. OAuth token expired?
if [ -f "$SECRETS_FILE" ]; then
    EXPIRES=$(grep "^claude_oauth_expires_at=" "$SECRETS_FILE" 2>/dev/null | cut -d= -f2 | tr -d ' ')
    NOW=$(date +%s)
    if [ -n "$EXPIRES" ] && [ "$NOW" -gt "$EXPIRES" ] 2>/dev/null; then
        ISSUES="$ISSUES\n- OAuth token EXPIRED"
    fi
fi

# 5. Disk space < 5GB?
DISK_AVAIL_KB=$(df -k / | tail -1 | awk '{print $4}')
if [ "$DISK_AVAIL_KB" -lt 5242880 ] 2>/dev/null; then
    DISK_GB=$((DISK_AVAIL_KB / 1048576))
    ISSUES="$ISSUES\n- Disk space LOW (${DISK_GB}GB free)"
fi

# 6. Service state: consecutive_failures >= 3?
for STATE_FILE in "$DATA_DIR"/service_state/*-state.json; do
    [ -f "$STATE_FILE" ] || continue
    FAILURES=$(python3 -c "import json,sys; print(json.load(open(sys.argv[1])).get('consecutive_failures',0))" "$STATE_FILE" 2>/dev/null || echo 0)
    if [ "$FAILURES" -ge 3 ] 2>/dev/null; then
        SVC_NAME=$(basename "$STATE_FILE" | sed 's/-state\.json$//')
        LAST_ERR=$(python3 -c "import json,sys; print(json.load(open(sys.argv[1])).get('last_error','unknown')[:100])" "$STATE_FILE" 2>/dev/null)
        ISSUES="$ISSUES\n- Service $SVC_NAME: $FAILURES consecutive failures ($LAST_ERR)"
    fi
done

# 7. LaunchDaemon crash-loop detection (Sprint 3.4; dynamic discovery — P5.1 #1732)
# Catches any com.bumba.* daemon where runs>0 AND last_exit_code!=0.
# This is the gap that allowed experiment-loop and deploy-helper to silently
# crash 3,152 times each before the 2026-04-07 audit found them. See
# memory/project_3152_crash_loop_postmortem.md for incident details.
#
# Discover all currently-bootstrapped com.bumba.* daemons from launchctl
# rather than maintaining a hardcoded list. The hardcoded list had 17 entries
# while production had 25+, leaving 9 daemons with undetected crash loops
# (Lane E E-H2 / HI-19, 2026-05-12 audit). launchctl list emits one row per
# loaded service; column 3 is the Label. We anchor on ^com\.bumba\. to avoid
# spurious matches.
KNOWN_DAEMONS=()
while IFS= read -r LABEL; do
    [ -n "$LABEL" ] && KNOWN_DAEMONS+=("$LABEL")
done < <(launchctl list 2>/dev/null | awk '$3 ~ /^com\.bumba\./ {print $3}')
if [ "${#KNOWN_DAEMONS[@]}" -eq 0 ]; then
    # No com.bumba.* daemons loaded — likely a dev machine without LaunchDaemons.
    # Surface this in the report (informational) but don't fail the check.
    ISSUES="$ISSUES\n- No com.bumba.* daemons discovered via launchctl (crash-loop check skipped)"
fi
for LABEL in "${KNOWN_DAEMONS[@]}"; do
    # launchctl print writes to stdout; capture once
    PRINT_OUT=$(launchctl print "system/$LABEL" 2>/dev/null) || continue
    # Parse 'runs = N' and 'last exit code = N' (or '(never exited)')
    RUNS=$(echo "$PRINT_OUT" | grep -E '^[[:space:]]*runs = ' | head -1 | sed -E 's/.*runs = ([0-9]+).*/\1/')
    LAST_EXIT=$(echo "$PRINT_OUT" | grep -E '^[[:space:]]*last exit code = ' | head -1 | sed -E 's/.*last exit code = (.*)/\1/' | tr -d ' ')
    # Skip daemons that have never run (runs=0) or have exited cleanly ((never exited) or 0)
    [ -z "$RUNS" ] && continue
    [ "$RUNS" = "0" ] && continue
    [ "$LAST_EXIT" = "(neverexited)" ] && continue
    [ "$LAST_EXIT" = "0" ] && continue
    # We're left with: runs>0 AND last_exit_code is set AND not 0 → crash loop signal
    # Report regardless of magnitude — even 1 unexpected exit is worth surfacing
    ISSUES="$ISSUES\n- Daemon $LABEL: runs=$RUNS last_exit=$LAST_EXIT (crash loop signal)"
done

# Report
if [ -n "$ISSUES" ]; then
    MSG="[MONITOR ALERT] $(date '+%Y-%m-%d %H:%M')$(echo -e "$ISSUES")"
    echo "$MSG"
    # Only alert once per issue cycle (don't spam every hour)
    if [ ! -f "$ALERT_SENT_FLAG" ]; then
        send_alert "$MSG"
        touch "$ALERT_SENT_FLAG"
    fi
    exit 1
else
    # Clear alert flag when healthy again
    rm -f "$ALERT_SENT_FLAG"
    exit 0
fi
