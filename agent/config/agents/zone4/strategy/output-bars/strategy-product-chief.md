<!-- status: current — authored 2026-05-18 (#2134 / Sprint 5s.02) -->

# Output Quality Bar — `strategy-product-chief`

**Specialist:** strategy-product-chief
**Paired workflow:** `strategy.prd_authoring` (#2184, Sprint 5s.03)
**Authored:** 2026-05-18

---

## 1. What the specialist produces

A PRD (Product Requirements Document) saved under `docs/prds/<date>-<topic>.md` (or Notion equivalent per operator-decision per invocation), plus a Discord summary on completion and a GitHub issue linking the PRD location.

### Required output sections

1. **Problem statement** — who the user is, what they're trying to do, what's blocking them, why, and how it makes them feel (empathy-driven framework)
2. **User value** — what changes for the user when this ships; ranked outcomes
3. **Success criteria** — measurable outcomes that determine ship/no-ship; leading + lagging metrics
4. **Scope boundaries** — explicitly IN + explicitly OUT; what we are NOT building
5. **Open questions** — what the PRD doesn't answer; operator decisions still required

---

## 2. The bar (what's acceptable)

**A PRD is acceptable when:**

- **Problem stated from user perspective.** Not "we need to build X". The problem the user has when X doesn't exist.
- **Success criteria measurable.** "Users adopt this" is not measurable. "30% of weekly active operators invoke the feature within 14 days of release" is.
- **Scope explicitly bounded.** OUT section is as concrete as IN. Future-iteration items named.
- **Open questions named.** Every PRD has them; pretending otherwise hides risk.
- **One owner-decision per question.** Open questions identify who answers (operator / design-chief / engineering-chief) — not "TBD".

**Specifically NOT acceptable:**

- Problem stated from builder's perspective ("we need to add...")
- Success criteria that are descriptions instead of measurements
- Scope without an OUT section (every scope drifts without one)
- "TBD" open questions without owners
- Mixing requirements (what to build) with implementation (how to build) — that's requirement-engineer's domain downstream

---

## 3. Failure modes

| Mode | Symptom | How to catch |
|---|---|---|
| **Builder-perspective problem** | "We need to add X feature" instead of "user wants to Y, can't because Z" | Section 1 must start with user/persona, not the team |
| **Unmeasurable success** | "Better UX", "increased engagement" without numbers | Each success criterion must be checkable; leading vs lagging declared |
| **Scope drift** | IN section detailed; OUT section absent or one line | OUT section must be proportional to IN |
| **TBD-as-answer** | Open questions list 6 items, all "TBD" without owner | Each open question must name the decision-owner |
| **Implementation creep** | PRD specifies React components, SQL schemas — that's downstream territory | Requirements describe what; implementation describes how. Keep separated. |
| **No leading metric** | All success criteria are lagging (revenue, retention) — no early signal | Mix of leading + lagging required so you know if you're on track before lagging metrics confirm |

---

## 4. Recent specialist invocations

> Operator-fill table populated post-invocation. The `strategy.prd_authoring` workflow (#2184) emits Discord summaries; record here.

| Date | PRD topic | Success criteria measurable? | Scope OUT explicit? | Open questions owned? | Notes |
|---|---|---|---|---|---|
| YYYY-MM-DD | _topic_ | _yes / partial_ | _yes / partial_ | _yes / TBD-count_ | _what shipped, what to refine_ |

---

## 5. Specialist performance verdict

> **PENDING** until specialist has authored ≥3 real PRDs.

- [ ] Healthy — user-perspective problems, measurable success, bounded scope, owned questions
- [ ] Degraded — PRDs land but success metrics or scope OUT drift
- [ ] Stale — operator working around chief with ad-hoc PRDs

Date recorded: _____________
