---
name: hook-development
description: How to develop and propose Claude Code hooks for Bumba. Hooks are kernel-protected — you can design and test them, but only the operator can deploy.
---

# Hook Development

## When to Use
- Designing new session lifecycle behaviors
- Proposing changes to existing hooks
- Understanding the hook system for debugging

## Constraint
Hooks are **kernel-protected files** owned by the admin user. You CANNOT modify them directly. You can:
1. Design hook logic and write it as a proposal
2. Test hook logic with sample input
3. Propose the change to the operator for deployment

## Current Hooks

| Hook | File | Trigger |
|------|------|---------|
| Session Start | `memory-session-start.sh` | Before Claude session begins |
| Session Stop | `memory-session-stop.sh` | When session ends |
| Subagent Stop | `memory-subagent-stop.sh` | When a subagent finishes |

These live in the hooks directory configured in `settings.json` and fire automatically in both interactive and `-p` mode.

## Hook Input/Output

Hooks receive JSON on stdin and output JSON on stdout.

**Input format:**
```json
{
  "tool_name": "Bash",
  "tool_input": {"command": "ls -la"},
  "session_id": "abc123"
}
```

**Output format (PreToolUse):**
```json
{"decision": "approve"}
```
or:
```json
{"decision": "deny", "reason": "Operation not allowed"}
```

**Output format (Session hooks):**
```json
{"systemMessage": "Context to inject into the session"}
```

## What Existing Hooks Do

### memory-session-start.sh
1. Queries SQLite for recent decisions, user facts, last session summary
2. Reads kernel-baseline.json and verifies file hashes
3. If integrity check fails → sets halt flag, adds security alert
4. Returns context as systemMessage for injection

### memory-session-stop.sh
1. Checks if session had recent activity
2. Builds a prompt with SQL examples for storing decisions, user facts, summaries
3. Returns prompt as systemMessage to guide knowledge persistence

### memory-subagent-stop.sh
1. Reads subagent metadata from stdin
2. Prompts for saving subagent findings to knowledge
3. Uses agent-specific key prefixes

## Proposing a Hook Change

1. **Design**: Write the hook as a standalone bash script
2. **Test**: Pipe sample JSON and verify output:
   ```bash
   echo '{"tool_name":"Bash","tool_input":{"command":"ls"}}' | bash /tmp/proposed-hook.sh
   ```
3. **Save**: Write to `~/agent/proposed-hooks/{hook-name}.sh`
4. **Document**: Explain what it does and why it's needed
5. **Notify**: Tell the operator about the proposal
6. **Wait**: Operator reviews, tests, and deploys (or rejects)

## Hook Best Practices
- Keep hooks fast (<2 seconds execution)
- Always output valid JSON
- Handle missing data gracefully (files not found, empty database)
- Never modify kernel files from within a hook
- Log errors to stderr, not stdout (stdout is the JSON response)
