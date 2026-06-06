#!/bin/bash
# PreToolUse hook: Validate memory write key conventions.
# Warning mode — logs violations but does not block.

input=$(cat)
tool_name=$(echo "$input" | jq -r '.tool_name // ""' 2>/dev/null)
timestamp=$(date -u +"%Y-%m-%dT%H:%M:%SZ")

if [[ "$tool_name" == *"team_store"* ]] || [[ "$tool_name" == *"team_record"* ]]; then
    key=$(echo "$input" | jq -r '.tool_input.key // ""' 2>/dev/null)
    if [[ -n "$key" ]] && [[ ! "$key" =~ ^(agent:|context:|handoff:|decision:|artifact:) ]]; then
        echo "[${timestamp}] WARN: Memory write key '${key}' does not follow prefix convention" >> /tmp/bumba-memory-hygiene.log
    fi
fi
