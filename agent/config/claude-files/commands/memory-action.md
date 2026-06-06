---
name: memory-action
description: Natural language interface for Bumba Memory - store, recall, and query memories
arguments:
  - name: request
    description: Natural language request about memory (e.g., "what did we decide about X", "remember this", "recall Y")
    required: true
---

# Memory Action Command

Natural language interface for interacting with Bumba Memory.

**Note:** The `memory-awareness` skill now provides this natural language recognition continuously. This command remains available for explicit invocation, but most memory queries should be recognized automatically in conversation.

## Usage Examples

```
/memory-action what did we decide about authentication
/memory-action this - stores the current context
/memory-action recall the API design decisions
/memory-action what work did the sandbox agents do
/memory-action find anything about database schema
/memory-action store this as an artifact
/memory-action list recent decisions
/memory-action show team status
```

## Request: $ARGUMENTS.request

Interpret the natural language request and execute the appropriate memory operations:

### Pattern Matching

**"remember this" / "store this" / "save this"**
- Ask user what specifically to store
- Use `memory_store` or `team_store_artifact` based on content type
- Generate appropriate key based on content

**"what did we decide about X" / "decisions about X"**
- Use `memory_search` with query: "decision:* AND {X}"
- Also check `team_get_status` for recent decisions
- Present decisions in chronological order

**"recall X" / "find X" / "search for X"**
- Use `memory_search` with query: "{X}"
- Present top results with relevance

**"what did sandbox/agent do" / "sandbox results"**
- Use `memory_search` with query: "sandbox:*" or "agent:*"
- Show artifacts and summaries from isolated environments

**"list decisions" / "recent decisions"**
- Use `memory_search` with query: "decision:*"
- Or use `team_get_status` to show decisions array

**"team status" / "what's happening"**
- Use `team_get_status`
- Summarize current task, recent context, decisions

**"handoff X" / "pass X to next agent"**
- Use `team_store_context` with key "handoff:{X}"
- Ask what to include in handoff

**"artifacts" / "show outputs"**
- Use `team_get_status` to list artifacts
- Or `memory_search` with query: "artifact:*"

### Execution Flow

1. Parse the natural language request
2. Identify the intent (store, search, recall, list, status)
3. Extract any specific terms or filters
4. Execute appropriate MCP tool(s)
5. Format and present results conversationally

### Context Awareness

When storing, consider:
- Current conversation topic
- Recent tool outputs
- User's stated goals
- Appropriate key prefix (context:, decision:, artifact:, etc.)

When searching, consider:
- Expanding synonyms
- Searching related prefixes
- Showing most relevant results first
