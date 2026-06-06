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

**Registry entry required for new capabilities** (E-O7): Adding a new event type, REST/WS endpoint, or metric to the bridge requires a corresponding entry in `agent/config/registry/{events,metrics,actions}/`. CI gate `registry-completeness` enforces this on every PR. Override with `[skip registry-gate]` in PR title for docs-only PRs.

## Agent-Specific Rules

**Deploy safety**: All code changes go through the source repo. Never modify files in `/opt/bumba-harness/agent/` directly. Deploy scripts follow the pattern: copy source→target, set ownership, regen baseline, restart.

**Kernel integrity**: Core files are SHA-256 verified on startup. Modifications to kernel files (security.py, hooks, bridge.toml, baseline) require operator approval.

**Escalation before silence**: When in doubt, send the alert. A false positive is infinitely better than a silent failure that runs for 5 days unnoticed.

**Session hygiene**: Capture open items on session stop. Resume context on session start. Don't leave state only in conversation — if it must persist, put it in a file.

**Budget discipline**: Respect token budgets and rate limits. The circuit breaker exists for a reason — don't fight it.

**One rule, one home** (P25): Each rule lives in exactly one place. No duplication across documents. If something needs to be referenced elsewhere, it gets a pointer — not a copy. Duplicated rules diverge.

**Concept-only-no-license affirmation** (codified 2026-05-03, Sprint D4.7): When porting concepts (patterns, skills, prompt designs) from an external repo (e.g. Karpathy skills, Dark Factory, anthropic-cookbook, third-party MCPs), the PR description must include the affirmation:

> "Concept-only port from `<source-repo>` (`<license>`, paraphrased). No code copied; license unchanged."

This protects the operator's IP posture (no inadvertent license contamination) and creates a clean attribution trail. See `agent/CLAUDE.md` "Behavioral Doctrine" — three principles ported from forrestchang/andrej-karpathy-skills (MIT, paraphrased).

## Subagent Dispatch Pattern (codified 2026-05-03, Sprint D4.7)

When dispatching subagents for parallel independent tasks, follow this contract:

- **Worktree isolation by default.** Use worktree isolation unless the task is genuinely shared-state (rare). Worktree isolation prevents cross-session working-tree leakage.
- **Don't-Open-PR contract.** Subagent commits + pushes its branch and reports back; the orchestrator (main agent or operator) opens the PR. Subagents opening PRs in parallel races CI and confuses the merge queue.
- **Bundle 3+ identical mechanical refactors.** A single subagent shipping 3-5 similar trivial changes is more efficient than 5 subagents shipping 1 each.
- **Surface ambiguity, never silent-fix.** If the spec is unclear, the subagent reports back asking; it does not guess. (See "Operator-Decides Rule" below.)
- **Self-verify before reporting back.** Run `python3 -m py_compile` on every changed `.py` file and run the relevant test file. If either fails, fix it before reporting "complete".

Reference patterns: 2026-04-26 marathon (36 PRs, 4 spec corrections caught by subagents); 2026-04-30 Phase 5 sweep (8 PRs, single Session A).

## Operator-Decides Rule (codified 2026-05-03, Sprint D4.7)

When work encounters ambiguity that policy or rules don't resolve:

1. **Surface, don't silent-fix.** Report the ambiguity to the operator with two to three concrete options and a recommended default with rationale.
2. **Default-if-low-stakes is fine.** For reversible / low-stakes calls (variable name, log level, comment style), state the assumption + chosen default in the PR description rather than blocking.
3. **Block-and-ask if high-stakes.** For irreversible / security / public-API / schema changes, do not guess; wait for operator decision.
4. **Bundle multiple ambiguities into one ask.** Don't create question-storm; collect 2-5 related questions and ask once.

This rule originates from 2026-04-26 marathon evidence: subagents that silent-fixed wasted ~30% of operator review time on detecting unannounced deviations.

## The Rules System

Rules in `~/.claude/rules/` auto-load into context.

**Currently active** (2 files):
- `complexity-assessment.md` — Task complexity scoring (0-10), decision matrix, execution approach guidance
- `resource-management.md` — Disk, worktree, /tmp, subprocess lifecycle rules (from April 2026 disk incident)

**Planned (not yet deployed)** — A two-tier structure is designed but not built:
- Always-loaded tier: coding-style, security, git-workflow, testing, hooks, agents
- Conditional tier: language-specific rules for TypeScript, Python, Go, Swift

Until the full rules structure is deployed, the principles in this document and in `config/zone1/guiding-principles.md` serve as the authoritative rule set.

## Model Selection

**Haiku 4.5**: Lightweight agents, frequent invocation, worker agents in swarms (90% of Sonnet capability, 3x savings)
**Sonnet 4.6**: Main development work, orchestration, complex coding
**Opus 4.6**: Deep reasoning, architectural decisions, research, analysis

## Context Discipline

- Avoid the last 20% of context window for large refactors and multi-file features
- Use `/compact` at natural breakpoints to preserve context quality
- CLAUDE.md and rules survive compaction — conversational instructions do not
- If something must persist, put it in a file, not in conversation
