<!-- status: current — authored 2026-05-18 (#2131 / Sprint 5d.02) -->

# Output Quality Bar — `design-interaction-designer`

**Specialist:** design-interaction-designer
**Paired workflow:** `design.user_journey_to_wireframes` (#2173, Sprint 5d.07)
**Authored:** 2026-05-18

---

## 1. What the specialist produces

An interaction artifact: wireframes, flow diagrams, hotspots, state-transition maps, micro-interaction specs, or motion timing tables. Saved at `docs/design/interactions/<date>-<surface>.md` with Figma/source-file references.

### Required output sections

1. **Target description** — what flow/surface/component, which user journey it lives in
2. **States enumerated** — every state the surface can be in, with transition triggers
3. **Interaction inventory** — per interaction: input → feedback → result; timing where it matters
4. **Edge cases** — what happens at empty / error / loading / offline / first-use / power-user states
5. **Motion intent** — for each animation, what state/hierarchy/intent it communicates (no decorative motion)

---

## 2. The bar (what's acceptable)

**An interaction artifact is acceptable when:**

- **States complete.** Every state the user can reach is enumerated. Empty, error, loading, first-use, power-user states are explicit, not assumed-default.
- **Transitions complete.** For every state pair (A → B), the trigger is named. No mystery transitions.
- **Feedback paired with input.** Every operator/user action has a visible response within 100ms (or explicit "this takes longer" affordance).
- **Edge cases addressed.** What does this look like with 0 items? With 10,000? Network offline? Operator-halted?
- **Motion has intent.** Each animation declares what it communicates: state change, hierarchy emphasis, attention direction. Decoration is forbidden.
- **Power-user paths exist.** Keyboard shortcuts, batch operations, quick-jumps — not just the click-through happy path.

**Specifically NOT acceptable:**

- "Happy path only" — states-missing for empty/error/loading is the canonical degraded mode
- Untriggered transitions (state appears in diagram with no arrow leading in)
- Input without feedback ("clicks the button — then..." with no visible response)
- Motion-for-motion's-sake (fade-ins on things that should snap)
- No keyboard or power-user consideration

---

## 3. Failure modes (what degraded output looks like)

| Mode | Symptom | How to catch |
|---|---|---|
| **Happy-path only** | State diagram has 3 states; reality has 8 | Edge-cases section must enumerate empty/error/loading/offline/first-use/power-user |
| **Mystery transitions** | State B exists in diagram with no labeled trigger leading to it | Every state needs at least one incoming transition labeled |
| **Silent input** | "User clicks X" without describing visible response | Each interaction in Section 3 must pair input with feedback |
| **Decorative motion** | Animations on elements that don't change meaning | Motion-intent section must justify each animation |
| **Power-user blind** | No keyboard shortcuts, no batch ops, no quick-jumps documented | Section 4 (edge cases) must include power-user state |
| **Magic loading** | "Loading..." spinners without timing context (sub-100ms vs multi-second) | Loading state should declare expected duration + affordance for long waits |

---

## 4. Recent specialist invocations

> Operator-fill table populated post-invocation.

| Date | Surface | States enumerated | Edge cases covered? | Notes |
|---|---|---|---|---|
| YYYY-MM-DD | _surface_ | _N_ | _yes / partial_ | _what works, what was missed_ |

---

## 5. Specialist performance verdict

> **PENDING** until specialist has shipped ≥3 real interaction artifacts. Verdict slot:

- [ ] Healthy — states complete, transitions traceable, edge cases covered, motion purposeful
- [ ] Degraded — happy path solid but edge cases skipped OR power-user paths missing
- [ ] Stale — operator working around interaction-designer with direct frontend dev

Date recorded: _____________
