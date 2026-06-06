---
name: handoff-prepare
description: Validate that a project spec is complete and ready for handoff to the execution environment. Runs a comprehensive checklist against the 60+ questions an execution agent will ask, flags gaps, and produces a handoff manifest.
args:
  - name: scope
    description: What to validate - "full" (all sections) or a specific section ID
    required: false
user-invokable: true
---

Validate that the current project's specifications are complete enough for a backend/execution agent to build from without asking questions. Produce a handoff manifest that the receiving agent can consume.

## Philosophy

The goal is NOT to answer every possible question. The goal is to make **ambiguity explicit**. Every gap should be either:
- **Resolved** (answer provided in the spec)
- **Delegated** (marked as "execution env decides" with constraints)
- **Flagged** (marked as "needs decision" — blocks handoff)

## Step 1: Locate Spec Artifacts

Scan for all specification artifacts in the project:

```
.design/bumba-design-director/product/
├── product-overview.md          # Vision, problems, features
├── product-roadmap.md           # Sections / feature areas
├── data-model/
│   ├── data-model.md            # Entity specs
│   └── types.ts                 # TypeScript interfaces
├── shell/
│   └── spec.md                  # Navigation, layout, routing
└── sections/
    └── {section-id}/
        ├── spec.md              # User flows, UI requirements
        ├── data.json            # Sample data
        └── screen-specs/        # Detailed screen specs
```

Also check for:
- `.design/tokens/` — design tokens
- `.design/extracted-code/` — component code
- `STYLES.md` — brand guidelines
- `.claude/project-config.json` — project configuration
- `docs/prd/` — PRD documents

Report what exists and what's missing.

## Step 2: Run the 8-Category Checklist

For each category, check whether the specs answer the critical questions. Score each as: RESOLVED, DELEGATED, or FLAGGED.

### Category 1: Data & API Contracts

Check the data model and section specs for:

| Question | Where to Find Answer | Status |
|----------|---------------------|--------|
| Entity shapes (fields, types, nullability) | `data-model/types.ts` | ? |
| Required vs optional fields | `data-model/types.ts` (null unions) | ? |
| Pagination model | Section specs or shell spec | ? |
| Sort/filter options | Section specs | ? |
| Entity relationships | `data-model/data-model.md` | ? |
| Max list lengths / payload sizes | Section specs | ? |
| Computed/derived fields | `data-model/types.ts` | ? |
| Real-time requirements | Section specs | ? |

**Auto-resolve:** If `types.ts` exists with complete interfaces, mark entity shapes as RESOLVED.
**Auto-delegate:** If pagination/sort/filter are not specified, mark as DELEGATED with constraint: "Use cursor-based pagination, default page size 20."
**Flag:** If no data model exists at all, FLAGGED — blocks handoff.

### Category 2: Authentication & Authorization

Check product overview and section specs for:

| Question | Where to Find Answer | Status |
|----------|---------------------|--------|
| Auth model (JWT, session, OAuth) | Product overview or dedicated auth section | ? |
| Permission model (RBAC, per-resource) | Section specs or data model | ? |
| Public vs authenticated routes | Shell spec (routing) | ? |
| Multi-tenancy model | Data model (org/team entities) | ? |
| Unauthorized behavior | Section specs (error states) | ? |

**Auto-delegate:** If not specified, mark as DELEGATED with constraint: "Use JWT with refresh tokens. All routes authenticated by default unless section spec says 'public'."
**Flag:** If multi-tenancy is implied by the data model but not specified, FLAGGED.

### Category 3: State & Edge Cases

For each section spec, check for:

| Question | Where to Find Answer | Status |
|----------|---------------------|--------|
| Empty states | Section spec UI requirements | ? |
| Loading states | Section spec UI requirements | ? |
| Error states | Section spec UI requirements | ? |
| Partial failure handling | Section spec | ? |
| Boundary cases (0, 1, many, max) | Section spec or data model | ? |
| Character limits | Data model attributes | ? |
| Delete behavior (soft/hard) | Data model or section spec | ? |
| Dependent data on delete | Data model relationships | ? |

**Auto-delegate:** If empty/loading/error states are not specified per-section, mark as DELEGATED with constraint: "Use skeleton loaders for loading, inline error with retry for errors, illustrated empty state with CTA for empty."
**Flag:** If delete behavior is ambiguous for entities with relationships, FLAGGED.

### Category 4: Frontend Implementation

Check shell spec and section specs for:

| Question | Where to Find Answer | Status |
|----------|---------------------|--------|
| Routing structure | Shell spec | ? |
| Component library | Project config or STYLES.md | ? |
| Form validation approach | Section specs | ? |
| Optimistic vs pessimistic updates | Section specs | ? |
| Responsive breakpoints | STYLES.md or design tokens | ? |
| Dark mode support | Design tokens | ? |

**Auto-resolve:** If shell spec defines routes, mark routing as RESOLVED.
**Auto-resolve:** If design tokens exist, mark breakpoints and dark mode as RESOLVED.
**Auto-delegate:** If not specified, mark form validation as DELEGATED with constraint: "Client-side validation with zod schemas matching TypeScript types. Server revalidates on submit."

