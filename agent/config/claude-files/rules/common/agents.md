# Agent Orchestration

40 specialist agents in `~/.claude/agents/`, organized by department prefix.
See `~/.claude/rules/department-routing.md` for the full mapping.

## When to Use Agents
- Complexity score 3+ (per complexity-assessment rule)
- Use the department chief (*-chief) for cross-cutting coordination
- Match agent prefix to task domain: design-*, engineering-*, qa-*, ops-*, strategy-*

## Parallel Execution
ALWAYS use parallel agents for independent operations across domains:

```
# GOOD: 3 agents in parallel
1. engineering-code-reviewer: Review auth module
2. qa-security-auditor: Security analysis
3. engineering-performance-engineer: Performance review

# BAD: Sequential when tasks are independent
```

## Multi-Perspective Analysis
For complex problems, launch multiple domain agents in parallel for split-role analysis.
