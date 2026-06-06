#!/bin/bash
# Concept-only port of disler/claude-code-hooks-mastery (MIT, paraphrased).
# Post-Compact Hook
# Event: PostCompact
# Purpose: Restore workflow state from checkpoint after compaction

CHECKPOINT_DIR="$HOME/.bumba/data/compaction_checkpoints"
session_id="${CLAUDE_SESSION_ID:-unknown}"
checkpoint_file="$CHECKPOINT_DIR/${session_id}.json"

# Restore from checkpoint if it exists
if [ -f "$checkpoint_file" ]; then
    team_task=$(jq -r '.team_task // empty' "$checkpoint_file" 2>/dev/null)
    active_tasks=$(jq -r '.active_tasks | if length > 0 then [.[].title] | join(", ") else "none" end' "$checkpoint_file" 2>/dev/null || echo "none")
    decisions=$(jq -r '.recent_decisions // 0' "$checkpoint_file" 2>/dev/null)
    captured_at=$(jq -r '.captured_at // "unknown"' "$checkpoint_file" 2>/dev/null)

    task_line=""
    if [ -n "$team_task" ]; then
        task_line="
ACTIVE TEAM TASK (restored from checkpoint):
  $team_task"
    fi

    msg="POST-COMPACTION CONTEXT RESTORED (from checkpoint at $captured_at):
$task_line
PIPELINE TASKS: $active_tasks
DECISIONS THIS SESSION: $decisions

The conversation was compacted. Older messages have been summarized above.
Your workflow state has been restored from the pre-compaction checkpoint.

If anything critical seems missing:
- team_get_status — current task state
- memory_search — persisted context
- /log — today's action history"
else
    msg="POST-COMPACTION NOTE:
Conversation was compacted. No pre-compaction checkpoint was found for this session.

Check these sources for context:
- team_get_status — current task state
- memory_search — persisted context
- /log — today's action history"
fi

jq -n --arg msg "$msg" '{"systemMessage": $msg}'
