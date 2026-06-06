# Rules

## Philosophy

Rules exist to prevent mistakes that cost more to fix than to avoid. Every rule earns its place through this test: would removing it cause the agent to make errors? If not, it doesn't belong.

Rules are not aspirational. They are enforced. If a rule is broken, the work is not done.

Full guiding principles with rationale and examples: `config/zone1/guiding-principles.md` (25 principles, operator-locked).

## Non-Negotiable Principles

**Immutability**: Never mutate existing objects. Always create new copies. This is the single most important code quality rule across all languages. No exceptions.

**Security-first** (P6): No hardcoded secrets. Parameterized queries only. Validate all external input. If a security issue is found, stop everything and fix it before continuing.

**Read before write** (P4): Never modify a file you haven't read in the current session. Never assume contents. Never assume an API exists — verify it.

**Simplicity** (P5): The minimum complexity that solves the problem. Don't over-engineer. Don't add features that weren't requested. Three similar lines of code is better than a premature abstraction.

**Search before build**: Before writing any new implementation, search GitHub (`gh search`), package registries (npm, PyPI), and existing codebase for prior art. Prefer adopting proven solutions over writing net-new code.

**Reliability over features**: For an always-on system, boring and reliable beats clever and fragile. Every new capability must not degrade existing uptime.

**Graceful degradation**: When part of the house goes down, the rest keeps running. The bridge doesn't crash because the email service crashed. The escalation engine doesn't stop because one cron failed. Services fail independently. Each subsystem must handle its own errors without poisoning the process that hosts it.

**Never go silent** (P14): Silent failures are the cardinal sin. If a service crashes, a state file is written, an alert fires, and the operator knows. If a cron stops running, the escalation engine detects the staleness. No process should be able to die without leaving evidence.

## Development Lifecycle

This is the expected workflow for feature-level work:

1. **Research** — Search for existing implementations, templates, patterns. Use `gh search`, Brave, Context7, package registries. Adopt or port when possible.
2. **Plan** — Score complexity. For 3+, use a specialist agent. For 6+, write an implementation plan before touching code. Use planner or `/orc:plan-feature`.
3. **Build (TDD)** — Write tests first (RED), implement to pass (GREEN), refactor (IMPROVE). Target 80%+ coverage. Unit + integration + E2E all required.
4. **Review** — Use code-reviewer agent immediately after writing code. Address CRITICAL and HIGH issues. Fix MEDIUM when possible.
5. **Validate** — Run `/validate` before any deploy. Pre-deploy test gating blocks Python file deploys if tests fail. Max 3 fix iterations.
6. **Commit** — Conventional commits: `type: description`. Full commit history analysis for PRs.
7. **Deploy** — Use `/deploy` for self-deploy (Tier A auto, Tier B approval, Tier C operator-only). Never skip the validate step.

For simple tasks (0-2 complexity), skip to step 3. For urgent fixes, skip to step 3 with a narrower test scope.

### Definition of Done (issue closure ≠ work complete)

**An issue is not complete when it is closed. An issue is closed because it is complete.** Two separate bars, in this order:

1. **Work complete**: every acceptance criterion in the issue body is satisfied, every task-checklist box is checked, tests are written and passing locally + in CI, the PR is opened, reviewed, and **merged to main**.
2. **Issue closed**: a state change that only happens after bar 1 is fully cleared — typically via `Closes #N` in the merged PR, not via a manual `gh issue close`.

Never close an issue to make progress appear. If work is partial, leave it open and post a comment describing exactly what remains. A closed-but-incomplete issue is strictly worse than an open-and-honest one — it loses the signal the operator needs to catch the gap. The prior solo audit found a 30% premature-closure rate; the 2026-04-18 swarm audit confirmed the pattern is systemic. Do not extend it.

Before closing, verify — don't infer:
- Run the tests mentioned in the acceptance criteria. If they don't exist, write them.
- Check that the PR that addresses the issue is **merged**, not just open.
- Re-read the acceptance criteria one at a time; map each to the evidence that satisfies it.

## Agent-Specific Rules

**Deploy safety**: All code changes go through PR + merge. Post-D6-bis (2026-05-09), the source clone at `/opt/bumba-harness/agent-flat/` IS the runtime — modifications happen via `git pull --ff-only origin main` on the runtime tree, not via direct edits. The 4-step deploy is: pull → regen baseline → bounce → smoke. Operator-only writes (kernel-baseline regen, plist edits) still belong to the operator-with-sudo, not autonomous specialists.

**Kernel integrity**: Core files are SHA-256 verified on startup. Modifications to kernel files (security.py, hooks, bridge.toml, baseline) require operator approval.

**Escalation before silence**: When in doubt, send the alert. A false positive is infinitely better than a silent failure that runs for 5 days unnoticed.

**Push back, then execute**: A real partner pushes back when they see a better path and executes when the direction is set. Voice the disagreement once, with the reasoning. Once the operator confirms the call, commit to it fully — no slow-rolling, no relitigating mid-task.

**Session hygiene**: Capture open items on session stop. Resume context on session start. Don't leave state only in conversation — if it must persist, put it in a file.

**Budget discipline**: Respect token budgets and rate limits. The circuit breaker exists for a reason — don't fight it.

**One rule, one home** (P25): Each rule lives in exactly one place. No duplication across documents. If something needs to be referenced elsewhere, it gets a pointer — not a copy. Duplicated rules diverge.

## The Rules System

Rules in `~/.claude/rules/` auto-load into context. Two tiers:

**Always-loaded** (6 files, ~5,200 chars of 12,000 budget):
- `common/coding-style.md` — Immutability, file organization, error handling, input validation, quality checklist
- `common/security.md` — Security checks, secret management, response protocol
- `common/git-workflow.md` — Commit format, PR workflow
- `common/testing.md` — 80% coverage, TDD workflow, test types
- `common/hooks.md` — Hook types, auto-accept guidance, TodoWrite practices
- `common/agents.md` — When to use agents, parallel execution, multi-perspective analysis

**Conditional** (20 files — load only when working with matching file types):
- TypeScript (5): Zod validation, spread immutability, no console.log in prod
- Python (5): PEP 8, type annotations, dataclasses, black/isort/ruff
- Go (5): Go idioms, error handling, goroutine safety
- Swift (5): `let` over `var`, `struct` by default, Swift 6+ concurrency

## Model Selection

**Haiku 4.5**: Lightweight agents, frequent invocation, worker agents in swarms (90% of Sonnet capability, 3x savings)
**Sonnet 4.6**: Main development work, orchestration, complex coding
**Opus 4.6**: Deep reasoning, architectural decisions, research, analysis

## Context Discipline

- Avoid the last 20% of context window for large refactors and multi-file features
- Use `/compact` at natural breakpoints to preserve context quality
- CLAUDE.md and rules survive compaction — conversational instructions do not
- If something must persist, put it in a file, not in conversation

## Living Document

This file grows with the system. When something rules-worthy surfaces — a pattern, a mistake, a hard-won judgment — propose it as a rule here. Rules are added as they become earned, not pre-declared.
