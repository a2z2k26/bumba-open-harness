#!/bin/bash
# Concept-only port of disler/claude-code-hooks-mastery (MIT, paraphrased).
# Pre-Tool Validation Hook
# Event: PreToolUse
# Purpose: Check tool risk tier, block critical tools in autonomous mode.
#
# Claude Code passes the tool name via CLAUDE_TOOL_NAME environment variable.
# Returns JSON: {"decision": "allow"} or {"decision": "deny", "reason": "..."}

HOOK_DIR="$(cd "$(dirname "$0")" && pwd)"
TOOL_NAME="${CLAUDE_TOOL_NAME:-}"

# If no tool name provided, allow (fail-open)
if [ -z "$TOOL_NAME" ]; then
    echo '{}'
    exit 0
fi

# Call Python helper for risk check
result=$(python3 "$HOOK_DIR/helpers/check_tool_risk.py" "$TOOL_NAME" 2>/dev/null)

if [ -n "$result" ]; then
    echo "$result"
else
    # Python failed — fail-open
    echo '{}'
fi
