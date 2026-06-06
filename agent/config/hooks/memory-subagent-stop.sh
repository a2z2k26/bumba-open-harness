#!/bin/bash
# Memory Subagent Stop Hook
# Event: SubagentStop
# Purpose: Prompt subagent to store findings before stopping
#
# Per BRIDGE-ARCHITECTURE.md Section 5.4:
#   Saves subagent findings to knowledge table

MEMORY_DB="/opt/bumba-harness/data/memory.db"

# Read stdin for hook input (contains agent info)
input=$(cat)

# Extract agent type if available
agent_type=$(echo "$input" | jq -r '.agent_type // "subagent"' 2>/dev/null)

msg="SUBAGENT SESSION ENDING - Please preserve your work before stopping.

Before this subagent session ends, store any findings or artifacts:

1. **Store Findings** - Save key results to memory:
   sqlite3 $MEMORY_DB \"INSERT OR REPLACE INTO knowledge (key, value, tags, source) VALUES ('agent:${agent_type}:<topic>', '<findings>', 'subagent', 'agent');\"

2. **Record Decisions** - If you made architectural or implementation choices:
   sqlite3 $MEMORY_DB \"INSERT OR REPLACE INTO knowledge (key, value, source) VALUES ('decision:<topic>', '<rationale>', 'agent');\"

3. **Note Blockers** - If work is incomplete, record what's remaining:
   sqlite3 $MEMORY_DB \"INSERT OR REPLACE INTO knowledge (key, value, source) VALUES ('handoff:${agent_type}', '<status, completed, remaining>', 'agent');\"

This ensures the primary session can access your contributions."

jq -n --arg msg "$msg" '{"systemMessage": $msg, "decision": "approve"}'
