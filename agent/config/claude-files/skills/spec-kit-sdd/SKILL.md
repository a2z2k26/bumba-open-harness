---
name: spec-kit-sdd
description: Specification-Driven Development using GitHub Spec-Kit. Use when creating new projects, adding features, or when user mentions SDD/spec-kit/specify.
---

# Specification-Driven Development (SDD) via Spec-Kit

## When to Use

- User says "new project" and wants structured development
- User mentions SDD, spec-kit, specify, or specification-driven
- Starting a new feature that benefits from a formal spec
- User asks for a constitution, specification, or development plan
- You identify a project that would benefit from spec-first methodology

## Prerequisites

- `specify` CLI installed (`~/.local/bin/specify`)
- For GitHub features (issues): `GH_TOKEN` or `gh` CLI authenticated

## Core Principle

**Specifications are executable artifacts — code serves specs, not the reverse.**

Every feature begins with a specification. The spec is the source of truth. Code implements the spec. Tests validate the spec. If code and spec disagree, the code is wrong.

## The 9-Command Pipeline

### Primary Pipeline (in order)

| # | Command | Purpose |
|---|---------|---------|
| 1 | `/speckit.constitution` | Define project constitution (principles, standards, constraints) |
| 2 | `/speckit.specify` | Create a specification for a feature |
| 3 | `/speckit.plan` | Generate implementation plan from spec |
| 4 | `/speckit.tasks` | Break plan into discrete tasks |
| 5 | `/speckit.implement` | Execute tasks, guided by spec |

### Enhancement Commands

| # | Command | Purpose |
|---|---------|---------|
| 6 | `/speckit.clarify` | Ask clarifying questions about a spec (max 5 questions) |
| 7 | `/speckit.analyze` | Analyze existing code against a spec |
| 8 | `/speckit.checklist` | Generate verification checklist |
| 9 | `/speckit.taskstoissues` | Push tasks to GitHub Issues |

### Important

The 9 `/speckit.*` commands are **per-project**, created by `specify init`. They use relative script paths and only work within the project directory. They are NOT global commands.

## Project Init Workflow

1. Navigate to or create project directory
2. Run: `specify init <name> --ai claude --here`
3. This creates:
   - `.specify/` directory (config, templates)
   - `.claude/commands/speckit.*.md` (the 9 per-project commands)
4. Run `/speckit.constitution` to define the project's governing document
5. Create a Zone 3 project registry entry

## Per-Project Directory Structure

```
project-root/
├── .specify/
│   ├── config.yaml          # Project config
│   ├── templates/            # Spec templates
│   └── constitution.md       # Project constitution
├── specs/
│   ├── 001-feature-name/
│   │   ├── spec.md           # The specification
│   │   ├── plan.md           # Implementation plan
│   │   ├── tasks.md          # Task breakdown
│   │   └── checklist.md      # Verification checklist
│   └── 002-another-feature/
├── .claude/
│   └── commands/
│       ├── speckit.constitution.md
│       ├── speckit.specify.md
│       ├── speckit.plan.md
│       ├── speckit.tasks.md
│       ├── speckit.implement.md
│       ├── speckit.clarify.md
│       ├── speckit.analyze.md
│       ├── speckit.checklist.md
│       └── speckit.taskstoissues.md
```

## Key Rules

1. **Spec-first**: Never implement before specifying
2. **Constitutional authority**: The constitution governs all specs; specs govern all code
3. **Template-driven**: Use Spec-Kit templates for consistency
4. **TDD per Article III**: Tests validate specs, not implementations
5. **Max 3 clarifications per spec**: If more needed, the spec is too vague — rewrite it
6. **Max 5 questions per clarify**: Focused, specific questions only
7. **Specs are numbered**: Sequential numbering (001, 002, ...) within each project

## Zone 3 Integration

When initializing a project with Spec-Kit:
1. Create a project registry memory file at `~/.claude/projects/*/memory/projects/<name>.md`
2. Include SDD status (constitution written, active specs, completed specs)
3. Track switching loads the project registry which includes SDD context

## Typical Feature Development Flow

```
1. /speckit.specify "User authentication with OAuth"
   → Creates specs/003-user-auth/spec.md
2. /speckit.clarify 003
   → Asks up to 5 focused questions, updates spec
3. /speckit.plan 003
   → Generates implementation plan from spec
4. /speckit.tasks 003
   → Breaks plan into discrete, implementable tasks
5. /speckit.implement 003
   → Implements each task, referencing spec throughout
6. /speckit.checklist 003
   → Generates verification checklist
7. /speckit.analyze 003
   → Validates implementation against spec
```

## Reference

Full audit report with detailed analysis of every command, template, and configuration option:
`~/.claude/docs/spec-kit-full-audit-report.md`
