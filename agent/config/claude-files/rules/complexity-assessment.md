# Task Complexity Assessment

Assess incoming operator messages to determine the right execution approach.

## Quick Score (0-10)

| Dimension | 0 | 1 | 2 |
|-----------|---|---|---|
| **Scope** | Single query/answer | 1-3 files or commands | 4+ files, multi-step |
| **System Impact** | Read-only | Write files, run commands | Modify config, restart services |
| **Knowledge Needed** | None / already known | Search memory first | Research + multiple queries |
| **Risk** | None, easily redone | Moderate, reversible | Affects uptime or data |
| **Ambiguity** | Clear intent | Some interpretation | Needs clarification |

## Decision Matrix

| Score | Approach |
|-------|----------|
| **0-2** | Answer directly or execute a single tool call |
| **3-5** | Search knowledge first, then execute with tool calls |
| **6-8** | Plan steps, execute sequentially, report progress |
| **9-10** | Confirm approach with operator before executing |

## Common Patterns

**Score 0-2**: "What time is it?", "Read this file", "What's my uptime?"

**Score 3-5**: "Create a script that does X", "Find all errors in recent logs", "Store this as a decision"

**Score 6-8**: "Set up a new monitoring check", "Refactor my cleanup script", "Analyze last week's performance"

**Score 9-10**: "Change the bridge configuration", "Update the hook system", "Migrate the database schema"

## Operator Confirmation Required

Always confirm before:
- Deleting data or files
- Actions that affect bridge uptime
- Changes to kernel-protected files (propose only)
- Operations you haven't done before
