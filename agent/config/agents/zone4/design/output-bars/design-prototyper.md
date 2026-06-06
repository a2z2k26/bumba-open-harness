<!-- status: current — authored 2026-05-18 (#2131 / Sprint 5d.02) -->

# Output Quality Bar — `design-prototyper`

**Specialist:** design-prototyper
**Paired workflow:** `design.component_spec_to_implementation` (#2171, Sprint 5d.05)
**Authored:** 2026-05-18

---

## 1. What the specialist produces

A working prototype: clickable Figma prototype, runnable code prototype (React/Vue/Svelte/SwiftUI/Flutter per target framework), or framework-agnostic HTML/CSS demo. Saved at `docs/design/prototypes/<date>-<surface>.md` linking to the prototype source.

The prototype demonstrates the interaction reality of a specification — not pixel-perfection, but FEEL-correctness.

### Required output sections

1. **Target description** — what's being prototyped, what specification it implements, what framework
2. **Validation goal** — what question does this prototype answer? ("Does this hover behavior feel right?" / "Does the multi-step form maintain context across pages?")
3. **What's real vs faked** — explicit: animations are real / data is mocked / network calls are stubbed / etc.
4. **Validation findings** — what the prototype confirmed; what it surfaced as needing revision
5. **Production gap** — what would change from prototype to production implementation (real auth, real data, real network, real responsive breakpoints, etc.)

---

## 2. The bar (what's acceptable)

**A design prototype is acceptable when:**

- **Validation goal stated.** A prototype without a question is decoration. "Does X feel right?" must be explicit.
- **Real vs faked is explicit.** Reviewers know what aspect of the prototype is load-bearing vs scaffold.
- **Interaction reality, not pixel perfection.** Prototype's job is feel — hover/transition/state-change correctness. Pixel-perfect Figma is ui-designer's domain.
- **Production gap named.** Reviewer can answer "what would change for production?" without asking.
- **Framework-appropriate.** If the target ships in React, the prototype is React (or framework-agnostic). Not "I prototyped it in Figma because I prefer Figma."

**Specifically NOT acceptable:**

- Prototype shipped without a validation question
- Faked-vs-real ambiguous; reviewer thinks animation is real when it's a static gif
- Pixel-perfection prioritized over interaction feel
- Production gap glossed ("just wire it up")
- Wrong framework choice (Figma prototype for a CSS animation question)

---

## 3. Failure modes (what degraded output looks like)

| Mode | Symptom | How to catch |
|---|---|---|
| **Decorative prototype** | Beautiful but no validation question | Section 2 must declare the question |
| **Reality ambiguity** | Reviewer can't tell what's stubbed vs real | Section 3 must explicitly list each |
| **Pixel-pursuit** | Hours spent on color accuracy of mocked state instead of interaction correctness | Validation goal should drive effort allocation |
| **Production gap silent** | Operator approves prototype; engineering discovers 80% of the work was scaffolded | Section 5 must enumerate what changes |
| **Framework mismatch** | Hover behavior prototyped in Figma (which has limited hover fidelity) when target is web | Framework choice rationale required if not target-native |

---

## 4. Recent specialist invocations

> Operator-fill table populated post-invocation.

| Date | Target | Validation question | Answer found? | Notes |
|---|---|---|---|---|
| YYYY-MM-DD | _surface_ | _question_ | _yes / partial_ | _what was learned_ |

---

## 5. Specialist performance verdict

> **PENDING** until specialist has shipped ≥3 real prototypes. Verdict slot:

- [ ] Healthy — validation-driven, real/faked explicit, production gap named
- [ ] Degraded — prototypes ship but validation question or production gap gets thin
- [ ] Stale — operator stopped commissioning prototypes (going direct to implementation)

Date recorded: _____________
