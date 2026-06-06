---
name: shared-memory
description: Use the bumba-memory MCP server for cross-agent shared memory, team coordination, decisions, artifacts, and handoffs. Use when working with subagents, worktrees, or tasks that need to persist context beyond the current session.
tools: mcp__bumba-memory__memory_store, mcp__bumba-memory__memory_retrieve, mcp__bumba-memory__memory_search, mcp__bumba-memory__team_start_task, mcp__bumba-memory__team_complete_task, mcp__bumba-memory__team_store_context, mcp__bumba-memory__team_get_context, mcp__bumba-memory__team_record_decision, mcp__bumba-memory__team_store_artifact, mcp__bumba-memory__team_search, mcp__bumba-memory__team_get_status
---

# Shared Memory (bumba-memory MCP)

Bumba has two memory systems. Use the right one for the right purpose:

| System | Storage | Purpose | When to use |
|--------|---------|---------|-------------|
| **Bridge memory** (SQLite `~/data/memory.db`) | Local, single-agent | Conversation history, operator preferences, knowledge, goals | Day-to-day memory, personal facts, session context |
| **Shared memory** (bumba-memory MCP) | Shared, multi-agent | Team coordination, cross-agent context, decisions, artifacts | Subagent work, handoffs, anything multiple agents need |

## When to Use Shared Memory

- **Starting a subagent task**: Store context before spawning so the subagent can retrieve it
- **Completing a subagent task**: Store results/artifacts so the parent agent can retrieve them
- **Making architectural decisions**: Record decisions with rationale for future reference
- **Cross-session handoffs**: Store work-in-progress context that must survive session expiry
- **Multi-step workflows**: Track shared state across multiple agent invocations

## Key Conventions

Use prefixed keys to organize entries:

| Prefix | Purpose | Example |
|--------|---------|---------|
| `context:` | Shared state, project config | `context:current-sprint` |
| `handoff:` | Work-in-progress for another agent | `handoff:refactor-auth` |
| `decision:` | Recorded decisions with rationale | `decision:use-postgres-over-mongo` |
| `artifact:` | Generated outputs, code snippets | `artifact:api-schema-v2` |
| `agent:{id}:` | Agent-specific working memory | `agent:researcher:findings` |

## Workflow Patterns

### Delegating to a Subagent

Before spawning:
1. `team_start_task` — describe the task
2. `team_store_context` — share relevant context the subagent will need

After subagent completes:
1. `team_search` or `team_get_context` — retrieve results
2. `team_complete_task` — close the task

### Recording a Decision

When a meaningful choice is made:
```
team_record_decision:
  decision: "Use PostgreSQL for the event store"
  rationale: "Need JSONB support and strong consistency; MongoDB's eventual consistency is a risk"
```

### Storing an Artifact

When producing a reusable output:
```
team_store_artifact:
  name: "api-schema-v2"
  type: "code"
  content: "<the schema>"
```

### Searching Before Creating

Always search before storing to avoid duplicates:
```
memory_search: "authentication"
```

## When NOT to Use Shared Memory

- **Operator preferences** → use bridge memory (`sqlite3 ~/data/memory.db`)
- **Session summaries** → handled automatically by hooks
- **Trivial facts** → don't store throwaway context
- **Sensitive credentials** → never store tokens, passwords, or API keys

## Monitoring

Check shared memory health periodically:
- `system_health` — storage stats, WAL status, active instances
- `memory_stats` — entry counts, FTS5 index status
- `team_get_status` — current task, recent decisions, artifacts
