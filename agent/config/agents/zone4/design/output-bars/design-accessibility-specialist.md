<!-- status: current — authored 2026-05-18 (#2131 / Sprint 5d.02) -->

# Output Quality Bar — `design-accessibility-specialist`

**Specialist:** design-accessibility-specialist
**Paired workflow:** `design.accessibility_pass` (#2170, Sprint 5d.04)
**Authored:** 2026-05-18

---

## 1. What the specialist produces

A markdown accessibility-pass report saved under `docs/design/accessibility/<date>-<target>.md`, plus a Discord summary with verdict + finding count.

This specialist operates at **design-time** (before code ships), distinct from `qa-accessibility-tester` who operates at **post-ship audit time**. Design-accessibility-specialist's job is to catch a11y issues IN the design artifact (Figma file, component spec, journey wireframe) before they get implemented.

### Required output sections

1. **Target description** — what design artifact was reviewed, what surface it lands on
2. **Inclusive-design checks** — keyboard-navigable structure, focus order, screen-reader semantics implied by the design, color/contrast at design-token level
3. **Responsive / adaptive findings** — does this work at the target breakpoints; does text reflow correctly; do touch targets meet minimums on mobile
4. **WCAG-anticipated findings** — issues that WILL surface in qa-accessibility-tester's WCAG 2.1 AA audit once shipped, flagged here as catch-before-build
5. **Recommendations to ui-designer / visual-designer** — concrete changes to make in the design before handoff

---

## 2. The bar (what's acceptable)

**A design-time accessibility pass is acceptable when:**

- **Design-stage, not post-ship.** This specialist catches issues in Figma/spec, not in shipped artifacts. Post-ship a11y is qa-accessibility-tester's job (distinct workflow, distinct bar).
- **Token-level contrast checks.** Color tokens checked against WCAG AA (4.5:1 for normal text, 3:1 for large) BEFORE the design ships; failures flagged with specific token + suggested replacement.
- **Touch target sizing verified.** Interactive elements meet 44×44 (iOS) / 48×48 (Material) minimums; flagged in design, not discovered post-ship.
- **Focus order implied by structure.** Wireframe / spec reveals logical focus order; out-of-order layouts get caught before implementation.
- **Recommendations are concrete + addressed to the source specialist.** "ui-designer: change button color from `color/brand/secondary` to `color/brand/primary` for 4.5:1 contrast on this surface."
- **Adaptive considered.** Breakpoint changes don't break navigability or readability; explicit per-breakpoint check.

**Specifically NOT acceptable:**

- Post-ship findings (that's qa-accessibility-tester's lane)
- Generic recommendations ("improve a11y")
- Skipping contrast checks because "we'll test post-ship"
- Touch target failures left for engineering to discover
- Focus order silent

---

## 3. Failure modes (what degraded output looks like)

| Mode | Symptom | How to catch |
|---|---|---|
| **Post-ship-only findings** | Report references shipped code instead of design artifact | This specialist works AT design time; if reviewing shipped code, the wrong workflow was invoked |
| **Token-contrast skipped** | Design ships with token combos that fail WCAG; qa finds it later | Section 2 must explicitly check every interactive color combo |
| **Touch target glossed** | Mobile design has 32px buttons | Section 3 must measure interactive elements against platform minimums |
| **Focus order silent** | Wireframe shows complex layout; no focus-order discussion | Section 2 must comment on focus order implied by structure |
| **Generic recommendations** | "Improve accessibility" or "consider WCAG" without specifics | Each recommendation cites a specific element + specific change |
| **Breakpoint blind** | Desktop a11y checked; mobile / tablet skipped | Section 3 must cover each declared breakpoint |

---

## 4. Recent specialist invocations

> Operator-fill table populated post-invocation.

| Date | Target | Findings (caught-pre-build) | Recommended specialist | Notes |
|---|---|---|---|---|
| YYYY-MM-DD | _design artifact_ | _N_ | _ui-designer / visual-designer_ | _what was prevented from shipping_ |

---

## 5. Specialist performance verdict

> **PENDING** until specialist has reviewed ≥3 real design artifacts. Verdict slot:

- [ ] Healthy — catching a11y issues in design before they ship; recommendations actionable to source specialist
- [ ] Degraded — finds issues but recommendations vague OR breakpoint coverage incomplete
- [ ] Stale — operator working around accessibility-specialist (skipping design-time a11y pass)

Date recorded: _____________
