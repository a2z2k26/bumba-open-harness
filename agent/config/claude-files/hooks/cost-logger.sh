#!/bin/bash
# Log session activity for cost tracking
LOG_FILE=~/logs/claude-sessions.jsonl
mkdir -p ~/logs

EVENT_TYPE="${1:-unknown}"
TIMESTAMP=$(date -u +%Y-%m-%dT%H:%M:%SZ)
SESSION_DIR=$(pwd)

echo "{\"ts\":\"$TIMESTAMP\",\"event\":\"$EVENT_TYPE\",\"dir\":\"$SESSION_DIR\"}" >> "$LOG_FILE"

exit 0
