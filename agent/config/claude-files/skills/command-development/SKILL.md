---
name: command-development
description: How to create new Claude Code commands for Bumba. Use when asked to create a command or when you identify a reusable workflow.
---

# Command Development

## When to Use
- Operator asks to create a new command
- You identify a repetitive task that should be standardized
- A workflow needs to be documented as a reusable pattern

## Important Note on -p Mode
Commands in `~/.claude/commands/` are slash commands for interactive Claude Code sessions. In Bumba's headless `-p` mode, slash commands are **not directly invocable**. However, commands are still valuable as:
- Documentation of standardized workflows
- Reference material when loaded into context
- Available when someone runs interactive Claude Code as bumba-agent

## Command File Structure

Location: `~/.claude/commands/{command-name}.md`

```markdown
---
description: Brief description shown in command list
---

[Clear instructions for what Claude should do when this command is invoked]
[Reference actual paths, tools, and sqlite3 queries]
[Use $ARGUMENTS for optional user-provided input]
```

## Steps to Create

1. **Identify the need**: What task does this command automate?
2. **Name it**: Kebab-case, descriptive, short (e.g., `health-check`, `search-knowledge`, `summarize-logs`)
3. **Write the instructions**: Use concrete tool references — Bash for commands, Read for files, sqlite3 for database
4. **Include $ARGUMENTS**: Allow the operator to provide optional input
5. **Test**: If in interactive mode, invoke and verify. Otherwise, review the instructions for completeness.

## Example

`~/.claude/commands/summarize-logs.md`:
```markdown
---
description: Summarize recent bridge logs
---

Read the last 100 lines of ~/logs/bridge.log and provide a concise summary:
- Errors and warnings (count and types)
- Messages processed since last restart
- Any rate limits or timeouts
- Overall health assessment

If $ARGUMENTS is provided, filter logs for that specific term.
```

## Quality Checklist
- Instructions reference actual Bumba paths and tools
- No restricted commands (sudo, launchctl, security)
- Works with or without $ARGUMENTS
- Description is clear and under one line
