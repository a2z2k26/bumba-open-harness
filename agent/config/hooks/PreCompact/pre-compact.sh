#!/bin/bash
# Concept-only port of disler/claude-code-hooks-mastery (MIT, paraphrased).
# Pre-Compact Hook
# Event: PreCompact
# Purpose: Capture workflow state before conversation compaction

CHECKPOINT_DIR="$HOME/.bumba/data/compaction_checkpoints"
MEMORY_DB="$HOME/.bumba/memory/memory.db"
TEAM_MEMORY="$HOME/.bumba/memory/team-memory.json"

mkdir -p "$CHECKPOINT_DIR"

# Gather active task titles from task_pipeline SQLite
active_tasks="[]"
if [ -f "$MEMORY_DB" ] && command -v sqlite3 &> /dev/null; then
    tasks_json=$(sqlite3 -json "$MEMORY_DB" \
        "SELECT id, title, status, project FROM task_pipeline WHERE status IN ('in_progress', 'review', 'assigned') ORDER BY updated_at DESC LIMIT 5" 2>/dev/null)
    if [ -n "$tasks_json" ] && [ "$tasks_json" != "[]" ]; then
        active_tasks="$tasks_json"
    fi
fi

# Also check team memory for current task
team_task=""
if [ -f "$TEAM_MEMORY" ]; then
    team_task=$(jq -r '.currentTask.description // empty' "$TEAM_MEMORY" 2>/dev/null)
fi

# Count recent decisions
recent_decisions=0
if [ -f "$MEMORY_DB" ] && command -v sqlite3 &> /dev/null; then
    recent_decisions=$(sqlite3 "$MEMORY_DB" \
        "SELECT COUNT(*) FROM knowledge WHERE key LIKE 'decision:%' AND created_at > datetime('now', '-24 hours')" 2>/dev/null || echo "0")
fi

# Save checkpoint to JSON file for PostCompact to read
session_id="${CLAUDE_SESSION_ID:-unknown}"
checkpoint_file="$CHECKPOINT_DIR/${session_id}.json"
jq -n \
    --arg sid "$session_id" \
    --arg team_task "$team_task" \
    --argjson active_tasks "$active_tasks" \
    --argjson decisions "$recent_decisions" \
    '{
        session_id: $sid,
        team_task: $team_task,
        active_tasks: $active_tasks,
        recent_decisions: $decisions,
        captured_at: (now | todate)
    }' > "$checkpoint_file" 2>/dev/null

# Build context message
task_summary=""
if [ -n "$team_task" ]; then
    task_summary="Active team task: $team_task"
fi

pipeline_tasks=$(echo "$active_tasks" | jq -r 'if length > 0 then [.[].title] | join(", ") else "none" end' 2>/dev/null || echo "none")

msg="PRE-COMPACTION CHECKPOINT CAPTURED:
Workflow state saved before compaction.
${task_summary:+$task_summary}
Pipeline tasks: $pipeline_tasks
Recent decisions: $recent_decisions

After compaction, critical context will be restored via PostCompact hook.
Continue your work — older messages will be summarized while preserving recent context."

jq -n --arg msg "$msg" '{"systemMessage": $msg}'
