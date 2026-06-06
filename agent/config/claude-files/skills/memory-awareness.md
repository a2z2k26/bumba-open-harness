# Memory Awareness

Continuous guidance for when to search and store knowledge during work. Hooks handle session boundaries; this skill handles everything in between.

## When to Search First

Before acting on something, check if prior context exists:

| About to... | Search for |
|-------------|------------|
| Make a decision | `sqlite3 ~/data/memory.db "SELECT key, value FROM knowledge WHERE key LIKE 'decision:%' AND value LIKE '%topic%'"` |
| Work on a feature | `sqlite3 ~/data/memory.db "SELECT key, value FROM knowledge WHERE key IN (SELECT key FROM knowledge_fts WHERE knowledge_fts MATCH 'feature name')"` |
| Answer about preferences | `sqlite3 ~/data/memory.db "SELECT value FROM knowledge WHERE key LIKE 'user:%'"` |
| Continue prior work | `sqlite3 ~/data/memory.db "SELECT key, value FROM knowledge WHERE key LIKE 'handoff:%' OR key LIKE 'context:%' ORDER BY updated_at DESC LIMIT 5"` |

## Recognizing Memory-Related Requests

When the operator says things like:

| Operator says | What to do |
|---------------|------------|
| "what did we decide about X" | Search: `key LIKE 'decision:%' AND value LIKE '%X%'` |
| "remember that I prefer X" | Store: `INSERT OR REPLACE INTO knowledge (key, value, source) VALUES ('user:preference-x', 'Operator prefers X', 'operator')` |
| "didn't we already..." | Search knowledge_fts for the topic |
| "forget about X" / "that's wrong" | Update or delete the relevant key |
| "what do you know about X" | Full-text search + key prefix search |

## When to Store

Store knowledge when:
- **Operator states a preference**: "I like X", "always do Y", "never Z" → `user:{topic}`
- **A decision is made**: "Let's use X because Y" → `decision:{topic}`
- **You discover something important**: Bug root cause, API behavior, system quirk → `decision:{topic}`
- **Work is incomplete**: Session ending with unfinished task → `handoff:{topic}`
- **Session had meaningful content**: Summarize key points → `session:summary:{id}`

## When NOT to Store

- Trivial exchanges ("hello", "thanks")
- Information already in knowledge (search first)
- Temporary debugging output
- Sensitive data (passwords, tokens, keys)
- Duplicate of what hooks already handle (session summaries at stop)

## Storage Pattern

Always use `INSERT OR REPLACE` to avoid duplicates:
```bash
sqlite3 ~/data/memory.db "INSERT OR REPLACE INTO knowledge (key, value, tags, source, updated_at) VALUES ('key', 'value', 'tags', 'agent', datetime('now'))"
```

Include context in the value — not just what, but why. Future sessions need the rationale.

## Complementing Hooks

| Aspect | Hooks handle | You handle |
|--------|-------------|------------|
| Loading context | Session start hook loads decisions, user facts, summaries | Search for specific topics mid-session |
| Saving context | Session stop hook prompts for summary | Store discoveries as they happen |
| Subagent results | Subagent stop hook captures findings | Reference subagent keys when relevant |
