---
name: tmux-agents
description: Spawn, monitor, and manage parallel Claude Code agents in tmux sessions
---

# Tmux Agents Skill

Manage parallel Claude Code agent execution via tmux sessions. Translate natural language requests into tmux agent operations. Enforce best practices for when and how to use parallel agents.

## What Tmux Agents Are

Independent Claude Code subprocesses running in isolated tmux sessions. Each agent:
- Has full tool access (Read, Edit, Bash, Grep, Glob, etc.)
- Runs in the agent working directory with OAuth credentials
- Produces NDJSON output parsed on completion
- Delivers results to Discord automatically when done

**Limits:** Max 3 concurrent. Max 4-hour lifetime. Results auto-delivered.

## Commands

### Spawn an Agent

**Trigger:** "spawn", "run in background", "do this in parallel", "delegate", "start an agent", "kick off", "have an agent do"

**Steps:**
1. Identify the task from the operator's request
2. Determine if the task is appropriate for an agent (see Decision Framework below)
3. If appropriate, run: `/spawn <clear task description>`
4. Report the agent ID and what it's doing

**Examples:**
- "audit the codebase for security issues" → `/spawn Audit all Python files in bridge/ for security vulnerabilities. Report findings as a markdown table with severity, file, line, and description.`
- "run tests in the background" → `/spawn Run the full test suite with python3 -m pytest tests/ -v and report results summary.`
- "check test coverage while I work on this" → `/spawn Analyze tests/ directory. For each module in bridge/, check if a corresponding test file exists. List untested modules.`

### Check Agent Status

**Trigger:** "how's the agent", "agent status", "what's running", "check on", "are any agents done"

**Steps:**
1. Run `/agents` to see all agents
2. For a specific agent: `/agents <id>`
3. Summarize status in natural language

### Kill an Agent

**Trigger:** "kill", "stop", "cancel agent", "abort"

**Steps:**
1. If agent ID provided: `/kill-agent <id>`
2. If no ID: run `/agents` first, confirm which one to kill
3. Report result

### Get Results

**Trigger:** "what did the agent find", "agent results", "what came back"

**Steps:**
1. Run `/agents <id>` for detailed results
2. Summarize key findings for the operator

## Decision Framework

### SPAWN an agent when:
- The task is **independent** — doesn't need the current conversation context
- The task would take **multiple minutes** of sequential work
- You want to **parallelize** — do two things at once
- The operator explicitly asks for background/parallel work
- Complex analysis tasks: audits, reviews, coverage reports, documentation generation

### DO NOT spawn when:
- The task is **quick** (< 30 seconds of work)
- The task needs **real-time operator interaction** (clarifications, approvals)
- The task **depends on current conversation state** (files you just read, decisions just made)
- You're already at **3 concurrent agents**
- The task involves **destructive operations** (deleting files, git push, deployments) — these need direct operator oversight

### Multi-agent patterns:
- **Parallel audit:** Spawn 2-3 agents each covering different file groups or concern areas
- **Research + execute:** Spawn a research agent, continue working, incorporate findings later
- **Divide and conquer:** Break a large codebase task into independent chunks, one agent per chunk

## Task Description Best Practices

When spawning, write the task description as a **complete, self-contained prompt**. The agent has no context from this conversation.

**Good task descriptions:**
- Specific: "Audit bridge/*.py for SQL injection, command injection, and path traversal vulnerabilities. Report as markdown table."
- Self-contained: "Read all files in job_search/boards/ and list which board classes have a working fetch() method vs stub implementations."
- Output-oriented: "Generate a test coverage report: for each .py file in bridge/, check if tests/test_<name>.py exists and count test functions."

**Bad task descriptions:**
- Vague: "Look at the code" (what code? for what?)
- Context-dependent: "Fix the bug we were discussing" (agent has no conversation context)
- Destructive: "Delete all unused files" (needs operator oversight)

## Trigger Detection

Activate this skill when the operator says any of:
- "spawn" / "run in background" / "do in parallel" / "kick off an agent"
- "delegate this" / "have an agent handle" / "background task"
- "how are the agents" / "agent status" / "what's running"
- "kill agent" / "stop agent" / "cancel the agent"
- "what did the agent find" / "agent results"
- "can you do two things at once" / "parallelize"
- Any request prefixed with "in the background" or "while you're at it"

## Integration

- **Discord commands:** `/spawn`, `/agents`, `/kill-agent`
- **CLI helper:** `bash scripts/tmux-agent.sh {spawn|list|status|output|kill}`
- **Bridge monitoring:** Heartbeat loop checks agent sessions every 60s
- **Result delivery:** Completed agents write to `data/service_messages/` for Discord pickup
- **Registry:** `data/agents/registry.json` — persists across bridge restarts
- **Bootstrap docs:** Agent awareness in `config/bootstrap/TOOLS.md` and `config/system-prompt.md`
