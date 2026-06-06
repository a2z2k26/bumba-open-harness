#!/bin/bash
# Memory Session Stop Hook
# Event: Stop
# Purpose: Prompt Claude to persist key facts and generate a structured session primer (T1)
#
# Two responsibilities:
#   1. Prompt Claude to store facts/decisions/summary to knowledge table (T3)
#   2. Prompt Claude to write primer.json (T1) capturing current state for next session

MEMORY_DB="/opt/bumba-harness/data/memory.db"
PRIMER_PATH="/opt/bumba-harness/.claude/projects/-opt-bumba-harness-agent/memory/primer.json"
PRIMER_DIR="$(dirname "$PRIMER_PATH")"

# Ensure primer directory exists
mkdir -p "$PRIMER_DIR" 2>/dev/null

# Check if there's an active session with recent activity
has_recent_activity="false"
if [ -f "$MEMORY_DB" ] && command -v sqlite3 &>/dev/null; then
    recent_count=$(sqlite3 "$MEMORY_DB" \
        "SELECT COUNT(*) FROM conversations WHERE created_at > datetime('now', '-1 hour');" 2>/dev/null)
    if [ "$recent_count" -gt 0 ] 2>/dev/null; then
        has_recent_activity="true"
    fi
fi

# Compute expiry timestamp (macOS date)
EXPIRES_AT=$(date -v+24H -Iseconds 2>/dev/null || date -d '+24 hours' -Iseconds 2>/dev/null || date -u +"%Y-%m-%dT%H:%M:%S+00:00")

# Build the session-end prompt
if [ "$has_recent_activity" = "true" ]; then
    msg="SESSION ENDING — Please preserve context before stopping.

## Part 1 — Store facts/decisions to knowledge table

Store any important information from this session:

1. **Key Facts** — operator preferences, project details, user info:
   sqlite3 /opt/bumba-harness/data/memory.db \"INSERT OR REPLACE INTO knowledge (key, data, source) VALUES ('user:<topic>', '<info>', 'agent');\"

2. **Decisions Made** — choices made this session:
   sqlite3 /opt/bumba-harness/data/memory.db \"INSERT OR REPLACE INTO knowledge (key, data, source) VALUES ('decision:<topic>', '<rationale>', 'agent');\"

3. **Self-Improvement Ideas** — ways to improve:
   sqlite3 /opt/bumba-harness/data/memory.db \"INSERT OR REPLACE INTO knowledge (key, data, source) VALUES ('decision:self-improvement:<id>', '<idea>', 'agent');\"

## Part 2 — Write session primer (T1)

Write a JSON primer to: ${PRIMER_PATH}

The primer must conform exactly to this schema (fill in real values from the session):

{
  \"schema_version\": \"1.0\",
  \"generated_at\": \"$(date -Iseconds 2>/dev/null || date -u +\"%Y-%m-%dT%H:%M:%S+00:00\")\",
  \"session_id\": \"<current session ID or 'unknown'>\",
  \"expires_at\": \"${EXPIRES_AT}\",

  \"current_track\": {
    \"name\": \"<active track name, e.g. 'System Build', 'bumba-desktop', or 'Job Search'>\",
    \"type\": \"<system | product | pa>\",
    \"switched_at\": \"<ISO timestamp or null>\"
  },

  \"active_projects\": [
    {
      \"name\": \"<project name>\",
      \"status\": \"<active | blocked | paused>\",
      \"current_phase\": \"<phase description>\",
      \"next_action\": \"<single sentence>\",
      \"github_branch\": \"<branch name or null>\"
    }
  ],

  \"recent_decisions\": [
    {
      \"topic\": \"<decision topic>\",
      \"decision\": \"<what was decided>\",
      \"rationale\": \"<why>\",
      \"made_at\": \"<ISO timestamp>\"
    }
  ],

  \"open_blockers\": [
    {
      \"id\": \"<short id>\",
      \"description\": \"<blocker description>\",
      \"waiting_on\": \"<operator | external | self>\",
      \"project\": \"<project name or null>\"
    }
  ],

  \"pending_tasks\": [
    {
      \"id\": \"<short id>\",
      \"description\": \"<task description>\",
      \"priority\": \"<high | medium | low>\",
      \"project\": \"<project name or null>\",
      \"due\": null
    }
  ],

  \"session_summary\": \"<2-4 sentence summary of what happened this session>\",

  \"operator_context\": {
    \"mood\": \"<focused | stressed | exploratory | unknown>\",
    \"last_seen\": \"$(date -Iseconds 2>/dev/null || date -u +\"%Y-%m-%dT%H:%M:%S+00:00\")\",
    \"notes\": \"<any notes from session or null>\"
  }
}

Write this JSON (with real values, not placeholders) to: ${PRIMER_PATH}

Use the Bash tool:
  bash -c 'cat > ${PRIMER_PATH} << '"'"'PRIMER_EOF'"'"'
  <your JSON here>
  PRIMER_EOF'

Or use the Write tool directly to write the file.

Only store what is genuinely worth remembering. Skip trivial exchanges."
else
    msg="SESSION ENDING — Short or idle session.

If anything important happened, store it:
  sqlite3 /opt/bumba-harness/data/memory.db \"INSERT OR REPLACE INTO knowledge (key, data, source) VALUES ('session:summary:<id>', '<highlights>', 'agent');\"

Also write a minimal primer to ${PRIMER_PATH} so the next session has continuity.
Use schema_version 1.0 with empty arrays for active_projects/decisions/blockers/tasks if nothing is active."
fi

jq -n --arg msg "$msg" '{"systemMessage": $msg, "decision": "approve"}'
