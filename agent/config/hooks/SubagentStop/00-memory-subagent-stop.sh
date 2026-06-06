#!/usr/bin/env bash
# Concept-only port of disler/claude-code-hooks-mastery (MIT, paraphrased). 13-lifecycle taxonomy.
# SubagentStop/00-memory-subagent-stop.sh — Bumba subagent findings persistence.
# Relocated from ~/.claude/hooks/memory-subagent-stop.sh; emit call appended.
#
# Fires at Claude Code CLI SubagentStop event. Prompts the subagent to surface
# findings to the parent context before the subprocess exits, then emits telemetry.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "$SCRIPT_DIR/../_lib/emit.sh"

# Output subagent findings prompt to stdout.
cat << 'PROMPT'
=== SUBAGENT STOP — FINDINGS SURFACE CHECK ===
Before this subagent exits:
1. Summarize your key findings in a structured format for the parent context.
2. List any files created or modified (paths + purpose).
3. Flag any blockers or open questions that need parent-agent follow-up.
4. Record durable findings via store_knowledge if they should persist across sessions.
PROMPT

# Emit lifecycle telemetry.
emit "SubagentStop" "subagent_id=${CLAUDE_SUBAGENT_ID:-unknown}"
