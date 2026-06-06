#!/bin/bash
# PostToolUse hook: Check memory hygiene on agent task completion.
# Warning mode — logs violations but does not block.

input=$(cat)
tool_name=$(echo "$input" | jq -r '.tool_name // ""' 2>/dev/null)
timestamp=$(date -u +"%Y-%m-%dT%H:%M:%SZ")

echo "[${timestamp}] Memory Hygiene: PostToolUse hook fired for tool=${tool_name}" >> /tmp/bumba-memory-hygiene.log
