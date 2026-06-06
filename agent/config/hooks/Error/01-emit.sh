#!/usr/bin/env bash
# Concept-only port of disler/claude-code-hooks-mastery (MIT, paraphrased). 13-lifecycle taxonomy.
# Error/01-emit.sh — emits Error telemetry on CLI-level errors.
# Fires when the Claude Code CLI encounters a non-recoverable error condition.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "$SCRIPT_DIR/../_lib/emit.sh"
emit "Error" "code=${CLAUDE_ERROR_CODE:-unknown}" "tool=${CLAUDE_TOOL_NAME:-none}"
