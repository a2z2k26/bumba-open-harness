---
name: using-superpowers
description: Guide to using Claude Code tools effectively in Bumba's headless -p mode. Reference this when choosing which tool to use for a task.
---

# Using Your Tools

You run as `claude -p` in headless mode. Here's what's available and how to use it well.

## Available Tools

| Tool | Use for | Instead of |
|------|---------|-----------|
| **Bash** | git, system commands, sqlite3, process checks | — |
| **Read** | View file contents | cat, head, tail |
| **Write** | Create new files | echo/cat redirection |
| **Edit** | Modify existing files (exact string replacement) | sed, awk |
| **Glob** | Find files by pattern (`**/*.py`) | find, ls |
| **Grep** | Search file contents (regex) | grep, rg |
| **Task** | Spawn subagents for parallel work | — |

## What Does NOT Work in -p Mode

- **Slash commands** (`/health-check`, `/commit`) — not available in headless mode
- **Interactive input** — no stdin, no prompts, no `git add -i`
- **Agent files** — don't auto-load unless passed via `--agent` flag

## What DOES Auto-Apply

- **Rules** in `~/.claude/rules/` — loaded via settings.json `include` directives
- **Hooks** — `memory-session-start.sh`, `memory-session-stop.sh`, `memory-subagent-stop.sh` fire automatically
- **Context** — injected via `--append-system-prompt-file` before each session

## Tool Patterns

### File Operations
```
Read the file first, then Edit to make changes.
Never Edit a file you haven't Read in this session.
Use Write only for new files, never to overwrite existing ones blindly.
```

### Searching the Codebase
```
Glob to find files: **/*.md, scripts/*.sh
Grep to search content: pattern, optional file filter
Combine: Glob to narrow, then Read the matches.
```

### System Commands (Bash)
```
Always prefer dedicated tools over Bash equivalents.
Use Bash for: git, sqlite3, ps, du, df, launchctl status checks.
Never use Bash for: cat, grep, find, sed, echo > file.
```

### Memory Queries (Bash + sqlite3)
```bash
sqlite3 ~/data/memory.db "SELECT key, value FROM knowledge WHERE key LIKE 'decision:%' ORDER BY updated_at DESC LIMIT 5"
```

### Subagents (Task)
```
Use for parallel research or independent subtasks.
Provide clear, self-contained prompts — subagents don't see your context.
Results come back as a single message.
```

## Allowed Paths

You can read/write within:
- `~/agent/` — your code and config
- `~/data/` — memory database, secrets, state files
- `~/logs/` — bridge and session logs
- `~/.claude/` — skills, rules, commands, scripts (non-kernel only)
- `/tmp/` — temporary files

## Restricted Operations

Never attempt:
- `sudo`, `launchctl`, `security` commands
- Modifying kernel files: `bridge/*.py`, `config/hooks/*`, `settings.json`, `*.plist`
- Installing packages or changing system config
- Writing to paths outside your home directory
