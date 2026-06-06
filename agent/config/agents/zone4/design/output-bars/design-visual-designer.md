<!-- status: current — authored 2026-05-18 (#2131 / Sprint 5d.02) -->

# Output Quality Bar — `design-visual-designer`

**Specialist:** design-visual-designer
**Paired workflow:** `design.brand_consistency_check` (#2172, Sprint 5d.06)
**Authored:** 2026-05-18

---

## 1. What the specialist produces

A visual artifact (composition, treatment, mood study, brand application, or polish pass) plus a markdown rationale saved under `docs/design/<date>-visual-<target>.md` linking to the source files.

The output reflects operator-level taste — distinctive, bold, intentional. Not generic-AI-aesthetic. Per operator doctrine: **"generic AI aesthetics are the enemy"**.

### Required output sections (in the rationale doc)

1. **Target description** — what was designed, what feel/mood/brand position is being expressed
2. **Visual decisions** — typography choices (faces, weights, scale), color choices (palette, contrast), spatial rhythm, motion treatment
3. **What this is NOT** — explicit anti-patterns avoided (generic SaaS template, default Tailwind starter, generic AI gradient palette, etc.)
4. **Brand alignment** — how this fits / extends the existing brand voice; what tokens it uses vs introduces
5. **Production-readiness** — every visual decision is implementable in the target framework with the current design-system tokens, OR new tokens are explicitly proposed

---

## 2. The bar (what's acceptable)

**A visual design artifact is acceptable when:**

- **Distinctive.** Reads like it could only have come from this team. Not "looks like every other AI app".
- **Intentional.** Every choice (font, color, spacing, motion) has a stated reason in the rationale. Not "felt right".
- **Token-aware.** Uses existing design-system tokens where they exist; new tokens are PROPOSED with rationale, not silently introduced.
- **Motion is purposeful.** Animations communicate state/hierarchy/intent — not decoration. Frames have easing curves chosen, not defaulted.
- **Typography is calibrated.** Type scale uses ≤3 sizes per surface; weights deliberate (not "let's add bold here"); line-height + letter-spacing tuned for the specific face.
- **Color is restrained.** Palette per surface ≤5 colors; contrast verified against WCAG (accessibility-specialist's domain, but visual-designer owns the choice).
- **Production-feasible.** Every visual decision can be implemented; engineering-frontend-developer doesn't have to argue against unbuildable specs.

**Specifically NOT acceptable:**

- Generic SaaS aesthetic ("looks like every other app")
- Decisions without rationale ("just felt right")
- Hardcoded values when tokens exist
- Motion-for-motion's-sake (animating things that should be static)
- Type that defaults to 16px / 400 / 1.5 without thought
- Palettes that drift into 9-color rainbows
- Specs that engineering can't build with current tools

---

## 3. Failure modes (what degraded output looks like)

| Mode | Symptom | How to catch |
|---|---|---|
| **Generic drift** | Output reads like the AI's default suggestion — gradient backgrounds, rounded corners, generic icon set | Operator gut check: "does this look like Bumba, or like a Replit starter?" |
| **Unjustified decisions** | Rationale doc skipped or "looks nice" — no actual reasons | Section 2 (Visual decisions) must list each major decision + reason |
| **Token silent introduction** | New design token used in the artifact but not proposed in the rationale | Cross-check tokens used against the existing design-system; new ones must be flagged + named |
| **Decorative motion** | Loading spinners spin even when no load happening; entrances animate that should snap | Each animation has a rationale: what state/hierarchy/intent it communicates |
| **Type laziness** | Sample uses 3+ font sizes within one component, no apparent scale rationale | Type scale per surface ≤3 sizes with explicit role per size |
| **Color drift** | Palette grows past 5 colors per surface without rationale | Count colors actually used; demand rationale beyond 5 |
| **Unbuildable spec** | Visual treatment depends on a CSS feature the target framework doesn't ship | Engineering-frontend-developer should validate feasibility post-spec |

---

## 4. Recent specialist invocations

> Operator-fill table populated post-invocation.

| Date | Target | Distinctive? | Token-clean? | Motion-purposeful? | Notes |
|---|---|---|---|---|---|
| YYYY-MM-DD | _surface_ | _yes / generic-drift_ | _yes / new-token-N_ | _yes / decorative-N_ | _what worked, what to refine_ |

---

## 5. Specialist performance verdict

> **PENDING** until specialist has shipped ≥3 real visual artifacts. Verdict slot:

- [ ] Healthy — distinctive, intentional, token-aware, production-feasible
- [ ] Degraded — visual quality holds but rationale gets thin OR motion drifts decorative
- [ ] Stale — generic-drift creeping in; operator overriding visual-designer choices

Date recorded: _____________
