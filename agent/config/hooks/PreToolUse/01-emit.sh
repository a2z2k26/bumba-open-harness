#!/usr/bin/env bash
# Concept-only port of disler/claude-code-hooks-mastery (MIT, paraphrased). 13-lifecycle taxonomy.
# PreToolUse/01-emit.sh — emits PreToolUse telemetry before each tool call.
# Fires immediately before the Claude Code CLI invokes any tool.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "$SCRIPT_DIR/../_lib/emit.sh"
emit "PreToolUse" "tool=${CLAUDE_TOOL_NAME:-unknown}"
