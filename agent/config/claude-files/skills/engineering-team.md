---
name: engineering-team
description: Always-loaded awareness of the Zone 3 engineering team and Zone 4 departments. Provides delegation guidance based on task complexity and type.
---

# Engineering Team & Zone 4 Departments

You have a full engineering team available as subagents and 5 Zone 4 departments available via escalation.

## Zone 3: Engineering Team (Claude Subagents)

These agents run as subagents within your session. They share your context.

| Agent | Specialty | When to Delegate |
|-------|-----------|-----------------|
| **engineering-chief** | Multi-specialist coordination | Complexity 6+, features spanning multiple specialties |
| **backend-architect** | System design, API architecture, database schema | Architecture decisions, backend system design |
| **frontend-developer** | UI implementation, React/Next.js components | Frontend features, component development |
| **api-engineer** | API design, endpoints, integrations | API work, third-party integrations, webhook handlers |
| **code-reviewer** | Code quality, best practices, PR review | Pre-merge review, code quality assessment |
| **database-specialist** | Schema design, query optimization, migrations | Database work, performance issues, migration planning |
| **devops-engineer** | CI/CD, build systems, GitHub Actions | Build pipeline, deployment config, automation |
| **performance-engineer** | Profiling, optimization, benchmarking | Performance issues, optimization work, load testing |

### Deployment Rules

| Complexity | Action |
|-----------|--------|
| 0-2 | Handle directly. No subagent needed. |
| 3-5 | Delegate to the single most relevant specialist. |
| 6-8 | Delegate to engineering-chief. Chief coordinates 2-3 specialists. |
| 9-10 | engineering-chief + parallel specialists + worktree isolation. |

## Zone 4: Departments (On-Demand Escalation)

These departments are invoked via `escalate()`. Each has a chief who coordinates a team of specialists.

| Department | Chief | Team Size | When to Escalate |
|-----------|-------|-----------|-----------------|
| **QA** | qa-chief | 9 agents | Pre-merge validation, security audits, test coverage, accessibility review |
| **Product Strategy** | strategy-product-chief | 8 agents | PRD creation, feature evaluation, competitive analysis, roadmap decisions |
| **Design** | design-chief | 8 agents | UI/UX specs, visual direction, design system audits, component design |
| **Operations** | ops-chief | 8 agents | Infrastructure review, deployment planning, monitoring setup, incident analysis |
| **Strategy Board** | board-ceo | 7 agents | High-stakes strategic decisions, new business idea evaluation, major architectural choices |

### Escalation Syntax

```python
# QA review
result = await escalate(department="qa", task="Security audit of src/auth/")

# Product strategy
result = await escalate(department="strategy", task="Evaluate adding a freemium tier")

# Design review
result = await escalate(department="design", task="Review the dashboard component hierarchy")

# Ops review
result = await escalate(department="ops", task="Review the deployment pipeline")

# Strategy Board (requires structured brief)
result = await escalate(
    department="board",
    brief="## Situation\n...\n## Stakes\n...\n## Constraints\n...\n## Key Questions\n..."
)
```

### When NOT to Escalate
- Simple code changes (complexity 0-2): handle directly
- Quick questions: answer from knowledge, don't spin up a department
- Repetitive work: if you've done this exact thing before, do it again directly
- When the user explicitly says to do it yourself
