# Engineering Team Roster

This file is the delegation guide for engineering work. Read it when the task
would benefit from a focused specialist's full attention. Do not read or use
for quick lookups — handle those yourself.

## How to Spawn a Specialist

Use Claude Code's **Agent tool** directly. Pass:
1. A specific, self-contained task prompt (the specialist has no context from
   your conversation)
2. The expertise profile as part of the system prompt if deeper context is
   needed (load from `config/expertise/updatable/{name}.md`)
3. Optionally, a model override (`sonnet` default; `opus` for complex reasoning)

The spawned subagent runs in its own session, returns a structured result,
and exits. Do NOT run the task yourself — always delegate when the roster
indicates delegation is appropriate.

## Delegation Principles

1. **Delegate for focus, not capacity.** Delegate when the work benefits from a
   specialist's sustained attention. Not for small lookups.
2. **Be specific about scope.** The subagent has no prior context. File paths,
   acceptance criteria, and expected output format go in the task prompt.
3. **Trust the result.** Review what comes back, but don't second-guess the
   specialist's chosen approach unless it violates a hard constraint.
4. **Operator-only changes are yours.** Tier C modifications (system prompts,
   security modules, kernel baselines) are never delegated.

## The Team

### Code Reviewer
- **Expertise:** Code quality review, style enforcement, architecture compliance, PR review
- **When to delegate:** Before PR submission, when you want an independent review of a non-trivial change, when reviewing someone else's PR
- **Expertise profile:** `config/expertise/updatable/code-reviewer.md`
- **Model:** sonnet (opus for architectural concerns)
- **Tools:** Read, Grep, Glob, Bash (for running tests)

### Security Auditor
- **Expertise:** Security vulnerability scanning, secret detection, authentication review, input validation, OWASP top 10
- **When to delegate:** When handling user input, authentication/authorization, secrets, crypto, or any code touching trust boundaries
- **Expertise profile:** `config/expertise/updatable/security-auditor.md`
- **Model:** sonnet
- **Tools:** Read, Grep, Glob, Bash (for bandit/semgrep)

### Test Engineer (QA Engineer)
- **Expertise:** Test design, coverage analysis, test strategy, regression testing
- **When to delegate:** When coverage needs to go from low to high (>60%), when designing a test strategy for a new module, when investigating flaky tests
- **Expertise profile:** `config/expertise/updatable/qa-engineer.md`
- **Model:** sonnet
- **Tools:** Read, Write, Edit, Bash (for pytest)

### Performance Engineer
- **Expertise:** Profiling, bottleneck identification, benchmark design, load testing
- **When to delegate:** When investigating slowness, when optimizing hot paths, when setting up benchmarks
- **Expertise profile:** `config/expertise/updatable/performance-engineer.md`
- **Model:** sonnet
- **Tools:** Read, Bash (for profilers)

### Backend Architect
- **Expertise:** System design, API design, data modeling, service boundaries, scalability
- **When to delegate:** When designing a new service, when refactoring architecture, when making decisions about persistence/caching/queuing
- **Expertise profile:** `config/expertise/updatable/backend-architect.md`
- **Model:** opus
- **Tools:** Read, Grep, Glob, Write (for spec docs)

### API Engineer
- **Expertise:** REST/GraphQL design, OpenAPI, versioning, auth patterns
- **When to delegate:** When designing API surfaces, when integrating with external APIs, when adding webhooks
- **Expertise profile:** `config/expertise/updatable/api-engineer.md`
- **Model:** sonnet
- **Tools:** Read, Write, Edit, Bash

### Database Specialist
- **Expertise:** Schema design, query optimization, indexing, migrations, transaction semantics
- **When to delegate:** When designing schemas, when optimizing slow queries, when writing migrations
- **Expertise profile:** `config/expertise/updatable/database-specialist.md`
- **Model:** sonnet
- **Tools:** Read, Bash (for psql/sqlite)

### DevOps Engineer
- **Expertise:** CI/CD, deployment pipelines, infrastructure, monitoring, logging
- **When to delegate:** When setting up CI, when diagnosing deployment failures, when configuring launchd/systemd services
- **Expertise profile:** `config/expertise/updatable/devops-engineer.md`
- **Model:** sonnet
- **Tools:** Read, Write, Bash

### Refactoring Specialist
- **Expertise:** Identifying dead code, duplication, code smells, safe refactoring patterns
- **When to delegate:** When cleaning up legacy code, when extracting shared utilities, when modernizing old patterns
- **Expertise profile:** `config/expertise/updatable/engineering-refactoring-specialist.md`
- **Model:** sonnet
- **Tools:** Read, Edit, Grep, Glob, Bash

### Architect Reviewer
- **Expertise:** Architectural drift detection, dependency boundary enforcement, layering violations
- **When to delegate:** Before merging large changes, when you suspect the design has strayed from intended boundaries
- **Expertise profile:** `config/expertise/updatable/engineering-architect-reviewer.md`
- **Model:** opus
- **Tools:** Read, Grep, Glob

### TDD Orchestrator
- **Expertise:** Enforcing red-green-refactor, writing failing tests first, coverage-driven development
- **When to delegate:** When starting a new feature from scratch, when you want discipline enforced
- **Expertise profile:** `config/expertise/updatable/engineering-tdd-orchestrator.md`
- **Model:** sonnet
- **Tools:** Read, Write, Edit, Bash

## Not Delegated

The following work is NOT delegated. Handle directly:
- Tier C files (system prompts, security.py, trust_score.py, tier_manager.py, kernel-baseline.json, hooks/, database.py)
- Quick lookups (< 2 minutes of focused work)
- Decisions that require the operator's input
- Anything involving credentials or secrets
