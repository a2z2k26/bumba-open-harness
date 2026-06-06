<!-- status: current — authored 2026-05-18 (#2134 / Sprint 5s.02) -->

# Output Quality Bar — `strategy-requirement-engineer`

**Specialist:** strategy-requirement-engineer
**Paired workflow:** `strategy.prd_authoring` (#2184, Sprint 5s.03)
**Authored:** 2026-05-18

---

## 1. What the specialist produces

A requirements artifact: structured requirement list, user stories, acceptance criteria sets, or epic-breakdown. Saved under `docs/prds/<prd-id>/requirements.md` (paired with the parent PRD).

### Required output sections

1. **Source PRD reference** — which PRD these requirements derive from (commit/version)
2. **Requirements** — each requirement: ID, statement, type (functional / non-functional / constraint), acceptance criteria, traceability to PRD section
3. **Atomicity check** — each requirement does ONE thing; compound requirements explicitly split
4. **Testability** — each requirement has at least one testable assertion (not "good UX", but "page loads under 200ms")
5. **Traceability matrix** — requirement → PRD section it derives from → downstream implementation reference (filed once implementation starts)

---

## 2. The bar (what's acceptable)

**A requirements artifact is acceptable when:**

- **Testable.** Each requirement has at least one assertion a test can verify. "The form validates email" is testable; "the form is user-friendly" is not.
- **Atomic.** Each requirement does one thing. "Login form with email + SSO + 2FA" = 3 requirements, not 1.
- **Traceable.** Every requirement cites the PRD section it derives from; implementation cites the requirement back.
- **Typed.** Functional / non-functional / constraint — type matters for downstream estimation + verification.
- **Acceptance criteria precede implementation.** AC are written BEFORE the code; not after as documentation.

**Specifically NOT acceptable:**

- "User-friendly", "performant", "secure" as requirements (untestable)
- Compound requirements that smuggle in multiple changes
- Requirements without PRD-section traceability
- AC written post-implementation as documentation
- Mixing requirements (what) with implementation (how) inline

---

## 3. Failure modes

| Mode | Symptom | How to catch |
|---|---|---|
| **Untestable AC** | "Should feel fast", "should be intuitive" | Each AC must be verifiable by a specific assertion |
| **Compound requirement** | One requirement "supports email + SSO + 2FA login" | Single-verb test: requirement should be expressible as one action |
| **Orphan requirement** | Requirement listed but no PRD section cited | Traceability matrix must be complete |
| **Implementation leakage** | "Use React Hook Form for validation" appears in requirements | Implementation choices belong downstream of requirements |
| **AC written post-hoc** | AC reads like a test that already passes | AC must be written before the code; check via commit history if needed |
| **Type missing** | Requirements listed without functional/non-functional/constraint labels | Type column required; defaults forbidden |

---

## 4. Recent specialist invocations

| Date | Source PRD | Requirement count | All testable? | Notes |
|---|---|---|---|---|
| YYYY-MM-DD | _PRD ref_ | _N_ | _yes / N-failed_ | _what shipped, what to refine_ |

---

## 5. Specialist performance verdict

> **PENDING** until specialist has produced ≥3 real requirement sets.

- [ ] Healthy — testable, atomic, traceable, typed
- [ ] Degraded — requirements clear but AC testability drifts
- [ ] Stale — operator skipping requirements layer (going PRD → implementation)

Date recorded: _____________