### Category 5: Integration & Third-Party

Check product overview and section specs for:

| Question | Where to Find Answer | Status |
|----------|---------------------|--------|
| Payment provider and flow | Section spec (if billing exists) | ? |
| Email service | Section spec (if notifications exist) | ? |
| File storage / upload | Section spec (if uploads exist) | ? |
| Analytics events | Not typically in specs | ? |
| OAuth providers | Section spec (if auth section exists) | ? |
| Notification channels | Section spec | ? |

**Auto-delegate:** If a section involves payments but no provider is specified, mark as DELEGATED with constraint: "Use Stripe. Checkout Session for one-time, Subscriptions for recurring."
**Auto-delegate:** Analytics events are always DELEGATED: "Execution env defines events based on user flows. Track all CTA clicks and page views at minimum."

### Category 6: Performance & Scale

Check product overview for:

| Question | Where to Find Answer | Status |
|----------|---------------------|--------|
| Expected data volume | Product overview | ? |
| Search requirements | Section specs | ? |
| Caching strategy | Not typically in specs | ? |
| Acceptable latency | Not typically in specs | ? |
| Rate limiting | Not typically in specs | ? |

**Auto-delegate all** with constraints:
- Data volume: "Design for 10K-100K records per entity unless spec says otherwise"
- Caching: "Cache GET responses for 60s. Invalidate on mutations."
- Latency: "P95 < 500ms for API responses. P95 < 3s for page loads."
- Rate limiting: "100 req/min per authenticated user. 20 req/min for unauthenticated."

### Category 7: DevOps & Deployment

Check project config for:

| Question | Where to Find Answer | Status |
|----------|---------------------|--------|
| Target infrastructure | `.claude/project-config.json` | ? |
| Database choice | Project config or data model | ? |
| Migration strategy | Not typically in specs | ? |
| Feature flags | Not typically in specs | ? |
| CI/CD expectations | Project config | ? |

**Auto-delegate** with constraints if not specified:
- Infrastructure: "Execution env decides based on project complexity"
- Database: "PostgreSQL unless data model suggests otherwise"
- Migrations: "Use ORM migrations (Prisma/Drizzle for Node, Alembic for Python)"

### Category 8: Business Logic

Check PRD and product overview for:

| Question | Where to Find Answer | Status |
|----------|---------------------|--------|
| Billing model | PRD or product overview | ? |
| Plan limits | PRD or product overview | ? |
| Trial flow | Section spec | ? |
| Invitation flow | Section spec | ? |
| Audit trail requirements | Product overview | ? |
| Compliance requirements | Product overview | ? |

**Flag** any billing/plan/trial questions that are relevant but unanswered — these are business decisions that can't be delegated.

## Step 3: Generate Handoff Manifest

Create `specs/HANDOFF.md` in the repo root with the following structure:

```markdown
# Handoff Manifest
Generated: {date}
Project: {project name from product-overview}

## Readiness Score
{RESOLVED count} / {total questions checked} resolved
{DELEGATED count} delegated with constraints
{FLAGGED count} flagged — need decisions before handoff

## Flagged Items (Blocks Handoff)
{For each FLAGGED item:}
### [{Category}] {Question}
**Why it matters:** {impact on execution}
**Options:** {2-3 possible answers}
**Decision needed from:** Planning env

## Delegated Decisions (Execution Env Decides)
{For each DELEGATED item:}
### [{Category}] {Question}
**Constraint:** {the guardrail}
**Default:** {what to do if no preference}

## Resolved Items
{Summary count per category}

## Spec Inventory
{List of all spec files with paths and last-modified dates}

## Quick Start for Execution Env
1. Read `product-overview.md` for context
2. Read `data-model/types.ts` for entity shapes
3. Read `shell/spec.md` for routing
4. Read section specs in priority order from `product-roadmap.md`
5. Review DELEGATED decisions above — override any you disagree with
6. Start building from the data layer up
```

## Step 4: Report Results

Display a summary:

```
Handoff Readiness Check
═══════════════════════

✓ {N} questions RESOLVED (answers in specs)
◐ {N} questions DELEGATED (execution env decides, with constraints)
✗ {N} questions FLAGGED (need your decision)

{If FLAGGED > 0:}
⚠ {N} items need your decision before handoff.
  Review specs/HANDOFF.md and resolve flagged items.

{If FLAGGED == 0:}
✓ Ready for handoff!
  specs/HANDOFF.md contains the manifest.
  Push to the shared repo and the execution env can begin.
```

## IMPORTANT

- Do NOT fabricate answers. If a spec doesn't address something, flag or delegate it.
- Do NOT modify existing specs. This skill only reads and reports.
- Delegation constraints should be sensible defaults, not arbitrary choices.
- The manifest is the CONTRACT. The execution env will read it as ground truth.
- Be conservative with "RESOLVED" — only mark it if the spec genuinely answers the question.
