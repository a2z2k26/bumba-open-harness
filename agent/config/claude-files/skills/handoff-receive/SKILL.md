---
name: handoff-receive
description: Bootstrap a project from a design/planning handoff. Reads the spec artifacts and handoff manifest, builds an execution plan, and identifies any gaps before writing code.
args:
  - name: section
    description: Start with a specific section ID instead of full project scan
    required: false
user-invokable: true
---

You are receiving a project that was planned and designed by another agent in a separate environment. Your job is to understand the specs, verify you have everything you need, and begin building.

**Your environment is the execution environment.** You build backends, APIs, infrastructure, and frontend implementations. The planning/design environment produced the specs — you consume them.

## Step 1: Locate and Inventory Spec Artifacts

Scan the repo for all specification artifacts. Check each path and report what exists:

### Design Director Specs
```
.design/bumba-design-director/product/
├── product-overview.md           # Vision, problems, features
├── product-roadmap.md            # Sections / feature areas (priority order)
├── data-model/
│   ├── data-model.md             # Entity descriptions and relationships
│   └── types.ts                  # TypeScript interfaces (THE source of truth for shapes)
├── shell/
│   └── spec.md                   # Navigation, layout, routing structure
└── sections/
    └── {section-id}/
        ├── spec.md               # User flows, UI requirements per section
        ├── data.json             # Sample data for this section
        └── screen-specs/         # Detailed screen-level specs
```

### Design Assets
```
.design/tokens/                   # Design tokens (colors, spacing, typography, etc.)
.design/extracted-code/           # Component code extracted from Figma
STYLES.md                         # Brand guidelines
```

### Export Package (if exists)
```
.design/bumba-design-director/design-direction-plan/
├── README.md                     # Quick start
├── prompts/                      # Pre-built prompts for implementation
│   ├── one-shot-prompt.md
│   └── incremental-prompts/
├── instructions/
│   ├── implementation-guide.md
│   ├── design-assets.md
│   └── testing-guide.md
└── specifications/               # Copied specs
```

### Handoff Manifest
```
specs/HANDOFF.md                  # THE KEY FILE — read this first after overview
```

### Project Config
```
.claude/project-config.json       # Project configuration (template, mode, integrations)
docs/prd/                         # PRD documents
```

Report inventory:
```
Spec Inventory
══════════════

Found:
  ✓ product-overview.md
  ✓ product-roadmap.md
  ✓ data-model/types.ts
  ...

Missing:
  ✗ shell/spec.md
  ✗ sections/auth/spec.md
  ...

Handoff manifest: {Found / Not found}
Export package: {Found / Not found}
```

## Step 2: Read the Handoff Manifest

If `specs/HANDOFF.md` exists, this is your primary orientation document. Read it completely.

It contains:
- **Readiness score** — how complete the specs are
- **Flagged items** — decisions that need the planning env's input (DO NOT proceed on these without raising them)
- **Delegated decisions** — decisions you make, with constraints from the planning env
- **Resolved items** — questions already answered in the specs
- **Quick start** — reading order for specs

**If no handoff manifest exists**, proceed with Step 3 but flag this: the planning env should run `/handoff-prepare` first. You can still read specs, but you'll need to identify gaps yourself.

## Step 3: Build Mental Model

Read specs in this order:

1. **`product-overview.md`** — Understand WHAT and WHY
2. **`data-model/types.ts`** — Understand the entity shapes (this is the most implementation-relevant artifact)
3. **`data-model/data-model.md`** — Understand relationships and constraints
4. **`product-roadmap.md`** — Understand sections and priority
5. **`shell/spec.md`** — Understand navigation and routing
6. **Section specs** in roadmap priority order
7. **`STYLES.md`** and design tokens — Understand visual constraints

After reading, produce a one-paragraph summary of what you're building. This validates your understanding.

## Step 4: Review Delegated Decisions

If the handoff manifest has DELEGATED items, review each one:

For each delegated decision:
1. Read the constraint from the planning env
2. Accept the default OR override with a better choice (document why)
3. Record your decision

Create or update `specs/DECISIONS.md`:

```markdown
# Execution Decisions
Generated: {date}

## Accepted Defaults
- [{Category}] {Question}: Accepted — {constraint}

## Overridden Defaults
- [{Category}] {Question}: Changed to {your decision}
  - Planning env suggested: {original constraint}
  - Reason: {why you overrode}

## Open Questions (Need Planning Env Input)
- [{Category}] {Question}: {what you need to know and why}
```

## Step 5: Check for Flagged Blockers

If the handoff manifest has FLAGGED items:

```
⚠ Handoff has {N} flagged items that need decisions from the planning env.

Flagged:
1. [{Category}] {Question}
2. [{Category}] {Question}

Options:
A) Proceed with assumptions (risky — may need rework)
B) Open GitHub issues for each flagged item (recommended)
C) Skip flagged sections and build what's unblocked
```

If proceeding with assumptions, document them clearly in `specs/DECISIONS.md` under a "ASSUMPTIONS (Unconfirmed)" section.

If opening issues, create one issue per flagged item with label `design-question`:

