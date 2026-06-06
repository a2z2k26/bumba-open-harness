---
name: tmux-orchestration
description: "Use tmux, dmux, and Agent Teams for parallel agent workflows, session persistence, and multi-agent orchestration. TRIGGER on any of these natural language patterns: 'run in parallel', 'spin up agents', 'work on these simultaneously', 'do these at the same time', 'split this into parallel tasks', 'run multiple agents', 'use dmux', 'use tmux', 'create a team', 'agent team', 'keep this running', 'background this', 'persistent session', 'detach', 'multiple sessions', 'run N agents', 'parallelize this', 'divide and conquer', 'fan out', 'work on both', 'tackle these together', 'launch agents', 'start agents for', 'have agents review', 'multi-agent', 'parallel review', 'parallel development', 'run these concurrently', 'split the work'. Also trigger when the user describes 2+ independent tasks that could benefit from parallel execution, or asks to keep something running in the background."
---

# tmux + dmux + Agent Teams Orchestration

This system has tmux, dmux, and Agent Teams configured for parallel agent workflows.

## What's Installed

| Tool | Version | Purpose |
|------|---------|---------|
| **tmux** | 3.6a | Terminal multiplexer — session persistence, pane splitting |
| **dmux** | 5.6.1 | Parallel agents with git worktree isolation |
| **Agent Teams** | Experimental | Coordinated multi-agent with shared task list |
| **TPM + resurrect + continuum** | Active | Session persistence across reboots |
| **Observability** | `~/Claude/claude-observability` | Real-time monitoring dashboard |

## When to Use Each

### tmux Popup (single agent, quick task)
For everyday Claude Code usage. One keybinding, per-project persistence.
- User presses `Ctrl-a y` to toggle Claude popup
- Each project directory gets its own persistent session
- Closing the popup keeps Claude running

### dmux (parallel agents, independent tasks)
For 2-5 agents working on independent tasks in the same repo. Each agent gets its own git worktree — complete file isolation.
```bash
cd /path/to/git-repo
dmux
```
- Press `n` to create agent panes, `j` to jump, `m` to merge, `f` for file browser, `q` to quit
- Each pane = 1 agent + 1 worktree + 1 branch
- Smart merging: auto-commit, merge to main, clean up worktree
- Supports Claude, Codex, Gemini, and 8 other agent CLIs
- **Requires a git repository**

### Agent Teams (coordinated agents, inter-dependent tasks)
For tasks where agents need to communicate, share findings, and coordinate. The lead delegates, teammates self-organize.
```
Create an agent team with N teammates to [describe task].
```
- Lead creates shared task list, assigns work
- Teammates message each other directly
- Tasks support dependencies (blocked until prerequisites complete)
- Shift+Down cycles through teammates in-process mode
- Split panes appear automatically when running inside tmux
- All teammates currently run Opus 4.6 (per-model selection not yet available)
- 3 teammates ≈ 3-4x token cost of single session
- Always clean up via the lead: "Clean up the team"

## tmux Keybindings Reference

Prefix is `Ctrl-a` (not the default Ctrl-b).

| Action | Keys |
|--------|------|
| Claude popup | `Ctrl-a y` |
| Session chooser | `Ctrl-a C-y` |
| Capture output | `Ctrl-a e` |
| Split horizontal | `Ctrl-a "` |
| Split vertical | `Ctrl-a %` |
| Switch pane | `Alt+Arrow` |
| Zoom pane | `Ctrl-a z` |
| New window | `Ctrl-a c` |
| Detach | `Ctrl-a d` |
| Save session | `Ctrl-a Ctrl-s` |
| Restore session | `Ctrl-a Ctrl-r` |

## Utility Scripts

```bash
# Open a project workspace (4 windows: main, claude, agents, git):
claude-workspace <project-name>

# Recovery:
claude-recovery status          # show sessions, worktrees, processes
claude-recovery kill-all        # nuclear reset
claude-recovery clean-worktrees # prune orphaned worktrees
```

## Observability Dashboard

Real-time monitoring of all Claude Code sessions:
```bash
# Terminal 1 — server:
cd ~/Claude/claude-observability/apps/server && bun run dev

# Terminal 2 — client:
cd ~/Claude/claude-observability/apps/client && npm run dev

# Open http://localhost:5173
```

Hooks automatically send PreToolUse, PostToolUse, SessionStart, Stop, and SubagentStop events to the dashboard when the server is running. If the server is not running, hooks silently fail with no impact.

## Decision Guide

| Situation | Use |
|-----------|-----|
| Quick question or single-file task | tmux popup (`Ctrl-a y`) |
| 2-5 independent tasks in one repo | dmux |
| Tasks that need agents to discuss/debate | Agent Teams |
| Code review from multiple perspectives | Agent Teams |
| Parallel feature dev (backend + frontend + tests) | dmux with file-based separation |
| Bug investigation with competing hypotheses | Agent Teams |
| Long-running background work | tmux session + detach |

## Important Notes

- **dmux requires git repos.** Non-git directories won't work.
- **Agent Teams is experimental.** `/resume` does not restore teammates — spawn new ones.
- **Teammate file conflicts:** Break work by file ownership. Two agents editing the same file = last write wins.
- **Cost awareness:** Each dmux pane and each Agent Teams teammate has its own context window. Token costs scale linearly.
- **Session persistence** preserves layouts, not running processes. After a reboot, tmux layouts restore but Claude Code must be relaunched.
- **Observability hooks** add a small latency per tool call (~100-300ms). If sluggish, temporarily remove the PreToolUse hook from settings.json.
