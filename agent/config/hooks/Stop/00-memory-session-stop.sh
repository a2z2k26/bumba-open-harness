#!/usr/bin/env bash
# Concept-only port of disler/claude-code-hooks-mastery (MIT, paraphrased). 13-lifecycle taxonomy.
# Stop/00-memory-session-stop.sh — Bumba knowledge persistence prompt at session stop.
# Relocated from ~/.claude/hooks/memory-session-stop.sh; emit call appended.
#
# Fires at Claude Code CLI Stop event. Reminds the agent to persist any important
# findings to the knowledge store before the session ends, then emits telemetry.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "$SCRIPT_DIR/../_lib/emit.sh"

HALT_FLAG="/opt/bumba-harness/data/halt.flag"
halt_active=0
[ -f "$HALT_FLAG" ] && halt_active=1

# Output the knowledge-persistence reminder to stdout (injected into session context).
if [ "$halt_active" -eq 0 ]; then
    cat << 'PROMPT'
=== SESSION STOP — KNOWLEDGE PERSISTENCE CHECK ===
Before this session ends:
1. Have you encountered any new facts, decisions, or insights worth saving?
   If yes, use the store_knowledge or update_knowledge tool to persist them.
2. Any task state changes that should be recorded?
3. Any errors or blockers to surface to the operator?
Review these before acknowledging session close.
PROMPT
fi

# Emit lifecycle telemetry.
emit "Stop" "halt_active=${halt_active}"