```
Title: [Design Decision Needed] {Question}
Body:
The execution environment needs a decision on:

**Question:** {question}
**Category:** {category}
**Impact:** {what can't be built without this}
**Options:** {2-3 possibilities}
**Current assumption:** {what we'll build if no response}

Label: design-question
```

## Step 6: Generate Execution Plan

Based on the specs, create an execution plan. Follow the roadmap's section priority.

```markdown
# Execution Plan
Generated: {date}

## Build Order

### Phase 0: Foundation
- [ ] Initialize project (framework, package manager, linting)
- [ ] Set up database schema from `types.ts`
- [ ] Configure auth (based on delegated decision or spec)
- [ ] Set up CI/CD pipeline

### Phase 1: {First Priority Section from Roadmap}
- [ ] API endpoints for {section} entities
- [ ] Database queries and business logic
- [ ] Frontend pages/components per section spec
- [ ] Tests for critical paths from user flows

### Phase 2: {Second Priority Section}
...

### Phase N: Integration & Polish
- [ ] Cross-section navigation (per shell spec)
- [ ] Error handling across all sections
- [ ] Performance optimization
- [ ] End-to-end tests for complete user flows

## Tech Stack Decisions
- Framework: {from project config or delegated decision}
- Database: {from delegated decision}
- ORM: {from delegated decision}
- Auth: {from delegated decision}
- Hosting: {from delegated decision}
```

## Step 7: Begin Execution

If a specific section was requested via args, start there. Otherwise, start with Phase 0 (Foundation).

For each phase:

1. **Read the relevant section spec** completely before writing code
2. **Check sample data** (`data.json`) if it exists — this tells you what real data looks like
3. **Reference `types.ts`** for all entity shapes — do not invent fields
4. **Follow user flows** from the section spec to determine API endpoints needed
5. **Check design tokens** before implementing any UI

### The Negotiation Protocol

When you encounter something the specs don't cover:

**If it's a backend/infrastructure decision** (database indexing, caching strategy, error codes):
→ Decide yourself. Document in `specs/DECISIONS.md`.

**If it's a product/design decision** (what happens when X, should users see Y):
→ Check `specs/HANDOFF.md` delegated decisions first.
→ If not covered, document your assumption in `specs/DECISIONS.md` under "ASSUMPTIONS (Unconfirmed)".
→ If it's high-impact, open a GitHub issue with label `design-question`.

**If it's a frontend implementation detail** (component structure, state management):
→ Decide yourself unless design tokens or component code constrain the choice.

### Progress Reporting

After completing each phase, update `specs/PROGRESS.md`:

```markdown
# Build Progress
Last updated: {date}

## Phase 0: Foundation ✓
- [x] Project initialized (Next.js 15, TypeScript)
- [x] Database schema (Prisma, PostgreSQL)
- [x] Auth (NextAuth.js, JWT)
- [x] CI/CD (GitHub Actions)

## Phase 1: {Section Name} — In Progress
- [x] API: GET /api/products
- [x] API: GET /api/products/:id
- [ ] API: POST /api/products
- [ ] Frontend: Product list page
- [ ] Frontend: Product detail page
- [ ] Tests: Product CRUD

## Decisions Made
- See specs/DECISIONS.md

## Questions for Planning Env
- See open issues with label `design-question`
```

## Communication Back to Planning Env

All communication happens through the shared repo:

| Channel | Purpose | Format |
|---------|---------|--------|
| `specs/DECISIONS.md` | Execution decisions + assumptions | Markdown |
| `specs/PROGRESS.md` | Build progress reporting | Markdown checklist |
| GitHub Issues (`design-question`) | Questions that need planning env input | Issue template |
| Pull Requests | Code ready for review | PR with description |
| `specs/HANDOFF.md` | Updated by planning env only | Read-only for execution |

**Never modify** files owned by the planning env:
- `.design/bumba-design-director/product/*` (specs)
- `.design/tokens/*` (design tokens)
- `STYLES.md` (brand guidelines)
- `specs/HANDOFF.md` (handoff manifest)

**You own:**
- `src/`, `tests/`, `infra/`, `migrations/`
- `specs/DECISIONS.md`, `specs/PROGRESS.md`
- GitHub issues with `design-question` label
- Implementation PRs

## Error Handling

**No specs found:**
```
Error: No specification artifacts found.

This repo hasn't been through the planning/design phase yet.
The planning environment needs to run:
  /design-director:design-director-init
  /design-director:design-director-vision
  /design-director:design-director-roadmap
  /design-director:design-director-data-model

Then push to this repo.
```

**Incomplete specs (no handoff manifest, missing critical files):**
```
Warning: Specs are incomplete. Missing:
  - {list of missing files}

You can proceed, but expect to make more assumptions.
All assumptions will be documented in specs/DECISIONS.md.

The planning env should run /handoff-prepare to generate a proper manifest.
```

**Conflicting specs:**
```
Warning: Conflicting information detected.

data-model/types.ts defines User.role as string
sections/admin/spec.md references roles: admin, editor, viewer (enum)

Resolution: Using enum ['admin', 'editor', 'viewer'] (more specific wins)
Documented in specs/DECISIONS.md
```
