#!/usr/bin/env bash
# Concept-only port of disler/claude-code-hooks-mastery (MIT, paraphrased). 13-lifecycle taxonomy.
# PostToolUse/01-emit.sh — emits PostToolUse telemetry after each tool call.
# Fires after the Claude Code CLI tool execution completes (success or failure).
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "$SCRIPT_DIR/../_lib/emit.sh"
emit "PostToolUse" "tool=${CLAUDE_TOOL_NAME:-unknown}" "exit_code=${CLAUDE_TOOL_EXIT_CODE:-0}"
